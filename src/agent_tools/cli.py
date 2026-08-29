from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import platform
import sys
from pathlib import Path

from . import __version__
from .capabilities import Availability, ProbePolicy, detect_capabilities

DISTRIBUTION_NAME = "smartnuf-agent-tools"
PACKAGE_PROBES = ("pypdf", "pdfplumber", "pymupdf", "PIL", "reportlab", "docx", "openpyxl")


def _application_version() -> str:
    try:
        return importlib.metadata.version(DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return __version__


def _distribution_version(module: str) -> str:
    distributions = importlib.metadata.packages_distributions().get(module, [module])
    for distribution in distributions:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return "not installed"


def _checkout_root(module_path: Path | None = None) -> Path | None:
    module_path = (module_path or Path(__file__)).resolve()
    try:
        candidate = module_path.parents[2]
    except IndexError:
        return None
    markers = (
        candidate / "pyproject.toml",
        candidate / "src" / "agent_tools",
        candidate / "bin",
        candidate / "scripts",
    )
    return candidate if all(marker.exists() for marker in markers) else None


def doctor() -> int:
    checkout = _checkout_root()
    if checkout is None:
        print("mode:       installed")
        print(f"package:    {Path(__file__).resolve().parent}")
    else:
        print("mode:       checkout")
        print(f"repository: {checkout}")
    print(f"agent-tools: {_application_version()}")
    print(f"platform:   {platform.platform()}")
    print(f"python:     {sys.executable} ({platform.python_version()})")

    problems = 0
    print("\nPython packages:")
    for module in PACKAGE_PROBES:
        version = _distribution_version(module)
        try:
            importlib.import_module(module)
        except Exception as error:
            print(f"  {module:<12} {version}; import failed: {type(error).__name__}: {error}")
            problems += 1
        else:
            print(f"  {module:<12} {version}")
            problems += version == "not installed"

    print("\nNative tools:")
    for state in detect_capabilities():
        label = state.capability.label
        if state.availability is Availability.UNSUPPORTED:
            machine = state.machine
            print(
                f"  {label:<12} unsupported on "
                f"{machine.platform}/{machine.architecture} ({machine.execution_environment})"
            )
            problems += 1
            continue

        provider = state.selected_provider or next(
            item for item in state.providers if item.availability is not Availability.UNSUPPORTED
        )
        if state.availability is Availability.ABSENT:
            probes = tuple(probe.name for probe in provider.provider.probes)
            if provider.provider.probe_policy is ProbePolicy.ALL:
                unavailable = provider.unavailable_probes
                print(f"  {label:<12} missing required executable(s): {', '.join(unavailable)}")
            else:
                print(f"  {label:<12} not found ({', '.join(probes)})")
            problems += 1
            continue

        available = tuple(item for item in provider.executables if item.verified)
        if provider.provider.probe_policy is ProbePolicy.ANY:
            available = available[:1]
        locations = ", ".join(f"{item.probe.name}: {item.path}" for item in available)
        print(f"  {label:<12} {locations}")

    if problems:
        print(f"\n{problems} check(s) need attention.")
        return 1
    print("\nAll checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-tools")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_application_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show Python and native-tool availability")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    return 2
