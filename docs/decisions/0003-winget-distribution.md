# 0003: WinGet requires a WinGet-owned application artifact

- Status: accepted for architecture; artifact implementation deferred
- Date: 2026-08-30
- Scope: optional WinGet discovery after M3

## Decision

Reject a thin WinGet bootstrapper around uv/PyPI. A WinGet package must own the
installed application, command exposure, version correlation, upgrade, and
uninstall. Prefer a complete portable executable/archive if feasibility tests
support it; otherwise an unattended EXE or MSI would require a further decision.

Decision 0001 does not authorize a Windows installer or standalone binary.
Therefore M4a may research, prototype locally, and define validation, but it
must not implement or publish a new artifact until a later decision accepts the
artifact class, architecture coverage, signing/provenance, and maintenance cost.
Do not install or claim ownership of uv, a shared Python installation, Poppler,
Ghostscript, or Bash. A later-approved standalone artifact may embed an
application-private Python runtime when the artifact owns and removes it fully.

## Consequences

- The existing PyPI/uv distribution remains the supported Windows route.
- WinGet manifests cannot point at the wheel, sdist, a script, or a delegating
  wrapper whose payload is resolved at install time.
- WinGet and the actual installed application will have one lifecycle owner.
- PATH changes must be WinGet/installer-owned and removed with the package;
  shell-profile mutation is excluded.
- M4a is rejected if no complete artifact is authorized or economically sound.

## Supersession conditions

Revisit only if official WinGet policy explicitly supports a delegation model
with coherent install/upgrade/uninstall state, or a later decision authorizes a
complete Windows artifact with durable lifecycle and supply-chain evidence.

Research and alternatives are recorded in the [WinGet research record](../plan/08-releases/02-winget-research.md).
