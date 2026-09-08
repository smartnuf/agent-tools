# v0.2 productisation slice

This document records the bounded work to turn the completed M3 machinery into
a minimally useful installed product. It does not authorize implementation by
itself. Before execution, the repository planning protocol still requires an
open GitHub milestone, assigned reviewable issues, reconciled current state, a
task plan, and any necessary behavioural specification.

## Intent

Ship a v0.2 release in which an ordinary user can install Agent Tools from PyPI
with `uv tool`, use `agent-tools` as the product interface, explicitly install
supported native capabilities through that CLI, and choose whether to install
document-processing functionality.

The purpose of this slice is not to maximize the eventual Agent Tools feature
set. It is to expose the useful M3 machinery through a coherent installed
product with defensible release and platform evidence, then stop and revisit
Intent before choosing the next product direction.

## Accepted product decisions

- [Decision 0007](../../decisions/0007-v0.2-product-and-distribution-boundary.md):
  one supported CLI, PyPI/`uv tool` as the sole Agent Tools distribution channel,
  repository scripts outside the ordinary-user product surface, and
  `agent-tools install <list>` in the next minimally useful release.
- [Decision 0008](../../decisions/0008-optional-document-capability-boundary.md):
  document libraries are separately requested rather than mandatory core
  dependencies.
- Alternative Agent Tools distribution channels are retired from the active
  roadmap indefinitely. A future channel requires new evidence and a new
  decision record.

## Characterisation

This slice changes a public CLI, Python dependency metadata, installed artifact
contents, upgrade compatibility, host-mutation entry points, and support/test
claims. It therefore crosses several persistent/public and cross-platform
boundaries even though the underlying M3 mutation engine already exists.

Important dimensions:

- public compatibility: high;
- host mutation: high but existing M3 semantics are reused;
- persistence/provenance: existing M3 contracts must remain intact;
- packaging/dependency boundary: materially changing;
- cross-platform variance: high;
- release evidence: must distinguish simulated, seeded, and real-provider tests;
- reversibility/preservation: existing M3 obligations remain mandatory.

Implementation should therefore remain in small reviewable slices and return to
Specify/Map rather than accumulating local patches if review reveals a new
contract family.

## Required discovery before implementation

Reconcile the current repository and published artifacts, including:

1. every user-visible `agent-tools`, `bin/`, and `scripts/` entry point and who
   currently depends on it;
2. wheel and source-distribution contents, including whether any scripts are
   accidentally or necessarily shipped;
3. the current document-library import/doctor coupling and v0.1.x upgrade
   implications;
4. all CI installation paths, distinguishing candidate-wheel installation,
   published-PyPI installation, external native pre-seeding, simulated/disposable
   provider execution, and real provider mutation;
5. current OS/distribution/version/architecture evidence and known gaps; and
6. the still-open README/PyPI front-door work in PR #102, which must be
   reconciled with these newer product decisions rather than merged from stale
   assumptions.

## Proposed acceptance gates

These are proposed v0.2 gates to turn into the next GitHub milestone before
implementation begins.

| Gate | Initial state | Primary tracker |
|---|---|---|
| Installed `agent-tools` is the sole supported ordinary-user command surface; repository operational scripts are not required by released workflows | not-started | #103 |
| `agent-tools install <capability> [<capability> ...]` reuses the existing managed provider lifecycle and works from an installed artifact | not-started | #103 |
| Core installation no longer requires document libraries; a separately requested document install has a specified compatibility contract | not-started | #57 |
| CI evidence distinguishes seeded/simulated/native mutation paths and exercises primary real provider mutations through the installed CLI where practical | not-started | #104 |
| Maintained platform evidence reports OS/distribution version, architecture, provider path, evidence class, and important common gaps without overclaiming | not-started | #104 |
| README/PyPI front door describes the new core/doc/CLI contract and is reconciled with PR #102 or its successor | not-started | #102 / successor |
| A reviewed v0.2 candidate passes exact-artifact install, upgrade-from-v0.1.x, pin/reinstall, rollback where supported, and removal/preservation tests before publication | not-started | split during planning |

## Likely sequencing

1. **Discover/specify CLI and release surface** — inventory scripts/bin/package
   contents and specify `agent-tools install <list>` without changing M3 safety
   semantics.
2. **Implement CLI-only product surface** — #103, split if it exceeds the
   two-person-day reviewable-task limit.
3. **Specify and implement the document extra** — #57, including upgrade and
   diagnostic semantics.
4. **Close CI parity and support-evidence gaps** — #104; retain external
   pre-seeding as a clearly named fixture path where useful, but add real
   installed-CLI mutation evidence for primary provider paths where practical.
5. **Reconcile user-facing documentation** — incorporate or supersede PR #102
   against the final v0.2 contract.
6. **Qualify and publish v0.2** — exact artifact, exact head, explicit release
   gate.

Parallel development is allowed only where file/product-contract ownership is
clear; integration remains serialized through one merge owner.

## Explicit non-goals for v0.2

Do not expand this slice into:

- WinGet, Homebrew, MSI, deb/rpm, standalone-binary, or other Agent Tools
  distribution channels;
- provider uninstall/removal merely because a capability is disabled;
- a generic third-party provider/plugin architecture;
- named tool sets, manifests/files, catalogue search, TUI, MCP, or automated
  agent-specific tool selection;
- broad expansion to many new native tools before the installed CLI and evidence
  model are sound.

Those ideas are retained in
[`../90-future-product-research.md`](../90-future-product-research.md) for a
later research/exploration phase.

## Completion and stop condition

When the proposed gates have durable evidence and v0.2 is published, stop the
bounded productisation programme. Reconcile the roadmap and deliberately choose
a new Intent rather than automatically promoting future research ideas into
implementation work.
