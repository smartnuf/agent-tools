# Platform installation and testing

## Recommended installation tools

| Platform | Python environment | Native tools | Notes |
|---|---|---|---|
| Windows 10/11 | `uv` via WinGet | WinGet for Poppler; Ghostscript route currently unavailable | The catalogue's Ghostscript WinGet package is absent upstream; see the evidence and provider gap below. |
| Debian/Ubuntu | `uv` standalone installer | `apt` | Poppler package is `poppler-utils`; Ghostscript is `ghostscript`. |
| Fedora/RHEL | `uv` standalone installer | `dnf` | Package availability must be checked for the specific distribution/release; current evidence is fixtures only. |
| Arch Linux | `uv` standalone installer | `pacman` | Use `poppler` and `ghostscript`. |
| macOS | `uv` via Homebrew or standalone installer | Homebrew | `brew install poppler ghostscript`. |

On Windows ARM64, a package may currently install an x64 build and run through Windows emulation. Clone bootstrap distinguishes the native host architecture from the bootstrap process architecture, verifies installed Python candidates, and normally selects a compatible native system interpreter. A translated Python fallback is visible and requires the explicit `-AllowEmulatedPython` flag. `agent-tools doctor` reports the executable actually found; architecture-sensitive work should be tested explicitly.

Native interpreter selection does not imply that every dependency publishes a
wheel for that architecture or that a compatible native compiler is installed.
Bootstrap reports the selected interpreter before package synchronization and
lets `uv pip` report an unavailable wheel or build-tool failure; it does not
silently retry under an emulated interpreter.

## Optional Python documents

The next-release wheel core requires no document libraries. The explicit
`smartnuf-agent-tools[documents]` extra supplies the existing library stack on
the same supported Python 3.11–3.13 range. Binary-wheel availability remains
architecture-dependent; core-only operation does not establish document support
on an untested architecture. Published v0.1.2 still bundles these libraries.

Use `agent-tools doctor --documents` to require document imports; plain doctor
reports their availability without counting optional failures. Both modes retain
native Poppler/Ghostscript checks. See the [installation and migration guide](../README.md#optional-document-libraries-next-release).
Checkout bootstrap/update retain their explicit document lock; they are not
core-only installation tests. No Python-extra operation installs native tools.

## Installed native setup

The CLI built from current `main` supports `agent-tools install poppler
ghostscript --dry-run` and the explicitly authorized form
`agent-tools install poppler ghostscript --allow-provider-mutation`. This is
next-release functionality, absent from published v0.1.2. `agent-tools` is the
sole ordinary-user command surface; Agent Tools itself is installed/updated by
`uv tool`, independently of these native providers.

Only named capabilities enter the request. Exact stored preferences for those
names apply; other enabled or unknown, structurally valid entries are ignored.
The whole configuration file still passes schema/path integrity checks.
Installation never changes desired configuration or agent settings. Plan/help
are read-only, no-op installation verifies existing providers, and host and
provenance outcomes are reported separately. Use `agent-tools install --help`
for the authoritative option and exit-status contract, also rendered in the
[CLI reference](cli-reference.md).

The supported manager must already be available: WinGet on Windows; apt, dnf
or pacman on their supported Linux environments; native Homebrew on macOS.
Agent Tools does not install a manager or configure privilege policy. Linux
system actions require verified GNU `timeout` and either root or existing
noninteractive sudo authorization for the exact supervised commands; an
interactive password prompt is not offered. Missing privileges or supervision
fail closed. Windows and macOS retain the existing M3 executor checks.
WSL-local requests operate inside Linux, not on the Windows host.

Process-only discovery refresh, final verification, cancellation and uncertain
recovery follow [Decision 0002](decisions/0002-native-capability-provider-model.md)
and [Decision 0009](decisions/0009-installed-capability-install.md).
No provider upgrade/removal, shell-profile change or cross-process coordination
is added. Real-provider and architecture coverage is classified below and remains tracked
in #104; installed no-op CI is not empty-host mutation proof.

## Clone native setup

The explicit native-install bootstrap flag delegates required-capability
detection, package-manager selection, the immutable provider plan, managed
execution, provenance persistence, and final verification to packaged Python.
The shell and PowerShell wrappers do not maintain package identifiers or native
installation commands. They install the editable package before delegation and
pass the dedicated provider-mutation authorization only when the user supplied
the existing native-install flag.

The delegated operation reports requested commands before mutation and keeps
the host outcome distinct from provenance durability. A repeated all-satisfied
run executes no provider command. Partial or uncertain execution is not retried
automatically. Process-only PATH refresh may be used for post-install
verification and is restored afterward; profile or persistent PATH changes
remain controlled by the separate explicit PATH flag.

## Desired capability configuration

Optional capabilities are enabled independently of detection and managed
mutation provenance. The v1 document is stored at
`%LOCALAPPDATA%\agent-tools\config.json` on Windows,
`$XDG_CONFIG_HOME/agent-tools/config.json` (or
`~/.config/agent-tools/config.json`) on Linux and WSL, and
`~/Library/Application Support/agent-tools/config.json` on macOS. Windows-host
and WSL configuration are therefore separate.

Use `agent-tools tools enable bash --allow-config-mutation` to accept the
catalogue's provider order, or add `--provider PROVIDER` to require one exact
provider supported in the current context. `tools disable bash
--allow-config-mutation` removes that desired entry only; it never invokes a
package manager or uninstalls Bash or Git. A real change to an existing valid
document creates a collision-safe sibling backup before atomic replacement.
Unreadable, malformed, unknown-version, symlinked, or non-regular state fails
closed and is preserved. See [Decision 0005](decisions/0005-desired-capability-state.md)
for the schema and failure contract.

## Claude Code Git Bash integration

On a native Windows host, Claude Code documents
`env.CLAUDE_CODE_GIT_BASH_PATH` in its user `settings.json` for selecting Git
Bash when automatic discovery is insufficient. Agent Tools can manage that one
member using the same selected, verified `git-bash` capability evidence:

```powershell
agent-tools integrations claude-code status
agent-tools integrations claude-code apply --allow-config-mutation
agent-tools integrations claude-code remove --allow-config-mutation
```

Claude settings are read from `%USERPROFILE%\.claude\settings.json`, or
`settings.json` below an absolute `CLAUDE_CONFIG_DIR`. The independent Agent
Tools phase record is
`%LOCALAPPDATA%\agent-tools\integrations\claude-code.json`. Apply and remove
preserve unrelated settings, back up existing files, validate replacements,
and reconcile interrupted cross-file phases without blindly replaying a
change. A matching unrecorded setting is not claimed. Linux, macOS, WSL, an
unverified/non-Git-Bash provider, and provider installation or removal remain
outside this adapter. See
[Decision 0006](decisions/0006-claude-code-git-bash-integration.md).

## Read-only capability discovery

The reviewed M1.5 package build supports `agent-tools tools list` and
`agent-tools tools status [CAPABILITY]` without changing the host. Bash
discovery behaves as follows:

| Platform | Host provider | Separate environment |
|---|---|---|
| Windows | Git Bash, discovered from Git for Windows even when Bash is outside process `PATH` | Bash in the default WSL distribution is reported separately and does not satisfy Windows-hosted Bash |
| Linux | System Bash on `PATH` | not applicable |
| macOS | System Bash on `PATH` | not applicable |

Status output includes the verified executable path and version, the execution
environment, and architecture where the executable exposes it. Discovery does
not install Git, Bash, or WSL; update `PATH`; or configure Codex, Claude Code,
or another agent.

## macOS without owning a Mac

Docker is not a macOS emulator: Docker Desktop runs Linux containers in a Linux virtual machine. A container therefore cannot validate macOS package management, launch services, filesystem behavior, or Apple-specific binaries.

Apple's macOS license generally confines macOS virtualization to Apple-branded hardware. Unofficial QEMU/Hackintosh setups on ordinary x86-64 or ARM64 PCs are fragile, unsupported, and not recommended for this repository.

Use these options instead:

1. GitHub Actions hosted macOS runners for routine Intel and Apple-silicon script checks.
2. A rented physical Mac service (for example EC2 Mac or MacStadium) for interactive or privileged integration tests.
3. A local Apple-silicon Mac with native virtualization if sustained macOS development becomes necessary.

The CI matrix is the sensible initial route: it costs little for a small private-repository workload, requires no local emulator, and tests on real supported macOS runner images.


## Evidence classes and current coverage

These describe observed evidence, not a guarantee for every version in a
platform family. Agent Tools itself remains a PyPI/uv product. The native
package managers below install prerequisites, not Agent Tools.

| Evidence class | Current owner | What it proves |
|---|---|---|
| Isolated package build | CI `package-artifacts`, release build | Restricted sdist rebuild, wheel contents/metadata and checksum identity |
| Installed artifact | CI `install-and-test`, core/documents and lifecycle drivers | Public CLI and optional dependency shapes outside a checkout; real old-release artifact migrations against a controlled local index |
| External native preseed | Native `external-preseed-and-test`, shared `install-native` action | Direct manager fixture preparation, discovery and all-satisfied CLI/bootstrap behaviour |
| Simulated provider mutation | Unit tests and `test_provider_execution_integration.py` | Planner/executor/provenance/failure contracts on fixtures and disposable subprocesses; no real native manager installation |
| Real installed-CLI mutation | #115, not yet complete | Required future proof of actual supported provider requests, final rediscovery/provenance and no-op repeat |
| Published artifact lifecycle | GitHub release smoke, PyPI smoke | Published artifact install/upgrade/reinstall/removal with externally seeded prerequisites; not native mutation by Agent Tools |

[PR #113's native run](https://github.com/smartnuf/agent-tools/actions/runs/34864622805)
provides this dated baseline (2026-09-14). Its generic runner labels resolved to
the following images. Later runs may differ; use each run's environment artifact
and setup log rather than carrying these versions forward.

| Observed host/image | Evidence | Limitation |
|---|---|---|
| Ubuntu 24.04.5 LTS; image `ubuntu-24.04`, `20260907.300.1` | apt-preseeded Poppler/Ghostscript, installed discovery/no-op | Not Debian, other Ubuntu releases, ARM64 or CLI-driven apt mutation |
| Windows Server 2025; image `windows-2025-vs2026`, `20260907.229.1` | WinGet-preseeded Poppler, Chocolatey-preseeded Ghostscript, installed discovery/no-op | Not Windows 10/11 or Windows ARM64; Chocolatey is not an Agent Tools adapter |
| macOS 26.6.2 build 25G83; image `macos-26-arm64`, `20260907.0351.1` | Homebrew-preseeded Poppler/Ghostscript, installed discovery/no-op on the ARM64 image | Not Intel macOS or older releases; no CLI-driven Homebrew mutation yet |

The shared external fixture now captures before/after JSON observations in
`native-environment-*` artifacts (90-day requested retention) and the job log.
They include OS/version/build, distinct host/process architecture indicators,
runner image/version, recording Python, uv, manager and executable versions,
and failure/missing-command observations. The recording Python is explicitly
not a claim about an installed application's interpreter. Missing architecture
or version observations remain unknown. Context indicators do not prove the
absence of virtualization or emulation. Artifact expiry is not durable release
qualification: the release coverage record must retain the relevant observed
matrix and link its exact qualification run.

### Windows Ghostscript provider gap

As checked on 2026-09-14, `ArtifexSoftware.GhostScript` is absent from the
[WinGet Artifex manifests](https://github.com/microsoft/winget-pkgs/tree/master/manifests/a/ArtifexSoftware).
The [upstream request](https://github.com/microsoft/winget-pkgs/issues/267547)
is blocked on interactive installation; [Artifex describes its removal of
silent installation](https://artifex.com/blog/ghostscript-10.01.0-disabling-silent-install-option).
The current catalogue still names this route, so planning can display it but
installation of a missing Windows Ghostscript is not currently demonstrated
as usable. Treat a provider failure as a failure and inspect the CLI's reported
outcome; there is no automatic fallback. Existing verified Ghostscript can
still satisfy discovery and no-op installation.

The CI Chocolatey fixture does not establish a supported Chocolatey adapter.
This evidence work neither adds one nor rebuilds or bypasses the publisher's
installer. A change of provider or installer policy needs its own decision.

### Untested variants and sensible follow-up

| Context | Current evidence class | Recommended way to close the gap |
|---|---|---|
| Windows 10/11 x64 | Code/fixtures; hosted evidence is Server | Periodic disposable client-OS VM or hardware qualification; do not relabel Server results |
| Windows ARM64 and x64 emulation | Architecture/selection fixtures; local Python 3.14 dependency failure reported, not a supported-range success | Periodic native hardware covering Python 3.11–3.13, native provider architecture and documents wheels |
| Debian, other Ubuntu versions | apt adapter plus fixtures; only the recorded Ubuntu runner exercised | Container matrix for package/discovery behaviour, labelled container evidence rather than full desktop/host integration |
| Fedora/RHEL and Arch | dnf/pacman adapters plus fixtures; no current hosted native mutation proof | Disposable distribution containers first; record package availability per release rather than promise an entire family |
| macOS Intel and older macOS | Code/fixtures; current recorded hosted image is ARM64 | Explicit Intel hosted runner when available, plus periodic older-version qualification if warranted |
| WSL | WSL-local versus Windows-host separation fixtures | Dedicated Windows/WSL qualification; ordinary Linux container evidence cannot prove Windows/WSL integration |
| Cross-host Windows installation from WSL; Claude adapter outside native Windows | Explicitly outside the accepted contracts | Do not treat as an evidence gap to fill without a new product decision |

#115 first targets fresh, separate apt/Homebrew Poppler+Ghostscript and WinGet
Poppler jobs through the installed CLI. Initially present providers must be
reported as no-op evidence, never removed or hidden to manufacture a mutation
result. The maintained matrix will gain mutation credit only from observed
successful provider requests and final verification. See the
[native evidence contract](plan/10-v0.2-productisation/06-native-evidence.md).
