# v0.2.1 documentation correction — #124

## Authority and plan

The human chose v0.2.1 as the documentation-only correction and authorized
continuation through final post-distribution review. This covers reviewed
preparation, immutable tag creation, stable promotion, protected PyPI publication
and final evidence/roadmap reconciliation. v0.2.0 remains immutable. Base:
`ae05d08a10f0d0b1b38b6ab3e7ac9623c8518719`; its post-merge CI passed.

Estimate: S, up to 0.5 person-day engineering effort, excluding CI/review waits;
actual effort untracked. Root is the sole merge owner. Up to six correction
waves per bounded PR. #124 and milestone 8 remain open until final evidence and
reviewed reconciliation complete. No new authorization is needed for this
v0.2.1 sequence; new product/policy choices remain human-reserved.

Discovery found the README correction and maintained-guide fixes already merged
in #125. Release metadata is derived from README.md; package version is defined
in `src/agent_tools/__init__.py`, with explicit expectations in two test files and the CI release-version step.
Existing migration drivers derive their candidate version from wheel metadata.
The release and public-PyPI workflows support the patch without code changes.

## Scope and acceptance

1. Change only version identity, corresponding expectations, release notes and
   factual release/status documentation. Compare application source and
   dependency metadata against the immutable v0.2.0 tree; only the version
   identity may differ in application source.
2. Inspect wheel and sdist README metadata plus all maintained availability
   prose. Validate full baseline, guide parsing, distribution and installed
   contracts, then obtain exact-head CI and automated review before merge.
3. Verify post-merge main CI, create/push the annotated v0.2.1 tag, inspect all
   tag jobs, download/checksum both distributions and verify signed provenance
   against the exact tag commit and release workflow.
4. Promote stable and approve the verified protected PyPI deployment. Compare
   public wheel/sdist bytes and description with qualified GitHub artifacts.
   Run the three-platform PyPI lifecycle at the exact tag.
5. Perform independent post-distribution review of actual public metadata,
   release notes, immutable identity, application-source delta and completed
   workflow evidence. Reconcile final status in a reviewed PR, confirm no
   required issue remains open and explicitly close milestone 8.

A source candidate or preparation PR is not completion evidence for publication.
Record exact run IDs, commit and asset hashes after distribution. Stop at fresh
human Intent after the bounded v0.2 programme; future research stays research.


Initial CI exposed the retained v0.2.0 expectation in the artifact workflow;
its explicit version check is updated to v0.2.1. This is release-validation
bookkeeping, not an application behavior change. The hidden workflow files
were included in the follow-up version-reference sweep. The failing check was
preserved, not bypassed; corrected-head CI and review must pass before tagging.


## Completed outcome

PR #126 merged the reviewed preparation; v0.2.1 was tagged, qualified and
published with unchanged runtime behavior and corrected README metadata.
The public lifecycle passed on all three platforms after one inspected Ubuntu
retry for initial PyPI propagation. Independent post-distribution review found
no unresolved issue. The [final record](13-v021-distribution-review.md) contains
exact identities, hashes and workflow evidence. Estimate unchanged; actual
effort untracked. No further product work is selected.
