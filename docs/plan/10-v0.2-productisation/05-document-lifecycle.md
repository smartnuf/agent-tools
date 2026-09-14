# #111: Document lifecycle evidence

Base: `6d8e1e267b6a586773b73509fdbefeb91acbb537`; milestone 8 open.
Authority: Decision 0010, #111/#109/#57; this stream owns integration.
Estimate remains 1–1.5 person-days, excluding CI/review; actual effort untracked.

## Discovery and specification

The accepted next release is v0.2. Set the unpublished candidate identity to
0.2.0 so its metadata cannot be confused with published v0.1.2. This assigns
build identity only: no tag, GitHub release or PyPI publication is performed.
Keep v0.1.2 documented as the current public release until publication evidence.
Update the historical lifecycle driver to distinguish candidate/current versions.

Test real checksum-verified v0.1.1 GitHub-wheel and v0.1.2 PyPI artifacts against
the exact candidate. Controlled local indexes expose the actual artifacts;
record this as local-index migration evidence, not live PyPI publication.
Cover core/documents targets, direct-source replacement, unpinned upgrade,
exact pin/reinstall, documents removal, failed resolution, rollback and uninstall.
Verify versions and inventories, not just command success. Snapshot desired and
managed-state files and external Bash; on native Windows apply/remove the
existing integration explicitly in private settings and snapshot its ledger,
settings and backups. No provider installation is part of this test.

Use private uv tool/bin/config/state roots. macOS fixed application-data paths
require the existing explicit disposable-host authority and refusal of existing
state, with cleanup only of unchanged test-owned data. Preserve pre-existing
user state on failure. Package operations never imply integration restoration;
perform any intended restoration explicitly while the current CLI is installed.

No second real documents-enabled release exists. A separately labelled source
fixture with an earlier development version supplies reproducible extra-retention
across a genuine version change into the actual candidate. This fixture is not
a historical release. Keep later exact-release/publication qualification open.

## Plan and validation

1. Commit this plan; assign the distinct candidate version and repair version
   assertions without rewriting historical release evidence.
2. Add bounded artifact lifecycle checks with state/inventory preservation and
   separately labelled extra-retention fixture evidence. Use existing uv and
   packaged path/state contracts; do not add application persistence or providers.
3. Integrate the checks in three-platform CI and release/PyPI smoke paths while
   retaining historical-release validation. Update guides/evidence and milestone
   counts only when exact-head validation supports them.
4. Run unit/fault tests, syntax/PATH and doctor checks, rebuilt artifact metadata,
   independent shapes, lifecycle tests, diff check and exact-head CI/review.
   Up to six correction waves; focused commits, one push per complete wave.
5. Merge only after current-base/exact-head checks and review converge. Close
   #111/#109/#57 only when their shared implementation/evidence target is met;
   retain provider/platform and final publication gates. Continue with #104
   discovery if circumstances and the authorized boundary allow.
