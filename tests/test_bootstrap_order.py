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


if __name__ == "__main__":
    unittest.main()
