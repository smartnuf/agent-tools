import unittest

from scripts.select_native_integration import requires_native


class NativeIntegrationSelectionTests(unittest.TestCase):
    def test_selects_native_product_and_workflow_changes(self) -> None:
        for path in (
            "src/agent_tools/capabilities.py",
            "src/agent_tools/native_setup.py",
            "scripts/bootstrap.ps1",
            ".github/actions/install-native/action.yml",
            ".github/workflows/native-integration.yml",
            "tests/check_preseeded_selection.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(requires_native([path]))

    def test_skips_unrelated_changes(self) -> None:
        self.assertFalse(requires_native(["README.md", "docs/packaging.md"]))

    def test_any_relevant_path_selects_native(self) -> None:
        self.assertTrue(requires_native(["README.md", "tests/test_capabilities.py"]))

    def test_selects_packaged_bootstrap_orchestration_tests(self) -> None:
        self.assertTrue(requires_native(["tests/test_native_setup.py"]))


if __name__ == "__main__":
    unittest.main()
