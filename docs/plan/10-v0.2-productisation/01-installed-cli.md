# #103: Installed capability CLI

Base: `d1cfa51723963cbe5b66b2fbb3dde26301fe898c`.
Milestone: [v0.2 productisation](https://github.com/smartnuf/agent-tools/milestone/8).
Acceptance: the first two v0.2 gates, one installed ordinary-user command surface
and named-capability installation through the M3 lifecycle.

## Discovery, mapping and specification

The [discovery record](https://github.com/smartnuf/agent-tools/issues/103#issuecomment-5662650917)
and [human decision](https://github.com/smartnuf/agent-tools/issues/103#issuecomment-5662820905)
resolve request membership. [Decision 0009](../../decisions/0009-installed-capability-install.md)
specifies the public contract before implementation.

Public compatibility and host mutation are high-risk dimensions; implementation
novelty is low because M3 already supplies the engine. Preserve its validated
identity, privilege, persistence and partial-result boundaries. Share request
planning after consumer-specific configuration selection; use the managed
executor and existing report/success handling without duplicating mappings.
No environmental experiment requires mutating this workstation: use existing
M3 disposable fixtures and read-only/no-op installed checks; real-provider CI
coverage remains #104.

## Entry-point inventory

| Paths | Role and disposition |
| --- | --- |
| Installed `agent-tools`, `src/agent_tools/__main__.py` | Product CLI; add install; existing diagnostic/config/integration operations already packaged |
| `bin/agent-tools`, `bin/agent-tools.cmd` | Development/compatibility launchers for the same CLI; retain in Git |
| `bin/agent-python`, `bin/agent-python.cmd` | Development shared-interpreter wrappers; retain in Git |
| `scripts/bootstrap.sh`, `scripts/bootstrap.ps1` | Development/CI setup and compatible native setup; retain clone expansion |
| `scripts/update.sh`, `scripts/update.ps1` | Checkout dependency synchronization and diagnostics; installed app update remains uv's responsibility |
| `scripts/path.sh`, `scripts/path.ps1` | Opt-in checkout PATH/profile compatibility with backup; retain |
| `scripts/select-python.py` | Pre-environment bootstrap bridge to packaged Python selection; retain |
| `scripts/select_native_integration.py` | CI path selection; retain |
| `scripts/release.py` | Release/checksum verification used by CI/tests; retain |

None is obsolete solely because it is a script. The initial wheel excludes all
of them; the initial sdist includes all of them. Restrict the latter to source,
build metadata, README and license, then verify building a wheel from it.

## Plan and estimate

1. Commit the specification, inventory and milestone activation.
2. Share native orchestration, add scoped desired-state consumption and installed
   parser dispatch with meaningful help; retain bootstrap compatibility.
3. Add scope/safety/result tests and installed-wheel smoke checks, restrict sdist
   contents, and update curated README/platform/packaging guidance.
4. Run full validation and obtain exact-head CI/review; address findings through
   at most six multi-commit/single-push correction waves before integration.
5. Reconcile roadmap evidence and issue completion after durable evidence.

Estimate: 1.5–2 person-days, excluding CI/review wait. The separate #106 generated
reference task adds 0.25–0.75 day and remains separate to preserve the two-day
reviewable-task limit. All command metadata stays in argparse for that task.
This stream owns integration; no concurrent implementation stream is active.

Validation: repository Python unit suite; available PowerShell/POSIX syntax and
PATH checks; doctor (report optional host gaps); wheel and sdist metadata/content
checks, wheel rebuilt from sdist, and installed CLI outside a checkout. Tests
must exercise named-only scope, config/preferences, dry-run/refusal/no-op,
managed result failures and interrupts, and retain all existing M3 tests.

No dependency-boundary (#57), real-provider/platform expansion (#104), release
publication, or future-research work is included. Recommend #106 after #103 so
the reference reflects the final command surface. Actual effort is not tracked;
update remaining effort when implementation evidence exists.
