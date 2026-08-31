import json
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

    def test_failed_write_preserves_prior_document_and_executor_evidence(self) -> None:
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
            self.assertEqual(result.persistence, managed_state.PersistenceOutcome.FAILED)
            self.assertEqual(managed_state.load_document(path), original)
            self.assertFalse(tuple(path.parent.glob(".managed-state.json.*")))
            self.assertEqual(
                result.execution.outcome, provider_execution.PlanOutcome.SUCCEEDED
            )
            self.assertIn("provenance was not durably recorded", result.recovery_guidance)

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
