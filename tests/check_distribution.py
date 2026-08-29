"""Validate built wheel and sdist contracts using only the standard library."""

from __future__ import annotations

import argparse
import tarfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
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
FORBIDDEN_PARTS = {".git", ".venv", ".tools", ".cache", ".backups", "__pycache__"}


def _one_match(names: list[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one {suffix} file, found {matches}")
    return matches[0]


def _check_metadata(metadata: Message) -> str:
    assert metadata["Name"] == "smartnuf-agent-tools"
    assert metadata["Version"] == "0.1.0"
    python_constraints = {
        constraint.strip()
        for constraint in metadata["Requires-Python"].split(",")
    }
    assert python_constraints == {">=3.11", "<3.14"}
    assert metadata["License-Expression"] == "MIT"
    assert set(metadata.get_all("Project-URL", [])) == EXPECTED_URLS
    dependencies = {
        requirement.replace(" ", "").lower()
        for requirement in metadata.get_all("Requires-Dist", [])
    }
    assert dependencies == EXPECTED_DEPENDENCIES
    return metadata["Version"]


def check_wheel(wheel: Path) -> str:
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_name = _one_match(names, ".dist-info/METADATA")
        dist_info = metadata_name.removesuffix("METADATA")
        entry_points_name = f"{dist_info}entry_points.txt"
        if entry_points_name not in names:
            raise AssertionError(f"missing entry points: {entry_points_name}")
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        entry_points = archive.read(entry_points_name).decode("utf-8")

    version = _check_metadata(metadata)
    assert "[console_scripts]\nagent-tools = agent_tools.cli:main\n" in entry_points
    unexpected = [
        name
        for name in names
        if not (name.startswith("agent_tools/") or name.startswith(dist_info))
    ]
    assert not unexpected, f"unexpected wheel content: {unexpected}"
    return version


def check_sdist(sdist: Path) -> str:
    expected_root = sdist.name.removesuffix(".tar.gz")
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        unsafe = []
        forbidden = []
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                unsafe.append(member.name)
            if FORBIDDEN_PARTS.intersection(path.parts) or path.suffix == ".pyc":
                forbidden.append(member.name)
        assert not unsafe, f"unsafe sdist members: {unsafe}"
        assert not forbidden, f"machine-local sdist members: {forbidden}"
        assert {PurePosixPath(name).parts[0] for name in names} == {expected_root}

        required = {
            f"{expected_root}/LICENSE",
            f"{expected_root}/README.md",
            f"{expected_root}/pyproject.toml",
            f"{expected_root}/src/agent_tools/__init__.py",
            f"{expected_root}/src/agent_tools/__main__.py",
            f"{expected_root}/src/agent_tools/cli.py",
            f"{expected_root}/PKG-INFO",
        }
        assert required.issubset(names), f"sdist is missing: {sorted(required.difference(names))}"
        metadata_file = archive.extractfile(f"{expected_root}/PKG-INFO")
        if metadata_file is None:
            raise AssertionError("sdist PKG-INFO is not a regular file")
        metadata = BytesParser().parsebytes(metadata_file.read())
    return _check_metadata(metadata)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.artifact_directory.glob("*.whl"))
    sdists = sorted(args.artifact_directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser.error(f"expected one wheel and one sdist, found {wheels} and {sdists}")
    wheel_version = check_wheel(wheels[0])
    sdist_version = check_sdist(sdists[0])
    assert wheel_version == sdist_version
    print(f"distribution artifacts passed: {wheels[0].name}, {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
