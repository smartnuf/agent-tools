# 0002: Native capability and provider model

- Status: accepted
- Date: 2026-08-29
- Scope: native workstation capability discovery and management

## Context

Native-tool knowledge is currently split across the packaged Python diagnostics,
Windows bootstrap logic, Unix installation scripts, platform documentation, and
CI. Poppler and Ghostscript probes, package identifiers, discovery locations,
and post-install handling are repeated in different forms. The packaged wheel
contains `src/agent_tools/`, but not the clone-oriented scripts, so extending
those scripts cannot make native capability management available to ordinary
`uv tool` users.

The motivating example is Bash on Windows. This machine already has Git for
Windows and usable Bash executables under `C:\Program Files\Git`, but `bash` is
not on the normal process `PATH`. PATH-only discovery therefore mistakes an
existing preferred provider for an absent capability. WSL is also present, but
it is a separate Linux execution environment with different path, process,
permission, and package-management semantics.

The present duplication is concrete:

| Concern | Current locations |
|---|---|
| Required/alternative executable probes | `src/agent_tools/cli.py`, `scripts/bootstrap.ps1`, and CI post-install checks |
| Windows package IDs and fallback discovery | `scripts/bootstrap.ps1`, `scripts/windows-tools.ps1`, and `.github/workflows/ci.yml` |
| Linux/macOS package-manager mappings | `scripts/install-native.sh`, `docs/platforms.md`, `README.md`, and CI |
| Required-versus-optional diagnostic meaning | `src/agent_tools/cli.py`, packaging documentation, tests, and CI expectations |
| Installation and update guidance | bootstrap scripts, `README.md`, `docs/platforms.md`, and `docs/packaging.md` |

## Decision

Put native capability product knowledge and orchestration in the packaged
Python application. Keep platform bootstrap scripts as thin clone/development
front ends to that implementation once mutating commands exist.

Use four explicitly separate kinds of data:

1. **Built-in catalogue:** immutable project-maintained declarations of
   capabilities, probes, supported platform/architecture/environment
   combinations, and provider/package-manager metadata.
2. **User configuration:** desired optional capabilities, provider preferences,
   and separately selected agent integrations. This is not a list of what the
   project supports.
3. **Detected state:** ephemeral observations such as executable paths,
   versions, architecture, provider evidence, and execution environment.
4. **Managed-state records:** facts about mutations agent-tools explicitly
   requested. A record establishes provenance of a request, not ownership of a
   shared provider package.

The catalogue will initially be Python data using small typed records and
named detector/provider strategies. Provider declarations include the package
installation unit, whether update/removal affects a shared package, and an
initial removal policy such as prohibited. It is not a public plugin API,
dependency solver, or user-editable package database. Provider execution must
consume an inspectable plan produced from catalogue, configuration, and
detected state; it must not embed a second package mapping in PowerShell or
shell.

Stage the CLI:

- First ship read-only `agent-tools tools list` and
  `agent-tools tools status [CAPABILITY]`. Keep `doctor` focused on the default
  supported product and add `doctor --all` only with explicit semantics for
  absent optional capabilities (absence is informational, not a failure).
- Add `tools install` only after provider plans, a dedicated explicit mutation
  flag, and disposable-host tests exist. Interactive confirmation alone does
  not authorize system-package mutation. Report every requested and observed
  host change, including the provider/package-manager action and outcome.
- Add desired-state `enable`/`disable` only when user configuration has a clear
  consumer. Disabling desired state must not uninstall anything.
- Keep provider-package uninstall out of the initial interface. If it is ever
  added, name it explicitly, show collateral packages/capabilities, require a
  separate confirmation, and refuse when provenance or safety is uncertain.

## Bash capability

Represent `bash` as an optional capability whose contract is a verified
executable, version, provider, architecture where observable, and execution
environment.

Initial providers are:

- **Git Bash:** preferred Windows-hosted provider. Discover an existing Git for
  Windows installation before proposing installation. Candidate discovery may
  use the executable PATH, Git's own installation location, package-manager or
  registry evidence, and documented install locations; every selected
  executable must pass a Bash version/execution probe.
- **System Bash:** normal host Bash on supported Linux and macOS systems.
- **WSL Bash:** report separately as a WSL/Linux-environment provider. Do not
  satisfy a Windows-hosted Bash request with WSL implicitly.

MSYS2 is a possible later Windows-hosted provider. Cygwin is deferred until
evidence justifies its compatibility and maintenance cost. Installing Git Bash
means asking the platform package manager for Git for Windows; it does not make
Git an agent-tools-owned package, and disabling Bash must never remove Git.

## Agent integrations

Capability management guarantees availability and reports the verified path;
it does not claim control over an agent's shell selection.

Integrations are separate adapters that consume detected capability state and
modify only documented agent configuration with explicit authorization,
backup, and validation. Anthropic documents
[`CLAUDE_CODE_GIT_BASH_PATH`](https://docs.anthropic.com/en/docs/claude-code/getting-started)
for native Windows Claude Code, so a future Claude Code adapter may configure
that supported mechanism. No Codex adapter will be promised until current
official Codex documentation establishes a
stable shell-selection interface.

## Consequences

- The wheel becomes the single product implementation for discovery and future
  provider orchestration.
- Existing Poppler and Ghostscript diagnostics must migrate to the catalogue
  before adding a parallel Bash implementation.
- Platform scripts, documentation, and CI should consume or test catalogue
  behaviour rather than restating mappings where practical.
- The package description should broaden from document-processing tools to
  agent workstation capabilities and diagnostics when the first capability
  commands ship; document libraries remain supported capabilities, not the
  entire product identity.
- Persistent user configuration and managed-state schemas are deferred until a
  mutating command needs them. This avoids inventing migration and ownership
  rules for state that has no current consumer.

## Rejected or deferred alternatives

- Adding an `InstallBash` bootstrap switch: quick, but deepens the duplication
  and remains unavailable from an installed wheel.
- A generic provider plugin framework or external catalogue format: premature
  compatibility and security surface for three built-in capabilities.
- Treating WSL, MSYS2, Cygwin, and Git Bash as interchangeable executables.
- Interpreting `disable` as package uninstall.
- Blocking the completed M1 prerelease: M1 evidence is already complete. A
  bounded capability-foundation milestone precedes M2 instead.
