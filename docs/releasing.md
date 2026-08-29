# GitHub prerelease procedure

GitHub tags and releases are the canonical artifact history. The M1 workflow creates a prerelease only; it does not publish to PyPI.

## Prepare a release

1. Update `src/agent_tools/__init__.py`, every version-sensitive test, and `docs/releases/v<version>.md` in a reviewed pull request.
2. Confirm `main` is clean and all required CI checks pass after that pull request is merged.
3. Create an annotated `v<version>` tag at the reviewed `main` commit, for example `v0.1.0`.
4. Push only that tag. Do not move or reuse a published version tag.

The tag workflow rejects a tag whose name differs from the package version, lacks reviewed release notes, or points to a commit outside the repository's default branch. It then builds and validates one wheel and one source distribution, writes deterministic `SHA256SUMS`, creates a GitHub prerelease with the checked-in notes, and exercises install, pin, and uninstall against the published wheel on Windows, Ubuntu, and macOS.

The workflow has repository read permission by default. Only its release job receives `contents: write`, using GitHub's short-lived workflow token. It has no PyPI credentials or other publishing secret.

## Validate or recover

Download all three release assets and verify the checksums when auditing a release. The tag workflow automatically tests the published installation lifecycle on supported-platform runners; inspect those jobs before treating the prerelease as complete.

If the workflow fails before creating a release, correct the cause through a pull request and create a new version rather than moving a published tag. If GitHub created an incomplete draft or prerelease, record what happened before removing it, then use a new version for the replacement. Never overwrite an artifact attached to an existing release.
