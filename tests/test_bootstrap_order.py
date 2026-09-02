import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapOrderTests(unittest.TestCase):
    def test_powershell_verifies_environment_before_native_mutation(self) -> None:
        script = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertLess(
            script.index("--verify-final"),
            script.index("agent_tools.native_setup"),
        )

    def test_posix_verifies_environment_before_native_mutation(self) -> None:
        script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertLess(
            script.index("--verify-final"),
            script.index("agent_tools.native_setup"),
        )

    def test_both_wrappers_delegate_native_setup_with_explicit_arguments(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        expected = "agent_tools.native_setup"
        for script in (powershell, posix):
            with self.subTest(script=script[:20]):
                self.assertEqual(script.count(expected), 1)
                self.assertIn("--allow-provider-mutation poppler ghostscript", script)
        self.assertLess(powershell.index("uv pip install"), powershell.index(expected))
        self.assertLess(posix.index("uv pip install"), posix.index(expected))

    def test_clone_wrappers_have_no_native_package_mapping(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        combined = powershell + posix
        for duplicate in (
            "oschwartz10612.Poppler",
            "ArtifexSoftware.GhostScript",
            "poppler-utils",
            "brew install poppler",
            "apt-get install",
        ):
            with self.subTest(duplicate=duplicate):
                self.assertNotIn(duplicate, combined)
        self.assertFalse((ROOT / "scripts" / "install-native.sh").exists())
        self.assertFalse((ROOT / "scripts" / "windows-tools.ps1").exists())

    def test_native_delegation_does_not_bypass_explicit_path_flag(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertLess(powershell.index("agent_tools.native_setup"), powershell.index("if ($AddToPath)"))
        self.assertLess(posix.index("agent_tools.native_setup"), posix.index('if [ "$ADD_PATH" -eq 1 ]'))

    def test_uv_system_filter_is_neutralized_on_both_platforms(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("'UV_SYSTEM_PYTHON'", powershell)
        self.assertIn("-u UV_SYSTEM_PYTHON", posix)

    def test_both_wrappers_can_launch_from_inactive_manager_runtime(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("PYENV_ROOT", powershell)
        self.assertIn('$1"/*/bin/python3.11', posix)

    def test_inactive_conda_and_bounded_probes_are_present_on_both_platforms(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("CONDA_ENVS_PATH", powershell)
        self.assertIn("CONDA_ENVS_PATH", posix)
        self.assertIn("WaitForExit(10000)", powershell)
        self.assertIn("sleep 10", posix)
        self.assertIn("CondaBaseRoots", powershell)
        self.assertIn("probe_conda_base", posix)

    def test_selector_launches_are_isolated_and_native_errors_allow_fallback(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("$PSNativeCommandUseErrorActionPreference = $false", powershell)
        self.assertGreaterEqual(powershell.count("$BootstrapPython -I"), 2)
        self.assertGreaterEqual(posix.count('"$BOOTSTRAP_PYTHON" -I'), 4)

    def test_existing_damaged_environment_fails_closed_and_posix_timeout_escalates(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("Existing .venv is damaged or incomplete", powershell)
        self.assertIn("Existing .venv is damaged or incomplete", posix)
        self.assertIn('kill -KILL "$PROBE_PID"', posix)

    def test_conda_registered_prefixes_are_consulted_on_both_platforms(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("environments.txt", powershell)
        self.assertIn("environments.txt", posix)


if __name__ == "__main__":
    unittest.main()
