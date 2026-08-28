#!/usr/bin/env sh
set -eu

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Installing native tools requires root or sudo." >&2
    return 1
  fi
}

if command -v brew >/dev/null 2>&1; then
  brew install poppler ghostscript
elif command -v apt-get >/dev/null 2>&1; then
  run_privileged apt-get update
  run_privileged apt-get install -y poppler-utils ghostscript
elif command -v dnf >/dev/null 2>&1; then
  run_privileged dnf install -y poppler-utils ghostscript
elif command -v pacman >/dev/null 2>&1; then
  run_privileged pacman -S --needed poppler ghostscript
else
  echo "No supported native package manager found." >&2
  exit 1
fi
