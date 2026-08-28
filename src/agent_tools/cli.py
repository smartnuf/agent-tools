from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import platform
import shutil
import sys
from pathlib import Path


PACKAGE_PROBES = ("pypdf", "pdfplumber", "fitz", "PIL", "reportlab", "docx", "openpyxl")
REQUIRED_EXECUTABLE_GROUPS = {
    "Poppler": ("pdfinfo", "pdftotext", "pdftoppm"),
}
ALTERNATIVE_EXECUTABLE_GROUPS = {
    "Ghostscript": ("gs", "gswin64c", "gswin32c"),
}


def _distribution_version(module: str) -> str:
    distributions = importlib.metadata.packages_distributions().get(module, [module])
    for distribution in distributions:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    return "not installed"


def doctor() -> int:
    root = Path(__file__).resolve().parents[2]
    print(f"repository: {root}")
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
        found = [(probe, shutil.which(probe)) for probe in probes]
        missing = [probe for probe, path in found if not path]
        if missing:
            print(f"  {label:<12} missing required executable(s): {', '.join(missing)}")
            problems += 1
        else:
            locations = ", ".join(f"{probe}: {path}" for probe, path in found)
            print(f"  {label:<12} {locations}")

    for label, alternatives in ALTERNATIVE_EXECUTABLE_GROUPS.items():
        available = [(probe, shutil.which(probe)) for probe in alternatives]
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
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="show Python and native-tool availability")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor()
    return 2
