"""Small, standard-library release helpers used by CI and maintainers."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "agent_tools" / "__init__.py"
VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
CHECKSUM_PATTERN = re.compile(r"^([0-9a-f]{64})  ([^/\\]+)$")


def package_version() -> str:
    match = VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not read __version__ from {VERSION_FILE}")
    return match.group(1)


def verify_tag(tag: str) -> str:
    expected = f"v{package_version()}"
    if tag != expected:
        raise ValueError(f"release tag {tag!r} does not match package version {expected!r}")
    return expected


def write_checksums(destination: Path, artifacts: list[Path]) -> None:
    if not artifacts:
        raise ValueError("at least one artifact is required")
    resolved_destination = destination.resolve()
    unique_artifacts = sorted({artifact.resolve() for artifact in artifacts}, key=lambda path: path.name)
    if any(artifact == resolved_destination for artifact in unique_artifacts):
        raise ValueError("the checksum file cannot checksum itself")
    missing = [artifact for artifact in unique_artifacts if not artifact.is_file()]
    if missing:
        raise FileNotFoundError(f"artifact files not found: {missing}")
    duplicate_names = {
        artifact.name for artifact in unique_artifacts if sum(item.name == artifact.name for item in unique_artifacts) > 1
    }
    if duplicate_names:
        raise ValueError(f"artifact basenames must be unique: {sorted(duplicate_names)}")

    lines = []
    for artifact in unique_artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artifact.name}\n")
    destination.write_text("".join(lines), encoding="utf-8", newline="\n")


def verify_checksums(manifest: Path) -> None:
    directory = manifest.resolve().parent
    entries: dict[str, str] = {}
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        match = CHECKSUM_PATTERN.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid checksum line {line_number}: {line!r}")
        digest, filename = match.groups()
        if filename in entries:
            raise ValueError(f"duplicate checksum entry: {filename}")
        entries[filename] = digest
    if not entries:
        raise ValueError("checksum manifest is empty")

    artifact_names = {path.name for path in directory.iterdir() if path.is_file() and path != manifest.resolve()}
    if set(entries) != artifact_names:
        raise ValueError(
            f"checksum entries do not match artifacts: entries={sorted(entries)}, artifacts={sorted(artifact_names)}"
        )
    for filename, expected in entries.items():
        actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"checksum mismatch: {filename}")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-tag")
    verify.add_argument("tag")
    checksums = subparsers.add_parser("checksums")
    checksums.add_argument("destination", type=Path)
    checksums.add_argument("artifacts", nargs="+", type=Path)
    verify_checksums_parser = subparsers.add_parser("verify-checksums")
    verify_checksums_parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    if args.command == "verify-tag":
        print(f"release tag matches package version: {verify_tag(args.tag)}")
    elif args.command == "checksums":
        write_checksums(args.destination, args.artifacts)
        print(f"wrote checksums: {args.destination}")
    elif args.command == "verify-checksums":
        verify_checksums(args.manifest)
        print(f"verified checksums: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
