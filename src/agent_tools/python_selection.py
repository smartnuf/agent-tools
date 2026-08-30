"""Read-only Python discovery and deterministic final-interpreter selection."""

from __future__ import annotations

import ctypes
import argparse
import json
import os
import platform
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

    def native_status(self, host: HostIdentity) -> NativeStatus:
        if self.architecture is None or host.architecture == "unknown":
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
        host_architecture = _unix_kernel_architecture() or process_architecture
    else:
        host_architecture = _unix_kernel_architecture() or process_architecture
    return HostIdentity(
        system,
        host_architecture,
        process_architecture,
        translated,
    )


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

    result = subprocess.run(
        [
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
        ],
        capture_output=True,
        check=False,
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
        "'architecture':platform.machine(),'implementation':platform.python_implementation()}))"
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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None
    if len(version) != 3:
        return None
    return PythonCandidate(
        resolved_path,
        version,
        normalize_architecture(facts.get("architecture")),
        _provider_mechanism(resolved_path),
        implementation=str(facts.get("implementation", "")).casefold(),
    )


def _provider_mechanism(path: str) -> ProviderMechanism:
    parts = tuple(part.casefold() for part in Path(path).parts)
    return (
        ProviderMechanism.TOOL_MANAGED
        if "uv" in parts and "python" in parts
        else ProviderMechanism.SYSTEM
    )


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
    candidates = verified_candidates(discover_with_uv(uv))
    selected = select_python(
        candidates,
        host,
        minor=minor,
        preferred_path=preferred_path,
        allow_translated=allow_translated,
    )
    return host, candidates, selected


def verify_final_environment(python: str, selected: PythonCandidate) -> None:
    """Verify that a created environment retained the selected runtime facts."""

    actual = verify_candidate({"path": python})
    if actual is None:
        raise SelectionError(f"final Python verification failed: {python}")
    if (
        actual.version != selected.version
        or actual.architecture != selected.architecture
        or actual.implementation != selected.implementation
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
