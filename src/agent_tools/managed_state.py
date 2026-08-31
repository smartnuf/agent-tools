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

from .capabilities import get_capability
from .provider_execution import (
    ActionOutcome,
    ActionReport,
    PlanOutcome,
    PlanExecutionReport,
    ProviderPlanInterrupted,
    _execute_provider_plan_unmanaged,
    _provider_execution_transaction,
)
from .provider_plans import ProviderPlan


SCHEMA_VERSION = 1
_MANAGED_STATE_LOCK = threading.RLock()


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
    home = home or Path.home()
    if platform_name in {"nt", "Windows"}:
        root = env.get("LOCALAPPDATA")
        if not root:
            raise ManagedStateError("LOCALAPPDATA is unavailable")
        if not PureWindowsPath(root).is_absolute():
            raise ManagedStateError("LOCALAPPDATA is not an absolute Windows path")
        return Path(root) / "agent-tools" / "managed-state.json"
    if platform_name in {"Darwin", "darwin"}:
        return (
            home
            / "Library"
            / "Application Support"
            / "agent-tools"
            / "managed-state.json"
        )
    configured_value = env.get("XDG_STATE_HOME")
    root = (
        Path(configured_value)
        if configured_value is not None and posixpath.isabs(configured_value)
        else home / ".local" / "state"
    )
    return root / "agent-tools" / "managed-state.json"


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
    if version != SCHEMA_VERSION:
        raise ManagedStateError(f"unsupported managed-state schema version: {version!r}")
    records = value.get("records")
    if not isinstance(records, list) or not all(
        isinstance(item, dict) for item in records
    ):
        raise ManagedStateError("managed-state records must be a JSON array of objects")
    record_ids: set[str] = set()
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
            uuid.UUID(record["id"])
        except (ValueError, AttributeError) as error:
            raise ManagedStateError(f"managed-state record {index} has an invalid id") from error
        if record["id"] in record_ids:
            raise ManagedStateError(f"managed-state record {index} has a duplicate id")
        record_ids.add(record["id"])
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
        if not all(
            isinstance(package_manager.get(name), str)
            for name in ("name", "executable")
        ):
            raise ManagedStateError(
                f"managed-state record {index} has invalid package-manager evidence"
            )
        if not all(
            isinstance(context.get(name), str)
            for name in ("platform", "architecture", "execution_environment")
        ):
            raise ManagedStateError(f"managed-state record {index} has invalid execution context")
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
        if not (
            isinstance(verification.get("outcome"), str)
            and verification["outcome"]
            in {outcome.value for outcome in ActionOutcome}
            and isinstance(verification.get("verified_paths"), list)
            and all(isinstance(item, str) for item in verification["verified_paths"])
            and isinstance(verification.get("detail"), str)
        ):
            raise ManagedStateError(f"managed-state record {index} has invalid verification evidence")
        for evidence in record["command_evidence"]:
            if not (
                isinstance(evidence, dict)
                and isinstance(evidence.get("argv"), list)
                and all(isinstance(argument, str) for argument in evidence["argv"])
                and (evidence.get("returncode") is None or isinstance(evidence["returncode"], int))
                and isinstance(evidence.get("stdout"), str)
                and isinstance(evidence.get("stderr"), str)
                and isinstance(evidence.get("timed_out"), bool)
            ):
                raise ManagedStateError(f"managed-state record {index} has invalid command evidence")
    return value


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
    temporary: Path | None = None
    replaced = False
    try:
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
        os.replace(temporary, path)
        replaced = True
        temporary = None
        _sync_parent_directory(path.parent)
        for directory in reversed(missing_directories):
            _sync_parent_directory(directory.parent)
    except OSError as error:
        _discard_temporary(temporary)
        outcome = PersistenceOutcome.UNKNOWN if replaced else PersistenceOutcome.FAILED
        raise PersistenceError(outcome, f"managed-state atomic persistence failed: {error}") from error
    except KeyboardInterrupt as error:
        _discard_temporary(temporary)
        outcome = PersistenceOutcome.UNKNOWN if replaced else PersistenceOutcome.FAILED
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
    mutation_authorized = bool(executor_arguments.get("allow_provider_mutation"))
    if not mutation_authorized:
        return ManagedExecutionResult(
            executor(plan, **executor_arguments), PersistenceOutcome.NOT_REQUIRED
        )
    if plan.context is None:
        raise ManagedStateError("mutating provider plan has no execution context")
    with _MANAGED_STATE_LOCK, _provider_execution_transaction():
        try:
            path = state_path or managed_state_path(
                platform_name=plan.context.platform
            )
            document = load_document(path)
        except ManagedStateError as error:
            return ManagedExecutionResult(None, PersistenceOutcome.BLOCKED, str(error))

        requested_at = _timestamp()
        interruption: ProviderPlanInterrupted | ManagedExecutionInterrupted | None = None
        try:
            report = executor(plan, **executor_arguments)
        except ProviderPlanInterrupted as error:
            interruption = error
            report = error.report
        except KeyboardInterrupt as error:
            interruption = ManagedExecutionInterrupted(error)
            report = _unknown_interrupted_report(plan)
        completed_at = _timestamp()
        attempted_indexes = tuple(
            index
            for index, action in enumerate(report.actions)
            if (
                action.commands or action.outcome is ActionOutcome.INTERRUPTED
            )
            and action.outcome is not ActionOutcome.ALREADY_SATISFIED
        )
        if not attempted_indexes:
            result = ManagedExecutionResult(report, PersistenceOutcome.NOT_REQUIRED)
            if interruption is not None:
                interruption.managed_result = result
                raise interruption
            return result
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
        try:
            _atomic_write(path, updated)
        except PersistenceInterrupted as error:
            result = _persistence_failure_result(report, error.outcome, error.detail)
            error.managed_result = result
            raise
        except PersistenceError as error:
            result = _persistence_failure_result(report, error.outcome, error.detail)
        else:
            result = ManagedExecutionResult(report, PersistenceOutcome.SUCCEEDED)
        if interruption is not None:
            interruption.managed_result = result
            raise interruption
        return result


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
