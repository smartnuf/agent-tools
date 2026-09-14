"""Read-only hosted-runner observations; these do not prove CLI mutation."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MAX_OUTPUT_BYTES = 16_384
PROBE_TIMEOUT_SECONDS = 10
MANAGERS = {
    "Windows": ("winget", "choco"),
    "Linux": ("apt-get", "dnf", "pacman"),
    "Darwin": ("brew",),
}
PROVIDERS = {
    "pdfinfo": "-v", "pdftotext": "-v", "pdftoppm": "-v",
    "gs": "--version", "gswin64c": "--version", "gswin32c": "--version",
}


def probe(command: str, *arguments: str) -> dict:
    executable = shutil.which(command)
    result = {"command": [command, *arguments], "executable": executable}
    if executable is None:
        result["status"] = "not-found"
        return result
    try:
        result["resolved_executable"] = str(Path(executable).resolve(strict=True))
    except OSError as error:
        # Windows app-execution aliases can run even when realpath is unavailable.
        # This is an observation, not the production manager identity verifier.
        result["resolution_error"] = str(error)
    try:
        with tempfile.TemporaryFile() as output:
            try:
                completed = subprocess.run(
                    [executable, *arguments], stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, check=False,
                    timeout=PROBE_TIMEOUT_SECONDS,
                    env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1"},
                )
                result.update(status="completed", returncode=completed.returncode)
            except subprocess.TimeoutExpired:
                result["status"] = "timeout"
            size = output.tell()
            output.seek(max(0, size - MAX_OUTPUT_BYTES))
            result["output_tail"] = output.read(MAX_OUTPUT_BYTES).decode("utf-8", "replace")
            result["output_truncated"] = size > MAX_OUTPUT_BYTES
    except OSError as error:
        result.update(status="error", detail=str(error))
    return result


def collect(phase: str, fixture_outcome: str) -> dict:
    system = platform.system()
    operating_system = {
        "system": system, "release": platform.release(), "version": platform.version(),
    }
    if system == "Linux":
        try:
            operating_system["distribution"] = platform.freedesktop_os_release()
        except OSError as error:
            operating_system["distribution_error"] = str(error)
    elif system == "Windows":
        operating_system["windows_version"] = list(sys.getwindowsversion())
    elif system == "Darwin":
        operating_system["mac_version"] = platform.mac_ver()[0]
        operating_system["sw_vers"] = probe("sw_vers")
    architecture = {
        "platform_machine": platform.machine(),
        "python_pointer_bits": 64 if sys.maxsize > 2**32 else 32,
        "runner_arch": os.environ.get("RUNNER_ARCH"),
    }
    if system == "Windows":
        architecture["processor_architecture"] = os.environ.get("PROCESSOR_ARCHITECTURE")
        architecture["processor_architew6432"] = os.environ.get("PROCESSOR_ARCHITEW6432")
    elif system == "Darwin":
        architecture["arm64_hardware"] = probe("sysctl", "-n", "hw.optional.arm64")
        architecture["process_translated"] = probe("sysctl", "-n", "sysctl.proc_translated")
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "evidence_class": "external-preseed-observation",
        "phase": phase,
        "fixture_outcome": fixture_outcome,
        "operating_system": operating_system,
        "architecture": architecture,
        "execution_context": {
            "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
            "runner_environment": os.environ.get("RUNNER_ENVIRONMENT"),
            "wsl_indicator": "microsoft" in platform.release().lower(),
            "container_markers": [str(p) for p in (Path("/.dockerenv"), Path("/run/.containerenv")) if p.exists()],
        },
        "runner": {name: os.environ.get(name) for name in (
            "RUNNER_OS", "ImageOS", "ImageVersion", "GITHUB_REPOSITORY",
            "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB",
        )},
        "recording_python": {"executable": sys.executable, "version": sys.version},
        "uv": probe("uv", "--version"),
        "managers": {name: probe(name, "--version") for name in MANAGERS.get(system, ())},
        "provider_executables": {name: probe(name, flag) for name, flag in PROVIDERS.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--fixture-outcome", default="not-started")
    args = parser.parse_args()
    data = collect(args.phase, args.fixture_outcome)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # A duplicate capture is a configuration error, not overwrite authority.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    print(json.dumps(data, ensure_ascii=True))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(
                f"\nNative fixture environment capture ({args.phase}): "
                f"`{args.output.name}`. This is external-preseed evidence, "
                "not installed-CLI mutation proof. See the native-environment artifact.\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
