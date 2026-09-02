# Platform installation and testing

## Recommended installation tools

| Platform | Python environment | Native tools | Notes |
|---|---|---|---|
| Windows 10/11 | `uv` via WinGet | WinGet | User-level PATH entry points only to `~/.agent-tools/bin`; package locations remain manager-owned. |
| Debian/Ubuntu | `uv` standalone installer | `apt` | Poppler package is `poppler-utils`; Ghostscript is `ghostscript`. |
| Fedora/RHEL | `uv` standalone installer | `dnf` | Both packages are available by their distribution names. |
| Arch Linux | `uv` standalone installer | `pacman` | Use `poppler` and `ghostscript`. |
| macOS | `uv` via Homebrew or standalone installer | Homebrew | `brew install poppler ghostscript`. |

On Windows ARM64, a package may currently install an x64 build and run through Windows emulation. Clone bootstrap distinguishes the native host architecture from the bootstrap process architecture, verifies installed Python candidates, and normally selects a compatible native system interpreter. A translated Python fallback is visible and requires the explicit `-AllowEmulatedPython` flag. `agent-tools doctor` reports the executable actually found; architecture-sensitive work should be tested explicitly.

Native interpreter selection does not imply that every dependency publishes a
wheel for that architecture or that a compatible native compiler is installed.
Bootstrap reports the selected interpreter before package synchronization and
lets `uv pip` report an unavailable wheel or build-tool failure; it does not
silently retry under an emulated interpreter.

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
