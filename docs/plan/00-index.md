# Plan status

- Last reconciled: 2026-08-28
- Current milestone: M0 — distribution foundations
- Current state: in-progress
- Current user installation: repository clone or source archive
- Target user installation: `uv tool install <distribution-name>`
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | in-progress | 3/5 | 0.5–1 day | 0.25–0.5 day |
| M1 | Installable GitHub prerelease | not-started | 0/8 | 4–7 days | 4–7 days |
| M2 | Public PyPI release | not-started | 0/5 | 1–2 days | 1–2 days |
| M3 | Tested update lifecycle | not-started | 0/6 | 2–4 days | 2–4 days |
| M4a | WinGet discovery | deferred | 0/4 | 2–4 days | 2–4 days |
| M4b | Homebrew discovery | deferred | 0/4 | 1.5–3 days | 1.5–3 days |

Estimated effort through M3: **7.25–13.5 person-days remaining**. Native discovery channels are optional and excluded from that total.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the intended public distribution model.
- [Planning protocol](README.md) defines task planning and progress reporting.

These are foundations, not evidence that the current wheel is ready for public installation.

## Recommended next work

Complete M0 with a focused packaging-discovery task (S, **0.25–0.5 day**):

1. Verify availability and suitability of the intended public distribution name.
2. Inventory which current commands and resources assume a repository checkout.
3. Map `requirements.in` entries to required, optional, or development dependencies.
4. Create or identify the actionable M1 work items and record their evidence links here.

Do not publish the existing `agent-tools-local` wheel as the public release merely because it builds.

## Known risks and assumptions

- The permanent registry distribution name remains undecided.
- The current wheel declares no runtime dependencies and contains only `src/agent_tools`.
- Repository wrappers and the shared `.venv` are not part of the wheel contract.
- M1 may reveal checkout assumptions in the CLI or bootstrap behaviour; its estimate includes limited contingency for that discovery.
- Windows ARM64/x64 emulation and macOS Intel/Apple-silicon coverage may require later expansion.

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
