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
docs/packaging.md       public distribution and dependency contract
docs/platforms.md       platform policy and macOS testing notes
scripts/                bootstrap, update, PATH, and validation scripts
src/agent_tools/        reusable standard-library Python helpers
tests/                  unit tests
requirements.in         reviewed direct Python dependencies
requirements.txt        generated, fully pinned Python environment lock
```

## Install the packaged prerelease

The current [v0.1.1 GitHub prerelease](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.1) is pinned to its reviewed release asset. Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) through a trusted package manager, then run:

```sh
uv tool install --python 3.13 "https://github.com/smartnuf/agent-tools/releases/download/v0.1.1/smartnuf_agent_tools-0.1.1-py3-none-any.whl"
```

Verify it without assuming uv's executable directory is already on `PATH`.

PowerShell:

```powershell
& "$(uv tool dir --bin)\agent-tools.exe" --version
```

Linux or macOS:

```sh
"$(uv tool dir --bin)/agent-tools" --version
```

To make `agent-tools` directly discoverable in future shells, `uv tool update-shell` can update the user shell configuration. That is an explicit profile change; review uv's reported change and open a new shell afterward.

The versioned URL is the pin. To restore that exact release if its isolated environment is damaged:

```sh
uv tool install --python 3.13 --reinstall "https://github.com/smartnuf/agent-tools/releases/download/v0.1.1/smartnuf_agent_tools-0.1.1-py3-none-any.whl"
```

To remove it:

```sh
uv tool uninstall smartnuf-agent-tools
```

Poppler and Ghostscript are not bundled. Install them through the operating-system package manager before expecting `agent-tools doctor` to pass completely. See the [v0.1.1 release notes](docs/releases/v0.1.1.md) for current limitations.

## Get the source

For the shared `agent-python` development environment and repository automation, clone into the conventional user-level location:

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

Linux or macOS (install `uv` with a trusted package manager first):

```sh
cd "$HOME/.agent-tools"
./scripts/bootstrap.sh --install-native-tools --add-to-path
agent-tools doctor
```

All mutation flags are opt-in. On Windows, `-InstallUv` delegates to WinGet. On systems with Homebrew, `--install-uv` delegates to Homebrew. The scripts never execute a downloaded installer response directly. Without installation flags, bootstrap creates or refreshes `.venv` only when `uv` is already available and prints actionable diagnostics.

PATH changes are also opt-in. Windows backups are written under `.backups/path/`; Unix shell-profile changes create a timestamped sibling backup before editing an existing profile.
Unix profile updates use a per-profile lock. If an interrupted update leaves that lock behind, the command stops without changing the profile and reports the exact lock path and recorded PID. Verify that no update process owns it before removing it manually and rerunning.

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

## Roadmap and current status

The maintained roadmap is [`docs/plan/00-index.md`](docs/plan/00-index.md). It records the current milestone, acceptance gates, estimates, evidence, remaining effort, and recommended next work. [`docs/plan/README.md`](docs/plan/README.md) defines how humans and agents plan tasks and report progress consistently.

The next objective is a normal PyPI/`uv tool install smartnuf-agent-tools` installation path. The versioned GitHub prerelease and clone-based shared environment remain supported while that work proceeds.
