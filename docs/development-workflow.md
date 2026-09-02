# Development and review workflow

This is the canonical workflow for changing this repository. Its top-level
engineering cycle is **Intent → Characterise → Discover → Map → Plan →
Specify → Execute → Review → Learn**. Execution contains the existing inner
pull-request review-to-merge loop. The [planning protocol](plan/README.md) owns
roadmap status and reporting details; this document owns development,
validation, review, integration, and cleanup.

## Operating principles

- Derive decisions from current repository and GitHub state, not session
  memory. Record the commit IDs on which decisions depend.
- Keep scope and non-goals explicit. Do not absorb optional or architecturally
  distinct work merely because review discovers it.
- Prefer small, focused commits and additive, reviewable changes.
- Treat CI, reviews, and merge readiness as evidence about one exact commit.
- Preserve unrelated user state, including dirty files, stashes, branches,
  worktrees, configuration, and credentials.
- Stop when required authority, safety, evidence, or architectural agreement
  is absent.

## Concurrent development and serialized integration

Multiple autonomous agents may develop concurrently from a common published
`origin/main`. Independent clones are preferred for long-lived concurrent work;
worktrees isolate files but still share repository state such as refs and
stashes.

Concurrent streams should own distinct tasks and pull requests and avoid
unnecessary overlap in files or roadmap authority. Exactly one autonomous
stream at a time is the **merge owner** for integration into the default
branch. Merge ownership concerns integration, not authorship: non-merge-owner
streams may branch, commit, push, open pull requests, run review waves, and
reach a clean **merge-ready** state, but they must not merge.

Two autonomous agents must never independently run the final verify-to-merge
sequence against `main` at the same time. For now, explicit merge-owner
authority plus task and file boundaries is the coordination mechanism. Do not
introduce a lock service unless actual contention demonstrates a need.

A waiting pull request's earlier green CI and review cease to be sufficient
when `main` advances. Before that stream assumes merge ownership, it must:

1. fetch the latest `origin/main`;
2. incorporate it, normally by rebasing its task-owned branch, or by merging
   when published history or repository policy makes that safer;
3. resolve conflicts semantically, reconciling intent and current roadmap
   truth rather than accepting either side mechanically;
4. rerun the complete repository-defined local validation;
5. push the new head safely, recording the previously verified remote branch
   SHA and using an explicit lease such as
   `--force-with-lease=refs/heads/<branch>:<expected-old-sha>`—never plain
   `--force` or a lease whose expectation was silently moved by a later fetch;
6. wait for CI and automated review of that exact new head; and
7. repeat the fresh unresolved-thread and current-head merge gate.

If streams develop a semantic dependency, overlap materially, or claim
conflicting roadmap authority, halt and reconcile ownership and order. Do not
race to merge.

Issue #32 and its governance pull request are the first deliberate exercise of
this rule. The M1.5 stream owned merging when governance work began and merged
while the governance branch was being prepared. This run remains explicitly
unauthorized to merge, and no successor merge owner has been assigned; the
governance stream must stop merge-ready and await ownership.

## Top-level engineering cycle

The cycle is a learning loop, not a rigid waterfall. New evidence may return
work to any earlier appropriate stage. Apply each stage proportionately: a
small, local, read-only change may need only a few recorded sentences, while a
novel persistent host mutation may need research, experiments, an ADR, and a
fault matrix. Repository-wide preservation, validation, exact-head, review,
authority, and merge-owner gates always remain in force.

Before entering the cycle, establish current truth:

1. fetch origin;
2. inspect the current branch and `HEAD`, `origin/main`, status, stashes,
   remotes, and relevant worktrees;
3. inspect open pull requests, issues, milestones, checks, and review state;
4. read `AGENTS.md`, the canonical status index, the relevant milestone and
   accepted decisions; and
5. reconcile documentation claims with code, tests, workflows, merged changes,
   and published artifacts.

Confirm that roadmap work has a corresponding open GitHub milestone and that
the selected issue is assigned to it. Treat an unassigned roadmap issue, a
closed milestone for active work, or an open milestone whose roadmap gates are
already complete as stale state to reconcile before implementation. Record
pre-existing dirty paths and stashes. Never hide, overwrite, apply, drop, or
include them unless the task explicitly owns them.

### 1. Intent

Preserve what is actually wanted before translating it into implementation.
Capture, in proportion to the work, the desired outcome, user or beneficiary,
success criteria, constraints, non-goals, and important qualities that must not
be sacrificed. Record the larger vision or ambition when it materially changes
design choices. The workflow serves the goal; it must not force every goal into
the same implementation process.

### 2. Characterise

At project creation, and whenever an existing project materially expands its
problem envelope, classify the engineering problem before selecting an
architecture or workflow. Relevant dimensions include:

- computational/read-only versus side-effecting;
- reversible versus irreversible;
- local versus externally coupled;
- deterministic versus observationally uncertain;
- ephemeral versus persistent;
- single-platform versus cross-platform;
- trusted versus hostile or untrusted input;
- synchronous versus concurrent or asynchronous;
- bounded versus potentially long-running;
- internal/private versus persistent/public compatibility surface;
- ordinary user-level versus privileged or destructive;
- one actor versus independent processes, users, or services;
- mature/well-understood versus novel/poorly understood;
- easily simulated versus dependent on real environments;
- low consequence versus high consequence; and
- stable dependencies versus external/provider instability.

Do not require a large form for every task. Use proportional judgment.

Classify significant assumptions where useful as **known and evidenced**,
**believed but insufficiently evidenced**, **unknown but discoverable**,
**unknown requiring experiment**, **inherently uncertain**, or **genuinely
novel**. The purpose is to expose important knowledge gaps before
implementation.

For work that warrants it, record a compact multidimensional risk profile, not
one aggregate score. For example, host mutation may be high, reversibility low,
persistence and platform variance high, provider dependency medium, knowledge
maturity medium-low, and testability medium. Record the architecture or process
consequence of every important dimension. The profile may communicate
complexity, select a workflow, require independent research/review or an
experiment, and qualify estimates and confidence. It may become a concise
durable project profile when material uncertainty or risk will outlive the
task; trivial work does not need that artifact.

Re-characterise instead of merely extending an old plan whenever the work adds
a materially new regime, including:

- read-only to mutation;
- in-memory to persistence;
- private representation to a public or versioned format;
- single-platform to cross-platform;
- unprivileged to privileged operation;
- synchronous to concurrent or asynchronous operation;
- local to networked, distributed, or external-service operation;
- reversible to destructive or non-replayable operation;
- trusted to hostile input; or
- one process to multi-process coordination.

### 3. Discover

Discovery determines what is true and reduces important uncertainty. Choose
methods from the characterisation: inspect repository history and existing
implementations; read primary specifications and platform documentation;
research relevant prior art and mature patterns; obtain independent
architecture analysis; prototype or benchmark; run disposable-environment
experiments, fault injection, adversarial tests, or real-environment exercises;
and compare platform behaviour empirically. Preserve unresolved uncertainty
explicitly when resolving it would not be economical.

#### Query and prior-art trigger

Do not research ceremonially. Query or experiment only when the result can
materially affect design, risk, specification, or workflow. Targeted primary-
source and prior-art research is especially appropriate for unfamiliar or
known-hard operating-system semantics, signals, process supervision, privilege,
crash consistency, filesystem paths, concurrency, persistence, schema/version
compatibility, package managers, security boundaries, standards/protocols,
cross-platform runtime differences, or repeated architectural review churn.
Record conclusions, not a bibliography dump.

#### Experiment trigger

Prefer an experiment, prototype, or real-environment exercise when
documentation is ambiguous, platform behaviour is empirical, a provider may
differ from its nominal contract, asynchronous/lifetime behaviour is hard to
reason about, an important assumption is inexpensive to test, or architecture
depends on performance or failure behaviour. An experiment gathers evidence;
it does not automatically become production architecture.

### 4. Map

Translate discovery into both architecture/design choices and process/workflow
choices. Discovery asks **what is true?** Mapping asks **given that truth, what
engineering responses follow?**

Architecture mappings are problem-specific, not a fixed cookbook. Examples
include:

- irreversible external mutation → explicit authority boundary and no blind
  retry;
- observational uncertainty → explicit certainty states and monotonic
  evidence;
- persistence → schema, version, compatibility, and crash-consistency
  contracts;
- asynchronous signal delivery → edge broker and cooperative internal
  cancellation;
- externally owned packages → provenance distinct from ownership;
- filesystem replacement → pathname-integrity classification;
- cross-platform operation → one semantic contract with platform-specific
  mechanisms;
- unbounded command output → bounded evidence retention; and
- multi-process mutation → an explicit decision whether native manager
  locking suffices or additional coordination is promised.

Map the workflow from the same profile. Low-risk, local, read-only, mature work
may use the lightweight task/PR loop. A persistent public contract normally
needs specification or an ADR before implementation. High novelty calls for
discovery or a prototype; multiple high-risk boundaries call for a prospective
closure matrix; privileged/destructive effects call for independent
architecture and safety adjudication; real-platform dependence calls for
native or disposable integration evidence; provider instability calls for an
explicit retry/evidence policy; high uncertainty favors smaller experimental
slices; and concurrent autonomous streams require explicit merge ownership and
integration order. The workflow is partly an output of characterisation and
mapping, while repository-wide minimum safety gates remain mandatory.

#### Prospective closure trigger

Before implementation that materially combines several high-risk dimensions,
apply the existing architectural closure dimensions prospectively. Typical
triggers include host mutation, privilege, process lifetime, asynchronous
cancellation, persistence/durability, filesystem namespace integrity,
concurrency, external provider/service semantics, persistent/public
compatibility, and multiple platform execution models.

Inspect applicable identity, authority, ownership/provenance, lifecycle,
partial failure, retry, idempotence, I/O, verification, persistence,
compatibility, platform, preservation, privilege, and authorization seams.
Classify each as addressed, already enforced with evidence, deliberately
inapplicable, human-reserved, or independently tracked. The sweep remains
bounded by the intended goal and slice; it does not authorize neighboring
product features.

### 5. Plan

Planning selects a bounded route through the mapped problem. For non-trivial
work record proportionately:

- the selected acceptance slice, scope, and non-goals;
- dependencies and sequencing;
- affected files and platforms;
- experiment work versus production work;
- validation and required evidence;
- effort and expected external prerequisites; and
- merge ownership when streams overlap.

Split work exceeding the planning protocol's reviewable-size limit. Use a
focused issue where GitHub tracking adds useful scope and evidence.

**Plan says what work we intend to do.** It does not replace the behavioural
contract.

### 6. Specify

Before production implementation of non-trivial or risky behaviour, establish
what must remain true. Specification is proportional to risk: an ordinary
change may need only a few explicit invariants, while side-effecting sysadmin
work should normally specify the relevant authority boundaries, state/phase
model, invariants, supported and unsupported inputs/contexts, partial failure,
certainty semantics, retry/idempotence, preservation obligations,
persistence/public compatibility, concurrency, platform/environment
distinctions, failure/closure matrix, and required test oracle or evidence.

Product, safety, persistence, or public-policy decisions belong in ADRs when
appropriate; not every internal contract needs a permanent ADR.

**Plan is what we will do. Specification is what must be true.**

### 7. Execute

Create a task-owned branch from the reconciled base and use the inner loop
below. Preserve coherent multi-commit/single-push review waves, complete local
validation before push, exact-head CI and automated review, finding
adjudication, merge-owner serialization, convergence circuit breakers, the ban
on empty retrigger commits, and preservation of user state. Several focused
commits may implement one acceptance slice; each must leave the branch
understandable.

### 8. Review

Review the model and contract as well as the local implementation. Significant
findings should return to the layer that failed:

- implementation wrong → Execute;
- specification incomplete → Specify;
- architecture mapping wrong → Map;
- important knowledge missing → Discover;
- problem incorrectly characterised → Characterise; or
- goal or constraint misunderstood → Intent.

Do not automatically turn every valid comment into another local patch. When
repeated exact-head reviews find adjacent valid defects in one decision family,
treat that churn as evidence that the model or specification may be incomplete.
Return to Characterise, Discover, Map, or Specify as appropriate and ask whether
the abstraction should be centralized, a missing fact/state needs explicit
representation, an invariant is distributed across too many boundaries, prior
art or an experiment is needed, the architecture is wrong, the requirement is
economically impossible or too strong, a simpler product contract is better,
or human authority is required. Resume implementation only after reconciling
the model. Existing correction-wave and architectural-family limits remain
circuit breakers.

### 9. Learn

Harvest reusable lessons from execution and review. Learning may update the
architecture, specification, risk profile, workflow, estimates, or reusable
engineering knowledge. For routine work it may record that no reusable
adaptation was found. For significant work, deliberately decide whether each
lesson belongs in an ADR, a reusable architecture/engineering note, a test or
fault-injection fixture, a standing workflow instruction, roadmap/risk
information, or nowhere permanent.

Learning completes a bounded cycle; it does not authorize the next roadmap
slice.

### Reconcile completion and stop

After durable evidence exists:

- update the criterion and canonical status in the same change that advances
  readiness;
- identify the test, workflow, commit, artifact, release, or merged change
  providing evidence;
- update estimates when new facts justify it;
- record unresolved work instead of hiding variance;
- reconcile issue assignments and the GitHub milestone state; and
- recommend one next task.

When this change completes a milestone, confirm that every required acceptance
criterion has durable evidence, close or move every remaining issue according
to its actual owner, explicitly close the GitHub milestone, and verify it is
closed. GitHub does not close a milestone merely because its open-issue count
reaches zero. Open the next milestone and assign its initial planned issues
only when roadmap work is ready to begin there.

Do not infer completion from prose, commit count, or issue count. A pull request
that is merely open or merge-ready is not merged evidence. Always recommend the
next task, but execute it only when the governing instruction explicitly
authorizes continuation. Continuing authority does not override a halt
condition or expand permitted scope.

## Inner loop: pull request review to merge

### 1. Establish the branch and base

Record the base commit from `origin/main`. Create a focused branch and confirm
that only task-owned changes will be made. Avoid overlapping files controlled
by a concurrent stream; if overlap becomes necessary, reconcile first.

### 2. Implement focused commits

Keep commits independently understandable. Separate behaviour, evidence, and
unrelated corrections when that improves review, but do not manufacture
ceremonial commits for inseparable edits.

### 3. Run local validation

Before every push, run all validation relevant to the complete wave. The
repository baseline is:

```text
repository-managed Python: python -m unittest discover -s tests
git diff --check <base>...HEAD
PowerShell parser/syntax checks for repository PowerShell files
sh -n checks for portable POSIX shell files
bash -n checks only for genuinely Bash-specific files
repository launcher: agent-tools doctor, when relevant
build/distribution checks, when packaging or installed behaviour may change
```

Run Python commands through the environment established by repository setup;
do not assume an unconfigured system interpreter can import checkout code. In
this repository after bootstrap, use `bin\agent-python.cmd` on Windows or
`bin/agent-python` on POSIX systems. An explicitly configured source-tree test,
such as setting `PYTHONPATH=src`, is acceptable when its environment is recorded
with the result.

Likewise, run diagnostics through `bin\agent-tools.cmd doctor` on Windows or
`bin/agent-tools doctor` on POSIX systems. Do not assume bootstrap made the
launcher globally discoverable, because PATH changes are deliberately opt-in.

`<base>` is the recorded integration base, normally `origin/main`. The ranged
`git diff --check` is required after commits so it examines the review wave;
the no-revision form alone checks only unstaged working-tree changes and is not
sufficient on a clean committed branch.

Known unavailable optional host tools may be reported as environmental facts;
do not conceal them or misrepresent them as passing. Documentation-only work
still runs the baseline tests and syntax checks unless a command is genuinely
unavailable, in which case report the limitation.

Also inspect the final diff for secrets, private material, generated files,
unrelated changes, and duplicated or contradictory normative text.

### 4. Push one coherent review wave

A review wave consists of one or more focused local commits plus complete local
validation, followed by one push. Push when the wave is coherent and ready for
CI and review.

Do not push:

- a partial correction wave;
- merely to trigger or hurry review;
- while CI or automated review is still evaluating the current head;
- with failing required validation; or
- when a finding requires unresolved authority or scope expansion.

Every push creates a new head and invalidates prior-head CI and review as merge
evidence.

### 5. Wait for exact-head evidence

Record the remote PR head SHA. Wait for all required CI jobs and automated
review to complete for that exact SHA before beginning another review wave or
declaring the PR clean. A completed review of an older commit is not evidence
for a newer head.

### 6. Classify and disposition findings

Classify each finding independently by:

- **validity:** valid, partly valid, invalid, or insufficiently evidenced;
- **impact:** P1, P2, P3, or editorial; and
- **scope:** required here, safe follow-up, or out of scope.

Reviewer severity is an input, not a rigid algorithm.

| Finding | Normal disposition |
|---|---|
| Valid P1 | Fix before merge, or halt if correction requires unsafe or unauthorized expansion |
| Invalid P1 | Rebut with concrete evidence; never ignore |
| Valid, in-scope P2 | Fix before merge |
| P2 exposing a safety or architectural contradiction | Fix if bounded; otherwise halt for reconciliation |
| Independent P2 not required for this PR's correctness | Record follow-up work and explain why this PR remains sound |
| Invalid P2 | Rebut with concrete evidence |
| P3 or editorial | Fix when bounded and low-risk; otherwise explain or defer without creating review churn |

“Out of scope” cannot defer a change necessary to make the PR's behaviour safe,
correct, or consistent with its acceptance criterion.

#### Architecture adjudication

Architectural reasoning is not itself a halt condition. When a finding touches
an architectural seam, classify its **decision family** before deciding whether
authority is missing:

| Class | Meaning | Authority and disposition |
|---|---|---|
| Architectural clarification / contract completion | Makes an accepted invariant explicit or closes a hole required to preserve it. Materially different outcomes are excluded by existing authority. | Continue autonomously after evidence-backed adjudication. Update an existing ADR only when its normative text is incomplete. |
| Bounded architectural evolution | Selects an internal, reversible structure while preserving accepted product, safety, compatibility, persistence, and roadmap contracts. | Continue only after independent adjudication confirms the boundary and records the alternatives excluded by existing constraints. |
| Architectural policy / product decision | Changes or chooses what the product promises, supports, mutates, exposes, prioritizes, persists, requires, or removes. | Complete the bounded closure sweep, then halt for human authority and, when accepted, record the new or revised durable decision. |

The adjudicator must be independent of the implementing context: use a
separate read-only agent/context or a human reviewer that has not proposed the
implementation. If no independent adjudicator is available, contract
completion may proceed only when accepted text determines one conservative
result without a material design choice; bounded evolution and product policy
halt for human adjudication. The adjudicator does not edit the branch.

Adjudication derives authority from current repository and GitHub evidence,
never session memory. Its PR-local record must identify:

- the exact head and base examined, the finding, and its decision family;
- the acceptance criterion, accepted ADRs, standing safety rules, public or
  persistent interfaces, tests, and platform evidence that govern the result;
- the conservative invariant and why materially different outcomes are either
  excluded or require human authority;
- scope, non-goals, affected execution contexts, and evidence needed for the
  correction; and
- whether an ADR clarification, new decision, or durable follow-up is needed.

Delegated adjudication cannot infer or enlarge authorization. Always reserve
for a human any choice that sets product intent, risk posture, compatibility or
supported-platform commitments, persistent/public contracts, privilege or
destructive-mutation policy, material dependency/service commitments, or
roadmap scope and priority. Existing preservation, verification, security,
mutation-safety, exact-head, review, and merge-owner gates remain mandatory.

After the first finding in a decision family, perform an **architectural
closure sweep** before the correction wave or a human-authority halt. Inspect
the affected seam for its adjacent consequences:

- identity, ownership/provenance, and execution context;
- lifecycle, partial failure, recovery, retry safety, and idempotence;
- input, output, verification, and persistent/public contracts;
- compatibility and platform/environment boundaries; and
- user-state preservation, privilege, and authorization.

Record each applicable consequence as addressed, already enforced with
evidence, deliberately inapplicable, human-reserved, or independently tracked.
The sweep is bounded by the acceptance criterion and does not authorize
neighbouring product work. Feed its required tests and documentation into the
next complete correction wave rather than waiting for review to rediscover
them one at a time.

For a fix, make a focused local commit. For a rebuttal, cite repository,
runtime, specification, or test evidence. For a deferral, link durable follow-up
work and explain the independence. Halt rather than assuming permission for a
materially larger design.

### 7. Reply and resolve

After a correcting commit is pushed, reply to the review thread with the commit
and relevant validation or changed contract, then resolve it. For a rebuttal,
record the evidence and deliberate disposition before resolving. Leave a
disputed high-impact finding open and halt for human judgment.

When review feedback is top-level and has no resolvable thread, add a PR comment
recording its disposition and evidence.

If corrections were required, accumulate the complete next correction wave,
validate, push once, and return to exact-head waiting.

### 8. Check convergence

The repository defaults are **15 correction waves** and **2 independent
architectural decision families** per pull request. A task or pull request may
declare different bounds only with a recorded reason. The limits are separate
circuit breakers, not targets and not substitutes for semantic convergence
judgment.

A correction wave is one coherent, completely validated push made in response
to review findings. Every such push consumes the correction-wave counter.
Architecture adjudication does not reset, replace, or stop that counter. Count
architectural decision families independently under the adjudication rules,
not from raw comments, files, or waves: later manifestations of one adjudicated
invariant remain in that family.

Process up to each effective maximum; halt before beginning a wave or decision
family that would exceed its bound. Halt earlier when adjudication identifies a
human-reserved choice, safe correction materially exceeds the acceptance
criterion or authority, review is demonstrably not converging, or another halt
condition applies. A human may deliberately authorize another family or wave
and must record that extension and its reason. Waiting for an active
current-head review is not non-convergence.

### 9. Review adaptations

Run this checkpoint when work encountered unexpected external behaviour,
provider instability, a partial-state failure, a changed assumption or process,
or reconciliation produced a materially different implementation. Routine
changes with none of these conditions record the checkpoint as not triggered;
they do not require a retrospective.

Answer the applicable questions concisely in the pull request or linked durable
record:

- Could the failure or changed assumption also affect users, releases, another
  platform, or another execution context?
- Is execution bounded, observable, retry-safe, and idempotent? What partial
  state remains after failure, and how can a user or operator recover safely?
- Can a dependency or command falsely report success? Which outcome is
  independently verified instead?
- Is the response repository-specific or a reusable cross-project pattern?
  Which tests, documentation, automation, or standing instructions preserve
  the lesson?
- Did the adaptation expose an independent defect? If valid, track it durably
  and explain why immediate correctness does not depend on fixing it here.
- Should the new rule apply more broadly, or must its scope remain deliberately
  narrow?

Adaptation review does not expand the current acceptance criterion. Fix
anything required for the current change to be safe and correct; track valid
independent defects and reusable follow-up separately rather than silently
absorbing them or leaving them only in review discussion.

### 10. Verify merge readiness

After automated review reports completion, perform a fresh, read-only gate as
a distinct operation:

1. fetch and record `origin/main` and the remote PR head;
2. confirm local intent matches the remote PR head;
3. confirm every required check passed for that exact head;
4. confirm automated review completed for that exact head;
5. query review threads again and confirm no unresolved actionable thread;
6. confirm mergeability, scope, roadmap/evidence consistency, issue assignment,
   and intended GitHub milestone state, with no unresolved contradictions; and
7. confirm that the stream currently owns merging.

If the base moved, use the concurrent-integration procedure before treating
earlier green evidence as sufficient.

The final verification and merge must be separate operations. Never place an
unconditional merge after a check query in the same shell command, script, or
tool batch: the head, base, review, or thread state may change between them.

A non-merge-owner stops here and reports **merge-ready, awaiting merge
ownership**.

### 11. Merge and clean up

Only the merge owner may merge. Immediately before the separate merge action,
repeat any volatile parts of the gate needed to ensure its decision is still
current. Integration must guard both the verified head and the verified base.
For this repository, the supported mechanism is:

- pass the exact verified head to
  `gh pr merge --match-head-commit <verified-head>`; and
- rely on strict required status checks on `main`, which require the pull
  request branch to be up to date and invalidate merge readiness when `main`
  advances.

The command's head guard and strict branch protection's base-freshness guard are
both required; `--match-head-commit` alone is insufficient. Final verification
and merge remain separate operations, so the server-side guards must reject a
stale decision if either input changes between them. If branch policy is absent,
disabled, or no longer strict, halt autonomous merge rather than weakening the
current-base validation contract. An unconditional merge is prohibited even
after a successful preceding query.

A hosting merge queue that validates the resulting merge group could replace
this mechanism in future. Although CI accepts the `merge_group` event, GitHub
does not currently offer merge queues to this public repository because it is
owned by a personal account rather than an organization. Do not present a merge
queue as available until repository ownership and settings make it observable.

After merge:

1. confirm the merge result and merge commit;
2. fetch origin;
3. synchronize the primary local `main` with `origin/main` without discarding
   unrelated state;
4. remove only task-owned worktrees, branches, and remote-tracking refs;
5. preserve and report unrelated stale refs rather than running an
   unconditional repository-wide prune;
6. verify local `main` equals `origin/main`; and
7. report status and preserved stashes or dirty state.

## Halt conditions

Halt and report the evidence and required decision when:

- an external account, registry, credential, approval, or publication
  prerequisite is unavailable;
- completion requires an unsafe host or user-configuration mutation;
- work contradicts an accepted decision or acceptance criterion;
- architecture adjudication finds a human-reserved policy/product choice, or a
  materially new data, discovery, persistence, mutation, or public-contract
  boundary whose semantics are not determined by accepted authority;
- a necessary correction materially expands scope or authority;
- required validation or CI fails and cannot be corrected within scope;
- current-head review or mergeability cannot be established reliably;
- a valid blocking finding remains unresolved;
- review churn stops converging within the declared bound;
- unrelated dirty, stash, branch, or worktree state cannot be preserved safely;
  or
- concurrent streams expose a semantic dependency or conflicting roadmap
  authority that has not been reconciled.

An external wait by itself is not a halt. Remain in the appropriate waiting
state when continued monitoring is authorized.

## Historical exercises

The policy was checked against recent repository history:

- PR #18 required a new review for head `8bce1a1` because the earlier review
  covered `73df3e6`.
- PR #20 was not safely merge-ready when a late valid finding invalidated its
  completion evidence; PRs #21 and #22 correctly supplied bounded workflow
  recovery and new published-release evidence rather than preserving the stale
  claim.
- PR #28 demonstrates the adjudication boundary. Desired-state backup/restore,
  provider-plan evidence, and removal-safety symmetry completed invariants
  already fixed by repository safety rules and ADR 0002, so a closure sweep
  could have kept those findings in one contract-completion family. Whether
  M1.5 promised a publicly published artifact instead changed the milestone's
  user-visible outcome; halting for human choice between publication and a
  narrower build-readiness promise remained required.
- PR #76 demonstrates why architectural comments are not counted mechanically.
  Its one-machine plan identity, WSL-local context, executable-evidence
  consistency, native-manager suitability, and complete verification policy
  were adjacent consequences of ADR 0002's accepted provider-selection and
  plan-boundary invariants. Independent adjudication plus a closure sweep could
  have authorized their bounded completion. A request to add mutation,
  persistence, package-manager lifecycle, or a new supported-provider promise
  would still have crossed into a human-reserved decision family.
- PR #78 initially retained a narrow three-wave local bound. Its own review
  demonstrated that bounded, semantically converging governance corrections
  could exhaust that circuit breaker prematurely; explicit human authority
  then established the repository defaults above. This was an adaptation
  discovered during review, not part of issue #77's original authorization.
- Issue #32's governance PR began with the M1.5 stream as merge owner. After
  that stream merged, governance incorporated the new `main`, remained
  unauthorized to merge, and had to stop merge-ready pending a newly assigned
  owner.
- PRs #37 and #39 adapted to an unreliable external Windows package provider by
  separating deterministic required CI from real provider integration, bounding
  installer execution, preserving diagnostics, rejecting false-success exit
  codes through executable verification, and allowing only one inspected
  same-head retry. A failed provider may leave partial package-manager state;
  after the provider recovers, the existing idempotent install route is safe to
  rerun and executable verification determines the usable outcome. Those
  controls are a reusable external-provider pattern and remain in automation
  and standing instructions. The same review raises a separate user-bootstrap
  question: comparable provider failure may affect an opt-in workstation
  install, but neither PR needed to redesign bootstrap to be correct, so any
  investigation belongs in focused follow-up rather than their acceptance
  scope.
- Reconciliation of PR #37 also exposed the editable-install `doctor` crash.
  That independent defect did not invalidate the PR's one-line retry rule; it
  was tracked as issue #40 and fixed separately by PR #42, preserving both
  immediate scope control and a durable path to correction.
