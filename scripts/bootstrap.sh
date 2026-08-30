#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INSTALL_UV=0
ALLOW_EMULATED_PYTHON=0
PYTHON_PATH=
INSTALL_NATIVE=0
ADD_PATH=0

probe_bootstrap_python() {
  "$1" -I -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 11))' >/dev/null 2>&1 &
  PROBE_PID=$!
  (sleep 10; kill "$PROBE_PID" 2>/dev/null || :) &
  WATCHDOG_PID=$!
  if wait "$PROBE_PID"; then
    PROBE_RESULT=0
  else
    PROBE_RESULT=$?
  fi
  kill "$WATCHDOG_PID" 2>/dev/null || :
  wait "$WATCHDOG_PID" 2>/dev/null || :
  return "$PROBE_RESULT"
}

probe_manager_root() {
  for CANDIDATE in "$1"/*/bin/python3.11 "$1"/*/bin/python3 "$1"/*/bin/python
  do
    if [ -x "$CANDIDATE" ] && probe_bootstrap_python "$CANDIDATE"; then
      BOOTSTRAP_PYTHON=$CANDIDATE
      return 0
    fi
  done
  return 1
}

probe_conda_base() {
  for CANDIDATE in "$1"/bin/python3.11 "$1"/bin/python3 "$1"/bin/python
  do
    if [ -x "$CANDIDATE" ] && probe_bootstrap_python "$CANDIDATE"; then
      BOOTSTRAP_PYTHON=$CANDIDATE
      return 0
    fi
  done
  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-uv) INSTALL_UV=1; shift ;;
    --allow-emulated-python) ALLOW_EMULATED_PYTHON=1; shift ;;
    --python)
      shift
      [ "$#" -gt 0 ] || { echo "--python requires a path" >&2; exit 2; }
      PYTHON_PATH=$1
      shift
      ;;
    --install-native-tools) INSTALL_NATIVE=1; shift ;;
    --add-to-path) ADD_PATH=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
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

SELECTOR_ARGS=
if [ "$ALLOW_EMULATED_PYTHON" -eq 1 ]; then
  SELECTOR_ARGS=--allow-translated
fi
if [ -n "$PYTHON_PATH" ]; then
  BOOTSTRAP_PYTHON=$PYTHON_PATH
else
  if ! BOOTSTRAP_PYTHON=$(env -u UV_MANAGED_PYTHON -u UV_NO_MANAGED_PYTHON -u UV_PYTHON_PREFERENCE -u UV_SYSTEM_PYTHON uv python find 3.11 --system --no-project --no-python-downloads --no-config); then
    BOOTSTRAP_PYTHON=$(env -u UV_MANAGED_PYTHON -u UV_NO_MANAGED_PYTHON -u UV_PYTHON_PREFERENCE -u UV_SYSTEM_PYTHON uv python find 3.11 --managed-python --no-project --no-python-downloads --no-config) || BOOTSTRAP_PYTHON=
  fi
  if [ -z "$BOOTSTRAP_PYTHON" ]; then
    for MANAGER_ROOT in \
      "${PYENV_ROOT:-$HOME/.pyenv}/versions" \
      "${ASDF_DATA_DIR:-$HOME/.asdf}/installs/python" \
      "${MISE_DATA_DIR:-$HOME/.local/share/mise}/installs/python" \
      "$HOME/.conda/envs" \
      "$HOME/miniconda3/envs" \
      "$HOME/anaconda3/envs" \
      "$HOME/miniforge3/envs" \
      "$HOME/mambaforge/envs"
    do
      probe_manager_root "$MANAGER_ROOT" && break
    done
  fi
  if [ -z "$BOOTSTRAP_PYTHON" ] && [ -n "${CONDA_ENVS_PATH:-}" ]; then
    SAVED_IFS=$IFS
    IFS=:
    for MANAGER_ROOT in $CONDA_ENVS_PATH
    do
      if probe_manager_root "$MANAGER_ROOT"; then break; fi
    done
    IFS=$SAVED_IFS
  fi
  if [ -z "$BOOTSTRAP_PYTHON" ]; then
    for CONDA_BASE in \
      "$HOME/miniconda3" \
      "$HOME/anaconda3" \
      "$HOME/miniforge3" \
      "$HOME/mambaforge"
    do
      probe_conda_base "$CONDA_BASE" && break
    done
  fi
  if [ -z "$BOOTSTRAP_PYTHON" ]; then
    echo "No installed Python 3.11 can run selection. Install a compatible Python with a trusted provider, then rerun bootstrap." >&2
    exit 1
  fi
fi
if [ -n "$PYTHON_PATH" ]; then
  SELECTED_PYTHON=$("$BOOTSTRAP_PYTHON" "$ROOT/scripts/select-python.py" $SELECTOR_ARGS --prefer "$PYTHON_PATH")
else
  SELECTED_PYTHON=$("$BOOTSTRAP_PYTHON" "$ROOT/scripts/select-python.py" $SELECTOR_ARGS)
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  uv venv "$ROOT/.venv" --python "$SELECTED_PYTHON" --no-python-downloads
fi
if [ -n "$PYTHON_PATH" ]; then
  "$BOOTSTRAP_PYTHON" "$ROOT/scripts/select-python.py" $SELECTOR_ARGS --prefer "$PYTHON_PATH" --verify-final "$ROOT/.venv/bin/python" >/dev/null
else
  "$BOOTSTRAP_PYTHON" "$ROOT/scripts/select-python.py" $SELECTOR_ARGS --verify-final "$ROOT/.venv/bin/python" >/dev/null
fi
if [ "$INSTALL_NATIVE" -eq 1 ]; then
  sh "$ROOT/scripts/install-native.sh"
fi
uv pip install --exact --python "$ROOT/.venv/bin/python" -r "$ROOT/requirements.txt" -e "$ROOT"
if [ "$ADD_PATH" -eq 1 ]; then
  "$ROOT/scripts/path.sh" --apply
fi
echo "Ready. Run $ROOT/bin/agent-tools doctor"
