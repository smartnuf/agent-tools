# ADR 0006: Claude Code Git Bash integration

- Status: Accepted
- Date: 2026-09-02
- Related: ADR 0002, ADR 0004, ADR 0005, issues #26 and #27

## Context

ADR 0002 separates provider capability management from agent integrations.
Issue #27 evaluates the first such adapter. Anthropic's current primary
documentation, rechecked on 2026-09-02, defines all of the required public
surface:

- [native Windows installation](https://code.claude.com/docs/en/installation)
  documents `env.CLAUDE_CODE_GIT_BASH_PATH` in `settings.json` when Claude Code
  cannot locate Git Bash;
- the [environment-variable reference](https://code.claude.com/docs/en/env-vars)
  defines it as Windows-only, requires an existing Bash/Sh executable identity,
  and describes invalid-value fallback; and
- the [settings contract](https://code.claude.com/docs/en/settings) defines
  strict JSON, user settings at `~/.claude/settings.json`, Windows
  `%USERPROFILE%\.claude`, and relocation through `CLAUDE_CONFIG_DIR`.

The mechanism is therefore documented well enough to implement. Editing a
shell profile, process environment, undocumented Claude file, or provider
package is unnecessary.

Apply and remove span Claude Code's user settings and Agent Tools' own
integration facts. Those files cannot be replaced atomically as one unit, so
the adapter needs an explicit recoverable phase model rather than pretending
the cross-file operation is a Boolean transaction.

## Decision

Agent Tools supports one native-Windows adapter through:

```text
agent-tools integrations claude-code status
agent-tools integrations claude-code apply --allow-config-mutation
agent-tools integrations claude-code remove --allow-config-mutation
```

Apply consumes the catalogue's currently selected, verified `git-bash`
provider and its one absolute `bash.exe` or `sh.exe` path. Linux, macOS, WSL,
another Bash provider, an absent provider, a relative path, or unverified
executable evidence fails before mutation. The adapter neither installs nor
removes Git for Windows and never invokes the provider executor.

The Claude settings path is the documented user `settings.json` under
`%USERPROFILE%\.claude`, or under an absolute `CLAUDE_CONFIG_DIR` when set.
Agent Tools changes only `env.CLAUDE_CODE_GIT_BASH_PATH`. Other top-level and
`env` members are preserved logically. A matching pre-existing member with no
Agent Tools record is a no-op and is explicitly not claimed.

### Separate integration record

The lifecycle record is separate from desired capability state, detected
state, and provider-mutation provenance. It lives at:

```text
%LOCALAPPDATA%\agent-tools\integrations\claude-code.json
```

Schema v1 is a closed object:

```json
{
  "schema_version": 1,
  "phase": "active",
  "settings_path": "C:\\Users\\person\\.claude\\settings.json",
  "settings_existed": true,
  "applied_value": "C:\\Program Files\\Git\\bin\\bash.exe",
  "previous": {
    "present": false
  }
}
```

`previous` distinguishes an absent member from its exact prior string value;
`settings_existed` separately distinguishes an absent settings file. The
accepted phases are:

- `prepared`: prior facts are durable before the Claude setting is changed;
- `active`: the recorded path is the setting Agent Tools applied;
- `removing`: restoration was requested and may need reconciliation; and
- `removed`: the recorded prior member/file state has been restored.

The removed record is retained as a tombstone so a crash after restoring
Claude settings but before final record publication can be reconciled without
repeating or guessing the external change. A later apply may replace the
tombstone through the same prepared phase.

Apply writes `prepared`, changes and verifies Claude settings, then writes
`active`. If active publication fails, it restores Claude settings and reports
failure; a durable prepared record remains safe to reconcile. Remove writes
`removing`, restores the prior member while preserving unrelated changes, then
writes `removed`. A removing record plus already-restored settings is finalized
without replaying the settings change. Any value outside the recorded prior or
applied facts is external divergence and is preserved while the operation
fails closed. A changed selected Git Bash path requires remove followed by a
fresh apply; it is not silently adopted.

### Persistence, authority, and cancellation

Every actual settings or record change requires the dedicated
`--allow-config-mutation` flag. No-op inspection and already-satisfied requests
do not. Existing files receive collision-safe byte-exact sibling backups before
replacement or removal. Entries are classified without following symlinks;
only absent or ordinary regular entries are accepted. JSON reads are bounded,
duplicate keys and excessive depth fail closed, complete temporary documents
are validated before atomic replacement, directories are synchronized where
supported, and resulting documents are read through their production reader.
Unreadable input is preserved.

Claude settings are validated only against the documented structural contract
needed here: a strict-JSON object whose optional `env` member is a string map.
Unknown Claude settings remain Claude-owned and are preserved; Agent Tools does
not claim to reproduce Claude Code's complete or faster-moving JSON schema.
The integration record has one exact writer/reader language. Changing its
fields or semantics requires a schema-version decision.

Consistent with ADR 0004, supported first SIGINT is brokered cooperatively
through mutation and broker teardown. A first request after an effect restores
the prior single-file state before interruption propagates; a second SIGINT may
force-abort. Cross-file phases retain recovery truth when quiescent completion
cannot be established.

Only process-local serialization is claimed. Source snapshots are rechecked
before replacement, but independent writers and Claude Code itself are not
locked. Subsequent divergence is detected and preserved rather than overwritten.

## Consequences

- Native Windows users can bind Claude Code to the same verified Git Bash path
  selected by Agent Tools without editing a shell profile.
- Remove restores pre-existing member absence/value and initial file absence
  when no unrelated settings were added; it never removes Git for Windows.
- Persistent integration facts do not contaminate desired state, detection, or
  non-owning provider provenance.
- Cross-file crashes remain explicitly reconcilable rather than being called
  atomic or blindly retried.
- The adapter must be re-evaluated if Anthropic removes or materially changes
  the documented settings mechanism.

## Alternatives considered

- Recording the variable in Agent Tools desired state was rejected because
  desired capability intent is not agent-configuration ownership or phase.
- Restoring an entire old `settings.json` on later remove was rejected because
  it would erase unrelated changes made after apply.
- Removing any matching unrecorded value was rejected because equality does
  not establish ownership.
- Editing PowerShell/Bash profiles or the persistent Windows user environment
  was rejected because Anthropic now documents a narrower settings-file
  mechanism and repository governance forbids silent profile/PATH changes.
- Invoking a private Claude command or validating by starting an authenticated
  Claude session was rejected: no such command is required by the public
  contract, and account credentials are not an adapter prerequisite.

## Non-goals

This decision adds no Claude installation, authentication, managed-policy
override, project settings, WSL integration, generic agent plugin framework,
provider mutation/removal, settings retention policy, or cross-process lock.
