"""Validate the public contract using only a built wheel and the standard library."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


EXPECTED_DEPENDENCIES = {
    "pypdf<7,>=6.16",
    "pdfplumber<0.12,>=0.11",
    "pymupdf<2,>=1.28",
    "pillow<13,>=12.3",
    "reportlab<6,>=5",
    "python-docx<2,>=1.2",
    "openpyxl<4,>=3.1",
}
EXPECTED_URLS = {
    "Homepage, https://github.com/smartnuf/agent-tools",
    "Repository, https://github.com/smartnuf/agent-tools",
    "Issues, https://github.com/smartnuf/agent-tools/issues",
}


def _one_match(names: list[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one {suffix} file, found {matches}")
    return matches[0]


def check_wheel(wheel: Path) -> None:
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_name = _one_match(names, ".dist-info/METADATA")
        dist_info = metadata_name.removesuffix("METADATA")
        entry_points_name = f"{dist_info}entry_points.txt"
        if entry_points_name not in names:
            raise AssertionError(f"missing entry points: {entry_points_name}")
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        entry_points = archive.read(entry_points_name).decode("utf-8")

    assert metadata["Name"] == "smartnuf-agent-tools"
    assert metadata["Version"] == "0.1.0"
    assert metadata["Requires-Python"] == ">=3.11"
    assert metadata["License-Expression"] == "MIT"
    assert set(metadata.get_all("Project-URL", [])) == EXPECTED_URLS

    dependencies = {
        requirement.replace(" ", "").lower()
        for requirement in metadata.get_all("Requires-Dist", [])
    }
    assert dependencies == EXPECTED_DEPENDENCIES
    assert "[console_scripts]\nagent-tools = agent_tools.cli:main\n" in entry_points

    unexpected = [
        name
        for name in names
        if not (name.startswith("agent_tools/") or name.startswith(dist_info))
    ]
    assert not unexpected, f"unexpected wheel content: {unexpected}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path, help="wheel file or directory containing one wheel")
    args = parser.parse_args()
    wheel = args.artifact
    if wheel.is_dir():
        wheels = sorted(wheel.glob("*.whl"))
        if len(wheels) != 1:
            parser.error(f"expected one wheel in {wheel}, found {len(wheels)}")
        wheel = wheels[0]
    check_wheel(wheel)
    print(f"wheel metadata passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
