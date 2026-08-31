import os
import subprocess
import unittest
from dataclasses import replace
from unittest.mock import Mock

from agent_tools import capabilities
from agent_tools import provider_execution
from agent_tools import provider_plans


class ProviderExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = capabilities.MachineState("Linux", "x86_64")
        self.manager = provider_plans.PackageManagerState(
            "apt", "/usr/bin/apt-get", "host", "x86_64"
        )

    def state(self, capability, *, available=False, architecture="x86_64"):
        return capabilities.detect_capability(
            capability,
            self.machine,
            locator=lambda probe, machine: (
                f"/tools/{probe.name}" if available else None
            ),
            version_reader=lambda probe, path: "1.0",
            architecture_reader=lambda probe, path: architecture,
        )

    def plan(self, capability=capabilities.GHOSTSCRIPT):
        state = self.state(capability)
        return provider_plans.generate_provider_plan(
            (state,),
            (capability.capability_id,),
            package_managers=(self.manager,),
        )

    def detector_sequence(self, *states):
        values = iter(states)

        def detect(capability, machine):
            self.assertEqual(machine, self.machine)
            return next(values)

        return detect

    def execute(self, plan, **kwargs):
        defaults = {
            "allow_provider_mutation": True,
            "current_context": lambda: self.machine,
            "manager_verifier": lambda state, machine: True,
            "privilege_resolver": lambda action: "/usr/bin/sudo",
        }
        defaults.update(kwargs)
        return provider_execution.execute_provider_plan(plan, **defaults)

    def test_zero_action_plan_needs_no_mutation_authorization(self):
        state = self.state(capabilities.GHOSTSCRIPT, available=True)
        plan = provider_plans.generate_provider_plan(
            (state,), ("ghostscript",), package_managers=(self.manager,)
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution.execute_provider_plan(
            plan,
            current_context=lambda: self.machine,
            runner=runner,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.NO_CHANGES)
        self.assertEqual(report.actions, ())
        runner.assert_not_called()

    def test_mutating_plan_refuses_without_dedicated_authorization(self):
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution.execute_provider_plan(
            self.plan(),
            current_context=lambda: self.machine,
            runner=runner,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.REFUSED)
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.REFUSED,
        )
        self.assertIn("explicit provider-mutation", report.recovery_guidance[0])
        runner.assert_not_called()

    def test_plan_for_another_context_fails_before_execution(self):
        runner = Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError, "different execution context"
        ):
            self.execute(
                self.plan(),
                current_context=lambda: capabilities.MachineState(
                    "Linux", "arm64", "host"
                ),
                runner=runner,
            )
        runner.assert_not_called()

    def test_caller_cannot_replace_catalogue_reviewed_commands(self):
        plan = self.plan()
        forged = replace(
            plan,
            actions=(replace(plan.actions[0], commands=(("/bin/sh", "-c", "bad"),)),),
        )
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError, "reviewed adapter"
        ):
            self.execute(forged)

    def test_contradictory_pre_action_detection_fails_before_mutation(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        contradictory = replace(
            absent,
            availability=capabilities.Availability.AVAILABLE,
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError,
            "pre-action detection is not authoritative",
        ):
            self.execute(
                self.plan(),
                detector=self.detector_sequence(contradictory),
                runner=runner,
            )
        runner.assert_not_called()

    def test_success_executes_with_privilege_then_rediscovers_provider(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        calls = []

        def run(argv, timeout):
            calls.append((argv, timeout))
            return subprocess.CompletedProcess(argv, 0, "installed", "")

        report = self.execute(
            plan,
            detector=self.detector_sequence(absent, available),
            runner=run,
            timeout_seconds=17,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.SUCCEEDED)
        self.assertEqual(report.actions[0].outcome, provider_execution.ActionOutcome.SUCCEEDED)
        self.assertEqual(calls[0][0][0], "/usr/bin/sudo")
        self.assertEqual(calls[0][0][1:], plan.actions[0].commands[0])
        self.assertEqual(calls[0][1], 17)
        self.assertEqual(
            report.actions[0].final_verified_paths,
            ("/tools/gs", "/tools/gswin64c", "/tools/gswin32c"),
        )

    def test_false_success_is_reported_as_partial_failure(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        report = self.execute(
            plan,
            detector=self.detector_sequence(absent, absent),
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "ok", ""),
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PARTIAL_FAILURE)
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )
        self.assertIn("partial host state", report.recovery_guidance[0])

    def test_timeout_is_bounded_and_reported(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)

        def timeout(argv, seconds):
            raise subprocess.TimeoutExpired(argv, seconds, output="partial")

        report = self.execute(
            plan,
            detector=self.detector_sequence(absent),
            runner=timeout,
            timeout_seconds=3,
        )
        action = report.actions[0]
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.TIMED_OUT)
        self.assertTrue(action.commands[0].timed_out)
        self.assertEqual(action.commands[0].stdout, "partial")

    def test_nonzero_command_stops_action_and_reports_output(self):
        plan = self.plan(capabilities.POPPLER)
        absent = self.state(capabilities.POPPLER)
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                plan.actions[0].commands[0], 23, "", "provider unavailable"
            )
        )
        report = self.execute(
            plan,
            detector=self.detector_sequence(absent),
            runner=runner,
        )
        action = report.actions[0]
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.COMMAND_FAILED)
        self.assertEqual(action.commands[0].returncode, 23)
        self.assertEqual(action.commands[0].stderr, "provider unavailable")
        runner.assert_called_once()

    def test_command_start_failure_does_not_claim_partial_host_state(self):
        absent = self.state(capabilities.GHOSTSCRIPT)

        def cannot_start(argv, timeout):
            raise FileNotFoundError("manager disappeared")

        report = self.execute(
            self.plan(),
            detector=self.detector_sequence(absent),
            runner=cannot_start,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.COMMAND_FAILED,
        )
        self.assertIn("no provider command started", report.recovery_guidance[0])
        self.assertNotIn("partial host state", report.recovery_guidance[0])

    def test_later_command_start_failure_reports_prior_possible_mutation(self):
        plan = self.plan(capabilities.POPPLER)
        absent = self.state(capabilities.POPPLER)
        calls = 0

        def fail_second_command(argv, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return subprocess.CompletedProcess(argv, 0, "updated", "")
            raise FileNotFoundError("manager disappeared")

        report = self.execute(
            plan,
            detector=self.detector_sequence(absent),
            runner=fail_second_command,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.COMMAND_FAILED,
        )
        self.assertEqual(len(report.actions[0].commands), 2)
        self.assertIn("partial host state", report.recovery_guidance[0])

    def test_failure_reports_later_requested_action_as_not_attempted(self):
        states = (
            self.state(capabilities.GHOSTSCRIPT),
            self.state(capabilities.POPPLER),
        )
        plan = provider_plans.generate_provider_plan(
            states,
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                plan.actions[0].commands[0], 1, "", "failed"
            )
        )
        report = self.execute(
            plan,
            detector=self.detector_sequence(states[0]),
            runner=runner,
        )
        self.assertEqual(len(report.actions), 2)
        self.assertEqual(
            report.actions[1].outcome,
            provider_execution.ActionOutcome.NOT_ATTEMPTED,
        )
        runner.assert_called_once()

    def test_stale_manager_identity_and_missing_privilege_fail_closed(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        for verifier, resolver, outcome in (
            (
                lambda state, machine: False,
                lambda action: "/usr/bin/sudo",
                provider_execution.ActionOutcome.MANAGER_UNAVAILABLE,
            ),
            (
                lambda state, machine: True,
                lambda action: None,
                provider_execution.ActionOutcome.PRIVILEGE_UNAVAILABLE,
            ),
        ):
            with self.subTest(outcome=outcome):
                report = self.execute(
                    self.plan(),
                    detector=self.detector_sequence(absent),
                    manager_verifier=verifier,
                    privilege_resolver=resolver,
                )
                self.assertEqual(report.actions[0].outcome, outcome)
                self.assertIn(
                    "no provider command started", report.recovery_guidance[0]
                )
                self.assertNotIn("partial host state", report.recovery_guidance[0])

    def test_repeat_skips_commands_when_planned_provider_now_verifies(self):
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        runner = Mock(side_effect=AssertionError("must not run"))
        report = self.execute(
            self.plan(),
            detector=self.detector_sequence(available),
            runner=runner,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.SUCCEEDED)
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.ALREADY_SATISFIED,
        )
        runner.assert_not_called()

    def test_refreshed_precheck_skips_newly_visible_provider(self):
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        runner = Mock(side_effect=AssertionError("must not run"))
        original = os.environ.get("PATH")

        def detect(capability, machine):
            self.assertEqual(os.environ.get("PATH"), "/persisted")
            return available

        report = self.execute(
            self.plan(),
            detector=detect,
            runner=runner,
            environment_refresher=lambda action: {"PATH": "/persisted"},
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.ALREADY_SATISFIED,
        )
        self.assertEqual(os.environ.get("PATH"), original)
        runner.assert_not_called()

    def test_environment_refresh_is_temporary_and_precedes_verification(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        original = os.environ.get("PATH")
        calls = 0

        def detect(capability, machine):
            nonlocal calls
            calls += 1
            self.assertEqual(os.environ.get("PATH"), "/refreshed")
            if calls == 1:
                return absent
            return available

        report = self.execute(
            plan,
            detector=detect,
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
            environment_refresher=lambda action: {"PATH": "/refreshed"},
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.SUCCEEDED)
        self.assertEqual(os.environ.get("PATH"), original)

    def test_native_replacement_requires_target_architecture_after_mutation(self):
        machine = capabilities.MachineState("Windows", "arm64")
        manager = provider_plans.PackageManagerState(
            "winget", "C:/Windows/System32/winget.exe", "host"
        )

        def state(architecture):
            return capabilities.detect_capability(
                capabilities.BASH,
                machine,
                locator=lambda probe, context: (
                    "C:/Git/bin/bash.exe"
                    if probe.locator_strategy == "git-bash"
                    else None
                ),
                version_reader=lambda probe, path: "GNU bash 5.2",
                architecture_reader=lambda probe, path: architecture,
            )

        translated = state("x86_64")
        plan = provider_plans.generate_provider_plan(
            (translated,),
            ("bash",),
            package_managers=(manager,),
            native_provisioning=("bash",),
        )
        report = provider_execution.execute_provider_plan(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            manager_verifier=lambda state, context: True,
            privilege_resolver=lambda action: "",
            detector=self.detector_sequence_for_machine(machine, translated, translated),
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )
        self.assertEqual(report.actions[0].target_architecture, "arm64")
        self.assertEqual(
            report.actions[0].displaces_verified_paths,
            plan.actions[0].displaces_verified_paths,
        )

    def detector_sequence_for_machine(self, machine, *states):
        values = iter(states)

        def detect(capability, current):
            self.assertEqual(current, machine)
            return next(values)

        return detect


if __name__ == "__main__":
    unittest.main()
