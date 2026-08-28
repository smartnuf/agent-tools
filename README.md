# Agent Tools

A user-level, agent-neutral home for reusable Python helpers, command wrappers, and native document-tool setup. The repository is intended to live at `~/.agent-tools` and to be usable by Codex, Claude Code, terminal users, and other local agents.

The checked-in repository contains source and recipes. Machine-local state stays untracked:

- `.venv/` — shared Python environment
- `.tools/` — exceptional locally managed binaries
- `.cache/`, `tmp/`, and generated output

## Initial tool policy

- **Python and packages:** use [`uv`](https://docs.astral.sh/uv/) to create and update `.venv` from `requirements.txt`.
- **Windows native tools:** prefer WinGet; use Chocolatey or Scoop only where WinGet is unsuitable.
- **Debian/Ubuntu:** use `apt`; Fedora/RHEL use `dnf`; Arch uses `pacman`.
- **macOS:** use Homebrew. Test scripts on GitHub-hosted macOS runners until physical Mac hardware is available.
- **Poppler and Ghostscript:** install through the native package manager. Do not copy opaque executables into this repository.

## Layout

```text
bin/                    stable user-facing wrappers
config/tools.toml       desired native tools and executable probes
docs/platforms.md       platform policy and macOS testing notes
scripts/                bootstrap, update, PATH, and validation scripts
src/agent_tools/        reusable standard-library Python helpers
tests/                  unit tests
requirements.txt        shared third-party Python packages
```

## Get the source

Until packaged releases are available, clone the repository into the conventional user-level location:

```sh
git clone https://github.com/smartnuf/agent-tools.git "$HOME/.agent-tools"
```

Alternatively, download the repository's [main-branch ZIP archive](https://github.com/smartnuf/agent-tools/archive/refs/heads/main.zip), extract it, and rename or move the extracted directory to `~/.agent-tools`. An archive installation works normally but cannot be updated with `git pull`; download a newer archive or replace it with a clone to update.

## Bootstrap

PowerShell 7+ on Windows:

```powershell
Set-Location $HOME\.agent-tools
.\scripts\bootstrap.ps1 -InstallUv -InstallNativeTools -AddToPath
agent-tools doctor
```

Linux or macOS:

```sh
cd "$HOME/.agent-tools"
./scripts/bootstrap.sh --install-uv --install-native-tools --add-to-path
agent-tools doctor
```

All three mutation flags are opt-in. Without them, bootstrap creates or refreshes `.venv` only when `uv` is already available, and prints actionable diagnostics.

To refresh Python packages later:

```powershell
.\scripts\update.ps1
```

or:

```sh
./scripts/update.sh
```

The `agent-python` wrapper runs the shared interpreter. The `agent-tools` wrapper runs the maintenance CLI. Agents can invoke either by absolute path without relying on `PATH`.

## Scope and security

This is a convenience environment, not a substitute for project-specific dependencies. A project's own environment and lock file remain authoritative. Keep secrets, credentials, private data, and machine-local state out of this public repository.

## Development and operation plan

Keep changes small and portable. Develop reusable behaviour in `src/agent_tools/`, unit-test it without modifying the host, then exercise bootstrap and native installations on disposable GitHub-hosted Windows, Ubuntu, and macOS runners. CI bootstraps twice to catch common idempotency failures and runs `doctor` against real Poppler, Ghostscript, and Python packages. Native installation on a workstation remains explicitly opt-in.

For routine operation:

1. Pull reviewed changes.
2. Run the platform update script to refresh `.venv`.
3. Run `agent-tools doctor` and investigate failures before relying on the environment.
4. Upgrade native programs through the operating system package manager, not by replacing files in this repository.

## Current TODO

- Publish installable release artifacts for `smartnuf/agent-tools`, including Python wheels and source distributions, release checksums, and documented upgrade paths; keep clone and source-archive installation supported.
- Add a release workflow that builds artifacts from a clean checkout, tests them on supported platforms, and publishes only from version tags with least-privilege GitHub permissions.
- Add a generated, reviewed lock file so ordinary updates are reproducible; retain a separate explicit dependency-upgrade workflow.
- Add fixture-based functional tests that extract text and render a small known PDF with both Python and native tools.
- Exercise each bootstrap script's native-install branch directly; current CI installs native prerequisites separately before testing bootstrap.
- Test PATH application against isolated temporary profiles, including repeated application and restoration.
- Record installed package versions and executable architecture in `doctor`, especially for Windows ARM64/x64 emulation.
- Add Linux distribution container coverage beyond Ubuntu and explicit Intel versus Apple-silicon macOS jobs where runner availability and cost justify them.
- Decide whether native-tool removal/repair commands are useful. Prefer disposable VMs for installation testing rather than promising perfect rollback on a workstation.
