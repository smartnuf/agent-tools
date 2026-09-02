"""Exercise upgrade, pin, rollback, and removal with exact wheel artifacts."""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import platform
import shutil
import subprocess
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile


PACKAGE = "smartnuf-agent-tools"
CONSOLE_SCRIPT = "agent-tools.exe" if os.name == "nt" else "agent-tools"


def wheel_identity(wheel: Path) -> tuple[str, str]:
    """Return the distribution name and version declared by one wheel."""

    with ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise AssertionError(
                f"expected one METADATA file in {wheel}, found {metadata_files}"
            )
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
    name = metadata["Name"]
    version = metadata["Version"]
    if not name or not version:
        raise AssertionError(f"wheel metadata lacks Name or Version: {wheel}")
    return name, version


def write_simple_index(index: Path, wheels: tuple[Path, ...]) -> None:
    """Write a minimal PEP 503 index containing the supplied exact wheels."""

    project = index / PACKAGE
    project.mkdir(parents=True)
    project_links: list[str] = []
    for wheel in wheels:
        destination = project / wheel.name
        shutil.copy2(wheel, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        filename = quote(destination.name)
        project_links.append(
            f'<a href="{filename}#sha256={digest}">{html.escape(destination.name)}</a>'
        )
    (project / "index.html").write_text(
        "<!doctype html>\n" + "\n".join(project_links) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (index / "index.html").write_text(
        f'<!doctype html>\n<a href="{PACKAGE}/">{PACKAGE}</a>\n',
        encoding="utf-8",
        newline="\n",
    )


def run_command(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    expected_return_codes: frozenset[int] = frozenset({0}),
) -> subprocess.CompletedProcess[str]:
    """Run and report a lifecycle command without shell interpretation."""

    print(f"+ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode not in expected_return_codes:
        raise AssertionError(
            f"command returned {result.returncode}; expected "
            f"{sorted(expected_return_codes)}: {command}"
        )
    return result


def assert_version(
    executable: Path,
    version: str,
    *,
    environment: dict[str, str],
    cwd: Path,
) -> None:
    result = run_command(
        [str(executable), "--version"], environment=environment, cwd=cwd
    )
    expected = f"agent-tools {version}"
    if result.stdout.strip() != expected:
        raise AssertionError(
            f"unexpected installed version: {result.stdout.strip()!r}; expected {expected!r}"
        )


def output_path(output: str) -> Path:
    for line in output.splitlines():
        if line.startswith("  path: "):
            return Path(line.removeprefix("  path: "))
    raise AssertionError(f"command did not report a desired-state path:\n{output}")


def assert_unchanged(path: Path, expected: bytes, phase: str) -> None:
    if not path.is_file():
        raise AssertionError(f"desired state was removed during {phase}: {path}")
    if path.read_bytes() != expected:
        raise AssertionError(f"desired state changed during {phase}: {path}")


def exercise_lifecycle(
    *,
    uv: str,
    python: str,
    previous_wheel: Path,
    previous_version: str,
    current_wheel: Path,
    current_version: str,
    work_directory: Path,
    allow_home_config_mutation: bool,
) -> None:
    previous_identity = wheel_identity(previous_wheel)
    current_identity = wheel_identity(current_wheel)
    if previous_identity != (PACKAGE, previous_version):
        raise AssertionError(
            f"unexpected previous wheel identity: {previous_identity}; "
            f"expected {(PACKAGE, previous_version)}"
        )
    if current_identity != (PACKAGE, current_version):
        raise AssertionError(
            f"unexpected current wheel identity: {current_identity}; "
            f"expected {(PACKAGE, current_version)}"
        )
    if previous_version == current_version:
        raise AssertionError("previous and current release versions must differ")

    work_directory.mkdir(parents=True, exist_ok=True)
    if any(work_directory.iterdir()):
        raise AssertionError(
            f"lifecycle work directory must be empty: {work_directory}"
        )
    current_index = work_directory / "current-index"
    write_simple_index(current_index, (current_wheel,))

    tool_directory = work_directory / "uv-tools"
    tool_bin = work_directory / "uv-bin"
    environment = dict(os.environ)
    environment.update(
        {
            "UV_TOOL_DIR": str(tool_directory),
            "UV_TOOL_BIN_DIR": str(tool_bin),
            "UV_CACHE_DIR": str(work_directory / "uv-cache"),
            "XDG_CONFIG_HOME": str(work_directory / "user-config"),
            "XDG_STATE_HOME": str(work_directory / "user-state"),
        }
    )
    if os.name == "nt":
        environment["LOCALAPPDATA"] = str(work_directory / "user-local-app-data")

    bash = shutil.which("bash", path=environment.get("PATH"))
    if bash is None:
        raise AssertionError("the disposable host has no externally owned Bash provider")
    bash_before = run_command(
        [bash, "--version"], environment=environment, cwd=work_directory
    ).stdout

    uv_command = [uv, "--no-config", "tool"]
    current_url = current_index.resolve().as_uri()
    executable = tool_bin / CONSOLE_SCRIPT

    run_command(
        uv_command + ["install", "--python", python, str(previous_wheel)],
        environment=environment,
        cwd=work_directory,
    )
    assert_version(
        executable, previous_version, environment=environment, cwd=work_directory
    )
    run_command(
        [str(executable), "integrations", "claude-code", "apply", "--help"],
        environment=environment,
        cwd=work_directory,
        expected_return_codes=frozenset({2}),
    )

    run_command(
        uv_command
        + [
            "install",
            "--python",
            python,
            "--upgrade",
            "--index",
            current_url,
            PACKAGE,
        ],
        environment=environment,
        cwd=work_directory,
    )
    assert_version(
        executable, current_version, environment=environment, cwd=work_directory
    )
    integration_help = run_command(
        [str(executable), "integrations", "claude-code", "apply", "--help"],
        environment=environment,
        cwd=work_directory,
    )
    if "--allow-config-mutation" not in integration_help.stdout:
        raise AssertionError("upgrade did not install the current artifact's CLI surface")

    refused = run_command(
        [str(executable), "tools", "enable", "bash"],
        environment=environment,
        cwd=work_directory,
        expected_return_codes=frozenset({1}),
    )
    config_path = output_path(refused.stdout)
    if config_path.exists():
        raise AssertionError(
            f"disposable lifecycle host already has desired state: {config_path}"
        )
    home_config = platform.system() == "Darwin"
    if home_config and not allow_home_config_mutation:
        raise AssertionError(
            "macOS lifecycle evidence requires --allow-home-config-mutation; "
            "the platform configuration path is under the current user home"
        )
    config_parent_existed = config_path.parent.exists()
    enabled = run_command(
        [
            str(executable),
            "tools",
            "enable",
            "bash",
            "--allow-config-mutation",
        ],
        environment=environment,
        cwd=work_directory,
    )
    if "desired state: updated" not in enabled.stdout:
        raise AssertionError("authorized desired-state creation was not reported")
    if output_path(enabled.stdout) != config_path:
        raise AssertionError("refused and authorized changes resolved different state paths")
    desired_state = config_path.read_bytes()
    if b'"bash"' not in desired_state:
        raise AssertionError("created desired state does not enable Bash")

    try:
        current_pin = f"{PACKAGE}=={current_version}"
        run_command(
            uv_command
            + [
                "install",
                "--python",
                python,
                "--reinstall",
                "--index",
                current_url,
                current_pin,
            ],
            environment=environment,
            cwd=work_directory,
        )
        assert_version(
            executable, current_version, environment=environment, cwd=work_directory
        )
        assert_unchanged(config_path, desired_state, "exact-version reinstall")

        run_command(
            uv_command
            + [
                "install",
                "--python",
                python,
                "--reinstall",
                str(previous_wheel),
            ],
            environment=environment,
            cwd=work_directory,
        )
        assert_version(
            executable, previous_version, environment=environment, cwd=work_directory
        )
        assert_unchanged(config_path, desired_state, "rollback")

        run_command(
            uv_command + ["uninstall", PACKAGE],
            environment=environment,
            cwd=work_directory,
        )
        if executable.exists():
            raise AssertionError(
                f"application executable remains after uninstall: {executable}"
            )
        assert_unchanged(config_path, desired_state, "application removal")
        resolved_bash_after = shutil.which("bash", path=environment.get("PATH"))
        if resolved_bash_after != bash:
            raise AssertionError(
                f"Bash provider path changed after application removal: {bash!r} -> "
                f"{resolved_bash_after!r}"
            )
        bash_after = run_command(
            [bash, "--version"], environment=environment, cwd=work_directory
        ).stdout
        if bash_after != bash_before:
            raise AssertionError(
                "Bash provider version output changed after application removal"
            )
    finally:
        if home_config and config_path.is_file() and config_path.read_bytes() == desired_state:
            config_path.unlink()
            print(f"cleaned lifecycle-created macOS desired state: {config_path}")
            if not config_parent_existed:
                config_path.parent.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-wheel", required=True, type=Path)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--current-wheel", required=True, type=Path)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--work-directory", required=True, type=Path)
    parser.add_argument("--python", default="3.13")
    parser.add_argument("--uv", default="uv")
    parser.add_argument(
        "--allow-home-config-mutation",
        action="store_true",
        help=(
            "authorize temporary creation and cleanup of the documented macOS "
            "desired-state file"
        ),
    )
    args = parser.parse_args()
    exercise_lifecycle(
        uv=args.uv,
        python=args.python,
        previous_wheel=args.previous_wheel.resolve(),
        previous_version=args.previous_version,
        current_wheel=args.current_wheel.resolve(),
        current_version=args.current_version,
        work_directory=args.work_directory.resolve(),
        allow_home_config_mutation=args.allow_home_config_mutation,
    )
    print(
        "release lifecycle passed: "
        f"{args.previous_version} -> {args.current_version} -> "
        f"{args.current_version} pin -> {args.previous_version} rollback -> removed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
