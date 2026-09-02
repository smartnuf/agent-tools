# ADR 0003: Managed-state mutation provenance

- Status: Accepted
- Date: 2026-08-31
- Decision owners: project maintainer (human-authorized for issue #52)
- Related: ADR 0002, ADR 0004, issues #26 and #52

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

The managed-state pathname is an integrity boundary. It may be absent or name
an ordinary regular file only. Symlinks, directories, and every other
non-regular entry are unsupported and rejected without following, replacing,
repairing, or deleting the entry. Rejection preserves the entry, performs no
state mutation, and is reported separately from an absent document.

An absent document is an empty history. Current v1 is validated before use.
There is no speculative legacy migration. Corrupt documents and unknown schema
versions are visible and are never automatically overwritten. A mutation that
would require provenance persistence is refused before host mutation unless the
existing document can be understood and preserved. Read-only detected-state
diagnostics continue and report provenance failure separately.

Persistent-format compatibility begins when a schema version enters the
merged or released product contract. After that point, later implementations
must continue to read every document that the accepted writer could produce
for that version, or must make an explicit human-authorized version and
migration decision. An implementation must not silently narrow an already
released schema language.

Before a persistent schema's first merge or release, transient development
writers on pull-request heads do not create a permanent compatibility
obligation. Review may tighten that unreleased schema before acceptance without
adding speculative migration machinery. Schema v1 is finalized here with
nondecreasing intra-record UTC wall-clock timestamps:

`requested_at <= completed_at <= recorded_at`

Equality is valid. If the wall clock regresses within one mutation transaction,
the accepted writer clamps each later timestamp to its predecessor. The v1
loader rejects reversed timestamps as corrupt and neither rewrites nor deletes
the document. Earlier unmerged development artifacts are not migrated and do
not authorize any inference about ownership or current machine state.

Mutation/verification and persistence are independent outcomes. When a
positively verified mutation is followed by persistence failure, reporting
preserves the executor result and states either `provenance not recorded` or
`provenance durability unknown`. It does not relabel the host mutation as
uncertain, claim ownership, automatically retry mutation, or attempt uninstall
or rollback. Any later mutation requires fresh rediscovery and a newly generated
plan.

ADR 0004 governs managed cancellation. The first SIGINT is captured at the
outer supported boundary as a cooperative request and is accepted only at an
explicit safe checkpoint; it is not injected as `KeyboardInterrupt` into
transaction bytecode. One operation-scoped controller remains authoritative
from provider execution through managed finalization. Provider execution and
persistence publish truthful transaction facts before the outer boundary
materializes and raises the controlled `ManagedExecutionInterrupted` result.

A transaction fact becomes authoritative when it has been successfully
published to the managed transaction snapshot. `Succeeded` means durable
completion was published as the terminal persistence fact. `Unknown` means the
boundary cannot prove durability from its published facts; it does not assert
physical non-durability. Cancellation never authorizes automatic mutation or
persistence retry, ownership, rollback, uninstall, or removal. Any later
mutation requires fresh machine-state rediscovery and a newly generated plan.

A second SIGINT after the first request is explicit force-abort. It propagates
immediately; structured result construction, attachment, cleanup, environment
restoration, provenance preparation, persistence completion, and finalization
are not guaranteed. Already completed host mutation and already durable
provenance remain as they are. Absence of a durable provenance record after
force-abort is not evidence that no host mutation occurred.

Process-local serialization protects one read–execute–write transaction from
lost updates within Agent Tools. Portable cross-process locking is outside
issue #52; independent processes and unrelated package-manager users are not
claimed to be excluded.

The managed-state execution entry point is the sole supported mutation
boundary. The lower-level plan executor remains an internal primitive for that
boundary and focused tests; it is not an alternate public mutator. Both use one
re-entrant execution lock so state preflight, mutation, and persistence cannot
interleave with another supported mutation in the same process.

## Why these boundaries changed

Early issue-52 development validated persisted fields largely as independent
shapes. Exact-head review showed that this did not define one coherent format:
some writer-reachable values could be rejected while other writer-unreachable
or hostile combinations could be accepted. The accepted design instead treats
writer, serializer, and production reader reachability as one compatibility
contract and validates the serialized temporary document through the production
reader before replacement. The compatibility obligation begins with the first
merged or released writer, not superseded pull-request heads.

The initial reader also treated `FileNotFoundError` from target-following reads
as absence. A dangling symlink demonstrated why JSON contents are not the whole
integrity boundary: the pathname entry could exist, be unreadable through its
target, and later be destroyed by replacement. The accepted non-following entry
classification therefore distinguishes confirmed absence from every symlink or
other non-regular entry and fails closed.

These corrections did not change the core fact model. Detected state remains
the authority for current reality, provenance records only an Agent Tools
request, ownership is never inferred, and persistence certainty remains
independent of the host-mutation result.

## Consequences

- Diagnostics can distinguish currently detected external state from recorded
  Agent Tools mutation requests without treating either as ownership.
- A persistence error after successful mutation is a structured partial
  success with both outcomes retained.
- One SIGINT request receives cooperative controlled handling at ADR 0004's
  safe checkpoints; another SIGINT is immediate force-abort with no managed-
  result guarantee.
- Schema evolution requires an explicit, tested migration for each supported
  older version.
- The document may grow without bound in v1; any compaction policy is a future
  human-reserved persistence decision.

## Non-goals

This decision adds no provider uninstall, public `tools install`, desired-state
configuration, package ownership, public path override, portable inter-process
lock, retention policy, or unrelated provider lifecycle behavior.
