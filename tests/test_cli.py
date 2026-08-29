import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from agent_tools import cli


class CliTests(unittest.TestCase):
    def test_parser_requires_command(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_doctor_command_dispatches(self) -> None:
        with patch.object(cli, "doctor", return_value=0) as doctor:
            self.assertEqual(cli.main(["doctor"]), 0)
            doctor.assert_called_once_with()

    def test_version_prefers_installed_distribution_metadata(self) -> None:
        with patch.object(cli.importlib.metadata, "version", return_value="2.3.4") as version:
            self.assertEqual(cli._application_version(), "2.3.4")
        version.assert_called_once_with("smartnuf-agent-tools")

    def test_version_falls_back_for_uninstalled_source(self) -> None:
        with patch.object(
            cli.importlib.metadata,
            "version",
            side_effect=cli.importlib.metadata.PackageNotFoundError,
        ):
            self.assertEqual(cli._application_version(), "0.1.0")

    def test_version_option_reports_application_version(self) -> None:
        with (
            patch.object(cli, "_application_version", return_value="2.3.4"),
            redirect_stdout(StringIO()) as output,
            self.assertRaises(SystemExit) as raised,
        ):
            cli.build_parser().parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), "agent-tools 2.3.4\n")

    def test_doctor_passes_when_packages_and_native_tools_exist(self) -> None:
        checkout = Path("/checkout")
        with (
            patch.object(cli, "_checkout_root", return_value=checkout),
            patch.object(cli, "_application_version", return_value="2.3.4"),
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module"),
            patch.object(cli.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 0)
        text = output.getvalue()
        self.assertIn("mode:       checkout", text)
        self.assertIn(f"repository: {checkout}", text)
        self.assertIn("agent-tools: 2.3.4", text)
        self.assertIn("All checks passed.", text)

    def test_doctor_labels_installed_package_without_repository_claim(self) -> None:
        with (
            patch.object(cli, "_checkout_root", return_value=None),
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module"),
            patch.object(cli.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 0)
        text = output.getvalue()
        self.assertIn("mode:       installed", text)
        self.assertIn("package:", text)
        self.assertNotIn("repository:", text)

    def test_checkout_root_requires_repository_markers(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "src" / "agent_tools" / "cli.py"
            module.parent.mkdir(parents=True)
            module.touch()
            self.assertIsNone(cli._checkout_root(module))
            (root / "pyproject.toml").touch()
            (root / "bin").mkdir()
            (root / "scripts").mkdir()
            self.assertEqual(cli._checkout_root(module), root.resolve())

    def test_doctor_reports_every_unavailable_requirement(self) -> None:
        with (
            patch.object(cli, "_distribution_version", return_value="not installed"),
            patch.object(cli.importlib, "import_module", side_effect=ModuleNotFoundError("unavailable")),
            patch.object(cli, "_find_executable", return_value=None),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        text = output.getvalue()
        self.assertIn("pypdf", text)
        self.assertIn("Poppler", text)
        self.assertIn("Ghostscript", text)
        self.assertIn("9 check(s) need attention.", text)

    def test_doctor_rejects_partial_poppler_installation(self) -> None:
        def find_executable(name: str) -> str | None:
            return f"/tools/{name}" if name in {"pdfinfo", "gs"} else None

        with (
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module"),
            patch.object(cli.shutil, "which", side_effect=find_executable),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        self.assertIn("missing required executable(s): pdftotext, pdftoppm", output.getvalue())

    def test_doctor_reports_package_import_failures(self) -> None:
        with (
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module", side_effect=OSError("incompatible ABI")),
            patch.object(cli.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        self.assertIn("import failed: OSError: incompatible ABI", output.getvalue())
        self.assertIn("7 check(s) need attention.", output.getvalue())

    def test_windows_ghostscript_is_discovered_outside_path(self) -> None:
        with TemporaryDirectory() as program_files:
            executable = Path(program_files, "gs", "10.06.0", "bin", "gswin64c.exe")
            executable.parent.mkdir(parents=True)
            executable.touch()
            old_executable = Path(program_files, "gs", "9.56.1", "bin", "gswin64c.exe")
            old_executable.parent.mkdir(parents=True)
            old_executable.touch()
            with (
                patch.object(cli.shutil, "which", return_value=None),
                patch.object(cli.platform, "system", return_value="Windows"),
                patch.dict(cli.os.environ, {"ProgramFiles": program_files}, clear=True),
            ):
                self.assertEqual(cli._find_executable("gswin64c"), str(executable))

    def test_distribution_version_tries_all_owning_distributions(self) -> None:
        with (
            patch.object(cli.importlib.metadata, "packages_distributions", return_value={"pymupdf": ["missing", "PyMuPDF"]}),
            patch.object(
                cli.importlib.metadata,
                "version",
                side_effect=[cli.importlib.metadata.PackageNotFoundError, "9.9"],
            ),
        ):
            self.assertEqual(cli._distribution_version("pymupdf"), "9.9")


if __name__ == "__main__":
    unittest.main()
