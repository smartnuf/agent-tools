# Capability foundation milestone

This milestone establishes the smallest packaged boundary needed for native
workstation capabilities. It is deliberately read-only: provider mutation,
persistent desired state, managed-state provenance, and agent-specific
configuration remain later lifecycle work.

## M1.5 — Packaged capability discovery

Outcome: an ordinary installed user can enumerate supported native
capabilities and reliably discover Bash and the existing document-tool
capabilities without a repository checkout.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Capability/provider boundary and safety semantics are decided | complete | [Decision 0002](../../decisions/0002-native-capability-provider-model.md) |
| Packaged catalogue and pure detection results cover Poppler and Ghostscript | not-started | Unit tests plus `doctor` using the shared catalogue |
| `tools list` and `tools status [CAPABILITY]` work from an installed wheel | not-started | Isolated wheel tests from an unrelated directory |
| Bash discovery distinguishes Git Bash, host system Bash, and WSL | not-started | Windows, Linux, and macOS tests with provider/path/version evidence |
| Product metadata, platform docs, and CI reflect the catalogue boundary | not-started | Distribution metadata test and cross-platform CI |

Estimate: **2–3 person-days**, excluding review and CI waiting time.

### Scope constraints

- No host package installation, updating, or removal in M1.5.
- No user configuration or managed-state file until a mutating consumer exists.
- No agent configuration changes.
- No generic third-party provider/plugin API.
- Optional Bash absence must not make the default `doctor` command fail.

### Planned reviewable slices

1. [Issue #23](https://github.com/smartnuf/agent-tools/issues/23): introduce
   the typed built-in catalogue/detection core and migrate existing
   Poppler/Ghostscript diagnostics (L, **1–1.5 days**).
2. [Issue #24](https://github.com/smartnuf/agent-tools/issues/24): add Bash
   provider discovery and packaged `tools list/status` commands (L,
   **0.75–1.25 days**).
3. [Issue #25](https://github.com/smartnuf/agent-tools/issues/25): reconcile
   product metadata, platform guidance, and built-artifact/CI tests (M,
   **0.25–0.5 day**).

After M1.5, resume M2 trusted publishing. Provider installation, desired state,
provenance, disable semantics, and integration removal tests belong in M3.
[Issue #26](https://github.com/smartnuf/agent-tools/issues/26) records the
provider-mutation boundary and must be split before implementation;
[issue #27](https://github.com/smartnuf/agent-tools/issues/27) keeps the Claude
Code integration assessment separate.
