# Plan status

- Last reconciled: 2026-08-29
- Current milestone: M1 — installable GitHub prerelease
- Current state: in-progress
- Current user installation: repository clone or source archive
- Target user installation: `uv tool install <distribution-name>`
- Estimate basis: one experienced contributor; engineering effort, excluding review and external wait time

## Status summary

| Milestone | Outcome | State | Acceptance gates | Incremental estimate | Estimated remaining |
|---|---|---|---:|---:|---:|
| M0 | Distribution decision and executable roadmap | complete | 5/5 | 0.5–1 day | none |
| M1 | Installable GitHub prerelease | in-progress | 2/9 | 4–7 days | 2.5–4.5 days |
| M2 | Public PyPI release | not-started | 0/5 | 1–2 days | 1–2 days |
| M3 | Tested update lifecycle | not-started | 0/6 | 2–4 days | 2–4 days |
| M4a | WinGet discovery | deferred | 0/4 | 2–4 days | 2–4 days |
| M4b | Homebrew discovery | deferred | 0/4 | 1.5–3 days | 1.5–3 days |

Estimated implementation effort through M3: **5.5–10.5 person-days remaining**. Native discovery channels are optional and excluded from that total; review time is reported separately.

Gate counts are binary readiness measures. Estimates are ranges and must be revised when implementation reveals new facts.

## Evidence already present

- Cross-platform clone bootstrap and tests run in `.github/workflows/ci.yml` on Windows, Ubuntu, and macOS.
- `pyproject.toml` builds the `agent-tools` entry point using Hatchling.
- The repository has platform bootstrap, update, PATH, and diagnostic implementations.
- [Decision 0001](../decisions/0001-distribution-model.md) establishes the intended public distribution model.
- [Planning protocol](README.md) defines task planning and progress reporting.

These are foundations, not evidence that the current wheel is ready for public installation.

## Recommended next work

Begin [issue #6](https://github.com/smartnuf/agent-tools/issues/6), isolated wheel and sdist tests (M, **0.5–1 day**), using the checkout-independent command and diagnostics established by issue #5.

Do not publish the existing `agent-tools-local` wheel merely because it builds.

## Known risks and assumptions

- `smartnuf-agent-tools` returned no existing PyPI project on 2026-08-29, but the name is not reserved until publication and must be rechecked.
- The wheel declares the supported document libraries as runtime dependencies and its command works without a checkout; full isolated dependency installation remains to be proven by issue #6.
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
