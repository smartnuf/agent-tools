"""Versioned desired capability configuration with reversible mutation."""

from __future__ import annotations

import json
import os
import platform
import posixpath
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any

from .capabilities import CapabilitySpec, MachineState, current_machine, get_capability
from .cooperative_cancellation import (
    _CancellationContext,
    _ForceAbort,
    _SigintBroker,
)


SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_CAPABILITIES = 256
MAX_IDENTITY_LENGTH = 128
_MUTATION_LOCK = threading.RLock()


class DesiredStateError(RuntimeError):
    """Desired state cannot be safely read, understood, or changed."""


class DesiredStateRestorationError(DesiredStateError):
    """A failed update could not confirm restoration of prior state."""

    def __init__(self, detail: str, backup_path: Path | None) -> None:
        super().__init__(detail)
        self.backup_path = backup_path


class DesiredMutationOutcome(str, Enum):
    NO_CHANGES = "no-changes"
    REFUSED = "refused"
    UPDATED = "updated"


@dataclass(frozen=True)
class DesiredCapability:
    capability_id: str
    provider_id: str | None = None


@dataclass(frozen=True)
class DesiredMutationResult:
    outcome: DesiredMutationOutcome
    path: Path
    document: dict[str, Any]
    backup_path: Path | None = None
    detail: str = ""


@dataclass(frozen=True)
class _Snapshot:
    exists: bool
    raw: bytes
    document: dict[str, Any]


def desired_state_path(
    *,
    platform_name: str | None = None,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve the private per-user desired-state path."""

    env = os.environ if environment is None else environment
    platform_name = platform_name or platform.system()
    if platform_name in {"nt", "Windows"}:
        root = env.get("LOCALAPPDATA")
        if not root:
            raise DesiredStateError("LOCALAPPDATA is unavailable")
        if not PureWindowsPath(root).is_absolute():
            raise DesiredStateError("LOCALAPPDATA is not an absolute Windows path")
        return Path(root) / "agent-tools" / "config.json"
    resolved_home = _resolved_home(home)
    if platform_name in {"Darwin", "darwin"}:
        return (
            resolved_home
            / "Library"
            / "Application Support"
            / "agent-tools"
            / "config.json"
        )
    configured = env.get("XDG_CONFIG_HOME")
    root = (
        Path(configured)
        if configured is not None and posixpath.isabs(configured)
        else resolved_home / ".config"
    )
    return root / "agent-tools" / "config.json"


def _resolved_home(home: Path | None) -> Path:
    if home is None:
        try:
            home = Path.home()
        except (OSError, RuntimeError) as error:
            raise DesiredStateError(
                f"user home directory is unavailable: {error}"
            ) from error
    if not posixpath.isabs(home.as_posix()):
        raise DesiredStateError("user home directory is not absolute")
    return home


def empty_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "capabilities": {}}


def _read_regular_bytes(path: Path) -> tuple[bool, bytes]:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False, b""
    except OSError as error:
        raise DesiredStateError(
            f"desired-state path cannot be inspected safely: {error}"
        ) from error
    if not stat.S_ISREG(entry.st_mode):
        raise DesiredStateError(
            "desired-state path must be absent or an ordinary regular file"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise DesiredStateError(f"desired state is unreadable: {error}") from error
    try:
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (
                entry.st_ino and opened.st_ino and entry.st_ino != opened.st_ino
            ):
                raise DesiredStateError(
                    "desired-state entry changed while being opened"
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
                raise DesiredStateError(
                    "desired-state document exceeds the size limit"
                )
            return True, b"".join(chunks)
        finally:
            os.close(descriptor)
    except DesiredStateError:
        raise
    except OSError as error:
        raise DesiredStateError(f"desired state is unreadable: {error}") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise DesiredStateError(f"desired state contains duplicate JSON key: {name}")
        value[name] = item
    return value


def _validate_depth(value: object) -> None:
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise DesiredStateError("desired-state JSON container depth exceeds the limit")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _parse_document(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise DesiredStateError(
            f"desired state is unreadable or corrupt: {error}"
        ) from error
    _validate_depth(value)
    if not isinstance(value, dict) or set(value) != {"schema_version", "capabilities"}:
        raise DesiredStateError("desired-state root does not match schema v1")
    version = value["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise DesiredStateError(f"unsupported desired-state schema version: {version!r}")
    capabilities = value["capabilities"]
    if not isinstance(capabilities, dict) or len(capabilities) > MAX_CAPABILITIES:
        raise DesiredStateError("desired-state capabilities must be a bounded JSON object")
    for capability_id, entry in capabilities.items():
        if (
            not isinstance(capability_id, str)
            or not capability_id
            or len(capability_id) > MAX_IDENTITY_LENGTH
        ):
            raise DesiredStateError("desired state contains an invalid capability identity")
        if not isinstance(entry, dict) or not set(entry).issubset({"provider"}):
            raise DesiredStateError(
                f"desired capability does not match schema v1: {capability_id}"
            )
        provider = entry.get("provider")
        if "provider" in entry and (
            not isinstance(provider, str)
            or not provider
            or len(provider) > MAX_IDENTITY_LENGTH
        ):
            raise DesiredStateError(
                f"desired capability has an invalid provider identity: {capability_id}"
            )
    return value


def _snapshot(path: Path) -> _Snapshot:
    exists, raw = _read_regular_bytes(path)
    return _Snapshot(exists, raw, _parse_document(raw) if exists else empty_document())


def load_document(path: Path) -> dict[str, Any]:
    """Load and validate desired state without interpreting catalogue support."""

    return _snapshot(path).document


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


def _write_backup(path: Path, raw: bytes) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = path.with_name(f"{path.name}.backup-{stamp}")
    for index in range(1000):
        backup = base if index == 0 else path.with_name(f"{base.name}-{index}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(backup, flags, 0o600)
        except FileExistsError:
            continue
        try:
            _write_all(descriptor, raw)
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            descriptor = None
            try:
                backup.unlink()
            except OSError:
                pass
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)
        _sync_directory(path.parent)
        return backup
    raise DesiredStateError("could not allocate a collision-safe backup path")


def _prepare_temporary(path: Path, raw: bytes) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        load_document(temporary)
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


def _raise_if_cancelled(cancellation: _CancellationContext) -> None:
    if cancellation.checkpoint():
        raise cancellation.first_interruption or KeyboardInterrupt()


def _missing_directories(directory: Path) -> tuple[Path, ...]:
    missing = []
    current = directory
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(missing))


def _restore(path: Path, original: _Snapshot, expected_current: bytes) -> None:
    current = _snapshot(path)
    if not current.exists or current.raw != expected_current:
        raise DesiredStateError("updated desired-state entry changed before restoration")
    if original.exists:
        temporary = _prepare_temporary(path, original.raw)
        try:
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        _sync_directory(path.parent)
        restored = _snapshot(path)
        if not _same_snapshot(restored, original):
            raise DesiredStateError("restored desired state does not match its backup")
    else:
        path.unlink()
        _sync_directory(path.parent)
        if _snapshot(path).exists:
            raise DesiredStateError("new desired-state entry could not be removed")


def _replace_document(
    path: Path,
    original: _Snapshot,
    document: dict[str, Any],
) -> Path | None:
    cancellation = _CancellationContext()
    with _SigintBroker(cancellation):
        missing_directories = _missing_directories(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _snapshot(path)
        if not _same_snapshot(current, original):
            raise DesiredStateError("desired state changed before mutation could begin")
        backup = _write_backup(path, original.raw) if original.exists else None
        _raise_if_cancelled(cancellation)
        raw = _serialize(document)
        temporary = _prepare_temporary(path, raw)
        replaced = False
        try:
            current = _snapshot(path)
            if not _same_snapshot(current, original):
                raise DesiredStateError("desired state changed before atomic replacement")
            _raise_if_cancelled(cancellation)
            os.replace(temporary, path)
            replaced = True
            temporary = None
            _raise_if_cancelled(cancellation)
            _sync_directory(path.parent)
            _raise_if_cancelled(cancellation)
            for directory in reversed(missing_directories):
                _sync_directory(directory.parent)
                _raise_if_cancelled(cancellation)
            persisted = _snapshot(path)
            if persisted.raw != raw or persisted.document != document:
                raise DesiredStateError(
                    "updated desired state failed resulting-state validation"
                )
            _raise_if_cancelled(cancellation)
            return backup
        except _ForceAbort:
            raise
        except KeyboardInterrupt as error:
            if replaced:
                try:
                    _restore(path, original, raw)
                except _ForceAbort:
                    raise
                except Exception as restoration_error:
                    raise DesiredStateRestorationError(
                        "desired-state update was interrupted and restoration is "
                        f"uncertain: {restoration_error}",
                        backup,
                    ) from error
            raise
        except Exception as error:
            if replaced:
                try:
                    _restore(path, original, raw)
                except Exception as restoration_error:
                    raise DesiredStateRestorationError(
                        "desired-state update failed and restoration is uncertain: "
                        f"{restoration_error}",
                        backup,
                    ) from error
                raise DesiredStateError(
                    f"desired-state update failed; previous state restored: {error}"
                ) from error
            raise DesiredStateError(
                f"desired-state update failed before replacement: {error}"
            ) from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass


def _request_spec(
    capability_id: str,
    provider_id: str | None,
    machine: MachineState,
) -> CapabilitySpec:
    try:
        capability = get_capability(capability_id)
    except KeyError as error:
        raise DesiredStateError(f"unknown built-in capability: {capability_id}") from error
    if capability.required_by_default:
        raise DesiredStateError(
            f"required capability cannot be enabled or disabled: {capability_id}"
        )
    if provider_id is not None:
        provider = next(
            (item for item in capability.providers if item.provider_id == provider_id),
            None,
        )
        if provider is None or not provider.satisfies_capability:
            raise DesiredStateError(
                f"provider does not satisfy capability {capability_id}: {provider_id}"
            )
        if not provider.supports(machine):
            raise DesiredStateError(
                f"provider is unsupported in the current execution context: {provider_id}"
            )
    return capability


def desired_capabilities(
    document: dict[str, Any],
    machine: MachineState | None = None,
) -> tuple[DesiredCapability, ...]:
    """Interpret every enabled v1 entry against the current built-in catalogue."""

    machine = machine or current_machine()
    desired: list[DesiredCapability] = []
    for capability_id, entry in document["capabilities"].items():
        try:
            capability = get_capability(capability_id)
        except KeyError as error:
            raise DesiredStateError(
                f"desired capability is unsupported by this Agent Tools version: {capability_id}"
            ) from error
        if capability.required_by_default:
            raise DesiredStateError(
                f"desired state redundantly enables required capability: {capability_id}"
            )
        provider_id = entry.get("provider")
        _request_spec(capability_id, provider_id, machine)
        desired.append(DesiredCapability(capability_id, provider_id))
    return tuple(desired)


def set_capability(
    capability_id: str,
    *,
    enabled: bool,
    provider_id: str | None = None,
    allow_config_mutation: bool = False,
    path: Path | None = None,
    machine: MachineState | None = None,
) -> DesiredMutationResult:
    """Apply one authorized desired-state change without provider mutation."""

    machine = machine or current_machine()
    _request_spec(capability_id, provider_id if enabled else None, machine)
    if not enabled and provider_id is not None:
        raise DesiredStateError("disable does not accept a provider preference")
    path = path or desired_state_path(platform_name=machine.platform)
    with _MUTATION_LOCK:
        original = _snapshot(path)
        capabilities = dict(original.document["capabilities"])
        if enabled:
            entry = {} if provider_id is None else {"provider": provider_id}
            capabilities[capability_id] = entry
        else:
            capabilities.pop(capability_id, None)
        updated = {"schema_version": SCHEMA_VERSION, "capabilities": capabilities}
        if updated == original.document:
            return DesiredMutationResult(
                DesiredMutationOutcome.NO_CHANGES, path, original.document
            )
        if not allow_config_mutation:
            return DesiredMutationResult(
                DesiredMutationOutcome.REFUSED,
                path,
                original.document,
                detail="desired-state mutation was not explicitly authorized",
            )
        try:
            backup = _replace_document(path, original, updated)
        except DesiredStateError:
            raise
        except OSError as error:
            raise DesiredStateError(
                f"desired-state mutation could not access its filesystem boundary: {error}"
            ) from error
        return DesiredMutationResult(
            DesiredMutationOutcome.UPDATED,
            path,
            updated,
            backup_path=backup,
        )


def provider_preferences(
    desired: tuple[DesiredCapability, ...],
) -> dict[str, str]:
    return {
        item.capability_id: item.provider_id
        for item in desired
        if item.provider_id is not None
    }
