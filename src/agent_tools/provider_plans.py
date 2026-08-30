"""Pure provider-plan generation and closed package-manager adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .capabilities import Availability, CapabilityState, ProviderPackage, ProviderSpec


class PlanningError(RuntimeError):
    """Raised when verified state cannot produce a safe provider plan."""


@dataclass(frozen=True)
class ProviderAction:
    capability_id: str
    provider_id: str
    manager: str
    installation_unit: str
    reason: str
    expected_probes: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    shared_package: bool


@dataclass(frozen=True)
class ProviderPlan:
    requested_capabilities: tuple[str, ...]
    actions: tuple[ProviderAction, ...]

    @property
    def changes_host(self) -> bool:
        return bool(self.actions)


def adapter_commands(manager: str, unit: str) -> tuple[tuple[str, ...], ...]:
    """Render inspectable argv without executing it."""

    adapters = {
        "winget": (("winget", "install", "--id", unit, "-e", "--accept-package-agreements", "--accept-source-agreements"),),
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
    provider: ProviderSpec, platform: str, available_managers: frozenset[str]
) -> ProviderPackage | None:
    return next(
        (
            package
            for package in provider.packages
            if platform in package.platforms and package.manager in available_managers
        ),
        None,
    )


def generate_provider_plan(
    states: Iterable[CapabilityState],
    requested_capabilities: Iterable[str],
    *,
    available_managers: Iterable[str],
) -> ProviderPlan:
    """Plan missing requested providers from verified state without mutation."""

    by_id = {state.capability.capability_id: state for state in states}
    requested = tuple(dict.fromkeys(requested_capabilities))
    managers = frozenset(available_managers)
    actions: list[ProviderAction] = []
    for capability_id in requested:
        try:
            state = by_id[capability_id]
        except KeyError as error:
            raise PlanningError(f"capability has no detected state: {capability_id}") from error
        if state.availability is Availability.AVAILABLE:
            continue
        if state.availability is Availability.UNSUPPORTED:
            raise PlanningError(f"capability is unsupported: {capability_id}")
        selected: tuple[ProviderSpec, ProviderPackage] | None = None
        for provider_state in state.providers:
            provider = provider_state.provider
            if not provider.satisfies_capability or not provider.supports(state.machine):
                continue
            package = _option(provider, state.machine.platform, managers)
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
                reason="no compatible provider verified",
                expected_probes=tuple(probe.name for probe in provider.probes),
                commands=adapter_commands(package.manager, package.installation_unit),
                shared_package=provider.shared_package,
            )
        )
    return ProviderPlan(requested, tuple(actions))
