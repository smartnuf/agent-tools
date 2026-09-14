"""Public install scope and managed-lifecycle tests; no real host mutation."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities as cap
from agent_tools import cli, desired_state, managed_state, native_setup
from agent_tools import provider_execution as execution
from agent_tools import provider_plans as plans


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.machine = cap.MachineState("Linux", "x86_64")
        self.manager = plans.PackageManagerState("apt", "/verified/apt-get", "host", "x86_64")

    def state(self, capability, available=True):
        return cap.detect_capability(
            capability, self.machine,
            locator=lambda probe, context: f"/tools/{probe.name}" if available else None,
            version_reader=lambda probe, path: "1.0",
            architecture_reader=lambda probe, path: "x86_64",
        )

    def test_named_only_ignores_unrelated_semantics_and_retains_clone_union(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"schema_version": 1, "capabilities": {
                "bash": {"provider": "system-bash"}, "future-capability": {"provider": "future"}
            }}))
            before = path.read_bytes()
            stack.enter_context(patch.object(native_setup, "current_machine", return_value=self.machine))
            detect = stack.enter_context(patch.object(native_setup, "detect_capabilities",
                side_effect=lambda catalogue, machine: tuple(self.state(c) for c in catalogue)))
            managers = stack.enter_context(patch.object(native_setup, "detect_package_managers",
                side_effect=AssertionError("satisfied request must not discover managers")))
            plan = native_setup.build_install_plan(("poppler", "poppler"), config_path=path)
            self.assertEqual(plan.requested_capabilities, ("poppler",))
            self.assertEqual(plan.provider_preferences, ())
            self.assertEqual(plan.actions, ())
            self.assertEqual(tuple(c.capability_id for c in detect.call_args.args[0]), ("poppler",))
            managers.assert_not_called()
            with self.assertRaisesRegex(desired_state.DesiredStateError, "unsupported"):
                native_setup.build_bootstrap_plan(("poppler",), config_path=path)
            self.assertEqual(path.read_bytes(), before)
            document = json.loads(before)
            del document["capabilities"]["future-capability"]
            path.write_text(json.dumps(document))
            clone = native_setup.build_bootstrap_plan(("poppler",), config_path=path)
            self.assertEqual(clone.requested_capabilities, ("poppler", "bash"))
            self.assertEqual(clone.provider_preferences, (("bash", "system-bash"),))

    def test_requested_preference_is_exact_and_invalid_preference_fails(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / "config.json"
            stack.enter_context(patch.object(native_setup, "current_machine", return_value=self.machine))
            stack.enter_context(patch.object(native_setup, "detect_capabilities",
                side_effect=lambda catalogue, machine: tuple(self.state(c) for c in catalogue)))
            for provider in ("system-bash", "git-bash", "unknown-provider"):
                with self.subTest(provider=provider):
                    path.write_text(json.dumps({"schema_version": 1, "capabilities": {
                        "bash": {"provider": provider}
                    }}))
                    if provider == "system-bash":
                        plan = native_setup.build_install_plan(("bash",), config_path=path)
                        self.assertEqual(plan.provider_preferences, (("bash", "system-bash"),))
                    else:
                        with self.assertRaises(desired_state.DesiredStateError):
                            native_setup.build_install_plan(("bash",), config_path=path)

    def test_unavailable_exact_preference_plans_it_instead_of_accepting_other_provider(self):
        machine = cap.MachineState("Darwin", "arm64")
        manager = plans.PackageManagerState("brew", "/opt/homebrew/bin/brew", "host", "arm64")
        state = cap.detect_capability(
            cap.BASH, machine,
            locator=lambda probe, context: "/bin/bash" if probe.locator_strategy == "system-bash" else None,
            version_reader=lambda probe, path: "3.2",
            architecture_reader=lambda probe, path: "arm64",
        )
        self.assertEqual(state.selected_provider.provider.provider_id, "system-bash")
        with TemporaryDirectory() as directory, ExitStack() as stack:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"schema_version": 1, "capabilities": {
                "bash": {"provider": "homebrew-bash"}
            }}))
            stack.enter_context(patch.object(native_setup, "current_machine", return_value=machine))
            stack.enter_context(patch.object(native_setup, "detect_capabilities", return_value=(state,)))
            stack.enter_context(patch.object(native_setup, "detect_package_managers", return_value=(manager,)))
            plan = native_setup.build_install_plan(("bash",), config_path=path)
            self.assertEqual(plan.provider_preferences, (("bash", "homebrew-bash"),))
            self.assertEqual(plan.actions[0].provider_id, "homebrew-bash")

    def test_malformed_configuration_blocks_even_unrelated_entries_without_writes(self):
        for raw in ('not json', '{"schema_version":2,"capabilities":{}}',
                    '{"schema_version":1,"capabilities":{"future":{"unexpected":true}}}'):
            with self.subTest(raw=raw), TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(raw)
                with patch.object(native_setup, "detect_capabilities") as detect:
                    with self.assertRaises(desired_state.DesiredStateError):
                        native_setup.build_install_plan(("poppler",), config_path=path)
                    detect.assert_not_called()
                self.assertEqual(path.read_text(), raw)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_arguments_and_help_never_discover_or_execute(self):
        cases = [([], 2), (["unknown"], 2),
                 (["poppler", "--dry-run", "--allow-provider-mutation"], 2),
                 (["--help"], 0), (["-h"], 0)]
        with patch.object(cli, "install_capabilities") as install:
            for args, expected in cases:
                with self.subTest(args=args), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as result:
                        cli.main(["install", *args])
                    self.assertEqual(result.exception.code, expected)
            install.assert_not_called()

    def test_dry_run_never_enters_managed_execution(self):
        plan = plans.generate_provider_plan((self.state(cap.GHOSTSCRIPT, False),),
            ("ghostscript",), package_managers=(self.manager,))
        with patch.object(native_setup, "build_install_plan", return_value=plan), \
             patch.object(native_setup, "execute_provider_plan") as execute, \
             redirect_stdout(StringIO()) as output:
            self.assertEqual(cli.main(["install", "ghostscript", "--dry-run"]), 0)
            execute.assert_not_called()
        self.assertIn("requested capabilities: ghostscript", output.getvalue())
        self.assertIn("requested command:", output.getvalue())
        self.assertIn("Dry run: plan only", output.getvalue())
        self.assertNotIn("Host mutation:", output.getvalue())

    def test_public_cli_uses_real_managed_executor_and_disposable_provider_then_noops(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            marker = root / "installed"
            config_path = root / "config.json"
            config_path.write_text('{"schema_version":1,"capabilities":{"bash":{}}}')
            config_before = config_path.read_bytes()
            state_path = root / "managed-state.json"
            helper = root / "manager.py"
            helper.write_text("from pathlib import Path\nimport sys\n"
                              "if 'install' in sys.argv: Path(sys.argv[1]).touch()\n")
            def detect(capability, machine):
                self.assertEqual(capability, cap.GHOSTSCRIPT)
                return self.state(capability, marker.exists())
            calls = []
            def run(argv, timeout):
                calls.append(argv)
                return subprocess.run((sys.executable, str(helper), str(marker),
                    *argv[argv.index(self.manager.executable_path) + 1:]),
                    capture_output=True, text=True, timeout=timeout)
            def execute(plan, **kwargs):
                self.assertEqual(plan.requested_capabilities, ("ghostscript",))
                self.assertIn("requested command:", output.getvalue())
                return managed_state.execute_provider_plan(plan, state_path=state_path,
                    current_context=lambda: self.machine, detector=detect,
                    manager_verifier=lambda manager, machine: True,
                    privilege_resolver=lambda action: "",
                    supervisor_resolver=lambda action: "/usr/bin/timeout",
                    privilege_preflight=lambda argv: True, runner=run, **kwargs)
            stack.enter_context(patch.object(native_setup, "current_machine", return_value=self.machine))
            stack.enter_context(patch.object(native_setup, "desired_state_path", return_value=config_path))
            stack.enter_context(patch.object(native_setup, "detect_capabilities",
                side_effect=lambda catalogue, machine: tuple(detect(c, machine) for c in catalogue)))
            stack.enter_context(patch.object(native_setup, "detect_package_managers", return_value=(self.manager,)))
            stack.enter_context(patch.object(native_setup, "execute_provider_plan", side_effect=execute))
            output = stack.enter_context(redirect_stdout(StringIO()))
            self.assertEqual(cli.main(["install", "ghostscript"]), 1)
            self.assertFalse(marker.exists())
            self.assertFalse(state_path.exists())
            self.assertEqual(calls, [])
            self.assertIn("Host mutation: refused", output.getvalue())
            self.assertEqual(cli.main(["install", "ghostscript", "--allow-provider-mutation"]), 0)
            self.assertTrue(marker.exists())
            self.assertEqual(len(calls), 2)
            records = managed_state.load_document(state_path)["records"]
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["ownership"])
            provenance_before = state_path.read_bytes()
            self.assertEqual(cli.main(["install", "ghostscript"]), 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual(state_path.read_bytes(), provenance_before)
            self.assertEqual(config_path.read_bytes(), config_before)
            self.assertIn("Host mutation: no-changes", output.getvalue())

    def test_failure_and_interruption_preserve_managed_reporting(self):
        report = execution.PlanExecutionReport(self.machine, ("ghostscript",),
            execution.PlanOutcome.PARTIAL_FAILURE, (), ("inspect uncertain result before retry",))
        cases = [
            managed_state.ManagedExecutionResult(report, managed_state.PersistenceOutcome.FAILED,
                                                 persistence_detail="disk full"),
            managed_state.ManagedExecutionResult(None, managed_state.PersistenceOutcome.BLOCKED,
                                                 persistence_detail="corrupt state"),
        ]
        plan = plans.generate_provider_plan((self.state(cap.GHOSTSCRIPT, False),),
            ("ghostscript",), package_managers=(self.manager,))
        for result in cases:
            with self.subTest(result=result), patch.object(native_setup, "build_install_plan", return_value=plan), \
                 patch.object(native_setup, "execute_provider_plan", return_value=result), \
                 redirect_stdout(StringIO()) as output:
                self.assertEqual(cli.main(["install", "ghostscript", "--allow-provider-mutation"]), 1)
                self.assertIn(result.persistence_detail, output.getvalue())
        interruption = managed_state.ManagedExecutionInterrupted(KeyboardInterrupt())
        interruption.managed_result = cases[0]
        with patch.object(native_setup, "build_install_plan", return_value=plan), \
             patch.object(native_setup, "execute_provider_plan", side_effect=interruption), \
             redirect_stdout(StringIO()) as output, redirect_stderr(StringIO()) as errors:
            self.assertEqual(cli.main(["install", "ghostscript", "--allow-provider-mutation"]), 130)
            self.assertIn("inspect uncertain result before retry", output.getvalue())
            self.assertIn("disk full", output.getvalue())
            self.assertIn("interrupted", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
