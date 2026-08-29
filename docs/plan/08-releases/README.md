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
| Runtime and optional dependencies are correctly declared | in-progress | [Packaging contract](../../packaging.md); clean-environment proof remains in issue #6 |
| Packaged CLI works outside a checkout | not-started | Installed-wheel smoke test |
| `agent-tools --version` matches package and tag | not-started | Automated assertion against tagged build |
| Wheel and sdist build successfully from a clean tag | not-started | Tag-triggered workflow artifact |
| Artifact tests pass on Windows, Linux, and macOS | not-started | Required CI matrix |
| Release workflow uses explicit least-privilege permissions | not-started | Workflow permission inspection |
| GitHub prerelease includes artifacts, checksums, and notes | not-started | GitHub Release link |
| Install, pin, and uninstall documentation is verified | not-started | CI or recorded clean-host smoke test |

Estimate: **4–7 person-days**.

Suggested task order:

1. Packaging contract and metadata, 0.75–1.25 days.
2. Checkout-independent installed CLI, 0.75–1.25 days.
3. Artifact isolation and metadata tests, 0.5–1 day.
4. Tag-driven least-privilege release workflow, 1–1.5 days.
5. Cross-platform artifact verification and fixes, 0.5–1 day.
6. User documentation and prerelease exercise, 0.5–1 day.

## M2 — Public PyPI release

Outcome: an ordinary user can install the supported CLI with one `uv tool install` command.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| PyPI project and trusted publisher are configured | not-started | Registry/project configuration |
| Reviewed tag publishes without a long-lived upload token | not-started | Successful publish workflow |
| Package installs from PyPI on all supported platforms | not-started | Post-publication matrix |
| README promotes tested install/update/remove commands | not-started | Documentation validation |
| Stable GitHub Release and PyPI metadata agree | not-started | Version and artifact comparison |

Estimate: **1–2 person-days**, excluding registry or review waiting time.

## M3 — Tested update lifecycle

Outcome: installation is not a one-off; supported upgrading, pinning, rollback, and removal are demonstrated behaviours.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Fresh and repeated installation are tested | not-started | Automated lifecycle test |
| Upgrade from the previous supported release is tested | not-started | Automated upgrade test |
| Version pinning and rollback are tested | not-started | Automated lifecycle test |
| Removal leaves documented user-owned state untouched | not-started | Automated or disposable-host test |
| Native dependency failures are actionable | not-started | `doctor` tests with absent/partial tools |
| Release procedure requires no unpublished local step | not-started | Maintainer runbook and completed release |

Estimate: **2–4 person-days**.

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
