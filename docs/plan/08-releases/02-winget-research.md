# M4a WinGet distribution research

- Research date and source retrieval date: 2026-08-30
- Governing decision: [Decision 0003](../../decisions/0003-winget-distribution.md)
- Status: research complete; implementation remains deferred until M3 is complete and demand justifies it
- Estimate: research/design 0.75–1 day; later implementation 4–7 person-days, excluding Microsoft moderation

## Conclusion

Do not submit a thin WinGet bootstrapper around `uv tool install`. The WinGet
community repository expressly disallows scripts as installers, expects a
publisher-hosted installer that installs and uninstalls unattended, and tests
the installed application. A bootstrap executable that delegates durable state
to uv would also leave WinGet's package record unable to describe, upgrade, or
remove the actual application reliably.

The smallest sound WinGet architecture is a project-published, versioned
Windows application artifact that WinGet can own end to end. A portable
executable or archive is preferable to MSI if it can provide the complete CLI
without runtime downloads; otherwise an unattended EXE or MSI is required.
Creating any of those artifact classes is not authorized by Decision 0001, so
M4a stops at design until a later artifact decision accepts one. The existing
wheel remains the supported Windows installation meanwhile.

## Documented policy findings

The following are documented requirements, not project inferences:

- Community packages accept MSIX/APPX, MSI, EXE-based installers, and eligible
  nested ZIP forms; batch and PowerShell scripts are expressly disallowed.
  Install must require no user interaction. [Community repository policies](https://github.com/microsoft/winget-pkgs/blob/master/doc/Policies.md)
- Community submissions use multi-file manifests; singleton manifests are
  prohibited. Version-specific official publisher URLs are preferred because
  mutable vanity URLs invalidate hashes. [Community repository policies](https://github.com/microsoft/winget-pkgs/blob/master/doc/Policies.md)
- `InstallerUrl` and SHA-256 are required per installer. The declared
  architecture describes installed binaries, and portable archives may expose
  command aliases and have WinGet manage their PATH integration. [Installer manifest schema](https://github.com/microsoft/winget-pkgs/blob/master/doc/manifest/schema/1.28.0/installer.md)
- Identifiers are unique; the manifest path, identifier, publisher,
  application, and version must agree. Publisher and package names should
  correlate with Add/Remove Programs so discovery and upgrades work.
  [Manifest authoring](https://learn.microsoft.com/en-us/windows/package-manager/package/manifest)
- A submission must install and uninstall correctly for administrators and
  non-administrators and support non-interactive operation. Automation checks
  schemas, URLs, hashes, malware, installation, the primary executable, and
  uninstall before moderator review. [Submission and validation](https://learn.microsoft.com/en-us/windows/package-manager/package/repository)
- `winget validate` and the community repository's Windows Sandbox test are
  official pre-submission tools. Microsoft may refuse a package and expects
  author feedback within the moderation workflow. [Submission and validation](https://learn.microsoft.com/en-us/windows/package-manager/package/repository)
- uv creates a separate environment and executable directory for each
  installed tool; uv, rather than an outer package manager, owns tool upgrade
  and uninstall. [uv tool environments](https://docs.astral.sh/uv/concepts/tools/)

No official source reviewed explicitly says “an EXE bootstrapper may not invoke
uv.” The rejection is an inference from the documented unattended install,
binary validation, direct-installer, application discovery, upgrade, and clean
uninstall requirements plus uv's separate ownership model. Confirmation from
WinGet maintainers would not repair the split ownership problem.

## Options considered

| Option | User lifecycle and state | Supply chain | Decision |
|---|---|---|---|
| Script or thin uv bootstrap | Two managers disagree; WinGet cannot reliably pin, repair, upgrade, or remove the uv tool; uv/Python/PyPI downloads occur after WinGet verifies only the wrapper | WinGet hash covers the wrapper, not resolved Python/runtime payloads | Reject |
| Package-manager-native EXE/MSI | WinGet owns registration, silent install, upgrade, and uninstall | One immutable, publisher-hosted artifact per version; hash and signature can cover delivered payload | Viable, but new artifact decision required |
| Standalone portable executable/ZIP | WinGet owns files, command alias/PATH, upgrade, and removal; no Python ownership exposed | Immutable archive/executable and hash cover the complete app | Preferred feasibility target; new artifact decision required |
| No WinGet package | Users continue the tested PyPI/uv lifecycle | Existing attestations and hashes remain authoritative | Default if demand or artifact economics fail |

An installer must not install uv, use uv-managed Python, resolve PyPI at runtime,
mutate a shell profile, bundle Poppler/Ghostscript/Git Bash, or claim ownership
of those shared native providers. Native capabilities remain separately managed
under Decision 0002 and missing providers remain actionable diagnostics.

## Proposed implementation and validation workflow

1. After M3, measure Windows demand and decide whether to authorize a portable
   standalone artifact or unattended installer. Stop M4a if neither is accepted.
2. Reserve a candidate identifier only after checking the live community
   repository; record publisher/name/ARP or portable correlation rules.
3. Produce an immutable x64 artifact and ARM64 artifact only where the contained
   executable is truly native. Generate multi-file manifests deterministically
   from the stable release metadata and downloaded artifact SHA-256 values.
4. Validate with pinned/current supported schema tooling, `winget validate`,
   URL and checksum verification, and scoped community-repository checks.
5. On disposable Windows hosts, test fresh/repeated silent install, command
   discovery, upgrade, exact older-version reinstall or documented rollback,
   interrupted/failed install recovery, non-admin behavior where supported,
   and complete uninstall without deleting user-owned configuration.
6. Automate release-version update proposals, but require review of artifact,
   URL, architecture, hash, and lifecycle evidence before any external PR.
7. Treat community submission and moderator response as a separate, explicitly
   authorized task. Acceptance—not a local manifest—is publication evidence.

Tracked order: [#59 artifact/identifier decision](https://github.com/smartnuf/agent-tools/issues/59)
→ [#60 manifest generation](https://github.com/smartnuf/agent-tools/issues/60)
→ [#61 manifest validation](https://github.com/smartnuf/agent-tools/issues/61)
→ [#62 disposable-host lifecycle](https://github.com/smartnuf/agent-tools/issues/62)
→ [#63 release updates](https://github.com/smartnuf/agent-tools/issues/63)
→ [#64 external submission](https://github.com/smartnuf/agent-tools/issues/64).
Issue #64 remains an external-publication boundary requiring explicit authority.

## Risks, unresolved questions, and rejection criteria

- Artifact selection, signing, Python embedding, CVE rebuilds, and x64/ARM64
  coverage require a later decision. An MSI is not presumed necessary.
- A portable executable may be impractical for current native Python
  dependencies or may trigger security scanning. Prototype evidence must decide.
- WinGet pinning is client state; rollback availability depends on retained
  manifests and immutable upstream artifacts. The lifecycle contract must not
  promise more than disposable-host tests demonstrate.
- PATH must be WinGet-managed for a portable package or installer-managed with
  explicit removal; no profile edits are allowed.
- Reject/continue deferral if demand does not justify 4–7 days plus release-by-
  release maintenance, Microsoft rejects the artifact behavior, all viable
  artifacts require bundled native providers, or supported architectures cannot
  be tested on disposable hosts.
