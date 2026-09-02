from __future__ import annotations

import json
import os
import signal
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_tools import capabilities, desired_state


LINUX = capabilities.MachineState("Linux", "x86_64")
WINDOWS = capabilities.MachineState("Windows", "AMD64")


class DesiredStateTests(unittest.TestCase):
    def test_platform_paths_are_private_per_user_locations(self) -> None:
        self.assertEqual(
            desired_state.desired_state_path(
                platform_name="Linux",
                environment={"XDG_CONFIG_HOME": "/srv/config"},
                home=Path("/home/user"),
            ),
            Path("/srv/config/agent-tools/config.json"),
        )
        self.assertEqual(
            desired_state.desired_state_path(
                platform_name="Linux",
                environment={"XDG_CONFIG_HOME": "relative"},
                home=Path("/home/user"),
            ),
            Path("/home/user/.config/agent-tools/config.json"),
        )
        self.assertEqual(
            desired_state.desired_state_path(
                platform_name="Darwin", environment={}, home=Path("/Users/user")
            ),
            Path("/Users/user/Library/Application Support/agent-tools/config.json"),
        )
        windows = desired_state.desired_state_path(
            platform_name="Windows",
            environment={"LOCALAPPDATA": "C:\\Users\\user\\AppData\\Local"},
        )
        self.assertEqual(windows.name, "config.json")
        self.assertEqual(windows.parent.name, "agent-tools")

    def test_platform_paths_fail_closed_without_absolute_authority(self) -> None:
        with self.assertRaisesRegex(desired_state.DesiredStateError, "LOCALAPPDATA"):
            desired_state.desired_state_path(
                platform_name="Windows", environment={"LOCALAPPDATA": "relative"}
            )
        with self.assertRaisesRegex(desired_state.DesiredStateError, "not absolute"):
            desired_state.desired_state_path(
                platform_name="Linux", environment={}, home=Path("relative")
            )

    def test_absent_document_reads_as_empty_without_creating_state(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertEqual(desired_state.load_document(path), desired_state.empty_document())
            self.assertFalse(path.exists())

    def test_reader_rejects_malformed_hostile_and_unknown_languages(self) -> None:
        cases = {
            "invalid utf8": b"\xff",
            "duplicate": b'{"schema_version":1,"schema_version":1,"capabilities":{}}',
            "unknown version": b'{"schema_version":2,"capabilities":{}}',
            "extra root": b'{"schema_version":1,"capabilities":{},"extra":true}',
            "extra entry": b'{"schema_version":1,"capabilities":{"bash":{"extra":true}}}',
            "wrong provider": b'{"schema_version":1,"capabilities":{"bash":{"provider":7}}}',
            "null provider": b'{"schema_version":1,"capabilities":{"bash":{"provider":null}}}',
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, raw in cases.items():
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(raw)
                    with self.assertRaises(desired_state.DesiredStateError):
                        desired_state.load_document(path)
                    self.assertEqual(path.read_bytes(), raw)

    def test_reader_bounds_size_depth_count_and_identity(self) -> None:
        nested: object = None
        for _ in range(desired_state.MAX_JSON_DEPTH):
            nested = [nested]
        cases = (
            b" " * (desired_state.MAX_DOCUMENT_BYTES + 1),
            json.dumps(
                {
                    "schema_version": 1,
                    "capabilities": {"bash": {"provider": nested}},
                }
            ).encode(),
            json.dumps(
                {
                    "schema_version": 1,
                    "capabilities": {
                        f"future-{index}": {}
                        for index in range(desired_state.MAX_CAPABILITIES + 1)
                    },
                }
            ).encode(),
            json.dumps(
                {
                    "schema_version": 1,
                    "capabilities": {
                        "x" * (desired_state.MAX_IDENTITY_LENGTH + 1): {}
                    },
                }
            ).encode(),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for raw in cases:
                with self.subTest(size=len(raw)):
                    path.write_bytes(raw)
                    with self.assertRaises(desired_state.DesiredStateError):
                        desired_state.load_document(path)
                    self.assertEqual(path.read_bytes(), raw)

    def test_descriptor_io_failures_are_normalized(self) -> None:
        raw = b'{"schema_version":1,"capabilities":{}}'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            for operation in ("fstat", "read"):
                with (
                    self.subTest(operation=operation),
                    patch.object(
                        desired_state.os,
                        operation,
                        side_effect=OSError(f"injected {operation} failure"),
                    ),
                    self.assertRaisesRegex(
                        desired_state.DesiredStateError, "unreadable"
                    ),
                ):
                    desired_state.load_document(path)
            actual_close = desired_state.os.close

            def close_then_fail(descriptor: int) -> None:
                actual_close(descriptor)
                raise OSError("injected close failure")

            with (
                patch.object(desired_state.os, "close", side_effect=close_then_fail),
                self.assertRaisesRegex(desired_state.DesiredStateError, "unreadable"),
            ):
                desired_state.load_document(path)
            self.assertEqual(path.read_bytes(), raw)

    def test_pathname_integrity_rejects_regular_file_alternatives(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text('{"schema_version":1,"capabilities":{}}')
            for name, make in (
                ("symlink", lambda path: path.symlink_to(target)),
                ("dangling", lambda path: path.symlink_to(root / "missing")),
                ("directory", lambda path: path.mkdir()),
            ):
                with self.subTest(name=name):
                    path = root / name
                    make(path)
                    with self.assertRaisesRegex(
                        desired_state.DesiredStateError, "ordinary regular file"
                    ):
                        desired_state.load_document(path)
                    self.assertTrue(path.is_symlink() or path.is_dir())

    def test_changed_request_requires_authority_but_noop_does_not(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            refused = desired_state.set_capability(
                "bash", enabled=True, path=path, machine=LINUX
            )
            self.assertIs(refused.outcome, desired_state.DesiredMutationOutcome.REFUSED)
            self.assertFalse(path.exists())

            updated = desired_state.set_capability(
                "bash",
                enabled=True,
                allow_config_mutation=True,
                path=path,
                machine=LINUX,
            )
            unchanged = desired_state.set_capability(
                "bash", enabled=True, path=path, machine=LINUX
            )
            self.assertIs(updated.outcome, desired_state.DesiredMutationOutcome.UPDATED)
            self.assertIs(unchanged.outcome, desired_state.DesiredMutationOutcome.NO_CHANGES)
            self.assertIsNone(updated.backup_path)
            self.assertEqual(list(path.parent.glob("config.json.backup-*")), [])

    def test_new_configuration_ancestors_receive_durability_syncs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "new-config-root" / "agent-tools" / "config.json"
            synced: list[Path] = []
            with patch.object(
                desired_state, "_sync_directory", side_effect=synced.append
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(synced, [path.parent, path.parent.parent, root])

    def test_failed_partial_backup_is_removed_after_descriptor_closes(self) -> None:
        raw = b'{"schema_version":1,"capabilities":{}}'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            with (
                patch.object(
                    desired_state,
                    "_write_all",
                    side_effect=OSError("injected partial write"),
                ),
                self.assertRaises(desired_state.DesiredStateError),
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(list(path.parent.glob("config.json.backup-*")), [])

    def test_failed_temporary_write_discards_its_partial_entry(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with (
                patch.object(
                    desired_state.os,
                    "fsync",
                    side_effect=OSError("injected temporary sync failure"),
                ),
                self.assertRaises(OSError),
            ):
                desired_state._prepare_temporary(
                    path, b'{"schema_version":1,"capabilities":{}}'
                )
            self.assertEqual(list(path.parent.glob(".config.json.*")), [])

    def test_existing_bytes_are_backed_up_and_unrelated_entries_survive_changes(self) -> None:
        raw = b'{ "schema_version": 1, "capabilities": {"future": {}} }\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            result = desired_state.set_capability(
                "bash",
                enabled=True,
                provider_id="system-bash",
                allow_config_mutation=True,
                path=path,
                machine=LINUX,
            )
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(result.backup_path.read_bytes(), raw)
            self.assertEqual(
                desired_state.load_document(path)["capabilities"],
                {"bash": {"provider": "system-bash"}, "future": {}},
            )
            disabled = desired_state.set_capability(
                "bash",
                enabled=False,
                allow_config_mutation=True,
                path=path,
                machine=LINUX,
            )
            self.assertEqual(
                desired_state.load_document(path)["capabilities"], {"future": {}}
            )
            self.assertIsNotNone(disabled.backup_path)

    def test_backup_allocation_never_overwrites_a_collision(self) -> None:
        raw = b'{"schema_version":1,"capabilities":{}}'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            collision = path.with_name("config.json.backup-STAMP")
            collision.write_bytes(b"preserve me")
            with patch.object(desired_state, "datetime") as clock:
                clock.now.return_value.strftime.return_value = "STAMP"
                result = desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(collision.read_bytes(), b"preserve me")
            self.assertEqual(result.backup_path.name, "config.json.backup-STAMP-1")
            self.assertEqual(result.backup_path.read_bytes(), raw)

    def test_failure_before_replace_preserves_original_and_recovery_backup(self) -> None:
        raw = b'{"schema_version":1,"capabilities":{}}\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            with (
                patch.object(desired_state.os, "replace", side_effect=OSError("denied")),
                self.assertRaisesRegex(desired_state.DesiredStateError, "before replacement"),
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(path.read_bytes(), raw)
            backups = list(path.parent.glob("config.json.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), raw)

    def test_post_replace_validation_failure_restores_existing_bytes(self) -> None:
        raw = b'{ "schema_version": 1, "capabilities": {} }\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            actual_snapshot = desired_state._snapshot
            target_reads = 0

            def fail_result_validation(candidate: Path):
                nonlocal target_reads
                if candidate == path:
                    target_reads += 1
                    if target_reads == 4:
                        raise desired_state.DesiredStateError("injected postwrite failure")
                return actual_snapshot(candidate)

            with (
                patch.object(desired_state, "_snapshot", side_effect=fail_result_validation),
                self.assertRaisesRegex(desired_state.DesiredStateError, "previous state restored"),
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(path.read_bytes(), raw)

    def test_post_replace_failure_restores_confirmed_initial_absence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            actual_snapshot = desired_state._snapshot
            target_reads = 0

            def fail_result_validation(candidate: Path):
                nonlocal target_reads
                if candidate == path:
                    target_reads += 1
                    if target_reads == 4:
                        raise desired_state.DesiredStateError("injected postwrite failure")
                return actual_snapshot(candidate)

            with (
                patch.object(desired_state, "_snapshot", side_effect=fail_result_validation),
                self.assertRaisesRegex(desired_state.DesiredStateError, "previous state restored"),
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertFalse(path.exists())

    def test_first_sigint_after_replace_cooperatively_restores_prior_bytes(self) -> None:
        raw = b'{ "schema_version": 1, "capabilities": {} }\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            actual_replace = desired_state.os.replace
            replacement_count = 0

            def replace_then_interrupt(source: Path, destination: Path) -> None:
                nonlocal replacement_count
                actual_replace(source, destination)
                replacement_count += 1
                if replacement_count == 1:
                    signal.raise_signal(signal.SIGINT)

            previous = signal.getsignal(signal.SIGINT)
            try:
                signal.signal(signal.SIGINT, signal.default_int_handler)
                with (
                    patch.object(
                        desired_state.os,
                        "replace",
                        side_effect=replace_then_interrupt,
                    ),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    desired_state.set_capability(
                        "bash",
                        enabled=True,
                        allow_config_mutation=True,
                        path=path,
                        machine=LINUX,
                    )
            finally:
                signal.signal(signal.SIGINT, previous)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(replacement_count, 2)

    def test_restoration_failure_reports_uncertainty_and_backup(self) -> None:
        raw = b'{"schema_version":1,"capabilities":{}}\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(raw)
            actual_snapshot = desired_state._snapshot
            target_reads = 0

            def fail_result_validation(candidate: Path):
                nonlocal target_reads
                if candidate == path:
                    target_reads += 1
                    if target_reads == 4:
                        raise desired_state.DesiredStateError("injected postwrite failure")
                return actual_snapshot(candidate)

            with (
                patch.object(desired_state, "_snapshot", side_effect=fail_result_validation),
                patch.object(desired_state, "_restore", side_effect=OSError("restore denied")),
                self.assertRaises(desired_state.DesiredStateRestorationError) as raised,
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertIsNotNone(raised.exception.backup_path)
            self.assertEqual(raised.exception.backup_path.read_bytes(), raw)
            self.assertIn("uncertain", str(raised.exception))

    def test_concurrent_source_change_is_not_overwritten(self) -> None:
        original = b'{"schema_version":1,"capabilities":{}}\n'
        external = b'{"schema_version":1,"capabilities":{"future":{}}}\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(original)
            actual_prepare = desired_state._prepare_temporary

            def change_source(candidate: Path, raw: bytes) -> Path:
                temporary = actual_prepare(candidate, raw)
                path.write_bytes(external)
                return temporary

            with (
                patch.object(desired_state, "_prepare_temporary", side_effect=change_source),
                self.assertRaisesRegex(desired_state.DesiredStateError, "before replacement"),
            ):
                desired_state.set_capability(
                    "bash",
                    enabled=True,
                    allow_config_mutation=True,
                    path=path,
                    machine=LINUX,
                )
            self.assertEqual(path.read_bytes(), external)

    def test_requests_are_limited_to_supported_optional_capabilities(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            cases = (
                ("unknown", True, None, LINUX),
                ("poppler", True, None, LINUX),
                ("bash", True, "git-bash", LINUX),
                ("bash", True, "wsl-bash", WINDOWS),
                ("bash", True, "unknown-provider", LINUX),
            )
            for capability_id, enabled, provider_id, machine in cases:
                with self.subTest(capability=capability_id, provider=provider_id):
                    with self.assertRaises(desired_state.DesiredStateError):
                        desired_state.set_capability(
                            capability_id,
                            enabled=enabled,
                            provider_id=provider_id,
                            allow_config_mutation=True,
                            path=path,
                            machine=machine,
                        )
                    self.assertFalse(path.exists())

    def test_unknown_shaped_entry_is_preserved_but_not_silently_consumed(self) -> None:
        document = {
            "schema_version": 1,
            "capabilities": {"future-capability": {}},
        }
        with self.assertRaisesRegex(
            desired_state.DesiredStateError, "unsupported by this Agent Tools version"
        ):
            desired_state.desired_capabilities(document, LINUX)

    def test_interpreted_preferences_remain_distinct_from_enablement(self) -> None:
        document = {
            "schema_version": 1,
            "capabilities": {
                "bash": {"provider": "system-bash"},
            },
        }
        desired = desired_state.desired_capabilities(document, LINUX)
        self.assertEqual(
            desired,
            (desired_state.DesiredCapability("bash", "system-bash"),),
        )
        self.assertEqual(desired_state.provider_preferences(desired), {"bash": "system-bash"})


if __name__ == "__main__":
    unittest.main()
