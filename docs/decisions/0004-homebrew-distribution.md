# 0004: Homebrew owns a native Python formula in a project tap

- Status: accepted for architecture; publication deferred
- Date: 2026-08-30
- Scope: optional Homebrew discovery after M3

## Decision

Reject a thin Homebrew wrapper around uv/PyPI. If post-M3 demand justifies the
channel, begin with a project-owned tap containing a normal Python formula. The
formula consumes the stable source distribution plus immutable, checksummed
Python resources, installs a formula-owned virtual environment, and lets
Homebrew own command linking, dependencies, upgrade, pin, and uninstall.

The initial formula does not require or authorize a standalone binary, cask,
bottle, bundled native tool, or uv-managed environment. Bottles may be added
later through an explicit publication design. `homebrew/core` submission is a
later promotion decision after tap demand, maintenance, macOS/Linux evidence,
and current core eligibility are demonstrated.

## Consequences

- PyPI remains the upstream source/provenance record, not an install-time
  dependency resolver.
- Every Python resource becomes Homebrew metadata maintained per release.
- The tap owner bears updates, audits, tests, security refreshes, and support.
- Poppler/Ghostscript dependency treatment must be settled after M3 without
  downloading or bundling them in the formula.
- Users get one coherent Homebrew lifecycle and no profile mutation by the app.

## Supersession conditions

Revisit if Homebrew's Python packaging rules materially change, the dependency
set cannot be represented reproducibly, core maintainers require a different
architecture, or measured demand justifies a separately approved binary/cask.

Research and alternatives are recorded in the [Homebrew research record](../plan/08-releases/03-homebrew-research.md).
