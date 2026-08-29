# Packaging contract

The public Python distribution is `smartnuf-agent-tools`. It installs the `agent-tools` command and the `agent_tools` import package. The version in `src/agent_tools/__init__.py` is the single source used by Hatchling to produce distribution metadata.

## Supported product boundary

The wheel is the ordinary-user command-line application. It contains portable Python code from `src/agent_tools/`; it does not contain the repository's clone-oriented `bin/`, `scripts/`, configuration, exact environment lock, or `.venv`.

The clone workflow remains supported for contributors and advanced users who want the shared `agent-python` environment. Its bootstrap scripts install the same project editable and synchronize the complete environment from `requirements.txt`. A project-specific environment and lock remain authoritative over either installation.

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

- Python: 3.11 or newer.
- Platforms: Windows, Linux, and macOS.
- License: MIT.
- Maturity: alpha until the release lifecycle milestones are complete.

`tests/check_wheel_metadata.py` validates the built wheel without importing from the checkout. Isolated installation and CLI execution are tracked separately by issue #6.
