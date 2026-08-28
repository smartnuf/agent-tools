#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_HOME=$(mktemp -d)
trap 'rm -rf "$TEST_HOME"' EXIT HUP INT TERM
PROFILE="$TEST_HOME/.bashrc"
LINE="export PATH=\"$ROOT/bin:\$PATH\""

printf '# %s\n' "$LINE" > "$PROFILE"
ORIGINAL=$(cat "$PROFILE")
HOME="$TEST_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply
[ "$(grep -Fxc "$LINE" "$PROFILE")" -eq 1 ]
BACKUP=$(find "$TEST_HOME" -maxdepth 1 -name '.bashrc.agent-tools-backup-*')
[ -n "$BACKUP" ]
[ "$(cat "$BACKUP")" = "$ORIGINAL" ]

HOME="$TEST_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply
[ "$(grep -Fxc "$LINE" "$PROFILE")" -eq 1 ]
[ "$(find "$TEST_HOME" -maxdepth 1 -name '.bashrc.agent-tools-backup-*' | wc -l | tr -d ' ')" -eq 1 ]
