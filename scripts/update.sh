#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v uv >/dev/null 2>&1 || { echo "uv is required; run bootstrap.sh first." >&2; exit 1; }
uv pip install --exact --python "$ROOT/.venv/bin/python" -r "$ROOT/requirements.txt" -e "$ROOT"
"$ROOT/bin/agent-tools" doctor
