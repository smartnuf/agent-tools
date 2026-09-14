# Plan status

- Last reconciled: 2026-09-02
- Current milestone: M3 — complete
- Current state: M3 completes tested upgrade, pin, rollback, safe provider mutation, desired-capability and agent-integration configuration, and removal preservation
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
| M3 | Tested update and capability lifecycle | complete | 9/9 | 6.5–11 days | none |
| M4a | WinGet discovery | deferred | 0/4 | 2–4 days | 2–4 days |
| M4b | Homebrew discovery | deferred | 0/4 | 1.5–3 days | 1.5–3 days |

Estimated implementation effort through M3: **complete**. Native discovery
channels and the independent document-dependency boundary are excluded; review
time is reported separately.

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
- [PR #44](https://github.com/smartnuf/agent-tools/pull/44) merged the protected, tokenless PyPI workflow and exact-tag artifact provenance checks.
- [v0.1.2](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.2) is the first stable GitHub release with signed provenance for its wheel and source distribution.
- [Publication run 33312422488](https://github.com/smartnuf/agent-tools/actions/runs/33312422488) published v0.1.2 through the protected PyPI environment and GitHub OIDC without a long-lived upload token.
- PyPI v0.1.2 metadata reports the expected project/version/Python range; its wheel and source-distribution sizes and SHA-256 digests match the GitHub release exactly.
- [PyPI lifecycle run 33313165322](https://github.com/smartnuf/agent-tools/actions/runs/33313165322) resolved the unpinned public package, version-checked, diagnosed, upgraded, exactly reinstalled, and removed it on Windows, Ubuntu, and macOS.
- [PR #72](https://github.com/smartnuf/agent-tools/pull/72) implements read-only installed-Python discovery, independent host/process evidence, deterministic native/system-first ranking, explicit-path clone bootstrap, and final-environment verification; its pure fixtures do not substitute for #49 platform evidence.
- Issue #49 adds repeatable pre-seeded Python, Git Bash, Poppler, and Ghostscript
  fixture evidence plus honest Windows, Ubuntu, and macOS hosted-runner checks;
  it explicitly does not claim hosted ARM64 coverage.
- Issue #50 adds deterministic, inspectable, read-only provider plans and
  catalogue-owned WinGet, apt, dnf, pacman, and Homebrew command adapters from
  immutable verified package-manager evidence; already-satisfied requests
  produce zero actions.
- [PR #78](https://github.com/smartnuf/agent-tools/pull/78) implements
  [issue #77](https://github.com/smartnuf/agent-tools/issues/77) by installing
  delegated architecture adjudication and an architectural closure sweep after
  #50, preserving human authority for product-policy choices before autonomous
  mutation work in #51.
- [Issue #51](https://github.com/smartnuf/agent-tools/issues/51) adds the
  packaged, explicitly authorized provider-plan executor with bounded command
  execution, structured attempted/observed change reports, mandatory
  rediscovery/final verification, partial-state recovery guidance, and
  idempotent repeat evidence on a disposable filesystem-backed host.
- [Issue #52](https://github.com/smartnuf/agent-tools/issues/52) adds the
  versioned, atomically replaced managed-state document governed by
  [Decision 0003](../decisions/0003-managed-state-provenance.md), preserving
  append-only Agent Tools mutation-request evidence without package ownership.
- [Issue #53](https://github.com/smartnuf/agent-tools/issues/53) makes both
  clone bootstrap wrappers delegate their explicit native-install flags to the
  packaged planner, managed executor, provenance boundary, and final verifier;
  unit and native-runner tests cover exact argument delegation, all-satisfied
  reruns, actionable failure evidence, and the absence of duplicate mappings.
- [Issue #54](https://github.com/smartnuf/agent-tools/issues/54) adds the
  versioned desired-capability document governed by
  [Decision 0005](../decisions/0005-desired-capability-state.md), explicit
  configuration-mutation authority, recoverable backup and atomic replacement,
  validation/restoration, unrelated-entry preservation, exact provider
  preferences, status reporting, and clone-bootstrap consumption without any
  provider-removal path.
- [Issue #27](https://github.com/smartnuf/agent-tools/issues/27) adds the
  native-Windows Claude Code adapter governed by
  [Decision 0006](../decisions/0006-claude-code-git-bash-integration.md): it
  consumes selected verified Git Bash evidence, mutates only the documented
  setting behind explicit authority, preserves unrelated configuration,
  restores prior state, and records independently reconcilable lifecycle
  phases without provider installation or removal.
- [Issue #55](https://github.com/smartnuf/agent-tools/issues/55) adds the
  checksum-verified, exact-artifact lifecycle test across Windows, Ubuntu, and
  macOS: direct-wheel v0.1.1 install, published-v0.1.2 upgrade and exact
  reinstall, v0.1.1 rollback, and application removal with byte-identical
  current desired state and the externally owned Bash provider preserved.

M1 is complete and its factual record is frozen except for corrections. M1.5
completed on 2026-08-29; M2 completed on 2026-08-30 with the first stable PyPI
release; M3 completed on 2026-09-02. Actual M1.5, M2, and M3 engineering effort
was not recorded, so their accepted estimates remain the historical forecasts;
review and CI wait were excluded.

## Recommended next work

M3 has no remaining implementation task. Keep exact-artifact application
lifecycle evidence separate from native provider removal, which remains
unsupported. M4 discovery channels remain deferred until user demand justifies
their maintenance burden. Issue #56 supplies the product-first README and PyPI
metadata presentation before the next release; the independent document
dependency-boundary decision remains human-reserved backlog rather than an M3
acceptance gate.

## Known risks and assumptions

- `smartnuf-agent-tools` is now the published PyPI project; trusted publication remains restricted to the exact repository, workflow, and protected environment.
- The published wheel and sdist pass independent checksum and metadata audits; install, pin, and uninstall pass on Windows, Ubuntu, and macOS runners.
- Repository wrappers and the shared `.venv` are not part of the wheel contract.
- Windows ARM64/x64 emulation and macOS Intel/Apple-silicon coverage may require later expansion.
- On Windows ARM64, unconstrained Python 3.14 selected a native interpreter but `cryptography` lacked a wheel and required an unavailable MSVC linker. The initial `<3.14` Python bound makes `uv tool` choose a supported managed interpreter; Python 3.14 support must be revalidated before widening it.
- Native/system-first interpreter selection and reporting is the first M3 implementation slice in [issue #14](https://github.com/smartnuf/agent-tools/issues/14). The bootstrap process architecture must not redefine the host or silently displace a suitable native provider.
- Current uv defaults prefer an already-installed managed Python over an installed system Python. M3 selection must rank verified candidates itself and pass an explicit interpreter path rather than relying on a version-only request.
- Git Bash can exist outside `PATH`; discovery must verify provider-specific candidates rather than equating `shutil.which("bash")` with capability absence.
- WSL Bash is a separate Linux execution environment and must not silently satisfy a Windows-hosted Bash preference.

## Other backlog

The release milestones are the current priority. Existing non-release work remains valid:

- automate reviewed dependency upgrades;
- add functional PDF extraction and rendering fixtures;
- extend concurrent Windows PATH tests and restoration documentation;
- report package versions and executable architecture in `doctor`;
- expand Linux distribution and architecture coverage when justified;
- decide whether native repair or removal commands are warranted.

See [release milestones and acceptance gates](08-releases/README.md) and the [capability-foundation milestone](09-capabilities/README.md) for the detailed definition of completion.
