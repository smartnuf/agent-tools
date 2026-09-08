# Future Agent Tools product research

This is a **research and rediscovery note, not an active roadmap or commitment**.
It preserves promising questions that should be reconsidered after the bounded
v0.2 productisation slice is complete. Future work must begin again at Intent
and use the repository's proportional
Intent → Characterise → Discover → Map → Plan → Specify → Execute → Review → Learn
cycle before any item here becomes scheduled implementation.

The purpose of keeping this in git is to make it easy for humans and agents to
rediscover the design space, assumptions, and unanswered questions from a fresh
checkout without treating an old chat, GitHub Discussion, or closed issue as
canonical product policy.

## Why research after v0.2

The immediate goal is deliberately small: one installed CLI, explicit
`agent-tools install <list>`, optional document dependencies, real-provider CI
evidence, and honest platform coverage. Once that is useful and released, there
is a much larger possible product space. We should explore it before selecting
the next Intent rather than allowing individual feature ideas to accrete into
the product accidentally.

A useful research phase should combine primary-source rights/licensing work,
real tool experiments, agent-workflow observation, and prototype interfaces.
The output should be evidence and candidate product models, not a presumption
that all feasible features should ship.

## Native and optional tool catalogue research

Investigate a broader range of tools that agents commonly benefit from, for
example document/PDF utilities, media tools, archive/compression tools, image
and diagram processors, source-code/search utilities, browser/automation
prerequisites, and other workstation capabilities.

For every candidate tool or provider, research at least:

- what user/agent job it enables and whether agents actually prefer it;
- authoritative upstream project and package-manager identities;
- licence, redistribution, trademark, and automation rights;
- whether Agent Tools may merely invoke the native package manager or must avoid
  recommending/automating some installation path;
- supported OS/distribution/architecture combinations;
- package availability, version lag, signatures/checksums, and provenance;
- privilege/interactivity/reboot requirements;
- executable discovery and reliable version/architecture verification;
- install idempotence, exit-code quality, partial failure, retry safety, and
  uninstallation/ownership semantics;
- CI/disposable-host testability; and
- maintenance burden and security implications.

Do not equate “available in a package manager” with “appropriate for Agent Tools
to install”. Rights, provider quality, automation semantics, and evidence matter.

## Candidate installation interfaces

The v0.2 primitive is intentionally small:

```text
agent-tools install <capability> [<capability> ...]
```

Research whether evidence justifies higher-level interfaces such as:

```text
agent-tools install <named-set>
agent-tools install --from-file <path>
agent-tools search <term>
```

Questions to resolve before designing these include:

### Named sets

Could Agent Tools supply coherent capability profiles such as document work,
web automation, software development, data analysis, or media processing?
Determine whether a set is a versioned product contract, a mutable recommendation,
or merely a convenient expansion into explicit capabilities. Specify how a set
changes over time without surprising repeat installs or making old manifests
non-reproducible.

### File-driven installation

Could a file express desired capabilities/provider preferences for a user,
project, agent, or machine? Research schema/versioning, portability, host versus
execution-environment identity, relative versus exact provider choices,
plan-only validation, partial failure, idempotence, provenance, and whether the
file expresses desired state or an imperative one-shot request.

Do not invent a second desired-state format without reconciling it with the
existing versioned desired-capability state.

### Search and catalogue discovery

Could `agent-tools search <term>` help users or agents discover supported
capabilities? Decide what is being searched: a small curated built-in catalogue,
remote metadata, package-manager catalogues, community contributions, or a
combination. Remote or community search introduces freshness, trust, ranking,
licensing, moderation, and network-availability questions that the current
built-in catalogue avoids.

Search results must not imply that arbitrary package-manager entries are vetted
or safely installable by Agent Tools.

## Agent preference and task-to-tool research

A potentially high-value direction is to study which tools coding/research
agents actually prefer for particular classes of work rather than choosing a
catalogue solely from human intuition.

Possible questions:

- Which PDF extraction/rendering tools do different agents choose when several
  are available, and why?
- Which search, archive, image, media, browser, diagram, build, or inspection
  tools materially improve success rate, quality, latency, or token use?
- Do Codex, Claude Code, other CLI agents, and MCP-capable clients make different
  choices for the same job?
- Are there small “baseline workstation” capability sets with unusually high
  value across agents?
- When do agents prefer native CLIs, Python libraries, MCP servers, or direct
  application APIs?
- Can recommendations be derived from reproducible task suites rather than
  anecdote?

Consider a research harness that presents controlled tasks under alternative
tool environments and records chosen tools, success/failure, time/cost,
artifacts, recovery behaviour, and review quality. Treat model/version and agent
harness as experimental variables because preferences may change.

The output might become curated recommendations, named sets, documentation, or
nothing at all; research does not pre-authorize automatic installation.

## Possible interaction surfaces

Explore only after the command model is coherent.

### TUI

A terminal UI could make capability browsing, plans, provider choice, platform
coverage, provenance, and recovery guidance easier to inspect. Research whether
it adds enough value over a composable CLI to justify another interaction layer.
The TUI should call the same core application contracts rather than owning
separate behaviour.

### MCP server

An MCP surface could let agents inspect capabilities, request plans, search a
curated catalogue, or initiate explicitly authorized operations through a
structured interface. Research authority, user confirmation, host identity,
long-running mutation, cancellation, provenance, and client trust boundaries
before treating MCP as a safe mutation channel.

The MCP server, if ever built, should expose the same domain model as the CLI;
it should not become a second implementation of provider semantics.

### Other agent integrations

Research whether integrations should remain narrow configuration adapters, as
with the current Claude Code Git Bash integration, or whether some agents
benefit from discoverable capability manifests, generated instructions, MCP,
or other mechanisms. Avoid per-agent special cases without demonstrated value.

## Product and architecture questions worth revisiting

- Should Agent Tools remain a curated closed catalogue, gain a plugin/provider
  extension mechanism, or support both with different trust levels?
- Is capability identity global enough for manifests and sets, or must variants
  include execution environment, architecture, and semantic version ranges?
- How should Agent Tools distinguish “installed”, “usable for this task”,
  “desired”, “recommended”, and “managed request recorded”?
- What promises, if any, should be made about update/repair/removal of native
  providers that Agent Tools did not install or does not own?
- Can some provider operations be safely concurrent, or should host package
  mutation remain serialized?
- What offline behaviour is required?
- How should rights/security review be recorded for catalogue additions?
- What evidence is sufficient to say a platform/provider combination is
  supported versus merely expected to work?
- At what point does a curated capability catalogue become a product requiring
  its own release/version policy independent of the Python package version?

## Where durable information belongs

Use repository artifacts for canonical knowledge:

- accepted product/architecture choices → `docs/decisions/` ADRs;
- current roadmap/status/gates → `docs/plan/`;
- stable platform/support claims → maintained platform documentation;
- reusable research conclusions that constrain future design → a repository
  research/architecture note or ADR as appropriate;
- bounded executable work → GitHub issues associated with the active milestone.

GitHub Discussions can be useful for open-ended community questions, proposals,
experience reports, and feedback if Discussions are enabled later. They should
not be the sole canonical record of a decision or roadmap fact that a fresh
agent must obey. When a Discussion produces a durable conclusion, harvest it
into the repository and link back to the discussion for provenance.

## Activation rule

After v0.2 is published, deliberately revisit the roadmap. Start a new Intent
phase and choose which research questions materially serve the product. Do not
promote this file wholesale into a milestone. Select and bound research slices,
record evidence, then Map/Plan/Specify only the directions justified by what was
learned.
