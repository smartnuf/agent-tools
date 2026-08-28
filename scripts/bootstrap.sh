#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INSTALL_UV=0
INSTALL_NATIVE=0
ADD_PATH=0
for arg in "$@"; do
  case "$arg" in
    --install-uv) INSTALL_UV=1 ;;
    --install-native-tools) INSTALL_NATIVE=1 ;;
    --add-to-path) ADD_PATH=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  if [ "$INSTALL_UV" -ne 1 ]; then
    echo "uv is not installed. Re-run with --install-uv, or install uv yourself." >&2
    exit 1
  fi
  if command -v brew >/dev/null 2>&1; then
    brew install uv
  else
    echo "Automatic uv installation requires Homebrew. Install uv with a trusted package manager, then rerun bootstrap." >&2
    exit 1
  fi
fi

if [ "$INSTALL_NATIVE" -eq 1 ]; then
  sh "$ROOT/scripts/install-native.sh"
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  uv venv "$ROOT/.venv" --python 3.11
fi
uv pip install --python "$ROOT/.venv/bin/python" -r "$ROOT/requirements.txt" -e "$ROOT"
if [ "$ADD_PATH" -eq 1 ]; then
  "$ROOT/scripts/path.sh" --apply
fi
echo "Ready. Run $ROOT/bin/agent-tools doctor"
