# #57: Optional document boundary

Base: `ed09825bcafef2c1ada669ccf9eb974b4b064042`.
Milestone: [v0.2 / 8](https://github.com/smartnuf/agent-tools/milestone/8), open.
Acceptance: optional document install with diagnostic and upgrade compatibility;
#57 remains the end-to-end tracker until implementation/evidence are merged.
This stream owns merging; no other open PR was present at discovery.

## Intent, characterisation and discovery

Implement Decision 0008 without expanding the native catalogue or document
features. Public dependency/diagnostic compatibility is high; Python environment
mutation belongs to uv. No new application persistence, native mutation or
privilege boundary is needed. Three-platform packaging evidence is necessary;
Linux experiments alone cannot qualify Windows/macOS or a published release.

At the base, `pyproject.toml` requires seven document libraries. Only
`cli.doctor` imports them, lazily inside its probe loop; all other packaged
functions use the standard library. There are no document-processing commands.
Doctor currently counts every library failure alongside native failures.
`tests/check_distribution.py` assumes unconditional dependencies and
`tests/check_installed_cli.py` requires all imports. CI, release, PyPI smoke and
`tests/check_release_lifecycle.py` must distinguish installation shapes.
`requirements.in`/`requirements.txt` explicitly describe the checkout document
environment; bootstrap/update consume that lock separately from package
metadata. They remain useful development/compatibility infrastructure.

Primary sources: Python's optional-dependency metadata specification and uv's
tool environment/upgrade documentation (linked in Decision 0010). Runtime
metadata does not prove which extras were requested. Therefore specify explicit
document validation rather than infer requested state or add persistent state.

### Disposable experiment, 2026-09-14

uv 0.12.7, Linux aarch64, CPython 3.11.16. Two locally built discovery wheels
used the current source with synthetic versions 0.1.2 (mandatory dependencies)
and 0.2.0 (same constraints under `documents`). They were not published artifacts
or a v0.2 release candidate. All tool and launcher directories were under a
temporary experiment directory, outside the checkout/user tool installation.

| Transition | Observed distributions | Receipt |
|---|---:|---|
| mandatory-stack prototype install | 17 | bare pinned request |
| explicit new core reinstall | 1 | bare pinned request |
| explicit documents reinstall | 17 | `documents` extra |
| uv tool upgrade of documents selection | 17 | extra retained |
| explicit core reinstall | 1 | extra removed |

The experiment used `uv tool install --reinstall --find-links WHEELS` with exact
prototype requirements and an existing interpreter. Installed distribution
inventories and uv receipts were inspected after every step; final tool
uninstall succeeded. No system provider/profile/configuration was changed.
This proves local selection mechanics only. Actual v0.1.x migration,
resolution-failure preservation and three-platform exact-candidate qualification
remain implementation obligations, not claims from this prototype.

## Mapping, specification and bounded plan

[Decision 0010](../../decisions/0010-document-extra-and-diagnostics.md) owns the
public syntax, doctor modes, migration and preservation contract. Preserve the
existing native catalogue, dependency constraints, Python range and lock.
No licensing decision, new document functionality, plugin abstraction or
self-updater is part of this work.

1. Discovery/specification PR: 0.5–1 person-day (issue's original estimate).
   Commit this contract and evidence; run baseline tests/syntax/diff validation
   and obtain exact-head automated review before merge. No runtime change.
2. Implementation/evidence PR: 1–2 person-days, tracked in [#109](https://github.com/smartnuf/agent-tools/issues/109) under #57.
   Move dependency metadata; implement doctor modes; update parser-generated
   reference and README/PyPI/platform/packaging guidance. Update metadata,
   isolated installed-shape, unit and preservation/lifecycle tests and CI/release
   gates. Retain pre-existing checkout locks and scripts.
3. Full exact-head validation and review, then merge the implementation only
   when evidence converges. Split further if discovery raises it above two days;
   never close #57 or increment the gate based on this specification alone.

Combined original discovery plus newly estimated implementation: 1.5–3 days;
implementation remaining 1–2 days after specification merges. Actual effort is
untracked; external review/CI wait is excluded. Six correction waves maximum
per bounded PR, with multiple focused commits in one push per correction wave.

Validation for implementation: unit/fault tests, POSIX/PowerShell syntax,
doctor in both shapes/modes, generated-reference and guide checks, rebuilt
sdist/wheel metadata, isolated uv tool lifecycle, and exact-head three-platform
CI/review. Preserve host state; local missing native tools or unavailable
PowerShell must be reported separately from product failures. Publication and
#104 provider/platform expansion remain separate release work.

After specification, implement this contract as the next task (L, 1–2 days).
After implementation, reconcile the optional-dependency gate and final-guide
readiness against actual evidence; recommend #104 discovery next.

## Specification validation

Documentation-only change: 407 baseline unit tests pass; CLI reference and 33
concrete guide invocations remain current; POSIX syntax/PATH checks pass.
Local doctor reports the two known missing native tools (Poppler/Ghostscript),
with all seven existing document imports healthy. PowerShell is unavailable
locally; hosted checks remain required. Ranged diff validation, exact-head CI
and automated review gate the specification merge. No implementation or new
artifact behavior is claimed by these baseline checks.
