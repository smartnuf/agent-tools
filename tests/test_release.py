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
    def test_pypi_workflow_is_stable_release_only_and_keyless(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("release:\n    types: [published, released]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("release_tag:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("github.event.release.prerelease == false", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("gh api", workflow)
        self.assertIn('git show "$RELEASE_TAG:src/agent_tools/__init__.py"', workflow)
        self.assertIn('test "$tag_version" = "${RELEASE_TAG#v}"', workflow)
        self.assertIn("diff -u expected-files manifest-files", workflow)
        self.assertIn("sha256sum --check SHA256SUMS", workflow)
        self.assertEqual(workflow.count("gh attestation verify"), 2)
        self.assertIn('--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"', workflow)
        self.assertIn('--source-ref "refs/tags/$RELEASE_TAG"', workflow)
        self.assertIn('--source-digest "$tag_commit"', workflow)
        self.assertIn("name: pypi", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn(
            "pypa/gh-action-pypi-publish@"
            "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
            workflow,
        )
        self.assertNotIn("password:", workflow)
        self.assertNotIn("username:", workflow)
        self.assertNotIn("PYPI_API_TOKEN", workflow)

    def test_release_workflow_attests_built_distributions(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("attestations: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn(
            "actions/attest@a1948c3f048ba23858d222213b7c278aabede763",
            workflow,
        )
        self.assertIn("dist/*.whl", workflow)
        self.assertIn("dist/*.tar.gz", workflow)

    def test_pypi_smoke_workflow_uses_the_public_index_on_all_platforms(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "pypi-smoke.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("release_version:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("os: [windows-latest, ubuntu-latest, macos-latest]", workflow)
        self.assertEqual(workflow.count("smartnuf-agent-tools=="), 2)
        self.assertNotIn("github.com/", workflow.replace("github.com/actions/", ""))
        self.assertIn("tools list", workflow)
        self.assertIn("doctor", workflow)
        self.assertEqual(workflow.count("uv tool upgrade smartnuf-agent-tools"), 2)
        self.assertIn("--reinstall", workflow)
        self.assertIn("uv tool uninstall smartnuf-agent-tools", workflow)

    def test_current_tag_matches_package_version(self) -> None:
        self.assertEqual(release.verify_tag("v0.1.2"), "v0.1.2")
        self.assertTrue((ROOT / "docs" / "releases" / "v0.1.2.md").is_file())

    def test_mismatched_tag_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            release.verify_tag("v0.1.3")

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
            release.verify_checksums(destination)

    def test_checksum_file_cannot_include_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "SHA256SUMS"
            destination.touch()
            with self.assertRaisesRegex(ValueError, "cannot checksum itself"):
                release.write_checksums(destination, [destination])

    def test_changed_artifact_fails_checksum_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            artifact = directory / "package.whl"
            artifact.write_bytes(b"original")
            manifest = directory / "SHA256SUMS"
            release.write_checksums(manifest, [artifact])
            artifact.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                release.verify_checksums(manifest)

    def test_unlisted_artifact_fails_checksum_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            artifact = directory / "package.whl"
            artifact.write_bytes(b"original")
            manifest = directory / "SHA256SUMS"
            release.write_checksums(manifest, [artifact])
            (directory / "unlisted.tar.gz").touch()
            with self.assertRaisesRegex(ValueError, "do not match artifacts"):
                release.verify_checksums(manifest)


if __name__ == "__main__":
    unittest.main()
