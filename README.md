# Agent Tools

A user-level, agent-neutral home for workstation capability discovery, reusable Python and document helpers, command wrappers, and native-tool setup. The repository is intended to live at `~/.agent-tools` and to be usable by Codex, Claude Code, terminal users, and other local agents.

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
- **Capability discovery:** keep detection read-only. Git Bash is the preferred Windows-hosted Bash provider; the default WSL distribution is reported as a separate environment.

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

## Install the packaged release

The current stable release is [v0.1.2](https://github.com/smartnuf/agent-tools/releases/tag/v0.1.2). Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) through a trusted package manager, then install `agent-tools` from PyPI:

```sh
uv tool install --python 3.13 smartnuf-agent-tools
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

Upgrade an unpinned installation to the latest compatible release:

```sh
uv tool upgrade smartnuf-agent-tools
```

Pin the current release when reproducibility matters, or reinstall that exact version if its isolated environment is damaged:

```sh
uv tool install --python 3.13 --reinstall "smartnuf-agent-tools==0.1.2"
```

Rollback uses the same exact-version command with an earlier available release:

```sh
uv tool install --python 3.13 --reinstall "smartnuf-agent-tools==0.1.1"
```

To remove it:

```sh
uv tool uninstall smartnuf-agent-tools
```

Application removal deletes uv's isolated tool environment and executable. It
does not delete Agent Tools' per-user desired-state configuration, reverse an
active agent integration, or uninstall externally owned native providers such
as Bash. Remove an integration explicitly before uninstalling the application
when restoration of its managed setting is intended.

Poppler and Ghostscript are not bundled. Install them through the operating-system package manager before expecting `agent-tools doctor` to pass completely. See the [v0.1.2 release notes](docs/releases/v0.1.2.md) for current limitations.

## Check health and discovered capabilities

After the optional `uv tool update-shell` step above, run the health check and
inspect the immutable native-capability catalogue with these read-only
commands. Without that PATH change, use the same platform-specific executable
path shown in the verification step.

```sh
agent-tools doctor
agent-tools tools list
agent-tools tools status
agent-tools tools status bash
agent-tools tools enable bash --allow-config-mutation
agent-tools tools disable bash --allow-config-mutation
agent-tools integrations claude-code status
agent-tools integrations claude-code apply --allow-config-mutation
agent-tools integrations claude-code remove --allow-config-mutation
```

`tools status bash` reports desired state separately and verifies the detected
provider, executable path, version, execution
environment, and executable architecture where observable. On Windows it
discovers Git Bash outside the normal process `PATH`; the default WSL
distribution is reported separately and never silently treated as
Windows-hosted Bash. `tools enable` and `tools disable` change only the
versioned per-user desired-capability document, require the dedicated mutation
flag for a real change, and back up an existing document before replacement.
Disable never uninstalls a provider. The status and list commands do not
install software or alter `PATH`.

On native Windows, the Claude Code integration commands can explicitly bind
Claude Code's documented user setting to the same selected, verified Git Bash
path. Apply and remove require the dedicated configuration-mutation flag,
preserve unrelated Claude settings, and restore the exact prior setting; they
never install or uninstall Git for Windows. A matching setting not created by
Agent Tools remains unowned and is not removed. See
[Decision 0006](docs/decisions/0006-claude-code-git-bash-integration.md) for
the recovery and compatibility contract. Version 0.1.2 is the first packaged
release containing the read-only commands; desired-state and integration
commands are currently available from `main` pending the next release.

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

All mutation flags are opt-in. On Windows, `-InstallUv` delegates to WinGet. On systems with Homebrew, `--install-uv` delegates to Homebrew. `-InstallNativeTools` and `--install-native-tools` delegate Poppler and Ghostscript discovery, provider planning, mutation, provenance persistence, and final verification to the packaged capability implementation; the wrappers contain no separate native package mapping. Python discovery and environment creation disable automatic downloads; install a compatible Python 3.11 with a trusted provider before bootstrap. A translated/emulated fallback requires `-AllowEmulatedPython` or `--allow-emulated-python`. Use `-PythonPath PATH` or `--python PATH` to require a particular compatible installed interpreter. The scripts never execute a downloaded installer response directly.

Bootstrap discovers installed interpreters without downloads, verifies each executable, and passes the selected absolute path to `uv`. A temporary bootstrap process does not determine the final runtime: a compatible native system Python normally wins over a translated managed Python. The resulting `.venv` is verified again before packages are installed. If an existing `.venv` no longer matches the selected runtime, bootstrap stops without replacing it; remove that checkout-owned environment deliberately and rerun.

Native setup reports the reviewed package-manager commands and then reports host-mutation and managed-provenance outcomes separately. It also consumes enabled optional capabilities and exact provider preferences from the desired-state document; the bootstrap native-install flag remains a separate authorization for any resulting provider mutation. An all-satisfied rerun performs no provider command. After partial or uncertain execution, do not rerun automatically: follow the reported recovery guidance, rediscover current state, and generate a fresh attempt. Temporary process `PATH` refresh used for verification is restored; persistent PATH or profile changes still require the separate explicit PATH flag.

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

The bounded [M1.5 packaged capability-discovery milestone](docs/plan/09-capabilities/README.md) and the first stable PyPI publication in M2 are complete. M3 now includes tested native/system-first selection, clone bootstrap delegation through the explicitly authorized managed provider lifecycle, reversible desired-capability configuration, and the native-Windows Claude Code Git Bash adapter. Release-lifecycle evidence remains. See the maintained roadmap for the ordered work. The packaged release and clone-based shared development environment remain supported entry points.
