# Capability foundation milestone

This milestone establishes the smallest packaged boundary needed for native
workstation capabilities. It is deliberately read-only build-readiness work:
provider mutation, persistent desired state, managed-state provenance,
agent-specific configuration, and publication of these new commands remain
later work.

## M1.5 — Packaged capability discovery

Outcome: reviewed source produces a wheel that can be installed outside a
repository checkout to enumerate supported native capabilities and reliably
discover Bash and the existing document-tool capabilities. Public availability
of these commands begins with M2.

| Acceptance criterion | State | Required evidence |
|---|---|---|
| Capability/provider boundary and safety semantics are decided | complete | [Decision 0002](../../decisions/0002-native-capability-provider-model.md) |
| Packaged catalogue and pure detection results cover Poppler and Ghostscript | complete | [Packaged catalogue](../../../src/agent_tools/capabilities.py), [fixture-driven tests](../../../tests/test_capabilities.py), and `doctor` using the shared detection results |
| `tools list` and `tools status [CAPABILITY]` work from an installed wheel | complete | [Packaged CLI](../../../src/agent_tools/cli.py) and [isolated installed-wheel checks](../../../tests/check_installed_cli.py) |
| Bash discovery distinguishes Git Bash, host system Bash, and WSL | complete | [Provider catalogue and locators](../../../src/agent_tools/capabilities.py) plus [platform/provider fixtures](../../../tests/test_capabilities.py) with path, version, architecture, and environment evidence |
| Product metadata, platform docs, and CI reflect the catalogue boundary | complete | [Distribution metadata checks](../../../tests/check_distribution.py), [platform guidance](../../platforms.md), and one transferred wheel exercised by [installed-CLI checks](../../../tests/check_installed_cli.py) on Windows, Ubuntu, and macOS CI |

Estimate: **2–3.25 person-days**, excluding review and CI waiting time. Complete
on 2026-08-29; actual engineering effort was not recorded.

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
   product metadata, platform guidance, and built-artifact/CI tests (S,
   **0.25–0.5 day**).

After M1.5, resume M2 trusted publishing. Provider installation, desired state,
provenance, disable semantics, and integration removal tests belong in M3.
[Issue #26](https://github.com/smartnuf/agent-tools/issues/26) records the
provider-mutation boundary and must be split before implementation;
[issue #27](https://github.com/smartnuf/agent-tools/issues/27) keeps the Claude
Code integration assessment separate.
