#!/usr/bin/env bash
# pre-commit-validate.sh — Runs ruff, mypy, and tests on changed files before commit.
# Called by Claude Code hook: PreToolUse matcher "Bash.*git commit"
# Exit 0 = allow, Exit 2 = block commit, Exit 1 = error (shown to agent)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FAILED=0

# ─── Detect changed files ────────────────────────────────────────────────────
STAGED_FILES=$(cd "$ROOT_DIR" && git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
UNSTAGED_FILES=$(cd "$ROOT_DIR" && git diff --name-only --diff-filter=ACMR 2>/dev/null || true)
ALL_CHANGED="$STAGED_FILES"$'\n'"$UNSTAGED_FILES"

if [ -z "$(echo "$ALL_CHANGED" | tr -d '[:space:]')" ]; then
  echo "✓ No changed files detected — skipping pre-commit validation."
  exit 0
fi

# ─── Identify changed Python files ───────────────────────────────────────────
CHANGED_PY=$(echo "$ALL_CHANGED" | grep '\.py$' | sort -u || true)

if [ -z "$CHANGED_PY" ]; then
  echo "✓ No Python files changed — skipping Python validation."
  exit 0
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  PRE-COMMIT VALIDATION"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── 1. Ruff check on changed files ──────────────────────────────────────────
echo "── Step 1/3: ruff check ──────────────────────────────────────"
RUFF_FILES=""
for f in $CHANGED_PY; do
  full_path="$ROOT_DIR/$f"
  if [ -f "$full_path" ]; then
    RUFF_FILES="$RUFF_FILES $full_path"
  fi
done

if [ -n "$RUFF_FILES" ]; then
  if (cd "$ROOT_DIR" && ruff check $RUFF_FILES 2>&1); then
    echo "✓ ruff check passed"
  else
    echo "✗ ruff check FAILED — fix lint errors before committing"
    FAILED=1
  fi
fi

# ─── 2. mypy on changed packages ─────────────────────────────────────────────
echo ""
echo "── Step 2/3: mypy ────────────────────────────────────────────"
MYPY_TARGETS=""
for f in $CHANGED_PY; do
  # Extract package: libs/<name>/src or services/<name>/src
  pkg=$(echo "$f" | sed -n 's|^\(libs/[^/]*/src\)/.*|\1|p; s|^\(services/[^/]*/src\)/.*|\1|p')
  if [ -n "$pkg" ]; then
    MYPY_TARGETS="$MYPY_TARGETS $ROOT_DIR/$pkg"
  fi
done
MYPY_TARGETS=$(echo "$MYPY_TARGETS" | tr ' ' '\n' | sort -u | tr '\n' ' ')

if [ -n "$(echo "$MYPY_TARGETS" | tr -d '[:space:]')" ]; then
  if (cd "$ROOT_DIR" && mypy $MYPY_TARGETS --config-file mypy.ini 2>&1); then
    echo "✓ mypy passed"
  else
    echo "✗ mypy FAILED — fix type errors before committing"
    FAILED=1
  fi
else
  echo "✓ No typed packages changed — skipping mypy"
fi

# ─── 3. Run tests for changed services/libs ──────────────────────────────────
echo ""
echo "── Step 3/3: pytest (unit tests) ─────────────────────────────"
TEST_DIRS=""
for f in $CHANGED_PY; do
  # Extract test directory: services/<name>/tests or libs/<name>/tests
  svc=$(echo "$f" | sed -n 's|^\(services/[^/]*\)/.*|\1|p')
  lib=$(echo "$f" | sed -n 's|^\(libs/[^/]*\)/.*|\1|p')
  if [ -n "$svc" ] && [ -d "$ROOT_DIR/$svc/tests" ]; then
    TEST_DIRS="$TEST_DIRS $ROOT_DIR/$svc/tests"
  elif [ -n "$lib" ] && [ -d "$ROOT_DIR/$lib/tests" ]; then
    TEST_DIRS="$TEST_DIRS $ROOT_DIR/$lib/tests"
  fi
done
TEST_DIRS=$(echo "$TEST_DIRS" | tr ' ' '\n' | sort -u | tr '\n' ' ')

if [ -n "$(echo "$TEST_DIRS" | tr -d '[:space:]')" ]; then
  for tdir in $TEST_DIRS; do
    svc_name=$(echo "$tdir" | sed 's|.*/\(services\|libs\)/\([^/]*\)/tests|\2|')
    echo "  Testing: $svc_name"
    if (cd "$ROOT_DIR" && python -m pytest "$tdir" -m "unit" -q --tb=short 2>&1); then
      echo "  ✓ $svc_name tests passed"
    else
      echo "  ✗ $svc_name tests FAILED"
      FAILED=1
    fi
  done
else
  echo "✓ No testable packages changed — skipping pytest"
fi

# ─── Result ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ $FAILED -ne 0 ]; then
  echo "  ✗ PRE-COMMIT VALIDATION FAILED — commit blocked"
  echo "  Fix the issues above before committing."
  echo "═══════════════════════════════════════════════════════════════"
  exit 2
fi

echo "  ✓ PRE-COMMIT VALIDATION PASSED"
echo "═══════════════════════════════════════════════════════════════"
exit 0
