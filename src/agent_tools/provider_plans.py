"""Pure provider-plan generation and closed package-manager adapters."""

from __future__ import annotations

import ntpath
import posixpath
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable

from .capabilities import (
    Availability,
    CapabilityState,
    ExecutableEvidenceError,
    ExecutableProbe,
    ProviderPackage,
    ProviderSpec,
    ProbePolicy,
    MachineState,
    capability_availability,
    consolidate_executable_evidence,
    get_capability,
    provider_availability,
)
from .python_selection import NativeStatus, normalize_architecture


class PlanningError(RuntimeError):
    """Raised when verified state cannot produce a safe provider plan."""


class ExecutionPrivilege(str, Enum):
    """Privilege level required to execute an already reviewed action."""

    CURRENT_USER = "current-user"
    SYSTEM = "system"


class EnvironmentRefresh(str, Enum):
    """Environment refresh required after an action and before verification."""

    NONE = "none"
    PATH = "path"
    MANAGER_BIN = "manager-bin"


@dataclass(frozen=True)
class PackageManagerState:
    """Verified primary observations for one package-manager executable."""

    manager: str
    executable_path: str
    execution_environment: str
    architecture: str | None = None
    resolved_executable_path: str | None = None
    installation_root: str | None = None

    def native_status(self, context: MachineState) -> NativeStatus:
        known_architectures = {"x86_64", "x86", "arm64", "arm"}
        manager_architecture = normalize_architecture(self.architecture)
        context_architecture = normalize_architecture(context.architecture)
        if (
            manager_architecture not in known_architectures
            or context_architecture not in known_architectures
        ):
            return NativeStatus.UNKNOWN
        return (
            NativeStatus.NATIVE
            if manager_architecture == context_architecture
            else NativeStatus.TRANSLATED
        )


@dataclass(frozen=True)
class VerificationRequirement:
    probes: tuple[ExecutableProbe, ...]
    policy: ProbePolicy


@dataclass(frozen=True)
class ProviderAction:
    capability_id: str
    provider_id: str
    manager_state: PackageManagerState
    installation_unit: str
    reason: str
    verification: VerificationRequirement
    execution_privilege: ExecutionPrivilege
    environment_refresh: EnvironmentRefresh
    commands: tuple[tuple[str, ...], ...]
    shared_package: bool
    displaces_verified_paths: tuple[str, ...] = ()
    target_architecture: str | None = None
    environment_path_entries: tuple[str, ...] = ()
    translated_manager_fallback_authorized: bool = False

    @property
    def manager(self) -> str:
        return self.manager_state.manager


@dataclass(frozen=True)
class ProviderPlan:
    requested_capabilities: tuple[str, ...]
    context: MachineState | None
    actions: tuple[ProviderAction, ...]

    @property
    def changes_host(self) -> bool:
        return bool(self.actions)


def adapter_commands(
    manager: str,
    unit: str,
    *,
    executable_path: str | None = None,
    target_architecture: str | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Render inspectable argv without executing it."""

    executable = executable_path or {
        "winget": "winget",
        "apt": "apt-get",
        "dnf": "dnf",
        "pacman": "pacman",
        "brew": "brew",
    }.get(manager, manager)
    winget = (
        executable, "install", "--id", unit, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
    )
    if target_architecture is not None and manager == "winget":
        winget_architectures = {"x86_64": "x64", "x86": "x86", "arm64": "arm64", "arm": "arm"}
        try:
            winget_architecture = winget_architectures[target_architecture]
        except KeyError as error:
            raise PlanningError(
                f"unsupported WinGet target architecture: {target_architecture}"
            ) from error
        winget += ("--architecture", winget_architecture)
    adapters = {
        "winget": (winget,),
        "apt": ((executable, "update"), (executable, "install", "-y", unit)),
        "dnf": ((executable, "install", "-y", unit),),
        "pacman": ((executable, "-S", "--needed", "--noconfirm", unit),),
        "brew": ((executable, "install", unit),),
    }
    try:
        return adapters[manager]
    except KeyError as error:
        raise PlanningError(f"unsupported package manager: {manager}") from error


def adapter_execution_privilege(manager: str) -> ExecutionPrivilege:
    """Return immutable execution policy for a supported package manager."""

    policies = {
        "winget": ExecutionPrivilege.CURRENT_USER,
        "apt": ExecutionPrivilege.SYSTEM,
        "dnf": ExecutionPrivilege.SYSTEM,
        "pacman": ExecutionPrivilege.SYSTEM,
        "brew": ExecutionPrivilege.CURRENT_USER,
    }
    try:
        return policies[manager]
    except KeyError as error:
        raise PlanningError(f"unsupported package manager: {manager}") from error


def adapter_environment_refresh(manager: str) -> EnvironmentRefresh:
    """Return the post-action environment refresh required before verification."""

    if manager == "winget":
        return EnvironmentRefresh.PATH
    if manager == "brew":
        return EnvironmentRefresh.MANAGER_BIN
    if manager in {"apt", "dnf", "pacman"}:
        return EnvironmentRefresh.NONE
    raise PlanningError(f"unsupported package manager: {manager}")


def adapter_environment_path_entries(
    state: PackageManagerState,
    context: MachineState,
) -> tuple[str, ...] | None:
    """Return reviewed executable-search paths, or None when evidence is insufficient."""

    if state.manager != "brew":
        return ()
    root = state.installation_root
    if root is None:
        executable = PurePosixPath(
            state.resolved_executable_path or state.executable_path
        )
        if executable.name != "brew" or executable.parent.name != "bin":
            return None
        root = str(executable.parent.parent)
    formula_bin = posixpath.join(posixpath.normpath(root), "bin")
    if not _manager_path_is_absolute(formula_bin, context):
        return None
    return (formula_bin,)


def _option(
    provider: ProviderSpec,
    context: MachineState,
    package_managers: tuple[PackageManagerState, ...],
    translated_fallbacks: frozenset[PackageManagerState],
    *,
    allow_translated: bool = True,
) -> tuple[ProviderPackage, PackageManagerState, NativeStatus] | None:
    for package in provider.packages:
        if context.platform not in package.platforms or (
            package.architectures
            and normalize_architecture(context.architecture) not in package.architectures
        ):
            continue
        candidates = []
        for manager_state in package_managers:
            if (
                manager_state.manager != package.manager
                or manager_state.execution_environment != context.execution_environment
            ):
                continue
            if adapter_environment_path_entries(manager_state, context) is None:
                continue
            native_status = manager_state.native_status(context)
            if package.manager == "brew":
                if native_status is NativeStatus.NATIVE:
                    rank = 0
                elif (
                    allow_translated
                    and native_status is NativeStatus.TRANSLATED
                    and manager_state in translated_fallbacks
                ):
                    rank = 1
                else:
                    continue
            else:
                # These managers select or explicitly receive the target package
                # architecture; their own executable architecture is not package
                # suitability evidence.
                rank = 0
            candidates.append(
                (
                    rank,
                    _manager_path_key(
                        manager_state.resolved_executable_path
                        or manager_state.executable_path,
                        context,
                    ),
                    manager_state,
                    native_status,
                )
            )
        if candidates:
            _, _, manager_state, native_status = min(candidates)
            return package, manager_state, native_status
    return None


def _manager_identity_key(
    state: PackageManagerState,
    context: MachineState | None,
) -> tuple[str, str]:
    """Return the resolved executable identity and execution environment."""

    return (
        _manager_path_key(
            state.resolved_executable_path or state.executable_path,
            context,
        ),
        state.execution_environment,
    )


def _canonicalize_manager_states(
    states: tuple[PackageManagerState, ...],
    context: MachineState | None,
) -> tuple[PackageManagerState, ...]:
    """Merge complementary manager observations and reject contradictions."""

    groups: dict[tuple[str, str], list[PackageManagerState]] = {}
    for state in states:
        groups.setdefault(_manager_identity_key(state, context), []).append(state)
    canonical: list[PackageManagerState] = []
    for identity in sorted(groups):
        observations = groups[identity]
        managers = {item.manager for item in observations}
        if len(managers) != 1:
            raise PlanningError(
                f"conflicting package-manager identity evidence: {identity[0]}"
            )
        recognized_architectures = {"x86_64", "x86", "arm64", "arm"}
        known_architectures = {
            architecture
            for item in observations
            if (architecture := normalize_architecture(item.architecture))
            in recognized_architectures
        }
        if len(known_architectures) > 1:
            raise PlanningError(
                "conflicting package-manager architecture evidence: "
                f"{observations[0].manager}"
            )
        selected = min(
            observations,
            key=lambda item: _manager_path_key(item.executable_path, context),
        )
        explicit_resolved_paths = tuple(
            item.resolved_executable_path
            for item in observations
            if item.resolved_executable_path is not None
        )
        resolved_path = (
            min(
                explicit_resolved_paths,
                key=lambda path: _manager_path_key(path, context),
            )
            if explicit_resolved_paths
            else None
        )
        installation_roots = {
            posixpath.normpath(item.installation_root)
            for item in observations
            if item.installation_root is not None
        }
        if len(installation_roots) > 1:
            raise PlanningError(
                "conflicting package-manager installation-root evidence: "
                f"{observations[0].manager}"
            )
        canonical.append(
            PackageManagerState(
                manager=selected.manager,
                executable_path=selected.executable_path,
                execution_environment=selected.execution_environment,
                architecture=next(iter(known_architectures), None),
                resolved_executable_path=resolved_path,
                installation_root=next(iter(installation_roots), None),
            )
        )
    return tuple(canonical)


def _manager_path_key(path: str, context: MachineState | None) -> str:
    """Return a stable executable identity under the plan platform's rules."""

    if context is not None and context.platform == "Windows":
        return ntpath.normpath(path).casefold()
    return posixpath.normpath(path)


def _manager_path_is_absolute(path: str, context: MachineState | None) -> bool:
    """Validate an executable identity using the plan platform's path rules."""

    if context is None:
        return PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute()
    if context.platform == "Windows":
        return PureWindowsPath(path).is_absolute()
    return PurePosixPath(path).is_absolute()


def _validate_provider_observations(state: CapabilityState) -> None:
    """Reject provider enums that contradict catalogue probes and evidence."""

    for provider_state in state.providers:
        provider = provider_state.provider
        expected_probes = provider.probes if provider.supports(state.machine) else ()
        if tuple(item.probe for item in provider_state.executables) != expected_probes:
            raise PlanningError(
                "detected provider probes do not match built-in catalogue: "
                f"{provider.provider_id}"
            )
        expected = provider_availability(
            provider,
            state.machine,
            provider_state.executables,
        )
        if provider_state.availability is not expected:
            raise PlanningError(
                "detected provider availability contradicts executable evidence: "
                f"{provider.provider_id}"
            )


def validate_capability_state(
    state: CapabilityState,
    *,
    expected_context: MachineState | None = None,
) -> None:
    """Validate caller-owned detected state against catalogue and context truth."""

    try:
        catalogue_capability = get_capability(state.capability.capability_id)
    except KeyError as error:
        raise PlanningError(
            f"unknown built-in capability: {state.capability.capability_id}"
        ) from error
    if (
        state.capability != catalogue_capability
        or tuple(item.provider for item in state.providers)
        != catalogue_capability.providers
    ):
        raise PlanningError(
            "detected state does not match built-in catalogue: "
            f"{state.capability.capability_id}"
        )
    if expected_context is not None and MachineState(
        state.machine.platform,
        normalize_architecture(state.machine.architecture),
        state.machine.execution_environment,
    ) != MachineState(
        expected_context.platform,
        normalize_architecture(expected_context.architecture),
        expected_context.execution_environment,
    ):
        raise PlanningError(
            f"detected state is from another execution context: {state.capability.capability_id}"
        )
    _validate_provider_observations(state)
    try:
        consolidate_executable_evidence(state.providers, state.machine)
    except ExecutableEvidenceError as error:
        raise PlanningError(str(error)) from error
    if state.availability is not capability_availability(state.providers):
        raise PlanningError(
            "detected capability availability contradicts provider states: "
            f"{state.capability.capability_id}"
        )


def generate_provider_plan(
    states: Iterable[CapabilityState],
    requested_capabilities: Iterable[str],
    *,
    package_managers: Iterable[PackageManagerState],
    native_provisioning: Iterable[str] = (),
    translated_manager_fallbacks: Iterable[PackageManagerState] = (),
) -> ProviderPlan:
    """Plan missing requested providers from verified state without mutation."""

    requested = tuple(dict.fromkeys(requested_capabilities))
    requested_ids = frozenset(requested)
    by_id: dict[str, CapabilityState] = {}
    for state in states:
        capability_id = state.capability.capability_id
        if capability_id not in requested_ids:
            continue
        if capability_id in by_id:
            raise PlanningError(f"duplicate detected capability state: {capability_id}")
        by_id[capability_id] = state
    requested_states = tuple(by_id[item] for item in requested if item in by_id)
    contexts = {
        MachineState(
            state.machine.platform,
            normalize_architecture(state.machine.architecture),
            state.machine.execution_environment,
        )
        for state in requested_states
    }
    if len(contexts) > 1:
        raise PlanningError("requested capability states span multiple execution contexts")
    context = next(iter(contexts), None)
    supplied_manager_states = tuple(dict.fromkeys(package_managers))
    supported_managers = {"winget", "apt", "dnf", "pacman", "brew"}
    for manager_state in supplied_manager_states:
        if manager_state.manager not in supported_managers:
            raise PlanningError(f"unsupported package manager: {manager_state.manager}")
        if not manager_state.executable_path.strip():
            raise PlanningError(
                f"package manager has no verified executable path: {manager_state.manager}"
            )
        if not _manager_path_is_absolute(manager_state.executable_path, context):
            raise PlanningError(
                f"package manager executable path is not absolute: {manager_state.manager}"
            )
        if manager_state.resolved_executable_path is not None and not (
            manager_state.resolved_executable_path.strip()
            and _manager_path_is_absolute(
                manager_state.resolved_executable_path, context
            )
        ):
            raise PlanningError(
                "package manager resolved executable path is not absolute: "
                f"{manager_state.manager}"
            )
        if manager_state.installation_root is not None and (
            manager_state.manager != "brew"
            or not manager_state.installation_root.strip()
            or not _manager_path_is_absolute(manager_state.installation_root, context)
        ):
            raise PlanningError(
                "package-manager installation root is invalid: "
                f"{manager_state.manager}"
            )
    manager_states = _canonicalize_manager_states(
        supplied_manager_states, context
    )
    canonical_managers = {
        _manager_identity_key(manager_state, context): manager_state
        for manager_state in manager_states
    }
    translated_fallbacks_list: list[PackageManagerState] = []
    for fallback in translated_manager_fallbacks:
        detected = canonical_managers.get(_manager_identity_key(fallback, context))
        if (
            detected is None
            or fallback.manager != detected.manager
            or normalize_architecture(fallback.architecture)
            != normalize_architecture(detected.architecture)
        ):
            raise PlanningError("translated package-manager fallback was not detected")
        translated_fallbacks_list.append(detected)
    translated_fallbacks = frozenset(translated_fallbacks_list)
    if context is not None:
        for fallback in translated_fallbacks:
            if fallback.manager != "brew" or fallback.native_status(context) is not NativeStatus.TRANSLATED:
                raise PlanningError(
                    "translated package-manager fallback is not verified translated Homebrew"
                )
    native_overrides = frozenset(native_provisioning)
    unknown_overrides = native_overrides.difference(requested)
    if unknown_overrides:
        raise PlanningError(
            "native-provisioning override was not requested: "
            + ", ".join(sorted(unknown_overrides))
        )
    actions: list[ProviderAction] = []
    for capability_id in requested:
        try:
            state = by_id[capability_id]
        except KeyError as error:
            raise PlanningError(f"capability has no detected state: {capability_id}") from error
        validate_capability_state(state, expected_context=context)
        displaced: tuple[str, ...] = ()
        if state.availability is Availability.AVAILABLE and capability_id not in native_overrides:
            continue
        if capability_id in native_overrides:
            host_architecture = normalize_architecture(state.machine.architecture)
            if host_architecture == "unknown":
                raise PlanningError(
                    f"native-provisioning override requires known host architecture: {capability_id}"
                )
            available_providers = tuple(
                provider_state
                for provider_state in state.providers
                if provider_state.availability is Availability.AVAILABLE
                and provider_state.provider.satisfies_capability
            )
            native_providers = tuple(
                verified
                for provider_state in available_providers
                if (
                    verified := tuple(
                        item
                        for item in provider_state.executables
                        if item.verified
                    )
                )
                and all(
                    normalize_architecture(item.architecture) == host_architecture
                    for item in verified
                )
            )
            if any(
                all(
                    item.path is not None
                    and _manager_path_is_absolute(item.path, context)
                    for item in verified
                )
                for verified in native_providers
            ):
                continue
            if native_providers:
                raise PlanningError(
                    "native-provider reuse requires absolute verified provider paths: "
                    f"{capability_id}"
                )
            selected_provider = state.selected_provider
            if selected_provider is None:
                raise PlanningError(
                    f"native-provisioning override has no installed provider to replace: {capability_id}"
                )
            verified = tuple(
                item for item in selected_provider.executables if item.verified
            )
            provider_architectures = tuple(
                normalize_architecture(item.architecture) for item in verified
            )
            if not verified or any(
                architecture not in {"x86_64", "x86", "arm64", "arm"}
                or architecture == host_architecture
                for architecture in provider_architectures
            ):
                raise PlanningError(
                    f"native-provisioning override is not a verified translated provider: {capability_id}"
                )
            if any(
                item.path is None or not _manager_path_is_absolute(item.path, context)
                for item in verified
            ):
                raise PlanningError(
                    "native-provisioning override requires absolute verified provider paths: "
                    f"{capability_id}"
                )
            displaced = tuple(item.path for item in verified if item.path is not None)
        if state.availability is Availability.UNSUPPORTED:
            raise PlanningError(f"capability is unsupported: {capability_id}")
        selected: tuple[
            ProviderSpec, ProviderPackage, PackageManagerState, NativeStatus
        ] | None = None
        for provider_state in state.providers:
            provider = provider_state.provider
            if not provider.satisfies_capability or not provider.supports(state.machine):
                continue
            option = _option(
                provider,
                context,
                manager_states,
                translated_fallbacks,
                allow_translated=not displaced,
            )
            if option is not None:
                package, manager_state, manager_native_status = option
                selected = (provider, package, manager_state, manager_native_status)
                break
        if selected is None:
            raise PlanningError(
                f"no supported provider plan for {capability_id} using: "
                + (", ".join(sorted(item.manager for item in manager_states)) or "no package manager")
            )
        provider, package, manager_state, manager_native_status = selected
        reason = (
            "explicit native-provisioning override replaces translated provider"
            if displaced
            else "no compatible provider verified"
        )
        if (
            manager_native_status is NativeStatus.TRANSLATED
            and manager_state in translated_fallbacks
        ):
            reason += "; explicit translated package-manager fallback"
        actions.append(
            ProviderAction(
                capability_id=capability_id,
                provider_id=provider.provider_id,
                manager_state=manager_state,
                installation_unit=package.installation_unit,
                reason=reason,
                verification=VerificationRequirement(
                    provider.probes,
                    provider.probe_policy,
                ),
                execution_privilege=adapter_execution_privilege(package.manager),
                environment_refresh=adapter_environment_refresh(package.manager),
                commands=adapter_commands(
                    package.manager,
                    package.installation_unit,
                    executable_path=manager_state.executable_path,
                    target_architecture=(
                        host_architecture
                        if displaced
                        else None
                    ),
                ),
                shared_package=provider.shared_package,
                displaces_verified_paths=displaced,
                target_architecture=(
                    host_architecture
                    if displaced
                    else None
                ),
                environment_path_entries=(
                    adapter_environment_path_entries(manager_state, context) or ()
                ),
                translated_manager_fallback_authorized=(
                    manager_native_status is NativeStatus.TRANSLATED
                    and manager_state in translated_fallbacks
                ),
            )
        )
    return ProviderPlan(requested, context, tuple(actions))
