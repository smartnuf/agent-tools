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
from .claude_code_integration import (
    ClaudeCodeIntegrationError,
    ClaudeCodeIntegrationRestorationError,
    IntegrationOutcome,
    apply_git_bash_integration,
    inspect_integration,
    remove_git_bash_integration,
)
from .managed_state import (
    ManagedStateError,
    load_document,
    managed_state_path,
    provenance_for_capability,
)
from .desired_state import (
    DesiredMutationOutcome,
    DesiredStateError,
    DesiredStateRestorationError,
    desired_capabilities,
    desired_state_path,
    load_document as load_desired_document,
    set_capability,
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
        effective_environment = (
            state.machine.execution_environment
            if spec.provided_environment == "host" and spec.supports(state.machine)
            else spec.provided_environment
        )
        print(f"    environment: {effective_environment}")
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
    managed_error: str | None = None
    desired_error: str | None = None
    try:
        managed = load_document(
            managed_state_path(platform_name=states[0].machine.platform)
        )
    except ManagedStateError as error:
        managed = None
        managed_error = str(error)
    try:
        desired_entries = desired_capabilities(
            load_desired_document(
                desired_state_path(platform_name=states[0].machine.platform)
            ),
            states[0].machine,
        )
        desired_by_id = {item.capability_id: item for item in desired_entries}
    except DesiredStateError as error:
        desired_by_id = {}
        desired_error = str(error)
    for index, state in enumerate(states):
        if index:
            print()
        _print_capability_status(state)
        desired = desired_by_id.get(state.capability.capability_id)
        if desired is not None:
            print("  desired: enabled")
            if desired.provider_id is not None:
                print(f"    preferred provider: {desired.provider_id}")
        elif desired_error is None and not state.capability.required_by_default:
            print("  desired: not enabled")
        if managed is not None:
            records = provenance_for_capability(managed, state.capability.capability_id)
            if records:
                latest = records[-1]
                print(f"  agent-tools requests: {len(records)}")
                print(f"    latest request: {latest['requested_at']}")
                print(f"    recorded at: {latest['recorded_at']}")
                print(f"    installation unit: {latest['installation_unit']}")
                print("    ownership: not claimed")
            else:
                print("  agent-tools requests: none recorded")
    if managed_error is not None:
        print(f"managed provenance unavailable: {managed_error}", file=sys.stderr)
    if desired_error is not None:
        print(f"desired state unavailable: {desired_error}", file=sys.stderr)

    if capability_id is not None:
        availability = states[0].availability
        if availability is Availability.AVAILABLE:
            return 0
        return 1 if availability is Availability.ABSENT else 2
    detected_status = int(
        any(
            state.capability.required_by_default
            and state.availability is not Availability.AVAILABLE
            for state in states
        )
    )
    return detected_status


def _change_desired_capability(
    capability_id: str,
    *,
    enabled: bool,
    provider_id: str | None,
    allow_config_mutation: bool,
) -> int:
    try:
        result = set_capability(
            capability_id,
            enabled=enabled,
            provider_id=provider_id,
            allow_config_mutation=allow_config_mutation,
        )
    except DesiredStateRestorationError as error:
        print(f"desired-state change failed: {error}", file=sys.stderr)
        if error.backup_path is not None:
            print(f"  recovery backup: {error.backup_path}", file=sys.stderr)
        return 1
    except DesiredStateError as error:
        print(f"desired-state change failed: {error}", file=sys.stderr)
        return 1
    print(f"desired state: {result.outcome.value}")
    print(f"  path: {result.path}")
    if result.backup_path is not None:
        print(f"  backup: {result.backup_path}")
    if result.detail:
        print(f"  detail: {result.detail}")
    return 1 if result.outcome is DesiredMutationOutcome.REFUSED else 0


def _claude_code_integration_status() -> int:
    try:
        status = inspect_integration()
    except ClaudeCodeIntegrationError as error:
        print(f"Claude Code integration state unavailable: {error}", file=sys.stderr)
        return 1
    print("Claude Code Git Bash integration:")
    print(f"  settings: {status.settings_path}")
    print(f"  state: {status.state_path}")
    print(f"  phase: {status.phase.value if status.phase is not None else 'unmanaged'}")
    print(f"  managed: {'yes' if status.managed else 'no'}")
    if status.current_value is not None:
        print(f"  configured Git Bash: {status.current_value}")
    return 0


def _change_claude_code_integration(*, apply: bool, allow_config_mutation: bool) -> int:
    try:
        result = (
            apply_git_bash_integration(
                allow_config_mutation=allow_config_mutation
            )
            if apply
            else remove_git_bash_integration(
                allow_config_mutation=allow_config_mutation
            )
        )
    except ClaudeCodeIntegrationRestorationError as error:
        print(f"Claude Code integration change failed: {error}", file=sys.stderr)
        for backup in error.backup_paths:
            print(f"  recovery backup: {backup}", file=sys.stderr)
        return 1
    except ClaudeCodeIntegrationError as error:
        print(f"Claude Code integration change failed: {error}", file=sys.stderr)
        return 1
    print(f"Claude Code integration: {result.outcome.value}")
    print(f"  settings: {result.settings_path}")
    print(f"  state: {result.state_path}")
    if result.phase is not None:
        print(f"  phase: {result.phase.value}")
    for backup in result.backup_paths:
        print(f"  backup: {backup}")
    if result.detail:
        print(f"  detail: {result.detail}")
    return 1 if result.outcome is IntegrationOutcome.REFUSED else 0


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
    enable_parser = tools_subparsers.add_parser(
        "enable", help="enable an optional desired capability"
    )
    enable_parser.add_argument("capability", help="capability identity")
    enable_parser.add_argument("--provider", help="exact built-in provider preference")
    enable_parser.add_argument(
        "--allow-config-mutation",
        action="store_true",
        help="authorize desired-state configuration mutation",
    )
    disable_parser = tools_subparsers.add_parser(
        "disable", help="disable an optional desired capability"
    )
    disable_parser.add_argument("capability", help="capability identity")
    disable_parser.add_argument(
        "--allow-config-mutation",
        action="store_true",
        help="authorize desired-state configuration mutation",
    )
    integrations_parser = subparsers.add_parser(
        "integrations", help="manage explicitly supported agent integrations"
    )
    integration_subparsers = integrations_parser.add_subparsers(
        dest="integration", required=True
    )
    claude_parser = integration_subparsers.add_parser(
        "claude-code", help="manage native-Windows Claude Code Git Bash selection"
    )
    claude_subparsers = claude_parser.add_subparsers(
        dest="integration_command", required=True
    )
    claude_subparsers.add_parser("status", help="show separate integration state")
    for command in ("apply", "remove"):
        change_parser = claude_subparsers.add_parser(
            command, help=f"{command} the Claude Code Git Bash setting"
        )
        change_parser.add_argument(
            "--allow-config-mutation",
            action="store_true",
            help="authorize Claude Code and integration-state mutation",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    if args.command == "tools" and args.tools_command == "list":
        return tools_list()
    if args.command == "tools" and args.tools_command == "status":
        return tools_status(args.capability)
    if args.command == "tools" and args.tools_command == "enable":
        return _change_desired_capability(
            args.capability,
            enabled=True,
            provider_id=args.provider,
            allow_config_mutation=args.allow_config_mutation,
        )
    if args.command == "tools" and args.tools_command == "disable":
        return _change_desired_capability(
            args.capability,
            enabled=False,
            provider_id=None,
            allow_config_mutation=args.allow_config_mutation,
        )
    if args.command == "integrations" and args.integration == "claude-code":
        if args.integration_command == "status":
            return _claude_code_integration_status()
        return _change_claude_code_integration(
            apply=args.integration_command == "apply",
            allow_config_mutation=args.allow_config_mutation,
        )
    return 2
