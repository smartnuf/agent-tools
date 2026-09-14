# Plan status

- Last reconciled: 2026-09-14
- Current completed milestone: M3 — complete
- Current milestone: v0.2 productisation — in-progress ([GitHub milestone 8](https://github.com/smartnuf/agent-tools/milestone/8))
- Current state: turn the completed M3 machinery into one minimally useful installed `agent-tools` product before selecting any broader future intent
- Current user installation: `uv tool install --python 3.13 smartnuf-agent-tools`
- Current unpublished candidate: 0.2.0 (build identity only; not tagged or published)
- Current published release: v0.1.2; M3 functionality on `main` remains pending the next feature-bearing release
- Distribution policy: PyPI via `uv tool` is the sole supported Agent Tools distribution channel; alternative WinGet/Homebrew distribution work is retired as not planned
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone / objective | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | complete | 5/5 | 0.5–1 day | none |
| M1 | Installable GitHub prerelease | complete | 9/9 | 4–7 days | none |
| M1.5 | Reviewed capability-ready package build | complete | 5/5 | 2–3.25 days | none |
| M2 | Public PyPI release | complete | 5/5 | 1–2 days | none |
| M3 | Tested update and capability lifecycle | complete | 9/9 | 6.5–11 days | none |
| v0.2 #103 | Installed CLI and named-only native installation | complete | contributes 2 gates | 1.5–2 days | none |
| v0.2 #57 specification | Optional-document contract and migration discovery | complete | no additional gate complete | 0.5–1 day | none |
| v0.2 #109 runtime slice | Optional documents extra, diagnostics and installed shapes | complete | completed with #111; 4/8 overall | 1–1.5 days | none |
| v0.2 #111 | Optional-document artifact migrations and preservation | complete | 4/8 v0.2 gates complete overall | 1–1.5 days | none |
| v0.2 #106 | Generated CLI reference and help/docs drift prevention | complete | 3/8 v0.2 gates complete overall | 0.25–0.75 day | none |
| v0.2 #104/#114 | Provider/platform discovery and retained environment capture | complete | no additional gate complete | 0.5–1 day | none |
| v0.2 #118 | WinGet activation identity prerequisite | complete | no additional gate complete | 0.5–1.5 days | none |
| v0.2 #120 | Legacy-encoded native reporting prerequisite | complete | no additional gate complete | 0.25–0.5 day | none |
| v0.2 #104/#115 | Real installed-CLI native mutation and explicit platform matrix | complete | 6/8 v0.2 gates complete overall | 1–2 days | none |
| v0.2 #122 | Final front door and release notes | in-progress | front-door gate pending | 0.5–1 day | 0.5–1 day |

Estimated implementation effort through M3: **complete**. Discovery for #103
is recorded in its [task plan](10-v0.2-productisation/01-installed-cli.md), and
[Decision 0009](../decisions/0009-installed-capability-install.md) records the
human-approved named-only request contract. The forecast above covers #103 and
#106 only (originally 1.75–2.75 days combined; implementation complete);
#57 implementation was estimated at 1–2 days from its
[discovery and specification](10-v0.2-productisation/03-document-boundary.md).
[Implementation discovery](10-v0.2-productisation/04-document-implementation.md)
revises this to 2–3 days: runtime/installed-shape work (1–1.5 days) and #111
lifecycle evidence (1–1.5 days), both implemented;
the #104 discovery/evidence work and its bounded prerequisites are implemented
as recorded above. Final guide reconciliation is specified in
[#122](10-v0.2-productisation/10-final-guides.md) at 0.5–1 day; release
qualification still needs its own discovery-based estimate. Actual effort is untracked.

Former M4a/M4b are historical, cancelled objectives rather than deferred work
or completed implementation. Their GitHub milestones are closed as not planned
and they are excluded from current readiness and effort totals.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the original public distribution model.
- [Decision 0002](../decisions/0002-native-capability-provider-model.md) establishes the packaged native-capability boundary and safe provider semantics.
- [Decision 0007](../decisions/0007-v0.2-product-and-distribution-boundary.md) narrows the next product boundary to one installed CLI and one Agent Tools distribution channel, retires alternative distribution-channel work, and requires an installed `agent-tools install <list>` path for v0.2.
- [Decision 0008](../decisions/0008-optional-document-capability-boundary.md) makes document-processing libraries a separately requested capability rather than mandatory core dependencies.
- The packaged [capability catalogue and detected-state model](../../src/agent_tools/capabilities.py) covers Poppler and Ghostscript with fixture-driven tests and `doctor` integration.
- The same catalogue distinguishes Git Bash, system Bash, and WSL Bash; the packaged read-only `tools list/status` interface is exercised outside a checkout.
- Distribution metadata, platform guidance, and the transferred-wheel CI matrix describe and test the capability-discovery product boundary.
- [Planning protocol](README.md) defines task planning and progress reporting.
- [v0.1.1](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) is an audited GitHub prerelease with a wheel, source distribution, checksums, and reviewed notes.
- [Release run 33231066203](https://github.com/smartnuf/agent-tools/actions/runs/33231066203) installed, pinned, version-checked, and uninstalled the public wheel on Windows, Ubuntu, and macOS.
- [Revised smoke run 33232110219](https://github.com/smartnuf/agent-tools/actions/runs/33232110219) repeated the published-wheel lifecycle on all three platforms using Python 3.13 and `uv tool dir --bin`.
- [PR #44](https://github.com/smartnuf/agent-tools/pull/44) merged the protected, tokenless PyPI workflow and exact-tag artifact provenance checks.
- [v0.1.2](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.2) is the first stable GitHub release with signed provenance for its wheel and source distribution.
- [Publication run 33312422488](https://github.com/smartnuf/agent-tools/actions/runs/33312422488) published v0.1.2 through the protected PyPI environment and GitHub OIDC without a long-lived upload token.
- PyPI v0.1.2 metadata reports the expected project/version/Python range; its wheel and source-distribution sizes and SHA-256 digests match the GitHub release exactly.
- [PyPI lifecycle run 33313165322](https://github.com/smartnuf/agent-tools/actions/runs/33313165322) resolved the unpinned public package, version-checked, diagnosed, upgraded, exactly reinstalled, and removed it on Windows, Ubuntu, and macOS.
- [PR #72](https://github.com/smartnuf/agent-tools/pull/72) implements read-only installed-Python discovery, independent host/process evidence, deterministic native/system-first ranking, explicit-path clone bootstrap, and final-environment verification; its pure fixtures do not substitute for #49 platform evidence.
- Issue #49 adds repeatable pre-seeded Python, Git Bash, Poppler, and Ghostscript fixture evidence plus honest Windows, Ubuntu, and macOS hosted-runner checks; it explicitly does not claim hosted ARM64 coverage.
- Issue #50 adds deterministic, inspectable, read-only provider plans and catalogue-owned WinGet, apt, dnf, pacman, and Homebrew command adapters from immutable verified package-manager evidence; already-satisfied requests produce zero actions.
- [PR #78](https://github.com/smartnuf/agent-tools/pull/78) implements [issue #77](https://github.com/smartnuf/agent-tools/issues/77) by installing delegated architecture adjudication and an architectural closure sweep after #50, preserving human authority for product-policy choices before autonomous mutation work in #51.
- [Issue #51](https://github.com/smartnuf/agent-tools/issues/51) adds the packaged, explicitly authorized provider-plan executor with bounded command execution, structured attempted/observed change reports, mandatory rediscovery/final verification, partial-state recovery guidance, and idempotent repeat evidence on a disposable filesystem-backed host.
- [Issue #52](https://github.com/smartnuf/agent-tools/issues/52) adds the versioned, atomically replaced managed-state document governed by [Decision 0003](../decisions/0003-managed-state-provenance.md), preserving append-only Agent Tools mutation-request evidence without package ownership.
- [Issue #53](https://github.com/smartnuf/agent-tools/issues/53) makes both clone bootstrap wrappers delegate their explicit native-install flags to the packaged planner, managed executor, provenance boundary, and final verifier; unit and native-runner tests cover exact argument delegation, all-satisfied reruns, actionable failure evidence, and the absence of duplicate mappings.
- [Issue #54](https://github.com/smartnuf/agent-tools/issues/54) adds the versioned desired-capability document governed by [Decision 0005](../decisions/0005-desired-capability-state.md), explicit configuration-mutation authority, recoverable backup and atomic replacement, validation/restoration, unrelated-entry preservation, exact provider preferences, status reporting, and clone-bootstrap consumption without any provider-removal path.
- [Issue #27](https://github.com/smartnuf/agent-tools/issues/27) adds the native-Windows Claude Code adapter governed by [Decision 0006](../decisions/0006-claude-code-git-bash-integration.md): it consumes selected verified Git Bash evidence, mutates only the documented setting behind explicit authority, preserves unrelated configuration, restores prior state, and records independently reconcilable lifecycle phases without provider installation or removal.
- [Issue #55](https://github.com/smartnuf/agent-tools/issues/55) adds the checksum-verified, exact-artifact lifecycle test across Windows, Ubuntu, and macOS: direct-wheel v0.1.1 install, published-v0.1.2 upgrade and exact reinstall, v0.1.1 rollback, and application removal with byte-identical current desired state and the externally owned Bash provider preserved.
- [Issue #103](https://github.com/smartnuf/agent-tools/issues/103) records the v0.2 CLI-only product work and required `agent-tools install <list>` entry point.
- [Issue #57](https://github.com/smartnuf/agent-tools/issues/57) records the separately installed document-capability boundary.
- [Issue #104](https://github.com/smartnuf/agent-tools/issues/104) records the real-provider CI parity and explicit platform-evidence work required before v0.2.
- The former M4 WinGet/Homebrew PR #71 and issues #59–#70 were closed as not planned on 2026-09-08. Their history remains available for provenance but is no longer an active roadmap direction. The empty GitHub milestones were explicitly closed as not planned on 2026-09-14.

M1 is complete and its factual record is frozen except for corrections. M1.5
completed on 2026-08-29; M2 completed on 2026-08-30 with the first stable PyPI
release; M3 completed on 2026-09-02. Actual M1.5, M2, and M3 engineering effort
was not recorded, so their accepted estimates remain the historical forecasts;
review and CI wait were excluded.

## Recommended next work

[PR #102](https://github.com/smartnuf/agent-tools/pull/102) merged as
`226c81f` on 2026-09-14 and closed #56, supplying the product-first README
and checked PyPI metadata. Preserve that front door while adapting it to v0.2.

The [v0.2 milestone](https://github.com/smartnuf/agent-tools/milestone/8) is open
with #103, #57, #104 and #106 assigned. The first two gates have
source and installed-artifact evidence in `tests/test_install.py`,
`tests/check_installed_cli.py` and `tests/check_distribution.py`: 401 unit tests
pass and the wheel rebuilt from the restricted sdist passes outside-checkout
CLI tests. #106 adds the third completed gate: `tests/test_cli_reference.py`,
`tests/check_cli_docs.py`, installed-help comparisons and pre-publication checks
keep the generated reference and guide invocations aligned with argparse.
The suite now has 433 passing tests. These changes await the next feature-bearing
release. #57 discovery specifies the `documents` extra and explicit
`doctor --documents` validation in [Decision 0010](../decisions/0010-document-extra-and-diagnostics.md),
backed by disposable uv selection experiments. #109 now supplies optional
metadata, explicit diagnostics, updated guides and independent core/documents
installed-wheel checks. #111 supplies old-release artifact migration,
pin/reinstall/removal/failure/rollback preservation and separately labelled
source-fixture extra-retention evidence; see [the lifecycle plan](10-v0.2-productisation/05-document-lifecycle.md).
The optional-document gate is complete on merge (4/8 overall), closing
#111/#109/#57. #114/#116 supplied provider/platform discovery and environment
capture; #118/#119 repaired WinGet activation identity, and #120/#121 repaired
legacy-encoded native reporting. #115/PR #117 now supplies inspected real apt,
Homebrew and WinGet mutation, provenance, fresh rediscovery and byte-preserving
no-op evidence plus the [maintained platform matrix](../platforms.md#observed-installed-cli-native-mutations).
Its two #104 gates are complete (6/8 overall); Windows Ghostscript and
untested common variants remain explicit gaps, not fallback success. See the
[native evidence plan](10-v0.2-productisation/06-native-evidence.md) and
[mutation implementation record](10-v0.2-productisation/07-native-mutation.md).
The 1–2 day evidence slice and focused 0.5–1.5 day identity / 0.25–0.5 day
reporting prerequisites are implemented, excluding review/CI wait. Final guide
reconciliation proceeds in #122 (0.5–1 day, excluding review/CI wait);
exact-artifact release qualification remains separate. Preserve public v0.1.2
until authorized publication.

The v0.2 goal is deliberately minimal: one installed CLI, `agent-tools install
<list>`, optional document dependencies, real-provider evidence where practical,
and honest platform coverage. When v0.2 is published, stop and choose a new
Intent rather than automatically continuing into the ideas retained in
[future product research](90-future-product-research.md).

## Known risks and assumptions

- `smartnuf-agent-tools` is the published PyPI project; trusted publication remains restricted to the exact repository, workflow, and protected environment.
- v0.1.2 is the current published release and predates M3 mutation/configuration functionality now present on `main`.
- The current CI native-integration path externally pre-seeds native tools before proving Agent Tools' all-satisfied behaviour; this is useful evidence but is not by itself end-to-end proof of real package-manager mutation through the installed CLI. Issue #104 owns the distinction.
- The published wheel and sdist pass independent checksum and metadata audits; install, pin, and uninstall pass on Windows, Ubuntu, and macOS runners.
- Repository wrappers and the shared `.venv` are not part of the future ordinary-user product contract; Decision 0007 requires released workflows through `agent-tools`.
- Windows ARM64/x64 emulation and macOS Intel/Apple-silicon coverage require explicit evidence and must not be inferred from generic hosted-runner labels.
- Debian, Fedora/RHEL, Arch, WSL, and other common variants must be labelled according to their actual evidence class rather than inferred from a nearby tested platform.
- On Windows ARM64, unconstrained Python 3.14 selected a native interpreter but `cryptography` lacked a wheel and required an unavailable MSVC linker. The initial `<3.14` Python bound makes `uv tool` choose a supported managed interpreter; Python 3.14 support must be revalidated before widening it.
- Git Bash can exist outside `PATH`; discovery must verify provider-specific candidates rather than equating `shutil.which("bash")` with capability absence.
- WSL Bash is a separate Linux execution environment and must not silently satisfy a Windows-hosted Bash preference.

## Other backlog and future research

Existing bounded maintenance work remains valid where independently justified:

- automate reviewed dependency upgrades;
- add functional PDF extraction and rendering fixtures where they remain relevant after the optional document boundary;
- extend concurrent Windows PATH tests and restoration documentation;
- report package versions and executable architecture in `doctor`;
- decide whether native repair or removal commands are ever warranted.

Broader product ideas — additional optional tools and rights research, named
capability sets, file-driven installs, catalogue search, TUI, MCP, and empirical
research into which tools different agents prefer for different jobs — are
preserved in [90-future-product-research.md](90-future-product-research.md).
They are not active roadmap work.

See [release milestones and acceptance gates](08-releases/README.md), the
[capability-foundation milestone](09-capabilities/README.md), and the
[v0.2 productisation plan](10-v0.2-productisation/README.md) for detailed
completion definitions and next-stage planning.
