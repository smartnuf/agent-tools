import json
import os
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

    def test_rosetta_translation_identifies_arm64_host(self) -> None:
        with (
            patch.object(selection.platform, "system", return_value="Darwin"),
            patch.object(selection.platform, "machine", return_value="x86_64"),
            patch.object(selection, "_macos_process_translated", return_value=True),
            patch.object(selection, "_unix_kernel_architecture", return_value="x86_64"),
        ):
            host = selection.current_host()
        self.assertEqual(host.architecture, "arm64")
        self.assertEqual(host.process_architecture, "x86_64")
        self.assertTrue(host.process_translated)

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

    def test_prerelease_is_not_compatible(self) -> None:
        prerelease = selection.PythonCandidate(
            "C:/Python311/python.exe",
            (3, 11, 0),
            "arm64",
            selection.ProviderMechanism.SYSTEM,
            release_level="candidate",
        )
        with self.assertRaisesRegex(selection.SelectionError, "no compatible"):
            selection.select_python((prerelease,), self.host)

    def test_uv_discovery_is_installed_only_and_downloads_disabled(self) -> None:
        completed = subprocess.CompletedProcess([], 0, '[{"path":"/python"}]', "")
        with (
            patch.dict(
                selection.os.environ,
                {"UV_MANAGED_PYTHON": "1", "UV_NO_MANAGED_PYTHON": "1"},
                clear=True,
            ),
            patch.object(selection.subprocess, "run", return_value=completed) as run,
        ):
            records = selection.discover_with_uv()
        self.assertEqual(records[0]["agent_tools_mechanism"], "tool-managed")
        command = run.call_args_list[0].args[0]
        self.assertIn("--only-installed", command)
        self.assertIn("--no-python-downloads", command)
        self.assertIn("--no-config", command)
        self.assertIn("--managed-python", run.call_args_list[1].args[0])
        for call in run.call_args_list:
            self.assertNotIn("UV_MANAGED_PYTHON", call.kwargs["env"])
            self.assertNotIn("UV_NO_MANAGED_PYTHON", call.kwargs["env"])

    def test_verify_candidate_uses_executed_facts(self) -> None:
        facts = {
            "path": str(Path("C:/Python311/python.exe")),
            "version": [3, 11, 9],
            "release_level": "final",
            "architecture": "ARM64",
            "implementation": "CPython",
            "base_path": str(Path("C:/Python311/python.exe")),
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(facts), "")
        with patch.object(selection.subprocess, "run", return_value=completed):
            verified = selection.verify_candidate({"path": "C:/WindowsApps/python.exe"})
        self.assertIsNotNone(verified)
        assert verified is not None
        self.assertEqual(verified.version, (3, 11, 9))
        self.assertEqual(verified.architecture, "arm64")
        self.assertEqual(verified.mechanism, selection.ProviderMechanism.SYSTEM)
        self.assertEqual(verified.release_level, "final")

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
        matching = selection.PythonCandidate(
            "C:/venv/python.exe", (3, 11, 9), "arm64", selection.ProviderMechanism.SYSTEM,
            base_path=selected.path,
        )
        wrong_base = selection.PythonCandidate(
            "C:/venv/python.exe", (3, 11, 9), "arm64", selection.ProviderMechanism.SYSTEM,
            base_path="C:/uv/python/python.exe",
        )
        with patch.object(selection, "verify_candidate", return_value=matching):
            selection.verify_final_environment("C:/venv/python.exe", selected)
        with patch.object(selection, "verify_candidate", return_value=wrong_base):
            with self.assertRaisesRegex(selection.SelectionError, "does not match"):
                selection.verify_final_environment("C:/venv/python.exe", selected)

    def test_direct_preference_is_verified_even_when_uv_omits_it(self) -> None:
        direct = candidate(
            str((Path.cwd() / "custom-python" / "python").resolve()),
            "arm64",
            selection.ProviderMechanism.SYSTEM,
        )
        with (
            patch.object(selection, "current_host", return_value=self.host),
            patch.object(selection, "discover_with_uv", return_value=()),
            patch.object(selection, "verify_candidate", return_value=direct) as verify,
        ):
            _, _, selected = selection.discover_verify_select(preferred_path=direct.path)
        self.assertIs(selected, direct)
        self.assertEqual(verify.call_args.args[0]["path"], direct.path)

    def test_direct_alias_reuses_discovered_mechanism_evidence(self) -> None:
        managed = candidate(
            str((Path.cwd() / "managed-python" / "python").resolve()),
            "arm64",
            selection.ProviderMechanism.TOOL_MANAGED,
        )
        alias = candidate(
            managed.path, "arm64", selection.ProviderMechanism.SYSTEM
        )
        with (
            patch.object(selection, "current_host", return_value=self.host),
            patch.object(selection, "discover_with_uv", return_value=({"path": managed.path},)),
            patch.object(selection, "verified_candidates", return_value=(managed,)),
            patch.object(selection, "verify_candidate", return_value=alias),
        ):
            _, candidates, selected = selection.discover_verify_select(
                preferred_path=str((Path.cwd() / "python-alias").resolve())
            )
        self.assertEqual(candidates, (managed,))
        self.assertIs(selected, managed)

    def test_direct_alias_rejects_conflicting_runtime_evidence(self) -> None:
        managed = candidate(
            str((Path.cwd() / "managed-python" / "python").resolve()),
            "arm64",
            selection.ProviderMechanism.TOOL_MANAGED,
        )
        changed = candidate(
            managed.path,
            "x86_64",
            selection.ProviderMechanism.SYSTEM,
        )
        with (
            patch.object(selection, "current_host", return_value=self.host),
            patch.object(selection, "discover_with_uv", return_value=({"path": managed.path},)),
            patch.object(selection, "verified_candidates", return_value=(managed,)),
            patch.object(selection, "verify_candidate", return_value=changed),
        ):
            with self.assertRaisesRegex(selection.SelectionError, "conflicting direct evidence"):
                selection.discover_verify_select(preferred_path="python-alias")

    def test_cross_environment_interpreter_is_rejected(self) -> None:
        facts = {
            "path": "C:/Python311/python.exe",
            "version": [3, 11, 9],
            "release_level": "final",
            "architecture": "AMD64",
            "implementation": "CPython",
            "base_path": "C:/Python311/python.exe",
            "system": "Windows",
            "release": "11",
            "wsl": False,
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(facts), "")
        with (
            patch.object(selection.platform, "system", return_value="Linux"),
            patch.object(selection.subprocess, "run", return_value=completed),
        ):
            verified = selection.verify_candidate({"path": "python.exe"})
        assert verified is not None
        self.assertEqual(verified.execution_environment, "windows")
        wsl = selection.HostIdentity("Linux", "x86_64", "x86_64", False, "wsl")
        with self.assertRaisesRegex(selection.SelectionError, "no compatible"):
            selection.select_python((verified,), wsl)

    def test_inactive_manager_runtimes_are_added_to_uv_catalogue(self) -> None:
        root = (Path.cwd() / "pyenv-fixture").resolve()
        inactive = root / "versions" / "3.11.9" / "bin" / "python3.11"
        completed = subprocess.CompletedProcess([], 0, "[]", "")
        with (
            patch.dict(selection.os.environ, {"PYENV_ROOT": str(root)}, clear=True),
            patch.object(selection.subprocess, "run", return_value=completed),
            patch.object(selection.Path, "glob", return_value=iter((inactive,))),
            patch.object(selection.Path, "is_file", return_value=True),
        ):
            records = selection.discover_with_uv()
        self.assertIn(
            {"path": str(inactive), "agent_tools_mechanism": "tool-managed"},
            records,
        )

    def test_manager_enumeration_rejects_python_helper_names(self) -> None:
        root = (Path.cwd() / "pyenv-fixture").resolve()
        interpreter = root / "3.11.9" / "bin" / "python3.11"
        helper = root / "3.11.9" / "bin" / "python3.11-config"
        with (
            patch.dict(selection.os.environ, {"PYENV_ROOT": str(root.parent)}, clear=True),
            patch.object(selection.Path, "home", return_value=Path.cwd()),
            patch.object(
                selection.Path,
                "glob",
                return_value=iter((interpreter, helper)),
            ),
            patch.object(selection.Path, "is_file", return_value=True),
        ):
            records = selection._manager_python_records()
        self.assertEqual(tuple(item["path"] for item in records), (str(interpreter),))

    def test_conda_environment_roots_include_configured_and_standard_locations(self) -> None:
        home = (Path.cwd() / "home-fixture").resolve()
        first = (Path.cwd() / "conda-one").resolve()
        second = (Path.cwd() / "conda-two").resolve()
        with patch.dict(
            selection.os.environ,
            {"CONDA_ENVS_PATH": os.pathsep.join((str(first), str(second)))},
            clear=True,
        ):
            roots = selection._conda_environment_roots(home)
        self.assertIn(first, roots)
        self.assertIn(second, roots)
        self.assertIn(home / ".conda" / "envs", roots)

    def test_discovery_mechanism_evidence_controls_ranking(self) -> None:
        facts = {
            "path": "C:/managed/python.exe",
            "version": [3, 11, 9],
            "release_level": "final",
            "architecture": "arm64",
            "implementation": "CPython",
            "base_path": "C:/managed/python.exe",
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(facts), "")
        record = {"path": facts["path"], "agent_tools_mechanism": "tool-managed"}
        with patch.object(selection.subprocess, "run", return_value=completed):
            verified = selection.verify_candidate(record)
        assert verified is not None
        self.assertEqual(verified.mechanism, selection.ProviderMechanism.TOOL_MANAGED)

    def test_provider_specific_manager_root_is_not_classified_as_system(self) -> None:
        manager_root = (Path.cwd() / "pyenv-fixture").resolve()
        executable = manager_root / "versions" / "3.11.9" / "python"
        with (
            patch.dict(
                selection.os.environ,
                {"PYENV_ROOT": str(manager_root)},
                clear=True,
            ),
            patch.object(selection.Path, "home", return_value=Path.cwd()),
        ):
            mechanism = selection._provider_mechanism(
                {"agent_tools_mechanism": "system"}, str(executable)
            )
        self.assertEqual(mechanism, selection.ProviderMechanism.TOOL_MANAGED)

    def test_normalized_unknown_architecture_uses_unknown_class(self) -> None:
        unknown = candidate("C:/Python311/python.exe", "unknown", selection.ProviderMechanism.SYSTEM)
        self.assertEqual(unknown.native_status(self.host), selection.NativeStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
