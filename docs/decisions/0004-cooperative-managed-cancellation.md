# ADR 0004: Cooperative managed cancellation

- Status: Accepted
- Date: 2026-09-02
- Decision owners: project maintainer (human-authorized reconciliation for issue #52)
- Related: ADR 0002, ADR 0003, issues #26, #51, and #52

## Context

ADR 0003 requires one controlled cancellation request, truthful attempted-
mutation evidence and persistence outcomes, and immediate force-abort for a
later interrupt. The first implementation treated Ctrl+C as an asynchronously
raised `KeyboardInterrupt` and attempted to preserve those truths at every
interruptible Python boundary.

Successive exact-head reviews found valid gaps during process cleanup, result
construction, failure-result construction, transaction finalization,
environment teardown, environment application, environment restoration,
lifecycle evidence materialization, exception stringification, and post-
verification `PlanningError` formatting. Operation-scoped cancellation state
and centralized evidence-materialization helpers improved individual paths but
did not converge. There is always another Python instruction between learning
a real-world fact and publishing the structured object that carries it.

Agent Tools does not need to make arbitrary Python bytecode atomic with OS
signal delivery. It needs a portable boundary that prevents the first SIGINT
from interrupting transaction code while still cancelling a running provider
command promptly and preserving ADR 0003's safety invariants.

## Design progression and rejected alternatives

The implemented design evolved through four materially different stages:

1. first Ctrl+C arrived as an asynchronously injected `KeyboardInterrupt`;
2. progressively wider exception boundaries and materialization guards tried
   to preserve cleanup, results, environment state, and persistence evidence;
3. one operation-scoped cancellation context centralized phase authority, but
   first cancellation was still injected asynchronously; and
4. the accepted design moved first-SIGINT handling to the edge as a cooperative
   request observed at semantic checkpoints.

Stages 2 and 3 fixed real local defects but did not structurally converge.
There is always another interruptible Python instruction between learning an
external fact and publishing its structured evidence, so protecting additional
expressions cannot close the family. The cooperative design removes that race
class instead of attempting to enumerate every bytecode boundary.

A worker thread or process was considered as an alternative way to isolate
transaction work but was not implemented. It would add a new lifetime,
coordination, and cancellation contract beyond the authorized synchronous
executor, while the outer broker and bounded polling checkpoints satisfy the
accepted requirement without that expansion. Any future worker-based design
requires separate human authority and prospective lifecycle closure.

## Decision

The first SIGINT during the supported managed mutation operation is an
asynchronous **request**, not an asynchronously injected transaction
exception. A small outer signal broker records that request and returns from
its handler. Internal code observes the operation-scoped cancellation
controller only at explicit semantic checkpoints. A second SIGINT after the
request is immediate force-abort and may raise asynchronously.

The controller has these monotonic phases:

| Phase | Meaning |
|---|---|
| `RUNNING` | No managed cancellation request has been observed. |
| `CANCEL_REQUESTED` | The first SIGINT was recorded; no asynchronous first-cancel exception was raised. |
| `CANCELLING` | A safe checkpoint accepted the request and bounded controlled cancellation is in progress. |
| `FORCE_ABORTED` | A later SIGINT requested immediate abort. No further structured recovery is guaranteed. |

The controller, not exception type or stack position, is the sole operation-
level authority for this phase. A checkpoint changes `CANCEL_REQUESTED` to
`CANCELLING` and returns cancellation state/data to its caller. First-SIGINT
transport through provider execution, report construction, and persistence is
cooperative; it is not a chain of `KeyboardInterrupt` catches. Existing typed
exceptions may remain for ordinary failures and final outward API
compatibility. The outer managed boundary raises `ManagedExecutionInterrupted`
only after it has materialized the managed result required by ADR 0003.

### Signal broker

The broker and controller are separate private concepts:

- the broker translates SIGINT into a controller request;
- the controller is passed through the supported operation and is the only
  interface used by transaction code.

The broker is installed only around the outer supported managed mutation
operation. It saves the prior disposition and restores it on every normal,
ordinary-error, and controlled-cancellation exit where force-abort has not
prevented restoration. The first handler invocation only updates controller
state and returns. It performs no output, logging, formatting, allocation of
reports, filesystem access, subprocess work, cleanup, or persistence. A later
handler invocation marks `FORCE_ABORTED` and raises the private typed force-
abort carrier immediately.

Broker teardown is the final cancellation handoff, not an unobserved gap after
the last business-logic checkpoint. The outer boundary first materializes the
managed result while the broker remains installed. Teardown then restores the
prior SIGINT disposition and, immediately after that restoration, consumes any
first request the broker recorded through that cutover by raising
`ManagedExecutionInterrupted` with the already-materialized result. Restoring
the disposition is the linearization point: a SIGINT handled by the broker
before it is restored is guaranteed to be consumed by this handoff; a SIGINT
delivered after restoration belongs to the prior handler and is outside the
managed broker interval. No normal return may occur from a request that the
broker recorded before its disposition was restored.

Python permits signal-handler installation only on the main thread. Managed
brokerage is therefore supported when the operation runs on the main thread
and Agent Tools owns normal CLI-style SIGINT handling. The broker may replace
only Python's default SIGINT disposition (`signal.default_int_handler` or the
platform-equivalent default disposition). If an embedding application has
installed any non-default custom handler, including an ignored disposition,
Agent Tools leaves it installed and authoritative; it does not claim managed
first-SIGINT semantics for that call. A custom handler that raises
`KeyboardInterrupt` produces an uncontrolled programmatic abort, not a
managed cancellation request.

Only the outer managed entry installs a broker. Internal/re-entrant execution
shares its controller and never installs another handler. A second independent
broker installation for the same process operation is an internal contract
error before provider mutation; it is not silently nested. The existing
process-local execution lock continues to serialize supported managed
mutations.

Direct or injected `raise KeyboardInterrupt` is distinct from supported Ctrl+C
delivery. Outside the broker it may propagate as an uncontrolled abort. Tests
must not use arbitrary `KeyboardInterrupt` injection as a substitute for the
supported first-SIGINT contract.

### Result-first transaction flow

Cancellation is transaction state and report data until the outer managed
boundary publishes the outward interruption:

1. provider execution accumulates a truthful `PlanExecutionReport`;
2. if mutation may have occurred, managed provenance preparation and atomic
   persistence consume that report and reach the strongest truthful terminal
   outcome;
3. public managed-result construction materializes those established facts;
4. the boundary then raises `ManagedExecutionInterrupted` when the controller
   records a controlled first cancellation.

A first request does not asynchronously interrupt exception formatting,
output-tail extraction, tuple/list construction, environment restoration,
report construction, provenance preparation, atomic replacement, durability
confirmation, or result attachment. Ordinary errors in those operations retain
their existing truthful classifications. A later SIGINT may force-abort any of
them immediately, preserving only facts already established.

### Safe checkpoint matrix

| Phase | Next safe checkpoint and controlled action | Facts that must survive | Second SIGINT |
|---|---|---|---|
| Managed preflight | Before mutation authorization proceeds; return a preflight interrupted/not-attempted report. | No command-start claim; any completed earlier facts in a re-entrant internal flow. | Immediate force-abort. |
| Before an action | Stop before its pre-action detector or mutation work; mark this and later actions not attempted while preserving earlier reports. | All earlier action reports. | Immediate force-abort. |
| Before each command launch | Do not call `Popen`/runner; report the current/later work not attempted and preserve earlier commands/actions. | All earlier command and action reports; no false launch claim. | Immediate force-abort. |
| Active subprocess | Supervision polls the controller at a short bounded interval rather than waiting for the command timeout. On request, terminate/reap with the existing bounded mechanism, drain bounded output, and report interrupted or supervisor-uncertain evidence. | Launch, bounded output, return/lifetime/quiescence evidence available at cleanup completion. | Immediate force-abort; no cleanup-completion guarantee. |
| Command completion/classification | First publish the completed command evidence and local outcome; then stop before another command/action. | Exact completed command evidence and earlier reports. | Immediate force-abort. |
| Environment application, detection, and restoration | Finish the current bounded environment scope, including restoration, then checkpoint before subsequent provider work. | Restored environment when no force-abort; completed command and detector facts. | Immediate force-abort; restoration completion is not guaranteed. |
| Post-action verification and detail/report construction | Finish truthful verification classification and publish its action/plan report, then checkpoint before later work. | Completed command evidence, observed verification facts, and failure detail. | Immediate force-abort. |
| Provenance preparation | When mutation may have occurred, finish preparation or truthfully classify an ordinary preparation failure, then proceed to the persistence decision. | Published execution report and pre-write persistence truth. | Immediate force-abort. |
| Atomic persistence before replacement | Do not checkpoint inside the atomic transaction; reach `FAILED`, `UNKNOWN`, or `SUCCEEDED` under ADR 0003. | Canonical-file/replacement/durability facts established before force-abort. | Immediate force-abort; current persistence certainty may remain incomplete. |
| Replacement/durability phase | Finish the current durability classification, publish it, then checkpoint. | The strongest terminal persistence fact that completed publication. | Immediate force-abort; no retry. |
| Final result materialization and broker teardown | Materialize and attach the result from established facts. Restore the prior handler, then consume any request recorded through that restoration cutover before allowing normal return. | Execution report, persistence outcome/detail, recovery guidance. | Immediate force-abort before restoration; after restoration the prior handler is authoritative. |

Polling responsiveness is an internal bounded-execution property, not a new
public timeout. The implementation must use a small testable wait slice and
must never defer an observed request until the full provider-command timeout.
It should use the existing synchronous supervision loop or another explicit
wakeup/polling mechanism; introducing a worker thread or process requires new
human authority.

### Obsolete implementation mechanisms

The cooperative implementation replaces machinery whose sole purpose is to
survive first-`KeyboardInterrupt` injection during arbitrary Python work,
including per-expression materialization guards, first-interrupt retry loops
for environment application/restoration, and branch-specific first-interrupt
fallback synthesis. The operation controller remains necessary for checkpoint
state and force-abort. Guards may remain only where they enforce immediate
second-SIGINT propagation or another independently documented non-SIGINT
contract.

## Consequences

- A first Ctrl+C is responsive at defined semantic boundaries without
  corrupting in-progress Python evidence construction.
- Cancellation during a running provider command still performs bounded
  termination/reaping and retains post-launch evidence.
- Provenance and atomic persistence reach truthful existing terminal outcomes
  before controlled cancellation is surfaced.
- A second Ctrl+C remains deliberately abrupt and may prevent cleanup,
  restoration, persistence, or result publication from completing.
- Embedded/custom-handler calls retain the embedding application's semantics
  and do not receive Agent Tools' managed-cancellation guarantee.
- Programmatic `KeyboardInterrupt` is not a supported first-Ctrl-C test model.

## Non-goals

This decision adds no worker thread/process, public cancellation token or API,
portable cross-process signalling, rollback, uninstall, ownership, desired
state, managed-state schema change, timeout grammar change, or automatic
provider/persistence retry.
