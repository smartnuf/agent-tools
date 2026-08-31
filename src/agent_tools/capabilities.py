"""Immutable native-capability catalogue and read-only detection helpers."""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .python_selection import current_host, normalize_architecture


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
class ProviderPackage:
    """One catalogue-owned package-manager installation option."""

    manager: str
    installation_unit: str
    platforms: frozenset[str]
    architectures: frozenset[str] = frozenset()


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
    nonzero_version_pattern: str | None = None
    architecture_args: tuple[str, ...] | None = None


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
    packages: tuple[ProviderPackage, ...] = ()
    shared_package: bool = True
    removal_policy: RemovalPolicy = RemovalPolicy.PROHIBITED
    provided_environment: str = "host"
    satisfies_capability: bool = True
    supported_contexts: frozenset[tuple[str, str]] = frozenset()

    def supports(self, machine: MachineState) -> bool:
        if self.supported_contexts:
            return (
                (machine.platform, machine.execution_environment)
                in self.supported_contexts
                and (not self.architectures or machine.architecture in self.architectures)
            )
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
    architecture: str | None = None

    @property
    def verified(self) -> bool:
        return self.path is not None and self.version is not None


class ExecutableEvidenceError(ValueError):
    """Raised when observations contradict one executable identity."""


@dataclass(frozen=True)
class ExecutableEvidence:
    """Consistent evidence consolidated for one normalized executable."""

    identity: str
    provider_id: str
    version: str | None
    architecture: str | None
    execution_environment: str
    satisfies_capability: bool


@dataclass(frozen=True)
class ProviderState:
    """Detected state for one provider on one machine."""

    provider: ProviderSpec
    availability: Availability
    executables: tuple[ExecutableState, ...]

    @property
    def missing_probes(self) -> tuple[str, ...]:
        return tuple(item.probe.name for item in self.executables if item.path is None)

    @property
    def unverified_executables(self) -> tuple[ExecutableState, ...]:
        return tuple(
            item for item in self.executables if item.path is not None and item.version is None
        )

    @property
    def unavailable_probes(self) -> tuple[str, ...]:
        return tuple(item.probe.name for item in self.executables if not item.verified)


def acceptable_provider_executables(
    provider_state: ProviderState,
    qualifies: Callable[[ExecutableState], bool],
) -> tuple[ExecutableState, ...]:
    """Return qualifying evidence using the provider's ANY/ALL probe policy."""

    if (
        provider_state.availability is not Availability.AVAILABLE
        or not provider_state.provider.satisfies_capability
    ):
        return ()
    qualifying = tuple(
        executable
        for executable in provider_state.executables
        if executable.verified and qualifies(executable)
    )
    if provider_state.provider.probe_policy is ProbePolicy.ALL:
        return (
            qualifying
            if len(qualifying) == len(provider_state.executables)
            else ()
        )
    return qualifying


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
            (
                provider
                for provider in self.providers
                if provider.availability is Availability.AVAILABLE
                and provider.provider.satisfies_capability
            ),
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
                ExecutableProbe("pdfinfo", ("-v",), nonzero_version_pattern=r"\bversion\b"),
                ExecutableProbe("pdftotext", ("-v",), nonzero_version_pattern=r"\bversion\b"),
                ExecutableProbe("pdftoppm", ("-v",), nonzero_version_pattern=r"\bversion\b"),
            ),
            probe_policy=ProbePolicy.ALL,
            packages=(
                ProviderPackage("winget", "oschwartz10612.Poppler", frozenset({"Windows"})),
                ProviderPackage("apt", "poppler-utils", frozenset({"Linux"})),
                ProviderPackage("dnf", "poppler-utils", frozenset({"Linux"})),
                ProviderPackage("pacman", "poppler", frozenset({"Linux"})),
                ProviderPackage("brew", "poppler", frozenset({"Darwin"})),
            ),
            supported_contexts=frozenset(
                {("Windows", "host"), ("Linux", "host"), ("Linux", "wsl"), ("Darwin", "host")}
            ),
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
            packages=(
                ProviderPackage("winget", "ArtifexSoftware.GhostScript", frozenset({"Windows"})),
                ProviderPackage("apt", "ghostscript", frozenset({"Linux"})),
                ProviderPackage("dnf", "ghostscript", frozenset({"Linux"})),
                ProviderPackage("pacman", "ghostscript", frozenset({"Linux"})),
                ProviderPackage("brew", "ghostscript", frozenset({"Darwin"})),
            ),
            supported_contexts=frozenset(
                {("Windows", "host"), ("Linux", "host"), ("Linux", "wsl"), ("Darwin", "host")}
            ),
        ),
    ),
)

BASH = CapabilitySpec(
    capability_id="bash",
    label="Bash",
    required_by_default=False,
    providers=(
        ProviderSpec(
            provider_id="git-bash",
            label="Git Bash",
            platforms=frozenset({"Windows"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe(
                    "bash",
                    ("--version",),
                    "git-bash",
                    architecture_args=("-c", "uname -m"),
                ),
            ),
            probe_policy=ProbePolicy.ANY,
            installation_unit="Git.Git",
            packages=(
                ProviderPackage("winget", "Git.Git", frozenset({"Windows"})),
            ),
            provided_environment="windows-host",
            supported_contexts=frozenset({("Windows", "host")}),
        ),
        ProviderSpec(
            provider_id="system-bash",
            label="system Bash",
            platforms=frozenset({"Linux", "Darwin"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe(
                    "bash",
                    ("--version",),
                    "system-bash",
                    architecture_args=("-c", "uname -m"),
                ),
            ),
            probe_policy=ProbePolicy.ANY,
            packages=(
                ProviderPackage("apt", "bash", frozenset({"Linux"})),
                ProviderPackage("dnf", "bash", frozenset({"Linux"})),
                ProviderPackage("pacman", "bash", frozenset({"Linux"})),
            ),
            supported_contexts=frozenset(
                {("Linux", "host"), ("Linux", "wsl"), ("Darwin", "host")}
            ),
        ),
        ProviderSpec(
            provider_id="homebrew-bash",
            label="Homebrew Bash",
            platforms=frozenset({"Darwin"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe(
                    "bash",
                    ("--version",),
                    "homebrew-bash",
                    architecture_args=("-c", "uname -m"),
                ),
            ),
            probe_policy=ProbePolicy.ANY,
            packages=(
                ProviderPackage("brew", "bash", frozenset({"Darwin"})),
            ),
            supported_contexts=frozenset({("Darwin", "host")}),
        ),
        ProviderSpec(
            provider_id="wsl-bash",
            label="default WSL Bash",
            platforms=frozenset({"Windows"}),
            execution_environments=frozenset({"host"}),
            probes=(
                ExecutableProbe(
                    "bash",
                    ("-e", "bash", "--version"),
                    "wsl-bash",
                    architecture_args=("-e", "uname", "-m"),
                ),
            ),
            probe_policy=ProbePolicy.ANY,
            provided_environment="wsl",
            satisfies_capability=False,
            supported_contexts=frozenset({("Windows", "host")}),
        ),
    ),
)

CAPABILITY_CATALOGUE = (POPPLER, GHOSTSCRIPT, BASH)

ExecutableLocator = Callable[[ExecutableProbe, MachineState], str | None]
VersionReader = Callable[[ExecutableProbe, str], str | None]
ArchitectureReader = Callable[[ExecutableProbe, str], str | None]


def current_machine() -> MachineState:
    host = current_host()
    return MachineState(host.platform, host.architecture, host.execution_environment)


def get_capability(capability_id: str) -> CapabilitySpec:
    for capability in CAPABILITY_CATALOGUE:
        if capability.capability_id == capability_id:
            return capability
    raise KeyError(capability_id)


def _windows_ghostscript_path(probe: str) -> str | None:
    candidates = (
        candidate
        for root in _windows_program_roots()
        for candidate in Path(root, "gs").glob(f"*/bin/{probe}.exe")
        if candidate.is_file()
    )

    def version_key(candidate: Path) -> tuple[int, ...]:
        match = re.search(r"\d+(?:\.\d+)*", candidate.parent.parent.name)
        return tuple(map(int, match.group().split("."))) if match else (0,)

    return str(max(candidates, key=version_key, default="")) or None


def _windows_program_roots() -> tuple[str, ...]:
    roots = []
    seen = set()
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable)
        key = value.casefold() if value else None
        if value and key not in seen:
            roots.append(value)
            seen.add(key)
    return tuple(roots)


def _git_bash_path() -> str | None:
    roots: list[Path] = []
    for command in (shutil.which("bash"), shutil.which("git")):
        if not command:
            continue
        for parent in Path(command).parents:
            if (parent / "cmd" / "git.exe").is_file():
                roots.append(parent)
                break

    standard_roots = (
        Path(root, "Git")
        for root in _windows_program_roots()
    )
    roots.extend(standard_roots)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data, "Programs", "Git"))

    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key in seen:
            continue
        seen.add(key)
        for relative in (Path("bin", "bash.exe"), Path("usr", "bin", "bash.exe")):
            candidate = root / relative
            if candidate.is_file():
                return str(candidate)
    return None


def _wsl_path() -> str | None:
    found = shutil.which("wsl.exe") or shutil.which("wsl")
    if found:
        return found
    system_root = os.environ.get("SystemRoot")
    candidate = Path(system_root, "System32", "wsl.exe") if system_root else None
    return str(candidate) if candidate is not None and candidate.is_file() else None


def locate_executable(probe: ExecutableProbe, machine: MachineState) -> str | None:
    """Locate an executable using one of the catalogue's closed strategies."""

    if probe.locator_strategy == "path":
        return shutil.which(probe.name)
    if probe.locator_strategy == "windows-ghostscript":
        return shutil.which(probe.name) or (
            _windows_ghostscript_path(probe.name) if machine.platform == "Windows" else None
        )
    if probe.locator_strategy == "git-bash":
        return _git_bash_path() if machine.platform == "Windows" else None
    if probe.locator_strategy == "system-bash":
        if machine.platform == "Linux":
            return shutil.which(probe.name)
        if machine.platform == "Darwin":
            system_bash = Path("/bin/bash")
            return system_bash.as_posix() if system_bash.is_file() else None
        return None
    if probe.locator_strategy == "homebrew-bash":
        if machine.platform != "Darwin":
            return None
        prefixes = (
            (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
            if normalize_architecture(machine.architecture) == "arm64"
            else (Path("/usr/local/bin"), Path("/opt/homebrew/bin"))
        )
        brew = shutil.which("brew")
        candidates = [
            (prefixes[0] / probe.name, (prefixes[0] / probe.name).as_posix())
        ]
        if brew:
            path_candidate = Path(brew).with_name(probe.name)
            candidates.append((path_candidate, path_candidate.as_posix()))
        candidates.append(
            (prefixes[1] / probe.name, (prefixes[1] / probe.name).as_posix())
        )
        seen: set[str] = set()
        for candidate, result in candidates:
            key = result
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return result
        return None
    if probe.locator_strategy == "wsl-bash":
        return _wsl_path() if machine.platform == "Windows" else None
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
    lines = [line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()]
    if not lines:
        return None
    first_line = lines[0]
    if result.returncode != 0 and (
        probe.nonzero_version_pattern is None
        or re.search(probe.nonzero_version_pattern, first_line, re.IGNORECASE) is None
    ):
        return None
    return first_line


def read_executable_architecture(probe: ExecutableProbe, executable: str) -> str | None:
    """Return executable architecture when the provider exposes a safe probe."""

    if probe.architecture_args is None:
        return None
    try:
        result = subprocess.run(
            [executable, *probe.architecture_args],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if result.returncode == 0 and lines else None


def detect_provider(
    provider: ProviderSpec,
    machine: MachineState,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
    architecture_reader: ArchitectureReader | None = None,
) -> ProviderState:
    """Evaluate provider support and probes without consulting persistent state."""

    if not provider.supports(machine):
        return ProviderState(provider, Availability.UNSUPPORTED, ())

    locator = locator or locate_executable
    version_reader = version_reader or read_executable_version
    architecture_reader = architecture_reader or read_executable_architecture
    executables = tuple(
        _detect_executable(probe, machine, locator, version_reader, architecture_reader)
        for probe in provider.probes
    )
    availability = provider_availability(provider, machine, executables)
    return ProviderState(provider, availability, executables)


def provider_availability(
    provider: ProviderSpec,
    machine: MachineState,
    executables: tuple[ExecutableState, ...],
) -> Availability:
    """Derive one provider's availability from support and probe evidence."""

    if not provider.supports(machine):
        return Availability.UNSUPPORTED
    verified = tuple(item.verified for item in executables)
    available = all(verified) if provider.probe_policy is ProbePolicy.ALL else any(verified)
    return Availability.AVAILABLE if available else Availability.ABSENT


def capability_availability(providers: tuple[ProviderState, ...]) -> Availability:
    """Derive aggregate availability from satisfying provider states."""

    satisfying = tuple(
        provider for provider in providers if provider.provider.satisfies_capability
    )
    if any(provider.availability is Availability.AVAILABLE for provider in satisfying):
        return Availability.AVAILABLE
    if any(provider.availability is Availability.ABSENT for provider in satisfying):
        return Availability.ABSENT
    return Availability.UNSUPPORTED


def normalized_executable_identity(path: str, machine: MachineState) -> str:
    """Normalize a locator-supplied resolved executable identity."""

    if machine.platform == "Windows":
        return ntpath.normpath(path).casefold()
    return posixpath.normpath(path)


def consolidate_executable_evidence(
    providers: tuple[ProviderState, ...],
    machine: MachineState,
) -> tuple[ExecutableEvidence, ...]:
    """Consolidate compatible observations and reject identity conflicts."""

    by_identity: dict[str, ExecutableEvidence] = {}
    for provider_state in providers:
        provider = provider_state.provider
        for executable in provider_state.executables:
            if executable.path is None:
                continue
            identity = normalized_executable_identity(executable.path, machine)
            architecture = (
                normalize_architecture(executable.architecture)
                if executable.architecture is not None
                else None
            )
            observation = ExecutableEvidence(
                identity=identity,
                provider_id=provider.provider_id,
                version=executable.version,
                architecture=architecture,
                execution_environment=machine.execution_environment,
                satisfies_capability=provider.satisfies_capability,
            )
            existing = by_identity.get(identity)
            if existing is None:
                by_identity[identity] = observation
                continue
            fixed_facts = (
                ("provider", existing.provider_id, observation.provider_id),
                (
                    "execution environment",
                    existing.execution_environment,
                    observation.execution_environment,
                ),
                (
                    "suitability",
                    existing.satisfies_capability,
                    observation.satisfies_capability,
                ),
            )
            optional_facts = (
                ("version", existing.version, observation.version),
                ("architecture", existing.architecture, observation.architecture),
            )
            conflict = next(
                (name for name, left, right in fixed_facts if left != right),
                None,
            ) or next(
                (
                    name
                    for name, left, right in optional_facts
                    if left is not None and right is not None and left != right
                ),
                None,
            )
            if conflict is not None:
                raise ExecutableEvidenceError(
                    f"conflicting {conflict} evidence for executable: {identity}"
                )
            by_identity[identity] = ExecutableEvidence(
                identity=identity,
                provider_id=existing.provider_id,
                version=existing.version or observation.version,
                architecture=existing.architecture or observation.architecture,
                execution_environment=existing.execution_environment,
                satisfies_capability=existing.satisfies_capability,
            )
    return tuple(by_identity[key] for key in sorted(by_identity))


def _detect_executable(
    probe: ExecutableProbe,
    machine: MachineState,
    locator: ExecutableLocator,
    version_reader: VersionReader,
    architecture_reader: ArchitectureReader,
) -> ExecutableState:
    path = locator(probe, machine)
    version = version_reader(probe, path) if path is not None else None
    architecture = (
        architecture_reader(probe, path) if path is not None and version is not None else None
    )
    if architecture is None and version is not None:
        architecture = _architecture_from_version(version)
    return ExecutableState(probe, path, version, architecture)


def _architecture_from_version(version: str) -> str | None:
    match = re.search(r"\(([^()\s]+)\)\s*$", version)
    return match.group(1).split("-", 1)[0] if match else None


def detect_capability(
    capability: CapabilitySpec,
    machine: MachineState | None = None,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
    architecture_reader: ArchitectureReader | None = None,
) -> CapabilityState:
    """Return immutable detected state for one capability."""

    machine = machine or current_machine()
    providers = tuple(
        detect_provider(
            provider,
            machine,
            locator=locator,
            version_reader=version_reader,
            architecture_reader=architecture_reader,
        )
        for provider in capability.providers
    )
    consolidate_executable_evidence(providers, machine)
    availability = capability_availability(providers)
    return CapabilityState(capability, machine, availability, providers)


def detect_capabilities(
    catalogue: Iterable[CapabilitySpec] = CAPABILITY_CATALOGUE,
    machine: MachineState | None = None,
    *,
    locator: ExecutableLocator | None = None,
    version_reader: VersionReader | None = None,
    architecture_reader: ArchitectureReader | None = None,
) -> tuple[CapabilityState, ...]:
    """Return detected state for each catalogue entry in deterministic order."""

    machine = machine or current_machine()
    return tuple(
        detect_capability(
            capability,
            machine,
            locator=locator,
            version_reader=version_reader,
            architecture_reader=architecture_reader,
        )
        for capability in catalogue
    )
