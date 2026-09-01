import os
import subprocess
import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

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
            "supervisor_resolver": lambda action: "/usr/bin/timeout",
            "privilege_preflight": lambda argv: True,
        }
        defaults.update(kwargs)
        return provider_execution._execute_provider_plan_unmanaged(plan, **defaults)

    def test_zero_action_plan_needs_no_mutation_authorization(self):
        state = self.state(capabilities.GHOSTSCRIPT, available=True)
        plan = provider_plans.generate_provider_plan(
            (state,), ("ghostscript",), package_managers=(self.manager,)
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            current_context=lambda: self.machine,
            detector=lambda capability, machine: state,
            runner=runner,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.NO_CHANGES)
        self.assertEqual(report.actions, ())
        runner.assert_not_called()

    def test_command_interruption_carries_partial_report(self):
        result = subprocess.CompletedProcess(
            ("/usr/bin/sudo",), -2, "partial output", "interrupted"
        )

        def interrupt(argv, timeout):
            raise provider_execution.CommandInterruptedError(result)

        with self.assertRaises(provider_execution.ProviderPlanInterrupted) as raised:
            self.execute(
                self.plan(),
                detector=lambda capability, machine: self.state(capability),
                runner=interrupt,
            )
        report = raised.exception.report
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PARTIAL_FAILURE)
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.INTERRUPTED,
        )
        self.assertEqual(report.actions[0].commands[0].stdout, "partial output")

    def test_post_command_verification_exception_returns_partial_evidence(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        detector = Mock(side_effect=(absent, RuntimeError("verification broke")))
        report = self.execute(
            self.plan(),
            detector=detector,
            runner=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "installed", ""
            ),
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PARTIAL_FAILURE)
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )
        self.assertEqual(report.actions[0].commands[0].returncode, 0)
        self.assertEqual(report.actions[0].commands[0].stdout, "installed")
        self.assertIn("RuntimeError: verification broke", report.actions[0].detail)

    def test_later_precheck_interrupt_preserves_completed_action_only(self):
        ghostscript_absent = self.state(capabilities.GHOSTSCRIPT)
        ghostscript_available = self.state(
            capabilities.GHOSTSCRIPT, available=True
        )
        poppler_absent = self.state(capabilities.POPPLER)
        plan = provider_plans.generate_provider_plan(
            (ghostscript_absent, poppler_absent),
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        detector = Mock(
            side_effect=(
                ghostscript_absent,
                ghostscript_available,
                KeyboardInterrupt(),
            )
        )
        with self.assertRaises(provider_execution.ProviderPlanInterrupted) as raised:
            self.execute(
                plan,
                detector=detector,
                runner=lambda argv, timeout: subprocess.CompletedProcess(
                    argv, 0, "installed", ""
                ),
            )
        report = raised.exception.report
        self.assertEqual(report.actions[0].outcome, provider_execution.ActionOutcome.SUCCEEDED)
        self.assertEqual(report.actions[0].commands[0].stdout, "installed")
        self.assertEqual(
            report.actions[1].outcome,
            provider_execution.ActionOutcome.NOT_ATTEMPTED,
        )
        self.assertEqual(report.actions[1].commands, ())

    def test_later_capability_lookup_interrupt_preserves_completed_action(self):
        ghostscript_absent = self.state(capabilities.GHOSTSCRIPT)
        ghostscript_available = self.state(
            capabilities.GHOSTSCRIPT, available=True
        )
        poppler_absent = self.state(capabilities.POPPLER)
        plan = provider_plans.generate_provider_plan(
            (ghostscript_absent, poppler_absent),
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        original = provider_execution.get_capability
        poppler_lookups = 0

        def interrupt_later_poppler_lookup(capability_id):
            nonlocal poppler_lookups
            if capability_id == "poppler":
                poppler_lookups += 1
                if poppler_lookups == 2:
                    raise KeyboardInterrupt()
            return original(capability_id)

        with (
            patch.object(
                provider_execution,
                "get_capability",
                side_effect=interrupt_later_poppler_lookup,
            ),
            self.assertRaises(provider_execution.ProviderPlanInterrupted) as raised,
        ):
            self.execute(
                plan,
                detector=self.detector_sequence(
                    ghostscript_absent, ghostscript_available
                ),
                runner=lambda argv, timeout: subprocess.CompletedProcess(
                    argv, 0, "installed", ""
                ),
            )
        report = raised.exception.report
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.SUCCEEDED,
        )
        self.assertEqual(report.actions[0].commands[0].stdout, "installed")
        self.assertEqual(
            report.actions[1].outcome,
            provider_execution.ActionOutcome.NOT_ATTEMPTED,
        )
        self.assertEqual(report.actions[1].commands, ())

    def test_execution_preflight_interrupt_never_marks_current_action_attempted(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        phases = (
            ("manager", {"manager_verifier": Mock(side_effect=KeyboardInterrupt())}),
            ("privilege", {"privilege_resolver": Mock(side_effect=KeyboardInterrupt())}),
            ("supervisor", {"supervisor_resolver": Mock(side_effect=KeyboardInterrupt())}),
            ("sudo", {"privilege_preflight": Mock(side_effect=KeyboardInterrupt())}),
        )
        for name, overrides in phases:
            with self.subTest(phase=name):
                with self.assertRaises(
                    provider_execution.ProviderPlanInterrupted
                ) as raised:
                    self.execute(
                        self.plan(),
                        detector=lambda capability, machine: absent,
                        **overrides,
                    )
                report = raised.exception.report
                self.assertEqual(
                    report.actions[0].outcome,
                    provider_execution.ActionOutcome.NOT_ATTEMPTED,
                )
                self.assertEqual(report.actions[0].commands, ())

    def test_later_execution_preflight_exception_preserves_completed_action(self):
        ghostscript_absent = self.state(capabilities.GHOSTSCRIPT)
        ghostscript_available = self.state(
            capabilities.GHOSTSCRIPT, available=True
        )
        poppler_absent = self.state(capabilities.POPPLER)
        plan = provider_plans.generate_provider_plan(
            (ghostscript_absent, poppler_absent),
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        detector = Mock(
            side_effect=(
                ghostscript_absent,
                ghostscript_available,
                poppler_absent,
            )
        )
        manager_calls = 0

        def verify_manager(state, machine):
            nonlocal manager_calls
            manager_calls += 1
            if manager_calls == 2:
                raise RuntimeError("manager verification broke")
            return True

        report = self.execute(
            plan,
            detector=detector,
            manager_verifier=verify_manager,
            runner=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "installed", ""
            ),
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PARTIAL_FAILURE)
        self.assertEqual(report.actions[0].outcome, provider_execution.ActionOutcome.SUCCEEDED)
        self.assertEqual(report.actions[0].commands[0].stdout, "installed")
        self.assertEqual(
            report.actions[1].outcome,
            provider_execution.ActionOutcome.PREFLIGHT_FAILED,
        )
        self.assertEqual(report.actions[1].commands, ())
        self.assertIn("RuntimeError", report.actions[1].detail)

    def test_zero_action_plan_revalidates_unknown_and_stale_requests(self):
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        plan = provider_plans.generate_provider_plan(
            (available,), ("ghostscript",), package_managers=(self.manager,)
        )
        stale = self.state(capabilities.GHOSTSCRIPT)
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            current_context=lambda: self.machine,
            detector=lambda capability, machine: stale,
        )
        self.assertEqual(
            report.outcome, provider_execution.PlanOutcome.PREFLIGHT_FAILED
        )
        self.assertIn("no longer verifies", report.recovery_guidance[0])

        unknown = replace(plan, requested_capabilities=("unknown",))
        report = provider_execution._execute_provider_plan_unmanaged(
            unknown,
            current_context=lambda: self.machine,
        )
        self.assertEqual(
            report.outcome, provider_execution.PlanOutcome.PREFLIGHT_FAILED
        )
        self.assertIn("unknown requested capability", report.recovery_guidance[0])

        wrong = self.state(capabilities.POPPLER, available=True)
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            current_context=lambda: self.machine,
            detector=lambda capability, machine: wrong,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PREFLIGHT_FAILED)
        self.assertIn("different capability", report.recovery_guidance[0])

    def test_mixed_plan_revalidates_requests_omitted_from_actions(self):
        ghostscript = self.state(capabilities.GHOSTSCRIPT)
        poppler_available = self.state(capabilities.POPPLER, available=True)
        plan = provider_plans.generate_provider_plan(
            (ghostscript, poppler_available),
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        self.assertEqual(
            tuple(action.capability_id for action in plan.actions),
            ("ghostscript",),
        )
        poppler_missing = self.state(capabilities.POPPLER)
        runner = Mock(side_effect=AssertionError("must not run"))
        report = self.execute(
            plan,
            detector=lambda capability, machine: poppler_missing,
            runner=runner,
        )
        self.assertEqual(
            report.outcome,
            provider_execution.PlanOutcome.PREFLIGHT_FAILED,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.NOT_ATTEMPTED,
        )
        self.assertIn("no longer verifies: poppler", report.recovery_guidance[1])
        runner.assert_not_called()

    def test_zero_action_plan_rejects_relative_provider_identity(self):
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        plan = provider_plans.generate_provider_plan(
            (available,), ("ghostscript",), package_managers=(self.manager,)
        )
        relative = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, machine: "./gs" if probe.name == "gs" else None,
            version_reader=lambda probe, path: "1.0",
            architecture_reader=lambda probe, path: "x86_64",
        )
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            current_context=lambda: self.machine,
            detector=lambda capability, machine: relative,
        )
        self.assertEqual(report.outcome, provider_execution.PlanOutcome.PREFLIGHT_FAILED)
        self.assertIn("no longer verifies", report.recovery_guidance[0])

    def test_mutating_plan_refuses_without_dedicated_authorization(self):
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution._execute_provider_plan_unmanaged(
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

    def test_later_contradictory_preflight_preserves_prior_mutation_report(self):
        states = (
            self.state(capabilities.GHOSTSCRIPT),
            self.state(capabilities.POPPLER),
        )
        plan = provider_plans.generate_provider_plan(
            states,
            ("ghostscript", "poppler"),
            package_managers=(self.manager,),
        )
        first_available = self.state(capabilities.GHOSTSCRIPT, available=True)
        contradictory = replace(
            states[1], availability=capabilities.Availability.AVAILABLE
        )
        report = self.execute(
            plan,
            detector=self.detector_sequence(
                states[0], first_available, contradictory
            ),
            runner=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "installed", ""
            ),
        )
        self.assertEqual(
            tuple(action.outcome for action in report.actions),
            (
                provider_execution.ActionOutcome.SUCCEEDED,
                provider_execution.ActionOutcome.PREFLIGHT_FAILED,
            ),
        )
        self.assertIn("partial host state", report.recovery_guidance[0])

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
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.SUCCEEDED,
        )
        self.assertEqual(calls[0][0][:3], ("/usr/bin/sudo", "-n", "--"))
        self.assertEqual(calls[0][0][3], "/usr/bin/timeout")
        self.assertEqual(
            calls[0][0][-len(plan.actions[0].commands[0]) :],
            plan.actions[0].commands[0],
        )
        self.assertEqual(calls[0][1], 32)
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

    def test_partial_all_probe_paths_survive_verification_failure(self):
        plan = self.plan(capabilities.POPPLER)
        absent = self.state(capabilities.POPPLER)
        partial = capabilities.detect_capability(
            capabilities.POPPLER,
            self.machine,
            locator=lambda probe, context: (
                "/tools/pdfinfo" if probe.name == "pdfinfo" else None
            ),
            version_reader=lambda probe, path: "1.0",
        )
        report = self.execute(
            plan,
            detector=self.detector_sequence(absent, partial),
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )
        self.assertEqual(
            report.actions[0].final_verified_paths,
            ("/tools/pdfinfo",),
        )

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
        self.assertEqual(
            action.outcome,
            provider_execution.ActionOutcome.SUPERVISOR_FAILED,
        )
        self.assertTrue(action.commands[0].timed_out)
        self.assertEqual(action.commands[0].stdout, "partial")
        self.assertTrue(
            any("do not retry" in item for item in report.recovery_guidance)
        )
        self.assertTrue(
            any("quiesced" in item for item in report.recovery_guidance)
        )

    def test_reader_initialization_failure_reports_possible_mutation(self):
        absent = self.state(capabilities.GHOSTSCRIPT)

        def fail_after_start(argv, timeout):
            raise provider_execution.CommandInitializationError(
                subprocess.CompletedProcess(argv, -9, "partial-out", "partial-err"),
                "output reader initialization failed after the command may have started; "
                "the process was terminated and reaped",
            )

        report = self.execute(
            self.plan(),
            detector=self.detector_sequence(absent),
            runner=fail_after_start,
        )
        action = report.actions[0]
        self.assertEqual(
            action.outcome,
            provider_execution.ActionOutcome.COMMAND_START_FAILED,
        )
        self.assertEqual(action.commands[0].returncode, -9)
        self.assertEqual(action.commands[0].stdout, "partial-out")
        self.assertEqual(action.commands[0].stderr, "partial-err")
        self.assertTrue(
            any("partial host state" in item for item in report.recovery_guidance)
        )
        self.assertTrue(
            any(
                "do not retry automatically or immediately" in item
                for item in report.recovery_guidance
            )
        )

    def test_elevated_supervisor_argv_is_noninteractive_and_reports_statuses(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        for returncode, expected in (
            (124, provider_execution.ActionOutcome.COMMAND_FAILED),
            (137, provider_execution.ActionOutcome.FORCED_KILL),
            (-9, provider_execution.ActionOutcome.FORCED_KILL),
            (125, provider_execution.ActionOutcome.SUPERVISOR_FAILED),
            (126, provider_execution.ActionOutcome.COMMAND_START_FAILED),
            (127, provider_execution.ActionOutcome.COMMAND_START_FAILED),
        ):
            with self.subTest(returncode=returncode):
                calls = []

                def run(argv, timeout):
                    calls.append((argv, timeout))
                    return subprocess.CompletedProcess(
                        argv, returncode, "raw-out", "raw-err"
                    )

                report = self.execute(
                    self.plan(),
                    detector=self.detector_sequence(absent),
                    runner=run,
                    timeout_seconds=7,
                )
                action = report.actions[0]
                self.assertEqual(action.outcome, expected)
                self.assertEqual(
                    calls[0][0][:7],
                    (
                        "/usr/bin/sudo",
                        "-n",
                        "--",
                        "/usr/bin/timeout",
                        "--signal=TERM",
                        "--kill-after=5s",
                        "7s",
                    ),
                )
                self.assertEqual(calls[0][1], 22)
                self.assertEqual(action.commands[0].returncode, returncode)
                self.assertEqual(action.commands[0].stdout, "raw-out")
                self.assertEqual(action.commands[0].stderr, "raw-err")
                self.assertEqual(
                    action.commands[0].timed_out,
                    False,
                )
                if returncode in {124, 137, -9}:
                    self.assertIn(
                        (
                            "cannot distinguish"
                            if returncode == 124
                            else "not independently established"
                        ),
                        action.detail,
                    )
                if returncode in {125, 126, 127}:
                    self.assertIn("cannot distinguish", action.detail)
                    self.assertFalse(
                        any(
                            "no provider command started" in item
                            for item in report.recovery_guidance
                        )
                    )
                    self.assertTrue(
                        any(
                            "do not retry automatically or immediately" in item
                            for item in report.recovery_guidance
                        )
                    )

    def test_native_replacement_rejects_unknown_target(self):
        plan = self.plan()
        action = replace(
            plan.actions[0],
            target_architecture="unknown",
            displaces_verified_paths=("/old/provider",),
        )
        invalid = replace(
            plan,
            context=replace(plan.context, architecture="unknown"),
            actions=(action,),
        )
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError,
            "target architecture is unknown",
        ):
            provider_execution._execute_provider_plan_unmanaged(
                invalid,
                allow_provider_mutation=True,
                current_context=lambda: replace(self.machine, architecture="unknown"),
            )

    def test_planner_generated_ppc64le_native_replacement_executes(self):
        machine = capabilities.MachineState("Linux", "ppc64le")

        def bash_state(architecture):
            return capabilities.detect_capability(
                capabilities.BASH,
                machine,
                locator=lambda probe, context: (
                    "/usr/bin/bash"
                    if probe.locator_strategy == "system-bash"
                    else None
                ),
                version_reader=lambda probe, path: "GNU bash 5.2",
                architecture_reader=lambda probe, path: architecture,
            )

        translated = bash_state("x86_64")
        native = bash_state("ppc64le")
        manager = replace(self.manager, architecture="ppc64le")
        plan = provider_plans.generate_provider_plan(
            (translated,),
            ("bash",),
            package_managers=(manager,),
            native_provisioning=("bash",),
        )
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=self.detector_sequence_for_machine(machine, translated, native),
            manager_verifier=lambda state, context: True,
            privilege_resolver=lambda action: "/usr/bin/sudo",
            supervisor_resolver=lambda action: "/usr/bin/timeout",
            privilege_preflight=lambda argv: True,
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(report.actions[0].outcome, provider_execution.ActionOutcome.SUCCEEDED)
        self.assertEqual(report.actions[0].target_architecture, "ppc64le")

    def test_later_supervisor_start_failure_preserves_prior_mutation_guidance(self):
        plan = self.plan(capabilities.POPPLER)
        absent = self.state(capabilities.POPPLER)
        calls = 0

        def run(argv, timeout):
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(
                argv,
                0 if calls == 1 else 126,
                "updated" if calls == 1 else "",
                "could not invoke" if calls == 2 else "",
            )

        report = self.execute(
            plan,
            detector=self.detector_sequence(absent),
            runner=run,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.COMMAND_START_FAILED,
        )
        self.assertEqual(len(report.actions[0].commands), 2)
        self.assertIn("partial host state", report.recovery_guidance[0])

    def test_elevated_preflight_fails_before_runner_without_prompt_path(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        runner = Mock(side_effect=AssertionError("must not run"))
        preflight = Mock(return_value=False)
        report = self.execute(
            self.plan(),
            detector=self.detector_sequence(absent),
            runner=runner,
            privilege_preflight=preflight,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.PRIVILEGE_UNAVAILABLE,
        )
        preflight.assert_called_once()
        self.assertEqual(
            preflight.call_args.args[0][:3],
            ("/usr/bin/sudo", "-n", "--"),
        )
        runner.assert_not_called()

    def test_sudo_preflight_uses_noninteractive_exact_argv_and_closed_stdin(self):
        supervised = (
            "/usr/bin/sudo",
            "-n",
            "--",
            "/usr/bin/timeout",
            "--signal=TERM",
            "--kill-after=5s",
            "7s",
            "/usr/bin/apt-get",
            "update",
        )
        completed = subprocess.CompletedProcess(supervised, 0, "allowed", "")
        with patch.object(subprocess, "run", return_value=completed) as run:
            self.assertTrue(provider_execution._preflight_privilege(supervised))
        self.assertEqual(
            run.call_args.args[0],
            (
                "/usr/bin/sudo",
                "-n",
                "-l",
                "--",
                *supervised[3:],
            ),
        )
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_missing_supervisor_fails_before_mutation(self):
        absent = self.state(capabilities.GHOSTSCRIPT)
        runner = Mock(side_effect=AssertionError("must not run"))
        report = self.execute(
            self.plan(),
            detector=self.detector_sequence(absent),
            supervisor_resolver=lambda action: None,
            runner=runner,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.SUPERVISOR_FAILED,
        )
        self.assertIn("no provider command started", report.recovery_guidance[0])
        runner.assert_not_called()

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
            provider_execution.ActionOutcome.COMMAND_START_FAILED,
        )
        self.assertIn("no provider command started", report.recovery_guidance[0])
        self.assertNotIn("partial host state", report.recovery_guidance[0])

    def test_current_user_command_start_failure_is_structured(self):
        machine = capabilities.MachineState("Windows", "x86_64")
        manager = provider_plans.PackageManagerState(
            "winget", "C:/Windows/System32/winget.exe", "host", "x86_64"
        )
        absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            machine,
            locator=lambda probe, context: None,
        )
        plan = provider_plans.generate_provider_plan(
            (absent,), ("ghostscript",), package_managers=(manager,)
        )
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            manager_verifier=lambda state, context: True,
            privilege_resolver=lambda action: "",
            detector=lambda capability, context: absent,
            runner=lambda argv, timeout: (_ for _ in ()).throw(
                FileNotFoundError("winget disappeared")
            ),
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.COMMAND_START_FAILED,
        )
        self.assertIn("no provider command started", report.recovery_guidance[0])

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
            provider_execution.ActionOutcome.COMMAND_START_FAILED,
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

    def test_uncertain_retained_output_never_verifies_or_advises_retry(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        result = subprocess.CompletedProcess(
            plan.actions[0].commands[0], 0, "bounded-out", "bounded-err"
        )
        detector = Mock(return_value=absent)
        report = self.execute(
            plan,
            detector=detector,
            runner=Mock(
                side_effect=provider_execution.UncertainSupervisionError(result)
            ),
        )
        action = report.actions[0]
        self.assertEqual(
            action.outcome, provider_execution.ActionOutcome.SUPERVISOR_FAILED
        )
        self.assertEqual(action.commands[0].returncode, 0)
        self.assertEqual(action.commands[0].stdout, "bounded-out")
        self.assertIn("could not establish quiescence", action.detail)
        self.assertTrue(any("do not retry" in item for item in report.recovery_guidance))
        self.assertTrue(any("do not attempt rollback" in item for item in report.recovery_guidance))
        detector.assert_called_once()

    def test_later_uncertain_command_preserves_all_evidence_and_blocks_retry(self):
        plan = self.plan(capabilities.POPPLER)
        first, second = plan.actions[0].commands
        runner = Mock(
            side_effect=(
                subprocess.CompletedProcess(first, 0, "updated", ""),
                provider_execution.UncertainSupervisionError(
                    subprocess.CompletedProcess(second, 0, "installed?", "hook-open")
                ),
            )
        )
        report = self.execute(
            plan,
            detector=Mock(return_value=self.state(capabilities.POPPLER)),
            runner=runner,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.SUPERVISOR_FAILED,
        )
        self.assertEqual(
            tuple(command.returncode for command in report.actions[0].commands),
            (0, 0),
        )
        self.assertTrue(any("fresh plan" in item for item in report.recovery_guidance))
        self.assertFalse(any("idempotent" in item for item in report.recovery_guidance))

    def test_stale_homebrew_bash_action_skips_for_fresh_system_bash(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        manager = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "arm64"
        )
        absent = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, context: None
        )
        plan = provider_plans.generate_provider_plan(
            (absent,), ("bash",), package_managers=(manager,)
        )
        system = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, context: (
                "/bin/bash" if probe.locator_strategy == "system-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 3.2",
            architecture_reader=lambda probe, path: "arm64",
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=lambda capability, context: system,
            runner=runner,
        )
        action = report.actions[0]
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.ALREADY_SATISFIED)
        self.assertEqual(action.satisfied_by_provider_id, "system-bash")
        self.assertEqual(action.final_verified_paths, ("/bin/bash",))
        runner.assert_not_called()

    def test_fresh_provider_skip_rejects_relative_identity(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        relative = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, context: (
                "./bash" if probe.locator_strategy == "system-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "arm64",
        )
        self.assertIsNone(
            provider_execution._acceptable_current_provider(relative, None)
        )
        self.assertIsNone(
            provider_execution._acceptable_current_provider(relative, "arm64")
        )

    def test_native_probe_policy_matrix_is_shared_by_skip_and_verification(self):
        machine = capabilities.MachineState("Windows", "arm64")

        def state(capability, architectures):
            return capabilities.detect_capability(
                capability,
                machine,
                locator=lambda probe, context: (
                    f"C:/tools/{probe.name}.exe"
                    if probe.name in architectures
                    else None
                ),
                version_reader=lambda probe, path: "1.0",
                architecture_reader=lambda probe, path: architectures[probe.name],
            )

        any_mixed = state(
            capabilities.GHOSTSCRIPT,
            {"gswin64c": "arm64", "gswin32c": "x86_64"},
        )
        all_mixed = state(
            capabilities.POPPLER,
            {"pdfinfo": "arm64", "pdftotext": "arm64", "pdftoppm": "x86_64"},
        )
        self.assertEqual(
            provider_execution._acceptable_current_provider(any_mixed, "arm64"),
            ("host-ghostscript", ("C:/tools/gswin64c.exe",)),
        )
        self.assertIsNone(
            provider_execution._acceptable_current_provider(all_mixed, "arm64")
        )

        manager = provider_plans.PackageManagerState(
            "winget", "C:/Windows/System32/winget.exe", "host"
        )
        translated = state(capabilities.GHOSTSCRIPT, {"gswin32c": "x86_64"})
        plan = provider_plans.generate_provider_plan(
            (translated,),
            ("ghostscript",),
            package_managers=(manager,),
            native_provisioning=("ghostscript",),
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=lambda capability, context: any_mixed,
            runner=runner,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.ALREADY_SATISFIED,
        )
        self.assertEqual(
            report.actions[0].final_verified_paths,
            ("C:/tools/gswin64c.exe",),
        )
        runner.assert_not_called()

        mutated = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=self.detector_sequence_for_machine(
                machine, translated, any_mixed
            ),
            manager_verifier=lambda state, context: True,
            privilege_resolver=lambda action: "",
            environment_refresher=lambda action: {},
            runner=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "", ""
            ),
        )
        self.assertEqual(
            mutated.actions[0].outcome,
            provider_execution.ActionOutcome.SUCCEEDED,
        )
        self.assertEqual(
            mutated.actions[0].final_verified_paths,
            ("C:/tools/gswin64c.exe",),
        )

    def test_relative_post_install_identity_cannot_report_success(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        relative = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, context: "./gs" if probe.name == "gs" else None,
            version_reader=lambda probe, path: "1.0",
            architecture_reader=lambda probe, path: "x86_64",
        )
        report = self.execute(
            plan,
            detector=self.detector_sequence(absent, relative),
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )

    def test_detector_cannot_substitute_another_capability_pre_or_post_action(self):
        plan = self.plan()
        ghostscript_absent = self.state(capabilities.GHOSTSCRIPT)
        poppler = self.state(capabilities.POPPLER, available=True)
        runner = Mock(side_effect=AssertionError("must not run"))
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError, "different capability"
        ):
            self.execute(plan, detector=lambda capability, context: poppler, runner=runner)
        runner.assert_not_called()

        report = self.execute(
            plan,
            detector=self.detector_sequence(ghostscript_absent, poppler),
            runner=lambda argv, timeout: subprocess.CompletedProcess(argv, 0, "", ""),
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.VERIFICATION_FAILED,
        )
        self.assertIn("different capability", report.actions[0].detail)

    def test_reader_join_interruption_detaches_as_uncertain(self):
        first = Mock()
        second = Mock()
        first.join.side_effect = (KeyboardInterrupt(), None)
        second.join.return_value = None
        first.is_alive.return_value = True
        second.is_alive.return_value = True
        stop = threading.Event()
        clean = provider_execution._join_output_readers(
            (first, second), stop, []
        )
        self.assertFalse(clean)
        self.assertTrue(stop.is_set())

    def test_native_replacement_uses_any_fresh_native_provider_but_not_translated(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        manager = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "arm64"
        )

        def bash_state(system_arch=None, homebrew_arch=None):
            return capabilities.detect_capability(
                capabilities.BASH,
                machine,
                locator=lambda probe, context: (
                    "/bin/bash"
                    if probe.locator_strategy == "system-bash" and system_arch
                    else "/usr/local/bin/bash"
                    if probe.locator_strategy == "homebrew-bash" and homebrew_arch
                    else None
                ),
                version_reader=lambda probe, path: "GNU bash 5.2",
                architecture_reader=lambda probe, path: (
                    system_arch if path == "/bin/bash" else homebrew_arch
                ),
            )

        translated = bash_state(homebrew_arch="x86_64")
        plan = provider_plans.generate_provider_plan(
            (translated,),
            ("bash",),
            package_managers=(manager,),
            native_provisioning=("bash",),
        )
        fresh_native = bash_state(system_arch="arm64", homebrew_arch="x86_64")
        runner = Mock(side_effect=AssertionError("must not run"))
        skipped = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=lambda capability, context: fresh_native,
            runner=runner,
        )
        self.assertEqual(
            skipped.actions[0].outcome,
            provider_execution.ActionOutcome.ALREADY_SATISFIED,
        )
        self.assertEqual(skipped.actions[0].satisfied_by_provider_id, "system-bash")
        runner.assert_not_called()

        installed_native = bash_state(homebrew_arch="arm64")
        mutated = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            detector=self.detector_sequence_for_machine(
                machine, translated, installed_native
            ),
            manager_verifier=lambda state, context: True,
            manager_architecture_reader=lambda state: "arm64",
            privilege_resolver=lambda action: "",
            runner=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "", ""
            ),
        )
        self.assertEqual(mutated.actions[0].outcome, provider_execution.ActionOutcome.SUCCEEDED)

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

    def test_temporary_environment_refreshes_are_serialized(self):
        original = os.environ.get("PATH")
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        observed = []

        def first():
            with provider_execution._temporary_environment({"PATH": "/first"}):
                first_entered.set()
                release_first.wait(2)
                observed.append(("first", os.environ.get("PATH")))

        def second():
            first_entered.wait(2)
            with provider_execution._temporary_environment({"PATH": "/second"}):
                second_entered.set()
                observed.append(("second", os.environ.get("PATH")))

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        self.assertTrue(first_entered.wait(2))
        self.assertFalse(second_entered.wait(0.1))
        release_first.set()
        first_thread.join(2)
        second_thread.join(2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertTrue(second_entered.is_set())
        self.assertEqual(observed, [("first", "/first"), ("second", "/second")])
        self.assertEqual(os.environ.get("PATH"), original)

    def test_refresh_mapping_is_computed_inside_serialized_region(self):
        original = os.environ.get("PATH")
        first_entered = threading.Event()
        release_first = threading.Event()
        second_refreshed = threading.Event()
        observed = []

        def first_refresher(action):
            return {"PATH": "/first"}

        def second_refresher(action):
            observed.append(("refresh", os.environ.get("PATH")))
            second_refreshed.set()
            return {"PATH": "/second"}

        def first():
            with provider_execution._refreshed_environment(
                self.plan().actions[0], first_refresher
            ):
                first_entered.set()
                release_first.wait(2)

        def second():
            first_entered.wait(2)
            with provider_execution._refreshed_environment(
                self.plan().actions[0], second_refresher
            ):
                observed.append(("applied", os.environ.get("PATH")))

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        self.assertTrue(first_entered.wait(2))
        self.assertFalse(second_refreshed.wait(0.1))
        release_first.set()
        first_thread.join(2)
        second_thread.join(2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(observed, [("refresh", original), ("applied", "/second")])
        self.assertEqual(os.environ.get("PATH"), original)

    def test_complete_provider_transactions_are_process_local_serialized(self):
        plan = self.plan()
        absent = self.state(capabilities.GHOSTSCRIPT)
        available = self.state(capabilities.GHOSTSCRIPT, available=True)
        installed = threading.Event()
        first_runner_entered = threading.Event()
        release_first = threading.Event()
        runner_calls = []
        reports = []

        def detect(capability, machine):
            return available if installed.is_set() else absent

        def run(argv, timeout):
            runner_calls.append(argv)
            first_runner_entered.set()
            release_first.wait(2)
            installed.set()
            return subprocess.CompletedProcess(argv, 0, "", "")

        def execute():
            reports.append(self.execute(plan, detector=detect, runner=run))

        first = threading.Thread(target=execute)
        second = threading.Thread(target=execute)
        first.start()
        self.assertTrue(first_runner_entered.wait(2))
        second.start()
        self.assertEqual(len(runner_calls), 1)
        release_first.set()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(runner_calls), len(plan.actions[0].commands))
        self.assertEqual(
            {report.actions[0].outcome for report in reports},
            {
                provider_execution.ActionOutcome.SUCCEEDED,
                provider_execution.ActionOutcome.ALREADY_SATISFIED,
            },
        )

    def test_translated_homebrew_requires_structured_exact_authorization(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        translated_manager = provider_plans.PackageManagerState(
            "brew",
            "/usr/local/bin/brew",
            "host",
            "x86_64",
            installation_root="/usr/local",
        )
        missing = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            machine,
            locator=lambda probe, context: None,
        )
        plan = provider_plans.generate_provider_plan(
            (missing,),
            ("ghostscript",),
            package_managers=(translated_manager,),
            translated_manager_fallbacks=(translated_manager,),
        )
        self.assertTrue(plan.actions[0].translated_manager_fallback_authorized)
        forged = replace(
            plan,
            actions=(
                replace(
                    plan.actions[0],
                    translated_manager_fallback_authorized=False,
                ),
            ),
        )
        with self.assertRaisesRegex(
            provider_execution.ExecutionContractError,
            "lacks explicit fallback authorization",
        ):
            provider_execution._execute_provider_plan_unmanaged(
                forged,
                allow_provider_mutation=True,
                current_context=lambda: machine,
            )

    def test_homebrew_architecture_is_revalidated_live_before_mutation(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        manager = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "arm64"
        )
        absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            machine,
            locator=lambda probe, context: None,
        )
        plan = provider_plans.generate_provider_plan(
            (absent,), ("ghostscript",), package_managers=(manager,)
        )
        runner = Mock(side_effect=AssertionError("must not run"))
        report = provider_execution._execute_provider_plan_unmanaged(
            plan,
            allow_provider_mutation=True,
            current_context=lambda: machine,
            manager_verifier=lambda state, context: True,
            manager_architecture_reader=lambda state: "x86_64",
            privilege_resolver=lambda action: "",
            detector=lambda capability, context: absent,
            runner=runner,
        )
        self.assertEqual(
            report.actions[0].outcome,
            provider_execution.ActionOutcome.MANAGER_UNAVAILABLE,
        )
        self.assertIn("architecture", report.actions[0].detail)
        runner.assert_not_called()

    def test_homebrew_architecture_probe_is_bounded_and_nonmutating(self):
        state = provider_plans.PackageManagerState(
            "brew",
            "/aliases/brew",
            "host",
            "arm64",
            resolved_executable_path="/opt/homebrew/bin/brew",
        )
        completed = subprocess.CompletedProcess((), 0, "arm64\n", "")
        with patch.object(subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                provider_execution._read_manager_architecture(state),
                "arm64",
            )
        self.assertEqual(
            run.call_args.args[0],
            (
                "/aliases/brew",
                "ruby",
                "-e",
                "puts Hardware::CPU.arch",
            ),
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(
            run.call_args.kwargs["env"]["HOMEBREW_NO_AUTO_UPDATE"],
            "1",
        )

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
        report = provider_execution._execute_provider_plan_unmanaged(
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
            report.actions[0].final_verified_paths,
            ("C:/Git/bin/bash.exe",),
        )
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
