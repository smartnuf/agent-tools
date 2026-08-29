from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import platform
import sys
from pathlib import Path

from . import __version__
from .capabilities import (
    CAPABILITY_CATALOGUE,
    Availability,
    CapabilityState,
    ProbePolicy,
    detect_capabilities,
    get_capability,
)

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
        if not isinstance(distribution, str) or not distribution.strip():
            continue
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
    required_capabilities = tuple(
        capability for capability in CAPABILITY_CATALOGUE if capability.required_by_default
    )
    for state in detect_capabilities(required_capabilities):
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
            missing = provider.missing_probes
            unverified = provider.unverified_executables
            details = []
            if provider.provider.probe_policy is ProbePolicy.ALL:
                if missing:
                    details.append(f"missing required executable(s): {', '.join(missing)}")
            else:
                if missing and not unverified:
                    details.append(f"not found ({', '.join(probes)})")
                elif missing:
                    details.append(f"not found: {', '.join(missing)}")
            if unverified:
                failures = ", ".join(
                    f"{item.probe.name}: {item.path}" for item in unverified
                )
                details.append(f"version verification failed: {failures}")
            print(f"  {label:<12} {'; '.join(details)}")
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


def tools_list() -> int:
    """List immutable project-supported capabilities without probing the host."""

    print("CAPABILITY     DEFAULT   PROVIDERS")
    for capability in CAPABILITY_CATALOGUE:
        requirement = "required" if capability.required_by_default else "optional"
        providers = ", ".join(provider.provider_id for provider in capability.providers)
        print(f"{capability.capability_id:<14} {requirement:<9} {providers}")
    return 0


def _print_capability_status(state: CapabilityState) -> None:
    requirement = "required" if state.capability.required_by_default else "optional"
    print(f"{state.capability.capability_id}: {state.availability.value} ({requirement})")
    for provider in state.providers:
        spec = provider.provider
        print(f"  {spec.provider_id}: {provider.availability.value}")
        print(f"    provider: {spec.label}")
        print(f"    environment: {spec.provided_environment}")
        if not spec.satisfies_capability:
            print("    note: separate environment; does not satisfy the host capability")
        for executable in provider.executables:
            if executable.path is None:
                continue
            print(f"    executable: {executable.path}")
            if executable.probe.locator_strategy == "wsl-bash":
                print(f"    command: {executable.probe.name}")
            if executable.version is None:
                print("    verification: failed")
                continue
            print(f"    version: {executable.version}")
            if executable.architecture is not None:
                print(f"    architecture: {executable.architecture}")


def tools_status(capability_id: str | None = None) -> int:
    """Report ephemeral detected state for one or every built-in capability."""

    if capability_id is not None:
        try:
            catalogue = (get_capability(capability_id),)
        except KeyError:
            supported = ", ".join(item.capability_id for item in CAPABILITY_CATALOGUE)
            print(
                f"unknown capability: {capability_id}; supported capabilities: {supported}",
                file=sys.stderr,
            )
            return 2
    else:
        catalogue = CAPABILITY_CATALOGUE

    states = detect_capabilities(catalogue)
    for index, state in enumerate(states):
        if index:
            print()
        _print_capability_status(state)

    if capability_id is not None:
        availability = states[0].availability
        if availability is Availability.AVAILABLE:
            return 0
        return 1 if availability is Availability.ABSENT else 2
    return int(
        any(
            state.capability.required_by_default
            and state.availability is not Availability.AVAILABLE
            for state in states
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-tools")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_application_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show Python and native-tool availability")
    tools_parser = subparsers.add_parser("tools", help="list capabilities or detect host state")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command", required=True)
    tools_subparsers.add_parser("list", help="list project-supported capabilities")
    status_parser = tools_subparsers.add_parser("status", help="show detected capability state")
    status_parser.add_argument("capability", nargs="?", help="capability identity")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "tools" and args.tools_command == "list":
        return tools_list()
    if args.command == "tools" and args.tools_command == "status":
        return tools_status(args.capability)
    return 2
