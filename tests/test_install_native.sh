#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT HUP INT TERM
TEST_BIN="$TEST_ROOT/bin"
LOG="$TEST_ROOT/commands.log"
mkdir -p "$TEST_BIN"

cat > "$TEST_BIN/id" <<'EOF'
#!/bin/sh
echo 0
EOF
cat > "$TEST_BIN/apt-get" <<'EOF'
#!/bin/sh
echo "$*" >> "$AGENT_TOOLS_TEST_LOG"
EOF
chmod +x "$TEST_BIN/id" "$TEST_BIN/apt-get"

AGENT_TOOLS_TEST_LOG="$LOG" PATH="$TEST_BIN" /bin/sh "$ROOT/scripts/install-native.sh"
[ "$(sed -n '1p' "$LOG")" = 'update' ]
[ "$(sed -n '2p' "$LOG")" = 'install -y poppler-utils ghostscript' ]

cat > "$TEST_BIN/id" <<'EOF'
#!/bin/sh
echo 1000
EOF
if AGENT_TOOLS_TEST_LOG="$LOG" PATH="$TEST_BIN" /bin/sh "$ROOT/scripts/install-native.sh" 2>/dev/null; then
  echo 'Expected non-root installation without sudo to fail.' >&2
  exit 1
fi
