# 0001: Distribution model

- Status: accepted
- Date: 2026-08-28
- Scope: public installation and updates

## Decision

Make the `agent-tools` command-line application the ordinary user's supported product. Publish one Python wheel and source distribution and use `uv tool` as the primary cross-platform installer and updater. Keep Poppler, Ghostscript, and other native programs under the operating system package manager.

Keep the clone-based repository installation and its shared `.venv`/`agent-python` interface as an advanced and development workflow while packaged releases mature. Do not promise that the private environment managed by `uv tool` is a general shared Python interpreter.

Use GitHub tags and Releases as the canonical release history and artifact record. After a GitHub prerelease has been installed and tested on supported platforms, publish the package to PyPI. Consider WinGet and Homebrew discovery channels only after the core release lifecycle is reliable.

## Reasons

- One package and CLI can behave consistently on Windows, Linux, and macOS.
- `uv tool` already provides isolated installation, upgrading, pinning, and removal.
- Platform package managers are better suited to native executables and architecture differences.
- Bespoke installers and self-updaters would add security and maintenance work before demand is established.

## Consequences

- Packaged commands must work without a repository checkout.
- Runtime dependencies must be represented by package metadata, while development and release testing may retain a reviewed exact lock.
- Installation, upgrade, pinning, rollback, and removal become tested product behaviours.
- Native installation remains explicit and reports every host change.
- The permanent Python distribution name must be selected and checked before publication; the command remains `agent-tools`.

## Deferred alternatives

- A managed, mutable shared-Python bundle for ordinary users.
- MSI, macOS package, deb/rpm, standalone-binary, or custom updater delivery.
- Automatically downloaded native binaries.

Revisit these only through a new decision record with evidence of need.
