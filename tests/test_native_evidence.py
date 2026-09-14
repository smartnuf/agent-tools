import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "native_evidence", Path(__file__).with_name("capture_native_evidence.py")
)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class NativeEvidenceTests(unittest.TestCase):
    def test_unavailable_probe_is_an_observation(self):
        with mock.patch.object(evidence.shutil, "which", return_value=None):
            result = evidence.probe("missing", "--version")
        self.assertEqual(result["status"], "not-found")
        self.assertIsNone(result["executable"])

    def test_failed_probe_retains_bounded_output_and_status(self):
        def run(argv, **kwargs):
            self.assertEqual(kwargs["timeout"], evidence.PROBE_TIMEOUT_SECONDS)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            kwargs["stdout"].write(b"x" * (evidence.MAX_OUTPUT_BYTES + 100))
            return subprocess.CompletedProcess(argv, 7)

        with mock.patch.object(evidence.shutil, "which", return_value=__file__), mock.patch.object(
            evidence.subprocess, "run", side_effect=run
        ):
            result = evidence.probe("tool", "--version")
        self.assertEqual(result["returncode"], 7)
        self.assertTrue(result["output_truncated"])
        self.assertEqual(len(result["output_tail"]), evidence.MAX_OUTPUT_BYTES)

    def test_unresolvable_alias_still_gets_read_only_version_probe(self):
        with mock.patch.object(evidence.shutil, "which", return_value=__file__), mock.patch.object(
            evidence.Path, "resolve", side_effect=OSError("app alias")
        ), mock.patch.object(evidence.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            result = evidence.probe("winget", "--version")
        self.assertEqual(result["resolution_error"], "app alias")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(run.call_args.args[0], [__file__, "--version"])

    def test_timeout_preserves_partial_observation(self):
        def run(argv, **kwargs):
            kwargs["stdout"].write(b"partial output")
            raise subprocess.TimeoutExpired(argv, 10)

        with mock.patch.object(evidence.shutil, "which", return_value=__file__), mock.patch.object(
            evidence.subprocess, "run", side_effect=run
        ):
            result = evidence.probe("tool", "--version")
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["output_tail"], "partial output")
        self.assertNotIn("returncode", result)

    def test_environment_collection_does_not_export_arbitrary_variables(self):
        with mock.patch.dict(os.environ, {"SECRET_EXAMPLE": "never-export-this"}), mock.patch.object(
            evidence, "probe", return_value={"status": "not-found"}
        ):
            result = evidence.collect("after", "failure")
        self.assertNotIn("never-export-this", str(result))
        self.assertEqual(result["fixture_outcome"], "failure")
        self.assertEqual(result["evidence_class"], "external-preseed-observation")


if __name__ == "__main__":
    unittest.main()
