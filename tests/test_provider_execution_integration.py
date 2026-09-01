import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_tools import capabilities
from agent_tools import managed_state
from agent_tools import provider_execution
from agent_tools import provider_plans


class ProviderExecutionIntegrationTests(unittest.TestCase):
    """Exercise the executor against a disposable filesystem-backed host."""

    def _mock_started_process(self):
        process = mock.Mock()
        process.stdout = None
        process.stderr = None
        process.returncode = None
        return process

    def test_popen_oserror_remains_a_launch_failure(self):
        with mock.patch.object(
            provider_execution.subprocess,
            "Popen",
            side_effect=FileNotFoundError("manager disappeared"),
        ):
            with self.assertRaises(FileNotFoundError):
                provider_execution._run(("missing-manager",), 1)

    def test_wait_oserror_after_launch_preserves_reaped_process_evidence(self):
        process = self._mock_started_process()
        process.wait.side_effect = OSError("wait failed")

        def terminate(started):
            self.assertIs(started, process)
            started.returncode = -9

        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution, "_start_output_readers", return_value=()
        ), mock.patch.object(
            provider_execution, "_terminate_process_tree", side_effect=terminate
        ), mock.patch.object(
            provider_execution, "_join_output_readers", return_value=True
        ):
            with self.assertRaises(
                provider_execution.CommandLifecycleError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertFalse(raised.exception.lifetime_uncertain)
        self.assertEqual(raised.exception.result.returncode, -9)
        self.assertIn("launched", raised.exception.detail)

    def test_reader_initialization_cleanup_oserror_finishes_bounded_local_cleanup(self):
        process = self._mock_started_process()
        process.stdout = mock.Mock()
        process.stderr = mock.Mock()
        reader = mock.Mock()
        reader.is_alive.return_value = False
        initialization_error = provider_execution._OutputReaderInitializationError(
            (reader,), OSError("reader start failed")
        )
        terminate = mock.Mock(side_effect=OSError("termination failed"))
        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution,
            "_start_output_readers",
            side_effect=initialization_error,
        ), mock.patch.object(
            provider_execution, "_terminate_process_tree", terminate
        ):
            with self.assertRaises(
                provider_execution.UncertainSupervisionError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertIn("could not establish quiescence", raised.exception.detail)
        self.assertEqual(terminate.call_count, 1)
        self.assertTrue(reader.join.called)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()

    def test_reader_oserror_after_leader_exit_is_uncertain(self):
        process = self._mock_started_process()

        def start_readers(
            started, stdout_tail, stderr_tail, stop_readers, reader_errors
        ):
            reader_errors.append(OSError("pipe read failed"))
            return ()

        def complete(timeout):
            process.returncode = 0
            return 0

        process.wait.side_effect = complete
        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution,
            "_start_output_readers",
            side_effect=start_readers,
        ):
            with self.assertRaises(
                provider_execution.UncertainSupervisionError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertEqual(raised.exception.result.returncode, 0)
        self.assertIn("could not establish quiescence", raised.exception.detail)

    def test_timeout_termination_oserror_preserves_started_uncertainty(self):
        process = self._mock_started_process()
        process.wait.side_effect = subprocess.TimeoutExpired(("manager",), 1)
        terminate = mock.Mock(side_effect=OSError("kill failed"))
        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution, "_start_output_readers", return_value=()
        ), mock.patch.object(
            provider_execution,
            "_terminate_process_tree",
            terminate,
        ):
            with self.assertRaises(
                provider_execution.CommandLifecycleError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertTrue(raised.exception.lifetime_uncertain)
        self.assertTrue(raised.exception.timed_out)
        self.assertIsNone(raised.exception.result.returncode)
        self.assertEqual(terminate.call_count, 2)

    def test_interrupted_termination_oserror_preserves_started_uncertainty(self):
        process = self._mock_started_process()
        process.wait.side_effect = KeyboardInterrupt()
        terminate = mock.Mock(side_effect=OSError("reap failed"))
        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution, "_start_output_readers", return_value=()
        ), mock.patch.object(
            provider_execution,
            "_terminate_process_tree",
            terminate,
        ):
            with self.assertRaises(
                provider_execution.CommandInterruptedError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertTrue(raised.exception.lifetime_uncertain)
        self.assertIsNone(raised.exception.result.returncode)
        self.assertIn("after launch", raised.exception.detail)
        self.assertEqual(terminate.call_count, 2)

    def test_output_join_interrupt_preserves_known_process_completion(self):
        process = self._mock_started_process()

        def complete(timeout):
            process.returncode = 0
            return 0

        process.wait.side_effect = complete
        with mock.patch.object(
            provider_execution.subprocess, "Popen", return_value=process
        ), mock.patch.object(
            provider_execution, "_start_output_readers", return_value=()
        ), mock.patch.object(
            provider_execution,
            "_join_output_readers",
            side_effect=KeyboardInterrupt(),
        ):
            with self.assertRaises(
                provider_execution.CommandInterruptedError
            ) as raised:
                provider_execution._run(("manager", "install"), 1)
        self.assertTrue(raised.exception.lifetime_uncertain)
        self.assertEqual(raised.exception.result.returncode, 0)

    def test_real_subprocess_install_rediscovery_and_repeat(self):
        machine = capabilities.MachineState("Linux", "x86_64")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "gs"
            helper = root / "package_manager.py"
            helper.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "marker = Path(sys.argv[1])\n"
                "if 'install' in sys.argv[2:]:\n"
                "    marker.write_text('installed', encoding='utf-8')\n",
                encoding="utf-8",
            )

            def detect(capability, context):
                return capabilities.detect_capability(
                    capability,
                    context,
                    locator=lambda probe, current: (
                        "/tools/gs"
                        if probe.name == "gs" and marker.is_file()
                        else None
                    ),
                    version_reader=lambda probe, path: "Ghostscript 1.0",
                )

            absent = detect(capabilities.GHOSTSCRIPT, machine)
            manager = provider_plans.PackageManagerState(
                "apt", "/verified/apt-get", "host", "x86_64"
            )
            plan = provider_plans.generate_provider_plan(
                (absent,),
                ("ghostscript",),
                package_managers=(manager,),
            )
            subprocess_calls = []

            def run(reviewed_argv, timeout):
                manager_index = reviewed_argv.index("/verified/apt-get")
                actual = (
                    sys.executable,
                    str(helper),
                    str(marker),
                    *reviewed_argv[manager_index + 1 :],
                )
                subprocess_calls.append(actual)
                return subprocess.run(
                    actual,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

            arguments = {
                "allow_provider_mutation": True,
                "current_context": lambda: machine,
                "manager_verifier": lambda state, context: True,
                "privilege_resolver": lambda action: "",
                "supervisor_resolver": lambda action: "/usr/bin/timeout",
                "privilege_preflight": lambda argv: True,
                "detector": detect,
                "runner": run,
            }
            state_path = root / "managed-state.json"
            first = managed_state.execute_provider_plan(
                plan, state_path=state_path, **arguments
            )
            self.assertEqual(
                first.execution.outcome, provider_execution.PlanOutcome.SUCCEEDED
            )
            self.assertEqual(first.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            self.assertTrue(marker.is_file())
            self.assertEqual(len(subprocess_calls), 2)
            records = managed_state.load_document(state_path)["records"]
            self.assertEqual(len(records), 1)
            self.assertFalse(records[0]["ownership"])

            repeated = managed_state.execute_provider_plan(
                plan, state_path=state_path, **arguments
            )
            self.assertEqual(
                repeated.execution.outcome, provider_execution.PlanOutcome.SUCCEEDED
            )
            self.assertEqual(
                repeated.execution.actions[0].outcome,
                provider_execution.ActionOutcome.ALREADY_SATISFIED,
            )
            self.assertEqual(
                repeated.persistence, managed_state.PersistenceOutcome.NOT_REQUIRED
            )
            self.assertEqual(len(subprocess_calls), 2)
            self.assertEqual(len(managed_state.load_document(state_path)["records"]), 1)

    def test_timeout_terminates_descendant_process_before_returning(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "orphaned-child"
            parent = root / "parent.py"
            parent.write_text(
                "import subprocess\n"
                "import sys\n"
                "import time\n"
                "child = \"import pathlib, sys, time; time.sleep(1); \"\n"
                "child += \"pathlib.Path(sys.argv[1]).write_text('orphan')\"\n"
                "subprocess.Popen([sys.executable, '-c', child, sys.argv[1]])\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )

            with self.assertRaises(subprocess.TimeoutExpired):
                provider_execution._run(
                    (sys.executable, str(parent), str(marker)),
                    0.2,
                )
            time.sleep(1.2)
            self.assertFalse(marker.exists())

    def test_runner_drains_output_while_retaining_only_bounded_tails(self):
        size = provider_execution.MAX_CAPTURED_OUTPUT_CHARS + 200_000
        code = (
            "import sys;"
            f"sys.stdout.write('o'*{size});"
            f"sys.stderr.write('e'*{size})"
        )
        result = provider_execution._run((sys.executable, "-c", code), 10)
        prefix = "[earlier output truncated]\n"
        self.assertTrue(result.stdout.startswith(prefix))
        self.assertTrue(result.stderr.startswith(prefix))
        self.assertLessEqual(
            len(result.stdout),
            len(prefix) + provider_execution.MAX_CAPTURED_OUTPUT_CHARS,
        )
        self.assertLessEqual(
            len(result.stderr),
            len(prefix) + provider_execution.MAX_CAPTURED_OUTPUT_CHARS,
        )
        self.assertTrue(result.stdout.endswith("o" * 100))
        self.assertTrue(result.stderr.endswith("e" * 100))

    def test_runner_bounds_retained_pipe_as_uncertain_external_state(self):
        code = (
            "import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(1)'])"
        )
        with mock.patch.object(
            provider_execution, "OUTPUT_PIPE_CLOSURE_GUARD_SECONDS", 0.1
        ):
            started = time.monotonic()
            with self.assertRaises(
                provider_execution.UncertainSupervisionError
            ) as raised:
                provider_execution._run((sys.executable, "-c", code), 5)
        self.assertEqual(raised.exception.result.returncode, 0)
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(
            any(
                thread.is_alive() and thread.name.startswith("provider-output-")
                for thread in threading.enumerate()
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX disposable process fixture")
    def test_reader_start_failures_terminate_process_and_leave_no_reader(self):
        for failed_start in (1, 2):
            with self.subTest(failed_start=failed_start):
                created = []
                real_popen = subprocess.Popen
                real_start = threading.Thread.start
                starts = 0

                def record_process(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    created.append(process)
                    return process

                def start_or_fail(thread):
                    nonlocal starts
                    starts += 1
                    if starts == failed_start:
                        raise RuntimeError("injected reader start failure")
                    return real_start(thread)

                with mock.patch.object(
                    provider_execution.subprocess, "Popen", side_effect=record_process
                ), mock.patch.object(
                    provider_execution.threading.Thread,
                    "start",
                    autospec=True,
                    side_effect=start_or_fail,
                ):
                    with self.assertRaises(
                        provider_execution.CommandLifecycleError
                    ) as raised:
                        provider_execution._run(
                            (sys.executable, "-c", "import time;time.sleep(30)"),
                            10,
                        )
                self.assertEqual(len(created), 1)
                self.assertIsNotNone(created[0].poll())
                self.assertIsNotNone(raised.exception.result.returncode)
                self.assertIn("may have started", raised.exception.detail)
                self.assertFalse(
                    any(
                        thread.is_alive()
                        and thread.name.startswith("provider-output-")
                        for thread in threading.enumerate()
                    )
                )

    @unittest.skipIf(os.name == "nt", "POSIX disposable process fixture")
    def test_second_reader_construction_failure_cleans_started_reader_and_process(self):
        real_thread = threading.Thread
        constructions = 0

        def construct_or_fail(*args, **kwargs):
            nonlocal constructions
            constructions += 1
            if constructions == 2:
                raise RuntimeError("injected reader construction failure")
            return real_thread(*args, **kwargs)

        with mock.patch.object(
            provider_execution.threading,
            "Thread",
            side_effect=construct_or_fail,
        ):
            with self.assertRaises(provider_execution.CommandLifecycleError):
                provider_execution._run(
                    (sys.executable, "-c", "import time;time.sleep(30)"),
                    10,
                )
        self.assertFalse(
            any(
                thread.is_alive() and thread.name.startswith("provider-output-")
                for thread in threading.enumerate()
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX disposable supervisor fixture")
    def test_reader_start_failure_uses_privileged_supervisor_cleanup(self):
        real_start = threading.Thread.start
        starts = 0

        def fail_second(thread):
            nonlocal starts
            starts += 1
            if starts == 2:
                raise RuntimeError("injected reader start failure")
            return real_start(thread)

        with mock.patch.object(
            provider_execution.threading.Thread,
            "start",
            autospec=True,
            side_effect=fail_second,
        ), mock.patch.object(
            provider_execution,
            "_terminate_privileged_supervisor",
            side_effect=provider_execution._terminate_process_tree,
        ) as terminate:
            with self.assertRaises(provider_execution.CommandLifecycleError):
                provider_execution._run(
                    (sys.executable, "-c", "import time;time.sleep(30)"),
                    10,
                    privileged_supervision=True,
                )
        terminate.assert_called_once()
        self.assertFalse(
            any(
                thread.is_alive() and thread.name.startswith("provider-output-")
                for thread in threading.enumerate()
            )
        )

    @unittest.skipIf(os.name == "nt", "POSIX disposable supervisor fixture")
    def test_reader_start_and_termination_failure_is_uncertain(self):
        def terminate_then_fail(process):
            provider_execution._terminate_process_tree(process)
            raise provider_execution.ExecutionContractError(
                "termination could not be established"
            )

        with mock.patch.object(
            provider_execution.threading.Thread,
            "start",
            autospec=True,
            side_effect=RuntimeError("injected reader start failure"),
        ), mock.patch.object(
            provider_execution,
            "_terminate_privileged_supervisor",
            side_effect=terminate_then_fail,
        ):
            with self.assertRaises(
                provider_execution.UncertainSupervisionError
            ) as raised:
                provider_execution._run(
                    (sys.executable, "-c", "import time;time.sleep(30)"),
                    10,
                    privileged_supervision=True,
                )
        self.assertIn("could not establish quiescence", raised.exception.detail)
        self.assertIsNotNone(raised.exception.result.returncode)

    @unittest.skipIf(os.name == "nt", "POSIX safe cleanup fixture")
    def test_failed_privileged_supervisor_termination_becomes_uncertain(self):
        def terminate_then_fail(process):
            provider_execution._terminate_process_tree(process)
            raise provider_execution.ExecutionContractError(
                "privileged supervisor termination could not be established"
            )

        with mock.patch.object(
            provider_execution,
            "_terminate_privileged_supervisor",
            side_effect=terminate_then_fail,
        ):
            with self.assertRaises(
                provider_execution.UncertainSupervisionError
            ) as raised:
                provider_execution._run(
                    (sys.executable, "-c", "import time;time.sleep(30)"),
                    0.1,
                    privileged_supervision=True,
                )
        self.assertIn("termination could not be established", raised.exception.detail)
        self.assertIsNotNone(raised.exception.result.returncode)

    @unittest.skipIf(os.name == "nt", "POSIX signal fixture")
    def test_interrupt_terminates_descendant_process_before_propagating(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "orphaned-after-interrupt"
            code = (
                "import signal,sys;"
                "from agent_tools import provider_execution;"
                "child=\"import pathlib,sys,time;time.sleep(1);\";"
                "child+=\"pathlib.Path(sys.argv[1]).write_text('orphan')\";"
                "parent=\"import subprocess,sys,time;\";"
                "parent+=\"subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);\";"
                "parent+=\"time.sleep(30)\";"
                "\ntry: provider_execution._run((sys.executable,'-c',parent,child,sys.argv[1]),30)"
                "\nexcept KeyboardInterrupt: pass"
            )
            process = subprocess.Popen(
                (sys.executable, "-c", code, str(marker)),
                env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
            )
            time.sleep(0.4)
            process.send_signal(signal.SIGINT)
            process.wait(timeout=3)
            time.sleep(1.1)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(shutil.which("timeout"), "GNU timeout is unavailable")
    def test_gnu_timeout_kills_term_resistant_descendant_group(self):
        timeout = provider_execution._resolve_supervisor(
            provider_plans.generate_provider_plan(
                (
                    capabilities.detect_capability(
                        capabilities.GHOSTSCRIPT,
                        capabilities.MachineState("Linux", "x86_64"),
                        locator=lambda probe, machine: None,
                    ),
                ),
                ("ghostscript",),
                package_managers=(
                    provider_plans.PackageManagerState(
                        "apt", "/usr/bin/apt-get", "host", "x86_64"
                    ),
                ),
            ).actions[0]
        )
        if not timeout:
            self.skipTest("available timeout is not verified GNU Coreutils")
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "survivor"
            child = (
                "import pathlib,signal,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "time.sleep(1);pathlib.Path(sys.argv[1]).write_text('alive')"
            )
            parent = (
                "import signal,subprocess,sys,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);"
                "time.sleep(30)"
            )
            result = provider_execution._run(
                (
                    timeout,
                    "--signal=TERM",
                    "--kill-after=0.2s",
                    "0.2s",
                    sys.executable,
                    "-c",
                    parent,
                    child,
                    str(marker),
                ),
                2,
            )
            self.assertIn(result.returncode, {137, -9})
            time.sleep(1.1)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
