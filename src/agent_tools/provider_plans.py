"""Pure provider-plan generation and closed package-manager adapters."""

from __future__ import annotations

from dataclasses import dataclass
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
from .python_selection import normalize_architecture


class PlanningError(RuntimeError):
    """Raised when verified state cannot produce a safe provider plan."""


@dataclass(frozen=True)
class VerificationRequirement:
    probes: tuple[ExecutableProbe, ...]
    policy: ProbePolicy


@dataclass(frozen=True)
class ProviderAction:
    capability_id: str
    provider_id: str
    manager: str
    installation_unit: str
    reason: str
    verification: VerificationRequirement
    commands: tuple[tuple[str, ...], ...]
    shared_package: bool
    displaces_verified_paths: tuple[str, ...] = ()
    target_architecture: str | None = None


@dataclass(frozen=True)
class ProviderPlan:
    requested_capabilities: tuple[str, ...]
    context: MachineState | None
    actions: tuple[ProviderAction, ...]

    @property
    def changes_host(self) -> bool:
        return bool(self.actions)


def adapter_commands(
    manager: str, unit: str, *, target_architecture: str | None = None
) -> tuple[tuple[str, ...], ...]:
    """Render inspectable argv without executing it."""

    winget = (
        "winget", "install", "--id", unit, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
    )
    if target_architecture is not None:
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
        "apt": (("apt-get", "update"), ("apt-get", "install", "-y", unit)),
        "dnf": (("dnf", "install", "-y", unit),),
        "pacman": (("pacman", "-S", "--needed", "--noconfirm", unit),),
        "brew": (("brew", "install", unit),),
    }
    try:
        return adapters[manager]
    except KeyError as error:
        raise PlanningError(f"unsupported package manager: {manager}") from error


def _option(
    provider: ProviderSpec,
    platform: str,
    architecture: str,
    available_managers: frozenset[str],
) -> ProviderPackage | None:
    return next(
        (
            package
            for package in provider.packages
            if platform in package.platforms
            and package.manager in available_managers
            and (
                not package.architectures
                or normalize_architecture(architecture) in package.architectures
            )
        ),
        None,
    )


def generate_provider_plan(
    states: Iterable[CapabilityState],
    requested_capabilities: Iterable[str],
    *,
    available_managers: Iterable[str],
    native_provisioning: Iterable[str] = (),
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
    contexts = {state.machine for state in requested_states}
    if len(contexts) > 1:
        raise PlanningError("requested capability states span multiple execution contexts")
    context = next(iter(contexts), None)
    managers = frozenset(available_managers)
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
        selected: tuple[ProviderSpec, ProviderPackage] | None = None
        for provider_state in state.providers:
            provider = provider_state.provider
            if not provider.satisfies_capability or not provider.supports(state.machine):
                continue
            package = _option(
                provider, state.machine.platform, state.machine.architecture, managers
            )
            if package is not None:
                selected = (provider, package)
                break
        if selected is None:
            raise PlanningError(
                f"no supported provider plan for {capability_id} using: "
                + (", ".join(sorted(managers)) or "no package manager")
            )
        provider, package = selected
        actions.append(
            ProviderAction(
                capability_id=capability_id,
                provider_id=provider.provider_id,
                manager=package.manager,
                installation_unit=package.installation_unit,
                reason=(
                    "explicit native-provisioning override replaces translated provider"
                    if displaced
                    else "no compatible provider verified"
                ),
                verification=VerificationRequirement(
                    provider.probes,
                    provider.probe_policy,
                ),
                commands=adapter_commands(
                    package.manager,
                    package.installation_unit,
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
