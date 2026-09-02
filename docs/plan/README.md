# Planning and progress protocol

This directory is the durable answer to “where are we, what should happen next, and how much work remains?” The canonical snapshot is [`00-index.md`](00-index.md); detailed release gates are in [`08-releases/README.md`](08-releases/README.md).

This protocol owns roadmap selection, status, estimates, and progress reporting.
Implementation, pull-request review, concurrent merge ownership, integration,
and cleanup follow the canonical [development and review
workflow](../development-workflow.md). Non-trivial roadmap work uses that
workflow's proportional [top-level engineering
cycle](../development-workflow.md#top-level-engineering-cycle); planning is one
stage in that cycle, not a substitute for characterisation, discovery,
architecture/workflow mapping, or behavioural specification when those stages
are warranted.

## Starting roadmap work

Before changing code or automation:

1. Read the repository `AGENTS.md`, the status index, the relevant milestone, and applicable decision records.
2. Reconcile claimed status with the repository, tests, workflows, and published artifacts. Correct stale status before relying on it.
3. Verify that the current roadmap milestone has an open GitHub milestone, and
   that its planned issues (including the selected task) are assigned to it.
   Reconcile missing or stale assignments before implementation.
4. Preserve the intended outcome and select one incomplete acceptance criterion.
   Prefer blockers and the documented “next recommended work.”
5. Characterise the problem and its knowledge/risk profile proportionately.
   Re-characterise when the work adds a new regime such as mutation,
   persistence, a public format, another platform, privilege, asynchronous
   execution, an external service, destructive effects, hostile input, or
   multi-process coordination.
6. Use discovery, architecture/workflow mapping, and behavioural specification
   where the profile warrants them. Material knowledge gaps may require
   targeted primary-source research, prior art, experiments, fault injection,
   or real-environment evidence before production implementation; ordinary
   low-risk work does not require heavyweight artifacts.
7. Write a task plan containing the acceptance slice, scope, non-goals,
   dependencies, sequencing, affected files/platforms, experiment versus
   production work, validation, risks, external prerequisites, effort, and
   merge ownership where relevant.
8. Split work estimated above two person-days into reviewable tasks. A task may
   use several focused commits, but each commit should leave the branch
   understandable.

The plan records what work is intended. The specification records what must
remain true. Keep both proportional to the task.

Use these effort classes for initial task planning:

| Class | Expected effort |
|---|---:|
| S | up to 0.5 person-day |
| M | 0.5–1 person-day |
| L | 1–2 person-days |
| XL | split before implementation |

Estimates are engineering effort for one experienced contributor, not elapsed calendar time. Report registry approval, CI queueing, or review delays separately.

## Completing work

Update the plan in the same pull request when work changes readiness:

- change criterion state only when its evidence exists;
- link or name the test, workflow, commit, artifact, or release providing evidence;
- record discovered work and estimate changes rather than hiding variance;
- recalculate incremental and cumulative remaining effort as ranges;
- identify one recommended next task and explain why it is next;
- move optional ideas to deferred work instead of expanding a milestone silently.

Use these states consistently: `not-started`, `in-progress`, `blocked`, `complete`, and `deferred`. A milestone is `complete` only when every required acceptance criterion is complete.

When the final required criterion gains durable evidence, reconcile GitHub in
the same completion loop: close completed issues, move valid follow-up work to
the milestone that owns it, confirm no required issue remains open, and
explicitly close the GitHub milestone. Verify the resulting milestone state;
zero open issues does not close a GitHub milestone automatically. The next
milestone starts only when its GitHub milestone is open and its initial planned
issues are assigned.

## Progress report format

Humans or agents asked for status should report:

```text
Current milestone and state:
Outcome already available to users:
Acceptance gates: N complete / N total
Work completed since the prior report:
Validation and durable evidence:
Blockers or risks:
Estimate: original, spent if known, and remaining range
Recommended next task, effort class, and reason:
```

Do not calculate progress from issue count alone. Report both completed gates and estimated effort. If actual time spent is unavailable, say so; do not invent it.

## Development expectations

- Prefer a focused issue or task for each acceptance criterion and associate it with the matching GitHub milestone before implementation.
- Use small commits that state the behaviour or evidence added.
- Test built artifacts rather than relying only on source-tree tests.
- Keep platform-independent behaviour common; isolate native installation and discovery behind explicit platform code.
- Treat README commands as testable interfaces.
- Preserve least-privilege release permissions and publish only from reviewed, versioned sources.
- At milestone completion, freeze its factual record except for corrections,
  put subsequent work in the next milestone, and verify that the completed
  GitHub milestone is closed.
