# Final v0.2 guides and release notes — #122

- Base: `8dc67165945d04db135a2199a0e860db34b05abe` (merged #117).
- Milestone 8 open; 6/8 gates complete. This task owns the front-door gate.
- Estimate: 0.5–1 person-day excluding review/CI wait; actual effort untracked.
- Single merge owner; exact-artifact release qualification/publication is separate.

## Discovery and scope

Decisions 0007–0010 fix the sole installed CLI, named-only installation,
PyPI/uv distribution, optional documents and preserved M3 result semantics.
The merged #102 front door and #103/#109 updates already describe these pieces;
final reconciliation must make their ordinary-user examples match observed
platform limitations and keep published v0.1.2 distinct from unreleased v0.2.

Findings: the native quick-start example requests unavailable Windows
Ghostscript, assumes a PATH change despite the earlier absolute launcher setup,
and omits the command's catalogue-name/status summary. The optional-library
section and core upgrade path exist but need version-qualified presentation.
The repository-maintenance recipe should say it is for source development.
The built wheel uses README.md for its PyPI description. Current v0.2 release
notes are absent; historical release notes must keep their original meaning.

## Plan and specification

1. Preserve the casual-user PyPI/uv front door. Keep explicit version qualification
   for unreleased capabilities, absolute installed-launcher examples and the
   Windows Poppler/Ghostscript distinction. Do not invent an alternate provider.
2. Reconcile native names, authorization/dry-run/no-op and partial/uncertain
   recovery guidance with generated help; distinguish the documents extra from
   native capabilities. Preserve core/document migration and state boundaries.
3. Add v0.2.0 release notes with the accepted product boundary, migration and
   preservation guidance, exact retained native platform observations and gaps,
   and the fresh-Intent stop after v0.2. Do not imply an unpublished version is on
   PyPI or qualify untested variants. Current-version release-note commands join
   the existing generated-help drift check when the notes exist.
4. Validate help/guide drift, full baseline and package metadata including the
   rendered README payload, installed CLI, workflow/POSIX checks and ranged diff.
   Obtain exact-head CI/review before merging; update roadmap and milestone.

A seventh gate can complete on this PR merge. The remaining release gate needs
its own exact-artifact evidence and publication authorization; no tag, release
promotion or package upload occurs in this task.

## Implementation and validation

README native examples now use the installed launcher and separate Windows
Poppler from Unix Poppler+Ghostscript. Names, explicit authorization/no-op,
status/recovery and optional-document boundaries match Decisions 0009/0010.
Source maintenance is labelled accordingly. Reviewed candidate release notes
retain exact observed versions, source/wheel identity, migration/preservation
and common gaps. Public v0.1.2 remains explicitly distinct from the candidate.

All 433 tests, 43 parsed guide invocations (including current release notes),
POSIX syntax/PATH, actionlint with ShellCheck, wheel/sdist contents and installed
CLI checks pass. The wheel's UTF-8 Markdown description exactly matches README.md.
Doctor reports only the known missing native workstation tools. The front-door
gate completes on merge after exact-head CI/review; no release gate is claimed.
