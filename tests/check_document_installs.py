"""Verify independent core/documents uv tool installs from the same exact wheel."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from check_installed_cli import run, wheel_version

DOCUMENT_DISTRIBUTIONS = {
    "pypdf", "pdfplumber", "pymupdf", "pillow", "reportlab", "python-docx", "openpyxl",
}


def check(wheel: Path, python: str, root: Path) -> None:
    version = wheel_version(wheel)
    for documents in (False, True):
        label = "documents" if documents else "core"
        directory = root / label
        directory.mkdir()
        environment = dict(os.environ, UV_TOOL_DIR=str(directory / "tools"),
                           UV_TOOL_BIN_DIR=str(directory / "bin"))
        requirement = f"smartnuf-agent-tools{'[documents]' if documents else ''} @ {wheel.as_uri()}"
        subprocess.run(["uv", "--no-config", "tool", "install", "--python", python, requirement],
                       env=environment, cwd=directory, check=True, timeout=300)
        tool = directory / "tools" / "smartnuf-agent-tools"
        interpreter = tool / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        installed = json.loads(subprocess.check_output([
            interpreter, "-I", "-c",
            "import importlib.metadata as m,json; print(json.dumps(sorted(d.metadata['Name'].lower() for d in m.distributions())))",
        ], cwd=directory, env=environment, text=True, timeout=30))
        if documents:
            assert DOCUMENT_DISTRIBUTIONS.issubset(installed), installed
        else:
            assert installed == ["smartnuf-agent-tools"], installed
        executable = directory / "bin" / ("agent-tools.exe" if os.name == "nt" else "agent-tools")
        run(executable, version, require_native=False, documents=documents)
        subprocess.run(["uv", "--no-config", "tool", "uninstall", "smartnuf-agent-tools"],
                       env=environment, cwd=directory, check=True, timeout=60)
        assert not os.path.lexists(executable) and not tool.exists()
        print(f"Independent {label} installed artifact passed: {wheel.name}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--python", default="3.13")
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    wheels = list(artifact.glob("*.whl")) if artifact.is_dir() else [artifact]
    if len(wheels) != 1:
        parser.error("expected exactly one wheel")
    with TemporaryDirectory(prefix="agent-tools-documents-") as temporary:
        check(wheels[0], args.python, Path(temporary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
