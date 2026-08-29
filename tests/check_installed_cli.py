"""Smoke-test an installed console script from outside the source checkout."""

from __future__ import annotations

import argparse
import subprocess
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def wheel_version(artifact: Path) -> str:
    wheels = sorted(artifact.glob("*.whl")) if artifact.is_dir() else [artifact]
    if len(wheels) != 1:
        raise AssertionError(f"expected one wheel, found {wheels}")
    with ZipFile(wheels[0]) as archive:
        metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise AssertionError(f"expected one METADATA file, found {metadata_files}")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
    version = metadata["Version"]
    if not version:
        raise AssertionError("wheel metadata has no Version")
    return version


def run(executable: Path, expected_version: str) -> None:
    with TemporaryDirectory() as unrelated_directory:
        version = subprocess.run(
            [executable, "--version"],
            cwd=unrelated_directory,
            check=True,
            capture_output=True,
            text=True,
        )
        assert version.stdout == f"agent-tools {expected_version}\n"

        doctor = subprocess.run(
            [executable, "doctor"],
            cwd=unrelated_directory,
            check=False,
            capture_output=True,
            text=True,
        )
    assert doctor.returncode in {0, 1}, doctor.stderr
    assert "Traceback" not in doctor.stderr
    assert "mode:       installed" in doctor.stdout
    assert "package:" in doctor.stdout
    assert "repository:" not in doctor.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    run(args.executable, wheel_version(args.artifact))
    print(f"installed CLI passed: {args.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
