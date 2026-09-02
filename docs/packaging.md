# Packaging contract

The public Python distribution is `smartnuf-agent-tools`. It provides agent workstation capability discovery and diagnostics alongside reusable document tools, and installs the `agent-tools` command and `agent_tools` import package. The version in `src/agent_tools/__init__.py` is the single source used by Hatchling to produce distribution metadata.

## Supported product boundary

The wheel is the ordinary-user command-line application. It contains portable Python code from `src/agent_tools/`; it does not contain the repository's clone-oriented `bin/`, `scripts/`, configuration, exact environment lock, or `.venv`.

[Decision 0002](decisions/0002-native-capability-provider-model.md) extends
this boundary: native capability catalogue, discovery, and provider
orchestration belong in packaged Python. Clone-oriented scripts are thin front
ends rather than a second implementation. Their explicit native-install flags
invoke the internal packaged bootstrap module after editable installation, so
planning, execution, provenance, and final verification use the same reviewed
implementation. This clone-only entry point is not a public `tools install`
command or a compatibility promise for direct module callers.

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
manage the separate desired-state document. Public provider installation and
removal remain outside this console-command boundary. The separately named
`agent-tools integrations claude-code` command group provides the one supported
agent-integration lifecycle; it is not a generic plugin surface.

## Dependencies

The seven document libraries probed by `agent-tools doctor` are direct runtime dependencies of the ordinary installation:

- `pypdf`, `pdfplumber`, and `PyMuPDF` for PDF inspection and manipulation;
- `Pillow` and `reportlab` for image and PDF generation support;
- `python-docx` for Word documents;
- `openpyxl` for Excel workbooks.

They use compatible release-series bounds in `pyproject.toml`. The exact, reviewed versions in `requirements.txt` continue to define the clone-based shared environment. Transitive packages remain owned by their direct dependencies unless this application later imports or constrains one deliberately.

Poppler and Ghostscript are native runtime prerequisites, not Python dependencies. Install and update them through the operating system package manager. `uv` is the external environment and application installer; Hatchling is a build-system dependency. Neither is an application runtime dependency.

There are currently no optional dependency groups: omitting the document libraries would make the supported `doctor` command report an incomplete ordinary installation. Introduce optional groups only alongside a corresponding change to that product contract.

## Metadata and compatibility

- Python: 3.11 through 3.13. Python 3.14 is deferred until all supported Windows architectures have binary dependency coverage or a documented compiler toolchain.
- Platforms: Windows, Linux, and macOS.
- License: MIT.
- Maturity: alpha until the release lifecycle milestones are complete.

`tests/check_distribution.py` validates wheel and source-distribution metadata, required contents (including desired-state and Claude Code integration support), archive safety, and exclusion of machine-local state without importing from the checkout. CI installs the wheel and all declared dependencies in a clean environment, then `tests/check_installed_cli.py` requires `--version`, `doctor`, `tools list`, the platform-appropriate Bash provider status, and the non-mutating desired-state and integration command help surfaces to pass from an unrelated directory. Build and smoke-test state is kept outside the checkout, which must remain unchanged.

CI builds one release bundle on Ubuntu, verifies its checksum manifest, and passes the same wheel to Windows, Ubuntu, and macOS jobs for isolated `uv tool` installation. This proves operating-system portability of the pure-Python artifact, but it is not native ARM64 coverage. Windows ARM64 may use x64-emulated uv-managed Python; native interpreter selection and architecture reporting are tracked in issue #14.

## PyPI presentation review

The root `README.md` is the package long description and therefore serves both
GitHub readers and the PyPI project page. The stable v0.1.2 metadata correctly
publishes Markdown content, the SPDX `MIT` license expression, the packaged
license file, the supported Python range, and the current product summary and
keywords. Publication uses PyPI Trusted Publishing through the dedicated
GitHub Actions release workflow and protected `pypi` environment; it does not
use a long-lived upload token.

Current PyPA guidance deprecates `License ::` classifiers when an SPDX license
expression is present, and recommends well-known project URL labels such as
Documentation and Changelog when genuine destinations exist. A bounded
[casual-user README and metadata issue](https://github.com/smartnuf/agent-tools/issues/56)
owns that presentation cleanup before the next release. It is kept out of the
provider-selection design change so the larger PyPI front-door rewrite can be
reviewed on its own rendered result.

The required document libraries are also a real product-boundary question for
casual users, not a mechanical metadata cleanup. [Issue #57](https://github.com/smartnuf/agent-tools/issues/57)
will decide the core-versus-`documents` contract before any dependency moves;
the present mandatory dependencies and `doctor` behavior remain unchanged.
