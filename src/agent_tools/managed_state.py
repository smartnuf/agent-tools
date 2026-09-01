"""Versioned provenance for provider mutations requested by Agent Tools."""

from __future__ import annotations

import json
import os
import platform
import posixpath
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

from .capabilities import MachineState, ProbePolicy, get_capability
from .provider_execution import (
    ActionOutcome,
    ActionReport,
    ELEVATED_TERM_TO_KILL_GRACE_SECONDS,
    PlanOutcome,
    PlanExecutionReport,
    ProviderPlanInterrupted,
    _execute_provider_plan_unmanaged,
    _provider_execution_transaction,
)
from .provider_plans import (
    NativeStatus,
    PackageManagerState,
    PlanningError,
    ProviderPlan,
    adapter_commands,
)
from .python_selection import normalize_architecture


SCHEMA_VERSION = 1
_MANAGED_STATE_LOCK = threading.RLock()
_PERSISTED_ATTEMPT_OUTCOMES = {
    ActionOutcome.SUCCEEDED.value,
    ActionOutcome.COMMAND_FAILED.value,
    ActionOutcome.COMMAND_START_FAILED.value,
    ActionOutcome.TIMED_OUT.value,
    ActionOutcome.FORCED_KILL.value,
    ActionOutcome.SUPERVISOR_FAILED.value,
    ActionOutcome.INTERRUPTED.value,
    ActionOutcome.VERIFICATION_FAILED.value,
}


class ManagedStateError(RuntimeError):
    """Managed state cannot safely be read, understood, or preserved."""


class PersistenceOutcome(str, Enum):
    NOT_REQUIRED = "not-required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class PersistenceError(ManagedStateError):
    def __init__(self, outcome: PersistenceOutcome, detail: str) -> None:
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail


class PersistenceInterrupted(KeyboardInterrupt):
    """Carry durability classification when state persistence is interrupted."""

    def __init__(self, outcome: PersistenceOutcome, detail: str) -> None:
        super().__init__(detail)
        self.outcome = outcome
        self.detail = detail
        self.managed_result: ManagedExecutionResult | None = None


class ManagedExecutionInterrupted(KeyboardInterrupt):
    """Propagate an interruption after conservative provenance persistence."""

    def __init__(self, original: KeyboardInterrupt) -> None:
        super().__init__("managed provider execution interrupted")
        self.original = original
        self.managed_result: ManagedExecutionResult | None = None


@dataclass(frozen=True)
class ManagedExecutionResult:
    execution: PlanExecutionReport | None
    persistence: PersistenceOutcome
    persistence_detail: str = ""
    recovery_guidance: tuple[str, ...] = ()


def managed_state_path(
    *,
    platform_name: str | None = None,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve the private per-user document path for the current environment."""

    env = os.environ if environment is None else environment
    platform_name = platform_name or platform.system()
    if platform_name in {"nt", "Windows"}:
        root = env.get("LOCALAPPDATA")
        if not root:
            raise ManagedStateError("LOCALAPPDATA is unavailable")
        if not PureWindowsPath(root).is_absolute():
            raise ManagedStateError("LOCALAPPDATA is not an absolute Windows path")
        return Path(root) / "agent-tools" / "managed-state.json"
    if platform_name in {"Darwin", "darwin"}:
        return (
            _resolved_home(home)
            / "Library"
            / "Application Support"
            / "agent-tools"
            / "managed-state.json"
        )
    configured_value = env.get("XDG_STATE_HOME")
    root = (
        Path(configured_value)
        if configured_value is not None and posixpath.isabs(configured_value)
        else _resolved_home(home) / ".local" / "state"
    )
    return root / "agent-tools" / "managed-state.json"


def _resolved_home(home: Path | None) -> Path:
    if home is None:
        try:
            home = Path.home()
        except (OSError, RuntimeError) as error:
            raise ManagedStateError(f"user home directory is unavailable: {error}") from error
    if not posixpath.isabs(home.as_posix()):
        raise ManagedStateError("user home directory is not absolute")
    return home


def empty_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "records": []}


def load_document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_document()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManagedStateError(f"managed state is unreadable or corrupt: {error}") from error
    try:
        value = json.loads(text, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as error:
        raise ManagedStateError(f"managed state is unreadable or corrupt: {error}") from error
    if not isinstance(value, dict):
        raise ManagedStateError("managed state root must be a JSON object")
    version = value.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ManagedStateError(f"unsupported managed-state schema version: {version!r}")
    records = value.get("records")
    if not isinstance(records, list) or not all(
        isinstance(item, dict) for item in records
    ):
        raise ManagedStateError("managed-state records must be a JSON array of objects")
    record_ids: set[uuid.UUID] = set()
    for index, record in enumerate(records):
        required = {
            "id": str,
            "requested_at": str,
            "completed_at": str,
            "recorded_at": str,
            "capability_id": str,
            "provider": dict,
            "package_manager": dict,
            "installation_unit": str,
            "execution_context": dict,
            "requested_action": dict,
            "verification": dict,
            "command_evidence": list,
            "ownership": bool,
        }
        if any(not isinstance(record.get(name), kind) for name, kind in required.items()):
            raise ManagedStateError(f"managed-state record {index} does not match schema v1")
        try:
            record_id = uuid.UUID(record["id"])
        except (ValueError, AttributeError) as error:
            raise ManagedStateError(f"managed-state record {index} has an invalid id") from error
        if record_id in record_ids:
            raise ManagedStateError(f"managed-state record {index} has a duplicate id")
        record_ids.add(record_id)
        for timestamp_name in ("requested_at", "completed_at", "recorded_at"):
            try:
                parsed = datetime.fromisoformat(record[timestamp_name].replace("Z", "+00:00"))
            except ValueError as error:
                raise ManagedStateError(
                    f"managed-state record {index} has an invalid {timestamp_name}"
                ) from error
            if parsed.tzinfo is None:
                raise ManagedStateError(
                    f"managed-state record {index} has a timezone-free {timestamp_name}"
                )
        if record["ownership"] is not False:
            raise ManagedStateError(f"managed-state record {index} makes an ownership claim")
        provider = record["provider"]
        package_manager = record["package_manager"]
        context = record["execution_context"]
        requested = record["requested_action"]
        verification = record["verification"]
        if not all(isinstance(provider.get(name), str) for name in ("id", "origin")):
            raise ManagedStateError(f"managed-state record {index} has invalid provider evidence")
        if provider["origin"] not in {"system-external", "tool-managed"}:
            raise ManagedStateError(f"managed-state record {index} has invalid provider origin")
        try:
            capability = get_capability(record["capability_id"])
        except KeyError as error:
            raise ManagedStateError(
                f"managed-state record {index} names an unknown capability"
            ) from error
        provider_spec = next(
            (
                item
                for item in capability.providers
                if item.provider_id == provider["id"]
            ),
            None,
        )
        if provider_spec is None or provider_spec.origin.value != provider["origin"]:
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent provider identity"
            )
        if (
            not all(
                isinstance(package_manager.get(name), str)
                for name in ("name", "executable")
            )
            or "architecture" not in package_manager
            or (
                package_manager.get("architecture") is not None
                and not isinstance(package_manager["architecture"], str)
            )
        ):
            raise ManagedStateError(
                f"managed-state record {index} has invalid package-manager evidence"
            )
        if not all(
            isinstance(context.get(name), str)
            for name in ("platform", "architecture", "execution_environment")
        ):
            raise ManagedStateError(f"managed-state record {index} has invalid execution context")
        machine = MachineState(
            context["platform"],
            context["architecture"],
            context["execution_environment"],
        )
        package_matches = any(
            package.manager == package_manager["name"]
            and package.installation_unit == record["installation_unit"]
            and machine.platform in package.platforms
            and (
                not package.architectures
                or machine.architecture in package.architectures
            )
            for package in provider_spec.packages
        )
        if not provider_spec.supports(machine) or not package_matches:
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent package or context evidence"
            )
        if not _is_absolute_for_platform(
            package_manager["executable"], context["platform"]
        ):
            raise ManagedStateError(
                f"managed-state record {index} has a non-absolute package-manager executable"
            )
        commands = requested.get("commands")
        if (
            not isinstance(requested.get("kind"), str)
            or requested["kind"] not in {"install", "native-replacement"}
            or not isinstance(requested.get("reason"), str)
            or (
                requested.get("target_architecture") is not None
                and not isinstance(requested["target_architecture"], str)
            )
            or not isinstance(requested.get("displaces_verified_paths"), list)
            or not all(
                isinstance(item, str)
                for item in requested["displaces_verified_paths"]
            )
            or type(requested.get("translated_manager_fallback_authorized"))
            is not bool
        ):
            raise ManagedStateError(
                f"managed-state record {index} has invalid requested-action semantics"
            )
        if not isinstance(commands, list) or not all(
            isinstance(command, list)
            and command
            and all(isinstance(argument, str) for argument in command)
            for command in commands
        ):
            raise ManagedStateError(f"managed-state record {index} has invalid requested action")
        target_architecture = requested.get("target_architecture")
        try:
            expected_commands = [
                list(command)
                for command in adapter_commands(
                    package_manager["name"],
                    record["installation_unit"],
                    executable_path=package_manager["executable"],
                    target_architecture=target_architecture,
                )
            ]
        except PlanningError as error:
            raise ManagedStateError(
                f"managed-state record {index} has invalid adapter semantics: {error}"
            ) from error
        if commands != expected_commands:
            raise ManagedStateError(
                f"managed-state record {index} has unreviewed requested commands"
            )
        displaced_paths = requested["displaces_verified_paths"]
        if any(
            not _is_absolute_for_platform(path, context["platform"])
            for path in displaced_paths
        ):
            raise ManagedStateError(
                f"managed-state record {index} has non-absolute displaced-provider evidence"
            )
        native_target = normalize_architecture(target_architecture)
        context_architecture = normalize_architecture(context["architecture"])
        if (
            requested["kind"] == "install"
            and (target_architecture is not None or displaced_paths)
        ) or (
            requested["kind"] == "native-replacement"
            and (
                target_architecture is None
                or not displaced_paths
                or native_target == "unknown"
                or native_target != context_architecture
            )
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent native-replacement semantics"
            )
        recorded_manager = PackageManagerState(
            package_manager["name"],
            package_manager["executable"],
            context["execution_environment"],
            package_manager["architecture"],
        )
        translated_authorized = requested[
            "translated_manager_fallback_authorized"
        ]
        if package_manager["name"] == "brew":
            manager_native_status = recorded_manager.native_status(machine)
            if manager_native_status is NativeStatus.UNKNOWN or (
                manager_native_status is NativeStatus.TRANSLATED
                and not translated_authorized
            ) or (
                manager_native_status is NativeStatus.NATIVE
                and translated_authorized
            ):
                raise ManagedStateError(
                    f"managed-state record {index} has inconsistent Homebrew authorization evidence"
                )
        elif translated_authorized:
            raise ManagedStateError(
                f"managed-state record {index} has invalid translated-manager authorization"
            )
        if not (
            isinstance(verification.get("outcome"), str)
            and verification["outcome"]
            in _PERSISTED_ATTEMPT_OUTCOMES
            and isinstance(verification.get("verified_paths"), list)
            and all(isinstance(item, str) for item in verification["verified_paths"])
            and all(
                _is_absolute_for_platform(item, context["platform"])
                for item in verification["verified_paths"]
            )
            and len(verification["verified_paths"])
            <= len(provider_spec.probes)
            and isinstance(verification.get("detail"), str)
        ):
            raise ManagedStateError(f"managed-state record {index} has invalid verification evidence")
        if (
            verification["outcome"] != ActionOutcome.INTERRUPTED.value
            and not record["command_evidence"]
        ):
            raise ManagedStateError(
                f"managed-state record {index} lacks required command evidence"
            )
        for evidence in record["command_evidence"]:
            if not (
                isinstance(evidence, dict)
                and isinstance(evidence.get("argv"), list)
                and all(isinstance(argument, str) for argument in evidence["argv"])
                and "returncode" in evidence
                and (
                    evidence.get("returncode") is None
                    or type(evidence["returncode"]) is int
                )
                and isinstance(evidence.get("stdout"), str)
                and isinstance(evidence.get("stderr"), str)
                and isinstance(evidence.get("timed_out"), bool)
            ):
                raise ManagedStateError(f"managed-state record {index} has invalid command evidence")
        outcome = verification["outcome"]
        evidence_items = record["command_evidence"]
        if len(evidence_items) > len(expected_commands) or (
            outcome != ActionOutcome.INTERRUPTED.value and not evidence_items
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent command evidence count"
            )
        for evidence, reviewed_command in zip(
            evidence_items, expected_commands
        ):
            if not _matches_recorded_command(
                evidence["argv"],
                reviewed_command,
                platform_name=context["platform"],
                manager_name=package_manager["name"],
            ):
                raise ManagedStateError(
                    f"managed-state record {index} has unreviewed command evidence"
                )
        if (
            context["platform"] == "Linux"
            and package_manager["name"] in {"apt", "dnf", "pacman"}
            and len(
                {
                    tuple(evidence["argv"][: -len(reviewed_command)])
                    for evidence, reviewed_command in zip(
                        evidence_items, expected_commands
                    )
                }
            )
            > 1
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent supervisor evidence"
            )
        if outcome in {
            ActionOutcome.SUCCEEDED.value,
            ActionOutcome.VERIFICATION_FAILED.value,
        } and (
            len(evidence_items) != len(expected_commands)
            or any(
                evidence["returncode"] != 0 or evidence["timed_out"]
                for evidence in evidence_items
            )
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent "
                + (
                    "success evidence"
                    if outcome == ActionOutcome.SUCCEEDED.value
                    else "completed command evidence"
                )
            )
        terminal = evidence_items[-1] if evidence_items else None
        if any(
            evidence["returncode"] != 0 or evidence["timed_out"]
            for evidence in evidence_items[:-1]
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent preceding command evidence"
            )
        if (
            outcome == ActionOutcome.COMMAND_FAILED.value
            and (
                terminal is None
                or terminal["returncode"] in {None, 0}
                or terminal["timed_out"]
                or (
                    context["platform"] == "Linux"
                    and package_manager["name"] in {"apt", "dnf", "pacman"}
                    and terminal["returncode"] in {125, 126, 127, 137, -9}
                )
            )
        ) or (
            outcome == ActionOutcome.TIMED_OUT.value
            and (
                terminal is None
                or not terminal["timed_out"]
                or terminal["returncode"] is not None
                or (
                    context["platform"] == "Linux"
                    and package_manager["name"] in {"apt", "dnf", "pacman"}
                )
            )
        ) or (
            outcome == ActionOutcome.FORCED_KILL.value
            and (
                terminal is None
                or terminal["timed_out"]
                or terminal["returncode"] not in {137, -9}
            )
        ) or (
            outcome == ActionOutcome.INTERRUPTED.value
            and terminal is not None
            and (terminal["timed_out"] or terminal["returncode"] is None)
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent terminal command evidence"
            )
        if outcome == ActionOutcome.SUCCEEDED.value and (
            not verification["verified_paths"]
            or (
                provider_spec.probe_policy is ProbePolicy.ALL
                and len(verification["verified_paths"])
                != len(provider_spec.probes)
            )
        ):
            raise ManagedStateError(
                f"managed-state record {index} has inconsistent success evidence"
            )
        if outcome not in {
            ActionOutcome.SUCCEEDED.value,
            ActionOutcome.VERIFICATION_FAILED.value,
        } and verification["verified_paths"]:
            raise ManagedStateError(
                f"managed-state record {index} has impossible pre-verification paths"
            )
    return value


def _is_absolute_for_platform(value: str, platform_name: object) -> bool:
    if not value:
        return False
    if platform_name in {"nt", "Windows"}:
        return PureWindowsPath(value).is_absolute()
    return posixpath.isabs(value)


def _matches_recorded_command(
    observed: list[str],
    reviewed: list[str],
    *,
    platform_name: str,
    manager_name: str,
) -> bool:
    if platform_name != "Linux" or manager_name not in {"apt", "dnf", "pacman"}:
        return observed == reviewed
    prefix_length = len(observed) - len(reviewed)
    if prefix_length not in {4, 7} or observed[prefix_length:] != reviewed:
        return False
    supervisor_index = 0
    if prefix_length == 7:
        if (
            not _is_absolute_for_platform(observed[0], platform_name)
            or observed[1:3] != ["-n", "--"]
        ):
            return False
        supervisor_index = 3
    supervisor = observed[supervisor_index : supervisor_index + 4]
    return (
        _is_absolute_for_platform(supervisor[0], platform_name)
        and supervisor[1] == "--signal=TERM"
        and supervisor[2]
        == f"--kill-after={ELEVATED_TERM_TO_KILL_GRACE_SECONDS}s"
        and supervisor[3].endswith("s")
        and supervisor[3][:-1].isdigit()
        and int(supervisor[3][:-1]) > 0
    )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise ManagedStateError(
                f"managed state contains duplicate JSON key: {name}"
            )
        value[name] = item
    return value


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    try:
        temporary: Path | None = None
        replace_attempted = False
        missing_directories = _missing_directories(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_attempted = True
        os.replace(temporary, path)
        temporary = None
        _sync_parent_directory(path.parent)
        for directory in reversed(missing_directories):
            _sync_parent_directory(directory.parent)
    except OSError as error:
        temporary = locals().get("temporary")
        replace_attempted = bool(locals().get("replace_attempted", False))
        _discard_temporary(temporary)
        outcome = (
            PersistenceOutcome.UNKNOWN
            if replace_attempted
            else PersistenceOutcome.FAILED
        )
        raise PersistenceError(outcome, f"managed-state atomic persistence failed: {error}") from error
    except KeyboardInterrupt as error:
        temporary = locals().get("temporary")
        replace_attempted = bool(locals().get("replace_attempted", False))
        _discard_temporary(temporary)
        outcome = (
            PersistenceOutcome.UNKNOWN
            if replace_attempted
            else PersistenceOutcome.FAILED
        )
        raise PersistenceInterrupted(
            outcome, "managed-state persistence was interrupted"
        ) from error


def _discard_temporary(temporary: Path | None) -> None:
    if temporary is None:
        return
    try:
        temporary.unlink()
    except OSError:
        pass


def _missing_directories(directory: Path) -> tuple[Path, ...]:
    missing = []
    current = directory
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(missing))


def _sync_parent_directory(directory: Path) -> None:
    """Confirm replacement-directory durability where the platform supports it."""

    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(
    plan: ProviderPlan,
    report: PlanExecutionReport,
    index: int,
    requested_at: str,
    completed_at: str,
) -> dict[str, Any]:
    action = plan.actions[index]
    observed = report.actions[index]
    capability = get_capability(action.capability_id)
    provider = next(
        item for item in capability.providers if item.provider_id == action.provider_id
    )
    return {
        "id": str(uuid.uuid4()),
        "requested_at": requested_at,
        "completed_at": completed_at,
        "recorded_at": _timestamp(),
        "capability_id": action.capability_id,
        "provider": {"id": action.provider_id, "origin": provider.origin.value},
        "package_manager": {
            "name": action.manager,
            "executable": action.manager_state.executable_path,
            "architecture": action.manager_state.architecture,
        },
        "installation_unit": action.installation_unit,
        "execution_context": asdict(plan.context),
        "requested_action": {
            "kind": (
                "native-replacement"
                if action.target_architecture is not None
                else "install"
            ),
            "reason": action.reason,
            "commands": [list(command) for command in action.commands],
            "target_architecture": action.target_architecture,
            "displaces_verified_paths": list(action.displaces_verified_paths),
            "translated_manager_fallback_authorized": (
                action.translated_manager_fallback_authorized
            ),
        },
        "verification": {
            "outcome": observed.outcome.value,
            "verified_paths": list(observed.final_verified_paths),
            "detail": observed.detail,
        },
        "command_evidence": [asdict(command) for command in observed.commands],
        "ownership": False,
    }


def execute_provider_plan(
    plan: ProviderPlan,
    *,
    state_path: Path | None = None,
    executor: Callable[..., PlanExecutionReport] = _execute_provider_plan_unmanaged,
    **executor_arguments: Any,
) -> ManagedExecutionResult:
    """Preflight provenance, execute, then independently persist attempted mutations."""

    if not plan.actions:
        return ManagedExecutionResult(
            executor(plan, **executor_arguments), PersistenceOutcome.NOT_REQUIRED
        )
    mutation_authorized = executor_arguments.get("allow_provider_mutation") is True
    if not mutation_authorized:
        executor_arguments = {**executor_arguments, "allow_provider_mutation": False}
        return ManagedExecutionResult(
            executor(plan, **executor_arguments), PersistenceOutcome.NOT_REQUIRED
        )
    if plan.context is None:
        raise ManagedStateError("mutating provider plan has no execution context")
    result: ManagedExecutionResult | None = None
    pending_interruption: (
        ProviderPlanInterrupted
        | ManagedExecutionInterrupted
        | PersistenceInterrupted
        | None
    ) = None
    try:
        with _MANAGED_STATE_LOCK, _provider_execution_transaction():
            try:
                path = state_path or managed_state_path(
                    platform_name=plan.context.platform
                )
                document = load_document(path)
            except ManagedStateError as error:
                result = ManagedExecutionResult(
                    None, PersistenceOutcome.BLOCKED, str(error)
                )
            else:
                requested_at = _timestamp()
                interruption: (
                    ProviderPlanInterrupted | ManagedExecutionInterrupted | None
                ) = None
                try:
                    report = executor(plan, **executor_arguments)
                except ProviderPlanInterrupted as error:
                    interruption = error
                    pending_interruption = error
                    report = error.report
                except KeyboardInterrupt as error:
                    interruption = ManagedExecutionInterrupted(error)
                    pending_interruption = interruption
                    report = _unknown_interrupted_report(plan)
                try:
                    completed_at, attempted_indexes, updated = _prepare_update(
                        document, plan, report, requested_at
                    )
                except KeyboardInterrupt as error:
                    if interruption is None:
                        interruption = ManagedExecutionInterrupted(error)
                        pending_interruption = interruption
                    try:
                        completed_at, attempted_indexes, updated = _prepare_update(
                            document, plan, report, requested_at
                        )
                    except Exception as construction_error:
                        result, finalization_interruption = (
                            _record_construction_failure_result(
                                report, construction_error
                            )
                        )
                        if (
                            finalization_interruption is not None
                            and pending_interruption is None
                        ):
                            pending_interruption = ManagedExecutionInterrupted(
                                finalization_interruption
                            )
                except Exception as construction_error:
                    result, finalization_interruption = (
                        _record_construction_failure_result(
                            report, construction_error
                        )
                    )
                    if (
                        finalization_interruption is not None
                        and pending_interruption is None
                    ):
                        pending_interruption = ManagedExecutionInterrupted(
                            finalization_interruption
                        )

                if result is None and not attempted_indexes:
                    result = ManagedExecutionResult(
                        report, PersistenceOutcome.NOT_REQUIRED
                    )
                elif result is None:
                    try:
                        _atomic_write(path, updated)
                        result = ManagedExecutionResult(
                            report, PersistenceOutcome.SUCCEEDED
                        )
                    except PersistenceInterrupted as error:
                        result, _ = _guarded_persistence_failure_result(
                            report, error.outcome, error.detail
                        )
                        pending_interruption = error
                    except PersistenceError as error:
                        result, finalization_interruption = (
                            _guarded_persistence_failure_result(
                                report, error.outcome, error.detail
                            )
                        )
                        if (
                            finalization_interruption is not None
                            and pending_interruption is None
                        ):
                            pending_interruption = ManagedExecutionInterrupted(
                                finalization_interruption
                            )
                    except KeyboardInterrupt as error:
                        result = ManagedExecutionResult(
                            report, PersistenceOutcome.SUCCEEDED
                        )
                        pending_interruption = ManagedExecutionInterrupted(error)

                if interruption is not None and pending_interruption is None:
                    pending_interruption = interruption
                if pending_interruption is not None:
                    pending_interruption.managed_result = result
                    raise pending_interruption
    except (
        ProviderPlanInterrupted,
        ManagedExecutionInterrupted,
        PersistenceInterrupted,
    ):
        raise
    except KeyboardInterrupt as error:
        final_interruption = pending_interruption or ManagedExecutionInterrupted(error)
        final_interruption.managed_result = result
        raise final_interruption

    if result is None:
        raise RuntimeError("managed provider execution produced no result")
    return result


def _prepare_update(
    document: dict[str, Any],
    plan: ProviderPlan,
    report: PlanExecutionReport,
    requested_at: str,
) -> tuple[str, tuple[int, ...], dict[str, Any]]:
    completed_at = _timestamp()
    attempted_indexes = tuple(
        index
        for index, action in enumerate(report.actions)
        if (action.commands or action.outcome is ActionOutcome.INTERRUPTED)
        and action.outcome is not ActionOutcome.ALREADY_SATISFIED
    )
    updated = {
        **document,
        "records": [
            *document["records"],
            *(
                _record(plan, report, index, requested_at, completed_at)
                for index in attempted_indexes
            ),
        ],
    }
    return completed_at, attempted_indexes, updated


def _record_construction_failure_result(
    report: PlanExecutionReport, error: Exception
) -> tuple[ManagedExecutionResult, KeyboardInterrupt | None]:
    return _guarded_persistence_failure_result(
        report,
        PersistenceOutcome.FAILED,
        (
            "provenance record construction failed before persistence began: "
            f"{type(error).__name__}: {error}"
        ),
    )


def _guarded_persistence_failure_result(
    report: PlanExecutionReport,
    outcome: PersistenceOutcome,
    detail: str,
) -> tuple[ManagedExecutionResult, KeyboardInterrupt | None]:
    try:
        return _persistence_failure_result(report, outcome, detail), None
    except KeyboardInterrupt as error:
        return _persistence_failure_result(report, outcome, detail), error


def _unknown_interrupted_report(plan: ProviderPlan) -> PlanExecutionReport:
    return PlanExecutionReport(
        plan.context,
        plan.requested_capabilities,
        PlanOutcome.PARTIAL_FAILURE,
        tuple(
            ActionReport(
                action.capability_id,
                action.provider_id,
                action.manager,
                action.installation_unit,
                ActionOutcome.INTERRUPTED,
                detail=(
                    "authorized execution was interrupted; exact per-action command "
                    "progress and resulting provider state are unknown"
                ),
                target_architecture=action.target_architecture,
                displaces_verified_paths=action.displaces_verified_paths,
                translated_manager_fallback_authorized=(
                    action.translated_manager_fallback_authorized
                ),
            )
            for action in plan.actions
        ),
        (
            "provider mutation may have started or completed",
            "do not retry automatically or immediately and do not attempt rollback or removal",
            "rediscover current machine state and generate a fresh plan before any later mutation",
        ),
    )


def _persistence_failure_result(
    report: PlanExecutionReport,
    outcome: PersistenceOutcome,
    detail: str,
) -> ManagedExecutionResult:
    return ManagedExecutionResult(
        report,
        outcome,
        detail,
        (
            "provider execution evidence is preserved in this result",
            "provenance was not durably recorded"
            if outcome is PersistenceOutcome.FAILED
            else "whether provenance became durable is unknown",
            "do not rerun provider mutation automatically and do not uninstall or roll back",
            "rediscover current machine state and generate a fresh plan before any later mutation",
        ),
    )


def provenance_for_capability(
    document: dict[str, Any], capability_id: str
) -> tuple[dict[str, Any], ...]:
    return tuple(
        record
        for record in document["records"]
        if record.get("capability_id") == capability_id
    )
