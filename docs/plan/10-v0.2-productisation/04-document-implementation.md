# #109: Implement optional document installation

Base: `3fd4cfbb953c528681b56eca98c67c866baeb64a`.
Milestone 8 remains open; #109 and parent #57 own the end-to-end acceptance.
Decision 0010 is authoritative. This stream owns integration; preserve the clean
main checkout and existing shared document environment.

## Discovery and bounded split

The runtime change is localized to pyproject metadata and lazy doctor probes.
The existing release lifecycle driver, however, requires candidate identity to
match published v0.1.2, and primarily tests old published artifacts; HEAD is
used only to create desired state. It cannot supply the new migration contract
through a few extra assertions. A second real documents-capable release also
does not exist yet; fixture version transitions must not be called publication
evidence. This raises the original 1–2 day implementation estimate to 2–3 days.

Split into this runtime/installed-shape PR (1–1.5 days) and
[#111](https://github.com/smartnuf/agent-tools/issues/111) lifecycle evidence
(1–1.5 days). Actual effort is untracked; external waits are excluded. Keep
#109/#57 and the optional-document milestone gate open until the lifecycle
slice completes. No version bump, release publication, constraint upgrade,
native catalogue change, Python support expansion or document feature is part
of this first slice.

## Execution and validation

1. Record this plan before implementation.
2. Move the unchanged seven requirements into `documents`. Add explicit
   document validation to doctor while reporting optional absence/failures
   separately in default mode; preserve native check status contributions.
3. Add absent/partial/broken/healthy diagnostic fixtures, exact metadata checks,
   core/documents installed CLI checks and uv-owned environment-shape checks.
   Exercise both shapes outside a checkout with the same built wheel on all
   three platforms and in the pre-publication installed check.
4. Regenerate parser help/reference; update README/PyPI, packaging and platform
   guidance while clearly separating current v0.1.2 from next-release behavior.
   Retain checkout locks and bootstrap/update compatibility.
5. Run full unit, available platform syntax/PATH, both doctor modes, artifact
   rebuild/metadata, installed-shape, diff and exact-head CI/review checks.
   Use up to six correction waves with focused commits and one push per wave.
6. Merge through protected exact-head/current-base checks. Reconcile partial
   evidence and recommend #111 next; do not claim release qualification.

No new persistent application state or host mutation is introduced. uv owns
explicit Python environment requests. Disposable tests use private tool/bin
roots and never alter user profiles/native packages. Existing M3 tests retain
responsibility for native mutation/provenance/recovery behavior.
