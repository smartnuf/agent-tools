from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import release  # noqa: E402


class ReleaseTests(unittest.TestCase):
    def test_current_tag_matches_package_version(self) -> None:
        self.assertEqual(release.verify_tag("v0.1.0"), "v0.1.0")

    def test_mismatched_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            release.verify_tag("v0.1.1")

    def test_checksums_are_sorted_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            second = directory / "second.tar.gz"
            first = directory / "first.whl"
            second.write_bytes(b"second")
            first.write_bytes(b"first")
            destination = directory / "SHA256SUMS"

            release.write_checksums(destination, [second, first])

            expected = (
                f"{hashlib.sha256(b'first').hexdigest()}  first.whl\n"
                f"{hashlib.sha256(b'second').hexdigest()}  second.tar.gz\n"
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), expected)

    def test_checksum_file_cannot_include_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "SHA256SUMS"
            destination.touch()
            with self.assertRaisesRegex(ValueError, "cannot checksum itself"):
                release.write_checksums(destination, [destination])


if __name__ == "__main__":
    unittest.main()
