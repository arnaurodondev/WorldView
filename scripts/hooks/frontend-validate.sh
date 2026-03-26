#!/usr/bin/env bash
# frontend-validate.sh — After TypeScript/TSX file edits, run lint + typecheck + tests.
# Called by Claude Code hook: PostToolUse matcher "Edit.*\.(ts|tsx)$"
# Exit 0 always (informational).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/apps/frontend"

if [ ! -d "$FRONTEND_DIR" ]; then
  exit 0
fi

# Check if pnpm is available
if ! command -v pnpm &>/dev/null; then
  echo "⚠ pnpm not found — skipping frontend validation"
  exit 0
fi

echo "── Frontend validation ─────────────────────────────────────"

# 1. ESLint
echo "  Lint check..."
if (cd "$FRONTEND_DIR" && pnpm lint 2>&1); then
  echo "  ✓ ESLint passed"
else
  echo "  ⚠ ESLint issues found"
fi

# 2. TypeScript type check
echo "  Type check..."
if (cd "$FRONTEND_DIR" && pnpm typecheck 2>&1); then
  echo "  ✓ TypeScript passed"
else
  echo "  ⚠ TypeScript errors found — fix before continuing"
fi

# 3. Unit tests
echo "  Unit tests..."
if (cd "$FRONTEND_DIR" && pnpm test --run 2>&1); then
  echo "  ✓ Unit tests passed"
else
  echo "  ⚠ Unit test failures — review before continuing"
fi

echo "── Frontend validation complete ─────────────────────────────"
exit 0
