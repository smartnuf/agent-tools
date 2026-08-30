import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapOrderTests(unittest.TestCase):
    def test_powershell_verifies_environment_before_native_mutation(self) -> None:
        script = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertLess(
            script.index("--verify-final"),
            script.index("if ($InstallNativeTools)"),
        )

    def test_posix_verifies_environment_before_native_mutation(self) -> None:
        script = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertLess(
            script.index("--verify-final"),
            script.index('if [ "$INSTALL_NATIVE" -eq 1 ]'),
        )

    def test_uv_system_filter_is_neutralized_on_both_platforms(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("'UV_SYSTEM_PYTHON'", powershell)
        self.assertIn("-u UV_SYSTEM_PYTHON", posix)

    def test_both_wrappers_can_launch_from_inactive_manager_runtime(self) -> None:
        powershell = (ROOT / "scripts" / "bootstrap.ps1").read_text(encoding="utf-8")
        posix = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("PYENV_ROOT", powershell)
        self.assertIn('$MANAGER_ROOT"/*/bin/python3.11', posix)


if __name__ == "__main__":
    unittest.main()
