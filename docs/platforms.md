# Platform installation and testing

## Recommended installation tools

| Platform | Python environment | Native tools | Notes |
|---|---|---|---|
| Windows 10/11 | `uv` via WinGet | WinGet | User-level PATH entry points only to `~/.agent-tools/bin`; package locations remain manager-owned. |
| Debian/Ubuntu | `uv` standalone installer | `apt` | Poppler package is `poppler-utils`; Ghostscript is `ghostscript`. |
| Fedora/RHEL | `uv` standalone installer | `dnf` | Both packages are available by their distribution names. |
| Arch Linux | `uv` standalone installer | `pacman` | Use `poppler` and `ghostscript`. |
| macOS | `uv` via Homebrew or standalone installer | Homebrew | `brew install poppler ghostscript`. |

On Windows ARM64, a package may currently install an x64 build and run through Windows emulation. `agent-tools doctor` reports the executable actually found; architecture-sensitive work should be tested explicitly.

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
