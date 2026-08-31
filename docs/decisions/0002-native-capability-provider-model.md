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
  consumer. Each change requires explicit authorization, preserves unrelated
  pre-existing state, creates a recoverable backup before modifying or
  replacing existing configuration, and validates the resulting configuration
  before reporting success. A write or validation failure must leave the
  previous usable state intact or restore it. Disabling desired state must not
  uninstall anything.
- Keep provider-package uninstall out of the initial interface. If it is ever
  added, name it explicitly, show collateral packages/capabilities, require a
  dedicated mutation flag in addition to separate confirmation, report every
  requested and observed host change, and refuse when provenance or safety is
  uncertain.

The provider executor consumes the immutable reviewed plan rather than
reconstructing selection or package mappings. Before any command it verifies
the current machine/execution context, catalogue-owned action contract,
package-manager executable identity, required privilege path, and whether the
planned provider already satisfies the request. A nonempty plan refuses unless
the dedicated non-interactive provider-mutation authorization is present.

Commands run sequentially in isolated process trees with explicit timeouts and
captured outcomes; a timeout terminates and reaps that tree before returning.
On Linux, a `SYSTEM`-privilege action has a stricter execution contract. Agent
Tools first resolves an absolute executable identity for GNU Coreutils
`timeout`, verifies that identity with its version output, and does not install
or configure a supervisor when none is available. A non-root process then
checks non-interactive sudo authorization for every exact supervised command
and executes only argument vectors equivalent to
`sudo -n -- <verified-timeout> --signal=TERM --kill-after=5s <timeout>
<reviewed-manager-argv...>`. A root process uses the same verified supervisor
without sudo. GNU timeout's normal process-group behavior is required;
`--foreground` is prohibited. The five-second TERM-to-KILL grace is small and
bounded so a cooperative manager can clean up while TERM-resistant work that
remains under GNU timeout's supported process-group supervision is escalated
without an indefinite wait.

The privileged supervisor, rather than the invoking Python process, is
authoritative for elevated Linux termination. Python process-tree termination
remains the same-privilege mechanism on other paths, but an elevated action
never falls back to claiming success from an unprivileged group kill. Missing
GNU timeout, unavailable non-interactive sudo, denied exact-command policy,
supervisor failure, and command-start failure all fail closed. Reports preserve
the actual supervised argv, raw return code, and bounded stdout/stderr tails
(marked when earlier output was truncated), and distinguish
ordinary command failure, timeout expiry, ambiguous forced kill, supervisor
failure, command-start failure, and privilege unavailability to the extent GNU
timeout's exit contract permits. An outer Python guard that expires after the
command timeout plus grace is an uncertain supervision failure, not a clean
timeout. Agent Tools does not modify sudoers, PATH, profiles, system packages,
or user configuration to establish this contract.

Caller interruption is also a process-lifetime boundary. Before propagating a
non-timeout interruption such as Ctrl+C, the runner terminates and reaps an
isolated same-privilege tree. For an elevated Linux action it signals the
sudo/timeout supervisor and waits through the bounded grace/guard interval for
privileged-side termination; it does not substitute an unprivileged process-
group kill. If confirmed privileged termination cannot be established, that
uncertain supervision failure replaces a normal interruption return so callers
cannot safely infer that retry is ready.

Agent Tools owns the synchronous package-manager invocation and work that
remains under these supported supervision mechanisms. It does not provide a
portable process sandbox or claim containment of arbitrary processes that a
package hook or installed program intentionally detaches. After the supervised
leader exits, output pipes receive only a one-second closure guard. A retained
pipe is positive evidence that synchronous quiescence was not established: the
runner stops its polling readers, closes its local handles, preserves bounded
output tails and the actual leader exit status, and reports `SUPERVISOR_FAILED`
with uncertain external state. It does not kill broadly, perform final
verification, convert a temporarily visible executable into success, retry
automatically, or attempt rollback/removal. Retry is permitted only after an
operator independently establishes that relevant activity has quiesced and
generates a fresh plan from current state. Invisible detached work is not
speculatively detected; normal completion with normally closed output remains
governed by manager exit evidence and complete rediscovery.

The runner drains stdout and stderr concurrently while retaining at most one
MiB of tail evidence per stream. Continuous installer output therefore cannot
make memory use grow for the full command timeout, while the report preserves
the most recent diagnostics and explicitly marks discarded earlier output.
GNU timeout status 124 is ambiguous because GNU timeout also propagates a
reviewed command's own status 124; it is therefore a command failure without a
`timed_out` claim unless the outer Python guard supplies independent deadline
evidence. Status 137 or a direct SIGKILL return is likewise reported only as an
ambiguous forced kill—an administrator, the OOM killer, or timeout escalation
can produce it—so it does not set the report's `timed_out` flag or claim the
TERM grace expired.

The executor stops on the first timeout, nonzero exit, unavailable manager, or
missing privilege. Failures before any command starts report no attempted
mutation; after a command starts, the report warns that package-manager state
may be partial and does not attempt provider removal or an unsafe rollback.
After an apparent
success it applies only the plan's temporary process-environment refresh before
both the repeat-safety check and final rediscovery, then verifies the complete
probe set, its `ANY`/`ALL` policy, and any native target architecture.
Package-manager success
without that final evidence is a reported failure. Individually verified paths
remain visible in that failure report even when an `ALL` condition or native
architecture target is not satisfied. Reusing the same plan after any freshly
detected catalogue-satisfying provider verifies performs no further command.
Ordinary actions accept the highest-priority satisfying provider in the
complete fresh capability state. Native-replacement actions accept any fresh
satisfying provider whose verified executable evidence meets the target
architecture; translated, unknown-architecture, or otherwise unsuitable
evidence does not suppress the authorized replacement. The report names the
provider whose fresh evidence caused the skip. Managed-state persistence remains
a separate subsequent contract.

Execution serialization is process-local. One process-wide re-entrant lock
encloses current-context and catalogue validation, fresh provider detection,
manager and translated-Homebrew authorization validation, privilege/supervisor
preflight, every command in the action, temporary environment refresh,
post-action rediscovery, final verification, and report construction. Thus two
threads in one Agent Tools process cannot both pass the missing-provider check
and mutate concurrently; the second observes the first transaction's verified
result before deciding whether a command is needed. This decision does not
claim exclusion against another Agent Tools process or an unrelated package
manager user. Portable inter-process coordination would be a separate public
and persistence contract; native package-manager locking remains external, and
this executor does not add file locks, named mutexes, or a lock service.

A requested capability omitted from the action list is not accepted from plan
history alone, whether the plan has zero actions or mixes satisfied requests
with a missing-provider action. Before mutation or `NO_CHANGES`, the executor
resolves every omitted request in the built-in catalogue and revalidates fresh
provider evidence against the current immutable machine context. Unknown,
stale, contradictory, or no-longer-verified requests fail preflight without
claiming mutation.

## Final-provider selection contract

Discovery and bootstrap are not provider-selection policy. For every
capability that Agent Tools selects or arranges for later use, the finalized
setup normally reuses a compatible existing native/system provider. A
bootstrap process may run under translation or use a temporary managed tool,
but that does not make a translated or managed provider preferable for the
final environment.

Selection keeps these facts separate:

- host platform and host architecture;
- discovery/bootstrap process architecture and translated/emulated state,
  where observable;
- execution environment, such as the Windows host, WSL, a container, or a
  native Unix host;
- provider executable architecture;
- provider mechanism/origin, such as system/external versus a runtime managed
  by uv or another tool;
- Agent Tools mutation provenance, meaning pre-existing/unrecorded versus a
  mutation Agent Tools requested, without implying package ownership; and
- compatibility with the intended final execution environment.

A provider plan is bound to exactly one immutable machine/execution context;
requested detected states from different contexts cannot be combined. Linux
providers local to a process running inside WSL are valid in that WSL context,
while a WSL provider discovered from the Windows host remains a separate
environment and does not satisfy the Windows-host request. Each planned action
preserves both its verification probes and their `ALL`/`ANY` composition policy
so an executor need not reconstruct the reviewed post-action condition. The
plan also records whether each package-manager action requires system
privilege; apt, dnf, and pacman actions require it, while Homebrew and WinGet
actions do not inherit that Linux elevation policy. The executor, rather than
the catalogue command, will apply the recorded privilege policy. An action
also records any environment refresh required before its verification probes;
WinGet actions refresh the process `PATH`; Homebrew actions make the exact
reviewed formula `bin` directory available for rediscovery; the built-in Linux
managers require no equivalent refresh.

Package-manager availability is verified evidence, not a bare manager name.
The immutable planning input records the built-in manager identity, verified
executable path, local execution environment, and executable architecture when
observable. When the executable path is an alias or symlink, discovery also
records its verified resolved executable path as the canonical identity.
When that identity does not unambiguously have `<root>/bin/brew` form,
Homebrew planning also requires verified installation-root evidence and carries
the derived formula `bin` path in the action; missing or contradictory root
evidence fails closed.
Complementary observations for that identity merge known architecture into
missing architecture evidence; differing known architectures fail closed.
Platform comes from the plan's single machine context rather than
being duplicated in manager evidence. Suitability is derived from those
observations and the catalogue option. Homebrew executable architecture is
material because an Intel Homebrew on Apple silicon provisions translated
packages: native Homebrew ranks first, unknown architecture is unusable, and a
translated Homebrew is usable only when that exact observed manager state is
explicitly authorized as a visible fallback. The executable architecture of
apt, dnf, pacman, or WinGet does not itself determine their target package
architecture; their local execution environment, catalogue option, and any
manager-specific target argument are the relevant planning evidence. Planned
argv uses the verified manager path so a later executor does not silently
resolve a different installation.

Immediately before executing a Homebrew action, the executor runs a bounded,
noninteractive, no-auto-update Homebrew Ruby architecture probe through the
exact planned executable path. Missing or changed live architecture evidence
invalidates the manager before mutation; the immutable plan's earlier
architecture is authorization evidence, not a substitute for current state.

When planning selects translated Homebrew, the immutable action carries a
dedicated structured authorization bit derived from membership of that exact
canonical `PackageManagerState` in the caller's translated-fallback set. The
executor revalidates manager identity, execution environment, architecture and
native status against the current plan context and refuses translated or
unknown-architecture Homebrew without that exact evidence. It does not infer
authorization from reason text or other incidental strings. Native Homebrew is
accepted without translated-fallback authorization and rejects a contradictory
translated-only marker. The evidence is ephemeral plan/report data, not user
configuration or persistent managed state.

`platform.machine()` describes the running Python context and is not, by
itself, sufficient evidence of host architecture when that Python may be
translated. Platform adapters may therefore add host/process evidence. On
Windows, [`IsWow64Process2`](https://learn.microsoft.com/windows/win32/api/wow64apiset/nf-wow64apiset-iswow64process2)
can report the process machine and native host machine; older or unavailable
APIs require an explicitly limited fallback.
On macOS, translation evidence such as `sysctl.proc_translated` may supplement
process and hardware architecture observations. On Linux and other Unix-like
systems, kernel-reported architecture is useful host-environment evidence, but
containers, virtual machines, and compatibility layers remain distinct
execution environments rather than facts to guess through. Unknown evidence
stays unknown and is reported; architecture aliases are normalized before
comparison.

Selection first evaluates installed candidates:

1. **Discover candidates** through provider-specific, read-only channels,
   including candidates outside `PATH`.
2. **Verify candidates** by executing bounded identity/version probes and
   collecting path, architecture, environment, and provenance evidence.
3. **Rank compatible installed candidates** for the intended final
   environment.
4. **Select explicitly**, passing a verified executable path to downstream
   tooling instead of relying on that tool's implicit preference order.
5. **Verify the final result** again and fail rather than report success when
   the selected provider and resulting environment disagree.

If no acceptable installed candidate exists, planning separately ranks
installable catalogue options. An authorized executor may provision the chosen
option; selection then starts again with discovery and verification. An absent
option never becomes the selected provider merely because it is installable,
and post-mutation rediscovery/final verification is mandatory.

The normal installed-candidate ranking is:

1. compatible existing native system/external-mechanism provider;
2. compatible existing system/external-mechanism provider where native status
   is unavailable or irrelevant;
3. compatible existing native tool-managed-mechanism provider;
4. compatible existing translated/emulated system/external-mechanism provider;
5. compatible existing tool-managed-mechanism provider where native status is
   unavailable or irrelevant; and
6. compatible existing translated/emulated tool-managed-mechanism provider
   only as a deliberate, visibly reported fallback, explicitly authorized
   where practical.

Installable options use native-before-translated and system/external-mechanism-
before-tool-managed-mechanism principles where the platform can actually
supply those alternatives.
Provisioning is considered only when no acceptable installed candidate
exists; it never displaces a compatible existing external translated provider
under the default policy. A validated explicit preference for native
provisioning may request that replacement, but the resulting package-manager
or managed-runtime action remains a separately reported mutation requiring
explicit authorization.

A validated explicit user provider preference narrows the compatible options
before default ranking. Selecting a lower-ranked compatible option requires
the same visible explicit authorization as the preference and reports the
departure from the default. An unavailable, unsuitable, or contradictory
preference fails with its evidence; selection never silently ignores it or
falls back to another provider. Without such a preference, the default order
above is authoritative.

Candidates in the same ranking class use stable tie-breakers rather than
discovery order. First group observations by normalized resolved executable
identity. Complementary evidence for one executable may be merged only when
all overlapping facts agree. Conflicting provider, version, architecture,
environment, provenance, or suitability evidence for that identity fails
visibly before deduplication; no discovery channel wins by arrival order.

Provider mechanism and Agent Tools mutation provenance remain independent. For
example, a uv-managed Python that predates Agent Tools is a tool-managed-
mechanism provider with pre-existing/unrecorded Agent Tools provenance. A
managed-state record changes reporting of the requested mutation, not the
candidate's mechanism class or ownership.

After each identity has one consistent candidate, compare built-in provider
priority, a capability-declared version score, and the normalized resolved
absolute path in that order. A version score must state its rule: Python
bootstrap prefers the requested compatible minor and then the greatest
verified stable patch; a capability without a declared version preference
assigns equal version scores. Path comparison is ordinal after platform
normalization (including case folding on Windows); the lowest ordinal
normalized path wins. If distinct candidates still have identical keys but
contradictory evidence, selection fails visibly as ambiguous instead of
choosing whichever discovery returned first.

A documented compatibility constraint may reject a higher-ranked candidate,
but its evidence and reason must be visible. In particular, an ARM64 host with
an x64/emulated bootstrap process and a compatible existing native ARM64
Python selects the native ARM64 Python for the final environment.

uv's current documented
[`python-preference = "managed"`](https://docs.astral.sh/uv/concepts/python-versions/#adjusting-python-version-preferences)
can prefer an already
installed uv-managed Python over an installed system Python, although a
compatible system Python is considered before uv downloads a new managed
Python. `system`, `only-system`/`--no-managed-python`, automatic-download
controls, and explicit interpreter paths are useful discovery/execution
controls; they do not determine native suitability for Agent Tools. Python
bootstrap must apply this contract first, then give uv the selected verified
interpreter path.

Under the default policy, provider plans must contain no installation action
when a suitable candidate already verifies. The only exception is a validated
explicit preference for native provisioning under the rule above; that plan
must identify the compatible installed provider it would displace and remains
subject to separate mutation authorization. Selection and planning require
both empty/disposable-host and already-equipped workstation evidence. Pure
fixtures cover otherwise unavailable combinations; platform CI claims only
the runner architectures it actually exercises and does not imply hosted
Windows ARM64 coverage.

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
- **System Bash:** normal local Bash on supported Linux (including a process
  running inside WSL) and the Apple-provided Bash on macOS. When explicitly
  requested and absent, Linux may plan the native `bash` package through apt,
  dnf, or pacman.
- **Homebrew Bash:** a distinct macOS provider that may be planned as the
  Homebrew `bash` package only when Homebrew is already an available manager.
  It neither relabels nor replaces a compatible Apple-provided Bash and does
  not authorize installing Homebrew.
- **WSL Bash:** report separately as a WSL/Linux-environment provider. Do not
  satisfy a Windows-hosted Bash request with WSL implicitly.

Bash remains optional and provisioning requires an explicit Bash capability
request with no suitable existing provider. Agent Tools installation,
bootstrap, and default diagnostics do not provision Bash or depend on this
optional plan.

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
