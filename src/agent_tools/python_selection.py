"""Read-only Python discovery and deterministic final-interpreter selection."""

from __future__ import annotations

import ctypes
import argparse
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class ProviderMechanism(str, Enum):
    SYSTEM = "system"
    TOOL_MANAGED = "tool-managed"


class NativeStatus(str, Enum):
    NATIVE = "native"
    UNKNOWN = "unknown"
    TRANSLATED = "translated"


@dataclass(frozen=True)
class HostIdentity:
    platform: str
    architecture: str
    process_architecture: str
    process_translated: bool | None
    execution_environment: str = "host"


@dataclass(frozen=True)
class PythonCandidate:
    path: str
    version: tuple[int, int, int]
    architecture: str | None
    mechanism: ProviderMechanism
    execution_environment: str = "host"
    implementation: str = "cpython"
    release_level: str = "final"
    base_path: str | None = None

    def native_status(self, host: HostIdentity) -> NativeStatus:
        if self.architecture in {None, "unknown"} or host.architecture == "unknown":
            return NativeStatus.UNKNOWN
        return (
            NativeStatus.NATIVE
            if normalize_architecture(self.architecture) == host.architecture
            else NativeStatus.TRANSLATED
        )


class SelectionError(RuntimeError):
    """Raised when verified candidates cannot produce one unambiguous selection."""


_MACHINE_ARCHITECTURES = {
    0x014C: "x86",
    0x8664: "x86_64",
    0x01C0: "arm",
    0xAA64: "arm64",
}


def normalize_architecture(value: str | None) -> str:
    normalized = (value or "").strip().casefold().replace("-", "_")
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "i386": "x86",
        "i686": "x86",
        "x86": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
        "arm64ec": "arm64",
        "armv7l": "arm",
        "arm": "arm",
    }
    return aliases.get(normalized, normalized or "unknown")


def current_host() -> HostIdentity:
    system = platform.system()
    process_architecture = normalize_architecture(platform.machine())
    host_architecture = process_architecture
    translated: bool | None = None
    if system == "Windows":
        detected = _windows_host_process_architectures()
        if detected is not None:
            process_architecture, host_architecture = detected
            translated = process_architecture != host_architecture
    elif system == "Darwin":
        translated = _macos_process_translated()
        host_architecture = (
            "arm64"
            if translated is True
            else _unix_kernel_architecture() or process_architecture
        )
    else:
        host_architecture = _unix_kernel_architecture() or process_architecture
    return HostIdentity(
        system,
        host_architecture,
        process_architecture,
        translated,
        _current_execution_environment(system),
    )


def _current_execution_environment(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Linux" and (
        os.environ.get("WSL_INTEROP")
        or os.environ.get("WSL_DISTRO_NAME")
        or "microsoft" in platform.release().casefold()
    ):
        return "wsl"
    return "host"


def _windows_host_process_architectures() -> tuple[str, str] | None:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel32.IsWow64Process2
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = []
        get_current_process.restype = ctypes.c_void_p
        process_machine = ctypes.c_ushort()
        native_machine = ctypes.c_ushort()
        function.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)]
        function.restype = ctypes.c_bool
        if not function(get_current_process(), process_machine, native_machine):
            return None
    except (AttributeError, OSError):
        return None
    return _windows_architectures(
        process_machine.value,
        native_machine.value,
        platform.machine(),
    )


def _windows_architectures(
    process_machine: int, native_machine: int, process_fallback: str
) -> tuple[str, str] | None:
    native = _MACHINE_ARCHITECTURES.get(native_machine)
    if native is None:
        return None
    process = _MACHINE_ARCHITECTURES.get(
        process_machine, normalize_architecture(process_fallback)
    )
    return process, native


def _unix_kernel_architecture() -> str | None:
    try:
        result = subprocess.run(
            ["uname", "-m"], capture_output=True, check=False, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return normalize_architecture(result.stdout) if result.returncode == 0 else None


def _macos_process_translated() -> bool | None:
    try:
        result = subprocess.run(
            ["sysctl", "-in", "sysctl.proc_translated"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() == "1"


def discover_with_uv(uv: str = "uv") -> tuple[dict[str, Any], ...]:
    """Return uv's installed catalogue without downloads or project configuration."""

    records = _uv_python_list(uv)
    managed = _uv_python_list(uv, managed_only=True)
    managed_paths = {
        os.path.normcase(os.path.normpath(str(item["path"]))) for item in managed
    }
    discovered = tuple(
        {
            **item,
            "agent_tools_mechanism": (
                ProviderMechanism.TOOL_MANAGED.value
                if os.path.normcase(os.path.normpath(str(item["path"]))) in managed_paths
                else ProviderMechanism.SYSTEM.value
            ),
        }
        for item in records
    )
    known = {
        os.path.normcase(os.path.normpath(str(item["path"]))) for item in discovered
    }
    return discovered + tuple(
        item
        for item in _manager_python_records()
        if os.path.normcase(os.path.normpath(str(item["path"]))) not in known
    )


def _uv_python_list(uv: str, *, managed_only: bool = False) -> tuple[dict[str, Any], ...]:
    command = [
        uv,
        "python",
        "list",
        "--only-installed",
        "--all-versions",
        "--all-arches",
        "--output-format",
        "json",
        "--no-python-downloads",
        "--no-config",
    ]
    if managed_only:
        command.append("--managed-python")
    environment = os.environ.copy()
    for variable in (
        "UV_MANAGED_PYTHON",
        "UV_NO_MANAGED_PYTHON",
        "UV_PYTHON_PREFERENCE",
    ):
        environment.pop(variable, None)
    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise SelectionError(f"uv Python discovery failed: {result.stderr.strip()}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SelectionError("uv Python discovery returned invalid JSON") from error
    if not isinstance(value, list):
        raise SelectionError("uv Python discovery did not return a list")
    return tuple(item for item in value if isinstance(item, dict) and item.get("path"))


def verify_candidate(record: dict[str, Any]) -> PythonCandidate | None:
    """Execute one discovered interpreter and return independently verified facts."""

    discovered_path = str(record["path"])
    script = (
        "import json,platform,sys;"
        "print(json.dumps({'path':sys.executable,'version':list(sys.version_info[:3]),"
        "'release_level':sys.version_info.releaselevel,'architecture':platform.machine(),"
        "'implementation':platform.python_implementation(),"
        "'platform_tag':__import__('sysconfig').get_platform(),"
        "'pointer_bits':__import__('struct').calcsize('P') * 8,"
        "'system':platform.system(),'release':platform.release(),"
        "'wsl':bool(__import__('os').environ.get('WSL_INTEROP') or "
        "__import__('os').environ.get('WSL_DISTRO_NAME') or "
        "('microsoft' in platform.release().casefold())),"
        "'base_path':getattr(sys,'_base_executable',sys.executable)}))"
    )
    try:
        result = subprocess.run(
            [discovered_path, "-I", "-c", script],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        facts = json.loads(result.stdout)
        version = tuple(int(part) for part in facts["version"])
        resolved_path = str(Path(facts["path"]).resolve())
        base_path = str(Path(facts["base_path"]).resolve())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None
    if len(version) != 3:
        return None
    return PythonCandidate(
        resolved_path,
        version,
        _process_architecture(facts),
        _provider_mechanism(record, resolved_path),
        execution_environment=_candidate_execution_environment(facts),
        implementation=str(facts.get("implementation", "")).casefold(),
        release_level=str(facts.get("release_level", "")),
        base_path=base_path,
    )


def _process_architecture(facts: dict[str, Any]) -> str:
    machine = normalize_architecture(facts.get("architecture"))
    tag = str(facts.get("platform_tag", "")).casefold().replace("-", "_")
    for aliases, architecture in (
        (("x86_64", "amd64"), "x86_64"),
        (("aarch64", "arm64"), "arm64"),
        (("i386", "i686", "win32"), "x86"),
        (("armv7", "armv6"), "arm"),
    ):
        if any(alias in tag for alias in aliases):
            return architecture
    try:
        pointer_bits = int(facts.get("pointer_bits", 0))
    except (TypeError, ValueError):
        pointer_bits = 0
    if pointer_bits == 32 and machine == "x86_64":
        return "x86"
    if pointer_bits == 32 and machine == "arm64":
        return "arm"
    return machine


def _candidate_execution_environment(facts: dict[str, Any]) -> str:
    candidate_system = str(facts.get("system", "")).casefold()
    current_system = platform.system().casefold()
    if candidate_system == "linux" and bool(facts.get("wsl")):
        return "wsl"
    if candidate_system and candidate_system != current_system:
        return candidate_system
    return "host"


def _provider_mechanism(record: dict[str, Any], path: str) -> ProviderMechanism:
    declared = record.get("agent_tools_mechanism")
    if declared == ProviderMechanism.TOOL_MANAGED.value:
        return ProviderMechanism.TOOL_MANAGED
    manager_roots = _known_manager_roots()
    resolved = os.path.normcase(os.path.normpath(path))
    for root in manager_roots:
        assert root is not None
        normalized_root = os.path.normcase(os.path.normpath(str(Path(root).resolve())))
        try:
            if os.path.commonpath((resolved, normalized_root)) == normalized_root:
                return ProviderMechanism.TOOL_MANAGED
        except ValueError:
            continue
    return (
        ProviderMechanism.SYSTEM
        if declared in {None, ProviderMechanism.SYSTEM.value}
        else ProviderMechanism(declared)
    )


def _known_manager_roots() -> tuple[str, ...]:
    home = Path.home()
    configured = tuple(
        os.environ.get(variable)
        for variable in (
            "UV_PYTHON_INSTALL_DIR",
            "PYENV_ROOT",
            "CONDA_PREFIX",
            "ASDF_DATA_DIR",
            "MISE_DATA_DIR",
        )
        if os.environ.get(variable)
    )
    defaults = (
        home / ".local" / "share" / "uv" / "python",
        home / ".pyenv" / "versions",
        home / ".asdf" / "installs" / "python",
        home / ".local" / "share" / "mise" / "installs" / "python",
        *_conda_environment_roots(home),
        *_conda_base_roots(home),
        *_conda_registered_prefixes(home),
    )
    return tuple(str(root) for root in (*configured, *defaults))


def _conda_environment_roots(home: Path) -> tuple[Path, ...]:
    configured = tuple(
        Path(value)
        for value in os.environ.get("CONDA_ENVS_PATH", "").split(os.pathsep)
        if value
    )
    defaults = tuple(
        home / relative
        for relative in (
            ".conda/envs",
            "miniconda3/envs",
            "anaconda3/envs",
            "miniforge3/envs",
            "mambaforge/envs",
        )
    )
    program_data = os.environ.get("ProgramData")
    shared = (Path(program_data) / "conda" / "envs",) if program_data else ()
    return configured + defaults + shared


def _conda_base_roots(home: Path) -> tuple[Path, ...]:
    defaults = tuple(
        home / name
        for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge")
    )
    program_data = os.environ.get("ProgramData")
    shared = (
        tuple(Path(program_data) / name for name in ("miniconda3", "anaconda3"))
        if program_data
        else ()
    )
    return defaults + shared


def _conda_registered_prefixes(home: Path) -> tuple[Path, ...]:
    registry = home / ".conda" / "environments.txt"
    try:
        lines = registry.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return ()
    return tuple(Path(line.strip()) for line in lines if line.strip())


def _manager_python_records() -> tuple[dict[str, Any], ...]:
    """Enumerate installed runtimes that may be inactive and omitted by uv."""

    try:
        home: Path | None = Path.home()
    except RuntimeError:
        home = None
    roots: list[Path] = []
    configured = os.environ.get("PYENV_ROOT")
    if configured or home is not None:
        roots.append(Path(configured) if configured else home / ".pyenv")
        roots[-1] = roots[-1] / "versions"
    configured = os.environ.get("ASDF_DATA_DIR")
    if configured or home is not None:
        roots.append(Path(configured) if configured else home / ".asdf")
        roots[-1] = roots[-1] / "installs" / "python"
    configured = os.environ.get("MISE_DATA_DIR")
    if configured or home is not None:
        roots.append(
            Path(configured)
            if configured
            else home / ".local" / "share" / "mise"
        )
        roots[-1] = roots[-1] / "installs" / "python"
    if home is not None:
        roots.extend(_conda_environment_roots(home))
        roots.extend(_conda_base_roots(home))
        roots.extend(_conda_registered_prefixes(home))
    paths: dict[str, dict[str, Any]] = {}
    for root in roots:
        try:
            for pattern in (
                "*/bin/python*",
                "*/python.exe",
                "bin/python*",
                "python.exe",
            ):
                for path in root.glob(pattern):
                    if re.fullmatch(r"python(?:3(?:\.11)?)?(?:\.exe)?", path.name) is None:
                        continue
                    if not path.is_file():
                        continue
                    key = os.path.normcase(os.path.normpath(str(path)))
                    paths[key] = {
                        "path": str(path),
                        "agent_tools_mechanism": ProviderMechanism.TOOL_MANAGED.value,
                    }
        except OSError:
            continue
    return tuple(paths[key] for key in sorted(paths))


def verified_candidates(records: Iterable[dict[str, Any]]) -> tuple[PythonCandidate, ...]:
    """Verify and reconcile discovery aliases by resolved executable identity."""

    candidates: dict[str, PythonCandidate] = {}
    for record in records:
        candidate = verify_candidate(record)
        if candidate is None:
            continue
        key = os.path.normcase(os.path.normpath(candidate.path))
        previous = candidates.get(key)
        if previous is not None and previous != candidate:
            raise SelectionError(f"conflicting evidence for Python executable: {candidate.path}")
        candidates[key] = candidate
    return tuple(candidates.values())


def select_python(
    candidates: Iterable[PythonCandidate],
    host: HostIdentity,
    *,
    minor: tuple[int, int] = (3, 11),
    preferred_path: str | None = None,
    allow_translated: bool = False,
) -> PythonCandidate:
    """Select one compatible installed interpreter using the ADR 0002 order."""

    compatible = [
        candidate
        for candidate in candidates
        if candidate.version[:2] == minor
        and candidate.implementation == "cpython"
        and candidate.release_level == "final"
        and candidate.execution_environment == host.execution_environment
    ]
    if preferred_path is not None:
        preferred_key = os.path.normcase(os.path.normpath(str(Path(preferred_path).resolve())))
        compatible = [
            candidate
            for candidate in compatible
            if os.path.normcase(os.path.normpath(candidate.path)) == preferred_key
        ]
        if not compatible:
            raise SelectionError("preferred Python is unavailable or incompatible")
    if not compatible:
        raise SelectionError(f"no compatible installed CPython {minor[0]}.{minor[1]} found")

    def rank(candidate: PythonCandidate) -> tuple[int, int, str]:
        native = candidate.native_status(host)
        classes = {
            (ProviderMechanism.SYSTEM, NativeStatus.NATIVE): 0,
            (ProviderMechanism.SYSTEM, NativeStatus.UNKNOWN): 1,
            (ProviderMechanism.TOOL_MANAGED, NativeStatus.NATIVE): 2,
            (ProviderMechanism.SYSTEM, NativeStatus.TRANSLATED): 3,
            (ProviderMechanism.TOOL_MANAGED, NativeStatus.UNKNOWN): 4,
            (ProviderMechanism.TOOL_MANAGED, NativeStatus.TRANSLATED): 5,
        }
        return (classes[(candidate.mechanism, native)], -candidate.version[2], os.path.normcase(candidate.path))

    selected = min(compatible, key=rank)
    if selected.native_status(host) is NativeStatus.TRANSLATED and not allow_translated:
        raise SelectionError(
            f"only translated/emulated CPython {minor[0]}.{minor[1]} is available; explicit authorization is required"
        )
    return selected


def discover_verify_select(
    *,
    uv: str = "uv",
    minor: tuple[int, int] = (3, 11),
    preferred_path: str | None = None,
    allow_translated: bool = False,
) -> tuple[HostIdentity, tuple[PythonCandidate, ...], PythonCandidate]:
    host = current_host()
    records = discover_with_uv(uv)
    candidates = list(verified_candidates(records))
    resolved_preference = preferred_path
    if preferred_path is not None:
        direct = verify_candidate({"path": preferred_path})
        if direct is not None:
            resolved_preference = direct.path
            direct_key = os.path.normcase(os.path.normpath(direct.path))
            matching = next(
                (
                    candidate
                    for candidate in candidates
                    if os.path.normcase(os.path.normpath(candidate.path)) == direct_key
                ),
                None,
            )
            if matching is None:
                candidates.append(direct)
            elif (
                matching.version != direct.version
                or matching.architecture != direct.architecture
                or matching.implementation != direct.implementation
                or matching.release_level != direct.release_level
                or matching.base_path != direct.base_path
                or matching.execution_environment != direct.execution_environment
            ):
                raise SelectionError(
                    f"conflicting direct evidence for Python executable: {direct.path}"
                )
    selected = select_python(
        candidates,
        host,
        minor=minor,
        preferred_path=resolved_preference,
        allow_translated=allow_translated,
    )
    return host, tuple(candidates), selected


def verify_final_environment(python: str, selected: PythonCandidate) -> None:
    """Verify that a created environment retained the selected runtime facts."""

    actual = verify_candidate({"path": python})
    if actual is None:
        raise SelectionError(f"final Python verification failed: {python}")
    if (
        actual.version != selected.version
        or actual.release_level != selected.release_level
        or actual.architecture != selected.architecture
        or actual.implementation != selected.implementation
        or os.path.normcase(os.path.normpath(actual.base_path or ""))
        != os.path.normcase(os.path.normpath(selected.base_path or selected.path))
    ):
        raise SelectionError(
            "final Python does not match the selected interpreter: "
            f"selected={selected.version}/{selected.architecture}, "
            f"final={actual.version}/{actual.architecture}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv", help="uv executable used for read-only discovery")
    parser.add_argument("--minor", default="3.11", help="required CPython major.minor")
    parser.add_argument("--prefer", help="require this exact installed interpreter path")
    parser.add_argument(
        "--verify-final",
        metavar="PYTHON",
        help="also verify a created environment against the selected runtime facts",
    )
    parser.add_argument(
        "--allow-translated",
        action="store_true",
        help="authorize a translated/emulated fallback when no higher-ranked candidate exists",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parts = tuple(int(part) for part in args.minor.split("."))
        if len(parts) != 2:
            raise ValueError
    except ValueError:
        raise SystemExit("--minor must be major.minor") from None
    try:
        host, candidates, selected = discover_verify_select(
            uv=args.uv,
            minor=parts,
            preferred_path=args.prefer,
            allow_translated=args.allow_translated,
        )
        if args.verify_final:
            verify_final_environment(args.verify_final, selected)
    except (OSError, subprocess.TimeoutExpired, SelectionError) as error:
        print(f"Python selection failed: {error}", file=os.sys.stderr)
        return 1
    print(
        f"Python host={host.platform}/{host.architecture} "
        f"process={host.process_architecture} translated={host.process_translated}; "
        f"verified={len(candidates)} selected={selected.path} "
        f"version={'.'.join(map(str, selected.version))} "
        f"architecture={selected.architecture} mechanism={selected.mechanism.value}",
        file=os.sys.stderr,
    )
    print(selected.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
