"""Select native integration for pull-request paths."""

from __future__ import annotations

import argparse
import fnmatch
import subprocess


NATIVE_PATHS = (
    ".github/actions/install-native/**",
    ".github/workflows/native-integration.yml",
    ".github/workflows/release.yml",
    "scripts/bootstrap.ps1",
    "scripts/bootstrap.sh",
    "scripts/select-python.py",
    "scripts/install-native.sh",
    "scripts/select_native_integration.py",
    "scripts/windows-tools.ps1",
    "src/agent_tools/capabilities.py",
    "src/agent_tools/cli.py",
    "src/agent_tools/python_selection.py",
    "tests/check_installed_cli.py",
    "tests/test_capabilities.py",
    "tests/test_cli.py",
    "tests/test_install_native.sh",
    "tests/test_select_native_integration.py",
    "tests/test_windows_tools.ps1",
)


def requires_native(paths: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(path.replace("\\", "/"), pattern)
        for path in paths
        for pattern in NATIVE_PATHS
    )


def changed_paths(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    print("true" if requires_native(changed_paths(args.base, args.head)) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
