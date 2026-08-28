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
if [ -f "$PROFILE" ] && grep -Fx "$LINE" "$PROFILE" >/dev/null 2>&1; then
  echo "$ROOT/bin is already configured in $PROFILE"
else
  if [ -f "$PROFILE" ]; then
    BACKUP_SNAPSHOT=$(mktemp "$PROFILE.agent-tools-backup-snapshot.XXXXXX")
    cleanup_backup_snapshot() {
      if [ -n "${BACKUP_SNAPSHOT:-}" ]; then
        rm -f "$BACKUP_SNAPSHOT"
      fi
    }
    trap cleanup_backup_snapshot EXIT HUP INT TERM
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
