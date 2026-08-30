# Plan status

- Last reconciled: 2026-08-30 at base `e7f35ffb84b45c6a62249b312f0c0642be5f0b92`
- Current milestone: M3 — tested update and capability lifecycle
- Current state: M2 complete; M3 not started
- Current user installation: `uv tool install --python 3.13 smartnuf-agent-tools`
- Target lifecycle: tested upgrade, pin, rollback, safe provider mutation, and removal
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | complete | 5/5 | 0.5–1 day | none |
| M1 | Installable GitHub prerelease | complete | 9/9 | 4–7 days | none |
| M1.5 | Reviewed capability-ready package build | complete | 5/5 | 2–3.25 days | none |
| M2 | Public PyPI release | complete | 5/5 | 1–2 days | none |
| M3 | Tested update and capability lifecycle | not-started | 0/8 | 3–6 days | 3–6 days |
| M4a | WinGet discovery | deferred | 0/6 | 4–7 days | 4–7 days |
| M4b | Homebrew discovery | deferred | 0/6 | 3–5 days | 3–5 days |

Estimated implementation effort through M3: **3–6 person-days remaining**. Native discovery channels are optional and excluded from that total; review time is reported separately.

Post-M3 optional-channel implementation is now estimated at **7–12
person-days**, excluding external moderation. Research completed the architecture
decisions but did not complete an implementation acceptance gate.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the intended public distribution model.
- [Decision 0002](../decisions/0002-native-capability-provider-model.md) establishes the packaged native-capability boundary and safe provider semantics.
- [Decision 0003](../decisions/0003-winget-distribution.md) rejects WinGet-to-uv delegation and requires a later-approved WinGet-owned artifact.
- [Decision 0004](../decisions/0004-homebrew-distribution.md) selects a native Python formula in a project tap rather than uv delegation.
- The packaged [capability catalogue and detected-state model](../../src/agent_tools/capabilities.py) covers Poppler and Ghostscript with fixture-driven tests and `doctor` integration.
- The same catalogue distinguishes Git Bash, system Bash, and WSL Bash; the packaged read-only `tools list/status` interface is exercised outside a checkout.
- Distribution metadata, platform guidance, and the transferred-wheel CI matrix now describe and test the capability-discovery product boundary.
- [Planning protocol](README.md) defines task planning and progress reporting.
- [v0.1.1](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) is an audited GitHub prerelease with a wheel, source distribution, checksums, and reviewed notes.
- [Release run 33231066203](https://github.com/smartnuf/agent-tools/actions/runs/33231066203) installed, pinned, version-checked, and uninstalled the public wheel on Windows, Ubuntu, and macOS.
- [Revised smoke run 33232110219](https://github.com/smartnuf/agent-tools/actions/runs/33232110219) repeated the published-wheel lifecycle on all three platforms using Python 3.13 and `uv tool dir --bin`.
- [PR #44](https://github.com/smartnuf/agent-tools/pull/44) merged the protected, tokenless PyPI workflow and exact-tag artifact provenance checks.
- [v0.1.2](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.2) is the first stable GitHub release with signed provenance for its wheel and source distribution.
- [Publication run 33312422488](https://github.com/smartnuf/agent-tools/actions/runs/33312422488) published v0.1.2 through the protected PyPI environment and GitHub OIDC without a long-lived upload token.
- PyPI v0.1.2 metadata reports the expected project/version/Python range; its wheel and source-distribution sizes and SHA-256 digests match the GitHub release exactly.
- [PyPI lifecycle run 33313165322](https://github.com/smartnuf/agent-tools/actions/runs/33313165322) resolved the unpinned public package, version-checked, diagnosed, upgraded, exactly reinstalled, and removed it on Windows, Ubuntu, and macOS.

M1 is complete and its factual record is frozen except for corrections. M1.5
completed on 2026-08-29; M2 completed on 2026-08-30 with the first stable PyPI
release. Actual M1.5 and M2 engineering effort was not recorded, so their
accepted estimates remain the historical forecasts; review and CI wait were
excluded.

## Recommended next work

Begin the M3 provider-mutation and managed-state design in [issue #26](https://github.com/smartnuf/agent-tools/issues/26), splitting implementation into reviewable execution, provenance, and integration slices before changing native programs (L, **3–6 days** for M3 overall).

After M3, evaluate measured demand first, then prefer M4b Homebrew because its
native formula can reuse the stable sdist without authorizing a new upstream
artifact. Start M4a only after a separate decision accepts a complete portable
Windows artifact or installer. See the [WinGet](08-releases/02-winget-research.md)
and [Homebrew](08-releases/03-homebrew-research.md) research records.

## Known risks and assumptions

- `smartnuf-agent-tools` is now the published PyPI project; trusted publication remains restricted to the exact repository, workflow, and protected environment.
- The published wheel and sdist pass independent checksum and metadata audits; install, pin, and uninstall pass on Windows, Ubuntu, and macOS runners.
- Repository wrappers and the shared `.venv` are not part of the wheel contract.
- Windows ARM64/x64 emulation and macOS Intel/Apple-silicon coverage may require later expansion.
- On Windows ARM64, unconstrained Python 3.14 selected a native interpreter but `cryptography` lacked a wheel and required an unavailable MSVC linker. The initial `<3.14` Python bound makes `uv tool` choose a supported managed interpreter; Python 3.14 support must be revalidated before widening it.
- Native-versus-emulated interpreter selection and reporting is preserved as [issue #14](https://github.com/smartnuf/agent-tools/issues/14); it remains outside the completed M1 scope.
- Git Bash can exist outside `PATH`; discovery must verify provider-specific candidates rather than equating `shutil.which("bash")` with capability absence.
- WSL Bash is a separate Linux execution environment and must not silently satisfy a Windows-hosted Bash preference.

## Other backlog

The release milestones are the current priority. Existing non-release work remains valid:

- automate reviewed dependency upgrades;
- add functional PDF extraction and rendering fixtures;
- test bootstrap native-install branches directly;
- extend concurrent Windows PATH tests and restoration documentation;
- report package versions and executable architecture in `doctor`;
- expand Linux distribution and architecture coverage when justified;
- decide whether native repair or removal commands are warranted.

See [release milestones and acceptance gates](08-releases/README.md) and the [capability-foundation milestone](09-capabilities/README.md) for the detailed definition of completion.
