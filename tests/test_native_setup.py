from __future__ import annotations

import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import (
    capabilities,
    desired_state,
    managed_state,
    native_setup,
    provider_execution,
)


class NativeSetupTests(unittest.TestCase):
    def test_homebrew_evidence_probe_disables_automatic_update(self) -> None:
        completed = subprocess.CompletedProcess(("brew", "--prefix"), 0, "/brew\n", "")
        with patch.object(
            native_setup, "run_bounded_command", return_value=completed
        ) as run:
            self.assertIs(native_setup._run_probe(("brew", "--prefix"), 10), completed)
        environment = run.call_args.kwargs["environment"]
        self.assertEqual(environment["HOMEBREW_NO_AUTO_UPDATE"], "1")

    def test_linux_manager_discovery_preserves_order_and_environment(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            apt = root / "apt-get"
            dnf = root / "dnf"
            apt.touch()
            dnf.touch()
            located = {"apt-get": str(apt), "dnf": str(dnf)}

            managers = native_setup.detect_package_managers(
                capabilities.MachineState("Linux", "x86_64", "wsl"),
                locator=located.get,
            )

        self.assertEqual(tuple(item.manager for item in managers), ("apt", "dnf"))
        self.assertTrue(all(item.execution_environment == "wsl" for item in managers))
        self.assertEqual(managers[0].resolved_executable_path, str(apt.resolve()))

    def test_manager_discovery_rejects_relative_identity(self) -> None:
        with self.assertRaisesRegex(native_setup.NativeSetupError, "non-absolute"):
            native_setup.detect_package_managers(
                capabilities.MachineState("Linux", "x86_64"),
                locator=lambda command: "bin/apt-get" if command == "apt-get" else None,
            )

    def test_homebrew_discovery_requires_prefix_and_architecture_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            prefix = Path(directory)
            executable = prefix / "bin" / "brew"
            executable.parent.mkdir()
            executable.touch()

            def run(argv: tuple[str, ...], timeout: int) -> subprocess.CompletedProcess[str]:
                self.assertEqual(timeout, 10)
                output = str(prefix) if argv[1:] == ("--prefix",) else "arm64"
                return subprocess.CompletedProcess(argv, 0, output + "\n", "")

            managers = native_setup.detect_package_managers(
                capabilities.MachineState("Darwin", "arm64"),
                locator=lambda command: str(executable),
                runner=run,
            )

        self.assertEqual(len(managers), 1)
        self.assertEqual(managers[0].manager, "brew")
        self.assertEqual(managers[0].architecture, "arm64")
        self.assertEqual(managers[0].installation_root, str(prefix))

    def test_all_satisfied_bootstrap_plan_needs_no_package_manager(self) -> None:
        machine = capabilities.MachineState("Linux", "x86_64")
        states = tuple(
            capabilities.detect_capability(
                capability,
                machine,
                locator=lambda probe, context: f"/verified/{probe.name}",
                version_reader=lambda probe, path: "1.0",
            )
            for capability in (capabilities.POPPLER, capabilities.GHOSTSCRIPT)
        )
        with TemporaryDirectory() as directory:
            with (
                patch.object(native_setup, "current_machine", return_value=machine),
                patch.object(native_setup, "detect_capabilities", return_value=states),
                patch.object(
                    native_setup,
                    "detect_package_managers",
                    side_effect=AssertionError("all-satisfied setup queried a manager"),
                ),
            ):
                plan = native_setup.build_bootstrap_plan(
                    ("poppler", "ghostscript"),
                    config_path=Path(directory) / "config.json",
                )

        self.assertFalse(plan.changes_host)
        self.assertEqual(plan.actions, ())

    def test_bootstrap_consumes_enabled_capability_and_exact_preference(self) -> None:
        machine = capabilities.MachineState("Linux", "x86_64")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            desired_state.set_capability(
                "bash",
                enabled=True,
                provider_id="system-bash",
                allow_config_mutation=True,
                path=path,
                machine=machine,
            )

            def detect(catalogue, context):
                self.assertEqual(context, machine)
                return tuple(
                    capabilities.detect_capability(
                        capability,
                        machine,
                        locator=lambda probe, current: f"/verified/{probe.name}",
                        version_reader=lambda probe, executable: "1.0",
                        architecture_reader=lambda probe, executable: "x86_64",
                    )
                    for capability in catalogue
                )

            with (
                patch.object(native_setup, "current_machine", return_value=machine),
                patch.object(native_setup, "detect_capabilities", side_effect=detect),
                patch.object(
                    native_setup,
                    "detect_package_managers",
                    side_effect=AssertionError("verified desired provider queried a manager"),
                ),
            ):
                plan = native_setup.build_bootstrap_plan(
                    ("poppler", "ghostscript", "poppler"), config_path=path
                )

        self.assertEqual(
            plan.requested_capabilities, ("poppler", "ghostscript", "bash")
        )
        self.assertEqual(plan.provider_preferences, (("bash", "system-bash"),))
        self.assertEqual(plan.actions, ())

    def test_bootstrap_fails_closed_on_unreadable_desired_state(self) -> None:
        machine = capabilities.MachineState("Linux", "x86_64")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("not json", encoding="utf-8")
            with (
                patch.object(native_setup, "current_machine", return_value=machine),
                patch.object(
                    native_setup,
                    "detect_capabilities",
                    side_effect=AssertionError("corrupt desired state reached detection"),
                ),
                self.assertRaises(desired_state.DesiredStateError),
            ):
                native_setup.build_bootstrap_plan(("poppler",), config_path=path)

    def test_cli_reports_desired_state_failure_without_traceback(self) -> None:
        with (
            patch.object(
                native_setup,
                "native_setup",
                side_effect=desired_state.DesiredStateError("corrupt config"),
            ),
            redirect_stdout(StringIO()) as output,
            redirect_stderr(StringIO()) as errors,
        ):
            status = native_setup.main(["poppler"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("corrupt config", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_native_setup_delegates_plan_and_explicit_authorization(self) -> None:
        plan = Mock()
        result = managed_state.ManagedExecutionResult(
            provider_execution.PlanExecutionReport(
                None,
                ("poppler", "ghostscript"),
                provider_execution.PlanOutcome.NO_CHANGES,
                (),
            ),
            managed_state.PersistenceOutcome.NOT_REQUIRED,
        )
        with (
            patch.object(native_setup, "build_bootstrap_plan", return_value=plan) as build,
            patch.object(native_setup, "report_plan") as report,
            patch.object(native_setup, "execute_provider_plan", return_value=result) as execute,
        ):
            actual = native_setup.native_setup(
                ("poppler", "ghostscript"),
                allow_provider_mutation=True,
            )

        self.assertIs(actual, result)
        build.assert_called_once_with(("poppler", "ghostscript"))
        report.assert_called_once_with(plan)
        execute.assert_called_once_with(plan, allow_provider_mutation=True)

    def test_cli_propagates_actionable_failure_without_traceback(self) -> None:
        with (
            patch.object(
                native_setup,
                "native_setup",
                side_effect=native_setup.NativeSetupError("no verified package manager"),
            ),
            redirect_stdout(StringIO()) as output,
            redirect_stderr(StringIO()) as errors,
        ):
            status = native_setup.main(
                ["--allow-provider-mutation", "poppler", "ghostscript"]
            )

        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("no verified package manager", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_cli_returns_success_only_for_complete_host_and_persistence_outcomes(self) -> None:
        execution = provider_execution.PlanExecutionReport(
            capabilities.MachineState("Linux", "x86_64"),
            ("poppler", "ghostscript"),
            provider_execution.PlanOutcome.SUCCEEDED,
            (),
        )
        cases = (
            (managed_state.PersistenceOutcome.SUCCEEDED, 0),
            (managed_state.PersistenceOutcome.FAILED, 1),
            (managed_state.PersistenceOutcome.UNKNOWN, 1),
        )
        for persistence, expected in cases:
            with self.subTest(persistence=persistence):
                result = managed_state.ManagedExecutionResult(execution, persistence)
                with (
                    patch.object(native_setup, "native_setup", return_value=result),
                    redirect_stdout(StringIO()),
                ):
                    self.assertEqual(
                        native_setup.main(
                            ["--allow-provider-mutation", "poppler", "ghostscript"]
                        ),
                        expected,
                    )

    def test_failure_report_keeps_host_and_persistence_facts_separate(self) -> None:
        action = provider_execution.ActionReport(
            "poppler",
            "host-poppler",
            "apt",
            "poppler-utils",
            provider_execution.ActionOutcome.COMMAND_FAILED,
            (
                provider_execution.CommandReport(
                    ("/usr/bin/apt-get", "install", "-y", "poppler-utils"),
                    100,
                    "",
                    "provider unavailable",
                ),
            ),
            detail="package-manager command failed",
        )
        result = managed_state.ManagedExecutionResult(
            provider_execution.PlanExecutionReport(
                capabilities.MachineState("Linux", "x86_64"),
                ("poppler",),
                provider_execution.PlanOutcome.PARTIAL_FAILURE,
                (action,),
                ("rediscover current machine state before retry",),
            ),
            managed_state.PersistenceOutcome.SUCCEEDED,
        )
        with redirect_stdout(StringIO()) as output:
            native_setup.report_result(result)

        rendered = output.getvalue()
        self.assertIn("Host mutation: partial-failure", rendered)
        self.assertIn("provider unavailable", rendered)
        self.assertIn("rediscover current machine state before retry", rendered)
        self.assertIn("Managed provenance: succeeded", rendered)


if __name__ == "__main__":
    unittest.main()
