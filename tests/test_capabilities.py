import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent_tools import capabilities


class CapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = capabilities.MachineState("Linux", "x86_64")

    def test_catalogue_has_stable_document_capability_order(self) -> None:
        self.assertEqual(
            tuple(item.capability_id for item in capabilities.CAPABILITY_CATALOGUE),
            ("poppler", "ghostscript"),
        )
        self.assertTrue(all(item.required_by_default for item in capabilities.CAPABILITY_CATALOGUE))
        self.assertIs(capabilities.get_capability("poppler"), capabilities.POPPLER)
        with self.assertRaises(KeyError):
            capabilities.get_capability("unknown")

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

    def test_version_probe_accepts_stderr_and_rejects_failures(self) -> None:
        probe = capabilities.ExecutableProbe("pdfinfo", ("-v",))
        success = subprocess.CompletedProcess(["pdfinfo", "-v"], 0, "", "pdfinfo 1.2.3\n")
        failure = subprocess.CompletedProcess(["pdfinfo", "-v"], 1, "", "failed\n")
        with patch.object(capabilities.subprocess, "run", return_value=success):
            self.assertEqual(capabilities.read_executable_version(probe, "/tools/pdfinfo"), "pdfinfo 1.2.3")
        with patch.object(capabilities.subprocess, "run", return_value=failure):
            self.assertIsNone(capabilities.read_executable_version(probe, "/tools/pdfinfo"))
        with patch.object(
            capabilities.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["pdfinfo", "-v"], 5),
        ):
            self.assertIsNone(capabilities.read_executable_version(probe, "/tools/pdfinfo"))


if __name__ == "__main__":
    unittest.main()
