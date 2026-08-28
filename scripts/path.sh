#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LINE="export PATH=\"$ROOT/bin:\$PATH\""
case "${1:-}" in
  --apply) ;;
  "") echo "Would add the following line to your shell profile:"; echo "$LINE"; exit 0 ;;
  *) echo "Usage: $0 [--apply]" >&2; exit 2 ;;
esac

SHELL_NAME=$(basename "${SHELL:-sh}")
case "$SHELL_NAME" in
  zsh) PROFILE="$HOME/.zshrc" ;;
  bash) PROFILE="$HOME/.bashrc" ;;
  *) echo "Unsupported shell $SHELL_NAME; add this manually: $LINE" >&2; exit 1 ;;
esac

LOCK="$PROFILE.agent-tools-lock"
LOCK_OWNER_FILE=$(mktemp "$LOCK.owner.XXXXXX")
printf '%s\n' "$$" > "$LOCK_OWNER_FILE"
LOCK_HELD=0
BACKUP_SNAPSHOT=
cleanup_path_update() {
  if [ -n "${BACKUP_SNAPSHOT:-}" ]; then
    rm -f "$BACKUP_SNAPSHOT"
  fi
  if [ "$LOCK_HELD" -eq 1 ] || { [ -e "$LOCK_OWNER_FILE" ] && [ -e "$LOCK" ] && [ "$LOCK_OWNER_FILE" -ef "$LOCK" ]; }; then
    rm -f "$LOCK"
  fi
  if [ -n "${LOCK_OWNER_FILE:-}" ]; then
    rm -f "$LOCK_OWNER_FILE"
  fi
}
trap cleanup_path_update EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

LOCK_ATTEMPTS=0
LOCK_MAX_ATTEMPTS=${AGENT_TOOLS_LOCK_MAX_ATTEMPTS:-100}
case "$LOCK_MAX_ATTEMPTS" in
  ''|*[!0-9]*|0) echo "AGENT_TOOLS_LOCK_MAX_ATTEMPTS must be a positive integer." >&2; exit 2 ;;
esac
while ! ln "$LOCK_OWNER_FILE" "$LOCK" 2>/dev/null; do
  LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
  if [ "$LOCK_ATTEMPTS" -ge "$LOCK_MAX_ATTEMPTS" ]; then
    LOCK_OWNER=$(cat "$LOCK" 2>/dev/null || true)
    echo "Timed out waiting for another agent-tools PATH update on $PROFILE." >&2
    echo "Lock file: $LOCK (recorded owner PID: ${LOCK_OWNER:-unknown})." >&2
    echo "If no update process owns that lock, remove the lock file manually and rerun." >&2
    exit 1
  fi
  sleep 0.1
done
LOCK_HELD=1
rm -f "$LOCK_OWNER_FILE"
LOCK_OWNER_FILE=

if [ -f "$PROFILE" ] && grep -Fx "$LINE" "$PROFILE" >/dev/null 2>&1; then
  echo "$ROOT/bin is already configured in $PROFILE"
else
  if [ -f "$PROFILE" ]; then
    BACKUP_SNAPSHOT=$(mktemp "$PROFILE.agent-tools-backup-snapshot.XXXXXX")
    cp -p "$PROFILE" "$BACKUP_SNAPSHOT"
    BACKUP_BASE="$PROFILE.agent-tools-backup-$(date -u +%Y%m%dT%H%M%SZ)"
    BACKUP="$BACKUP_BASE"
    BACKUP_SUFFIX=0
    while ! ln "$BACKUP_SNAPSHOT" "$BACKUP" 2>/dev/null; do
      BACKUP_SUFFIX=$((BACKUP_SUFFIX + 1))
      BACKUP="$BACKUP_BASE-$BACKUP_SUFFIX"
    done
    rm -f "$BACKUP_SNAPSHOT"
    BACKUP_SNAPSHOT=
    echo "Backed up $PROFILE to $BACKUP"
  fi
  printf '\n# User-level agent tools\n%s\n' "$LINE" >> "$PROFILE"
  echo "Updated $PROFILE. Start a new shell to use the wrappers."
fi
