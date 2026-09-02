# Managed mutation engineering pattern

This non-normative note captures reusable engineering lessons from issues
[#51](https://github.com/smartnuf/agent-tools/issues/51) and
[#52](https://github.com/smartnuf/agent-tools/issues/52). It explains how to
reason about sysadmin-style software that observes and mutates shared external
state. The implementation and review sequence is preserved in
[PR #79](https://github.com/smartnuf/agent-tools/pull/79) and
[PR #80](https://github.com/smartnuf/agent-tools/pull/80). This note does not
add product promises. The normative Agent Tools contracts remain
[ADR 0002](../decisions/0002-native-capability-provider-model.md),
[ADR 0003](../decisions/0003-managed-state-provenance.md), and
[ADR 0004](../decisions/0004-cooperative-managed-cancellation.md).

## Separate the facts

Keep these facts distinct:

- desired state;
- built-in supported or catalogue state;
- detected current state;
- the reviewed requested mutation;
- actual command and process evidence;
- post-action verification evidence;
- mutation provenance;
- persistence and durability; and
- ownership.

None implies another. A successful package-manager exit does not prove the
capability is usable. A provenance record does not prove the provider is still
present or owned. A durable write does not make the host mutation successful,
and a persistence failure does not erase a mutation already observed.

## Evidence-first transactions

Represent established external facts monotonically. Once a command has
launched or completed, later reporting, cleanup, formatting, or persistence
failures must not rewrite history into “nothing happened.” Publish facts at
explicit transaction boundaries and retain the strongest certainty actually
established.

Prefer explicit states such as not attempted, attempted, observed success,
observed failure, and uncertain supervision or durability over a single
Boolean success flag. Uncertainty describes the limit of the available
evidence; it is not permission to invent a stronger claim in either direction.

## Non-replayable mutation boundaries

A package-manager or system mutation is not an ordinary retryable function
call. After partial or uncertain execution:

- do not rerun automatically;
- do not infer idempotence;
- do not infer rollback or removal authority;
- establish that relevant activity has quiesced where possible;
- rediscover current reality; and
- generate and review a fresh plan.

Retry policy belongs to the external mutation contract, not to a generic
exception handler.

## Process lifecycle

Process creation, supervision, termination, reaping, output closure, and the
provider mutation are related but distinct facts. `Popen` success establishes a
launch even if reader initialization, waiting, cleanup, or result construction
later fails. Bound supervision and cleanup, retain bounded output evidence, and
preserve uncertainty when process or reader quiescence cannot be proved.

Do not treat leader exit as proof that descendants have released inherited
resources, and do not broaden termination authority merely to manufacture
certainty.

Choose and state the concurrency boundary. Agent Tools currently promises only
process-local serialization; portable cross-process coordination would add a
public and persistence contract, while native package-manager locking remains
external. Do not silently turn a local lock into a distributed guarantee.

## Cancellation

Signals belong at the edge. Translate the first SIGINT into operation-scoped
cooperative state and observe it at semantic checkpoints. Do not inject first
cancellation asynchronously through arbitrary transaction code. Complete the
bounded semantic unit needed to publish truthful evidence, then surface the
controlled interruption.

A second interrupt may deliberately trade reporting, cleanup, restoration, and
persistence guarantees for immediate termination. State that trade explicitly;
do not disguise force-abort as another recoverable first cancellation.

## Persistence

Treat persistent state as a long-lived compatibility surface even when its
first implementation is private. Define:

- the exact writer language and reader language;
- writer-to-reader reachability and version compatibility;
- malformed, hostile, unknown-version, and unreadable input behavior;
- crash consistency and atomic replacement;
- the point at which replacement becomes ambiguous;
- durability certainty; and
- preservation of unreadable or unsupported existing state.

Validate the complete serialized artifact through the production reader before
replacement. Compatibility begins when a format is accepted into the merged or
released product contract; transient development writers do not automatically
create a permanent migration obligation. After acceptance, narrowing the
reader below the accepted writer language requires an explicit compatibility
or migration decision.

Keep persistence outcome separate from host-mutation outcome. A verified
mutation followed by a pre-replacement write failure is a partial success with
provenance not recorded. A replacement or durability ambiguity is different
again. Neither case authorizes mutation replay.

## Filesystem namespace integrity

The pathname itself is input and state. When replacement safety depends on the
directory entry, classify it without following it. `FileNotFoundError` from
target resolution does not prove that the pathname is absent: a dangling
symlink is an existing entry. Preserve and reject symlinks, directories, and
other unsupported non-regular entries unless an explicit product policy says
otherwise.

Revalidate the entry at the replacement boundary when a time-of-check/time-of-
use change could invalidate the earlier classification.

## Platform differences

Define one semantic contract and implement explicit platform mechanisms. POSIX
path, process-group, signal, directory-sync, and package-manager behavior does
not automatically transfer to Windows, macOS, or WSL. Tests should assert the
semantic guarantee while allowing legitimate platform representations, such as
different symlink target spelling.

Use pure fixtures for combinatorial contracts and real or disposable platform
evidence for behavior that simulation cannot establish. Report which platforms
and architectures were actually exercised.

## Bounded evidence

External tools may hang or emit unbounded output. Bound command duration,
supervision and cleanup time, retained stdout/stderr, parser depth and numeric
domains, and evidence materialization. Mark truncation and uncertainty rather
than consuming unbounded resources or pretending evidence is complete.

## Fault and closure matrices

For difficult side-effecting seams, enumerate failures prospectively:

- before an effect;
- during an effect;
- after the effect but before observation;
- after observation but before publication;
- before persistent replacement;
- during ambiguous replacement or durability confirmation;
- during cleanup;
- during first cancellation and force-abort; and
- at platform-specific boundaries.

For each phase, record the authority, facts already known, facts that must
survive, certainty, retry policy, cleanup bound, and required test oracle. Apply
the broader prospective closure dimensions from the [development
workflow](../development-workflow.md#prospective-closure-trigger) when several
high-risk boundaries interact.

## Approaches that did not scale

The #51/#52 sequence supplied evidence about design method as well as code:

- **Increasingly local cancellation guards.** PRs
  [#86](https://github.com/smartnuf/agent-tools/pull/86) through
  [#90](https://github.com/smartnuf/agent-tools/pull/90) implemented broader
  operation state, teardown handling, and evidence-materialization guards.
  Each fixed valid defects, but adjacent interruptible instructions remained.
  ADR 0004's cooperative first-SIGINT architecture replaced the underlying
  model rather than adding another guard.
- **Independent shape validation.** Early schema checks validated fields and
  relationships piecemeal. PRs
  [#93](https://github.com/smartnuf/agent-tools/pull/93) and
  [#94](https://github.com/smartnuf/agent-tools/pull/94) showed that the useful
  invariant is writer/serializer/reader reachability plus bounded hostile-input
  handling, not a collection of locally reasonable checks.
- **Contents before namespace.** JSON corruption and durability received early
  attention, but final review found that following a dangling symlink could
  turn an existing unreadable entry into apparent absence. The pathname became
  an explicit integrity boundary before
  [PR #80](https://github.com/smartnuf/agent-tools/pull/80) merged.
- **Seam-by-seam reactive closure.** Repeated valid adjacent findings were not
  a review problem; they were evidence that the domain model and specification
  were incomplete. A prospective state/fact model and fault/closure matrix
  would have exposed the families earlier and reduced correction churn.

The general response to same-family review churn is therefore to return to
characterisation, discovery, mapping, and specification. Centralize the
abstraction or make the missing state explicit before resuming implementation;
do not assume the next local patch will make an incomplete model converge.
