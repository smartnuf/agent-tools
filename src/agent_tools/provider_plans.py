"""Pure provider-plan generation and closed package-manager adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .capabilities import (
    Availability,
    CapabilityState,
    ExecutableProbe,
    ProviderPackage,
    ProviderSpec,
    ProbePolicy,
    MachineState,
    get_capability,
)
from .python_selection import NativeStatus, normalize_architecture


class PlanningError(RuntimeError):
    """Raised when verified state cannot produce a safe provider plan."""


class ExecutionPrivilege(str, Enum):
    """Privilege level required to execute an already reviewed action."""

    CURRENT_USER = "current-user"
    SYSTEM = "system"


@dataclass(frozen=True)
class PackageManagerState:
    """Verified primary observations for one package-manager executable."""

    manager: str
    executable_path: str
    execution_environment: str
    architecture: str | None = None

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
    commands: tuple[tuple[str, ...], ...]
    shared_package: bool
    displaces_verified_paths: tuple[str, ...] = ()
    target_architecture: str | None = None

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
            candidates.append((rank, manager_state.executable_path, manager_state, native_status))
        if candidates:
            _, _, manager_state, native_status = min(candidates)
            return package, manager_state, native_status
    return None


def _aggregate_availability(state: CapabilityState) -> Availability:
    """Derive capability availability from its immutable provider observations."""

    satisfying = tuple(
        item for item in state.providers if item.provider.satisfies_capability
    )
    if any(item.availability is Availability.AVAILABLE for item in satisfying):
        return Availability.AVAILABLE
    if any(item.availability is Availability.ABSENT for item in satisfying):
        return Availability.ABSENT
    return Availability.UNSUPPORTED


def _manager_evidence_key(
    state: PackageManagerState,
) -> tuple[str, str, str, str]:
    """Return alias-canonical identity for one manager observation."""

    return (
        state.manager,
        state.executable_path,
        state.execution_environment,
        normalize_architecture(state.architecture),
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
    by_identity: dict[tuple[str, str, str], PackageManagerState] = {}
    for manager_state in supplied_manager_states:
        identity = (
            manager_state.manager,
            manager_state.executable_path,
            manager_state.execution_environment,
        )
        existing = by_identity.get(identity)
        if existing is not None and normalize_architecture(
            existing.architecture
        ) != normalize_architecture(manager_state.architecture):
            raise PlanningError(
                f"conflicting package-manager architecture evidence: {manager_state.manager}"
            )
        by_identity[identity] = manager_state
    canonical_managers: dict[
        tuple[str, str, str, str], PackageManagerState
    ] = {}
    for manager_state in supplied_manager_states:
        canonical_managers.setdefault(_manager_evidence_key(manager_state), manager_state)
    manager_states = tuple(canonical_managers.values())
    translated_fallbacks_list: list[PackageManagerState] = []
    for fallback in translated_manager_fallbacks:
        detected = canonical_managers.get(_manager_evidence_key(fallback))
        if detected is None:
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
        try:
            catalogue_capability = get_capability(capability_id)
        except KeyError as error:
            raise PlanningError(f"unknown built-in capability: {capability_id}") from error
        if (
            state.capability != catalogue_capability
            or tuple(item.provider for item in state.providers)
            != catalogue_capability.providers
        ):
            raise PlanningError(
                f"detected state does not match built-in catalogue: {capability_id}"
            )
        if state.availability is not _aggregate_availability(state):
            raise PlanningError(
                f"detected capability availability contradicts provider states: {capability_id}"
            )
        displaced: tuple[str, ...] = ()
        if state.availability is Availability.AVAILABLE and capability_id not in native_overrides:
            continue
        if capability_id in native_overrides:
            host_architecture = normalize_architecture(state.machine.architecture)
            if host_architecture == "unknown":
                raise PlanningError(
                    f"native-provisioning override requires known host architecture: {capability_id}"
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
        if manager_native_status is NativeStatus.TRANSLATED:
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
            )
        )
    return ProviderPlan(requested, context, tuple(actions))
