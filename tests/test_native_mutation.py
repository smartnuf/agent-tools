import copy
import importlib.util
from pathlib import Path
import unittest


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

    def test_missing_extra_or_duplicate_requests_do_not_count(self):
        for records, expected in (
            ([], ["poppler"]), ([self.record], ["poppler", "ghostscript"]),
            ([self.record, self.record], ["poppler"]), ([self.record], []),
        ):
            with self.subTest(records=records, expected=expected), self.assertRaises(AssertionError):
                mutation.validate_mutation_records(records, expected, "apt")


if __name__ == "__main__":
    unittest.main()
