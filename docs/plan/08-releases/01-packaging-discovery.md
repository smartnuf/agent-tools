# M0 packaging discovery

- Date: 2026-08-29
- Branch: `plan/m0-packaging-discovery`
- Effort class: S
- Original estimate: 0.25–0.5 person-day

## Distribution name

Select **`smartnuf-agent-tools`** as the intended public Python distribution name. Keep **`agent-tools`** as the installed command and `agent_tools` as the import package.

The official PyPI JSON endpoint returned HTTP 404 for both `smartnuf-agent-tools` and its normalized underscore spelling on 2026-08-29. The unqualified `agent-tools` distribution is already owned by an unrelated project. A 404 establishes that no public project page currently exists; it does not reserve the name or guarantee that PyPI will accept it later. Recheck during registry setup and treat the first successful trusted-publisher release as the conclusive reservation.

## Current packaging boundary

The current wheel contains `src/agent_tools` and installs the `agent-tools` entry point. It does not contain the repository's `bin/`, `scripts/`, configuration, or exact environment lock.

Checkout assumptions found during inventory:

- `doctor` labels `Path(__file__).resolve().parents[2]` as the repository, which is misleading in an installed wheel.
- `bin/agent-tools*` and `bin/agent-python*` locate a repository-owned `.venv` relative to the wrapper.
- bootstrap, update, PATH, and native-install automation locate scripts, requirements, and the environment relative to the checkout root.
- clone bootstrap installs the repository editable and synchronizes the complete shared environment from `requirements.txt`.
- the package exposes version `0.1.0` separately in `pyproject.toml` and `src/agent_tools/__init__.py`.
- CI tests clone/bootstrap operation, but it does not yet build and install the release wheel outside the checkout.

The clone workflow remains supported. M1 must add an installed-application contract without silently treating repository-only wrappers or the shared interpreter as wheel contents.

## Dependency classification

Current behaviour and the proposed package boundary differ, so issue #4 must finalize this classification in metadata:

| Dependency group | Current use | Proposed release treatment |
|---|---|---|
| Python standard library | CLI implementation and tests | required core; no package dependency |
| `pypdf`, `pdfplumber`, `PyMuPDF`, `Pillow`, `reportlab`, `python-docx`, `openpyxl` | shared document environment and required `doctor` probes | document-tool bundle or extra; decide whether the ordinary CLI installs all of it |
| transitive packages in `requirements.txt` | exact clone environment | do not declare directly unless the application imports or constrains them deliberately |
| Poppler and Ghostscript | required native `doctor` probes and document operations | native prerequisites owned by platform package managers |
| Hatchling | wheel/sdist build backend | build-system dependency only |
| `uv` | environment, tool installation, and release operations | external installer/runner; not a Python runtime dependency |
| repository scripts and wrappers | clone bootstrap, updates, PATH, and shared interpreter | advanced clone workflow unless deliberately ported into packaged CLI commands |

`requirements.in` and `requirements.txt` remain authoritative for the exact clone-based shared environment until the packaging contract deliberately changes them.

## Actionable M1 work

All tasks are assigned to GitHub milestone [M1 — Installable GitHub prerelease](https://github.com/smartnuf/agent-tools/milestone/2):

1. [#4 — Finalize packaging contract and distribution metadata](https://github.com/smartnuf/agent-tools/issues/4), 0.75–1.25 days.
2. [#5 — Make the installed CLI checkout-independent](https://github.com/smartnuf/agent-tools/issues/5), 0.75–1.25 days.
3. [#6 — Test wheel and sdist in isolated environments](https://github.com/smartnuf/agent-tools/issues/6), 0.5–1 day.
4. [#7 — Add a least-privilege tag release workflow](https://github.com/smartnuf/agent-tools/issues/7), 1–1.5 days.
5. [#8 — Verify release artifacts across supported platforms](https://github.com/smartnuf/agent-tools/issues/8), 0.5–1 day.
6. [#9 — Document and exercise the GitHub prerelease](https://github.com/smartnuf/agent-tools/issues/9), 0.5–1 day.

The ranges total the M1 estimate of 4–7 person-days. Dependencies and acceptance criteria are recorded in each issue; the repository milestone definition remains authoritative.

## Recommended next task

Begin issue #4 after this discovery change is reviewed and merged. It fixes the product boundary and metadata on which the installed CLI and artifact tests depend.
