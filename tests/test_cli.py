import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from agent_tools import capabilities, cli


class CliTests(unittest.TestCase):
    def test_parser_requires_command(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_doctor_command_dispatches(self) -> None:
        with patch.object(cli, "doctor", return_value=0) as doctor:
            self.assertEqual(cli.main(["doctor"]), 0)
            doctor.assert_called_once_with()

    def test_tools_commands_dispatch(self) -> None:
        with patch.object(cli, "tools_list", return_value=0) as tools_list:
            self.assertEqual(cli.main(["tools", "list"]), 0)
        tools_list.assert_called_once_with()
        with patch.object(cli, "tools_status", return_value=1) as tools_status:
            self.assertEqual(cli.main(["tools", "status", "bash"]), 1)
        tools_status.assert_called_once_with("bash")

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
            self.assertEqual(cli._application_version(), "0.1.2")

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
            patch.object(capabilities.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            patch.object(capabilities, "read_executable_version", return_value="1.2.3"),
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
            patch.object(capabilities.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            patch.object(capabilities, "read_executable_version", return_value="1.2.3"),
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
            patch.object(capabilities, "locate_executable", return_value=None),
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
            patch.object(capabilities.shutil, "which", side_effect=find_executable),
            patch.object(capabilities, "read_executable_version", return_value="1.2.3"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        self.assertIn("missing required executable(s): pdftotext, pdftoppm", output.getvalue())

    def test_doctor_distinguishes_failed_verification_from_missing(self) -> None:
        def version(probe: capabilities.ExecutableProbe, path: str) -> str | None:
            return None if probe.name == "pdftotext" else "1.2.3"

        with (
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module"),
            patch.object(
                capabilities.shutil, "which", side_effect=lambda name: f"/tools/{name}"
            ),
            patch.object(capabilities, "read_executable_version", side_effect=version),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        text = output.getvalue()
        self.assertIn(
            "version verification failed: pdftotext: /tools/pdftotext", text
        )
        self.assertNotIn("missing required executable(s): pdftotext", text)

    def test_doctor_reports_package_import_failures(self) -> None:
        with (
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module", side_effect=OSError("incompatible ABI")),
            patch.object(capabilities.shutil, "which", side_effect=lambda name: f"/tools/{name}"),
            patch.object(capabilities, "read_executable_version", return_value="1.2.3"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.doctor(), 1)
        self.assertIn("import failed: OSError: incompatible ABI", output.getvalue())
        self.assertIn("7 check(s) need attention.", output.getvalue())

    def test_doctor_does_not_probe_optional_bash(self) -> None:
        def locate(
            probe: capabilities.ExecutableProbe, machine: capabilities.MachineState
        ) -> str | None:
            self.assertNotIn(probe.locator_strategy, {"git-bash", "system-bash", "wsl-bash"})
            return f"/tools/{probe.name}"

        with (
            patch.object(cli, "_distribution_version", return_value="1.2.3"),
            patch.object(cli.importlib, "import_module"),
            patch.object(capabilities, "locate_executable", side_effect=locate),
            patch.object(capabilities, "read_executable_version", return_value="1.2.3"),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(cli.doctor(), 0)

    def test_tools_list_is_catalogue_only(self) -> None:
        with (
            patch.object(capabilities, "locate_executable", side_effect=AssertionError),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.tools_list(), 0)
        text = output.getvalue()
        self.assertIn("poppler", text)
        self.assertIn("ghostscript", text)
        self.assertIn("bash", text)
        self.assertIn("git-bash, system-bash, wsl-bash", text)

    def test_tools_status_reports_windows_git_bash(self) -> None:
        def locate(
            probe: capabilities.ExecutableProbe, machine: capabilities.MachineState
        ) -> str | None:
            return "C:/Git/bin/bash.exe" if probe.locator_strategy == "git-bash" else None

        with (
            patch.object(
                capabilities,
                "current_machine",
                return_value=capabilities.MachineState("Windows", "ARM64"),
            ),
            patch.object(capabilities, "locate_executable", side_effect=locate),
            patch.object(
                capabilities, "read_executable_version", return_value="GNU bash, version 5.2"
            ),
            patch.object(capabilities, "read_executable_architecture", return_value="x86_64"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.tools_status("bash"), 0)
        text = output.getvalue()
        self.assertIn("bash: available (optional)", text)
        self.assertIn("git-bash: available", text)
        self.assertIn("environment: windows-host", text)
        self.assertIn("executable: C:/Git/bin/bash.exe", text)
        self.assertIn("version: GNU bash, version 5.2", text)
        self.assertIn("architecture: x86_64", text)

    def test_tools_status_reports_wsl_without_satisfying_host(self) -> None:
        def locate(
            probe: capabilities.ExecutableProbe, machine: capabilities.MachineState
        ) -> str | None:
            return "C:/Windows/System32/wsl.exe" if probe.locator_strategy == "wsl-bash" else None

        with (
            patch.object(
                capabilities,
                "current_machine",
                return_value=capabilities.MachineState("Windows", "AMD64"),
            ),
            patch.object(capabilities, "locate_executable", side_effect=locate),
            patch.object(
                capabilities, "read_executable_version", return_value="GNU bash, version 5.1"
            ),
            patch.object(capabilities, "read_executable_architecture", return_value="x86_64"),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.tools_status("bash"), 1)
        text = output.getvalue()
        self.assertIn("bash: absent (optional)", text)
        self.assertIn("wsl-bash: available", text)
        self.assertIn("environment: wsl", text)
        self.assertIn("does not satisfy the host capability", text)

    def test_tools_status_distinguishes_unsupported_and_unknown(self) -> None:
        with (
            patch.object(
                capabilities,
                "current_machine",
                return_value=capabilities.MachineState("Plan9", "mips"),
            ),
            redirect_stdout(StringIO()) as output,
        ):
            self.assertEqual(cli.tools_status("bash"), 2)
        self.assertIn("bash: unsupported", output.getvalue())

        with redirect_stderr(StringIO()) as error:
            self.assertEqual(cli.tools_status("unknown"), 2)
        self.assertIn("unknown capability: unknown", error.getvalue())

    def test_distribution_version_tries_all_owning_distributions(self) -> None:
        with (
            patch.object(
                cli.importlib.metadata,
                "packages_distributions",
                return_value={"pymupdf": [None, "", "missing", "PyMuPDF"]},
            ),
            patch.object(
                cli.importlib.metadata,
                "version",
                side_effect=[cli.importlib.metadata.PackageNotFoundError, "9.9"],
            ),
        ):
            self.assertEqual(cli._distribution_version("pymupdf"), "9.9")

    def test_distribution_version_reports_invalid_or_missing_metadata(self) -> None:
        for distributions in ([None], [], None):
            with self.subTest(distributions=distributions):
                mapping = {} if distributions is None else {"pypdf": distributions}
                with (
                    patch.object(
                        cli.importlib.metadata,
                        "packages_distributions",
                        return_value=mapping,
                    ),
                    patch.object(
                        cli.importlib.metadata,
                        "version",
                        side_effect=cli.importlib.metadata.PackageNotFoundError,
                    ) as version,
                ):
                    self.assertEqual(cli._distribution_version("pypdf"), "not installed")
                if distributions is None:
                    version.assert_called_once_with("pypdf")
                else:
                    version.assert_not_called()


if __name__ == "__main__":
    unittest.main()
