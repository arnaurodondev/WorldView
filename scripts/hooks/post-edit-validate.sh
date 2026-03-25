#!/usr/bin/env bash
# post-edit-validate.sh — After a Python file is edited, run targeted tests.
# Called by Claude Code hook: PostToolUse matcher "Edit.*\.py$"
# Reads TOOL_INPUT env var to determine which file was edited.
# Exit 0 = success (informational), non-zero = warning shown to agent.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# ─── Parse edited file from hook context ──────────────────────────────────────
# The hook receives the tool input as JSON via stdin or env
EDITED_FILE="${CLAUDE_TOOL_INPUT_FILE_PATH:-}"

if [ -z "$EDITED_FILE" ]; then
  # Try to extract from TOOL_INPUT JSON if available
  if [ -n "${TOOL_INPUT:-}" ]; then
    EDITED_FILE=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('file_path',''))" 2>/dev/null || true)
  fi
fi

# If we can't determine the file, skip silently
if [ -z "$EDITED_FILE" ] || [[ ! "$EDITED_FILE" == *.py ]]; then
  exit 0
fi

# ─── Determine the service or lib being edited ───────────────────────────────
REL_PATH="${EDITED_FILE#$ROOT_DIR/}"

# Extract service or lib name
SVC=$(echo "$REL_PATH" | sed -n 's|^services/\([^/]*\)/.*|\1|p')
LIB=$(echo "$REL_PATH" | sed -n 's|^libs/\([^/]*\)/.*|\1|p')

TARGET=""
TARGET_NAME=""
if [ -n "$SVC" ] && [ -d "$ROOT_DIR/services/$SVC/tests" ]; then
  TARGET="$ROOT_DIR/services/$SVC/tests"
  TARGET_NAME="services/$SVC"
elif [ -n "$LIB" ] && [ -d "$ROOT_DIR/libs/$LIB/tests" ]; then
  TARGET="$ROOT_DIR/libs/$LIB/tests"
  TARGET_NAME="libs/$LIB"
fi

if [ -z "$TARGET" ]; then
  exit 0
fi

# ─── Run targeted ruff check ─────────────────────────────────────────────────
echo "── Post-edit: ruff check $REL_PATH ──"
if ! (cd "$ROOT_DIR" && ruff check "$EDITED_FILE" 2>&1); then
  echo "⚠ ruff issues detected in $REL_PATH — fix before continuing"
fi

# ─── Run targeted unit tests ─────────────────────────────────────────────────
echo "── Post-edit: pytest $TARGET_NAME (unit) ──"
if (cd "$ROOT_DIR" && python -m pytest "$TARGET" -m "unit" -q --tb=line -x 2>&1); then
  echo "✓ $TARGET_NAME unit tests passed"
else
  echo "⚠ $TARGET_NAME unit tests have failures — review before continuing"
fi

exit 0
