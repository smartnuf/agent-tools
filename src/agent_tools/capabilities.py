"""Immutable native-capability catalogue and read-only detection helpers."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Availability(str, Enum):
    """Observed availability of a capability or provider."""

    AVAILABLE = "available"
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"


class ProbePolicy(str, Enum):
    """Whether every executable probe or any one probe satisfies a provider."""

    ALL = "all"
    ANY = "any"


class RemovalPolicy(str, Enum):
    """Provider-package removal policy declared by the built-in catalogue."""

    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class MachineState:
    """Platform facts used during pure capability evaluation."""

    platform: str
    architecture: str
    execution_environment: str = "host"


@dataclass(frozen=True)
class ExecutableProbe:
    """A named executable and the non-mutating command used to verify it."""

    name: str
    version_args: tuple[str, ...]
    locator_strategy: str = "path"


@dataclass(frozen=True)
class ProviderSpec:
    """Project-maintained support and probe knowledge for one provider."""

    provider_id: str
    label: str
    platforms: frozenset[str]
    execution_environments: frozenset[str]
    probes: tuple[ExecutableProbe, ...]
    probe_policy: ProbePolicy
    architectures: frozenset[str] = frozenset()
    installation_unit: str | None = None
    shared_package: bool = True
    removal_policy: RemovalPolicy = RemovalPolicy.PROHIBITED

    def supports(self, machine: MachineState) -> bool:
        return (
            machine.platform in self.platforms
            and machine.execution_environment in self.execution_environments
            and (not self.architectures or machine.architecture in self.architectures)
        )


@dataclass(frozen=True)
class CapabilitySpec:
    """A stable capability identity and its ordered provider declarations."""

    capability_id: str
    label: str
    required_by_default: bool
    providers: tuple[ProviderSpec, ...]


@dataclass(frozen=True)
class ExecutableState:
    """Ephemeral result of locating and verifying one executable."""

    probe: ExecutableProbe
    path: str | None
    version: str | None

    @property
    def verified(self) -> bool:
        return self.path is not None and self.version is not None


@dataclass(frozen=True)
class ProviderState:
    """Detected state for one provider on one machine."""

    provider: ProviderSpec
    availability: Availability
    executables: tuple[ExecutableState, ...]

    @property
    def unavailable_probes(self) -> tuple[str, ...]:
        return tuple(item.probe.name for item in self.executables if not item.verified)


@dataclass(frozen=True)
class CapabilityState:
    """Detected state for a capability, independent of desired or managed state."""

    capability: CapabilitySpec
    machine: MachineState
    availability: Availability
    providers: tuple[ProviderState, ...]

    @property
    def selected_provider(self) -> ProviderState | None:
        return next(
            (provider for provider in self.providers if provider.availability is Availability.AVAILABLE),
            None,
        )


POPPLER = CapabilitySpec(
    capability_id="poppler",
    label="Poppler",
    required_by_default=True,
    providers=(
        ProviderSpec(
            provider_id="host-poppler",
            label="host Poppler",
            platforms=frozenset({"Windows", "Linux", "Darwin"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe("pdfinfo", ("-v",)),
                ExecutableProbe("pdftotext", ("-v",)),
                ExecutableProbe("pdftoppm", ("-v",)),
            ),
            probe_policy=ProbePolicy.ALL,
        ),
    ),
)

GHOSTSCRIPT = CapabilitySpec(
    capability_id="ghostscript",
    label="Ghostscript",
    required_by_default=True,
    providers=(
        ProviderSpec(
            provider_id="host-ghostscript",
            label="host Ghostscript",
            platforms=frozenset({"Windows", "Linux", "Darwin"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe("gs", ("--version",)),
                ExecutableProbe("gswin64c", ("--version",), "windows-ghostscript"),
                ExecutableProbe("gswin32c", ("--version",), "windows-ghostscript"),
            ),
            probe_policy=ProbePolicy.ANY,
        ),
    ),
)

CAPABILITY_CATALOGUE = (POPPLER, GHOSTSCRIPT)

ExecutableLocator = Callable[[ExecutableProbe, MachineState], str | None]
VersionReader = Callable[[ExecutableProbe, str], str | None]


def current_machine() -> MachineState:
    return MachineState(platform.system(), platform.machine(), "host")


def get_capability(capability_id: str) -> CapabilitySpec:
    for capability in CAPABILITY_CATALOGUE:
        if capability.capability_id == capability_id:
            return capability
    raise KeyError(capability_id)


def _windows_ghostscript_path(probe: str) -> str | None:
    roots = filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")))
    candidates = (
        candidate
        for root in roots
        for candidate in Path(root, "gs").glob(f"*/bin/{probe}.exe")
        if candidate.is_file()
    )

    def version_key(candidate: Path) -> tuple[int, ...]:
        match = re.search(r"\d+(?:\.\d+)*", candidate.parent.parent.name)
        return tuple(map(int, match.group().split("."))) if match else (0,)

    return str(max(candidates, key=version_key, default="")) or None


def locate_executable(probe: ExecutableProbe, machine: MachineState) -> str | None:
    """Locate an executable using one of the catalogue's closed strategies."""

    found = shutil.which(probe.name)
    if found:
        return found
    if probe.locator_strategy == "path":
        return None
    if probe.locator_strategy == "windows-ghostscript":
        return _windows_ghostscript_path(probe.name) if machine.platform == "Windows" else None
    raise ValueError(f"unknown executable locator strategy: {probe.locator_strategy}")


def read_executable_version(probe: ExecutableProbe, executable: str) -> str | None:
    """Run a bounded, non-mutating version probe and return its first output line."""

    try:
        result = subprocess.run(
            [executable, *probe.version_args],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()]
    return lines[0] if lines else None


def detect_provider(
    provider: ProviderSpec,
    machine: MachineState,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
) -> ProviderState:
    """Evaluate provider support and probes without consulting persistent state."""

    if not provider.supports(machine):
        return ProviderState(provider, Availability.UNSUPPORTED, ())

    locator = locator or locate_executable
    version_reader = version_reader or read_executable_version
    executables = tuple(
        _detect_executable(probe, machine, locator, version_reader) for probe in provider.probes
    )
    verified = tuple(item.verified for item in executables)
    available = all(verified) if provider.probe_policy is ProbePolicy.ALL else any(verified)
    availability = Availability.AVAILABLE if available else Availability.ABSENT
    return ProviderState(provider, availability, executables)


def _detect_executable(
    probe: ExecutableProbe,
    machine: MachineState,
    locator: ExecutableLocator,
    version_reader: VersionReader,
) -> ExecutableState:
    path = locator(probe, machine)
    version = version_reader(probe, path) if path is not None else None
    return ExecutableState(probe, path, version)


def detect_capability(
    capability: CapabilitySpec,
    machine: MachineState | None = None,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
) -> CapabilityState:
    """Return immutable detected state for one capability."""

    machine = machine or current_machine()
    providers = tuple(
        detect_provider(provider, machine, locator=locator, version_reader=version_reader)
        for provider in capability.providers
    )
    if any(provider.availability is Availability.AVAILABLE for provider in providers):
        availability = Availability.AVAILABLE
    elif any(provider.availability is Availability.ABSENT for provider in providers):
        availability = Availability.ABSENT
    else:
        availability = Availability.UNSUPPORTED
    return CapabilityState(capability, machine, availability, providers)


def detect_capabilities(
    catalogue: Iterable[CapabilitySpec] = CAPABILITY_CATALOGUE,
    machine: MachineState | None = None,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
) -> tuple[CapabilityState, ...]:
    """Return detected state for each catalogue entry in deterministic order."""

    machine = machine or current_machine()
    return tuple(
        detect_capability(
            capability,
            machine,
            locator=locator,
            version_reader=version_reader,
        )
        for capability in catalogue
    )
