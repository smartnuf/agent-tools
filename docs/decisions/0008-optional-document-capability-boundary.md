# 0008: Optional document capability boundary

- Status: accepted
- Date: 2026-09-08
- Scope: core Python dependency surface and document-processing capabilities

## Decision

Document-processing libraries are not mandatory dependencies of the Agent Tools
core product. The ordinary core installation provides the `agent-tools` CLI,
capability discovery, provider management, configuration, diagnostics, and
other core workstation functions without installing the document-library stack.

Document-processing functionality must be installed through a separate,
explicitly requested packaging boundary. The implementation may use a Python
extra such as `smartnuf-agent-tools[documents]` or another equally clear
packaging surface selected during specification, but the product boundary is
settled: installing Agent Tools core must not pull document libraries merely to
make workstation capability management available.

The selected public extra/distribution name becomes a compatibility surface once
released and must therefore be specified, documented, and tested before v0.2 is
published.

## Required behaviour

- `agent-tools` core installs and operates without document libraries.
- Core `doctor` health is distinct from optional document capability
  availability; an omitted optional document install is not a broken core.
- Document-specific commands or helpers report the absent optional dependency
  cleanly and actionably rather than failing during unrelated CLI startup.
- Installing, upgrading, or removing the document option must not silently
  mutate native provider state.
- Upgrade from v0.1.x, where document libraries are mandatory dependencies, has
  a documented compatibility and migration path.
- Wheel/sdist metadata, installed-artifact tests, README/PyPI documentation, and
  release lifecycle evidence cover both core-only and document-enabled installs.

## Reasons

- Agent Tools is becoming a general workstation capability manager; mandatory
  PDF/document libraries make the core installation larger and more fragile
  without being necessary for that purpose.
- Optionality makes dependency failures local to the feature that needs them.
- A lighter core reduces installation friction, especially on architectures
  where transitive binary wheels may lag.
- Keeping the boundary explicit lets future document functionality grow without
  forcing every Agent Tools user to carry it.

## Consequences

- Current import and `doctor` assumptions must be refactored before release.
- Packaging and upgrade tests must exercise both installation shapes.
- Documentation must distinguish Python document libraries from native
  capabilities such as Poppler and Ghostscript; neither category may be
  silently conflated with the other.
- This decision does not determine which document tools are ultimately worth
  supporting. Broader tool-selection, rights, quality, and agent-preference
  research belongs to a later exploratory phase.
