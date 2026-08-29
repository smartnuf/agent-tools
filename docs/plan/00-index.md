# Plan status

- Last reconciled: 2026-08-29
- Current milestone: M2 — public PyPI release
- Current state: in-progress (M1.5 build-readiness evidence complete; trusted-publisher workflow and external configuration underway)
- Current user installation: versioned GitHub prerelease asset, repository clone, or source archive
- Target user installation: `uv tool install smartnuf-agent-tools`
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | complete | 5/5 | 0.5–1 day | none |
| M1 | Installable GitHub prerelease | complete | 9/9 | 4–7 days | none |
| M1.5 | Reviewed capability-ready package build | complete | 5/5 | 2–3.25 days | none |
| M2 | Public PyPI release | in-progress | 1/5 | 1–2 days | 0.75–1.5 days |
| M3 | Tested update and capability lifecycle | not-started | 0/8 | 3–6 days | 3–6 days |
| M4a | WinGet discovery | deferred | 0/4 | 2–4 days | 2–4 days |
| M4b | Homebrew discovery | deferred | 0/4 | 1.5–3 days | 1.5–3 days |

Estimated implementation effort through M3: **3.75–7.5 person-days remaining**. Native discovery channels are optional and excluded from that total; review time is reported separately.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the intended public distribution model.
- [Decision 0002](../decisions/0002-native-capability-provider-model.md) establishes the packaged native-capability boundary and safe provider semantics.
- The packaged [capability catalogue and detected-state model](../../src/agent_tools/capabilities.py) covers Poppler and Ghostscript with fixture-driven tests and `doctor` integration.
- The same catalogue distinguishes Git Bash, system Bash, and WSL Bash; the packaged read-only `tools list/status` interface is exercised outside a checkout.
- Distribution metadata, platform guidance, and the transferred-wheel CI matrix now describe and test the capability-discovery product boundary.
- [Planning protocol](README.md) defines task planning and progress reporting.
- [v0.1.1](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) is an audited GitHub prerelease with a wheel, source distribution, checksums, and reviewed notes.
- [Release run 33231066203](https://github.com/smartnuf/agent-tools/actions/runs/33231066203) installed, pinned, version-checked, and uninstalled the public wheel on Windows, Ubuntu, and macOS.
- [Revised smoke run 33232110219](https://github.com/smartnuf/agent-tools/actions/runs/33232110219) repeated the published-wheel lifecycle on all three platforms using Python 3.13 and `uv tool dir --bin`.

M1 is complete and its factual record is frozen except for corrections. M1.5
completed on 2026-08-29; public release work now resumes in M2. Actual M1.5
engineering effort was not recorded, so its accepted **2–3.25 person-day**
estimate remains the historical forecast; review and CI wait were excluded.

## Recommended next work

Implement [issue #19](https://github.com/smartnuf/agent-tools/issues/19), configuring the PyPI project and narrowly scoped GitHub OIDC trusted publisher without a long-lived upload token (M, **0.5–1 day**). Do not publish an untagged development wheel merely because it builds.

## Known risks and assumptions

- `smartnuf-agent-tools` returned no existing PyPI project on 2026-08-29, but the name is not reserved until publication and must be rechecked.
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
