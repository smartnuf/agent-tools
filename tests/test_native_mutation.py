import copy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("native_mutation", Path(__file__).with_name("check_native_mutation.py"))
mutation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mutation)


class NativeMutationOracleTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "capability_id": "poppler", "ownership": False,
            "package_manager": {"name": "apt"},
            "verification": {"outcome": "succeeded", "verified_paths": ["/usr/bin/pdfinfo"]},
            "command_evidence": [{"returncode": 0}],
        }

    def test_credit_requires_actual_successful_requests(self):
        mutation.validate_mutation_records([self.record], ["poppler"], "apt")
        variants = []
        for field, value in (
            ("ownership", True), ("command_evidence", []),
            ("command_evidence", [{"returncode": 1}]),
            ("verification", {"outcome": "verification-failed", "verified_paths": []}),
            ("package_manager", {"name": "brew"}),
        ):
            record = copy.deepcopy(self.record)
            record[field] = value
            variants.append(record)
        for record in variants:
            with self.subTest(record=record), self.assertRaises(AssertionError):
                mutation.validate_mutation_records([record], ["poppler"], "apt")

    def test_every_advertised_target_requires_mutation_coverage(self):
        requested = ["poppler", "ghostscript"]
        mutation.validate_mutation_coverage(requested, requested)
        for unsatisfied in ([], ["poppler"], ["ghostscript"]):
            with self.subTest(unsatisfied=unsatisfied), self.assertRaisesRegex(AssertionError, "coverage gap"):
                mutation.validate_mutation_coverage(requested, unsatisfied)

    def test_windows_rediscovery_refreshes_only_child_environment(self):
        original = os.environ.get("PATH")
        with mock.patch.object(mutation.os, "name", "nt"), mock.patch.object(
            mutation.provider_execution, "_windows_persisted_path", return_value="updated-provider-path"
        ):
            refreshed = mutation.rediscovery_environment()
        self.assertEqual(refreshed["PATH"], "updated-provider-path")
        self.assertEqual(os.environ.get("PATH"), original)

    def test_missing_extra_or_duplicate_requests_do_not_count(self):
        for records, expected in (
            ([], ["poppler"]), ([self.record], ["poppler", "ghostscript"]),
            ([self.record, self.record], ["poppler"]), ([self.record], []),
        ):
            with self.subTest(records=records, expected=expected), self.assertRaises(AssertionError):
                mutation.validate_mutation_records(records, expected, "apt")


if __name__ == "__main__":
    unittest.main()
