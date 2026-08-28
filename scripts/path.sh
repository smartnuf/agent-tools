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
LOCK_ATTEMPTS=0
while ! mkdir "$LOCK" 2>/dev/null; do
  if [ -f "$LOCK/pid" ]; then
    LOCK_OWNER=$(cat "$LOCK/pid" 2>/dev/null || true)
    case "$LOCK_OWNER" in
      ''|*[!0-9]*) ;;
      *)
        if ! kill -0 "$LOCK_OWNER" 2>/dev/null; then
          rm -f "$LOCK/pid"
          rmdir "$LOCK" 2>/dev/null || true
          continue
        fi
        ;;
    esac
  fi
  LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
  if [ "$LOCK_ATTEMPTS" -ge 100 ]; then
    echo "Timed out waiting for another agent-tools PATH update on $PROFILE" >&2
    exit 1
  fi
  sleep 0.1
done
printf '%s\n' "$$" > "$LOCK/pid"
BACKUP_SNAPSHOT=
cleanup_path_update() {
  if [ -n "${BACKUP_SNAPSHOT:-}" ]; then
    rm -f "$BACKUP_SNAPSHOT"
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup_path_update EXIT HUP INT TERM

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
