# Native-provider evidence: #104, #114 and #115

- Base: `b622308427150f2f9e10360791e8f12a7beba441` (PR #113).
- Milestone: v0.2 productisation, GitHub milestone 8, open; 4/8 gates complete.
- #114: discovery/specification and environment capture, 0.5–1 person-day.
- #115: installed-CLI mutation matrix and observed results, 1–2 person-days.
- Actual effort untracked; review/provider wait excluded. One merge owner.

## Intent and characterisation

Issue #104 needs honest evidence that the installed public CLI can drive the
existing native providers, plus an explicit OS/version/architecture matrix.
Existing external preseed jobs prove detection and all-satisfied behaviour;
M3 subprocess fixtures prove executor semantics, not real manager mutation.
Neither is a replacement for the intended end-to-end acceptance.

This is test infrastructure, not new product mutation authority. Real hosted
installation is privileged, externally coupled, persistent for the runner's
lifetime and platform-dependent. Therefore preserve existing provider identity,
authorization, bounded execution, provenance and verification contracts; use
fresh disposable runners, retain failure evidence, and separate each evidence
class. Local development never installs or removes host packages for this task.
Read-only environment capture is low risk and must not export arbitrary
environment variables or secrets.

## Discovery and mapping

[Native run 34864622805](https://github.com/smartnuf/agent-tools/actions/runs/34864622805)
on PR #113 reports Ubuntu 24.04.5 (image `20260907.300.1`), Windows Server 2025
(image `windows-2025-vs2026`, `20260907.229.1`), and macOS 26.6.2 build 25G83
(image `macos-26-arm64`, `20260907.0351.1`). These are external-preseed results,
not empty-host mutation. Generic `*-latest` labels cannot establish Windows
10/11 or Intel macOS coverage. Exact architecture/process observations will be
captured instead of extrapolated from labels.

The catalogue names `ArtifexSoftware.GhostScript` for WinGet, but the current
[Artifex manifest directory](https://github.com/microsoft/winget-pkgs/tree/master/manifests/a/ArtifexSoftware)
has no Ghostscript package. The [upstream request](https://github.com/microsoft/winget-pkgs/issues/267547)
is blocked on an interactive-only installer. [Artifex's explanation](https://artifex.com/blog/ghostscript-10.01.0-disabling-silent-install-option)
records its deliberate removal of silent installation from distributed Windows
binaries. Existing CI installs Ghostscript through Chocolatey; this is external
fixture preparation, not an Agent Tools provider. No fallback, catalogue
remapping, source rebuild or licensing interpretation is authorized here.

Independent architecture/safety adjudication on 2026-09-14 found that #104's
"where safely practical" scope permits apt/Homebrew Poppler+Ghostscript and
WinGet Poppler evidence with the Windows Ghostscript gap disclosed. It does not
require a new product decision. Preserve the existing catalogue in this slice.

## #114 implementation and validation plan

Add a shared read-only environment recorder to the external fixture action:
record OS/build, host and process architecture evidence separately, execution
context indicators, runner image/version, recording Python, uv, managers and
observable provider executable versions. Command probes have fixed version-only
arguments, bounded duration and output; errors remain observations. Write JSON
and job-summary evidence before and after preparation, including failures, and
retain uploaded artifacts. Never dump the full environment. The later mutation
slice adds installed interpreter/catalogue/provenance observations.

Classify the workflows and publish a matrix in `docs/platforms.md`. No native
mutation gate completes from this slice. Run the full unit suite, shell/PATH
checks, doctor, documentation drift checks, ranged diff check, required CI and
exact-head automated review. Hosted Windows supplies unavailable local
PowerShell validation. Check uploaded capture artifacts from all three hosts.

## #115 required mutation oracle and closure sweep

1. Install the transferred wheel in a private uv tool environment and run its
   public CLI outside the checkout. Record wheel SHA-256 and source head.
2. Query the installed catalogue/discovery in an isolated installed Python
   process. Require each targeted capability initially absent for mutation
   credit. Do not uninstall, hide or replace pre-existing providers to force
   that condition. Initially satisfied cases supply no-op evidence only; if a
   primary pair cannot be exercised, investigate another disposable image.
3. Use only the supported manager and existing runner privilege configuration.
   Display the dry-run plan, then explicitly authorize the same named request
   through `agent-tools install ... --allow-provider-mutation`. Do not add
   package mappings, privilege setup or manager fallbacks to the driver.
4. Isolate XDG/LOCALAPPDATA state. On macOS preflight the actual documented home
   state path, refuse pre-existing state, and never substitute HOME or add a
   product config-path override. Cleanup may remove only unchanged owned state.
5. Require successful CLI status, production-reader-valid request records,
   actual command evidence, non-ownership and verified final outcomes. Record
   catalogue-derived manager/package identities and execution context.
6. Rediscover in a fresh installed process. Repeat the named request and require
   no provider commands and byte-identical provenance. Desired configuration,
   agent settings and external providers remain outside cleanup authority.
7. Bound job, step and subprocess lifetimes. Retain partial/failure outcomes and
   upload evidence on failure. Do not retry uncertain execution automatically;
   the existing one-inspected-same-head CI retry maximum remains in force.
8. Keep external preseed and real mutation jobs separate. Publish the exact
   observed OS/build, host/process architecture, runner image, Python/uv,
   manager and provider versions; distinguish hosted, simulated, manual,
   untested and unsupported contexts. A green skip never counts as mutation.

These cover identity, authority, privilege, provenance, lifecycle, partial
failure, retry, idempotence, verification, platform and state preservation.
Product schemas, provider support policy, licensing and broader roadmap remain
unchanged. Human adjudication is required only if completing the evidence would
require crossing those boundaries.

## Completion and next task

#114 implementation is complete on merge after exact-head review/CI and
three-host capture artifact inspection. Local validation: 416 unit tests,
36 parsed guide invocations, POSIX syntax/PATH tests and read-only environment
capture pass. Local doctor reports only the known absent Poppler/Ghostscript;
PowerShell validation and real hosted observations require Windows CI. No
product/native host changes or additional acceptance gates are claimed.
#104 stays open across both slices; neither of its two gates is claimed here.
Next: #115, using the recorded contract and actual runner conditions. Final
v0.2 guides and release qualification remain separate after #104.
