# WinGet App Execution Alias identity — #118

- Base: `4888887cd19f5f17e1556a011392b06e2d48d49a`, current main.
- Milestone 8 open; 4/8 gates complete. Focused prerequisite for #115/#104.
- Estimate: 0.5–1.5 person-days including discovery/repair; actual effort untracked.
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

Discovery experiment pending. No product implementation or new readiness gate
is claimed. The broader #104 acceptance stays open.
