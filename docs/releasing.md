# GitHub and PyPI release procedure

GitHub tags and releases are the canonical artifact history. The tag workflow creates a prerelease and does not publish to PyPI. Publishing to PyPI is a separate, stable-release-only workflow protected by GitHub's `pypi` environment and PyPI trusted publishing.

## Prepare a release

1. Update `src/agent_tools/__init__.py`, every version-sensitive test, and `docs/releases/v<version>.md` in a reviewed pull request.
2. Confirm `main` is clean and all required CI checks pass after that pull request is merged.
3. Create an annotated `v<version>` tag at the reviewed `main` commit, for example `v1.2.3`.
4. Push only that tag. Do not move or reuse a published version tag.

The tag workflow rejects a tag whose name differs from the package version, lacks reviewed release notes, or points to a commit outside the repository's default branch. It then builds and validates one wheel and one source distribution, writes deterministic `SHA256SUMS`, creates a GitHub prerelease with the checked-in notes, and exercises install, pin, and uninstall against the published wheel on Windows, Ubuntu, and macOS.

The workflow has repository read permission by default. Only its release job receives `contents: write`, using GitHub's short-lived workflow token. It has no PyPI credentials or other publishing secret.

## Publish a stable release to PyPI

The PyPI project uses a pending trusted publisher until the first successful upload creates the project. A pending publisher does not reserve the project name. Recheck that `smartnuf-agent-tools` remains available immediately before the first publication.

The trusted-publisher identity must match these values exactly:

- PyPI project: `smartnuf-agent-tools`
- GitHub owner: `smartnuf`
- GitHub repository: `agent-tools`
- Workflow: `publish-pypi.yml`
- GitHub environment: `pypi`

This pending publisher and the protected `pypi` environment were configured and verified on 2026-08-30. The environment requires approval from `smartnuf`, permits that sole maintainer to approve their own deployment, accepts only the `main` branch and `v[0-9]*` tags, and contains no secrets. The publisher remains pending until its first successful upload creates the PyPI project.

Configure the GitHub `pypi` environment with required reviewer protection so publication requires a maintainer's explicit approval. Do not add a PyPI API token, username, password, repository secret, or environment secret.

After the tag workflow and its cross-platform smoke jobs pass, promote the reviewed GitHub prerelease to a stable release without replacing its assets. Publishing that stable release triggers `publish-pypi.yml`. Pull requests, branch pushes, and tag pushes cannot trigger PyPI publication. The publish job rejects drafts and prereleases, verifies that the immutable tag matches the package version and belongs to the default branch, downloads the existing wheel, source distribution, and checksum manifest, verifies the release assets, and exposes `id-token: write` only to the environment-protected publish job. The pinned PyPA action exchanges GitHub's OIDC identity for a short-lived PyPI publishing credential.

Before approving the environment deployment, verify the workflow run references the expected tag, commit, release assets, and workflow file. After it succeeds, confirm the PyPI version and files match the stable GitHub release before promoting the PyPI install command in user documentation.

## Validate or recover

Download all three release assets and verify the checksums when auditing a release. The tag workflow automatically tests the published installation lifecycle on supported-platform runners; inspect those jobs before treating the prerelease as complete.

If the workflow fails before creating a release, correct the cause through a pull request and create a new version rather than moving a published tag. If GitHub created an incomplete draft or prerelease, record what happened before removing it, then use a new version for the replacement. Never overwrite an artifact attached to an existing release.

If trusted publication fails before PyPI accepts an upload, leave the GitHub tag and release immutable. Diagnose the exact owner, repository, workflow filename, environment, and OIDC permission against the trusted-publisher configuration. If no code change is needed, retry the failed job only when the same release artifacts and tag remain valid. A rerun uses the original workflow revision; after correcting workflow code through a reviewed pull request, run the merged workflow manually from `main` with the existing stable `release_tag`. The recovery job revalidates the stable release, tag ancestry, artifact names, and checksums and still requires `pypi` environment approval. If PyPI accepted any file, do not overwrite or reuse that version; record the partial publication and release a new version.
