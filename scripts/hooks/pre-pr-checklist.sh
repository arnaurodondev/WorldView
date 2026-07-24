#!/usr/bin/env bash
# pre-pr-checklist.sh — Full validation before creating a PR.
# Called by Claude Code hook: PreToolUse matcher "Bash.*gh pr create"
# Exit 0 = allow, Exit 2 = block PR creation, Exit 1 = error.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FAILED=0
WARNINGS=0

echo "═══════════════════════════════════════════════════════════════"
echo "  PRE-PR CHECKLIST VALIDATION"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── Detect all changes vs main ──────────────────────────────────────────────
BASE_BRANCH="main"
CHANGED_FILES=$(cd "$ROOT_DIR" && git diff --name-only "$BASE_BRANCH"...HEAD 2>/dev/null || git diff --name-only HEAD~1 2>/dev/null || true)
CHANGED_PY=$(echo "$CHANGED_FILES" | grep '\.py$' || true)
CHANGED_TS=$(echo "$CHANGED_FILES" | grep -E '\.(ts|tsx)$' || true)
CHANGED_AVSC=$(echo "$CHANGED_FILES" | grep '\.avsc$' || true)
CHANGED_SERVICES=$(echo "$CHANGED_FILES" | sed -n 's|^services/\([^/]*\)/.*|\1|p' | sort -u || true)
CHANGED_LIBS=$(echo "$CHANGED_FILES" | sed -n 's|^libs/\([^/]*\)/.*|\1|p' | sort -u || true)

echo "Changed files: $(echo "$CHANGED_FILES" | wc -l | tr -d ' ')"
echo "Changed services: $CHANGED_SERVICES"
echo "Changed libs: $CHANGED_LIBS"
echo ""

# ─── 1. Lint: ruff ───────────────────────────────────────────────────────────
echo "── 1/8: ruff check ───────────────────────────────────────────"
if [ -n "$CHANGED_PY" ]; then
  PY_FILES=""
  for f in $CHANGED_PY; do
    [ -f "$ROOT_DIR/$f" ] && PY_FILES="$PY_FILES $ROOT_DIR/$f"
  done
  if [ -n "$PY_FILES" ] && ! (cd "$ROOT_DIR" && ruff check $PY_FILES 2>&1); then
    echo "✗ ruff check FAILED"; FAILED=1
  else
    echo "✓ ruff check passed"
  fi
else
  echo "✓ No Python files changed — skipped"
fi

# ─── 2. Lint: ruff format ────────────────────────────────────────────────────
echo ""
echo "── 2/8: ruff format check ────────────────────────────────────"
if [ -n "$CHANGED_PY" ]; then
  PY_FILES=""
  for f in $CHANGED_PY; do
    [ -f "$ROOT_DIR/$f" ] && PY_FILES="$PY_FILES $ROOT_DIR/$f"
  done
  if [ -n "$PY_FILES" ] && ! (cd "$ROOT_DIR" && ruff format --check $PY_FILES 2>&1); then
    echo "✗ ruff format FAILED"; FAILED=1
  else
    echo "✓ ruff format passed"
  fi
else
  echo "✓ No Python files changed — skipped"
fi

# ─── 3. Type check: mypy ─────────────────────────────────────────────────────
echo ""
echo "── 3/8: mypy ─────────────────────────────────────────────────"
MYPY_TARGETS=""
for svc in $CHANGED_SERVICES; do
  [ -d "$ROOT_DIR/services/$svc/src" ] && MYPY_TARGETS="$MYPY_TARGETS $ROOT_DIR/services/$svc/src"
done
for lib in $CHANGED_LIBS; do
  [ -d "$ROOT_DIR/libs/$lib/src" ] && MYPY_TARGETS="$MYPY_TARGETS $ROOT_DIR/libs/$lib/src"
done

if [ -n "$(echo "$MYPY_TARGETS" | tr -d '[:space:]')" ]; then
  if ! (cd "$ROOT_DIR" && mypy $MYPY_TARGETS --config-file mypy.ini 2>&1); then
    echo "✗ mypy FAILED"; FAILED=1
  else
    echo "✓ mypy passed"
  fi
else
  echo "✓ No typed packages changed — skipped"
fi

# ─── 4. Unit tests for changed services/libs ─────────────────────────────────
echo ""
echo "── 4/8: unit tests ───────────────────────────────────────────"
for svc in $CHANGED_SERVICES; do
  if [ -d "$ROOT_DIR/services/$svc/tests" ]; then
    echo "  Testing: services/$svc"
    if ! (cd "$ROOT_DIR" && python -m pytest "services/$svc/tests" -m "unit" -q --tb=short 2>&1); then
      echo "  ✗ services/$svc FAILED"; FAILED=1
    else
      echo "  ✓ services/$svc passed"
    fi
  fi
done
for lib in $CHANGED_LIBS; do
  if [ -d "$ROOT_DIR/libs/$lib/tests" ]; then
    echo "  Testing: libs/$lib"
    if ! (cd "$ROOT_DIR" && python -m pytest "libs/$lib/tests" -m "unit" -q --tb=short 2>&1); then
      echo "  ✗ libs/$lib FAILED"; FAILED=1
    else
      echo "  ✓ libs/$lib passed"
    fi
  fi
done

# ─── 5. Integration tests (if applicable) ────────────────────────────────────
echo ""
echo "── 5/8: integration tests ────────────────────────────────────"
for svc in $CHANGED_SERVICES; do
  if [ -d "$ROOT_DIR/services/$svc/tests" ]; then
    HAS_INT=$(cd "$ROOT_DIR" && grep -rl "pytest.mark.integration" "services/$svc/tests/" 2>/dev/null || true)
    if [ -n "$HAS_INT" ]; then
      echo "  Integration: services/$svc"
      if ! (cd "$ROOT_DIR" && python -m pytest "services/$svc/tests" -m "integration" -q --tb=short 2>&1); then
        echo "  ⚠ services/$svc integration tests failed (non-blocking — infra may not be running)"
        WARNINGS=$((WARNINGS + 1))
      else
        echo "  ✓ services/$svc integration tests passed"
      fi
    fi
  fi
done

# ─── 6. Architecture tests ───────────────────────────────────────────────────
echo ""
echo "── 6/8: architecture tests ───────────────────────────────────"
if [ -d "$ROOT_DIR/tests/architecture" ]; then
  if ! (cd "$ROOT_DIR" && python -m pytest tests/architecture -q --tb=short 2>&1); then
    echo "✗ Architecture tests FAILED"; FAILED=1
  else
    echo "✓ Architecture tests passed"
  fi
fi

# ─── 7. Schema validation ────────────────────────────────────────────────────
echo ""
echo "── 7/8: Avro schema validation ──────────────────────────────"
if [ -n "$CHANGED_AVSC" ]; then
  if [ -x "$ROOT_DIR/scripts/gen-contracts.sh" ]; then
    if ! ("$ROOT_DIR/scripts/gen-contracts.sh" 2>&1); then
      echo "✗ Schema validation FAILED"; FAILED=1
    else
      echo "✓ Schema validation passed"
    fi
  fi
else
  echo "✓ No schema files changed — skipped"
fi

# ─── 8. Documentation freshness check ────────────────────────────────────────
echo ""
echo "── 8/8: documentation freshness ──────────────────────────────"
DOC_WARNINGS=""

# Check if API routes changed but service docs weren't updated
for svc in $CHANGED_SERVICES; do
  API_CHANGED=$(echo "$CHANGED_FILES" | grep "services/$svc/src/.*/api/" || true)
  DOC_CHANGED=$(echo "$CHANGED_FILES" | grep "docs/services/$svc" || true)
  if [ -n "$API_CHANGED" ] && [ -z "$DOC_CHANGED" ]; then
    DOC_WARNINGS="$DOC_WARNINGS\n  ⚠ services/$svc API changed but docs/services/$svc.md not updated"
    WARNINGS=$((WARNINGS + 1))
  fi
done

# Check if Kafka events changed but not documented
EVENTS_CHANGED=$(echo "$CHANGED_FILES" | grep -E "(events\.py|messaging/)" || true)
if [ -n "$EVENTS_CHANGED" ] && ! echo "$CHANGED_FILES" | grep -q "docs/"; then
  DOC_WARNINGS="$DOC_WARNINGS\n  ⚠ Event/messaging code changed but no docs updated"
  WARNINGS=$((WARNINGS + 1))
fi

# Check if env config changed
ENV_CHANGED=$(echo "$CHANGED_FILES" | grep -E "config/" || true)
ENV_EXAMPLE_CHANGED=$(echo "$CHANGED_FILES" | grep "dev.local.env.example" || true)
if [ -n "$ENV_CHANGED" ] && [ -z "$ENV_EXAMPLE_CHANGED" ]; then
  DOC_WARNINGS="$DOC_WARNINGS\n  ⚠ Config files changed but dev.local.env.example not updated"
  WARNINGS=$((WARNINGS + 1))
fi

if [ -n "$DOC_WARNINGS" ]; then
  echo -e "$DOC_WARNINGS"
else
  echo "✓ Documentation appears up to date"
fi

# ─── 9. Security quick-scan ──────────────────────────────────────────────────
echo ""
echo "── Bonus: security quick-scan ────────────────────────────────"
SEC_ISSUES=""
for f in $CHANGED_PY; do
  full_path="$ROOT_DIR/$f"
  [ ! -f "$full_path" ] && continue

  # Check for hardcoded secrets patterns
  if grep -nE '(password|secret|token|api_key)\s*=\s*["\x27][^"\x27]{8,}' "$full_path" 2>/dev/null | grep -v "example\|test\|mock\|fake\|dummy" > /dev/null 2>&1; then
    SEC_ISSUES="$SEC_ISSUES\n  ⚠ Possible hardcoded secret in $f"
  fi

  # Check for eval/exec usage
  if grep -nE '\b(eval|exec)\s*\(' "$full_path" 2>/dev/null | grep -v "test_\|#.*eval" > /dev/null 2>&1; then
    SEC_ISSUES="$SEC_ISSUES\n  ⚠ eval/exec usage in $f"
  fi

  # Check for SQL injection patterns
  if grep -nE 'f["\x27].*SELECT|f["\x27].*INSERT|f["\x27].*UPDATE|f["\x27].*DELETE' "$full_path" 2>/dev/null > /dev/null 2>&1; then
    SEC_ISSUES="$SEC_ISSUES\n  ⚠ Possible SQL injection (f-string SQL) in $f"
  fi
done

if [ -n "$SEC_ISSUES" ]; then
  echo -e "$SEC_ISSUES"
  WARNINGS=$((WARNINGS + ${#SEC_ISSUES}))
else
  echo "✓ No obvious security issues detected"
fi

# ─── 10. tool_use.py prompt-version live-eval-artifact gate ──────────────────
# 2026-07-23 bottleneck audit, Recurrence B / BP-735 / HR-065 /
# REVIEW_CHECKLIST.md:117 — mechanically enforces (rather than merely
# advises) that any TOOL_USE_SYSTEM_PROMPT_TEMPLATE version bump carries a
# live-eval artifact. Checked over the WHOLE PR range ($BASE_BRANCH...HEAD),
# complementing the per-commit check already wired into
# pre-commit-validate.sh (a PR could otherwise bump the version in a commit
# made before that gate existed, or via a rebase/cherry-pick that skipped
# the per-commit hook). See scripts/hooks/check_tool_use_prompt_eval_artifact.py.
echo ""
echo "── 10/10: tool_use.py prompt-version eval-artifact gate ───────"
if GATE_OUTPUT=$(cd "$ROOT_DIR" && TOOL_USE_EVAL_GATE_DIFF_RANGE="$BASE_BRANCH...HEAD" \
    python3 scripts/hooks/check_tool_use_prompt_eval_artifact.py 2>&1); then
  echo "✓ tool_use.py eval-artifact gate passed"
else
  echo "✗ tool_use.py eval-artifact gate FAILED"
  echo "$GATE_OUTPUT"
  FAILED=1
fi

# ─── Result ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ $FAILED -ne 0 ]; then
  echo "  ✗ PRE-PR CHECKLIST FAILED — PR creation blocked"
  echo "  Fix the failures above before creating a PR."
  [ $WARNINGS -gt 0 ] && echo "  Also address $WARNINGS warning(s)."
  echo "═══════════════════════════════════════════════════════════════"
  exit 2
fi

if [ $WARNINGS -gt 0 ]; then
  echo "  ⚠ PRE-PR CHECKLIST PASSED with $WARNINGS warning(s)"
  echo "  Review warnings above — they may indicate missing updates."
  echo "═══════════════════════════════════════════════════════════════"
  exit 0
fi

echo "  ✓ PRE-PR CHECKLIST PASSED — all checks green"
echo "═══════════════════════════════════════════════════════════════"
exit 0
