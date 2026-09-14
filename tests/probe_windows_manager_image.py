"""Read-only AppExec image experiment; not a production identity resolver."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest import mock

from agent_tools import provider_execution


def process_image(process):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    if not query(int(process._handle), 0, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("native Windows is required")
    result = {"evidence_class": "read-only-identity-experiment"}
    try:
        alias = shutil.which("winget")
        assert alias is not None, "WinGet is absent"
        result.update(alias=alias, reparse_tag=os.lstat(alias).st_reparse_tag)
        original = subprocess.Popen
        argv = (alias, "--version")

        def observe(*positional, **keywords):
            process = original(*positional, **keywords)
            if tuple(positional[0]) == argv:
                # Never raise before the existing supervisor receives ownership.
                # The experiment observes the owned handle, not a reusable PID.
                try:
                    target = Path(process_image(process))
                    result.update(image=str(target), image_is_file=target.is_file(),
                                  resolved_image=str(target.resolve(strict=True)))
                except Exception as error:
                    result["observation_error"] = str(error)
            return process

        with mock.patch.object(provider_execution.subprocess, "Popen", side_effect=observe):
            completed = provider_execution.run_bounded_command(argv, 10)
        result.update(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
        assert completed.returncode == 0, "version probe failed"
        assert "observation_error" not in result, result
        assert result.get("image_is_file") and result.get("resolved_image"), result
        result["status"] = "observed"
    except Exception as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
