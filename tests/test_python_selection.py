import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools import python_selection as selection


def candidate(
    path: str,
    architecture: str | None,
    mechanism: selection.ProviderMechanism,
    version: tuple[int, int, int] = (3, 11, 9),
) -> selection.PythonCandidate:
    return selection.PythonCandidate(path, version, architecture, mechanism)


class PythonSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = selection.HostIdentity("Windows", "arm64", "x86_64", True)

    def test_architecture_aliases_are_normalized_without_guessing(self) -> None:
        self.assertEqual(selection.normalize_architecture("AMD64"), "x86_64")
        self.assertEqual(selection.normalize_architecture("aarch64"), "arm64")
        self.assertEqual(selection.normalize_architecture(None), "unknown")
        self.assertEqual(selection.normalize_architecture("mips64"), "mips64")

    def test_emulated_bootstrap_does_not_redefine_host(self) -> None:
        with (
            patch.object(selection.platform, "system", return_value="Windows"),
            patch.object(selection.platform, "machine", return_value="AMD64"),
            patch.object(
                selection,
                "_windows_host_process_architectures",
                return_value=("x86_64", "arm64"),
            ),
        ):
            host = selection.current_host()
        self.assertEqual(host.architecture, "arm64")
        self.assertEqual(host.process_architecture, "x86_64")
        self.assertTrue(host.process_translated)

    def test_windows_unknown_process_machine_preserves_process_fallback(self) -> None:
        self.assertEqual(
            selection._windows_architectures(0, 0xAA64, "AMD64"),
            ("x86_64", "arm64"),
        )

    def test_native_system_python_beats_emulated_managed_python(self) -> None:
        native = candidate("C:/Python311-arm64/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        managed = candidate("C:/uv/python/python.exe", "x86_64", selection.ProviderMechanism.TOOL_MANAGED)
        self.assertIs(selection.select_python((managed, native), self.host), native)

    def test_installed_native_managed_beats_translated_system(self) -> None:
        native = candidate("C:/uv/python/python.exe", "arm64", selection.ProviderMechanism.TOOL_MANAGED)
        translated = candidate("C:/Python311/python.exe", "x86_64", selection.ProviderMechanism.SYSTEM)
        self.assertIs(selection.select_python((translated, native), self.host), native)

    def test_unknown_system_beats_native_managed_per_contract(self) -> None:
        unknown = candidate("C:/Python311/python.exe", None, selection.ProviderMechanism.SYSTEM)
        managed = candidate("C:/uv/python/python.exe", "arm64", selection.ProviderMechanism.TOOL_MANAGED)
        self.assertIs(selection.select_python((managed, unknown), self.host), unknown)

    def test_translated_fallback_requires_explicit_authorization(self) -> None:
        translated = candidate("C:/Python311/python.exe", "x86_64", selection.ProviderMechanism.SYSTEM)
        with self.assertRaisesRegex(selection.SelectionError, "explicit authorization"):
            selection.select_python((translated,), self.host)
        self.assertIs(
            selection.select_python((translated,), self.host, allow_translated=True),
            translated,
        )

    def test_preference_is_exact_and_never_silently_falls_back(self) -> None:
        native = candidate("C:/Python311/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        with self.assertRaisesRegex(selection.SelectionError, "preferred Python"):
            selection.select_python((native,), self.host, preferred_path="C:/missing/python.exe")

    def test_patch_and_path_ties_are_deterministic(self) -> None:
        old = candidate("C:/B/python.exe", "arm64", selection.ProviderMechanism.SYSTEM, (3, 11, 8))
        high_path = candidate("C:/B/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        low_path = candidate("C:/A/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        self.assertIs(selection.select_python((old, high_path, low_path), self.host), low_path)

    def test_incompatible_minor_and_environment_are_rejected(self) -> None:
        wrong_version = candidate(
            "C:/Python312/python.exe", "arm64", selection.ProviderMechanism.SYSTEM, (3, 12, 1)
        )
        wrong_environment = selection.PythonCandidate(
            "/usr/bin/python3", (3, 11, 9), "arm64", selection.ProviderMechanism.SYSTEM, "wsl"
        )
        with self.assertRaisesRegex(selection.SelectionError, "no compatible"):
            selection.select_python((wrong_version, wrong_environment), self.host)

    def test_uv_discovery_is_installed_only_and_downloads_disabled(self) -> None:
        completed = subprocess.CompletedProcess([], 0, '[{"path":"/python"}]', "")
        with patch.object(selection.subprocess, "run", return_value=completed) as run:
            self.assertEqual(selection.discover_with_uv(), ({"path": "/python"},))
        command = run.call_args.args[0]
        self.assertIn("--only-installed", command)
        self.assertIn("--no-python-downloads", command)
        self.assertIn("--no-config", command)

    def test_verify_candidate_uses_executed_facts(self) -> None:
        facts = {
            "path": str(Path("C:/Python311/python.exe")),
            "version": [3, 11, 9],
            "architecture": "ARM64",
            "implementation": "CPython",
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(facts), "")
        with patch.object(selection.subprocess, "run", return_value=completed):
            verified = selection.verify_candidate({"path": "C:/WindowsApps/python.exe"})
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(verified.version, (3, 11, 9))
        self.assertEqual(verified.architecture, "arm64")
        self.assertEqual(verified.mechanism, selection.ProviderMechanism.SYSTEM)

    def test_aliases_deduplicate_and_conflicting_evidence_fails(self) -> None:
        first = candidate("C:/Python311/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        second = candidate("C:/Python311/python.exe", "x86_64", selection.ProviderMechanism.SYSTEM)
        with patch.object(selection, "verify_candidate", side_effect=(first, first)):
            self.assertEqual(len(selection.verified_candidates(({"path": "a"}, {"path": "b"}))), 1)
        with patch.object(selection, "verify_candidate", side_effect=(first, second)):
            with self.assertRaisesRegex(selection.SelectionError, "conflicting evidence"):
                selection.verified_candidates(({"path": "a"}, {"path": "b"}))

    def test_unverified_candidates_are_ignored(self) -> None:
        with patch.object(selection, "verify_candidate", return_value=None):
            self.assertEqual(selection.verified_candidates(({"path": "bad"},)), ())

    def test_final_environment_must_match_selected_runtime(self) -> None:
        selected = candidate("C:/Python311/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        matching = candidate("C:/venv/python.exe", "arm64", selection.ProviderMechanism.SYSTEM)
        mismatch = candidate(
            "C:/venv/python.exe",
            "x86_64",
            selection.ProviderMechanism.SYSTEM,
        )
        with patch.object(selection, "verify_candidate", return_value=matching):
            selection.verify_final_environment("C:/venv/python.exe", selected)
        with patch.object(selection, "verify_candidate", return_value=mismatch):
            with self.assertRaisesRegex(selection.SelectionError, "does not match"):
                selection.verify_final_environment("C:/venv/python.exe", selected)


if __name__ == "__main__":
    unittest.main()
