from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import os
import platform
import re
import shutil
import sys
from pathlib import Path

from . import __version__

DISTRIBUTION_NAME = "smartnuf-agent-tools"
PACKAGE_PROBES = ("pypdf", "pdfplumber", "pymupdf", "PIL", "reportlab", "docx", "openpyxl")
REQUIRED_EXECUTABLE_GROUPS = {
    "Poppler": ("pdfinfo", "pdftotext", "pdftoppm"),
}
ALTERNATIVE_EXECUTABLE_GROUPS = {
    "Ghostscript": ("gs", "gswin64c", "gswin32c"),
}


def _application_version() -> str:
    try:
        return importlib.metadata.version(DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return __version__


def _distribution_version(module: str) -> str:
    distributions = importlib.metadata.packages_distributions().get(module, [module])
    for distribution in distributions:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return "not installed"


def _checkout_root(module_path: Path | None = None) -> Path | None:
    module_path = (module_path or Path(__file__)).resolve()
    try:
        candidate = module_path.parents[2]
    except IndexError:
        return None
    markers = (
        candidate / "pyproject.toml",
        candidate / "src" / "agent_tools",
        candidate / "bin",
        candidate / "scripts",
    )
    return candidate if all(marker.exists() for marker in markers) else None


def _find_executable(probe: str) -> str | None:
    found = shutil.which(probe)
    if found or platform.system() != "Windows" or probe not in {"gswin64c", "gswin32c"}:
        return found
    roots = filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")))
    candidates = (
        candidate
        for root in roots
        for candidate in Path(root, "gs").glob(f"*/bin/{probe}.exe")
        if candidate.is_file()
    )
    def version_key(candidate: Path) -> tuple[int, ...]:
        match = re.search(r"\d+(?:\.\d+)*", candidate.parent.parent.name)
        return tuple(map(int, match.group().split("."))) if match else (0,)

    return str(max(candidates, key=version_key, default="")) or None


def doctor() -> int:
    checkout = _checkout_root()
    if checkout is None:
        print("mode:       installed")
        print(f"package:    {Path(__file__).resolve().parent}")
    else:
        print("mode:       checkout")
        print(f"repository: {checkout}")
    print(f"agent-tools: {_application_version()}")
    print(f"platform:   {platform.platform()}")
    print(f"python:     {sys.executable} ({platform.python_version()})")

    problems = 0
    print("\nPython packages:")
    for module in PACKAGE_PROBES:
        version = _distribution_version(module)
        try:
            importlib.import_module(module)
        except Exception as error:
            print(f"  {module:<12} {version}; import failed: {type(error).__name__}: {error}")
            problems += 1
        else:
            print(f"  {module:<12} {version}")
            problems += version == "not installed"

    print("\nNative tools:")
    for label, probes in REQUIRED_EXECUTABLE_GROUPS.items():
        found = [(probe, _find_executable(probe)) for probe in probes]
        missing = [probe for probe, path in found if not path]
        if missing:
            print(f"  {label:<12} missing required executable(s): {', '.join(missing)}")
            problems += 1
        else:
            locations = ", ".join(f"{probe}: {path}" for probe, path in found)
            print(f"  {label:<12} {locations}")

    for label, alternatives in ALTERNATIVE_EXECUTABLE_GROUPS.items():
        available = [(probe, _find_executable(probe)) for probe in alternatives]
        available = [(probe, path) for probe, path in available if path]
        if available:
            probe, path = available[0]
            print(f"  {label:<12} {probe}: {path}")
        else:
            print(f"  {label:<12} not found ({', '.join(alternatives)})")
            problems += 1

    if problems:
        print(f"\n{problems} check(s) need attention.")
        return 1
    print("\nAll checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-tools")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_application_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show Python and native-tool availability")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    return 2
