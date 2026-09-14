# WinGet App Execution Alias identity — #118

- Base: `4888887cd19f5f17e1556a011392b06e2d48d49a`, current main.
- Milestone 8 open; 4/8 gates complete. Focused prerequisite for #115/#104.
- Estimate: 0.5–1.5 person-days including discovery/repair; review/CI wait excluded; actual effort untracked.
- Single merge owner. PR #117 remains unmerged until its Windows proof passes.

## Confirmed problem and intent

[Native run 34868870908](https://github.com/smartnuf/agent-tools/actions/runs/34868870908)
for PR #117 head `38abd451921111d2cbccbce7318380a582450ab2` shows the installed
public `agent-tools install poppler --dry-run` failing before mutation with
WinError 1920 on the working WinGet app alias. Read-only capture reports WinGet
v1.11.510. Ubuntu/macOS real mutations passed. This is a product identity gap,
not an unavailable manager, provider failure, or reason to add a fallback.

Preserve Decision 0002's alias invocation and verified resolved identity plus
per-action revalidation. Do not use non-strict path resolution, bypass the alias
with a guessed package path, alter PATH, parse undocumented reparse data, or
change provider/licensing/persistence policy.

## Characterisation, discovery and conditional mapping

The boundary is Windows process activation and identity before privileged native
mutation. Identity, process lifetime, external platform behavior and verification
are material risks; new package-manager or persistence abstractions are not
needed. [CPython's upstream explanation](https://github.com/python/cpython/issues/104336)
distinguishes AppExec activation links from ordinary filesystem symlinks and
warns that their payload format is undocumented.

Microsoft documents the [AppExec reparse tag](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-tags)
and [QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew).
A bounded read-only experiment must first establish that the owned process
handle from `winget --version` identifies the actual manager image, not an
activation broker, and that its absolute regular target can be strictly resolved.
The experiment records observations; its success is not product repair evidence.

Independent architecture adjudication classifies the following design as
conditional contract completion. If the experiment supports it, recognize only
Windows WinGet AppExec aliases, observe their launched image through an owned
handle under existing bounded supervision, and share resolution between initial
discovery and immediate executor revalidation. Preserve invocation/target in the
existing PackageManagerState. Reject unexpected tags, missing/inaccessible
paths, malformed/query-failed observations, unsuccessful probes and retargeting.
A failure to establish identity returns to discovery, not weaker verification.

## Closure and implementation plan

- Use fixed absolute-alias `--version` arguments and an owned process handle;
  avoid PID lookup/reuse and guessed package directories.
- Keep image observation narrow and within existing post-launch cleanup and
  timeout accounting. Query, buffer, observer, cancellation, timeout and fast-exit
  failures must preserve cleanup/fail-closed behavior.
- Test shared discovery/revalidation, retargeted identities, unexpected reparse
  tags, missing/inaccessible targets, failed observation, and normal files and
  symlinks. Do not change persistent schemas or unrelated executor semantics.
- Identity remains observed and revalidated, not atomically pinned against
  concurrent replacement; cross-process exclusion is not promised.
- Run the full local baseline, workflow validation including ShellCheck, artifact
  build/installed read-only checks, required hosted CI and exact-head automated
  review. This workstation receives no native packages or Windows emulation.
- Prove installed Windows dry-run and executor identity verification on a real
  runner; then integrate this focused fix before rebasing #117 for actual WinGet
  mutation/provenance/no-op evidence. Both streams have the same merge owner.

## Status

The [read-only experiment](https://github.com/smartnuf/agent-tools/actions/runs/34869512816)
on Windows Server 2025 observed WinGet v1.11.510's actual DesktopAppInstaller
image through its owned process handle; the image is regular and strictly
resolvable. Independent closure adjudication accepted the bounded repair as
completion of Decision 0002, with no new product/persistence/mutation policy.

The implementation shares strict manager resolution between discovery and
executor revalidation. Only positively tagged Windows WinGet activation aliases
use a fixed bounded version probe and documented process-image query. The
existing supervisor owns observation failure cleanup and elapsed-time accounting.
Normal files and symlinks retain strict filesystem resolution. The installed
Windows experiment now also checks production identity revalidation and public
CLI dry-run. Exact-head hosted validation and review remain pending; #104 remains
open and no readiness gate advances here.

First-head review found a missing roadmap dependency (reconciled in the index)
and reliance on setup-uv's exported tool directory (the observed run passed, but
the workflow now derives it explicitly with `uv tool dir`).

Local validation: 425 unit tests, generated reference/36 guide invocations, POSIX
syntax/PATH checks, actionlint with ShellCheck, wheel/sdist contents and installed
CLI checks pass. Doctor reports only this workstation's known absent Poppler and
Ghostscript. Independent implementation closure found no blocking architecture
defect; requested observation-path interruption/force-abort tests now pass.

The implementation head's hosted checks all passed, including installed Windows
production proof ([run 34870474749](https://github.com/smartnuf/agent-tools/actions/runs/34870474749)).
The next review found estimate-basis wording and probe artifact rerun handling.
Forecasts consistently exclude review/CI wait. The explicitly selected artifact
is now replaced atomically; failed replacement preserves prior bytes and does
not mask an original observation failure. Full local validation passes 426 tests.
