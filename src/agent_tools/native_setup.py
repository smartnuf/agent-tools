"""Clone-bootstrap delegation to packaged native provider management."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .capabilities import (
    MachineState,
    current_machine,
    detect_capabilities,
    get_capability,
)
from .desired_state import (
    DesiredStateError,
    desired_capabilities,
    desired_state_path,
    load_document as load_desired_document,
    provider_preferences,
)
from .managed_state import (
    ManagedExecutionInterrupted,
    ManagedExecutionResult,
    ManagedStateError,
    PersistenceInterrupted,
    PersistenceOutcome,
    execute_provider_plan,
)
from .provider_execution import (
    ExecutionContractError,
    PlanOutcome,
    ProviderPlanInterrupted,
    run_bounded_command,
)
from .provider_plans import (
    NoSupportedProviderPlanError,
    PackageManagerState,
    PlanningError,
    ProviderPlan,
    generate_provider_plan,
)


DEFAULT_BOOTSTRAP_CAPABILITIES = ("poppler", "ghostscript")
_MANAGER_COMMANDS = {
    "Windows": (("winget", "winget"),),
    "Linux": (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman")),
    "Darwin": (("brew", "brew"),),
}


class NativeSetupError(RuntimeError):
    """The clone bootstrap could not establish safe provider inputs."""


ProbeRunner = Callable[[tuple[str, ...], int], subprocess.CompletedProcess[str]]
ExecutableLocator = Callable[[str], str | None]


def _run_probe(argv: tuple[str, ...], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return run_bounded_command(
        argv,
        timeout_seconds,
        environment={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"},
    )


def _probe_line(
    argv: tuple[str, ...],
    *,
    runner: ProbeRunner,
    description: str,
) -> str:
    try:
        completed = runner(argv, 10)
    except (OSError, subprocess.TimeoutExpired, ExecutionContractError) as error:
        raise NativeSetupError(f"{description} could not be verified: {error}") from error
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not lines:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise NativeSetupError(f"{description} could not be verified: {detail}")
    return lines[-1]


def detect_package_managers(
    machine: MachineState | None = None,
    *,
    locator: ExecutableLocator = shutil.which,
    runner: ProbeRunner = _run_probe,
) -> tuple[PackageManagerState, ...]:
    """Return verified package-manager identities for the current environment."""

    machine = machine or current_machine()
    managers: list[PackageManagerState] = []
    for manager, command in _MANAGER_COMMANDS.get(machine.platform, ()):
        located = locator(command)
        if located is None:
            continue
        executable = Path(located)
        if not executable.is_absolute():
            raise NativeSetupError(
                f"package manager resolved to a non-absolute path: {manager}: {located}"
            )
        try:
            if not executable.is_file():
                raise OSError("entry is not a regular file")
            resolved = executable.resolve(strict=True)
        except OSError as error:
            raise NativeSetupError(
                f"package manager identity could not be verified: {manager}: {error}"
            ) from error

        architecture = None
        installation_root = None
        if manager == "brew":
            installation_root = _probe_line(
                (str(executable), "--prefix"),
                runner=runner,
                description="Homebrew installation root",
            )
            if not Path(installation_root).is_absolute():
                raise NativeSetupError(
                    "Homebrew installation root is not an absolute path"
                )
            architecture = _probe_line(
                (
                    str(executable),
                    "ruby",
                    "-e",
                    "puts Hardware::CPU.arch",
                ),
                runner=runner,
                description="Homebrew architecture",
            )

        managers.append(
            PackageManagerState(
                manager=manager,
                executable_path=str(executable),
                execution_environment=machine.execution_environment,
                architecture=architecture,
                resolved_executable_path=str(resolved),
                installation_root=installation_root,
            )
        )
    return tuple(managers)


def build_bootstrap_plan(
    capability_ids: Sequence[str],
    *,
    config_path: Path | None = None,
) -> ProviderPlan:
    """Discover current facts and produce the canonical immutable provider plan."""

    machine = current_machine()
    configured = desired_capabilities(
        load_desired_document(
            config_path or desired_state_path(platform_name=machine.platform)
        ),
        machine,
    )
    requested = tuple(
        dict.fromkeys(
            (*capability_ids, *(item.capability_id for item in configured))
        )
    )
    if not requested:
        raise NativeSetupError("at least one native capability must be requested")
    capabilities = []
    for capability_id in requested:
        try:
            capabilities.append(get_capability(capability_id))
        except KeyError as error:
            raise NativeSetupError(f"unknown native capability: {capability_id}") from error
    states = detect_capabilities(capabilities, machine)
    preferences = provider_preferences(configured)
    try:
        return generate_provider_plan(
            states,
            requested,
            package_managers=(),
            provider_preferences=preferences,
        )
    except NoSupportedProviderPlanError:
        managers = detect_package_managers(machine)
        return generate_provider_plan(
            states,
            requested,
            package_managers=managers,
            provider_preferences=preferences,
        )


def _render_argv(argv: tuple[str, ...]) -> str:
    return json.dumps(list(argv), ensure_ascii=False)


def report_plan(plan: ProviderPlan) -> None:
    """Print the reviewed requested mutations before execution begins."""

    print("Native provider plan:")
    if not plan.actions:
        print("  no host changes required; all requested capabilities verify")
        return
    for action in plan.actions:
        print(
            f"  {action.capability_id}: {action.manager} package "
            f"{action.installation_unit}"
        )
        for command in action.commands:
            print(f"    requested command: {_render_argv(command)}")


def report_result(result: ManagedExecutionResult) -> None:
    """Print host-mutation evidence separately from persistence evidence."""

    execution = result.execution
    if execution is None:
        print("Host mutation: not attempted")
    else:
        print(f"Host mutation: {execution.outcome.value}")
        for action in execution.actions:
            print(
                f"  {action.capability_id}: {action.outcome.value} "
                f"({action.manager} {action.installation_unit})"
            )
            if action.detail:
                print(f"    detail: {action.detail}")
            for command in action.commands:
                status = "not observed" if command.returncode is None else str(command.returncode)
                print(f"    command: {_render_argv(command.argv)}")
                print(f"    return code: {status}")
                if command.stdout:
                    print(f"    stdout tail:\n{command.stdout}")
                if command.stderr:
                    print(f"    stderr tail:\n{command.stderr}")
            for path in action.final_verified_paths:
                print(f"    verified executable: {path}")
        for guidance in execution.recovery_guidance:
            print(f"  recovery: {guidance}")
    print(f"Managed provenance: {result.persistence.value}")
    if result.persistence_detail:
        print(f"  detail: {result.persistence_detail}")
    for guidance in result.recovery_guidance:
        print(f"  recovery: {guidance}")


def native_setup(
    capability_ids: Sequence[str],
    *,
    allow_provider_mutation: bool,
) -> ManagedExecutionResult:
    """Plan and execute one clone-bootstrap native setup transaction."""

    plan = build_bootstrap_plan(capability_ids)
    report_plan(plan)
    return execute_provider_plan(
        plan,
        allow_provider_mutation=allow_provider_mutation,
    )


def _successful(result: ManagedExecutionResult) -> bool:
    return (
        result.execution is not None
        and result.execution.outcome in {PlanOutcome.NO_CHANGES, PlanOutcome.SUCCEEDED}
        and result.persistence
        in {PersistenceOutcome.NOT_REQUIRED, PersistenceOutcome.SUCCEEDED}
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent_tools.native_setup",
        description="internal clone-bootstrap native provider delegation",
    )
    parser.add_argument(
        "--allow-provider-mutation",
        action="store_true",
        help="authorize the reviewed package-manager plan",
    )
    parser.add_argument("capability", nargs="+", help="built-in capability identity")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = native_setup(
            args.capability,
            allow_provider_mutation=args.allow_provider_mutation,
        )
    except (
        ManagedExecutionInterrupted,
        PersistenceInterrupted,
        ProviderPlanInterrupted,
    ) as interruption:
        result = interruption.managed_result
        if result is not None:
            report_result(result)
        print(f"Native provider setup interrupted: {interruption}", file=sys.stderr)
        return 130
    except (
        NativeSetupError,
        PlanningError,
        ManagedStateError,
        DesiredStateError,
        ExecutionContractError,
    ) as error:
        print(f"Native provider setup failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Native provider setup interrupted before managed execution", file=sys.stderr)
        return 130
    report_result(result)
    return 0 if _successful(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
