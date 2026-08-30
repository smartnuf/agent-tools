# M4b Homebrew distribution research

- Research date and source retrieval date: 2026-08-30
- Governing decision: [Decision 0004](../../decisions/0004-homebrew-distribution.md)
- Status: research complete; implementation remains deferred until M3 is complete and demand justifies it
- Estimate: research/design 0.75–1 day; later tap implementation 3–5 person-days, excluding external review; homebrew-core submission adds 1–2 days plus review

## Conclusion

Do not wrap `uv tool install` in a formula. Homebrew's reproducibility policy
requires immutable, checksummed sources and Python resources installed without
dependency resolution during `install`; a uv/PyPI delegation would create a
second package database and make `brew upgrade`, `brew pin`, and `brew uninstall`
misrepresent the installed application.

Start, if demand justifies M4b after M3, with a project-owned tap containing a
normal Python formula. The formula should consume the stable source distribution
and checksummed Python dependency resources, use Homebrew's Python virtualenv
helper, install the CLI under Homebrew's prefix, and declare only required
Homebrew dependencies. This does not require a new upstream binary artifact or
bottles initially. Consider `homebrew/core` only after the tap proves maintenance,
usage, macOS and Linux support, and every current core acceptance rule.

## Documented policy findings

- Core formulae must build and test on the current supported macOS and Linux CI
  matrix unless a useful upstream platform restriction is justified. Sources
  must be stable, immutable, versioned, checksummed, and reproducible.
  [Acceptable Formulae](https://docs.brew.sh/Acceptable-Formulae)
- Python formulae declare checksummed `resource` blocks and install with
  dependency resolution disabled; an install may not resolve a moving dependency
  set. Self-update behavior conflicts with Homebrew ownership.
  [Acceptable Formulae](https://docs.brew.sh/Acceptable-Formulae)
- Formula dependencies must be declared; `homebrew/core` disallows optional and
  recommended dependency options. Formulae can vary dependencies by macOS/Linux
  and ARM/Intel. [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook)
- Formulae require a meaningful `test do` block. New submissions run
  `brew audit --new --formula`; authors should also run strict online audit,
  style, source-build install, and test checks. [Formula Cookbook](https://docs.brew.sh/Formula-Cookbook)
- Homebrew's Python virtualenv helper creates a formula-owned environment in
  `libexec`, installs declared resources, then installs the formula.
  [Python virtualenv API](https://docs.brew.sh/rubydoc/Language/Python/Virtualenv.html)
- Anyone may create a tap. Users can install a single formula directly, taps
  update through `brew update`, and formulae upgrade normally. The project owns
  tap upkeep and may build bottles with generated GitHub Actions workflows.
  Eligible software is preferred in core for discoverability.
  [Creating and maintaining a tap](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap)
- uv owns its persistent tool environment, executable directory, upgrades, and
  uninstall. [uv tool environments](https://docs.astral.sh/uv/concepts/tools/)

The official policy does not name uv specifically. Rejecting uv delegation is
an inference from the reproducible-resource rule, network restrictions during
formula installation, and conflicting lifecycle ownership. A formula may use
the existing PyPI sdist as an immutable upstream source; it must not ask PyPI or
uv to resolve dependencies at install time.

## Options considered

| Option | User lifecycle and state | Supply chain | Decision |
|---|---|---|---|
| Thin uv formula | Brew records a wrapper while uv owns Python, app, PATH, upgrade, and removal | Formula hash does not cover later PyPI resolution | Reject |
| Native Python formula in project tap | Brew owns virtualenv, links, dependencies, upgrade, pin, and uninstall | Sdist and every resource have reviewed immutable URLs and SHA-256 | Recommend first |
| Native Python formula in homebrew/core | Same sound lifecycle, with core CI/bottles and discoverability | Core review and ongoing policy/usage burden | Reconsider after tap evidence |
| Standalone binary/cask | Could simplify dependency resources but introduces a new artifact and platform builds | New binary/bottle provenance boundary | Defer; unnecessary for initial formula |
| No Homebrew package | Users retain tested uv/PyPI lifecycle | Existing release boundary | Use if demand/maintenance threshold fails |

The formula owns its Python dependency and must not depend on externally managed
uv. Poppler, Ghostscript, and Bash must not be downloaded or bundled. Whether
Poppler and Ghostscript become required formula dependencies is a post-M3 product
choice: current packaging calls them native prerequisites while `doctor` expects
them. A tap may test both absent/actionable and installed/functional states;
core submission should wait until this boundary is unambiguous.

## Proposed implementation and validation workflow

1. After M3, confirm demand and settle the native-capability dependency boundary.
2. Generate a formula from the stable sdist, reviewed lock/metadata, and immutable
   PyPI or publisher URLs. Record SHA-256 for the sdist and every Python resource;
   do not run dependency resolution or network downloads in `install`.
3. In a temporary local tap, run format/style, `brew audit --strict --online`,
   `brew audit --new --formula`, source-build installation, a functional test,
   and checksum verification.
4. On disposable Apple-silicon and Intel macOS where runners are available, and
   Linuxbrew x86_64 initially, test fresh/repeated install, link/PATH behavior,
   upgrade, `brew pin` behavior, prior-version recovery through supported tap
   history, partial-failure cleanup, and uninstall preserving user-owned state.
5. Create the project tap and any bottle publication only as separately
   authorized external publication tasks. If bottles are added, guard the exact
   reviewed head and record bottle rebuild/architecture ownership.
6. Automate release update proposals with reviewed URL/resource/hash diffs and
   lifecycle evidence. Never let automation publish a formula or bottle solely
   because a new PyPI version exists.
7. Evaluate core only after durable tap demand and maintenance evidence; treat
   external submission and response handling as a separate issue.

Tracked order: [#65 demand/dependency boundary](https://github.com/smartnuf/agent-tools/issues/65)
→ [#66 formula generation](https://github.com/smartnuf/agent-tools/issues/66)
→ [#67 formula audit/test](https://github.com/smartnuf/agent-tools/issues/67)
→ [#68 disposable-host lifecycle](https://github.com/smartnuf/agent-tools/issues/68)
→ [#69 release updates](https://github.com/smartnuf/agent-tools/issues/69)
→ [#70 tap publication/core evaluation](https://github.com/smartnuf/agent-tools/issues/70).
Issue #70 remains an external-publication boundary requiring explicit authority.

## Risks, unresolved questions, and rejection criteria

- The complete Python resource set may be large and platform-specific. A
  deterministic generator must prove that wheels are not accidentally treated
  as portable source resources and that licenses remain acceptable.
- Linuxbrew and macOS may resolve different native/transitive dependencies;
  the formula must test both rather than infer portability from the wheel.
- Homebrew bottles are downstream artifacts with their own checksums and rebuild
  lifecycle. They are optional for the tap and require explicit publication
  ownership if introduced.
- Formula unlink/uninstall removes Homebrew-owned files, not user configuration;
  tests must prove that application state is preserved and documented.
- Reject/continue deferral if demand does not justify 3–5 days plus recurring
  resource updates, the dependency tree cannot be reproduced without install-
  time resolution, required native capabilities create an unreasonable core
  dependency tree, or disposable macOS/Linux evidence is unavailable.
