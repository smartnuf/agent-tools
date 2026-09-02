from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_tools import capabilities, claude_code_integration as integration


WINDOWS = capabilities.MachineState("Windows", "AMD64", "host")
WSL = capabilities.MachineState("Linux", "x86_64", "wsl")
GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"


def git_bash_state(path: str = GIT_BASH):
    return capabilities.detect_capability(
        capabilities.BASH,
        WINDOWS,
        locator=lambda probe, machine: (
            path if probe.locator_strategy == "git-bash" else None
        ),
        version_reader=lambda probe, executable: "GNU bash 5.2.37",
        architecture_reader=lambda probe, executable: "x86_64",
    )


class ClaudeCodeIntegrationTests(unittest.TestCase):
    def paths(self, directory: str) -> tuple[Path, Path]:
        root = Path(directory)
        return root / ".claude" / "settings.json", root / "state.json"

    def apply(self, settings: Path, state: Path, **kwargs):
        return integration.apply_git_bash_integration(
            machine=WINDOWS,
            detector=lambda capability, machine: git_bash_state(),
            settings_path=settings,
            state_path=state,
            **kwargs,
        )

    def remove(self, settings: Path, state: Path, **kwargs):
        return integration.remove_git_bash_integration(
            machine=WINDOWS,
            settings_path=settings,
            state_path=state,
            **kwargs,
        )

    def test_documented_windows_paths_honor_claude_config_dir(self) -> None:
        self.assertEqual(
            integration.claude_settings_path(
                environment={"USERPROFILE": r"C:\Users\person"}
            ),
            Path(r"C:\Users\person") / ".claude" / "settings.json",
        )
        self.assertEqual(
            integration.claude_settings_path(
                environment={"CLAUDE_CONFIG_DIR": r"D:\Claude"}
            ),
            Path(r"D:\Claude") / "settings.json",
        )
        self.assertEqual(
            integration.integration_state_path(
                environment={"LOCALAPPDATA": r"C:\Users\person\AppData\Local"}
            ),
            Path(r"C:\Users\person\AppData\Local")
            / "agent-tools"
            / "integrations"
            / "claude-code.json",
        )

    def test_changed_apply_requires_authority_without_writing(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            result = self.apply(settings, state)
            self.assertIs(result.outcome, integration.IntegrationOutcome.REFUSED)
            self.assertFalse(settings.exists())
            self.assertFalse(state.exists())

    def test_apply_and_remove_restore_preexisting_value_and_unrelated_settings(self) -> None:
        original = {
            "$schema": "https://json.schemastore.org/claude-code-settings.json",
            "env": {"KEEP": "yes", integration.SETTING_NAME: r"D:\Old\bash.exe"},
            "theme": "dark",
        }
        raw = json.dumps(original, separators=(",", ":")).encode()
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            settings.parent.mkdir()
            settings.write_bytes(raw)
            applied = self.apply(
                settings, state, allow_config_mutation=True
            )
            self.assertIs(applied.outcome, integration.IntegrationOutcome.UPDATED)
            configured = integration._parse_settings(settings.read_bytes())
            self.assertEqual(configured["env"][integration.SETTING_NAME], GIT_BASH)
            self.assertEqual(configured["env"]["KEEP"], "yes")
            self.assertEqual(configured["theme"], "dark")
            self.assertTrue(any(path.read_bytes() == raw for path in applied.backup_paths))
            record = integration._parse_state(state.read_bytes())
            self.assertEqual(record["phase"], "active")
            self.assertEqual(record["previous"]["value"], r"D:\Old\bash.exe")

            removed = self.remove(
                settings, state, allow_config_mutation=True
            )
            self.assertIs(removed.phase, integration.IntegrationPhase.REMOVED)
            restored = integration._parse_settings(settings.read_bytes())
            self.assertEqual(restored, original)
            self.assertEqual(
                integration._parse_state(state.read_bytes())["phase"], "removed"
            )

    def test_apply_and_remove_are_safe_to_repeat(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            first = self.apply(settings, state, allow_config_mutation=True)
            second = self.apply(settings, state, allow_config_mutation=True)
            self.assertIs(first.outcome, integration.IntegrationOutcome.UPDATED)
            self.assertIs(second.outcome, integration.IntegrationOutcome.NO_CHANGES)
            first_remove = self.remove(settings, state, allow_config_mutation=True)
            second_remove = self.remove(settings, state, allow_config_mutation=True)
            self.assertIs(first_remove.outcome, integration.IntegrationOutcome.UPDATED)
            self.assertIs(
                second_remove.outcome, integration.IntegrationOutcome.NO_CHANGES
            )
            self.assertFalse(settings.exists())

    def test_new_lifecycle_does_not_inherit_absent_file_ownership(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            self.apply(settings, state, allow_config_mutation=True)
            self.remove(settings, state, allow_config_mutation=True)
            self.assertFalse(settings.exists())

            settings.parent.mkdir(exist_ok=True)
            settings.write_text("{}\n", encoding="utf-8")
            self.apply(settings, state, allow_config_mutation=True)
            self.remove(settings, state, allow_config_mutation=True)

            self.assertTrue(settings.exists())
            self.assertEqual(integration._parse_settings(settings.read_bytes()), {})

    def test_preexisting_matching_value_is_not_claimed(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"env": {integration.SETTING_NAME: GIT_BASH}}),
                encoding="utf-8",
            )
            result = self.apply(
                settings, state, allow_config_mutation=True
            )
            self.assertIs(result.outcome, integration.IntegrationOutcome.NO_CHANGES)
            self.assertIn("not claimed", result.detail)
            self.assertFalse(state.exists())
            removed = self.remove(
                settings, state, allow_config_mutation=True
            )
            self.assertIs(removed.outcome, integration.IntegrationOutcome.NO_CHANGES)
            self.assertEqual(
                integration._parse_settings(settings.read_bytes())["env"][
                    integration.SETTING_NAME
                ],
                GIT_BASH,
            )

    def test_only_verified_selected_native_windows_git_bash_is_accepted(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            for machine, detected in (
                (WSL, git_bash_state()),
                (
                    WINDOWS,
                    capabilities.detect_capability(
                        capabilities.BASH,
                        WINDOWS,
                        locator=lambda probe, context: None,
                    ),
                ),
            ):
                with self.subTest(machine=machine, selected=detected.selected_provider):
                    with self.assertRaises(integration.ClaudeCodeIntegrationError):
                        integration.apply_git_bash_integration(
                            machine=machine,
                            detector=lambda capability, context, value=detected: value,
                            settings_path=settings,
                            state_path=state,
                            allow_config_mutation=True,
                        )
                    self.assertFalse(settings.exists())
                    self.assertFalse(state.exists())

    def test_malformed_and_nonregular_entries_fail_closed(self) -> None:
        cases = (
            b'{"env":{"X":"1","X":"2"}}',
            b'{"env":null}',
            b'{"env":{"X":1}}',
        )
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            settings.parent.mkdir()
            for raw in cases:
                settings.write_bytes(raw)
                with self.assertRaises(integration.ClaudeCodeIntegrationError):
                    self.apply(settings, state, allow_config_mutation=True)
                self.assertEqual(settings.read_bytes(), raw)
                self.assertFalse(state.exists())
            settings.unlink()
            target = settings.parent / "target.json"
            target.write_text("{}", encoding="utf-8")
            try:
                settings.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(
                integration.ClaudeCodeIntegrationError, "ordinary regular"
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertTrue(settings.is_symlink())

    def test_unreadable_integration_state_is_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            state.write_bytes(b'{"schema_version":2}')
            with self.assertRaisesRegex(
                integration.ClaudeCodeIntegrationError, "schema v1"
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertEqual(state.read_bytes(), b'{"schema_version":2}')
            self.assertFalse(settings.exists())

            state.unlink()
            target = state.with_name("state-target.json")
            target.write_text("{}", encoding="utf-8")
            try:
                state.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(
                integration.ClaudeCodeIntegrationError, "ordinary regular"
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertTrue(state.is_symlink())
            self.assertFalse(settings.exists())

    def test_state_reader_rejects_unreachable_absent_file_history(self) -> None:
        record = {
            "schema_version": 1,
            "phase": "active",
            "settings_path": r"C:\Users\person\.claude\settings.json",
            "settings_existed": False,
            "applied_value": GIT_BASH,
            "previous": {"present": True, "value": r"D:\Old\bash.exe"},
        }
        with self.assertRaisesRegex(
            integration.ClaudeCodeIntegrationError, "settings history"
        ):
            integration._parse_state(json.dumps(record).encode())

    def test_external_member_change_blocks_apply_and_remove(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            self.apply(settings, state, allow_config_mutation=True)
            document = integration._parse_settings(settings.read_bytes())
            document["env"][integration.SETTING_NAME] = r"E:\User\bash.exe"
            settings.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                integration.ClaudeCodeIntegrationError, "diverged"
            ):
                self.apply(settings, state, allow_config_mutation=True)
            with self.assertRaisesRegex(
                integration.ClaudeCodeIntegrationError, "diverged"
            ):
                self.remove(settings, state, allow_config_mutation=True)
            self.assertEqual(
                integration._parse_settings(settings.read_bytes())["env"][
                    integration.SETTING_NAME
                ],
                r"E:\User\bash.exe",
            )

    def test_activation_record_failure_restores_settings(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            settings.parent.mkdir()
            raw = b'{"env":{"KEEP":"yes"}}\n'
            settings.write_bytes(raw)
            actual_replace = integration._replace_document
            calls = 0

            def fail_activation(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise integration.ClaudeCodeIntegrationError("state denied")
                return actual_replace(*args, **kwargs)

            with (
                patch.object(integration, "_replace_document", side_effect=fail_activation),
                self.assertRaisesRegex(
                    integration.ClaudeCodeIntegrationError, "prior settings restored"
                ),
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertEqual(settings.read_bytes(), raw)
            self.assertEqual(
                integration._parse_state(state.read_bytes())["phase"], "prepared"
            )

    def test_prepared_reconciliation_refreshes_unchanged_file_existence(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            actual_replace = integration._replace_document
            calls = 0

            def fail_activation(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise integration.ClaudeCodeIntegrationError("state denied")
                return actual_replace(*args, **kwargs)

            with (
                patch.object(
                    integration,
                    "_replace_document",
                    side_effect=fail_activation,
                ),
                self.assertRaises(integration.ClaudeCodeIntegrationError),
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertFalse(settings.exists())

            settings.parent.mkdir(exist_ok=True)
            settings.write_text("{}\n", encoding="utf-8")
            self.apply(settings, state, allow_config_mutation=True)
            self.remove(settings, state, allow_config_mutation=True)
            self.assertTrue(settings.exists())
            self.assertEqual(integration._parse_settings(settings.read_bytes()), {})

    def test_first_interrupt_during_activation_restores_settings(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            settings.parent.mkdir()
            raw = b'{"env":{"KEEP":"yes"}}\n'
            settings.write_bytes(raw)
            actual_replace = integration._replace_document
            calls = 0

            def interrupt_activation(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise KeyboardInterrupt
                return actual_replace(*args, **kwargs)

            with (
                patch.object(
                    integration,
                    "_replace_document",
                    side_effect=interrupt_activation,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertEqual(settings.read_bytes(), raw)
            self.assertEqual(
                integration._parse_state(state.read_bytes())["phase"], "prepared"
            )

    def test_first_interrupt_between_files_is_observed_before_setting_change(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            actual_replace = integration._replace_document
            calls = 0

            def request_after_prepared(*args, **kwargs):
                nonlocal calls
                calls += 1
                result = actual_replace(*args, **kwargs)
                if calls == 1:
                    args[-1].request()
                return result

            with (
                patch.object(
                    integration,
                    "_replace_document",
                    side_effect=request_after_prepared,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.apply(settings, state, allow_config_mutation=True)
            self.assertFalse(settings.exists())
            self.assertEqual(
                integration._parse_state(state.read_bytes())["phase"], "prepared"
            )

    def test_interrupted_remove_can_finalize_without_repeating_setting_change(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            self.apply(settings, state, allow_config_mutation=True)
            actual_replace = integration._replace_document
            calls = 0

            def fail_final_state(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise integration.ClaudeCodeIntegrationError("state denied")
                return actual_replace(*args, **kwargs)

            with (
                patch.object(integration, "_replace_document", side_effect=fail_final_state),
                self.assertRaises(integration.ClaudeCodeIntegrationError),
            ):
                self.remove(settings, state, allow_config_mutation=True)
            self.assertFalse(settings.exists())
            self.assertEqual(
                integration._parse_state(state.read_bytes())["phase"], "removing"
            )
            reconciled = self.remove(settings, state, allow_config_mutation=True)
            self.assertIs(reconciled.phase, integration.IntegrationPhase.REMOVED)
            self.assertFalse(settings.exists())

    def test_status_keeps_integration_state_distinct(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            empty = integration.inspect_integration(
                settings_path=settings, state_path=state
            )
            self.assertFalse(empty.managed)
            self.assertIsNone(empty.phase)
            self.apply(settings, state, allow_config_mutation=True)
            active = integration.inspect_integration(
                settings_path=settings, state_path=state
            )
            self.assertTrue(active.managed)
            self.assertIs(active.phase, integration.IntegrationPhase.ACTIVE)

    def test_lifecycle_never_invokes_provider_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            settings, state = self.paths(directory)
            with patch(
                "agent_tools.managed_state.execute_provider_plan",
                side_effect=AssertionError("integration must not mutate providers"),
            ) as execute:
                self.apply(settings, state, allow_config_mutation=True)
                self.remove(settings, state, allow_config_mutation=True)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
