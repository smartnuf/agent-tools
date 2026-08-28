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

# Force the next backup to use the same timestamp and prove it cannot overwrite.
BACKUP_STAMP=${BACKUP##*.bashrc.agent-tools-backup-}
printf 'original backup\n' > "$BACKUP"
printf 'second profile\n' > "$PROFILE"
FAKE_BIN="$TEST_HOME/fake-bin"
mkdir "$FAKE_BIN"
cat > "$FAKE_BIN/date" <<EOF
#!/bin/sh
printf '%s\n' '$BACKUP_STAMP'
EOF
chmod +x "$FAKE_BIN/date"
PATH="$FAKE_BIN:$PATH" HOME="$TEST_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply
[ "$(cat "$BACKUP")" = 'original backup' ]
[ -f "$BACKUP-1" ]
[ "$(cat "$BACKUP-1")" = 'second profile' ]
[ "$(find "$TEST_HOME" -maxdepth 1 -name '.bashrc.agent-tools-backup-snapshot.*' | wc -l | tr -d ' ')" -eq 0 ]

# Concurrent applies must serialize the check, backup, and profile append.
CONCURRENT_HOME="$TEST_HOME/concurrent"
mkdir "$CONCURRENT_HOME"
printf 'concurrent profile\n' > "$CONCURRENT_HOME/.bashrc"
HOME="$CONCURRENT_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply &
FIRST_PID=$!
HOME="$CONCURRENT_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply &
SECOND_PID=$!
wait "$FIRST_PID"
wait "$SECOND_PID"
[ "$(grep -Fxc "$LINE" "$CONCURRENT_HOME/.bashrc")" -eq 1 ]
[ ! -e "$CONCURRENT_HOME/.bashrc.agent-tools-lock" ]

# An abandoned lock must fail safely without being removed automatically.
STALE_HOME="$TEST_HOME/stale"
mkdir "$STALE_HOME"
printf 'stale profile\n' > "$STALE_HOME/.bashrc"
printf '99999999\n' > "$STALE_HOME/.bashrc.agent-tools-lock"
if AGENT_TOOLS_LOCK_MAX_ATTEMPTS=1 HOME="$STALE_HOME" SHELL=/bin/bash sh "$ROOT/scripts/path.sh" --apply 2> "$STALE_HOME/error"; then
  echo 'Expected an abandoned lock to stop the update.' >&2
  exit 1
fi
[ "$(cat "$STALE_HOME/.bashrc")" = 'stale profile' ]
[ "$(cat "$STALE_HOME/.bashrc.agent-tools-lock")" = '99999999' ]
grep -F "Lock file: $STALE_HOME/.bashrc.agent-tools-lock (recorded owner PID: 99999999)." "$STALE_HOME/error" >/dev/null
[ "$(find "$STALE_HOME" -maxdepth 1 -name '.bashrc.agent-tools-lock.owner.*' | wc -l | tr -d ' ')" -eq 0 ]
