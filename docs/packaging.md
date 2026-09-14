# Packaging contract

The public Python distribution is `smartnuf-agent-tools`. It provides
cross-platform capability discovery and diagnostics for coding-agent
workstations, with optional document libraries verified by `doctor`, and
installs the `agent-tools` command and `agent_tools` import package. The version
in `src/agent_tools/__init__.py` is the single source used by Hatchling to
produce distribution metadata.

## Supported product boundary

This section describes the current implementation. For v0.2,
[Decision 0007](decisions/0007-v0.2-product-and-distribution-boundary.md)
establishes `agent-tools` as the sole ordinary-user CLI and PyPI through
`uv tool` as the sole Agent Tools distribution channel. Issue #103 exposes
installed native installation through the existing M3 lifecycle; checkout
helpers remain development/compatibility infrastructure.

The wheel is the ordinary-user command-line application. It contains portable Python code from `src/agent_tools/`; it does not contain the repository's clone-oriented `bin/`, `scripts/`, configuration, exact environment lock, or `.venv`.

[Decision 0002](decisions/0002-native-capability-provider-model.md) extends
this boundary: native capability catalogue, discovery, and provider
orchestration belong in packaged Python. Clone-oriented scripts are thin front
ends rather than a second implementation. Their explicit native-install flags
invoke the internal packaged bootstrap module after editable installation, so
planning, execution, provenance, and final verification use the same reviewed
implementation. The internal bootstrap module is not a compatibility promise for direct module
callers. The public `agent-tools install` command uses the same orchestration,
with named-only scope under [Decision 0009](decisions/0009-installed-capability-install.md).

[Decision 0005](decisions/0005-desired-capability-state.md) adds a public,
versioned desired-capability document and `tools enable`/`tools disable`
lifecycle. These commands change user intent only: they require explicit
configuration-mutation authority, back up existing state, preserve unrelated
valid entries, and never install or remove a provider. Clone native setup is
the first consumer and still requires independent provider-mutation authority
before it can execute a nonempty plan.

[Decision 0006](decisions/0006-claude-code-git-bash-integration.md) adds one
packaged native-Windows agent adapter. It consumes the selected, verified Git
Bash path and manages only Claude Code's documented user-setting member behind
separate configuration-mutation authority. Its phase record is independent of
desired state and provider provenance; removal restores the prior member and
never removes the provider.

The clone workflow remains supported for contributors and advanced users who want the shared `agent-python` environment. Its bootstrap scripts install the same project editable and synchronize the complete environment from `requirements.txt`. A project-specific environment and lock remain authoritative over either installation.

`agent-tools doctor` reports `mode: checkout` and the verified repository root when invoked through that source layout. A wheel installation reports `mode: installed` and the package directory instead; it never labels a `site-packages` parent as a repository. `agent-tools --version` reads installed distribution metadata and falls back to the source version only when running directly from an uninstalled checkout.

`agent-tools tools list` reads the immutable packaged catalogue without probing
or changing the host. `agent-tools tools status [CAPABILITY]` reports ephemeral
detected state. Bash is optional: Git Bash is the preferred Windows-hosted
provider, normal system Bash serves Linux and macOS, and the default WSL
distribution is reported separately rather than satisfying Windows-hosted
Bash. `agent-tools tools enable bash [--provider PROVIDER]
--allow-config-mutation` and `tools disable bash --allow-config-mutation`
manage the separate desired-state document. `agent-tools install CAPABILITY [CAPABILITY ...]` exposes explicitly authorized
provider installation, honoring stored exact preferences only for named
capabilities. Provider removal remains outside the command boundary. The separately named
`agent-tools integrations claude-code` command group provides the one supported
agent-integration lifecycle; it is not a generic plugin surface.

## CLI help and reference

The public argparse tree in `src/agent_tools/cli.py` defines syntax, defaults,
purposes, safety and exit-status descriptions. Both runtime help and the
[generated reference](cli-reference.md) render that tree. Curated README and
platform prose provide examples and context rather than duplicate option tables.

From a bootstrapped development checkout, regenerate the reference with
`bin/agent-python -m agent_tools.cli_reference --write docs/cli-reference.md`
(Windows: `bin\agent-python.cmd`). Check it and the concrete guide invocations
with `bin/agent-python tests/check_cli_docs.py`. This developer-only projection
does not add an ordinary-user command or operational script to the artifact.

Required CI and release artifact validation check reference/example drift.
Installed-wheel smoke tests traverse every public root/nested `-h` and `--help`
and compare semantic help text with source outside a checkout. Unit tests prove
help cannot dispatch operational handlers and that command/default/help changes
invalidate stale documentation. Concrete fenced and inline guide commands are
parsed without execution; inline syntax placeholders and bare command-path
references are not treated as runnable shell examples. Historical ADR/release
records are not rewritten or checked as current command guides.

## Source distribution boundary

The sdist contains the application source, pyproject build metadata, README,
license, build-backend-included `.gitignore`, and generated PKG-INFO. It excludes `bin/`, `scripts/`, checkout tests,
configuration and maintenance documentation. No operational-script exception is
needed to rebuild the wheel. Repository CI runs the full checkout tests and
`uv build` builds the wheel from the sdist; artifact checks enforce both payloads.
[Hatch's file-selection contract](https://hatch.pypa.io/latest/config/build/#file-selection)
provides the target-specific include list. Use the Git repository for source
maintenance/tests; installing the sdist is not a clone-bootstrap route.

## Dependencies

The current source has no third-party core runtime dependencies. Its public
`documents` extra contains the seven libraries probed by `agent-tools doctor`:

- `pypdf`, `pdfplumber`, and `PyMuPDF` for PDF inspection and manipulation;
- `Pillow` and `reportlab` for image and PDF generation support;
- `python-docx` for Word documents;
- `openpyxl` for Excel workbooks.

They use compatible release-series bounds in `pyproject.toml`. The exact, reviewed versions in `requirements.txt` continue to define the clone-based shared environment. Transitive packages remain owned by their direct dependencies unless this application later imports or constrains one deliberately.

Poppler and Ghostscript are native runtime prerequisites, not Python dependencies. Install and update them through the operating system package manager. `uv` is the external environment and application installer; Hatchling is a build-system dependency. Neither is an application runtime dependency.

Use `uv tool install --python 3.13 --reinstall 'smartnuf-agent-tools[documents]'`
to select the extra, and reinstall the bare distribution to return to core.
`doctor` reports missing/partial/broken document imports without counting them
as required checks; `agent-tools doctor --documents` explicitly requires the
full stack. Both modes retain default native checks. No requested-extra state
is inferred or persisted. There are no document-processing commands; uv's
isolated tool imports do not become available in arbitrary project interpreters.
The [README](../README.md#optional-document-libraries) and
[Decision 0010](decisions/0010-document-extra-and-diagnostics.md) describe exact
pins, extra-preserving upgrades, direct-wheel migration and checksum-bound
rollback. Published v0.1.2 predates this boundary and still bundles documents.

## Metadata and compatibility

- Python: 3.11 through 3.13. Python 3.14 is deferred until all supported Windows architectures have binary dependency coverage or a documented compiler toolchain.
- Platforms: Windows, Linux, and macOS.
- License: MIT.
- Maturity: alpha. Lifecycle-milestone completion proves the corresponding
  behaviours but does not itself promote the distribution classifier; maturity
  promotion requires a separate reviewed release decision.

`tests/check_distribution.py` validates wheel and source-distribution metadata, required contents (including desired-state and Claude Code integration support), archive safety, and exclusion of machine-local state without importing from the checkout. CI installs the core wheel in a clean environment, then `tests/check_installed_cli.py` requires `--version`, `doctor`, `tools list`, the platform-appropriate Bash provider status, and the non-mutating desired-state and integration command help surfaces to pass from an unrelated directory. Build and smoke-test state is kept outside the checkout, which must remain unchanged.

CI builds one release bundle on Ubuntu, verifies its checksum manifest, and passes the same wheel to Windows, Ubuntu, and macOS jobs for isolated `uv tool` installation. `tests/check_document_installs.py` separately installs that exact wheel as core
and with documents into private uv tool roots, asserts distribution inventories,
checks both doctor modes and all CLI help, and removes each installation. The
pre-publication installed check exercises both shapes too. This proves
operating-system portability of the pure-Python artifact, but it is not native ARM64 coverage. Windows ARM64 may use x64-emulated uv-managed Python; native interpreter selection and architecture reporting are tracked in issue #14.

The same platform jobs download the complete published v0.1.1 and v0.1.2
release bundles and verify both release checksum manifests. The
[release lifecycle driver](../tests/check_release_lifecycle.py) then installs
that exact earlier wheel directly, matching its documented GitHub-release
installation, and exposes the exact published v0.1.2 wheel through a disposable
PEP 503 index. It proves replacement of the earlier direct-wheel receipt during
upgrade, then uses the independently checksum-verified HEAD wheel only to
create current desired-capability state. Reinstalling the exact published
current version, rolling back through the exact earlier wheel, and uninstalling
must all preserve the state bytes. The test also records and rechecks the
externally owned Bash executable and version after uninstall. This is an
application lifecycle contract, not a native-provider removal promise. On
macOS, where the documented configuration path is under the current user home,
the test requires separate home-configuration mutation authority and removes
only the file it created after proving application removal preserved it; it
never redirects `HOME`.

## PyPI presentation review

The root `README.md` is the package long description and therefore serves both
GitHub readers and the PyPI project page. Its first path now introduces the
application, gives one ordinary installation command, invokes read-only health
and capability inspection without requiring a profile change, and shows
upgrade and removal before source-development detail. Repository documentation
links use absolute, genuine GitHub destinations so they also work from PyPI.

Distribution metadata publishes Markdown content, the SPDX `MIT` license
expression, the packaged license file, the supported Python range, and a
product-aligned summary and keyword set. It omits the deprecated `License ::`
classifier and publishes the well-known `Documentation` and `Changelog` URLs
for the repository documentation and canonical GitHub release history.
`tests/check_distribution.py` verifies those fields and the product-first
long-description order in both the wheel and source distribution. Publication
uses PyPI Trusted Publishing through the dedicated GitHub Actions release
workflow and protected `pypi` environment; it does not use a long-lived upload
token.

[Decision 0008](decisions/0008-optional-document-capability-boundary.md) and
[Decision 0010](decisions/0010-document-extra-and-diagnostics.md) define the
optional packaging/diagnostic boundary, published in v0.2.0. Publication and
exact-tag evidence are recorded in the
[release qualification record](plan/10-v0.2-productisation/11-release-qualification.md);
a source build identity alone is not evidence of publication.

`tests/check_document_lifecycle.py` extends the historical lifecycle with four
migrations: the checksum-verified GitHub v0.1.1 wheel and published PyPI v0.1.2
wheel, each into core and documents candidates. Controlled local indexes expose
these exact artifacts, so this is artifact migration evidence rather than live
PyPI resolution. It checks versions, distributions, direct-source replacement,
unpinned upgrade, pin/reinstall, extra removal, resolution failure, both old
rollback targets and uninstall. Desired state, managed-state metadata and Bash
are preserved at each boundary. Native Windows also checks a real explicitly
applied integration in private settings, its ledger and backups; intended
restoration is explicit before rollback. macOS requires disposable-host
home-state authority, refuses existing state roots, and preserves changed state
on cleanup failure.

A separate current-source fixture, labelled as such, supplies an earlier
0.2.0.dev0 identity to test extra retention across a version change into the
actual 0.2.0 build. It is not a historical document-enabled release. CI runs
these checks on all three platforms, and the tag workflow repeats the candidate
contract before publication. GitHub/PyPI smoke checks exercise both shapes,
exact source/pin reconciliation, extra removal and uninstall after publication;
historical releases retain their mandatory-stack smoke path. Exact-tag,
attestation and public-index qualification passed for v0.2.0; the linked
release record also discloses its immutable PyPI description erratum. Future
versions require fresh qualification. See the
[lifecycle plan](plan/10-v0.2-productisation/05-document-lifecycle.md) for
candidate and source-fixture evidence boundaries.
