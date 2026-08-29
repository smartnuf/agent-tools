# Plan status

- Last reconciled: 2026-08-29
- Current milestone: M1 — installable GitHub prerelease
- Current state: evidence correction in progress
- Current user installation: versioned GitHub prerelease asset, repository clone, or source archive
- Target user installation: `uv tool install smartnuf-agent-tools`
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | complete | 5/5 | 0.5–1 day | none |
| M1 | Installable GitHub prerelease | in-progress | 8/9 | 4–7 days | less than 0.5 day |
| M2 | Public PyPI release | not-started | 0/5 | 1–2 days | 1–2 days |
| M3 | Tested update lifecycle | not-started | 0/6 | 2–4 days | 2–4 days |
| M4a | WinGet discovery | deferred | 0/4 | 2–4 days | 2–4 days |
| M4b | Homebrew discovery | deferred | 0/4 | 1.5–3 days | 1.5–3 days |

Estimated implementation effort through M3: **3–6 person-days remaining**. Native discovery channels are optional and excluded from that total; review time is reported separately.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the intended public distribution model.
- [Planning protocol](README.md) defines task planning and progress reporting.
- [v0.1.1](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) is an audited GitHub prerelease with a wheel, source distribution, checksums, and reviewed notes.
- [Release run 33231066203](https://github.com/smartnuf/agent-tools/actions/runs/33231066203) installed, pinned, version-checked, and uninstalled the public wheel on Windows, Ubuntu, and macOS.

M1 awaits a fresh three-platform run of the revised published-release smoke contract. Its release artifact remains valid; only the evidence for the PATH-independent, Python-3.13-pinned user command is outstanding.

## Recommended next work

Run the manually dispatched published-release smoke workflow against `v0.1.1`, record its result, and close M1. Then begin [issue #19](https://github.com/smartnuf/agent-tools/issues/19), configuring the PyPI project and trusted publisher without a long-lived upload token (M, **0.5–1 day**).

Do not publish an untagged development wheel merely because it builds.

## Known risks and assumptions

- `smartnuf-agent-tools` returned no existing PyPI project on 2026-08-29, but the name is not reserved until publication and must be rechecked.
- The published wheel and sdist pass independent checksum and metadata audits; install, pin, and uninstall pass on Windows, Ubuntu, and macOS runners.
- Repository wrappers and the shared `.venv` are not part of the wheel contract.
- Windows ARM64/x64 emulation and macOS Intel/Apple-silicon coverage may require later expansion.
- On Windows ARM64, unconstrained Python 3.14 selected a native interpreter but `cryptography` lacked a wheel and required an unavailable MSVC linker. The initial `<3.14` Python bound makes `uv tool` choose a supported managed interpreter; Python 3.14 support must be revalidated before widening it.
- Native-versus-emulated interpreter selection and reporting is preserved as [issue #14](https://github.com/smartnuf/agent-tools/issues/14); it remains outside the completed M1 scope.

## Other backlog

The release milestones are the current priority. Existing non-release work remains valid:

- automate reviewed dependency upgrades;
- add functional PDF extraction and rendering fixtures;
- test bootstrap native-install branches directly;
- extend concurrent Windows PATH tests and restoration documentation;
- report package versions and executable architecture in `doctor`;
- expand Linux distribution and architecture coverage when justified;
- decide whether native repair or removal commands are warranted.

See [release milestones and acceptance gates](08-releases/README.md) for the detailed definition of completion.
