# v0.2.0 release qualification and closure (#124)

## Task plan and boundary

Complete the eighth v0.2 gate using the existing release procedure, then
reconcile the status index, gate table and release runbook. This is a bounded
release-record task: estimate **S, up to 0.5 person-day**, excluding CI/review
waits; actual effort is untracked. Root is the sole merge owner. No product,
provider, distribution, dependency or public-contract change is included.

Discovery confirmed that reviewed main was clean, post-merge CI was green,
and no v0.2.0 tag or files existed before explicit human tag authorization.
Publication is externally coupled and irreversible: preserve the tag and
assets, verify provenance and public bytes, and require separate authorization
for stable promotion and protected PyPI publication. Both authorizations were
received. Documentation reconciliation uses a focused PR with baseline tests,
syntax checks, guide validation, ranged diff checking and exact-head review.

## Immutable release identity

- Reviewed release commit: `7e1eea88c8e4ea497529ee8a9f6b0918996ab627`.
- Annotated `v0.2.0` tag object: `329c36498655d7dc7afa9add5bb602d2b922da2e`.
- [Stable GitHub release](https://github.com/smartnuf/agent-tools/releases/tag/v0.2.0).
- [Public PyPI version](https://pypi.org/project/smartnuf-agent-tools/0.2.0/).
- Wheel asset ID: `563977843`; source archive: `563977844`; checksum manifest:
  `563977845`. Promotion retained these assets unchanged.

| Distribution | SHA-256 |
|---|---|
| `smartnuf_agent_tools-0.2.0-py3-none-any.whl` | `cbb6bb60d7c00f5d40b9a633acc06dd3bffdd932e51bd8a998bfa29849e201cc` |
| `smartnuf_agent_tools-0.2.0.tar.gz` | `428a4287a5e1f2b41c8065417fd727ef347dfb8f5baaab6d2a05878570d48954` |

Downloaded GitHub files passed `SHA256SUMS`. Both attestations verified against
`refs/tags/v0.2.0`, the exact release commit and `.github/workflows/release.yml`.
Public PyPI metadata and independently downloaded file bytes matched both
hashes; neither file was yanked. The public project endpoint reported 0.2.0 as
latest after its initial index propagation delay.

## Durable validation

| Evidence | Result and limit |
|---|---|
| [Reviewed PR #123](https://github.com/smartnuf/agent-tools/pull/123) and [post-merge CI 34878209594](https://github.com/smartnuf/agent-tools/actions/runs/34878209594) | 433 unit tests, 43 guide invocations, required CI and exact-head review; reviewed and merged trees matched |
| [Tag qualification 34880881981](https://github.com/smartnuf/agent-tools/actions/runs/34880881981) | Release job and Windows/Ubuntu/macOS GitHub-wheel smoke jobs passed at the release commit; installed-shape and v0.1.x migration/pin/rollback/preservation checks preceded attestation/publication |
| [Protected publication 34882085405](https://github.com/smartnuf/agent-tools/actions/runs/34882085405) | Exact tag, stable status, checksums and provenance verified; human-authorized `pypi` deployment published unchanged files through OIDC |
| [PyPI lifecycle 34882242567](https://github.com/smartnuf/agent-tools/actions/runs/34882242567) | Dispatched at v0.2.0; Windows, Ubuntu and macOS all passed public installation, upgrade, pin/reinstall, removal and optional-document lifecycle checks |

The publication/smoke workflows use external native fixtures; they do not
replace the separate real installed-CLI mutation evidence in the
[maintained platform matrix](../../platforms.md#observed-installed-cli-native-mutations).
Candidate migration tests and source-version fixtures retain the distinctions
recorded in [the document lifecycle plan](05-document-lifecycle.md); no new
public rollback version or broader OS/architecture coverage is claimed.

## Published-text defect and disposition

PR #125 review found that the immutable v0.2.0 wheel/sdist README, also served
as the PyPI description, says desired-state and integration commands are
available only from `main` pending the next release. They are included in
v0.2.0. This is a documentation availability error, not a runtime failure;
the installed-artifact and public lifecycle validation above remains valid.

The source README correction uses version-qualified availability. An appended
GitHub release erratum corrects the mutable release presentation, while the
tag, distribution files and their signed hashes remain unchanged. Neither
correction repairs the already-published PyPI description.

Independent read-only adjudication under the development workflow confirmed
that immutable-file preservation determines the conservative result: reopen
the front-door gate, retain seven completed gates, keep #124 and milestone 8
open, and reserve disposition for the human. No new architecture, supported
platform, host mutation or persistent state is involved. No release asset may
be overwritten or tag moved to repair prose.

Recommended disposition: authorize a new immutable patch release with corrected
metadata and repeat reviewed-source, exact-tag, protected-publication and
public-lifecycle qualification. The alternative is explicit human acceptance
of the documented v0.2.0 metadata limitation. Current authority covers v0.2.0
publication only; it does not choose a new version or waive the front-door gate.

## Completion and learning

The release gate is complete; the front-door gate is blocked on the disposition
above. This record does not close #124 or milestone 8. The up-to-0.5-day record
reconciliation estimate is unchanged; actual effort is untracked. A patch
publication, if authorized, receives its own estimate. Historical task plans
describe their original execution state and are not current release snapshots.

Local tooling and transient index observations were not product defects: the
host GitHub CLI lacked attestation support, so an official checksum-verified
temporary CLI performed verification; the public version endpoint was available
before the unversioned project endpoint caught up. The README defect also shows
that parsed examples and installed help checks do not detect stale surrounding
availability prose. Future release review must inspect that prose before the
immutable tag, in addition to validating executable examples.

After v0.2 disposition, require a fresh human Intent decision before expanding
product work. Future research remains research.


The second review wave extended the availability sweep to maintained platform
and packaging guides; their stale next-release claims are corrected. Historical
task plans and the generic generated source-reference caveat remain explicitly
scoped. The reusable release runbook now requires pre-merge inspection of built
README metadata and surrounding availability prose before tagging. Actual PR
commit messages and its revised body contain no issue-closing keyword; merge
metadata must also preserve #124 as open.


## Subsequent human disposition

The human authorized v0.2.1 as the documentation-only correction, through final
post-distribution review. The decision above is resolved in favor of a new
immutable patch; no limitation waiver is used. Follow the
[v0.2.1 plan](12-doc-patch-release.md) for current status. The v0.2.0 evidence and
metadata defect remain historical facts; final gate closure still requires
the corrected public description and completed qualification/review.
