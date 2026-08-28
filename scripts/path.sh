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
    BACKUP_BASE="$PROFILE.agent-tools-backup-$(date -u +%Y%m%dT%H%M%SZ)"
    BACKUP="$BACKUP_BASE"
    BACKUP_SUFFIX=0
    while [ -e "$BACKUP" ]; do
      BACKUP_SUFFIX=$((BACKUP_SUFFIX + 1))
      BACKUP="$BACKUP_BASE-$BACKUP_SUFFIX"
    done
    cp -p "$PROFILE" "$BACKUP"
    echo "Backed up $PROFILE to $BACKUP"
  fi
  printf '\n# User-level agent tools\n%s\n' "$LINE" >> "$PROFILE"
  echo "Updated $PROFILE. Start a new shell to use the wrappers."
fi
