"""Explicit, bounded execution of immutable provider plans."""

from __future__ import annotations

import ntpath
import os
import posixpath
import shutil
import subprocess
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

from .capabilities import (
    Availability,
    CapabilitySpec,
    CapabilityState,
    MachineState,
    current_machine,
    detect_capability,
    get_capability,
)
from .provider_plans import (
    EnvironmentRefresh,
    ExecutionPrivilege,
    PackageManagerState,
    ProviderAction,
    ProviderPlan,
    adapter_commands,
    adapter_environment_refresh,
    adapter_execution_privilege,
    PlanningError,
    validate_capability_state,
)
from .python_selection import normalize_architecture


DEFAULT_COMMAND_TIMEOUT_SECONDS = 300


class ExecutionContractError(RuntimeError):
    """Raised before mutation when a plan is stale or not catalogue-authoritative."""


class PlanOutcome(str, Enum):
    NO_CHANGES = "no-changes"
    REFUSED = "refused"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILURE = "partial-failure"


class ActionOutcome(str, Enum):
    REFUSED = "refused"
    NOT_ATTEMPTED = "not-attempted"
    ALREADY_SATISFIED = "already-satisfied"
    SUCCEEDED = "succeeded"
    MANAGER_UNAVAILABLE = "manager-unavailable"
    PRIVILEGE_UNAVAILABLE = "privilege-unavailable"
    COMMAND_FAILED = "command-failed"
    TIMED_OUT = "timed-out"
    VERIFICATION_FAILED = "verification-failed"


@dataclass(frozen=True)
class CommandReport:
    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class ActionReport:
    capability_id: str
    provider_id: str
    manager: str
    installation_unit: str
    outcome: ActionOutcome
    commands: tuple[CommandReport, ...] = ()
    final_verified_paths: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class PlanExecutionReport:
    context: MachineState | None
    requested_capabilities: tuple[str, ...]
    outcome: PlanOutcome
    actions: tuple[ActionReport, ...]
    recovery_guidance: tuple[str, ...] = ()


Runner = Callable[[tuple[str, ...], int], subprocess.CompletedProcess[str]]
Detector = Callable[[CapabilitySpec, MachineState], CapabilityState]
ContextReader = Callable[[], MachineState]
ManagerVerifier = Callable[[PackageManagerState, MachineState], bool]
PrivilegeResolver = Callable[[ProviderAction], str | None]
EnvironmentRefresher = Callable[[ProviderAction], Mapping[str, str]]


def _normalized_context(machine: MachineState) -> MachineState:
    return MachineState(
        machine.platform,
        normalize_architecture(machine.architecture),
        machine.execution_environment,
    )


def _path_key(path: str, machine: MachineState) -> str:
    if machine.platform == "Windows":
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


def _path_is_absolute(path: str, machine: MachineState) -> bool:
    return (
        PureWindowsPath(path).is_absolute()
        if machine.platform == "Windows"
        else PurePosixPath(path).is_absolute()
    )


def _run(argv: tuple[str, ...], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )


def _detect(capability: CapabilitySpec, machine: MachineState) -> CapabilityState:
    return detect_capability(capability, machine)


def _verify_manager(state: PackageManagerState, machine: MachineState) -> bool:
    path = Path(state.executable_path)
    try:
        if not path.is_file():
            return False
        resolved = str(path.resolve(strict=True))
    except OSError:
        return False
    expected = state.resolved_executable_path or state.executable_path
    return _path_key(resolved, machine) == _path_key(expected, machine)


def _resolve_privilege(action: ProviderAction) -> str | None:
    if action.execution_privilege is ExecutionPrivilege.CURRENT_USER:
        return ""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return ""
    sudo = shutil.which("sudo")
    return sudo if sudo and Path(sudo).is_absolute() else None


def _windows_persisted_path() -> str:
    if os.name != "nt":
        return os.environ.get("PATH", "")
    import winreg

    values: list[str] = []
    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    )
    for hive, key_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        if isinstance(value, str) and value:
            values.append(os.path.expandvars(value))
    current = os.environ.get("PATH", "")
    if current:
        values.append(current)
    return os.pathsep.join(values)


def _refresh_environment(action: ProviderAction) -> Mapping[str, str]:
    if action.environment_refresh is EnvironmentRefresh.NONE:
        return {}
    if action.environment_refresh is EnvironmentRefresh.PATH:
        return {"PATH": _windows_persisted_path()}
    if action.environment_refresh is EnvironmentRefresh.MANAGER_BIN:
        manager_bin = str(Path(action.manager_state.executable_path).parent)
        current = os.environ.get("PATH", "")
        return {"PATH": manager_bin + (os.pathsep + current if current else "")}
    raise ExecutionContractError(
        f"unsupported environment refresh: {action.environment_refresh}"
    )


@contextmanager
def _temporary_environment(updates: Mapping[str, str]):
    previous = {name: os.environ.get(name) for name in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _validate_action(action: ProviderAction, context: MachineState) -> None:
    try:
        capability = get_capability(action.capability_id)
    except KeyError as error:
        raise ExecutionContractError(
            f"unknown action capability: {action.capability_id}"
        ) from error
    provider = next(
        (item for item in capability.providers if item.provider_id == action.provider_id),
        None,
    )
    if provider is None or not provider.supports(context) or not provider.satisfies_capability:
        raise ExecutionContractError(
            f"action provider is not catalogue-supported: {action.provider_id}"
        )
    package = next(
        (
            item
            for item in provider.packages
            if item.manager == action.manager
            and item.installation_unit == action.installation_unit
            and context.platform in item.platforms
            and (
                not item.architectures
                or normalize_architecture(context.architecture) in item.architectures
            )
        ),
        None,
    )
    if package is None:
        raise ExecutionContractError(
            f"action package is not catalogue-owned: {action.installation_unit}"
        )
    if action.manager_state.execution_environment != context.execution_environment:
        raise ExecutionContractError("action package manager is from another environment")
    if not _path_is_absolute(action.manager_state.executable_path, context) or (
        action.manager_state.resolved_executable_path is not None
        and not _path_is_absolute(action.manager_state.resolved_executable_path, context)
    ):
        raise ExecutionContractError("action package-manager identity is not absolute")
    expected_commands = adapter_commands(
        action.manager,
        action.installation_unit,
        executable_path=action.manager_state.executable_path,
        target_architecture=action.target_architecture,
    )
    if action.commands != expected_commands:
        raise ExecutionContractError("action commands do not match the reviewed adapter")
    if action.execution_privilege is not adapter_execution_privilege(action.manager):
        raise ExecutionContractError("action privilege does not match the reviewed adapter")
    if action.environment_refresh is not adapter_environment_refresh(action.manager):
        raise ExecutionContractError("action refresh does not match the reviewed adapter")
    if (
        action.verification.probes != provider.probes
        or action.verification.policy is not provider.probe_policy
        or action.shared_package is not provider.shared_package
    ):
        raise ExecutionContractError("action verification does not match the catalogue")
    if action.target_architecture is not None and normalize_architecture(
        action.target_architecture
    ) != normalize_architecture(context.architecture):
        raise ExecutionContractError("action target architecture is not native to the plan")
    if bool(action.displaces_verified_paths) != (action.target_architecture is not None):
        raise ExecutionContractError("native replacement evidence is incomplete")
    if any(
        not _path_is_absolute(path, context)
        for path in action.displaces_verified_paths
    ):
        raise ExecutionContractError("displaced provider identity is not absolute")


def _validate_plan(plan: ProviderPlan, current: MachineState) -> MachineState:
    if plan.context is None:
        if plan.actions:
            raise ExecutionContractError("mutating plan has no execution context")
        return current
    context = _normalized_context(plan.context)
    if context != _normalized_context(current):
        raise ExecutionContractError("provider plan is for a different execution context")
    if len(plan.requested_capabilities) != len(set(plan.requested_capabilities)):
        raise ExecutionContractError("provider plan has duplicate requested capabilities")
    seen: set[str] = set()
    for action in plan.actions:
        if action.capability_id not in plan.requested_capabilities:
            raise ExecutionContractError("action capability was not requested")
        if action.capability_id in seen:
            raise ExecutionContractError("provider plan has duplicate capability actions")
        seen.add(action.capability_id)
        _validate_action(action, context)
    return context


def _verified_provider_paths(
    action: ProviderAction,
    state: CapabilityState,
) -> tuple[str, ...]:
    provider = next(
        (item for item in state.providers if item.provider.provider_id == action.provider_id),
        None,
    )
    if provider is None or provider.availability is not Availability.AVAILABLE:
        return ()
    if (
        provider.provider.probes != action.verification.probes
        or provider.provider.probe_policy is not action.verification.policy
    ):
        return ()
    verified = tuple(item for item in provider.executables if item.verified)
    if action.target_architecture is not None and (
        not verified
        or any(
            normalize_architecture(item.architecture)
            != normalize_architecture(action.target_architecture)
            for item in verified
        )
    ):
        return ()
    return tuple(item.path for item in verified if item.path is not None)


def _command_report(
    argv: tuple[str, ...], result: subprocess.CompletedProcess[str]
) -> CommandReport:
    return CommandReport(
        argv,
        result.returncode,
        result.stdout or "",
        result.stderr or "",
    )


def execute_provider_plan(
    plan: ProviderPlan,
    *,
    allow_provider_mutation: bool = False,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    runner: Runner = _run,
    detector: Detector = _detect,
    current_context: ContextReader = current_machine,
    manager_verifier: ManagerVerifier = _verify_manager,
    privilege_resolver: PrivilegeResolver = _resolve_privilege,
    environment_refresher: EnvironmentRefresher = _refresh_environment,
) -> PlanExecutionReport:
    """Consume one reviewed plan, mutate only when authorized, and report outcomes."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = _validate_plan(plan, current_context())
    if not plan.actions:
        return PlanExecutionReport(
            context,
            plan.requested_capabilities,
            PlanOutcome.NO_CHANGES,
            (),
        )
    if not allow_provider_mutation:
        return PlanExecutionReport(
            context,
            plan.requested_capabilities,
            PlanOutcome.REFUSED,
            tuple(
                ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    ActionOutcome.REFUSED,
                    detail="provider mutation was not explicitly authorized",
                )
                for action in plan.actions
            ),
            ("rerun with explicit provider-mutation authorization",),
        )

    reports: list[ActionReport] = []
    for action in plan.actions:
        capability = get_capability(action.capability_id)
        before = detector(capability, context)
        try:
            validate_capability_state(before, expected_context=context)
        except PlanningError as error:
            raise ExecutionContractError(
                f"pre-action detection is not authoritative: {error}"
            ) from error
        existing_paths = _verified_provider_paths(action, before)
        if existing_paths:
            reports.append(
                ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    ActionOutcome.ALREADY_SATISFIED,
                    final_verified_paths=existing_paths,
                    detail="planned provider already verifies; no command executed",
                )
            )
            continue
        if not manager_verifier(action.manager_state, context):
            reports.append(
                ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    ActionOutcome.MANAGER_UNAVAILABLE,
                    detail="verified package-manager identity is no longer available",
                )
            )
            return _failed_report(plan, context, reports)
        elevation = privilege_resolver(action)
        if elevation is None:
            reports.append(
                ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    ActionOutcome.PRIVILEGE_UNAVAILABLE,
                    detail="system privilege is required but no safe elevation path is available",
                )
            )
            return _failed_report(plan, context, reports)

        commands: list[CommandReport] = []
        for reviewed_argv in action.commands:
            argv = (elevation, *reviewed_argv) if elevation else reviewed_argv
            try:
                result = runner(argv, timeout_seconds)
            except subprocess.TimeoutExpired as error:
                commands.append(
                    CommandReport(
                        argv,
                        None,
                        _timeout_text(error.stdout),
                        _timeout_text(error.stderr),
                        timed_out=True,
                    )
                )
                reports.append(
                    ActionReport(
                        action.capability_id,
                        action.provider_id,
                        action.manager,
                        action.installation_unit,
                        ActionOutcome.TIMED_OUT,
                        tuple(commands),
                        detail=f"command exceeded {timeout_seconds} seconds",
                    )
                )
                return _failed_report(plan, context, reports)
            except OSError as error:
                commands.append(CommandReport(argv, None, "", str(error)))
                reports.append(
                    ActionReport(
                        action.capability_id,
                        action.provider_id,
                        action.manager,
                        action.installation_unit,
                        ActionOutcome.COMMAND_FAILED,
                        tuple(commands),
                        detail=f"command could not start: {error}",
                    )
                )
                return _failed_report(plan, context, reports)
            commands.append(_command_report(argv, result))
            if result.returncode != 0:
                reports.append(
                    ActionReport(
                        action.capability_id,
                        action.provider_id,
                        action.manager,
                        action.installation_unit,
                        ActionOutcome.COMMAND_FAILED,
                        tuple(commands),
                        detail=f"command exited with status {result.returncode}",
                    )
                )
                return _failed_report(plan, context, reports)

        with _temporary_environment(environment_refresher(action)):
            after = detector(capability, context)
        try:
            validate_capability_state(after, expected_context=context)
        except PlanningError as error:
            final_paths = ()
            verification_detail = f"post-action detection is not authoritative: {error}"
        else:
            final_paths = _verified_provider_paths(action, after)
            verification_detail = (
                "package-manager success did not produce the planned verified provider"
            )
        if not final_paths:
            reports.append(
                ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    ActionOutcome.VERIFICATION_FAILED,
                    tuple(commands),
                    detail=verification_detail,
                )
            )
            return _failed_report(plan, context, reports)
        reports.append(
            ActionReport(
                action.capability_id,
                action.provider_id,
                action.manager,
                action.installation_unit,
                ActionOutcome.SUCCEEDED,
                tuple(commands),
                final_paths,
                "planned provider rediscovered and verified",
            )
        )

    return PlanExecutionReport(
        context,
        plan.requested_capabilities,
        PlanOutcome.SUCCEEDED,
        tuple(reports),
    )


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _failed_report(
    plan: ProviderPlan,
    context: MachineState,
    reports: list[ActionReport],
) -> PlanExecutionReport:
    reports.extend(
        ActionReport(
            action.capability_id,
            action.provider_id,
            action.manager,
            action.installation_unit,
            ActionOutcome.NOT_ATTEMPTED,
            detail="not attempted because an earlier provider action failed",
        )
        for action in plan.actions[len(reports) :]
    )
    return PlanExecutionReport(
        context,
        plan.requested_capabilities,
        PlanOutcome.PARTIAL_FAILURE,
        tuple(reports),
        (
            "the package manager may have left partial host state",
            "inspect the reported command output, restore provider availability if needed, "
            "then regenerate a plan and retry; repeated package-manager operations are expected "
            "to be idempotent",
        ),
    )
