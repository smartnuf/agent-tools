## Scope

- Acceptance criterion or issue:
- In scope:
- Non-goals:
- Base commit:
- Merge owner:

## Evidence

- [ ] Focused commits form one coherent review wave.
- [ ] Repository-defined local validation passed, including `git diff --check`.
- [ ] CI and automated review completed for the exact current head.
- [ ] Findings have evidence-backed dispositions and no actionable thread remains unresolved.
- [ ] [Adaptation review](https://github.com/smartnuf/agent-tools/blob/main/docs/development-workflow.md#9-review-adaptations) was not triggered, or applicable impact, recovery, reusable lessons, evidence, and durable follow-ups are recorded.
- [ ] Roadmap/evidence was reconciled when this change advances readiness.
- [ ] Unrelated dirty state, stashes, branches, worktrees, and user configuration were preserved.

## Integration

- Current head:
- Current `origin/main`:
- [ ] The base has not moved, or latest `origin/main` was incorporated and the new head was revalidated and rereviewed.
- [ ] This stream owns merging. If not, stop merge-ready and await ownership.
- [ ] `--match-head-commit` will guard the verified head and strict required status checks still guard base freshness.
