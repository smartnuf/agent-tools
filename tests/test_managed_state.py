import json
import subprocess
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities, managed_state, provider_execution, provider_plans


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
        command_reports = (
            provider_execution.CommandReport(action.commands[0], 0, "installed", ""),
        ) if commands else ()
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
                    ("/tools/gs",),
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

    def test_interrupted_attempt_is_persisted_before_interrupt_propagates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "managed-state.json"
            action = replace(
                self.report().actions[0],
                outcome=provider_execution.ActionOutcome.INTERRUPTED,
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


if __name__ == "__main__":
    unittest.main()
