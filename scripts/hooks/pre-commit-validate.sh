#!/usr/bin/env bash
# pre-commit-validate.sh — Runs ruff, mypy, and tests on changed files before commit.
# Called by Claude Code hook: PreToolUse matcher "Bash.*git commit"
#
# Output protocol (structured hook JSON):
#   stdout → JSON: {"rejection": "..."} on failure, or empty on success
#   stderr → human-readable validation output
#   exit 0 = allow commit
#   exit 2 = block commit (Claude Code reads the JSON rejection from stdout)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FAILED=0
FAILURE_REASONS=()   # accumulates structured failure messages

# Helper: emit human-readable output to stderr (keeps stdout clean for JSON)
info() { echo "$@" >&2; }

# ─── Detect changed files ────────────────────────────────────────────────────
STAGED_FILES=$(cd "$ROOT_DIR" && git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
UNSTAGED_FILES=$(cd "$ROOT_DIR" && git diff --name-only --diff-filter=ACMR 2>/dev/null || true)
ALL_CHANGED="$STAGED_FILES"$'\n'"$UNSTAGED_FILES"

if [ -z "$(echo "$ALL_CHANGED" | tr -d '[:space:]')" ]; then
  info "✓ No changed files detected — skipping pre-commit validation."
  exit 0
fi

# ─── Identify changed Python files ───────────────────────────────────────────
CHANGED_PY=$(echo "$ALL_CHANGED" | grep '\.py$' | sort -u || true)

if [ -z "$CHANGED_PY" ]; then
  info "✓ No Python files changed — skipping Python validation."
  exit 0
fi

info "═══════════════════════════════════════════════════════════════"
info "  PRE-COMMIT VALIDATION"
info "═══════════════════════════════════════════════════════════════"
info ""

# ─── 1. Ruff check on changed files ──────────────────────────────────────────
info "── Step 1/4: ruff check ──────────────────────────────────────"
RUFF_FILES=""
for f in $CHANGED_PY; do
  full_path="$ROOT_DIR/$f"
  if [ -f "$full_path" ]; then
    RUFF_FILES="$RUFF_FILES $full_path"
  fi
done

if [ -n "$RUFF_FILES" ]; then
  RUFF_OUTPUT=""
  # shellcheck disable=SC2086
  if RUFF_OUTPUT=$(cd "$ROOT_DIR" && ruff check $RUFF_FILES 2>&1); then
    info "✓ ruff check passed"
  else
    info "✗ ruff check FAILED"
    info "$RUFF_OUTPUT"
    # Build structured failure with fix command
    FIX_FILES=$(echo "$RUFF_FILES" | tr ' ' '\n' | head -3 | tr '\n' ' ')
    FAILURE_REASONS+=("ruff check failed. Fix with: cd $ROOT_DIR && uvx ruff check --fix $FIX_FILES && uvx ruff format $FIX_FILES")
    FAILED=1
  fi
fi

# ─── 2. mypy on changed packages ─────────────────────────────────────────────
info ""
info "── Step 2/4: mypy ────────────────────────────────────────────"
MYPY_TARGETS=""
for f in $CHANGED_PY; do
  pkg=$(echo "$f" | sed -n 's|^\(libs/[^/]*/src\)/.*|\1|p; s|^\(services/[^/]*/src\)/.*|\1|p')
  if [ -n "$pkg" ]; then
    MYPY_TARGETS="$MYPY_TARGETS $ROOT_DIR/$pkg"
  fi
done
MYPY_TARGETS=$(echo "$MYPY_TARGETS" | tr ' ' '\n' | sort -u | tr '\n' ' ')

if [ -n "$(echo "$MYPY_TARGETS" | tr -d '[:space:]')" ]; then
  MYPY_OUTPUT=""
  # shellcheck disable=SC2086
  if MYPY_OUTPUT=$(cd "$ROOT_DIR" && mypy $MYPY_TARGETS --config-file mypy.ini 2>&1); then
    info "✓ mypy passed"
  else
    info "✗ mypy FAILED"
    info "$MYPY_OUTPUT"
    FIRST_ERROR=$(echo "$MYPY_OUTPUT" | grep '^.*error:' | head -3 | tr '\n' '; ')
    FAILURE_REASONS+=("mypy type errors: $FIRST_ERROR Fix with: cd $ROOT_DIR && mypy $MYPY_TARGETS --config-file mypy.ini")
    FAILED=1
  fi
else
  info "✓ No typed packages changed — skipping mypy"
fi

# ─── 3. Import guards on changed service files ───────────────────────────────
info ""
info "── Step 3/4: import guards ─────────────────────────────────────"
SVC_CHANGED=$(echo "$CHANGED_PY" | grep '^services/' || true)
if [ -n "$SVC_CHANGED" ]; then
  GUARD_SERVICES=$(echo "$SVC_CHANGED" | sed -n 's|^services/\([^/]*\)/.*|\1|p' | sort -u | paste -sd, -)
  GUARD_OUTPUT=""
  if GUARD_OUTPUT=$(cd "$ROOT_DIR" && python3 scripts/import_guards/check_import_guards.py \
      --strict --baseline scripts/import_guards/baseline.json \
      --services "$GUARD_SERVICES" 2>&1); then
    info "✓ import guards passed"
  else
    info "✗ import guards FAILED"
    info "$GUARD_OUTPUT"
    VIOLATION=$(echo "$GUARD_OUTPUT" | grep -i 'violation\|forbidden\|error' | head -2 | tr '\n' '; ')
    FAILURE_REASONS+=("import guard violations in $GUARD_SERVICES: $VIOLATION See RULES.md R25 — API layer must not import from infrastructure/.")
    FAILED=1
  fi
else
  info "✓ No service files changed — skipping import guards"
fi

# ─── 4. Run tests for changed services/libs ──────────────────────────────────
info ""
info "── Step 4/4: pytest (unit tests) ─────────────────────────────"
TEST_DIRS=""
for f in $CHANGED_PY; do
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
    svc_name=$(basename "$(dirname "$tdir")")
    info "  Testing: $svc_name"
    TEST_OUTPUT=""
    if TEST_OUTPUT=$(cd "$ROOT_DIR" && python -m pytest "$tdir" -m "unit" -q --tb=short 2>&1); then
      info "  ✓ $svc_name tests passed"
    else
      info "  ✗ $svc_name tests FAILED"
      info "$TEST_OUTPUT"
      FIRST_FAIL=$(echo "$TEST_OUTPUT" | grep -E '^FAILED|AssertionError|Error' | head -2 | tr '\n' '; ')
      FAILURE_REASONS+=("pytest unit tests failed in $svc_name: $FIRST_FAIL Fix: cd $ROOT_DIR && python -m pytest $tdir -m unit -v --tb=long")
      FAILED=1
    fi
  done
else
  info "✓ No testable packages changed — skipping pytest"
fi

# ─── Result ───────────────────────────────────────────────────────────────────
info ""
info "═══════════════════════════════════════════════════════════════"
if [ $FAILED -ne 0 ]; then
  info "  ✗ PRE-COMMIT VALIDATION FAILED — commit blocked"
  info "═══════════════════════════════════════════════════════════════"

  # Build structured JSON rejection for Claude Code (stdout only)
  REASON_STR=""
  for reason in "${FAILURE_REASONS[@]+"${FAILURE_REASONS[@]}"}"; do
    if [ -n "$REASON_STR" ]; then
      REASON_STR="$REASON_STR | "
    fi
    REASON_STR="$REASON_STR$reason"
  done
  # Escape for JSON: replace backslashes, double quotes, newlines
  REASON_JSON=$(printf '%s' "$REASON_STR" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
  printf '{"rejection":%s}\n' "$REASON_JSON"
  exit 2
fi

info "  ✓ PRE-COMMIT VALIDATION PASSED"
info "═══════════════════════════════════════════════════════════════"
exit 0
