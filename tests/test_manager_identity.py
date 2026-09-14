from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_tools import manager_identity, native_setup, provider_execution
from agent_tools.capabilities import MachineState


class ManagerIdentityTests(unittest.TestCase):
    def test_normal_file_and_symlink_keep_strict_identity_without_probe(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "winget.exe"
            target.touch()
            link = Path(directory) / "alias.exe"
            paths = [target]
            try:
                link.symlink_to(target)
                paths.append(link)
            except OSError:
                pass  # Windows runners need not grant symlink creation privileges.
            with patch.object(provider_execution, "run_bounded_command_with_image") as probe:
                for path in paths:
                    self.assertEqual(manager_identity.resolve_manager_identity(
                        path, "winget", "Windows"), target.resolve(strict=True))
                probe.assert_not_called()
            with self.assertRaises(OSError):
                manager_identity.resolve_manager_identity(Path(directory) / "absent", "apt", "Linux")

    def test_app_alias_discovery_and_revalidation_share_identity_and_reject_retarget(self):
        with TemporaryDirectory() as directory:
            alias, image, other = (Path(directory) / name for name in ("alias", "image", "other"))
            for path in (alias, image, other):
                path.touch()
            original_lstat = Path.lstat

            def lstat(path):
                return (SimpleNamespace(st_reparse_tag=manager_identity._APPEXECLINK)
                        if path == alias else original_lstat(path))

            result = subprocess.CompletedProcess((str(alias), "--version"), 0, "v1.11\n", "")
            machine = MachineState("Windows", "x86_64")
            with patch.object(Path, "lstat", lstat), patch.object(
                provider_execution, "run_bounded_command_with_image", return_value=(result, str(image))
            ) as probe:
                state, = native_setup.detect_package_managers(machine, locator=lambda _: str(alias))
                self.assertEqual(state.executable_path, str(alias))
                self.assertEqual(state.resolved_executable_path, str(image.resolve(strict=True)))
                self.assertTrue(provider_execution._verify_manager(state, machine))
                probe.assert_called_with((str(alias), "--version"), 10)
                probe.return_value = result, str(other)
                self.assertFalse(provider_execution._verify_manager(state, machine))
                probe.side_effect = OSError("query failed")
                self.assertFalse(provider_execution._verify_manager(state, machine))
                with self.assertRaises(native_setup.NativeSetupError):
                    native_setup.detect_package_managers(machine, locator=lambda _: str(alias))

    def test_alias_scope_and_invalid_image_fail_closed(self):
        with TemporaryDirectory() as directory:
            alias = Path(directory) / "alias"
            alias.touch()
            result = subprocess.CompletedProcess((), 0, "v1.11", "")
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_reparse_tag=manager_identity._APPEXECLINK)), patch.object(
                provider_execution, "run_bounded_command_with_image", return_value=(result, "")
            ) as probe:
                for value in ("", "relative.exe", "bad\0image", str(Path(directory) / "missing"), directory):
                    probe.return_value = result, value
                    with self.subTest(value=value), self.assertRaises(OSError):
                        manager_identity.resolve_manager_identity(alias, "winget", "Windows")
                for result in (subprocess.CompletedProcess((), 1, "version", "failure"),
                               subprocess.CompletedProcess((), 0, "", "")):
                    probe.return_value = result, str(alias)
                    with self.assertRaises(OSError):
                        manager_identity.resolve_manager_identity(alias, "winget", "Windows")
            # Unknown reparse types and other managers never receive an activation probe.
            with patch.object(Path, "lstat", return_value=SimpleNamespace(st_reparse_tag=123)), patch.object(
                Path, "resolve", side_effect=OSError("unsupported reparse point")
            ), patch.object(provider_execution, "run_bounded_command_with_image") as probe:
                for manager, platform in (("winget", "Windows"), ("apt", "Linux"), ("brew", "Windows")):
                    with self.assertRaises(OSError):
                        manager_identity.resolve_manager_identity(alias, manager, platform)
                probe.assert_not_called()

    def test_observation_and_publication_failure_reap_launched_process(self):
        class BrokenList(list):
            def append(self, value):
                raise RuntimeError("publication failed")

        for failure in (True, False):
            launched = []

            def observe(process):
                launched.append(process)
                if failure:
                    raise RuntimeError("query failed")
                return "image"

            with self.subTest(query_failure=failure), patch.object(provider_execution, "_windows_process_image", side_effect=observe):
                with self.assertRaises(provider_execution.CommandLifecycleError) as caught:
                    provider_execution._run((sys.executable, "-c", "import time; time.sleep(30)"), 5,
                                            _image_observations=BrokenList())
                self.assertFalse(caught.exception.lifetime_uncertain)
                self.assertIsNotNone(launched[0].poll())

    def test_observation_time_uses_existing_timeout_cleanup(self):
        import time
        launched = []

        def observe(process):
            launched.append(process)
            time.sleep(0.05)
            return "image"

        with patch.object(provider_execution, "_windows_process_image", side_effect=observe):
            with self.assertRaises(subprocess.TimeoutExpired):
                provider_execution.run_bounded_command_with_image(
                    (sys.executable, "-c", "import time; time.sleep(30)"), 0.01)
        self.assertIsNotNone(launched[0].poll())

    def test_fast_probe_completion_returns_observed_image(self):
        with patch.object(provider_execution, "_windows_process_image", return_value="image"):
            result, image = provider_execution.run_bounded_command_with_image(
                (sys.executable, "-c", "print('version')"), 5)
        self.assertEqual((result.returncode, result.stdout.strip(), image), (0, "version", "image"))

    def test_windows_query_validates_buffer_and_borrows_owned_handle(self):
        import ctypes
        from ctypes import wintypes
        from unittest.mock import Mock

        for value, count in (("C:\\manager.exe", 14), ("", 0), ("C:\\manager.exe", 32768),
                             ("C:\\manager.exe", 2), ("C:\\😀.exe", 9)):
            def query(handle, flags, buffer, size):
                self.assertEqual((handle, flags), (123456789012, 0))
                buffer.value = value
                ctypes.cast(size, ctypes.POINTER(wintypes.DWORD)).contents.value = count
                return True

            kernel = SimpleNamespace(QueryFullProcessImageNameW=Mock(side_effect=query))
            with self.subTest(value=value, count=count), patch.object(
                provider_execution.os, "name", "nt"
            ), patch.object(ctypes, "WinDLL", return_value=kernel, create=True):
                if count == len(value.encode("utf-16-le")) // 2 and value:
                    self.assertEqual(provider_execution._windows_process_image(
                        SimpleNamespace(_handle=123456789012)), value)
                else:
                    with self.assertRaises(OSError):
                        provider_execution._windows_process_image(SimpleNamespace(_handle=123456789012))

    def test_observation_interrupt_cleans_up_and_force_abort_propagates(self):
        from agent_tools.cooperative_cancellation import _ForceAbort

        for interrupt in (KeyboardInterrupt, _ForceAbort):
            launched = []

            def observe(process):
                launched.append(process)
                raise (_ForceAbort(KeyboardInterrupt()) if interrupt is _ForceAbort else KeyboardInterrupt())

            try:
                with self.subTest(interrupt=interrupt.__name__), patch.object(
                    provider_execution, "_windows_process_image", side_effect=observe
                ), patch.object(provider_execution, "_best_effort_started_process_cleanup",
                                wraps=provider_execution._best_effort_started_process_cleanup) as cleanup:
                    with self.assertRaises(interrupt):
                        provider_execution.run_bounded_command_with_image(
                            (sys.executable, "-c", "import time; time.sleep(30)"), 5)
                    if interrupt is KeyboardInterrupt:
                        cleanup.assert_called_once()
                        self.assertIsNotNone(launched[0].poll())
                    else:
                        cleanup.assert_not_called()
            finally:
                # Force-abort deliberately retains immediate propagation semantics;
                # the test still owns and cleans its disposable child and pipes.
                for process in launched:
                    if process.poll() is None:
                        provider_execution._terminate_process_tree(process)
                    for pipe in (process.stdout, process.stderr):
                        if pipe and not pipe.closed:
                            pipe.close()
