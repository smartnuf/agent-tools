import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities


class CapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = capabilities.MachineState("Linux", "x86_64")

    def test_catalogue_has_stable_capability_order(self) -> None:
        self.assertEqual(
            tuple(item.capability_id for item in capabilities.CAPABILITY_CATALOGUE),
            ("poppler", "ghostscript", "bash"),
        )
        self.assertEqual(
            tuple(item.capability_id for item in capabilities.CAPABILITY_CATALOGUE if item.required_by_default),
            ("poppler", "ghostscript"),
        )
        self.assertIs(capabilities.get_capability("poppler"), capabilities.POPPLER)
        with self.assertRaises(KeyError):
            capabilities.get_capability("unknown")

    def test_bash_catalogue_separates_host_and_wsl_providers(self) -> None:
        self.assertFalse(capabilities.BASH.required_by_default)
        self.assertEqual(
            tuple(provider.provider_id for provider in capabilities.BASH.providers),
            ("git-bash", "system-bash", "wsl-bash"),
        )
        self.assertEqual(capabilities.BASH.providers[0].provided_environment, "windows-host")
        self.assertEqual(capabilities.BASH.providers[2].provided_environment, "wsl")
        self.assertEqual(capabilities.BASH.providers[2].label, "default WSL Bash")
        self.assertFalse(capabilities.BASH.providers[2].satisfies_capability)

    def test_windows_git_bash_is_preferred_and_reports_architecture(self) -> None:
        machine = capabilities.MachineState("Windows", "ARM64")

        def locate(probe: capabilities.ExecutableProbe, machine: capabilities.MachineState) -> str | None:
            return "C:/Git/bin/bash.exe" if probe.locator_strategy == "git-bash" else None

        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=locate,
            version_reader=lambda probe, path: "GNU bash, version 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )

        self.assertEqual(state.availability, capabilities.Availability.AVAILABLE)
        self.assertEqual(state.selected_provider.provider.provider_id, "git-bash")
        executable = state.selected_provider.executables[0]
        self.assertEqual(executable.version, "GNU bash, version 5.2")
        self.assertEqual(executable.architecture, "x86_64")

    def test_wsl_bash_is_reported_but_does_not_satisfy_windows_host(self) -> None:
        machine = capabilities.MachineState("Windows", "AMD64")

        def locate(probe: capabilities.ExecutableProbe, machine: capabilities.MachineState) -> str | None:
            return "C:/Windows/System32/wsl.exe" if probe.locator_strategy == "wsl-bash" else None

        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=locate,
            version_reader=lambda probe, path: "GNU bash, version 5.1",
            architecture_reader=lambda probe, path: "x86_64",
        )

        self.assertEqual(state.availability, capabilities.Availability.ABSENT)
        self.assertIsNone(state.selected_provider)
        wsl = next(provider for provider in state.providers if provider.provider.provider_id == "wsl-bash")
        self.assertEqual(wsl.availability, capabilities.Availability.AVAILABLE)

    def test_system_bash_satisfies_linux_host(self) -> None:
        state = capabilities.detect_capability(
            capabilities.BASH,
            self.machine,
            locator=lambda probe, machine: "/bin/bash",
            version_reader=lambda probe, path: "GNU bash, version 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        self.assertEqual(state.availability, capabilities.Availability.AVAILABLE)
        self.assertEqual(state.selected_provider.provider.provider_id, "system-bash")

    def test_detection_reports_verified_paths_and_versions(self) -> None:
        state = capabilities.detect_capability(
            capabilities.POPPLER,
            self.machine,
            locator=lambda probe, machine: f"/tools/{probe.name}",
            version_reader=lambda probe, path: f"{probe.name} 1.2.3",
        )

        self.assertEqual(state.availability, capabilities.Availability.AVAILABLE)
        provider = state.selected_provider
        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(
            tuple((item.path, item.version) for item in provider.executables),
            tuple((f"/tools/{name}", f"{name} 1.2.3") for name in ("pdfinfo", "pdftotext", "pdftoppm")),
        )

    def test_preseeded_required_providers_are_reused_repeatably(self) -> None:
        paths = {
            "pdfinfo": "/existing/poppler/pdfinfo",
            "pdftotext": "/existing/poppler/pdftotext",
            "pdftoppm": "/existing/poppler/pdftoppm",
            "gs": "/existing/ghostscript/gs",
        }
        locator = Mock(side_effect=lambda probe, machine: paths.get(probe.name))
        version_reader = Mock(side_effect=lambda probe, path: f"{probe.name} 1.2.3")

        first = capabilities.detect_capabilities(
            (capabilities.POPPLER, capabilities.GHOSTSCRIPT),
            self.machine,
            locator=locator,
            version_reader=version_reader,
        )
        second = capabilities.detect_capabilities(
            (capabilities.POPPLER, capabilities.GHOSTSCRIPT),
            self.machine,
            locator=locator,
            version_reader=version_reader,
        )

        self.assertEqual(first, second)
        self.assertTrue(
            all(state.availability is capabilities.Availability.AVAILABLE for state in first)
        )
        self.assertEqual(
            tuple(state.selected_provider.provider.provider_id for state in first),
            ("host-poppler", "host-ghostscript"),
        )
        self.assertEqual(locator.call_count, 12)
        self.assertEqual(version_reader.call_count, 8)

    def test_found_but_unverified_executable_does_not_satisfy_provider(self) -> None:
        state = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, machine: "/tools/gs" if probe.name == "gs" else None,
            version_reader=lambda probe, path: None,
        )

        self.assertEqual(state.availability, capabilities.Availability.ABSENT)
        provider = state.providers[0]
        self.assertEqual(provider.executables[0].path, "/tools/gs")
        self.assertIsNone(provider.executables[0].version)
        self.assertEqual(provider.missing_probes, ("gswin64c", "gswin32c"))
        self.assertEqual(
            tuple(item.probe.name for item in provider.unverified_executables), ("gs",)
        )
        self.assertEqual(provider.unavailable_probes, ("gs", "gswin64c", "gswin32c"))

    def test_unsupported_is_distinct_from_absent_without_running_probes(self) -> None:
        locator = Mock()
        version_reader = Mock()
        unsupported = capabilities.detect_capability(
            capabilities.POPPLER,
            capabilities.MachineState("Plan9", "mips"),
            locator=locator,
            version_reader=version_reader,
        )
        absent = capabilities.detect_capability(
            capabilities.POPPLER,
            self.machine,
            locator=lambda probe, machine: None,
            version_reader=version_reader,
        )

        self.assertEqual(unsupported.availability, capabilities.Availability.UNSUPPORTED)
        self.assertEqual(absent.availability, capabilities.Availability.ABSENT)
        locator.assert_not_called()
        version_reader.assert_not_called()

    def test_provider_support_includes_architecture_and_environment(self) -> None:
        provider = capabilities.ProviderSpec(
            provider_id="fixture",
            label="fixture",
            platforms=frozenset({"Linux"}),
            architectures=frozenset({"arm64"}),
            execution_environments=frozenset({"container"}),
            probes=(capabilities.ExecutableProbe("fixture", ("--version",)),),
            probe_policy=capabilities.ProbePolicy.ANY,
        )
        self.assertTrue(provider.supports(capabilities.MachineState("Linux", "arm64", "container")))
        self.assertFalse(provider.supports(capabilities.MachineState("Linux", "x86_64", "container")))
        self.assertFalse(provider.supports(capabilities.MachineState("Linux", "arm64", "host")))

    def test_any_probe_policy_selects_first_verified_alternative(self) -> None:
        state = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            self.machine,
            locator=lambda probe, machine: f"/tools/{probe.name}" if probe.name == "gswin64c" else None,
            version_reader=lambda probe, path: "10.0",
        )
        provider = state.selected_provider
        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(state.availability, capabilities.Availability.AVAILABLE)
        self.assertEqual(
            tuple(item.probe.name for item in provider.executables if item.verified),
            ("gswin64c",),
        )

    def test_windows_ghostscript_locator_prefers_newest_version(self) -> None:
        with TemporaryDirectory() as program_files:
            executable = Path(program_files, "gs", "10.06.0", "bin", "gswin64c.exe")
            executable.parent.mkdir(parents=True)
            executable.touch()
            old_executable = Path(program_files, "gs", "9.56.1", "bin", "gswin64c.exe")
            old_executable.parent.mkdir(parents=True)
            old_executable.touch()
            probe = capabilities.ExecutableProbe(
                "gswin64c", ("--version",), "windows-ghostscript"
            )
            with (
                patch.object(capabilities.shutil, "which", return_value=None),
                patch.dict(capabilities.os.environ, {"ProgramFiles": program_files}, clear=True),
            ):
                self.assertEqual(
                    capabilities.locate_executable(
                        probe, capabilities.MachineState("Windows", "AMD64")
                    ),
                    str(executable),
                )

    def test_git_bash_locator_uses_git_installation_outside_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory, "Git")
            git = root / "cmd" / "git.exe"
            bash = root / "bin" / "bash.exe"
            git.parent.mkdir(parents=True)
            bash.parent.mkdir(parents=True)
            git.touch()
            bash.touch()
            probe = capabilities.BASH.providers[0].probes[0]

            def which(command: str) -> str | None:
                return str(git) if command == "git" else None

            with (
                patch.object(capabilities.shutil, "which", side_effect=which),
                patch.dict(capabilities.os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    capabilities.locate_executable(
                        probe, capabilities.MachineState("Windows", "AMD64")
                    ),
                    str(bash),
                )

    def test_git_bash_locator_includes_native_program_files_for_32_bit_python(self) -> None:
        with TemporaryDirectory() as directory:
            native = Path(directory, "native")
            emulated = Path(directory, "x86")
            bash = native / "Git" / "bin" / "bash.exe"
            bash.parent.mkdir(parents=True)
            bash.touch()
            probe = capabilities.BASH.providers[0].probes[0]
            with (
                patch.object(capabilities.shutil, "which", return_value=None),
                patch.dict(
                    capabilities.os.environ,
                    {
                        "ProgramW6432": str(native),
                        "ProgramFiles": str(emulated),
                        "ProgramFiles(x86)": str(emulated),
                    },
                    clear=True,
                ),
            ):
                self.assertEqual(
                    capabilities.locate_executable(
                        probe, capabilities.MachineState("Windows", "x86")
                    ),
                    str(bash),
                )

    def test_windows_program_roots_are_ordered_and_deduplicated(self) -> None:
        with patch.dict(
            capabilities.os.environ,
            {
                "ProgramW6432": "C:/Program Files",
                "ProgramFiles": "c:/program files",
                "ProgramFiles(x86)": "C:/Program Files (x86)",
            },
            clear=True,
        ):
            self.assertEqual(
                capabilities._windows_program_roots(),
                ("C:/Program Files", "C:/Program Files (x86)"),
            )

    def test_version_probe_accepts_stderr_and_rejects_failures(self) -> None:
        probe = capabilities.ExecutableProbe(
            "pdfinfo", ("-v",), nonzero_version_pattern=r"\bversion\b"
        )
        success = subprocess.CompletedProcess(["pdfinfo", "-v"], 0, "", "pdfinfo 1.2.3\n")
        nonzero_version = subprocess.CompletedProcess(
            ["pdfinfo", "-v"], 99, "", "pdfinfo version 1.2.3\n"
        )
        failure = subprocess.CompletedProcess(["pdfinfo", "-v"], 1, "", "failed\n")
        with patch.object(capabilities.subprocess, "run", return_value=success):
            self.assertEqual(capabilities.read_executable_version(probe, "/tools/pdfinfo"), "pdfinfo 1.2.3")
        with patch.object(capabilities.subprocess, "run", return_value=nonzero_version):
            self.assertEqual(
                capabilities.read_executable_version(probe, "/tools/pdfinfo"),
                "pdfinfo version 1.2.3",
            )
        with patch.object(capabilities.subprocess, "run", return_value=failure):
            self.assertIsNone(capabilities.read_executable_version(probe, "/tools/pdfinfo"))
        with patch.object(
            capabilities.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["pdfinfo", "-v"], 5),
        ):
            self.assertIsNone(capabilities.read_executable_version(probe, "/tools/pdfinfo"))

    def test_architecture_probe_requires_successful_stdout(self) -> None:
        probe = capabilities.ExecutableProbe(
            "bash", ("--version",), architecture_args=("-c", "uname -m")
        )
        success = subprocess.CompletedProcess(["bash", "-c", "uname -m"], 0, "arm64\n", "")
        failure = subprocess.CompletedProcess(["bash", "-c", "uname -m"], 1, "x86_64\n", "")
        with patch.object(capabilities.subprocess, "run", return_value=success):
            self.assertEqual(
                capabilities.read_executable_architecture(probe, "/tools/bash"), "arm64"
            )
        with patch.object(capabilities.subprocess, "run", return_value=failure):
            self.assertIsNone(capabilities.read_executable_architecture(probe, "/tools/bash"))

    def test_bash_architecture_falls_back_to_verified_build_tuple(self) -> None:
        state = capabilities.detect_capability(
            capabilities.BASH,
            self.machine,
            locator=lambda probe, machine: "/bin/bash",
            version_reader=lambda probe, path: (
                "GNU bash, version 5.3.15(2)-release (aarch64-unknown-linux-gnu)"
            ),
            architecture_reader=lambda probe, path: None,
        )
        self.assertEqual(state.selected_provider.executables[0].architecture, "aarch64")


if __name__ == "__main__":
    unittest.main()
