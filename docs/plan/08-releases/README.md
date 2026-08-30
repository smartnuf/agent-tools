# Release milestones and acceptance gates

This file defines what “done” means. Update states and evidence here and summarize them in [`../00-index.md`](../00-index.md).

## M0 — Distribution foundations

Outcome: contributors and agents share one durable product decision, roadmap, and measurable work queue.

| Acceptance criterion | State | Evidence |
|---|---|---|
| Public distribution model is decided | complete | [Decision 0001](../../decisions/0001-distribution-model.md) |
| Milestones have estimates and observable gates | complete | this file and the [status index](../00-index.md) |
| Agent planning and reporting protocol is documented | complete | [planning protocol](../README.md) and [root instructions](../../../AGENTS.md) |
| Intended distribution name is selected and current availability checked | complete | [M0 packaging discovery](01-packaging-discovery.md) |
| M1 tasks are inventoried and linked | complete | [M0 packaging discovery](01-packaging-discovery.md#actionable-m1-work) |

Original estimate: **0.5–1 person-day**. Complete; actual effort was not recorded.

## M1 — Installable GitHub prerelease

Outcome: a user can install and run a versioned prerelease artifact without cloning the repository.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Package name, metadata, and supported versions are final | complete | [Packaging contract](../../packaging.md) and built-wheel metadata check |
| Runtime and optional dependencies are correctly declared | complete | [Packaging contract](../../packaging.md) and complete clean-environment `doctor` run |
| Packaged CLI works outside a checkout | complete | No-dependency installed-wheel smoke test from an unrelated directory |
| `agent-tools --version` matches package and tag | complete | v0.1.1 tag contract and published-wheel smoke run |
| Wheel and sdist build successfully from a clean tag | complete | [v0.1.1 tag workflow](https://github.com/smartnuf/agent-tools/actions/runs/33231066203) |
| Artifact tests pass on Windows, Linux, and macOS | complete | `release-dist` CI artifact installed and checked by every platform job |
| Release workflow uses explicit least-privilege permissions | complete | `release.yml`: read by default; only the tag-push release job has `contents: write` |
| GitHub prerelease includes artifacts, checksums, and notes | complete | [v0.1.1 GitHub prerelease](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) |
| Install, pin, and uninstall documentation is verified | complete | [Revised published-release smoke run 33232110219](https://github.com/smartnuf/agent-tools/actions/runs/33232110219) passed on Windows, Ubuntu, and macOS |

Estimate: **4–7 person-days**.

Complete on 2026-08-29. Actual engineering effort was not recorded. The immutable `v0.1.0` tag failed workflow validation before creating a release; the incident and recovery are preserved in `docs/releases/v0.1.0.md`. Version `v0.1.1` supplied the release artifacts. The documented install pins Python 3.13 and locates the executable through `uv tool dir --bin`; three-platform CI exercises that contract against the built wheel, and [run 33232110219](https://github.com/smartnuf/agent-tools/actions/runs/33232110219) repeated it against the published release.

Suggested task order:

1. Packaging contract and metadata, 0.75–1.25 days.
2. Checkout-independent installed CLI, 0.75–1.25 days.
3. Artifact isolation and metadata tests, 0.5–1 day.
4. Tag-driven least-privilege release workflow, 1–1.5 days.
5. Cross-platform artifact verification and fixes, 0.5–1 day.
6. User documentation and prerelease exercise, 0.5–1 day.

## M2 — Public PyPI release

Outcome: an ordinary user can install the supported CLI with one `uv tool install` command.

Starts after the bounded [M1.5 capability foundation](../09-capabilities/README.md)
clarifies the installed product boundary. M1.5 does not include native package
mutation and must not expand into the M3 lifecycle work.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| PyPI project and trusted publisher are configured | complete | The v0.1.2 upload created the project through the protected GitHub `pypi` environment and exact identity in the [release runbook](../../releasing.md) |
| Reviewed tag publishes without a long-lived upload token | complete | [OIDC publication run 33312422488](https://github.com/smartnuf/agent-tools/actions/runs/33312422488) |
| Package installs from PyPI on all supported platforms | complete | [PyPI lifecycle run 33313165322](https://github.com/smartnuf/agent-tools/actions/runs/33313165322) passed unpinned resolution, upgrade, exact reinstall, and removal on Windows, Ubuntu, and macOS |
| README promotes tested install/update/remove commands | complete | PyPI install, upgrade, exact reinstall pin, and removal commands in the root README are covered by the lifecycle workflow |
| Stable GitHub Release and PyPI metadata agree | complete | v0.1.2 filename, size, version, Python constraint, and SHA-256 comparison |

Estimate: **1–2 person-days**, excluding registry or review waiting time. Complete on 2026-08-30 through issues #19 and #45. Actual engineering effort was not recorded; the accepted estimate remains the historical forecast.

## M3 — Tested update and capability lifecycle

Outcome: installation is not a one-off; supported upgrading, pinning, rollback, and removal are demonstrated behaviours.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Fresh and repeated installation are tested | complete | [PyPI lifecycle run 33313165322](https://github.com/smartnuf/agent-tools/actions/runs/33313165322) installs, upgrades/reconciles, exactly reinstalls, and removes v0.1.2 on Windows, Ubuntu, and macOS |
| Upgrade from the previous supported release is tested | not-started | Automated upgrade test |
| Version pinning and rollback are tested | not-started | Automated lifecycle test |
| Removal leaves documented user-owned state untouched | not-started | Automated or disposable-host test |
| Native dependency failures are actionable | not-started | `doctor` tests with absent/partial tools |
| Release procedure requires no unpublished local step | complete | [v0.1.2 publication run 33312422488](https://github.com/smartnuf/agent-tools/actions/runs/33312422488) verified the signed GitHub release artifacts against tag checksums/attestations and published them through GitHub OIDC/Trusted Publishing |
| Native/system-first final-provider selection reuses suitable pre-seeded providers independently of bootstrap process architecture | not-started | #14 pure selection fixtures and #49 seeded-workstation/disposable-host evidence cover native, unknown, translated, external, managed, and separate-environment candidates; explicit preferences and native-provisioning overrides; consistent same-executable evidence merging and conflict rejection; provider/version/path tie-breakers; and ambiguity failure, without claiming unavailable hosted ARM64 coverage |
| Provider mutation consumes an inspectable plan, requires a flag, reports changes, records provenance, and is shared by clone wrappers | not-started | Unit/disposable-host tests prove plan generation and executor consumption, installation flag enforcement, complete change reports, and persisted record contents; if provider removal is added, its separate flag and refusal rules are tested; bootstrap wrappers delegate without duplicate package mappings |
| Desired-state and integration configuration changes are authorized, backed up, validated, reversible, preserve unrelated state, and never uninstall providers | not-started | Tests for existing configuration prove explicit authorization, recoverable backup, resulting-state validation, failure restoration, unrelated-state preservation, and no provider uninstall; integration cases cover shared/dedicated providers and Git for Windows |

Estimate: **6–10 person-days**. [Issue #26](https://github.com/smartnuf/agent-tools/issues/26)
records the reviewed dependency order. Native/system-first selection (#14) and
pre-seeded workstation evidence (#49) precede read-only provider planning
(#50), explicit mutation (#51), provenance (#52), clone delegation (#53),
desired-state safety (#54), and agent integration (#27). Issue #55 supplies
the earlier-release upgrade, rollback, and removal evidence not already proven
by M2. GitHub-hosted CI covers Windows, Ubuntu, and macOS on its available
runner architectures; pure fixtures cover translated/ARM64 combinations and
must not be presented as hosted ARM64 evidence.

## M4 — Optional discovery channels

Start only after M3 is complete and user demand justifies the maintenance burden.

### M4a — WinGet

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Versioned manifest is generated from a published release | deferred | Generated manifest review |
| Architecture, URL, and checksum are validated | deferred | Manifest validation output |
| Install and upgrade work on disposable Windows hosts | deferred | Disposable-host test |
| Community-repository submission is accepted | deferred | Accepted submission link |

Estimate: **2–4 person-days**, excluding external review time.

### M4b — Homebrew

| Acceptance criterion | State | Required evidence |
| Formula or tap is generated from a published release | deferred | Formula or tap review |
| Checksum and version updates are automated | deferred | Update workflow test |
| Intel and Apple-silicon behaviour is tested where runners are available | deferred | Platform test results |
| Install and upgrade documentation is verified | deferred | Documentation smoke test |

Estimate: **1.5–3 person-days**.

Do not schedule MSI, macOS package, deb/rpm, standalone binary, self-updater, or bundled native-program work without a new decision record and demonstrated need.
