"""Smoke-test an installed console script from outside the source checkout."""

from __future__ import annotations

import argparse
import platform
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


def run(executable: Path, expected_version: str, require_native: bool) -> None:
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
        tools_list = subprocess.run(
            [executable, "tools", "list"],
            cwd=unrelated_directory,
            check=True,
            capture_output=True,
            text=True,
        )
        bash_status = subprocess.run(
            [executable, "tools", "status", "bash"],
            cwd=unrelated_directory,
            check=False,
            capture_output=True,
            text=True,
        )
        enable_help = subprocess.run(
            [executable, "tools", "enable", "--help"],
            cwd=unrelated_directory,
            check=True,
            capture_output=True,
            text=True,
        )
        disable_help = subprocess.run(
            [executable, "tools", "disable", "--help"],
            cwd=unrelated_directory,
            check=True,
            capture_output=True,
            text=True,
        )
    expected_return_codes = {0} if require_native else {0, 1}
    assert doctor.returncode in expected_return_codes, doctor.stderr or doctor.stdout
    assert "Traceback" not in doctor.stderr
    assert "mode:       installed" in doctor.stdout
    assert "package:" in doctor.stdout
    assert "repository:" not in doctor.stdout
    python_section = doctor.stdout.split("\nPython packages:\n", 1)[1].split(
        "\nNative tools:\n", 1
    )[0]
    assert "not installed" not in python_section
    assert "import failed" not in python_section
    if require_native:
        assert "All checks passed." in doctor.stdout
    assert "bash" in tools_list.stdout
    assert "git-bash, system-bash, homebrew-bash, wsl-bash" in tools_list.stdout
    assert bash_status.returncode == 0, bash_status.stderr or bash_status.stdout
    assert "bash: available (optional)" in bash_status.stdout
    expected_provider = "git-bash" if platform.system() == "Windows" else "system-bash"
    assert f"{expected_provider}: available" in bash_status.stdout
    assert "--allow-config-mutation" in enable_help.stdout
    assert "--provider" in enable_help.stdout
    assert "--allow-config-mutation" in disable_help.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--native-tools",
        choices=("allow-missing", "require"),
        default="allow-missing",
        help="whether Poppler and Ghostscript must be available",
    )
    args = parser.parse_args()
    run(args.executable, wheel_version(args.artifact), args.native_tools == "require")
    print(f"installed CLI passed: {args.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
