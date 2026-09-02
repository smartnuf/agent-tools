import os
import signal
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities, managed_state, provider_execution, provider_plans


class _SignalOnString(provider_plans.PlanningError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._signalled = False

    def __str__(self) -> str:
        if not self._signalled:
            self._signalled = True
            signal.raise_signal(signal.SIGINT)
        return super().__str__()


class _SignalOnOSErrorString(OSError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._signalled = False

    def __str__(self) -> str:
        if not self._signalled:
            self._signalled = True
            signal.raise_signal(signal.SIGINT)
        return super().__str__()


class _ForceAbortOnString(provider_plans.PlanningError):
    def __str__(self) -> str:
        signal.raise_signal(signal.SIGINT)
        signal.raise_signal(signal.SIGINT)
        return super().__str__()


class CooperativeCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = capabilities.MachineState("Linux", "x86_64", "host")
        self.manager = provider_plans.PackageManagerState(
            "apt", "/usr/bin/apt-get", "host", "x86_64"
        )
        self.absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, machine: None,
        )
        self.plan = provider_plans.generate_provider_plan(
            (self.absent,), ("ghostscript",), package_managers=(self.manager,)
        )

    def managed_arguments(self) -> dict[str, object]:
        return {
            "allow_provider_mutation": True,
            "current_context": lambda: self.machine,
            "manager_verifier": lambda state, machine: True,
            "privilege_resolver": lambda action: "/usr/bin/sudo",
            "supervisor_resolver": lambda action: "/usr/bin/timeout",
            "privilege_preflight": lambda argv: True,
            "environment_refresher": lambda action: {},
        }

    def test_controller_records_first_request_and_force_aborts_second(self) -> None:
        cancellation = provider_execution._CancellationContext()
        first = KeyboardInterrupt()
        second = KeyboardInterrupt()

        cancellation.request(first)
        self.assertEqual(
            cancellation.phase,
            provider_execution._CancellationPhase.CANCEL_REQUESTED,
        )
        with self.assertRaises(provider_execution._ForceAbort) as raised:
            cancellation.request(second)

        self.assertIs(raised.exception.interruption, second)
        self.assertEqual(
            cancellation.phase,
            provider_execution._CancellationPhase.FORCE_ABORTED,
        )

    def test_broker_restores_default_handler_and_preserves_custom_handler(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        cancellation = provider_execution._CancellationContext()
        try:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            with provider_execution._SigintBroker(cancellation) as broker:
                self.assertTrue(broker.installed)
                signal.raise_signal(signal.SIGINT)
                self.assertEqual(
                    cancellation.phase,
                    provider_execution._CancellationPhase.CANCEL_REQUESTED,
                )
            self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)

            custom = lambda signum, frame: None
            signal.signal(signal.SIGINT, custom)
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ) as declined:
                self.assertFalse(declined.installed)
                self.assertIs(signal.getsignal(signal.SIGINT), custom)
            self.assertIs(signal.getsignal(signal.SIGINT), custom)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_broker_recognizes_sig_dfl_without_comparing_custom_handlers(self) -> None:
        class HostileCustomHandler:
            def __call__(self, signum, frame):
                del signum, frame

            def __hash__(self):
                raise AssertionError("custom handler must not be hashed")

            def __eq__(self, other):
                raise AssertionError("custom handler must not be compared")

        previous = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ) as broker:
                self.assertTrue(broker.installed)
            self.assertIs(signal.getsignal(signal.SIGINT), signal.SIG_DFL)

            custom = HostileCustomHandler()
            signal.signal(signal.SIGINT, custom)
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ) as declined:
                self.assertFalse(declined.installed)
                self.assertIs(signal.getsignal(signal.SIGINT), custom)
            self.assertIs(signal.getsignal(signal.SIGINT), custom)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_broker_declines_unhashable_custom_handler(self) -> None:
        class UnhashableCustomHandler:
            __hash__ = None

            def __call__(self, signum, frame):
                del signum, frame

        previous = signal.getsignal(signal.SIGINT)
        custom = UnhashableCustomHandler()
        try:
            signal.signal(signal.SIGINT, custom)
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ) as declined:
                self.assertFalse(declined.installed)
                self.assertIs(signal.getsignal(signal.SIGINT), custom)
            self.assertIs(signal.getsignal(signal.SIGINT), custom)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_broker_remains_uninstalled_off_main_thread(self) -> None:
        observed: list[bool] = []

        def enter_broker() -> None:
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ) as broker:
                observed.append(broker.installed)

        thread = threading.Thread(target=enter_broker)
        thread.start()
        thread.join()
        self.assertEqual(observed, [False])

    def test_broker_rejects_nested_installation(self) -> None:
        previous = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            with provider_execution._SigintBroker(
                provider_execution._CancellationContext()
            ):
                with self.assertRaisesRegex(RuntimeError, "cannot be nested"):
                    with provider_execution._SigintBroker(
                        provider_execution._CancellationContext()
                    ):
                        self.fail("nested broker must not install")
            self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_planning_error_formatting_retains_completed_command_and_persists(self) -> None:
        detector = Mock(side_effect=(self.absent, _SignalOnString("stale evidence")))
        runner = Mock(
            side_effect=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "installed", ""
            )
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=detector,
                    runner=runner,
                    **self.managed_arguments(),
                )
            document = managed_state.load_document(path)

        result = raised.exception.managed_result
        self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
        action = result.execution.actions[0]
        self.assertEqual(action.commands[0].returncode, 0)
        self.assertEqual(action.commands[0].stdout, "installed")
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.VERIFICATION_FAILED)
        self.assertEqual(document["records"][0]["command_evidence"][0]["returncode"], 0)
        self.assertEqual(runner.call_count, len(self.plan.actions[0].commands))

    def test_request_after_command_completion_stops_before_next_launch(self) -> None:
        runner = Mock()

        def complete_then_request(argv, timeout):
            signal.raise_signal(signal.SIGINT)
            return subprocess.CompletedProcess(argv, 0, "completed", "")

        runner.side_effect = complete_then_request
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=Mock(return_value=self.absent),
                    runner=runner,
                    **self.managed_arguments(),
                )

        action = raised.exception.managed_result.execution.actions[0]
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(len(action.commands), 1)
        self.assertEqual(action.commands[0].stdout, "completed")
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.INTERRUPTED)

    def test_request_during_preaction_detection_prevents_command_launch(self) -> None:
        runner = Mock(side_effect=AssertionError("provider command must not launch"))
        manager_verifier = Mock(
            side_effect=AssertionError("post-detection preflight must not run")
        )

        def request_during_detection(capability, machine):
            signal.raise_signal(signal.SIGINT)
            return self.absent

        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=request_during_detection,
                    runner=runner,
                    **{
                        **self.managed_arguments(),
                        "manager_verifier": manager_verifier,
                    },
                )

        action = raised.exception.managed_result.execution.actions[0]
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.NOT_ATTEMPTED)
        self.assertEqual(action.commands, ())
        self.assertEqual(
            raised.exception.managed_result.persistence,
            managed_state.PersistenceOutcome.NOT_REQUIRED,
        )
        runner.assert_not_called()
        manager_verifier.assert_not_called()

    def test_pending_request_before_executor_entry_prevents_injected_mutation(self) -> None:
        executor = Mock(side_effect=AssertionError("executor must not run"))
        original_timestamp = managed_state._timestamp
        signalled = False

        def request_at_timestamp():
            nonlocal signalled
            if not signalled:
                signalled = True
                signal.raise_signal(signal.SIGINT)
            return original_timestamp()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with (
                patch.object(managed_state, "_timestamp", request_at_timestamp),
                self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised,
            ):
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )

        executor.assert_not_called()
        action = raised.exception.managed_result.execution.actions[0]
        self.assertEqual(action.outcome, provider_execution.ActionOutcome.NOT_ATTEMPTED)
        self.assertEqual(
            raised.exception.managed_result.persistence,
            managed_state.PersistenceOutcome.NOT_REQUIRED,
        )

    def test_second_signal_during_formatting_force_aborts_without_persistence(self) -> None:
        detector = Mock(side_effect=(self.absent, _ForceAbortOnString("stale")))
        runner = Mock(
            side_effect=lambda argv, timeout: subprocess.CompletedProcess(
                argv, 0, "installed", ""
            )
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with self.assertRaises(provider_execution._ForceAbort):
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=detector,
                    runner=runner,
                    **self.managed_arguments(),
                )
            self.assertFalse(path.exists())

        self.assertEqual(runner.call_count, len(self.plan.actions[0].commands))

    def test_post_start_oserror_stringification_is_not_asynchronously_interrupted(self) -> None:
        cancellation = provider_execution._CancellationContext()
        process = Mock(returncode=0, stdout=Mock(), stderr=Mock())
        error = _SignalOnOSErrorString("reader failed")
        with (
            provider_execution._SigintBroker(cancellation),
            patch.object(provider_execution.subprocess, "Popen", return_value=process),
            patch.object(
                provider_execution,
                "_supervise_started_process",
                side_effect=error,
            ),
            self.assertRaises(provider_execution.CommandLifecycleError) as raised,
        ):
            provider_execution._run(("provider",), 5, _cancellation=cancellation)

        self.assertIn("reader failed", raised.exception.detail)
        self.assertEqual(raised.exception.result.args, ("provider",))
        self.assertEqual(
            cancellation.phase,
            provider_execution._CancellationPhase.CANCEL_REQUESTED,
        )
        self.assertTrue(cancellation.checkpoint())
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_environment_lifecycle_defers_first_signal_until_checkpoint(self) -> None:
        for phase in ("apply", "body", "restore"):
            with self.subTest(phase=phase):
                cancellation = provider_execution._CancellationContext()
                name = "AGENT_TOOLS_COOPERATIVE_TEST"
                original = os.environ.get(name)
                real_apply = provider_execution._apply_environment
                real_restore = provider_execution._restore_environment

                def apply(updates):
                    real_apply(updates)
                    if phase == "apply":
                        signal.raise_signal(signal.SIGINT)

                def restore(previous):
                    if phase == "restore":
                        signal.raise_signal(signal.SIGINT)
                    real_restore(previous)

                with (
                    provider_execution._SigintBroker(cancellation),
                    patch.object(provider_execution, "_apply_environment", apply),
                    patch.object(provider_execution, "_restore_environment", restore),
                ):
                    with provider_execution._temporary_environment(
                        {name: "temporary"}, cancellation
                    ):
                        self.assertEqual(os.environ[name], "temporary")
                        if phase == "body":
                            signal.raise_signal(signal.SIGINT)

                self.assertEqual(os.environ.get(name), original)
                self.assertTrue(cancellation.checkpoint())

    @unittest.skipIf(not hasattr(signal, "raise_signal"), "signal delivery unavailable")
    def test_active_process_observes_cooperative_request(self) -> None:
        cancellation = provider_execution._CancellationContext()
        timer = threading.Timer(0.15, signal.raise_signal, (signal.SIGINT,))
        timer.start()
        try:
            with (
                provider_execution._SigintBroker(cancellation),
                self.assertRaises(provider_execution.CommandInterruptedError) as raised,
            ):
                provider_execution._run(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    10,
                    _cancellation=cancellation,
                )
        finally:
            timer.cancel()
            timer.join()

        self.assertIsNotNone(raised.exception.result.returncode)
        self.assertEqual(
            cancellation.phase, provider_execution._CancellationPhase.CANCELLING
        )

    def test_active_cancellation_termination_failure_retains_launch_evidence(self) -> None:
        cancellation = provider_execution._CancellationContext()
        process = Mock(returncode=None, stdout=Mock(), stderr=Mock())

        def request_during_wait(timeout):
            signal.raise_signal(signal.SIGINT)
            raise subprocess.TimeoutExpired(("provider",), timeout)

        process.wait.side_effect = request_during_wait
        with (
            provider_execution._SigintBroker(cancellation),
            patch.object(provider_execution.subprocess, "Popen", return_value=process),
            patch.object(provider_execution, "_start_output_readers", return_value=()),
            patch.object(
                provider_execution,
                "_terminate_process_tree",
                side_effect=provider_execution.ExecutionContractError(
                    "termination unavailable"
                ),
            ),
            self.assertRaises(provider_execution.CommandInterruptedError) as raised,
        ):
            provider_execution._run(
                ("provider",), 5, _cancellation=cancellation
            )

        self.assertTrue(raised.exception.lifetime_uncertain)
        self.assertIsNone(raised.exception.result.returncode)
        self.assertIn("termination or reaping failed", raised.exception.detail)
        self.assertEqual(
            cancellation.phase, provider_execution._CancellationPhase.CANCELLING
        )

    def test_reader_join_accepts_request_before_clean_completion(self) -> None:
        cancellation = provider_execution._CancellationContext()
        stop = threading.Event()
        reader = Mock()
        reader.is_alive.return_value = True

        def request_during_join(timeout):
            signal.raise_signal(signal.SIGINT)

        reader.join.side_effect = request_during_join
        with provider_execution._SigintBroker(cancellation):
            clean = provider_execution._join_output_readers(
                (reader,), stop, [], cancellation
            )

        self.assertFalse(clean)
        self.assertTrue(stop.is_set())
        reader.join.assert_called_once()
        self.assertEqual(
            cancellation.phase, provider_execution._CancellationPhase.CANCELLING
        )

    def test_first_signal_during_atomic_write_surfaces_after_durable_result(self) -> None:
        original_dump = managed_state.json.dump
        calls = 0

        def request_then_dump(*args, **kwargs):
            nonlocal calls
            calls += 1
            signal.raise_signal(signal.SIGINT)
            return original_dump(*args, **kwargs)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with (
                patch.object(managed_state.json, "dump", request_then_dump),
                self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised,
            ):
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=Mock(side_effect=(self.absent, self.absent)),
                    runner=lambda argv, timeout: subprocess.CompletedProcess(
                        argv, 1, "", "failed"
                    ),
                    **self.managed_arguments(),
                )
            document = managed_state.load_document(path)

        self.assertEqual(calls, 1)
        self.assertEqual(
            raised.exception.managed_result.persistence,
            managed_state.PersistenceOutcome.SUCCEEDED,
        )
        self.assertEqual(len(document["records"]), 1)

    def test_first_signal_during_provenance_preparation_is_deferred(self) -> None:
        original_prepare = managed_state._prepare_update
        calls = 0

        def request_then_prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            signal.raise_signal(signal.SIGINT)
            return original_prepare(*args, **kwargs)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with (
                patch.object(
                    managed_state, "_prepare_update", request_then_prepare
                ),
                self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised,
            ):
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    detector=Mock(side_effect=(self.absent, self.absent)),
                    runner=lambda argv, timeout: subprocess.CompletedProcess(
                        argv, 1, "", "failed"
                    ),
                    **self.managed_arguments(),
                )

        self.assertEqual(calls, 1)
        self.assertEqual(
            raised.exception.managed_result.persistence,
            managed_state.PersistenceOutcome.SUCCEEDED,
        )

    def test_request_during_final_materialization_is_consumed_after_teardown(self) -> None:
        plan = provider_plans.generate_provider_plan((), (), package_managers=())
        report = provider_execution.PlanExecutionReport(
            self.machine, (), provider_execution.PlanOutcome.NO_CHANGES, ()
        )
        original_finalize = managed_state._finalize_transaction
        calls = 0

        def request_then_finalize(transaction):
            nonlocal calls
            calls += 1
            signal.raise_signal(signal.SIGINT)
            return original_finalize(transaction)

        with (
            patch.object(
                managed_state,
                "_finalize_transaction",
                request_then_finalize,
            ),
            self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised,
        ):
            managed_state.execute_provider_plan(
                plan, executor=Mock(return_value=report)
            )

        self.assertEqual(calls, 1)
        self.assertIs(raised.exception.managed_result.execution, report)
        self.assertEqual(
            raised.exception.managed_result.persistence,
            managed_state.PersistenceOutcome.NOT_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
