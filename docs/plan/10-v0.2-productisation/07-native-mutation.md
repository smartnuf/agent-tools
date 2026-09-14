# Installed native mutation evidence — #115

- Base: `042fc28a9b7482fe80368758ec63a21e574aed27` (PR #121), reconciled from PR #116.
- Milestone 8: open, 4/8 gates complete; #104 remains the end-to-end target.
- Estimate: 1–2 person-days, actual effort untracked; provider/review wait excluded.
- Merge owner: this stream. No concurrent repository mutation work.

## Scope and specification refinements

Implement the [#104 evidence contract](06-native-evidence.md) using separate
fresh hosted jobs, a transferred wheel and installed isolated Python. Target
apt/Homebrew Poppler+Ghostscript and WinGet Poppler. Do not change product
package mappings, manager identity, privilege or authorization policy to make
CI green. All-satisfied or unavailable-manager scenarios are explicit coverage
gaps, not successful mutation evidence. Fail the targeted mutation job when it
cannot supply its promised proof and inspect the evidence before any retry.

PR #116 observed the WinGet execution alias can execute but strict Python
resolution raises Windows error 1920. Existing production discovery and
executor revalidation both require a verified resolved identity. The fresh
Windows test may expose this product gap. If confirmed, characterize and track
a bounded identity repair separately; neither bypassing the alias with a guessed
binary nor accepting its version alone meets the accepted contract.

Independent safety adjudication refined the internal fixture-state setup:
retain Windows LOCALAPPDATA because WinGet and provider discovery use it;
isolate Linux XDG paths. On Windows/macOS derive actual state roots through
installed code and refuse pre-existing roots, including dangling links. Require
explicit mutation authority and the observable GitHub-hosted environment; never
use this path implicitly on a workstation. Leave resulting state/packages to
the disposable runner's teardown rather than add provider removal or risky
cleanup. This supersedes the earlier blanket LOCALAPPDATA isolation suggestion.

An initially unsatisfied capability can have partial executable evidence (for
example preinstalled Windows Xpdf pdftotext). Preserve and record it; do not
confuse capability unavailability with absence of every executable. Mutation
credit requires an actual catalogue-planned install with successful commands,
provenance and final verification. Already-satisfied capabilities remain no-op
only, even if another requested capability mutates.

## Implementation and validation plan

The driver runs under the installed tool's `python -I` outside the checkout,
checks package identity against the exact wheel and uses installed catalogue,
planner and state readers for observations. It invokes the public CLI for
planning and explicitly authorized mutation, validates actual command records,
rediscovery in a fresh process, and byte-identical provenance after an
unauthorized all-satisfied repeat. It asserts desired configuration remains
absent. No second package map or test substitution for production execution.

Capture host/tool evidence and the driver result even on failure; upload from a
separate caller-level always step, with independent job/step/command bounds.
Keep external-preseed jobs intact and separately named. Extend native-path
selection to relevant executor/provenance/driver changes so real tests cannot
silently disappear for the code they qualify.

Run full unit, POSIX syntax/PATH, doctor, CLI docs and ranged diff checks before
push. Build/check the wheel and exercise read-only driver snapshots using its
isolated interpreter locally; do not mutate this workstation. Hosted CI supplies
real manager and PowerShell evidence. Inspect every platform's result and exact
review head; preserve failures and allow at most one inspected same-head retry.

## Completion

Pending actual runs and review. Update the maintained platform matrix only from
observed outcomes; close #104 only when both its evidence gates are supported.
Final guides and release qualification remain separate tasks afterward.


Initial implementation validation: 419 unit tests, 36 guide invocations,
POSIX syntax/PATH checks, sdist-rebuilt wheel metadata and installed read-only
snapshots pass. The installed driver refuses execution without explicit
hosted-runner mutation authority. Local doctor has only the known absent native
tools. No local native packages were installed; hosted results/review pending.

The first hosted wave stopped at workflow validation: `runner.temp` is not
available in job-level environment definitions. No real mutation ran. The
correction initializes private paths in a step through GITHUB_ENV and passes
the same pinned actionlint 1.7.12 locally (official ARM64 archive, published
checksum verified). The public CLI dry-run now precedes internal plan capture,
so planning failures are recorded at the actual installed command surface.


The first review found two valid evidence/lifecycle defects. Fresh Windows
rediscovery and no-op repetition now reuse the production persisted-PATH reader
in a child-only environment, without changing the driver's or user's PATH.
The driver no longer kills the CLI on an independent aggregate timeout: M3
retains its existing command supervision, cancellation and provenance ownership.
Independent adjudication confirmed that removing competing parent-only
termination completes the established contract. The 23-minute step and 40-minute
job bounds remain infrastructure backstops; infrastructure cancellation means
failed/incomplete evidence, never orderly cleanup or mutation success. Full
validation now includes 420 tests and the unchanged M3 cancellation suite.

Run 34868870908 supplied actual successful apt/Homebrew requests for both
capabilities, final verification, provenance and no-op repetition. Windows
failed the public dry-run before mutation with WinError 1920; #118 owns the
focused identity prerequisite. #117 remains unmerged until that proof passes.
A subsequent review found the independent after-capture process also needed
the same PATH policy. It now runs through the installed read-only driver mode
and shared refresh helper, completing the driver/capture environment seam.
Local installed snapshots, authorization refusal and after-capture mode pass.
The remaining ShellCheck style finding is corrected with one grouped GITHUB_ENV
write, after setup-uv so the intended private tool paths are not overwritten.
Actionlint plus the official distro ShellCheck package now both run locally;
no system package was installed to obtain that validator.

PR #119/#118 merged after 426 tests, all hosted checks and clean exact-head
review. This branch is rebased onto that authoritative main, preserving the two
unpublished after-capture/validation corrections. Native path selection now
includes the shared manager-identity module and its tests. The combined baseline
passes 429 tests; installed-wheel snapshots, mutation authorization refusal and
after-capture pass locally. New real mutation evidence remains pending.

Run 34872132255 proved successful WinGet Poppler mutation, verification and
persisted provenance but failed final public reporting with UnicodeEncodeError
on a redirected cp1252 stream. No retry was made. Focused #120/PR #121 repaired
that boundary and merged after 429 tests, green checks and clean review. This
branch now integrates it; the combined baseline passes 432 tests. The completed
#117 review also found cancellation-module changes missing from native CI
selection; the module and selection regression are included in this wave.
