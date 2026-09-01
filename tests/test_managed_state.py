import json
import subprocess
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities, managed_state, provider_execution, provider_plans


class _InterruptOnExit:
    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        raise KeyboardInterrupt()


class ManagedStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = capabilities.MachineState("Linux", "x86_64", "host")
        manager = provider_plans.PackageManagerState(
            "apt", "/usr/bin/apt-get", "host", "x86_64"
        )
        absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, machine: None,
        )
        self.plan = provider_plans.generate_provider_plan(
            (absent,), ("ghostscript",), package_managers=(manager,)
        )

    def report(
        self,
        outcome: provider_execution.ActionOutcome = provider_execution.ActionOutcome.SUCCEEDED,
        *,
        commands: bool = True,
    ) -> provider_execution.PlanExecutionReport:
        action = self.plan.actions[0]
        returncode = {
            provider_execution.ActionOutcome.COMMAND_FAILED: 1,
            provider_execution.ActionOutcome.COMMAND_START_FAILED: None,
            provider_execution.ActionOutcome.TIMED_OUT: None,
            provider_execution.ActionOutcome.FORCED_KILL: 137,
        }.get(outcome, 0)
        reported_commands = (
            action.commands[:1]
            if outcome
            in {
                provider_execution.ActionOutcome.COMMAND_FAILED,
                provider_execution.ActionOutcome.COMMAND_START_FAILED,
                provider_execution.ActionOutcome.TIMED_OUT,
                provider_execution.ActionOutcome.FORCED_KILL,
                provider_execution.ActionOutcome.SUPERVISOR_FAILED,
            }
            else action.commands
        )
        command_reports = (
            tuple(
                provider_execution.CommandReport(
                    (
                        "/usr/bin/timeout",
                        "--signal=TERM",
                        "--kill-after=5s",
                        "900s",
                        *command,
                    ),
                    returncode,
                    "installed",
                    "",
                    outcome is provider_execution.ActionOutcome.TIMED_OUT,
                )
                for command in reported_commands
            )
            if commands
            else ()
        )
        final_verified_paths = (
            ("/tools/gs",)
            if outcome is provider_execution.ActionOutcome.SUCCEEDED
            else ()
        )
        return provider_execution.PlanExecutionReport(
            self.machine,
            self.plan.requested_capabilities,
            provider_execution.PlanOutcome.SUCCEEDED,
            (
                provider_execution.ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    outcome,
                    command_reports,
                    final_verified_paths,
                    "verified",
                ),
            ),
        )

    def test_platform_paths_are_separate_and_internal(self) -> None:
        home = Path("/users/test")
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Windows",
                environment={"LOCALAPPDATA": r"C:\Users\test\AppData\Local"},
                home=home,
            ),
            Path(r"C:\Users\test\AppData\Local") / "agent-tools" / "managed-state.json",
        )
        for invalid in ("relative", r"C:relative"):
            with self.subTest(local_app_data=invalid):
                with self.assertRaisesRegex(
                    managed_state.ManagedStateError, "absolute Windows path"
                ):
                    managed_state.managed_state_path(
                        platform_name="Windows",
                        environment={"LOCALAPPDATA": invalid},
                        home=home,
                    )
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Linux", environment={"XDG_STATE_HOME": "/state"}, home=home
            ),
            Path("/state/agent-tools/managed-state.json"),
        )
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Linux", environment={}, home=home
            ),
            home / ".local/state/agent-tools/managed-state.json",
        )
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Linux",
                environment={"XDG_STATE_HOME": "relative-state"},
                home=home,
            ),
            home / ".local/state/agent-tools/managed-state.json",
        )
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Darwin", environment={}, home=home
            ),
            home / "Library/Application Support/agent-tools/managed-state.json",
        )

    def test_home_is_resolved_only_when_the_selected_root_needs_it(self) -> None:
        with patch.object(Path, "home", side_effect=RuntimeError("no home")) as resolve:
            self.assertEqual(
                managed_state.managed_state_path(
                    platform_name="Windows",
                    environment={"LOCALAPPDATA": r"C:\Users\svc\AppData\Local"},
                ),
                Path(r"C:\Users\svc\AppData\Local")
                / "agent-tools"
                / "managed-state.json",
            )
            self.assertEqual(
                managed_state.managed_state_path(
                    platform_name="Linux",
                    environment={"XDG_STATE_HOME": "/state"},
                ),
                Path("/state/agent-tools/managed-state.json"),
            )
            resolve.assert_not_called()
        with patch.object(Path, "home", side_effect=RuntimeError("no home")):
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "home directory is unavailable"
            ):
                managed_state.managed_state_path(
                    platform_name="Linux", environment={}
                )
        with self.assertRaisesRegex(
            managed_state.ManagedStateError, "home directory is not absolute"
        ):
            managed_state.managed_state_path(
                platform_name="Darwin", environment={}, home=Path("relative")
            )
        self.assertEqual(
            managed_state.managed_state_path(
                platform_name="Linux",
                environment={},
                home=Path("/posix/home"),
            ),
            Path("/posix/home/.local/state/agent-tools/managed-state.json"),
        )

    def test_canonical_empty_plan_needs_no_context_or_persistence(self) -> None:
        plan = provider_plans.generate_provider_plan((), (), package_managers=())
        execution = provider_execution.PlanExecutionReport(
            self.machine, (), provider_execution.PlanOutcome.NO_CHANGES, ()
        )
        executor = Mock(return_value=execution)
        result = managed_state.execute_provider_plan(plan, executor=executor)
        self.assertIs(result.execution, execution)
        self.assertEqual(result.persistence, managed_state.PersistenceOutcome.NOT_REQUIRED)
        executor.assert_called_once_with(plan)

    def test_unauthorized_plan_is_refused_without_state_access(self) -> None:
        with patch.object(
            managed_state,
            "managed_state_path",
            side_effect=AssertionError("must not resolve persistence path"),
        ) as path:
            result = managed_state.execute_provider_plan(
                self.plan,
                current_context=lambda: self.machine,
            )
        self.assertEqual(
            result.execution.outcome, provider_execution.PlanOutcome.REFUSED
        )
        self.assertEqual(result.persistence, managed_state.PersistenceOutcome.NOT_REQUIRED)
        path.assert_not_called()

    def test_truthy_non_boolean_does_not_authorize_mutation(self) -> None:
        result = managed_state.execute_provider_plan(
            self.plan,
            allow_provider_mutation="false",
            current_context=lambda: self.machine,
        )
        self.assertEqual(
            result.execution.outcome, provider_execution.PlanOutcome.REFUSED
        )
        self.assertEqual(result.persistence, managed_state.PersistenceOutcome.NOT_REQUIRED)

    def test_absent_document_is_empty_and_unknown_or_corrupt_state_fails(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertEqual(managed_state.load_document(path), managed_state.empty_document())
            path.write_text('{"schema_version": 2, "records": []}', encoding="utf-8")
            with self.assertRaisesRegex(managed_state.ManagedStateError, "unsupported"):
                managed_state.load_document(path)
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(managed_state.ManagedStateError, "corrupt"):
                managed_state.load_document(path)

    def test_schema_version_requires_an_exact_integer(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for version in (True, 1.0):
                with self.subTest(version=version):
                    path.write_text(
                        json.dumps({"schema_version": version, "records": []}),
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "unsupported"
                    ):
                        managed_state.load_document(path)

    def test_inaccessible_document_is_not_treated_as_absent(self) -> None:
        path = Path("/inaccessible/managed-state.json")
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(managed_state.ManagedStateError, "denied"):
                managed_state.load_document(path)

    def test_malformed_v1_record_is_rejected_without_speculative_migration(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps({"schema_version": 1, "records": [{"id": "not-enough"}]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(managed_state.ManagedStateError, "schema v1"):
                managed_state.load_document(path)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                '{"schema_version":1,"records":[],"records":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(managed_state.ManagedStateError, "duplicate"):
                managed_state.load_document(path)

    def test_semantically_duplicate_uuid_ids_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            duplicate = json.loads(json.dumps(document["records"][0]))
            duplicate["id"] = "{" + duplicate["id"].upper() + "}"
            document["records"].append(duplicate)
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(managed_state.ManagedStateError, "duplicate id"):
                managed_state.load_document(path)

    def test_container_discriminators_are_managed_schema_errors(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            for field, value in (
                (("requested_action", "kind"), []),
                (("verification", "outcome"), {}),
            ):
                with self.subTest(field=field):
                    document = managed_state.load_document(path)
                    document["records"][0][field[0]][field[1]] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(managed_state.ManagedStateError):
                        managed_state.load_document(path)
                    document["records"][0][field[0]][field[1]] = (
                        "install" if field[0] == "requested_action" else "succeeded"
                    )
                    path.write_text(json.dumps(document), encoding="utf-8")

    def test_command_return_code_requires_explicit_null_or_exact_integer(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            for returncode in (True, 1.0, "1", object()):
                with self.subTest(returncode=returncode):
                    document = managed_state.load_document(path)
                    evidence = document["records"][0]["command_evidence"][0]
                    if type(returncode) is object:
                        del evidence["returncode"]
                    else:
                        evidence["returncode"] = returncode
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "command"
                    ):
                        managed_state.load_document(path)
                    evidence["returncode"] = 0
                    path.write_text(json.dumps(document), encoding="utf-8")

    def test_completed_outcome_requires_command_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["command_evidence"] = []
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "command evidence"
            ):
                managed_state.load_document(path)

    def test_requested_commands_must_match_reviewed_adapter(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["requested_action"]["commands"] = [
                ["/bin/sh", "-c", "unreviewed"]
            ]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(managed_state.ManagedStateError, "unreviewed"):
                managed_state.load_document(path)

            with patch.object(
                managed_state,
                "adapter_commands",
                side_effect=provider_plans.PlanningError("unsupported target"),
            ):
                with self.assertRaisesRegex(
                    managed_state.ManagedStateError, "adapter semantics"
                ):
                    managed_state.load_document(path)

    def test_recorded_manager_and_success_paths_are_platform_absolute(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            for fields, value, message in (
                (("package_manager", "executable"), "apt-get", "package-manager"),
                (
                    ("verification", "verified_paths"),
                    ["relative/gs"],
                    "verification evidence",
                ),
            ):
                with self.subTest(fields=fields):
                    document = json.loads(json.dumps(original))
                    document["records"][0][fields[0]][fields[1]] = value
                    if fields[0] == "package_manager":
                        document["records"][0]["requested_action"]["commands"] = [
                            list(command)
                            for command in provider_plans.adapter_commands(
                                "apt", "ghostscript", executable_path=value
                            )
                        ]
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(managed_state.ManagedStateError, message):
                        managed_state.load_document(path)

    def test_command_evidence_must_match_reviewed_or_authorized_wrapper(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            for argv in (
                [],
                ["/bin/sh", "-c", "unreviewed"],
                [
                    "/usr/bin/sudo", "--", "/usr/bin/timeout",
                    "--signal=TERM", "--kill-after=5s", "900s",
                    *self.plan.actions[0].commands[0],
                ],
                [
                    "/usr/bin/timeout", "--foreground", "--kill-after=5s", "900s",
                    *self.plan.actions[0].commands[0],
                ],
            ):
                with self.subTest(argv=argv):
                    document = json.loads(json.dumps(original))
                    document["records"][0]["command_evidence"][0]["argv"] = argv
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "command evidence"
                    ):
                        managed_state.load_document(path)
            document = json.loads(json.dumps(original))
            for evidence in document["records"][0]["command_evidence"]:
                evidence["argv"] = [
                    "/usr/bin/sudo",
                    "-n",
                    "--",
                    *evidence["argv"],
                ]
            path.write_text(json.dumps(document), encoding="utf-8")
            managed_state.load_document(path)

            document["records"][0]["command_evidence"][1]["argv"] = original[
                "records"
            ][0]["command_evidence"][1]["argv"]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "supervisor evidence"
            ):
                managed_state.load_document(path)

    def test_only_writer_reachable_attempt_outcomes_are_accepted(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            for outcome in (
                "not-attempted",
                "already-satisfied",
                "refused",
                "manager-unavailable",
                "privilege-unavailable",
                "preflight-failed",
            ):
                with self.subTest(outcome=outcome):
                    document = json.loads(json.dumps(original))
                    document["records"][0]["verification"]["outcome"] = outcome
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "verification evidence"
                    ):
                        managed_state.load_document(path)

    def test_preceding_command_evidence_must_show_success(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            record = document["records"][0]
            record["verification"]["outcome"] = "command-failed"
            record["command_evidence"][0]["returncode"] = 1
            record["command_evidence"][1]["returncode"] = 1
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "preceding command evidence"
            ):
                managed_state.load_document(path)

            record["command_evidence"][0]["returncode"] = 0
            record["verification"]["verified_paths"] = []
            path.write_text(json.dumps(document), encoding="utf-8")
            managed_state.load_document(path)

    def test_command_start_failure_keeps_post_popen_cleanup_status(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            report = self.report()
            action = replace(
                report.actions[0],
                outcome=provider_execution.ActionOutcome.COMMAND_START_FAILED,
                final_verified_paths=(),
            )
            report = replace(
                report,
                outcome=provider_execution.PlanOutcome.PARTIAL_FAILURE,
                actions=(action,),
            )
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(
                record["verification"]["outcome"], "command-start-failed"
            )
            self.assertTrue(
                all(
                    evidence["returncode"] == 0
                    for evidence in record["command_evidence"]
                )
            )

    def test_preverification_outcomes_cannot_claim_verified_paths(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            report = self.report(provider_execution.ActionOutcome.COMMAND_FAILED)
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["verification"]["verified_paths"] = [
                "/tools/gs"
            ]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "pre-verification paths"
            ):
                managed_state.load_document(path)

    def test_timeout_requires_null_returncode(self) -> None:
        machine = capabilities.MachineState("Darwin", "arm64", "host")
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
        action = plan.actions[0]
        report = provider_execution.PlanExecutionReport(
            machine,
            plan.requested_capabilities,
            provider_execution.PlanOutcome.PARTIAL_FAILURE,
            (
                provider_execution.ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    provider_execution.ActionOutcome.TIMED_OUT,
                    (
                        provider_execution.CommandReport(
                            action.commands[0], None, "partial output", "", True
                        ),
                    ),
                    detail="command timed out",
                ),
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["command_evidence"][-1]["returncode"] = 0
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "terminal command evidence"
            ):
                managed_state.load_document(path)

    def test_interrupted_command_evidence_cannot_claim_timeout(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.INTERRUPTED
                    )
                ),
                allow_provider_mutation=True,
            )
            for field, value in (("timed_out", True), ("returncode", None)):
                with self.subTest(field=field):
                    document = managed_state.load_document(path)
                    document["records"][0]["command_evidence"][-1][field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "terminal command evidence",
                    ):
                        managed_state.load_document(path)
                    path.unlink()
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(
                            return_value=self.report(
                                provider_execution.ActionOutcome.INTERRUPTED
                            )
                        ),
                        allow_provider_mutation=True,
                    )

    def test_supervised_command_failure_rejects_reserved_wrapper_statuses(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.COMMAND_FAILED
                    )
                ),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            root_argv = original["records"][0]["command_evidence"][-1]["argv"]
            wrapper_forms = (
                root_argv,
                ["/usr/bin/sudo", "-n", "--", *root_argv],
            )
            for wrapper_argv in wrapper_forms:
                for returncode in (125, 126, 127, 137, -9):
                    with self.subTest(
                        prefix_length=(
                            len(wrapper_argv)
                            - len(self.plan.actions[0].commands[0])
                        ),
                        returncode=returncode,
                    ):
                        document = json.loads(json.dumps(original))
                        terminal = document["records"][0]["command_evidence"][-1]
                        terminal["argv"] = wrapper_argv
                        terminal["returncode"] = returncode
                        path.write_text(json.dumps(document), encoding="utf-8")
                        with self.assertRaisesRegex(
                            managed_state.ManagedStateError,
                            "terminal command evidence",
                        ):
                            managed_state.load_document(path)

            document = json.loads(json.dumps(original))
            document["records"][0]["command_evidence"][-1]["returncode"] = 124
            path.write_text(json.dumps(document), encoding="utf-8")
            managed_state.load_document(path)

    def test_supervised_execution_cannot_persist_unsupervised_timeout(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.COMMAND_FAILED
                    )
                ),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            root_argv = original["records"][0]["command_evidence"][-1]["argv"]
            for wrapper_argv in (
                root_argv,
                ["/usr/bin/sudo", "-n", "--", *root_argv],
            ):
                with self.subTest(wrapper_argv=wrapper_argv[:4]):
                    document = json.loads(json.dumps(original))
                    record = document["records"][0]
                    record["verification"]["outcome"] = "timed-out"
                    terminal = record["command_evidence"][-1]
                    terminal["argv"] = wrapper_argv
                    terminal["returncode"] = None
                    terminal["timed_out"] = True
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "terminal command evidence",
                    ):
                        managed_state.load_document(path)

    def test_current_user_command_failure_can_preserve_reserved_numeric_status(self) -> None:
        machine = capabilities.MachineState("Darwin", "arm64", "host")
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
        action = plan.actions[0]
        report = provider_execution.PlanExecutionReport(
            machine,
            plan.requested_capabilities,
            provider_execution.PlanOutcome.PARTIAL_FAILURE,
            (
                provider_execution.ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    provider_execution.ActionOutcome.COMMAND_FAILED,
                    (
                        provider_execution.CommandReport(
                            action.commands[0], 125, "manager output", ""
                        ),
                    ),
                    detail="command exited with status 125",
                ),
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["command_evidence"][0]["returncode"], 125)

    def test_forced_kill_is_limited_to_supervised_linux_execution(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.FORCED_KILL
                    )
                ),
                allow_provider_mutation=True,
            )
            supervised = managed_state.load_document(path)
            root_argv = supervised["records"][0]["command_evidence"][0]["argv"]
            for wrapper_argv in (
                root_argv,
                ["/usr/bin/sudo", "-n", "--", *root_argv],
            ):
                for returncode in (137, -9):
                    with self.subTest(
                        wrapper_length=len(wrapper_argv), returncode=returncode
                    ):
                        candidate = json.loads(json.dumps(supervised))
                        terminal = candidate["records"][0]["command_evidence"][0]
                        terminal["argv"] = wrapper_argv
                        terminal["returncode"] = returncode
                        path.write_text(json.dumps(candidate), encoding="utf-8")
                        managed_state.load_document(path)

            machine = capabilities.MachineState("Darwin", "arm64", "host")
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
            action = plan.actions[0]
            for returncode in (137, -9):
                with self.subTest(current_user_returncode=returncode):
                    report = provider_execution.PlanExecutionReport(
                        machine,
                        plan.requested_capabilities,
                        provider_execution.PlanOutcome.PARTIAL_FAILURE,
                        (
                            provider_execution.ActionReport(
                                action.capability_id,
                                action.provider_id,
                                action.manager,
                                action.installation_unit,
                                provider_execution.ActionOutcome.COMMAND_FAILED,
                                (
                                    provider_execution.CommandReport(
                                        action.commands[0], returncode, "output", ""
                                    ),
                                ),
                            ),
                        ),
                    )
                    path.unlink(missing_ok=True)
                    managed_state.execute_provider_plan(
                        plan,
                        state_path=path,
                        executor=Mock(return_value=report),
                        allow_provider_mutation=True,
                    )
                    current_user = managed_state.load_document(path)
                    current_user["records"][0]["verification"]["outcome"] = (
                        "forced-kill"
                    )
                    path.write_text(json.dumps(current_user), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "terminal command evidence",
                    ):
                        managed_state.load_document(path)
            current_user["records"][0]["verification"]["outcome"] = (
                "supervisor-failed"
            )
            terminal = current_user["records"][0]["command_evidence"][-1]
            terminal["returncode"] = None
            terminal["timed_out"] = True
            path.write_text(json.dumps(current_user), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "terminal command evidence"
            ):
                managed_state.load_document(path)

    def test_terminal_timeout_relationships_match_writer_outcomes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            for outcome in (
                provider_execution.ActionOutcome.COMMAND_START_FAILED,
                provider_execution.ActionOutcome.SUPERVISOR_FAILED,
            ):
                with self.subTest(outcome=outcome.value):
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report(outcome)),
                        allow_provider_mutation=True,
                    )
                    document = managed_state.load_document(path)
                    terminal = document["records"][0]["command_evidence"][-1]
                    terminal["timed_out"] = True
                    terminal["returncode"] = None
                    path.write_text(json.dumps(document), encoding="utf-8")
                    if outcome is provider_execution.ActionOutcome.SUPERVISOR_FAILED:
                        managed_state.load_document(path)
                    else:
                        with self.assertRaisesRegex(
                            managed_state.ManagedStateError,
                            "terminal command evidence",
                        ):
                            managed_state.load_document(path)
                    path.unlink()

    def test_command_output_bounds_apply_before_write_and_on_load(self) -> None:
        oversized = "z" * (provider_execution.MAX_CAPTURED_OUTPUT_CHARS + 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            absent = capabilities.detect_capability(
                capabilities.GHOSTSCRIPT,
                self.machine,
                locator=lambda probe, context: None,
            )
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                allow_provider_mutation=True,
                current_context=lambda: self.machine,
                detector=lambda capability, context: absent,
                manager_verifier=lambda state, context: True,
                privilege_resolver=lambda action: "/usr/bin/sudo",
                supervisor_resolver=lambda action: "/usr/bin/timeout",
                privilege_preflight=lambda argv: True,
                runner=lambda argv, timeout: subprocess.CompletedProcess(
                    argv, 1, oversized, oversized
                ),
            )
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.SUCCEEDED
            )
            document = managed_state.load_document(path)
            terminal = document["records"][0]["command_evidence"][-1]
            for stream in ("stdout", "stderr"):
                self.assertEqual(
                    len(terminal[stream]),
                    provider_execution.MAX_CAPTURED_OUTPUT_CHARS
                    + len(provider_execution.OUTPUT_TRUNCATION_MARKER),
                )
                self.assertTrue(
                    terminal[stream].startswith(
                        provider_execution.OUTPUT_TRUNCATION_MARKER
                    )
                )

            exact_limit = json.loads(json.dumps(document))
            exact_limit["records"][0]["command_evidence"][-1]["stdout"] = (
                "x" * provider_execution.MAX_CAPTURED_OUTPUT_CHARS
            )
            path.write_text(json.dumps(exact_limit), encoding="utf-8")
            managed_state.load_document(path)

            for value in (
                oversized,
                provider_execution.OUTPUT_TRUNCATION_MARKER + oversized,
            ):
                with self.subTest(length=len(value)):
                    damaged = json.loads(json.dumps(document))
                    damaged["records"][0]["command_evidence"][-1][
                        "stdout"
                    ] = value
                    path.write_text(json.dumps(damaged), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "command evidence",
                    ):
                        managed_state.load_document(path)

            overlarge_report = self.report()
            overlarge_action = replace(
                overlarge_report.actions[0],
                commands=(
                    replace(overlarge_report.actions[0].commands[0], stdout=oversized),
                    *overlarge_report.actions[0].commands[1:],
                ),
            )
            path.unlink()
            blocked_write = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=replace(
                        overlarge_report, actions=(overlarge_action,)
                    )
                ),
                allow_provider_mutation=True,
            )
            self.assertEqual(
                blocked_write.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertFalse(path.exists())

    def test_all_probe_success_requires_complete_verified_paths(self) -> None:
        missing = capabilities.detect_capability(
            capabilities.POPPLER,
            self.machine,
            locator=lambda probe, context: None,
        )
        plan = provider_plans.generate_provider_plan(
            (missing,),
            ("poppler",),
            package_managers=(self.plan.actions[0].manager_state,),
        )
        action = plan.actions[0]
        commands = tuple(
            provider_execution.CommandReport(
                (
                    "/usr/bin/timeout",
                    "--signal=TERM",
                    "--kill-after=5s",
                    "900s",
                    *command,
                ),
                0,
                "installed",
                "",
            )
            for command in action.commands
        )
        report = provider_execution.PlanExecutionReport(
            self.machine,
            plan.requested_capabilities,
            provider_execution.PlanOutcome.SUCCEEDED,
            (
                provider_execution.ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    provider_execution.ActionOutcome.SUCCEEDED,
                    commands,
                    (
                        "/tools/pdfinfo",
                        "/tools/pdftotext",
                        "/tools/pdftoppm",
                    ),
                    "verified",
                ),
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["verification"]["verified_paths"] = [
                "/tools/pdfinfo"
            ]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "success evidence"
            ):
                managed_state.load_document(path)

    def test_verification_failure_paths_cannot_exceed_provider_probes(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.VERIFICATION_FAILED
                    )
                ),
                allow_provider_mutation=True,
            )
            document = managed_state.load_document(path)
            document["records"][0]["verification"]["verified_paths"] = [
                "/tools/one",
                "/tools/two",
                "/tools/three",
                "/tools/four",
            ]
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError, "verification evidence"
            ):
                managed_state.load_document(path)

    def test_verification_failure_paths_preserve_probe_policy_semantics(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            any_document = managed_state.load_document(path)
            any_document["records"][0]["verification"]["outcome"] = (
                "verification-failed"
            )
            path.write_text(json.dumps(any_document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError,
                "verification-failure evidence",
            ):
                managed_state.load_document(path)

            missing = capabilities.detect_capability(
                capabilities.POPPLER,
                self.machine,
                locator=lambda probe, context: None,
            )
            all_plan = provider_plans.generate_provider_plan(
                (missing,),
                ("poppler",),
                package_managers=(self.plan.actions[0].manager_state,),
            )
            all_action = all_plan.actions[0]
            all_commands = tuple(
                provider_execution.CommandReport(
                    (
                        "/usr/bin/timeout",
                        "--signal=TERM",
                        "--kill-after=5s",
                        "900s",
                        *command,
                    ),
                    0,
                    "installed",
                    "",
                )
                for command in all_action.commands
            )
            all_report = provider_execution.PlanExecutionReport(
                self.machine,
                all_plan.requested_capabilities,
                provider_execution.PlanOutcome.SUCCEEDED,
                (
                    provider_execution.ActionReport(
                        all_action.capability_id,
                        all_action.provider_id,
                        all_action.manager,
                        all_action.installation_unit,
                        provider_execution.ActionOutcome.SUCCEEDED,
                        all_commands,
                        ("/tools/pdfinfo", "/tools/pdftotext", "/tools/pdftoppm"),
                    ),
                ),
            )
            path.unlink()
            managed_state.execute_provider_plan(
                all_plan,
                state_path=path,
                executor=Mock(return_value=all_report),
                allow_provider_mutation=True,
            )
            all_document = managed_state.load_document(path)
            all_record = all_document["records"][0]
            all_record["verification"]["outcome"] = "verification-failed"
            path.write_text(json.dumps(all_document), encoding="utf-8")
            with self.assertRaisesRegex(
                managed_state.ManagedStateError,
                "verification-failure evidence",
            ):
                managed_state.load_document(path)

            all_record["requested_action"]["kind"] = "native-replacement"
            all_record["requested_action"]["target_architecture"] = "x86_64"
            all_record["requested_action"]["displaces_verified_paths"] = [
                "/translated/pdfinfo"
            ]
            path.write_text(json.dumps(all_document), encoding="utf-8")
            managed_state.load_document(path)

            all_record["requested_action"]["kind"] = "install"
            all_record["requested_action"]["target_architecture"] = None
            all_record["requested_action"]["displaces_verified_paths"] = []
            all_record["verification"]["verified_paths"] = ["/tools/pdfinfo"]
            path.write_text(json.dumps(all_document), encoding="utf-8")
            managed_state.load_document(path)

    def test_native_replacement_verification_failure_can_retain_wrong_arch_paths(self) -> None:
        action = replace(
            self.plan.actions[0],
            target_architecture="x86_64",
            displaces_verified_paths=("/translated/gs",),
            reason="explicit native replacement",
        )
        plan = replace(self.plan, actions=(action,))
        report_action = replace(
            self.report(provider_execution.ActionOutcome.VERIFICATION_FAILED).actions[0],
            final_verified_paths=("/translated/gs",),
            target_architecture="x86_64",
            displaces_verified_paths=("/translated/gs",),
        )
        report = provider_execution.PlanExecutionReport(
            self.machine,
            plan.requested_capabilities,
            provider_execution.PlanOutcome.PARTIAL_FAILURE,
            (report_action,),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(
                record["verification"]["verified_paths"], ["/translated/gs"]
            )

    def test_translated_homebrew_authorization_evidence_is_structured(self) -> None:
        machine = capabilities.MachineState("Darwin", "arm64", "host")
        missing = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, context: None,
        )
        translated = provider_plans.PackageManagerState(
            "brew", "/usr/local/bin/brew", "host", "x86_64"
        )
        plan = provider_plans.generate_provider_plan(
            (missing,),
            ("bash",),
            package_managers=(translated,),
            translated_manager_fallbacks=(translated,),
        )
        action = plan.actions[0]
        report = provider_execution.PlanExecutionReport(
            machine,
            plan.requested_capabilities,
            provider_execution.PlanOutcome.SUCCEEDED,
            (
                provider_execution.ActionReport(
                    action.capability_id,
                    action.provider_id,
                    action.manager,
                    action.installation_unit,
                    provider_execution.ActionOutcome.SUCCEEDED,
                    (
                        provider_execution.CommandReport(
                            action.commands[0], 0, "installed", ""
                        ),
                    ),
                    ("/usr/local/bin/bash",),
                    "verified",
                ),
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            original = managed_state.load_document(path)
            record = original["records"][0]
            self.assertEqual(record["package_manager"]["architecture"], "x86_64")
            self.assertTrue(
                record["requested_action"][
                    "translated_manager_fallback_authorized"
                ]
            )
            native_document = json.loads(json.dumps(original))
            native_document["records"][0]["package_manager"]["architecture"] = (
                "arm64"
            )
            native_document["records"][0]["requested_action"][
                "translated_manager_fallback_authorized"
            ] = False
            path.write_text(json.dumps(native_document), encoding="utf-8")
            managed_state.load_document(path)
            for architecture, authorized in (
                ("x86_64", False),
                ("arm64", True),
                ("unknown", True),
            ):
                with self.subTest(
                    architecture=architecture, authorized=authorized
                ):
                    document = json.loads(json.dumps(original))
                    document["records"][0]["package_manager"][
                        "architecture"
                    ] = architecture
                    document["records"][0]["requested_action"][
                        "translated_manager_fallback_authorized"
                    ] = authorized
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "Homebrew authorization evidence",
                    ):
                        managed_state.load_document(path)
            for container, field, message in (
                ("package_manager", "architecture", "package-manager evidence"),
                (
                    "requested_action",
                    "translated_manager_fallback_authorized",
                    "requested-action semantics",
                ),
            ):
                with self.subTest(missing_field=field):
                    document = json.loads(json.dumps(original))
                    del document["records"][0][container][field]
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, message
                    ):
                        managed_state.load_document(path)

    def test_success_requires_zero_non_timeout_commands_and_verified_paths(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            document_sentinel = object()
            corruptions = (
                (("command_evidence", 0, "returncode"), 1),
                (("command_evidence", 0, "timed_out"), True),
                (("verification", "verified_paths"), []),
                (
                    ("verification", "verified_paths"),
                    ["/tools/one", "/tools/two", "/tools/three", "/tools/four"],
                ),
                (("command_evidence",), document_sentinel),
            )
            for fields, value in corruptions:
                with self.subTest(fields=fields):
                    document = managed_state.load_document(path)
                    target = document["records"][0]
                    for field in fields[:-1]:
                        target = target[field]
                    if value is document_sentinel:
                        target[fields[-1]] = target[fields[-1]][:1]
                    else:
                        target[fields[-1]] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "evidence"
                    ):
                        managed_state.load_document(path)
                    path.unlink()
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )

    def test_capability_provider_origin_relationship_is_validated(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            for field, value in (
                ("capability_id", "bash"),
                ("origin", "tool-managed"),
            ):
                with self.subTest(field=field):
                    document = managed_state.load_document(path)
                    if field == "origin":
                        document["records"][0]["provider"][field] = value
                    else:
                        document["records"][0][field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "provider identity"
                    ):
                        managed_state.load_document(path)
                    document["records"][0]["capability_id"] = "ghostscript"
                    document["records"][0]["provider"]["origin"] = "system-external"
                    path.write_text(json.dumps(document), encoding="utf-8")

    def test_package_and_context_relationship_is_validated(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=self.report()),
                allow_provider_mutation=True,
            )
            corruptions = (
                (("package_manager", "name"), "winget"),
                (("installation_unit",), "Git.Git"),
                (("execution_context", "platform"), "Windows"),
                (("execution_context", "execution_environment"), "unsupported"),
            )
            for fields, value in corruptions:
                with self.subTest(fields=fields):
                    document = managed_state.load_document(path)
                    target = document["records"][0]
                    for field in fields[:-1]:
                        target = target[field]
                    target[fields[-1]] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError, "package or context"
                    ):
                        managed_state.load_document(path)
                    path.unlink()
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )

    def test_success_appends_immutable_nonownership_records(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(return_value=self.report())
            first = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=executor,
                allow_provider_mutation=True,
            )
            second = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=executor,
                allow_provider_mutation=True,
            )
            self.assertEqual(first.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            self.assertEqual(second.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            records = managed_state.load_document(path)["records"]
            self.assertEqual(len(records), 2)
            self.assertNotEqual(records[0]["id"], records[1]["id"])
            self.assertEqual(
                records[0]["provider"],
                {"id": "host-ghostscript", "origin": "system-external"},
            )
            self.assertEqual(records[0]["package_manager"]["name"], "apt")
            self.assertEqual(records[0]["installation_unit"], "ghostscript")
            self.assertEqual(records[0]["execution_context"]["execution_environment"], "host")
            self.assertFalse(records[0]["ownership"])
            self.assertEqual(records[0]["verification"]["outcome"], "succeeded")
            self.assertEqual(records[0]["requested_action"]["kind"], "install")

            damaged = managed_state.load_document(path)
            damaged["records"][0]["verification"]["outcome"] = "nonsense"
            path.write_text(json.dumps(damaged), encoding="utf-8")
            with self.assertRaisesRegex(managed_state.ManagedStateError, "verification"):
                managed_state.load_document(path)

    def test_preflight_failure_blocks_executor_and_preserves_document(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original = b'{"schema_version":99,"records":[]}\n'
            path.write_bytes(original)
            executor = Mock(side_effect=AssertionError("must not mutate"))
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=executor,
                allow_provider_mutation=True,
            )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.BLOCKED)
            self.assertIsNone(result.execution)
            self.assertEqual(path.read_bytes(), original)
            executor.assert_not_called()

    def test_replace_failure_is_unknown_and_preserves_executor_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original = managed_state.empty_document()
            path.write_text(json.dumps(original), encoding="utf-8")
            execution = self.report()
            with patch.object(managed_state.os, "replace", side_effect=OSError("denied")):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=Mock(return_value=execution),
                    allow_provider_mutation=True,
                )
            self.assertIs(result.execution, execution)
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.UNKNOWN)
            self.assertEqual(managed_state.load_document(path), original)
            self.assertFalse(tuple(path.parent.glob(".managed-state.json.*")))
            self.assertEqual(
                result.execution.outcome, provider_execution.PlanOutcome.SUCCEEDED
            )
            self.assertIn(
                "whether provenance became durable is unknown",
                result.recovery_guidance,
            )

    def test_parent_directory_failure_is_structured_after_successful_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unavailable" / "managed-state.json"
            execution = self.report()
            with patch.object(
                managed_state.Path, "mkdir", side_effect=OSError("read only")
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=Mock(return_value=execution),
                    allow_provider_mutation=True,
                )
            self.assertIs(result.execution, execution)
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.FAILED)
            self.assertIn("provenance was not durably recorded", result.recovery_guidance)
            self.assertFalse(path.exists())

    def test_record_construction_failure_is_structured_before_persistence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original = managed_state.empty_document()
            path.write_text(json.dumps(original), encoding="utf-8")
            execution = self.report()
            executor = Mock(return_value=execution)
            with patch.object(
                managed_state.uuid,
                "uuid4",
                side_effect=OSError("randomness unavailable"),
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertIn("before persistence began", result.persistence_detail)
            self.assertEqual(managed_state.load_document(path), original)
            executor.assert_called_once()

    def test_record_construction_retry_failure_preserves_pending_interrupt(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original = managed_state.empty_document()
            path.write_text(json.dumps(original), encoding="utf-8")
            execution = self.report()
            executor = Mock(return_value=execution)
            with patch.object(
                managed_state,
                "_record",
                side_effect=(KeyboardInterrupt(), OSError("assembly failed")),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertEqual(managed_state.load_document(path), original)
            executor.assert_called_once()

    def test_repeated_record_construction_interrupt_is_structured_prewrite_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original = managed_state.empty_document()
            path.write_text(json.dumps(original), encoding="utf-8")
            execution = self.report()
            executor = Mock(return_value=execution)
            with patch.object(
                managed_state,
                "_record",
                side_effect=(KeyboardInterrupt(), KeyboardInterrupt()),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertIn("repeatedly interrupted", result.persistence_detail)
            self.assertIn(
                "do not rerun provider mutation automatically and do not uninstall or roll back",
                result.recovery_guidance,
            )
            self.assertEqual(managed_state.load_document(path), original)
            executor.assert_called_once()

    def test_repeated_interruption_while_building_prewrite_failure_is_structured(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state,
                    "_prepare_update",
                    side_effect=OSError("assembly failed"),
                ),
                patch.object(
                    managed_state,
                    "_persistence_failure_result",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertIn("before persistence began", result.persistence_detail)
            self.assertFalse(path.exists())
            executor.assert_called_once()

    def test_lock_exit_interrupt_preserves_successful_result(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with patch.object(
                managed_state,
                "_provider_execution_transaction",
                return_value=_InterruptOnExit(),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.SUCCEEDED
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)
            executor.assert_called_once()

    def test_lock_exit_interrupt_preserves_failed_persistence_result(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state,
                    "_provider_execution_transaction",
                    return_value=_InterruptOnExit(),
                ),
                patch.object(
                    managed_state,
                    "_atomic_write",
                    side_effect=managed_state.PersistenceError(
                        managed_state.PersistenceOutcome.FAILED,
                        "write failed",
                    ),
                ),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            executor.assert_called_once()

    def test_lock_exit_interrupt_preserves_provider_interruption(self) -> None:
        action = replace(
            self.report().actions[0],
            outcome=provider_execution.ActionOutcome.INTERRUPTED,
            final_verified_paths=(),
        )
        report = provider_execution.PlanExecutionReport(
            self.machine,
            self.plan.requested_capabilities,
            provider_execution.PlanOutcome.PARTIAL_FAILURE,
            (action,),
        )
        interruption = provider_execution.ProviderPlanInterrupted(report)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(side_effect=interruption)
            with patch.object(
                managed_state,
                "_provider_execution_transaction",
                return_value=_InterruptOnExit(),
            ):
                with self.assertRaises(
                    provider_execution.ProviderPlanInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception, interruption)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.SUCCEEDED,
            )
            executor.assert_called_once()

    def test_lock_exit_interrupt_preserves_persistence_interruption(self) -> None:
        failure = managed_state.PersistenceInterrupted(
            managed_state.PersistenceOutcome.UNKNOWN,
            "durability unknown",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(return_value=self.report())
            with (
                patch.object(
                    managed_state,
                    "_provider_execution_transaction",
                    return_value=_InterruptOnExit(),
                ),
                patch.object(managed_state, "_atomic_write", side_effect=failure),
            ):
                with self.assertRaises(
                    managed_state.PersistenceInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception, failure)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            executor.assert_called_once()

    def test_new_directory_entries_are_synced_before_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "agent-tools" / "managed-state.json"
            with patch.object(managed_state, "_sync_parent_directory") as sync:
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=Mock(return_value=self.report()),
                    allow_provider_mutation=True,
                )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            self.assertEqual(
                [call.args[0] for call in sync.call_args_list],
                [path.parent, root],
            )

    def test_post_replace_sync_failure_reports_unknown_without_rerun(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(return_value=self.report())
            with patch.object(
                managed_state,
                "_sync_parent_directory",
                side_effect=OSError("directory sync failed"),
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.UNKNOWN)
            executor.assert_called_once()
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)

    def test_persistence_interruption_preserves_unknown_result(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with patch.object(
                managed_state,
                "_sync_parent_directory",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(managed_state.PersistenceInterrupted) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            result = raised.exception.managed_result
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.UNKNOWN)
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)

    def test_prewrite_persistence_interrupt_is_failed_not_succeeded(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with patch.object(
                managed_state,
                "_missing_directories",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(managed_state.PersistenceInterrupted) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.FAILED,
            )
            self.assertFalse(path.exists())

    def test_pre_replace_failures_are_failed_and_do_not_rerun_provider(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                (
                    "mkdir",
                    root / "mkdir" / "managed-state.json",
                    patch.object(
                        managed_state.Path,
                        "mkdir",
                        side_effect=OSError("mkdir failed"),
                    ),
                ),
                (
                    "temporary creation",
                    root / "temporary.json",
                    patch.object(
                        managed_state.tempfile,
                        "NamedTemporaryFile",
                        side_effect=OSError("temporary creation failed"),
                    ),
                ),
                (
                    "write",
                    root / "write.json",
                    patch.object(
                        managed_state.json,
                        "dump",
                        side_effect=OSError("write failed"),
                    ),
                ),
                (
                    "fsync",
                    root / "fsync.json",
                    patch.object(
                        managed_state.os,
                        "fsync",
                        side_effect=OSError("fsync failed"),
                    ),
                ),
            )
            for name, path, injected_failure in cases:
                with self.subTest(phase=name):
                    executor = Mock(return_value=self.report())
                    with injected_failure:
                        result = managed_state.execute_provider_plan(
                            self.plan,
                            state_path=path,
                            executor=executor,
                            allow_provider_mutation=True,
                        )
                    self.assertEqual(
                        result.persistence, managed_state.PersistenceOutcome.FAILED
                    )
                    self.assertIs(result.execution, executor.return_value)
                    self.assertIn(
                        "do not rerun provider mutation automatically and do not uninstall or roll back",
                        result.recovery_guidance,
                    )
                    executor.assert_called_once()

    def test_cleanup_cannot_replace_failed_or_unknown_primary_outcome(self) -> None:
        cases = (
            (
                "pre-replacement error",
                patch.object(
                    managed_state.json,
                    "dump",
                    side_effect=OSError("write failed"),
                ),
                managed_state.PersistenceOutcome.FAILED,
            ),
            (
                "replacement error",
                patch.object(
                    managed_state.os,
                    "replace",
                    side_effect=OSError("replace failed"),
                ),
                managed_state.PersistenceOutcome.UNKNOWN,
            ),
        )
        for primary_name, primary_failure, expected in cases:
            for cleanup_error in (OSError("cleanup failed"), KeyboardInterrupt()):
                with self.subTest(
                    primary=primary_name,
                    cleanup=type(cleanup_error).__name__,
                ), TemporaryDirectory() as directory:
                    executor = Mock(return_value=self.report())
                    with (
                        primary_failure,
                        patch.object(
                            managed_state,
                            "_discard_temporary",
                            side_effect=cleanup_error,
                        ),
                    ):
                        result = managed_state.execute_provider_plan(
                            self.plan,
                            state_path=Path(directory) / "managed-state.json",
                            executor=executor,
                            allow_provider_mutation=True,
                        )
                    self.assertEqual(result.persistence, expected)
                    self.assertIs(result.execution, executor.return_value)
                    executor.assert_called_once()

    def test_cleanup_interrupt_preserves_primary_persistence_interrupt(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(return_value=self.report())
            with (
                patch.object(
                    managed_state.json,
                    "dump",
                    side_effect=KeyboardInterrupt(),
                ),
                patch.object(
                    managed_state,
                    "_discard_temporary",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(
                    managed_state.PersistenceInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.FAILED,
            )
            self.assertIs(
                raised.exception.managed_result.execution, executor.return_value
            )
            executor.assert_called_once()

    def test_error_carrier_construction_interrupt_preserves_failed_outcome(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state.json,
                    "dump",
                    side_effect=OSError("write failed"),
                ),
                patch.object(
                    managed_state.PersistenceError,
                    "__init__",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            self.assertIs(result.execution, execution)
            self.assertEqual(
                result.persistence, managed_state.PersistenceOutcome.FAILED
            )
            self.assertIn("write failed", result.persistence_detail)
            self.assertFalse(path.exists())
            executor.assert_called_once()

    def test_interrupt_carrier_construction_interrupt_preserves_primary_outcome(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state.json,
                    "dump",
                    side_effect=KeyboardInterrupt(),
                ),
                patch.object(
                    managed_state.PersistenceInterrupted,
                    "__init__",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(
                    managed_state.PersistenceInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception.managed_result.execution, execution)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.FAILED,
            )
            self.assertFalse(path.exists())
            executor.assert_called_once()

    def test_failure_result_constructor_interrupt_preserves_failed_outcome(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state,
                    "_atomic_write",
                    side_effect=managed_state.PersistenceError(
                        managed_state.PersistenceOutcome.FAILED,
                        "write failed",
                    ),
                ),
                patch.object(
                    managed_state.ManagedExecutionResult,
                    "__init__",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception.managed_result.execution, execution)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.FAILED,
            )
            executor.assert_called_once()

    def test_managed_interrupt_constructor_interrupt_preserves_unknown_result(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            execution = self.report()
            executor = Mock(return_value=execution)
            with (
                patch.object(
                    managed_state,
                    "_atomic_write",
                    side_effect=KeyboardInterrupt(),
                ),
                patch.object(
                    managed_state.ManagedExecutionInterrupted,
                    "__init__",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception.managed_result.execution, execution)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            executor.assert_called_once()

    def test_unclassified_atomic_interrupt_is_conservatively_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(return_value=self.report())
            with patch.object(
                managed_state,
                "_atomic_write",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=executor,
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            self.assertIs(
                raised.exception.managed_result.execution, executor.return_value
            )
            self.assertIn(
                "whether provenance became durable is unknown",
                raised.exception.managed_result.recovery_guidance,
            )
            executor.assert_called_once()

    def test_interrupt_during_persistence_failure_result_is_structured(self) -> None:
        original = managed_state._persistence_failure_result
        calls = 0

        def interrupt_once(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt()
            return original(*args)

        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            report = self.report()
            with (
                patch.object(
                    managed_state,
                    "_atomic_write",
                    side_effect=managed_state.PersistenceError(
                        managed_state.PersistenceOutcome.FAILED,
                        "write failed",
                    ),
                ),
                patch.object(
                    managed_state,
                    "_persistence_failure_result",
                    side_effect=interrupt_once,
                ),
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=report),
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.FAILED,
            )
            self.assertIs(raised.exception.managed_result.execution, report)

    def test_interrupt_during_persistence_result_attachment_keeps_unknown(self) -> None:
        class AttachmentInterrupted(managed_state.PersistenceInterrupted):
            def __init__(self) -> None:
                super().__init__(
                    managed_state.PersistenceOutcome.UNKNOWN,
                    "durability is unknown",
                )
                self._interrupt_attachment = True

            def __setattr__(self, name, value):
                if name == "managed_result" and getattr(
                    self, "_interrupt_attachment", False
                ):
                    object.__setattr__(self, "_interrupt_attachment", False)
                    raise KeyboardInterrupt()
                super().__setattr__(name, value)

        failure = AttachmentInterrupted()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with patch.object(
                managed_state, "_atomic_write", side_effect=failure
            ):
                with self.assertRaises(managed_state.PersistenceInterrupted) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            self.assertIs(raised.exception, failure)
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )

    def test_interruption_after_replace_begins_is_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original_replace = managed_state.os.replace

            def replace_then_interrupt(source: Path, destination: Path) -> None:
                original_replace(source, destination)
                raise KeyboardInterrupt()

            with patch.object(
                managed_state.os, "replace", side_effect=replace_then_interrupt
            ):
                with self.assertRaises(managed_state.PersistenceInterrupted) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)

    def test_error_after_replace_begins_is_unknown(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original_replace = managed_state.os.replace

            def replace_then_error(source: Path, destination: Path) -> None:
                original_replace(source, destination)
                raise OSError("remote durability indeterminate")

            with patch.object(
                managed_state.os, "replace", side_effect=replace_then_error
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=Mock(return_value=self.report()),
                    allow_provider_mutation=True,
                )
            self.assertEqual(
                result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)

    def test_cleanup_interrupt_after_replacement_ambiguity_remains_unknown(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original_replace = managed_state.os.replace

            def replace_then_error(source: Path, destination: Path) -> None:
                original_replace(source, destination)
                raise OSError("replacement completion is ambiguous")

            executor = Mock(return_value=self.report())
            with (
                patch.object(
                    managed_state.os,
                    "replace",
                    side_effect=replace_then_error,
                ),
                patch.object(
                    managed_state,
                    "_discard_temporary",
                    side_effect=KeyboardInterrupt(),
                ),
            ):
                result = managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            self.assertEqual(
                result.persistence,
                managed_state.PersistenceOutcome.UNKNOWN,
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)
            self.assertIn(
                "whether provenance became durable is unknown",
                result.recovery_guidance,
            )
            executor.assert_called_once()

    def test_process_local_transactions_do_not_lose_records(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            barrier = threading.Barrier(2)
            results = []

            def execute() -> None:
                barrier.wait()
                results.append(
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
                )

            threads = [threading.Thread(target=execute) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(
                [result.persistence for result in results],
                [managed_state.PersistenceOutcome.SUCCEEDED] * 2,
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 2)

    def test_no_command_means_no_provenance_write(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(
                    return_value=self.report(
                        provider_execution.ActionOutcome.ALREADY_SATISFIED,
                        commands=False,
                    )
                ),
                allow_provider_mutation=True,
            )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.NOT_REQUIRED)
            self.assertFalse(path.exists())

    def test_failed_mutation_attempt_is_recorded_without_success_claim(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            failed = self.report(provider_execution.ActionOutcome.COMMAND_FAILED)
            failed = provider_execution.PlanExecutionReport(
                failed.context,
                failed.requested_capabilities,
                provider_execution.PlanOutcome.PARTIAL_FAILURE,
                failed.actions,
                ("inspect current provider state",),
            )
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                executor=Mock(return_value=failed),
                allow_provider_mutation=True,
            )
            self.assertEqual(
                result.execution.outcome, provider_execution.PlanOutcome.PARTIAL_FAILURE
            )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "command-failed")
            self.assertFalse(record["ownership"])

    def test_post_command_verification_exception_is_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            absent = capabilities.detect_capability(
                capabilities.GHOSTSCRIPT,
                self.machine,
                locator=lambda probe, machine: None,
            )
            detector = Mock(side_effect=(absent, RuntimeError("verification broke")))
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                allow_provider_mutation=True,
                current_context=lambda: self.machine,
                detector=detector,
                manager_verifier=lambda state, machine: True,
                privilege_resolver=lambda action: "/usr/bin/sudo",
                supervisor_resolver=lambda action: "/usr/bin/timeout",
                privilege_preflight=lambda argv: True,
                runner=lambda argv, timeout: subprocess.CompletedProcess(
                    argv, 0, "installed", ""
                ),
            )
            self.assertEqual(
                result.execution.actions[0].outcome,
                provider_execution.ActionOutcome.VERIFICATION_FAILED,
            )
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "verification-failed")
            self.assertEqual(record["command_evidence"][0]["stdout"], "installed")

    def test_relative_post_action_identity_cannot_corrupt_provenance(self) -> None:
        absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, context: None,
        )
        relative = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, context: "relative/gs",
            version_reader=lambda probe, path: "1.0",
            architecture_reader=lambda probe, path: "x86_64",
        )
        detector = Mock(side_effect=(absent, relative))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            result = managed_state.execute_provider_plan(
                self.plan,
                state_path=path,
                allow_provider_mutation=True,
                current_context=lambda: self.machine,
                detector=detector,
                manager_verifier=lambda state, context: True,
                privilege_resolver=lambda action: "/usr/bin/sudo",
                supervisor_resolver=lambda action: "/usr/bin/timeout",
                privilege_preflight=lambda argv: True,
                runner=lambda argv, timeout: subprocess.CompletedProcess(
                    argv, 0, "installed", ""
                ),
            )
            self.assertEqual(
                result.execution.actions[0].outcome,
                provider_execution.ActionOutcome.VERIFICATION_FAILED,
            )
            self.assertEqual(
                result.execution.actions[0].final_verified_paths,
                (),
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["verified_paths"], [])

    def test_interrupted_attempt_is_persisted_before_interrupt_propagates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            action = replace(
                self.report().actions[0],
                outcome=provider_execution.ActionOutcome.INTERRUPTED,
                final_verified_paths=(),
                detail="interrupted",
            )
            report = provider_execution.PlanExecutionReport(
                self.machine,
                self.plan.requested_capabilities,
                provider_execution.PlanOutcome.PARTIAL_FAILURE,
                (action,),
                ("inspect current provider state",),
            )
            interruption = provider_execution.ProviderPlanInterrupted(report)
            executor = Mock(side_effect=interruption)
            with self.assertRaises(provider_execution.ProviderPlanInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            result = raised.exception.managed_result
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "interrupted")

    def test_post_runner_classification_interrupt_persists_completed_evidence(self) -> None:
        absent = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, context: None,
        )
        completed = subprocess.CompletedProcess(
            ("ignored",), 7, "completed output", "completed error"
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with (
                patch.object(
                    provider_execution,
                    "_completed_command_failure",
                    side_effect=KeyboardInterrupt(),
                ),
                self.assertRaises(
                    provider_execution.ProviderPlanInterrupted
                ) as raised,
            ):
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    allow_provider_mutation=True,
                    current_context=lambda: self.machine,
                    detector=lambda capability, context: absent,
                    manager_verifier=lambda state, context: True,
                    privilege_resolver=lambda action: "/usr/bin/sudo",
                    supervisor_resolver=lambda action: "/usr/bin/timeout",
                    privilege_preflight=lambda argv: True,
                    runner=lambda argv, timeout: completed,
                )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.SUCCEEDED,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "interrupted")
            self.assertEqual(len(record["command_evidence"]), 1)
            self.assertEqual(record["command_evidence"][0]["returncode"], 7)
            self.assertEqual(
                record["command_evidence"][0]["stdout"], "completed output"
            )
            self.assertEqual(
                record["command_evidence"][0]["stderr"], "completed error"
            )

    def test_executor_preflight_interrupt_is_not_recorded_as_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            with self.assertRaises(provider_execution.ProviderPlanInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    allow_provider_mutation=True,
                    current_context=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
                )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.NOT_REQUIRED,
            )
            self.assertTrue(
                all(
                    action.outcome is provider_execution.ActionOutcome.NOT_ATTEMPTED
                    for action in raised.exception.report.actions
                )
            )
            self.assertFalse(path.exists())

    def test_raw_post_command_interrupt_is_conservatively_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            executor = Mock(side_effect=KeyboardInterrupt())
            with self.assertRaises(managed_state.ManagedExecutionInterrupted) as raised:
                managed_state.execute_provider_plan(
                    self.plan,
                    state_path=path,
                    executor=executor,
                    allow_provider_mutation=True,
                )
            result = raised.exception.managed_result
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.SUCCEEDED)
            self.assertEqual(
                result.execution.actions[0].outcome,
                provider_execution.ActionOutcome.INTERRUPTED,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "interrupted")
            self.assertEqual(record["command_evidence"], [])
            self.assertIn("progress", record["verification"]["detail"])

    def test_record_assembly_interrupt_preserves_completed_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            original_record = managed_state._record
            calls = 0

            def interrupt_once(*arguments: object) -> dict[str, object]:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise KeyboardInterrupt()
                return original_record(*arguments)

            with patch.object(managed_state, "_record", side_effect=interrupt_once):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.SUCCEEDED,
            )
            record = managed_state.load_document(path)["records"][0]
            self.assertEqual(record["verification"]["outcome"], "succeeded")
            self.assertEqual(record["command_evidence"][0]["returncode"], 0)
            self.assertEqual(record["command_evidence"][0]["stdout"], "installed")

    def test_post_persistence_finalization_interrupt_carries_result(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            result_type = managed_state.ManagedExecutionResult
            calls = 0

            def interrupt_once(*arguments: object) -> object:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise KeyboardInterrupt()
                return result_type(*arguments)

            with patch.object(
                managed_state,
                "ManagedExecutionResult",
                side_effect=interrupt_once,
            ):
                with self.assertRaises(
                    managed_state.ManagedExecutionInterrupted
                ) as raised:
                    managed_state.execute_provider_plan(
                        self.plan,
                        state_path=path,
                        executor=Mock(return_value=self.report()),
                        allow_provider_mutation=True,
                    )
            self.assertEqual(
                raised.exception.managed_result.persistence,
                managed_state.PersistenceOutcome.SUCCEEDED,
            )
            self.assertEqual(len(managed_state.load_document(path)["records"]), 1)

    def test_invalid_default_state_path_blocks_before_executor(self) -> None:
        executor = Mock(side_effect=AssertionError("must not mutate"))
        with patch.object(
            managed_state,
            "managed_state_path",
            side_effect=managed_state.ManagedStateError("invalid state root"),
        ):
            result = managed_state.execute_provider_plan(
                self.plan,
                executor=executor,
                allow_provider_mutation=True,
            )
        self.assertEqual(result.persistence, managed_state.PersistenceOutcome.BLOCKED)
        self.assertIsNone(result.execution)
        executor.assert_not_called()

    def test_native_replacement_semantics_are_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            action = replace(
                self.plan.actions[0],
                target_architecture="x86_64",
                displaces_verified_paths=("/translated/gs",),
                reason="explicit native replacement",
            )
            plan = replace(self.plan, actions=(action,))
            report = self.report()
            report_action = replace(
                report.actions[0],
                target_architecture="x86_64",
                displaces_verified_paths=("/translated/gs",),
            )
            report = replace(report, actions=(report_action,))
            path = Path(directory) / "managed-state.json"
            managed_state.execute_provider_plan(
                plan,
                state_path=path,
                executor=Mock(return_value=report),
                allow_provider_mutation=True,
            )
            requested = managed_state.load_document(path)["records"][0][
                "requested_action"
            ]
            self.assertEqual(requested["kind"], "native-replacement")
            self.assertEqual(requested["target_architecture"], "x86_64")
            self.assertEqual(requested["displaces_verified_paths"], ["/translated/gs"])

            for field, value in (
                ("kind", "install"),
                ("target_architecture", None),
                ("target_architecture", "arm64"),
                ("displaces_verified_paths", []),
                ("displaces_verified_paths", ["relative/gs"]),
            ):
                with self.subTest(field=field, value=value):
                    document = managed_state.load_document(path)
                    document["records"][0]["requested_action"][field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(
                        managed_state.ManagedStateError,
                        "native-replacement|displaced-provider",
                    ):
                        managed_state.load_document(path)
                    path.unlink()
                    managed_state.execute_provider_plan(
                        plan,
                        state_path=path,
                        executor=Mock(return_value=report),
                        allow_provider_mutation=True,
                    )


if __name__ == "__main__":
    unittest.main()
