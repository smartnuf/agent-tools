# ADR 0003: Managed-state mutation provenance

- Status: Accepted
- Date: 2026-08-31
- Decision owners: project maintainer (human-authorized for issue #52)
- Related: ADR 0002, issues #26 and #52

## Context

ADR 0002 separates built-in catalogue facts, desired configuration, ephemeral
detected machine state, and records of mutations that Agent Tools requested.
The provider executor now supplies structured attempted-command and final
verification evidence, so issue #52 is the first consumer that needs a durable
managed-state schema.

Provider packages are shared machine state. Recording that Agent Tools asked a
package manager to mutate such state does not establish ownership, removal
rights, or even that the provider remains installed. Detection remains the
authority for current machine state.

## Decision

Each execution environment uses one private per-user JSON document:

- Windows host: `%LOCALAPPDATA%\agent-tools\managed-state.json`;
- Linux, including execution inside WSL:
  `$XDG_STATE_HOME/agent-tools/managed-state.json`, falling back to
  `~/.local/state/agent-tools/managed-state.json`; and
- macOS: `~/Library/Application Support/agent-tools/managed-state.json`.

Windows-host and WSL records are naturally separate. The implementation may
inject another path for tests, but there is no public option, environment
variable, or user configuration for overriding it.

Schema v1 is a versioned object containing logically append-only immutable
mutation-attempt records. Each record has a stable opaque ID and separately
records:

- capability and provider identity;
- provider mechanism/origin, package-manager mechanism, and installation unit;
- execution environment and machine context;
- the action Agent Tools requested and bounded command evidence;
- structured package-manager architecture and translated-Homebrew fallback
  authorization evidence, never inferred from free-form reason text;
- request, completion, and recording timestamps; and
- the executor's rediscovery/verification result.

Every record explicitly disclaims ownership. No record authorizes uninstall or
rollback. New records never replace, modify, or remove old records. Version 1
has no retention, rotation, or compaction policy.

Logical append uses a complete new document written to a temporary file in the
destination directory, flushed, and atomically replaced. The previous document
is preserved when failure occurs before replacement. A failure known to precede
replacement is `failed`; failure after replacement but before durability can be
confirmed is `unknown`.

An absent document is an empty history. Current v1 is validated before use.
There is no speculative legacy migration. Corrupt documents and unknown schema
versions are visible and are never automatically overwritten. A mutation that
would require provenance persistence is refused before host mutation unless the
existing document can be understood and preserved. Read-only detected-state
diagnostics continue and report provenance failure separately.

Mutation/verification and persistence are independent outcomes. When a
positively verified mutation is followed by persistence failure, reporting
preserves the executor result and states either `provenance not recorded` or
`provenance durability unknown`. It does not relabel the host mutation as
uncertain, claim ownership, automatically retry mutation, or attempt uninstall
or rollback. Any later mutation requires fresh rediscovery and a newly generated
plan.

The first `KeyboardInterrupt` observed by the supported managed mutation
boundary is a request for controlled cancellation. That boundary preserves the
strongest authoritatively published execution evidence and monotonic
persistence outcome, then attempts to publish a structured managed result. A
transaction fact becomes authoritative to this boundary only when it has been
successfully published to the managed transaction snapshot. If cancellation
races publication of a stronger fact, the strongest predecessor fact already
in that snapshot remains truthful and may be conservatively terminalized.

Consequently, exact completed executor evidence is not guaranteed when
cancellation prevents its publication; mutation-uncertain evidence must not
claim that no provider command started and provider mutation is never rerun.
Similarly, `succeeded` means durable completion was published as the terminal
transaction fact. When replacement has occurred and durability work may have
physically completed but cancellation prevents that publication, the last
authoritative post-replacement fact may remain `unknown`. `Unknown` does not
assert physical non-durability. Neither uncertainty authorizes automatic
mutation or persistence retry, ownership, rollback, uninstall, or removal. Any
later mutation requires fresh machine-state rediscovery and a newly generated
plan.

Any later `KeyboardInterrupt` while that controlled cancellation, recovery, or
result publication is active is an explicit force-abort. It propagates
immediately; structured result construction or attachment is not guaranteed,
and Agent Tools performs no recovery-of-recovery, further cleanup recovery,
provenance preparation, persistence retry, or finalization retry. Already
completed host mutation and already durable provenance remain as they are. In
particular, absence of a durable provenance record after force-abort is not
evidence that no host mutation occurred. A later Agent Tools mutation requires
fresh machine-state rediscovery and a newly generated plan.

Process-local serialization protects one read–execute–write transaction from
lost updates within Agent Tools. Portable cross-process locking is outside
issue #52; independent processes and unrelated package-manager users are not
claimed to be excluded.

The managed-state execution entry point is the sole supported mutation
boundary. The lower-level plan executor remains an internal primitive for that
boundary and focused tests; it is not an alternate public mutator. Both use one
re-entrant execution lock so state preflight, mutation, and persistence cannot
interleave with another supported mutation in the same process.

## Consequences

- Diagnostics can distinguish currently detected external state from recorded
  Agent Tools mutation requests without treating either as ownership.
- A persistence error after successful mutation is a structured partial
  success with both outcomes retained.
- One cancellation request receives controlled structured handling; another
  interrupt during that handling is an immediate force-abort with no managed-
  result guarantee.
- Schema evolution requires an explicit, tested migration for each supported
  older version.
- The document may grow without bound in v1; any compaction policy is a future
  human-reserved persistence decision.

## Non-goals

This decision adds no provider uninstall, public `tools install`, desired-state
configuration, package ownership, public path override, portable inter-process
lock, retention policy, or unrelated provider lifecycle behavior.
