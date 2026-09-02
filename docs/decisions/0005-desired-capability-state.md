# ADR 0005: Desired capability configuration

- Status: Accepted
- Date: 2026-09-02
- Related: ADR 0002, ADR 0003, issues #26 and #54

## Context

ADR 0002 separates desired configuration from the built-in catalogue,
ephemeral detected state, and managed mutation provenance. Issue #54 introduces
the first desired-state consumer: clone native setup may include explicitly
enabled optional capabilities and honor an exact provider preference. The
configuration is persistent user input, so its pathname, accepted language,
backup, replacement, validation, and failure behavior are compatibility and
preservation boundaries even though the initial catalogue has only one
optional capability.

Desired state does not establish availability, mutation history, ownership, or
removal authority. Those facts remain with detection, execution reports, and
managed provenance.

## Decision

Each execution environment uses one private per-user JSON document:

- Windows host: `%LOCALAPPDATA%\agent-tools\config.json`;
- Linux, including WSL: `$XDG_CONFIG_HOME/agent-tools/config.json`, falling
  back to `~/.config/agent-tools/config.json`; and
- macOS: `~/Library/Application Support/agent-tools/config.json`.

Windows-host and WSL configuration is naturally separate. Tests may inject a
path, but there is no public path override.

Schema v1 is:

```json
{
  "schema_version": 1,
  "capabilities": {
    "bash": {
      "provider": "git-bash"
    }
  }
}
```

Membership in `capabilities` means that optional capability is enabled. The
`provider` member is optional; when absent, ADR 0002's default provider order
applies. When present, it names one exact built-in satisfying provider and
narrows selection rather than acting as a fallback hint. Disable removes the
capability entry. It never removes a provider package.

The v1 document and capability-entry objects have no other members. Capability
identifiers that this binary does not know are accepted when they have the v1
shape and are preserved byte-for-logical-value through changes to known
entries. A consumer that cannot honor an enabled unknown capability fails
closed rather than silently ignoring it. This permits catalogue growth without
letting an older consumer misrepresent the requested outcome. Adding another
field or changing these semantics requires a new schema-version decision.

Only optional built-in capabilities can be enabled or disabled. A provider
preference must belong to that capability, satisfy it, and support the current
platform/execution environment. An unavailable preferred provider remains an
exact preference: planning may provision it when separately authorized, or
fails visibly; it never silently selects another provider.

### Mutation authority and transaction

A changed document requires the dedicated `--allow-config-mutation` flag.
Interactive confirmation alone is insufficient. An already-satisfied request
is a no-op and creates no backup.

Before replacing an existing document, Agent Tools writes a collision-safe,
byte-for-byte recoverable sibling backup and makes it durable. It never
overwrites a prior backup. It then writes the complete updated document to an
exclusive temporary regular file in the destination directory, flushes it,
validates it through the production reader, and atomically replaces the
destination. The directory is synchronized where the platform supports that
operation. A successful mutation is read and validated again before success is
reported.

Failure before replacement leaves the prior document in place. Failure after
replacement triggers restoration from the backup; failure after first-file
creation restores confirmed absence by removing only the newly created regular
entry. Restoration itself uses validated atomic replacement. If restoration
cannot be confirmed, the error reports the uncertainty and the backup path
when one exists; it never claims the previous state was restored.

Consistent with ADR 0004, a supported first SIGINT is translated at the
mutation edge into cooperative cancellation and observed at transaction
checkpoints. Cancellation observed after replacement restores the prior state
before propagating the interruption. A second SIGINT is a deliberate
force-abort and may trade restoration guarantees for immediate termination.
This avoids asynchronously injecting first-interrupt control flow between the
replacement effect and the transaction's knowledge that it occurred.

The configuration pathname is an integrity boundary. It may be absent or name
an ordinary regular file only. Symlinks, directories, and other non-regular
entries fail closed without being followed, replaced, repaired, or deleted.
Malformed, over-large, excessively deep, duplicate-key, or unknown-version
documents are preserved and block mutation. Backups and temporary entries are
also created without following existing entries.

Mutation is serialized within one Agent Tools process. Version 1 does not
claim cross-process exclusion. Concurrent independent writers are unsupported;
the mutation rechecks the source snapshot before replacement and refuses a
known conflict, but does not claim a portable lock against a change in the
remaining comparison/replacement interval. A stronger multi-process contract
requires a separate decision.

### Consumers and reporting

Clone native setup loads desired state, adds enabled optional capabilities to
its explicit required-capability request, and passes exact provider
preferences into the immutable provider plan. Provider mutation still requires
its separate authorization. `tools status` reports desired state separately
from detected availability and managed provenance.

`tools enable CAPABILITY [--provider PROVIDER]` and
`tools disable CAPABILITY` are the public lifecycle commands. They report the
configuration outcome and backup path. They do not install, remove, or inspect
ownership of provider packages.

## Consequences

- Desired intent, detected reality, mutation provenance, persistence, and
  ownership remain separate facts.
- Provider preferences are exact and visible; absence or incompatibility does
  not silently fall back.
- Existing configuration receives a durable recovery point before change, and
  post-replacement failures attempt explicit restoration.
- Unknown v1 capability entries remain preservable without being silently
  treated as implemented behavior.
- Callers must serialize independent configuration writers themselves.

## Alternatives considered

- Reusing managed-state provenance was rejected because append-only mutation
  evidence is not editable user intent and conveys no selection authority.
- Storing only an enabled-capability list was rejected because it could not
  represent ADR 0002's exact provider preference.
- Treating a preference as a best-effort hint was rejected because silent
  fallback contradicts the accepted selection contract.
- Removing providers during disable was rejected by ADR 0002; configuration
  removal changes intent only.
- A cross-platform lock-file protocol was deferred because issue #54 has a
  single-actor contract and portable stale-owner recovery would create a new
  coordination surface.

## Non-goals

This decision adds no provider uninstall, rollback, ownership, public path
override, generic provider plugin format, integration configuration, retention
policy, cross-process lock, or automatic provider mutation when configuration
changes.
