"""Reversible Claude Code configuration for verified native-Windows Git Bash."""

from __future__ import annotations

import copy
import json
import ntpath
import os
import stat
import tempfile
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

from .capabilities import (
    BASH,
    CapabilitySpec,
    CapabilityState,
    MachineState,
    acceptable_provider_executables,
    current_machine,
    detect_capability,
)
from .cooperative_cancellation import (
    _CancellationContext,
    _ForceAbort,
    _SigintBroker,
)
from .desired_state import desired_state_path


SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_PATH_LENGTH = 32767
SETTING_NAME = "CLAUDE_CODE_GIT_BASH_PATH"
_MUTATION_LOCK = threading.RLock()


class ClaudeCodeIntegrationError(RuntimeError):
    """Claude Code integration state cannot be safely understood or changed."""


class ClaudeCodeIntegrationRestorationError(ClaudeCodeIntegrationError):
    """A failed integration update could not confirm restoration."""

    def __init__(self, detail: str, backup_paths: tuple[Path, ...]) -> None:
        super().__init__(detail)
        self.backup_paths = backup_paths


class IntegrationOutcome(str, Enum):
    NO_CHANGES = "no-changes"
    REFUSED = "refused"
    UPDATED = "updated"


class IntegrationPhase(str, Enum):
    PREPARED = "prepared"
    ACTIVE = "active"
    REMOVING = "removing"
    REMOVED = "removed"


@dataclass(frozen=True)
class IntegrationResult:
    outcome: IntegrationOutcome
    settings_path: Path
    state_path: Path
    phase: IntegrationPhase | None
    backup_paths: tuple[Path, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class IntegrationStatus:
    settings_path: Path
    state_path: Path
    phase: IntegrationPhase | None
    current_value: str | None
    managed: bool


@dataclass(frozen=True)
class _Snapshot:
    exists: bool
    raw: bytes
    document: dict[str, Any]


DocumentParser = Callable[[bytes], dict[str, Any]]


def claude_settings_path(
    *,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve Claude Code's documented native-Windows user settings path."""

    env = os.environ if environment is None else environment
    configured = env.get("CLAUDE_CONFIG_DIR")
    if configured:
        if not PureWindowsPath(configured).is_absolute():
            raise ClaudeCodeIntegrationError(
                "CLAUDE_CONFIG_DIR must be an absolute Windows path"
            )
        return Path(configured) / "settings.json"
    if home is None:
        home_value = env.get("USERPROFILE")
        if not home_value:
            raise ClaudeCodeIntegrationError("USERPROFILE is unavailable")
        home = Path(home_value)
    if not PureWindowsPath(str(home)).is_absolute():
        raise ClaudeCodeIntegrationError("Windows user profile path is not absolute")
    return home / ".claude" / "settings.json"


def integration_state_path(
    *,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve Agent Tools' separate Claude Code integration ledger."""

    return (
        desired_state_path(
            platform_name="Windows",
            environment=environment,
            home=home,
        ).parent
        / "integrations"
        / "claude-code.json"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ClaudeCodeIntegrationError(f"duplicate JSON key: {name}")
        value[name] = item
    return value


def _parse_json(raw: bytes) -> object:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise ClaudeCodeIntegrationError(
            f"configuration is unreadable or corrupt: {error}"
        ) from error
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise ClaudeCodeIntegrationError("JSON container depth exceeds the limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _parse_settings(raw: bytes) -> dict[str, Any]:
    value = _parse_json(raw)
    if not isinstance(value, dict):
        raise ClaudeCodeIntegrationError("Claude Code settings must be a JSON object")
    environment = value.get("env")
    if "env" in value and (
        not isinstance(environment, dict)
        or any(
            not isinstance(name, str) or not isinstance(item, str)
            for name, item in environment.items()
        )
    ):
        raise ClaudeCodeIntegrationError(
            "Claude Code settings env must be an object of string values"
        )
    return value


def _valid_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_PATH_LENGTH
        and (PureWindowsPath(value).is_absolute() or Path(value).is_absolute())
    )


def _valid_git_bash_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_PATH_LENGTH
        and PureWindowsPath(value).is_absolute()
        and ntpath.basename(value).casefold() in {"bash.exe", "sh.exe"}
    )


def _parse_state(raw: bytes) -> dict[str, Any]:
    value = _parse_json(raw)
    required = {
        "schema_version",
        "phase",
        "settings_path",
        "settings_existed",
        "applied_value",
        "previous",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ClaudeCodeIntegrationError(
            "Claude Code integration state does not match schema v1"
        )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ClaudeCodeIntegrationError("unsupported integration-state schema version")
    try:
        IntegrationPhase(value["phase"])
    except (TypeError, ValueError) as error:
        raise ClaudeCodeIntegrationError("invalid integration phase") from error
    if not _valid_path(value["settings_path"]) or not _valid_git_bash_path(
        value["applied_value"]
    ):
        raise ClaudeCodeIntegrationError("integration state contains an invalid path")
    if type(value["settings_existed"]) is not bool:
        raise ClaudeCodeIntegrationError("integration state has invalid settings history")
    previous = value["previous"]
    if not isinstance(previous, dict) or type(previous.get("present")) is not bool:
        raise ClaudeCodeIntegrationError("integration state has invalid prior value")
    expected = {"present", "value"} if previous["present"] else {"present"}
    if set(previous) != expected or (
        previous["present"] and not isinstance(previous["value"], str)
    ):
        raise ClaudeCodeIntegrationError("integration state has invalid prior value")
    if not value["settings_existed"] and previous["present"]:
        raise ClaudeCodeIntegrationError("integration state has invalid settings history")
    return value


def _read_regular_bytes(path: Path) -> tuple[bool, bytes]:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False, b""
    except OSError as error:
        raise ClaudeCodeIntegrationError(
            f"configuration path cannot be inspected safely: {error}"
        ) from error
    if not stat.S_ISREG(entry.st_mode):
        raise ClaudeCodeIntegrationError(
            "configuration path must be absent or an ordinary regular file"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ClaudeCodeIntegrationError(f"configuration is unreadable: {error}") from error
    try:
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                entry.st_ino and opened.st_ino and entry.st_ino != opened.st_ino
            ):
                raise ClaudeCodeIntegrationError(
                    "configuration entry changed while being opened"
                )
            chunks: list[bytes] = []
            retained = 0
            while retained <= MAX_DOCUMENT_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65536, MAX_DOCUMENT_BYTES + 1 - retained),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                retained += len(chunk)
            if retained > MAX_DOCUMENT_BYTES:
                raise ClaudeCodeIntegrationError(
                    "configuration document exceeds the size limit"
                )
            return True, b"".join(chunks)
        finally:
            os.close(descriptor)
    except ClaudeCodeIntegrationError:
        raise
    except OSError as error:
        raise ClaudeCodeIntegrationError(f"configuration is unreadable: {error}") from error


def _snapshot(path: Path, parser: DocumentParser) -> _Snapshot:
    exists, raw = _read_regular_bytes(path)
    return _Snapshot(exists, raw, parser(raw) if exists else {})


def _serialize(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            raise OSError("write made no progress")
        offset += written


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _missing_directories(directory: Path) -> tuple[Path, ...]:
    missing = []
    current = directory
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(missing))


def _write_backup(path: Path, raw: bytes) -> Path:
    base = path.with_name(f"{path.name}.agent-tools-backup")
    for index in range(1000):
        backup = base if index == 0 else path.with_name(f"{base.name}-{index}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(backup, flags, 0o600)
        except FileExistsError:
            continue
        try:
            try:
                _write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except Exception:
            try:
                backup.unlink()
            except OSError:
                pass
            raise
        _sync_directory(path.parent)
        return backup
    raise ClaudeCodeIntegrationError("could not allocate a collision-safe backup")


def _prepare_temporary(path: Path, raw: bytes, parser: DocumentParser) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        parser(_read_regular_bytes(temporary)[1])
    except Exception:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise
    return temporary


def _same_snapshot(left: _Snapshot, right: _Snapshot) -> bool:
    return left.exists == right.exists and left.raw == right.raw


def _restore(path: Path, original: _Snapshot, expected_raw: bytes, parser: DocumentParser) -> None:
    current = _snapshot(path, parser)
    if not current.exists or current.raw != expected_raw:
        raise ClaudeCodeIntegrationError(
            "configuration changed before restoration could begin"
        )
    if original.exists:
        temporary = _prepare_temporary(path, original.raw, parser)
        try:
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        _sync_directory(path.parent)
        if not _same_snapshot(_snapshot(path, parser), original):
            raise ClaudeCodeIntegrationError("restored configuration is not exact")
    else:
        path.unlink()
        _sync_directory(path.parent)
        if _snapshot(path, parser).exists:
            raise ClaudeCodeIntegrationError("new configuration could not be removed")


def _restore_deleted(path: Path, original: _Snapshot, parser: DocumentParser) -> None:
    if _snapshot(path, parser).exists:
        raise ClaudeCodeIntegrationError("deleted configuration path is no longer absent")
    temporary = _prepare_temporary(path, original.raw, parser)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    _sync_directory(path.parent)
    if not _same_snapshot(_snapshot(path, parser), original):
        raise ClaudeCodeIntegrationError("deleted configuration was not restored exactly")


def _raise_if_cancelled(cancellation: _CancellationContext) -> None:
    if cancellation.checkpoint():
        raise cancellation.first_interruption or KeyboardInterrupt()


def _replace_document(
    path: Path,
    original: _Snapshot,
    document: dict[str, Any],
    parser: DocumentParser,
    cancellation: _CancellationContext | None = None,
) -> Path | None:
    owns_cancellation = cancellation is None
    cancellation = cancellation or _CancellationContext()
    brokerage = (
        _SigintBroker(cancellation, propagate_pending_on_exit=True)
        if owns_cancellation
        else nullcontext()
    )
    backup: Path | None = None
    raw = _serialize(document)
    temporary: Path | None = None
    replaced = False
    restored = False
    try:
        with brokerage:
            try:
                missing = _missing_directories(path.parent)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not _same_snapshot(_snapshot(path, parser), original):
                    raise ClaudeCodeIntegrationError(
                        "configuration changed before mutation could begin"
                    )
                backup = _write_backup(path, original.raw) if original.exists else None
                _raise_if_cancelled(cancellation)
                temporary = _prepare_temporary(path, raw, parser)
                if not _same_snapshot(_snapshot(path, parser), original):
                    raise ClaudeCodeIntegrationError(
                        "configuration changed before atomic replacement"
                    )
                _raise_if_cancelled(cancellation)
                os.replace(temporary, path)
                replaced = True
                temporary = None
                _raise_if_cancelled(cancellation)
                _sync_directory(path.parent)
                for directory in reversed(missing):
                    _sync_directory(directory.parent)
                _raise_if_cancelled(cancellation)
                persisted = _snapshot(path, parser)
                if persisted.raw != raw or persisted.document != document:
                    raise ClaudeCodeIntegrationError(
                        "configuration failed resulting-state validation"
                    )
                _raise_if_cancelled(cancellation)
                return backup
            except _ForceAbort:
                raise
            except KeyboardInterrupt as error:
                if replaced:
                    try:
                        _restore(path, original, raw, parser)
                        restored = True
                    except _ForceAbort:
                        raise
                    except Exception as restoration_error:
                        raise ClaudeCodeIntegrationRestorationError(
                            f"interrupted update restoration is uncertain: {restoration_error}",
                            tuple(item for item in (backup,) if item is not None),
                        ) from error
                raise
            except Exception as error:
                if replaced:
                    try:
                        _restore(path, original, raw, parser)
                        restored = True
                        _raise_if_cancelled(cancellation)
                    except (_ForceAbort, KeyboardInterrupt):
                        raise
                    except Exception as restoration_error:
                        raise ClaudeCodeIntegrationRestorationError(
                            f"failed update restoration is uncertain: {restoration_error}",
                            tuple(item for item in (backup,) if item is not None),
                        ) from error
                    raise ClaudeCodeIntegrationError(
                        f"configuration update failed; prior state restored: {error}"
                    ) from error
                raise ClaudeCodeIntegrationError(
                    f"configuration update failed before replacement: {error}"
                ) from error
    except _ForceAbort:
        raise
    except KeyboardInterrupt as error:
        if replaced and not restored:
            try:
                _restore(path, original, raw, parser)
            except Exception as restoration_error:
                raise ClaudeCodeIntegrationRestorationError(
                    f"interrupted update restoration is uncertain: {restoration_error}",
                    tuple(item for item in (backup,) if item is not None),
                ) from error
        raise
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _remove_document(
    path: Path,
    original: _Snapshot,
    parser: DocumentParser,
    cancellation: _CancellationContext | None = None,
) -> Path:
    if not original.exists:
        raise ClaudeCodeIntegrationError("cannot remove an absent configuration")
    owns_cancellation = cancellation is None
    cancellation = cancellation or _CancellationContext()
    brokerage = (
        _SigintBroker(cancellation, propagate_pending_on_exit=True)
        if owns_cancellation
        else nullcontext()
    )
    backup: Path | None = None
    deleted = False
    restored = False
    try:
        with brokerage:
            try:
                if not _same_snapshot(_snapshot(path, parser), original):
                    raise ClaudeCodeIntegrationError(
                        "configuration changed before removal"
                    )
                backup = _write_backup(path, original.raw)
                _raise_if_cancelled(cancellation)
                path.unlink()
                deleted = True
                _sync_directory(path.parent)
                _raise_if_cancelled(cancellation)
                if _snapshot(path, parser).exists:
                    raise ClaudeCodeIntegrationError(
                        "removed configuration is still present"
                    )
                _raise_if_cancelled(cancellation)
                return backup
            except _ForceAbort:
                raise
            except KeyboardInterrupt as error:
                if deleted:
                    try:
                        _restore_deleted(path, original, parser)
                        restored = True
                    except _ForceAbort:
                        raise
                    except Exception as restoration_error:
                        raise ClaudeCodeIntegrationRestorationError(
                            f"interrupted removal restoration is uncertain: {restoration_error}",
                            tuple(item for item in (backup,) if item is not None),
                        ) from error
                raise
            except Exception as error:
                if deleted:
                    try:
                        _restore_deleted(path, original, parser)
                        restored = True
                        _raise_if_cancelled(cancellation)
                    except (_ForceAbort, KeyboardInterrupt):
                        raise
                    except Exception as restoration_error:
                        raise ClaudeCodeIntegrationRestorationError(
                            f"failed removal restoration is uncertain: {restoration_error}",
                            tuple(item for item in (backup,) if item is not None),
                        ) from error
                    raise ClaudeCodeIntegrationError(
                        f"configuration removal failed; prior state restored: {error}"
                    ) from error
                raise ClaudeCodeIntegrationError(
                    f"configuration removal failed before deletion: {error}"
                ) from error
    except _ForceAbort:
        raise
    except KeyboardInterrupt as error:
        if deleted and not restored:
            try:
                _restore_deleted(path, original, parser)
            except Exception as restoration_error:
                raise ClaudeCodeIntegrationRestorationError(
                    f"interrupted removal restoration is uncertain: {restoration_error}",
                    tuple(item for item in (backup,) if item is not None),
                ) from error
        raise


def _current_member(document: dict[str, Any]) -> tuple[bool, str | None]:
    environment = document.get("env")
    if not isinstance(environment, dict) or SETTING_NAME not in environment:
        return False, None
    return True, environment[SETTING_NAME]


def _with_member(document: dict[str, Any], present: bool, value: str | None) -> dict[str, Any]:
    updated = copy.deepcopy(document)
    environment = dict(updated.get("env", {}))
    if present:
        environment[SETTING_NAME] = value
    else:
        environment.pop(SETTING_NAME, None)
    if environment:
        updated["env"] = environment
    else:
        updated.pop("env", None)
    return updated


def _record(
    phase: IntegrationPhase,
    settings_path: Path,
    applied_value: str,
    settings_existed: bool,
    previous_present: bool,
    previous_value: str | None,
) -> dict[str, Any]:
    previous: dict[str, Any] = {"present": previous_present}
    if previous_present:
        previous["value"] = previous_value
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": phase.value,
        "settings_path": str(settings_path),
        "settings_existed": settings_existed,
        "applied_value": applied_value,
        "previous": previous,
    }


def _record_facts(
    document: dict[str, Any],
) -> tuple[IntegrationPhase, str, bool, bool, str | None]:
    previous = document["previous"]
    return (
        IntegrationPhase(document["phase"]),
        document["applied_value"],
        document["settings_existed"],
        previous["present"],
        previous.get("value"),
    )


def _selected_git_bash(
    machine: MachineState,
    detector: Callable[[CapabilitySpec, MachineState], CapabilityState],
) -> str:
    if machine.platform != "Windows" or machine.execution_environment != "host":
        raise ClaudeCodeIntegrationError(
            "Claude Code Git Bash integration requires native Windows host execution"
        )
    state = detector(BASH, machine)
    selected = state.selected_provider
    if selected is None or selected.provider.provider_id != "git-bash":
        raise ClaudeCodeIntegrationError("verified selected Git Bash is unavailable")
    executables = acceptable_provider_executables(
        selected,
        lambda item: (
            item.path is not None
            and _valid_git_bash_path(item.path)
        ),
    )
    if len(executables) != 1 or executables[0].path is None:
        raise ClaudeCodeIntegrationError(
            "selected Git Bash does not have one verified Windows executable"
        )
    return executables[0].path


def inspect_integration(
    *,
    settings_path: Path | None = None,
    state_path: Path | None = None,
) -> IntegrationStatus:
    settings_path = settings_path or claude_settings_path()
    state_path = state_path or integration_state_path()
    settings = _snapshot(settings_path, _parse_settings)
    state = _snapshot(state_path, _parse_state)
    present, current = _current_member(settings.document)
    if not state.exists:
        return IntegrationStatus(settings_path, state_path, None, current, False)
    phase, applied, settings_existed, previous_present, previous_value = _record_facts(
        state.document
    )
    if state.document["settings_path"] != str(settings_path):
        raise ClaudeCodeIntegrationError("integration state names another settings path")
    expected = (True, applied) if phase in {
        IntegrationPhase.PREPARED,
        IntegrationPhase.ACTIVE,
    } else (previous_present, previous_value)
    managed = (present, current) == expected
    return IntegrationStatus(settings_path, state_path, phase, current, managed)


def apply_git_bash_integration(
    *,
    allow_config_mutation: bool = False,
    machine: MachineState | None = None,
    detector: Callable[[CapabilitySpec, MachineState], CapabilityState] = detect_capability,
    settings_path: Path | None = None,
    state_path: Path | None = None,
) -> IntegrationResult:
    cancellation = _CancellationContext()
    with _SigintBroker(cancellation, propagate_pending_on_exit=True):
        return _apply_git_bash_integration(
            allow_config_mutation=allow_config_mutation,
            machine=machine,
            detector=detector,
            settings_path=settings_path,
            state_path=state_path,
            cancellation=cancellation,
        )


def _apply_git_bash_integration(
    *,
    allow_config_mutation: bool,
    machine: MachineState | None,
    detector: Callable[[CapabilitySpec, MachineState], CapabilityState],
    settings_path: Path | None,
    state_path: Path | None,
    cancellation: _CancellationContext,
) -> IntegrationResult:
    machine = machine or current_machine()
    applied = _selected_git_bash(machine, detector)
    settings_path = settings_path or claude_settings_path()
    state_path = state_path or integration_state_path()
    with _MUTATION_LOCK:
        settings = _snapshot(settings_path, _parse_settings)
        state = _snapshot(state_path, _parse_state)
        current_present, current_value = _current_member(settings.document)
        if not state.exists:
            if (current_present, current_value) == (True, applied):
                return IntegrationResult(
                    IntegrationOutcome.NO_CHANGES,
                    settings_path,
                    state_path,
                    None,
                    detail="matching Claude Code setting already exists and is not claimed",
                )
            settings_existed = settings.exists
            previous_present, previous_value = current_present, current_value
            phase = None
        else:
            if state.document["settings_path"] != str(settings_path):
                raise ClaudeCodeIntegrationError(
                    "integration state names another settings path"
                )
            (
                phase,
                recorded_applied,
                settings_existed,
                previous_present,
                previous_value,
            ) = _record_facts(state.document)
            if phase is IntegrationPhase.ACTIVE:
                if recorded_applied != applied:
                    raise ClaudeCodeIntegrationError(
                        "selected Git Bash changed; remove the active integration before reapplying"
                    )
                if (current_present, current_value) != (True, recorded_applied):
                    raise ClaudeCodeIntegrationError(
                        "Claude Code setting diverged from active integration state"
                    )
                return IntegrationResult(
                    IntegrationOutcome.NO_CHANGES,
                    settings_path,
                    state_path,
                    phase,
                )
            if phase is IntegrationPhase.REMOVING:
                raise ClaudeCodeIntegrationError(
                    "integration removal must be reconciled before apply"
                )
            expected_previous = (previous_present, previous_value)
            if phase is IntegrationPhase.PREPARED:
                if recorded_applied != applied:
                    raise ClaudeCodeIntegrationError(
                        "prepared integration names another Git Bash path"
                    )
                if (current_present, current_value) not in {
                    expected_previous,
                    (True, recorded_applied),
                }:
                    raise ClaudeCodeIntegrationError(
                        "Claude Code setting diverged from prepared integration state"
                    )
                if (current_present, current_value) == expected_previous:
                    settings_existed = settings.exists
                    previous_present, previous_value = (
                        current_present,
                        current_value,
                    )
            else:
                if (current_present, current_value) != expected_previous:
                    raise ClaudeCodeIntegrationError(
                        "Claude Code setting diverged from removed integration state"
                    )
                settings_existed = settings.exists
                previous_present, previous_value = current_present, current_value
        if not allow_config_mutation:
            return IntegrationResult(
                IntegrationOutcome.REFUSED,
                settings_path,
                state_path,
                phase,
                detail="integration mutation was not explicitly authorized",
            )
        backups: list[Path] = []
        prepared = _record(
            IntegrationPhase.PREPARED,
            settings_path,
            applied,
            settings_existed,
            previous_present,
            previous_value,
        )
        if not state.exists or state.document != prepared:
            backup = _replace_document(
                state_path, state, prepared, _parse_state, cancellation
            )
            if backup is not None:
                backups.append(backup)
            state = _snapshot(state_path, _parse_state)
        changed_settings = (current_present, current_value) != (True, applied)
        if changed_settings:
            updated_settings = _with_member(settings.document, True, applied)
            backup = _replace_document(
                settings_path,
                settings,
                updated_settings,
                _parse_settings,
                cancellation,
            )
            if backup is not None:
                backups.append(backup)
        active = dict(prepared, phase=IntegrationPhase.ACTIVE.value)
        try:
            backup = _replace_document(
                state_path, state, active, _parse_state, cancellation
            )
            if backup is not None:
                backups.append(backup)
        except _ForceAbort:
            raise
        except (Exception, KeyboardInterrupt) as error:
            if changed_settings:
                try:
                    _restore(
                        settings_path,
                        settings,
                        _serialize(updated_settings),
                        _parse_settings,
                    )
                except Exception as restoration_error:
                    raise ClaudeCodeIntegrationRestorationError(
                        "integration activation failed and settings restoration is "
                        f"uncertain: {restoration_error}",
                        tuple(backups),
                    ) from error
            _raise_if_cancelled(cancellation)
            if isinstance(error, KeyboardInterrupt):
                raise
            raise ClaudeCodeIntegrationError(
                f"integration activation failed; prior settings restored: {error}"
            ) from error
        return IntegrationResult(
            IntegrationOutcome.UPDATED,
            settings_path,
            state_path,
            IntegrationPhase.ACTIVE,
            tuple(backups),
        )


def remove_git_bash_integration(
    *,
    allow_config_mutation: bool = False,
    machine: MachineState | None = None,
    settings_path: Path | None = None,
    state_path: Path | None = None,
) -> IntegrationResult:
    cancellation = _CancellationContext()
    with _SigintBroker(cancellation, propagate_pending_on_exit=True):
        return _remove_git_bash_integration(
            allow_config_mutation=allow_config_mutation,
            machine=machine,
            settings_path=settings_path,
            state_path=state_path,
            cancellation=cancellation,
        )


def _remove_git_bash_integration(
    *,
    allow_config_mutation: bool,
    machine: MachineState | None,
    settings_path: Path | None,
    state_path: Path | None,
    cancellation: _CancellationContext,
) -> IntegrationResult:
    machine = machine or current_machine()
    if machine.platform != "Windows" or machine.execution_environment != "host":
        raise ClaudeCodeIntegrationError(
            "Claude Code Git Bash integration requires native Windows host execution"
        )
    settings_path = settings_path or claude_settings_path()
    state_path = state_path or integration_state_path()
    with _MUTATION_LOCK:
        settings = _snapshot(settings_path, _parse_settings)
        state = _snapshot(state_path, _parse_state)
        if not state.exists:
            return IntegrationResult(
                IntegrationOutcome.NO_CHANGES,
                settings_path,
                state_path,
                None,
                detail="no Agent Tools-managed Claude Code integration exists",
            )
        if state.document["settings_path"] != str(settings_path):
            raise ClaudeCodeIntegrationError("integration state names another settings path")
        (
            phase,
            applied,
            settings_existed,
            previous_present,
            previous_value,
        ) = _record_facts(state.document)
        current = _current_member(settings.document)
        previous = (previous_present, previous_value)
        if phase is IntegrationPhase.REMOVED:
            if current != previous:
                raise ClaudeCodeIntegrationError(
                    "Claude Code setting diverged from removed integration state"
                )
            return IntegrationResult(
                IntegrationOutcome.NO_CHANGES,
                settings_path,
                state_path,
                phase,
            )
        if current not in {(True, applied), previous}:
            raise ClaudeCodeIntegrationError(
                "Claude Code setting diverged from managed integration state"
            )
        if not allow_config_mutation:
            return IntegrationResult(
                IntegrationOutcome.REFUSED,
                settings_path,
                state_path,
                phase,
                detail="integration mutation was not explicitly authorized",
            )
        backups: list[Path] = []
        removing = dict(state.document, phase=IntegrationPhase.REMOVING.value)
        if phase is not IntegrationPhase.REMOVING:
            backup = _replace_document(
                state_path, state, removing, _parse_state, cancellation
            )
            if backup is not None:
                backups.append(backup)
            state = _snapshot(state_path, _parse_state)
        if current == (True, applied):
            restored_settings = _with_member(
                settings.document, previous_present, previous_value
            )
            backup = (
                _remove_document(
                    settings_path, settings, _parse_settings, cancellation
                )
                if not settings_existed and not restored_settings
                else _replace_document(
                    settings_path,
                    settings,
                    restored_settings,
                    _parse_settings,
                    cancellation,
                )
            )
            if backup is not None:
                backups.append(backup)
        removed = dict(removing, phase=IntegrationPhase.REMOVED.value)
        backup = _replace_document(
            state_path, state, removed, _parse_state, cancellation
        )
        if backup is not None:
            backups.append(backup)
        return IntegrationResult(
            IntegrationOutcome.UPDATED,
            settings_path,
            state_path,
            IntegrationPhase.REMOVED,
            tuple(backups),
        )
