# 0010: Document extra and diagnostics

- Status: accepted for implementation; not yet released
- Date: 2026-09-14
- Scope: #57 packaging, diagnostics and v0.1.x migration
- Authority: human-approved Decision 0008 and #57's delegated packaging/migration specification

## Packaging contract

Use the public extra `smartnuf-agent-tools[documents]`. Core has no third-party
runtime dependencies. Move all seven existing document requirements, with their
current constraints unchanged, into that extra. Do not expand Python support,
replace libraries, or change licensing policy in this task. Extras are additive
dependency metadata, not another distribution, executable or native capability.

Keep `agent-tools` as the sole ordinary-user CLI. `agent-tools install documents`
is not a supported native-catalogue request. Use `uv tool` to manage the
application's Python environment; do not add self-modification of that
environment or another provider/provenance abstraction.

For a released version that supplies the extra, the supported requests are:

```sh
uv tool install --python 3.13 smartnuf-agent-tools
uv tool install --python 3.13 --reinstall 'smartnuf-agent-tools[documents]'
uv tool upgrade smartnuf-agent-tools
uv tool install --python 3.13 --reinstall smartnuf-agent-tools
uv tool uninstall smartnuf-agent-tools
```

The second command explicitly selects documents (also valid for first install);
the fourth explicitly returns to core-only. For exact reinstall, upgrade target
or rollback, append `==VERSION` to the selected package requirement, after the
closing bracket when selecting documents. Preserve the existing documented
interpreter choice when it differs from the recommended 3.13.

These operations affect uv's isolated application environment and launcher.
They do not authorize native install/removal, desired/managed-state changes,
integration changes or shell-profile edits. No manual pip editing of uv's tool
environment is supported. A failed transition must be reported honestly; never
claim success or automatically remove a working installation to repair failure.

## Diagnostic contract

Plain `agent-tools doctor` reports optional document-library availability in a
separate, clearly labelled section. Missing, partial or broken optional libraries
do not contribute to its exit status. Report each unavailable/import-failing
library and the explicit documents install/check instructions; do not silently
hide import errors or describe an unhealthy optional stack as healthy.

`agent-tools doctor --documents` explicitly requires the full seven-library
stack: each library must have distribution metadata and import successfully.
Absent metadata, missing modules and import failures contribute to status 1 in
this mode. It is read-only and never installs packages. Both modes retain the
existing native catalogue checks and their status contribution: Poppler and
Ghostscript remain required by the current catalogue. Thus a healthy Python
core can still have status 1 from a separately identified native check.

Status 0 means all checks required by the selected diagnostic mode passed;
status 1 means at least one required check failed; parser errors remain 2.
Help defines these facts once and generates the CLI reference under #106.
No persisted "extra requested" flag is inferred from installed packages or
written into desired/managed state: package metadata cannot establish the
user's original install intent. Explicit diagnostic selection avoids that
ambiguity, including partially installed environments.

There are currently no packaged document-processing commands or helpers beyond
these probes. Do not invent any here. Libraries installed in an isolated uv
tool environment do not become imports in arbitrary project interpreters;
project environments remain authoritative for project document processing.
Future document commands must guard optional imports at their feature boundary
and give actionable absence errors, never break unrelated CLI startup.

## Migration and checkout compatibility

v0.1.x declares document libraries unconditionally. A normal upgrade that did
not previously request an extra selects the new core contract; users requiring
the old library bundle must explicitly select `[documents]` at migration.
Subsequent uv tool upgrades retain the selected extra. Exact reinstalls must
spell the intended shape explicitly. Rollback to v0.1.x uses the bare pinned
distribution because those releases predate the extra and include documents
unconditionally. Test actual package contents, not just installer exit codes.

Repository bootstrap/update remain development/compatibility infrastructure.
Their explicit `requirements.txt` lock continues to request the document stack;
do not silently strip that existing checkout environment or regenerate its
reviewed lock as part of this packaging change. Document that this differs from
core-only installed usage. No checkout is required for the released interface.

## Evidence and release boundary

Before shipping, verify wheel and rebuilt-sdist metadata: zero unconditional
runtime dependencies, exactly the `documents` extra, and all seven unchanged
requirements guarded by that extra. Exercise independent core-only and
document-enabled artifacts outside a checkout on Windows, Ubuntu and macOS.
Core CLI startup, help, named-native dry-run/no-op and configuration help must
work with all document libraries absent. Cover absent, partial, broken and
healthy document probes, including explicit-mode status and unchanged native
status semantics.

Extend candidate and release lifecycle evidence for actual v0.1.x-to-candidate
core/documents migration, extra-preserving upgrade, exact reinstall,
documents-to-core removal, rollback and application removal. Verify desired,
managed and integration state and an external provider remain unchanged;
include failed resolution preserving the prior valid installation. Clearly
distinguish discovery prototypes, candidate artifacts and published artifacts.
No publication is authorized or claimed by this specification PR.

## Basis

[Python packaging metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
defines extras as optional dependency groups.
[uv's tool contract](https://docs.astral.sh/uv/concepts/tools/) uses isolated
environments and retains install settings across upgrades; changing the
requested installation uses `uv tool install`.
The [task discovery](../plan/10-v0.2-productisation/03-document-boundary.md)
records the local migration experiment and its limits.
