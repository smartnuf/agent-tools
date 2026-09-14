# v0.2.1 final post-distribution review — #124

The human authorized v0.2.1 as the documentation-only correction through final
post-distribution review. The corrected version is stable on GitHub and PyPI.
All eight v0.2 product acceptance gates have durable evidence; no broader
product work is selected. This factual reconciliation completes the existing
[patch plan](12-doc-patch-release.md), whose estimate remains up to 0.5 person-day
excluding CI/review waits; actual effort is untracked.

## Immutable identity and public files

- Release commit: `821917f3e158b3d1cb11a833225fd8e9651fd47d`.
- Annotated `v0.2.1` tag object: `f1012995435f13c95e5d02ef5c055c5bb83d8a3a`.
- [Stable GitHub release](https://github.com/smartnuf/agent-tools/releases/tag/v0.2.1).
- [Public PyPI version](https://pypi.org/project/smartnuf-agent-tools/0.2.1/).
- GitHub wheel asset `564086336`, sdist asset `564086329`, checksum manifest
  `564086334`; stable promotion retained the qualified assets unchanged.

| Distribution | SHA-256 |
|---|---|
| `smartnuf_agent_tools-0.2.1-py3-none-any.whl` | `cac98fefac4b7f84e8e69dd289c75bcdd795e5d87d78f4433a1be244c4b6ebf5` |
| `smartnuf_agent_tools-0.2.1.tar.gz` | `200107b9b0fc9ae10498ac1d978a383cd471e27a6592168bdb1fadb98e3cd378` |

Downloaded GitHub assets passed `SHA256SUMS`. Both signed attestations verified
against `refs/tags/v0.2.1`, the exact commit above and
`.github/workflows/release.yml`. Independently downloaded PyPI bytes match
both hashes, and neither file is yanked. The project endpoint reports 0.2.1 as
latest and its simple index exposes the expected files.

The UTF-8 wheel METADATA description, sdist PKG-INFO description and public
PyPI description each match the corrected tagged README exactly. Its SHA-256
is `d094cabee6fb31c89f24c64c939b5b2b2b65729098982e5650c8995cc028afa9`.
Desired-state and integration commands are correctly described as included in
v0.2.0 and later, without requiring a checkout. The v0.2.0 files and tag remain
unchanged; their historical metadata limitation is not silently rewritten.

## Qualification evidence

| Evidence | Result |
|---|---|
| [Preparation PR #126](https://github.com/smartnuf/agent-tools/pull/126) | Reviewed head `886cca49d240c1ae1b9eeb3ea5d8dbe4ce869081`; merged tree matches exactly. Required checks and review passed; four findings resolved in one two-commit correction wave |
| [Main CI 34887508351](https://github.com/smartnuf/agent-tools/actions/runs/34887508351) | All four required jobs passed on the exact release commit before tagging |
| [Tag qualification 34888154687](https://github.com/smartnuf/agent-tools/actions/runs/34888154687) | Installed contract and historical migration checks preceded attestation; Windows, Ubuntu and macOS published-wheel smoke jobs passed |
| [Protected publication 34888539252](https://github.com/smartnuf/agent-tools/actions/runs/34888539252) | Verified tag, stable state, checksums and provenance; authorized `pypi` deployment published unchanged assets through OIDC |
| [Public PyPI lifecycle 34888687662](https://github.com/smartnuf/agent-tools/actions/runs/34888687662) | Windows/macOS passed in attempt 1; Ubuntu passed the sole failed-job retry in attempt 2, all at the exact release commit |

The first Ubuntu public smoke job correctly failed its version assertion when
an unpinned install resolved v0.2.0 during initial PyPI index propagation.
Version-specific files were already available before every index view caught
up. Inspection confirmed the stale resolution and later simple-index/latest
availability. Only the failed job was retried, once, on the unchanged tag. No
assertion, workflow or artifact was changed to obtain the passing result.
The original failed attempt remains in the run history.

A separate isolated public-PyPI check on the Linux ARM64 workstation explicitly
reinstalled `smartnuf-agent-tools[documents]==0.2.0` as
`smartnuf-agent-tools[documents]==0.2.1`, verified library imports,
reinstalled core-only 0.2.1, verified its one-distribution shape, and uninstalled
the application. Temporary uv tool/bin/cache directories kept this evidence
separate from normal user installations. This is patch-pin and Python-extra
lifecycle evidence, not native-provider/platform qualification.

## Independent review and scope closure

An independent read-only context repeated public metadata/byte comparisons,
verified both attestations, inspected stable release notes and completed runs,
and compared the released wheels and source trees. Verdict: **pass, no
unresolved actionable findings**. Runtime files differ from v0.2.0 only in the
version string; dependencies and entry points are identical. No native mapping,
mutation/authorization contract, persistent state or support promise changed.

The release/PyPI workflows use external native fixtures. They do not substitute
for the separate real installed-CLI mutation evidence in the
[platform matrix](../../platforms.md#observed-installed-cli-native-mutations),
or expand its explicit OS/architecture gaps. Candidate and source-fixture
migration evidence retains the distinctions in the prior lifecycle records.

The completion protocol integrates this factual record through exact-head
review, then verifies GitHub issue/milestone closure and clean synchronized
main. Administrative status is authoritative at
[issue #124](https://github.com/smartnuf/agent-tools/issues/124) and
[milestone 8](https://github.com/smartnuf/agent-tools/milestone/8).
Fresh human Intent is required before future research becomes implementation.
