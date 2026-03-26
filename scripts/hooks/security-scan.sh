#!/usr/bin/env bash
# security-scan.sh — Scans changed Python files for common security issues.
# Called by Claude Code hook: PostToolUse matcher "Edit.*\.py$" (alongside post-edit)
# Exit 0 always (informational — flags issues for agent review).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# ─── Detect changed Python files ─────────────────────────────────────────────
CHANGED_PY=$(cd "$ROOT_DIR" && git diff --name-only 2>/dev/null | grep '\.py$' || true)

if [ -z "$CHANGED_PY" ]; then
  exit 0
fi

ISSUES=0

for f in $CHANGED_PY; do
  full_path="$ROOT_DIR/$f"
  [ ! -f "$full_path" ] && continue

  # Skip test files for most checks
  IS_TEST=0
  echo "$f" | grep -qE '(tests/|test_|_test\.py)' && IS_TEST=1

  FILE_ISSUES=""

  # ── 1. Hardcoded secrets ──
  if [ $IS_TEST -eq 0 ]; then
    SECRETS=$(grep -nE '(password|secret|api_key|token|private_key)\s*=\s*["\x27][A-Za-z0-9+/=_-]{12,}' "$full_path" 2>/dev/null | grep -v '#.*\|example\|test\|mock\|fake\|dummy\|placeholder\|TODO\|FIXME' || true)
    if [ -n "$SECRETS" ]; then
      FILE_ISSUES="$FILE_ISSUES\n    CRITICAL: Possible hardcoded secret\n$SECRETS"
    fi
  fi

  # ── 2. SQL injection via f-strings ──
  SQL_INJECT=$(grep -nE 'f["\x27].*\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b' "$full_path" 2>/dev/null || true)
  if [ -n "$SQL_INJECT" ]; then
    FILE_ISSUES="$FILE_ISSUES\n    HIGH: Possible SQL injection (use parameterized queries)\n$SQL_INJECT"
  fi

  # ── 3. eval/exec usage ──
  if [ $IS_TEST -eq 0 ]; then
    EVAL_USE=$(grep -nE '\b(eval|exec)\s*\(' "$full_path" 2>/dev/null | grep -v '#' || true)
    if [ -n "$EVAL_USE" ]; then
      FILE_ISSUES="$FILE_ISSUES\n    HIGH: eval/exec usage (code injection risk)\n$EVAL_USE"
    fi
  fi

  # ── 4. Subprocess shell=True ──
  SHELL_TRUE=$(grep -nE 'subprocess\.(run|call|Popen|check_output)\(.*shell\s*=\s*True' "$full_path" 2>/dev/null || true)
  if [ -n "$SHELL_TRUE" ]; then
    FILE_ISSUES="$FILE_ISSUES\n    HIGH: subprocess with shell=True (command injection risk)\n$SHELL_TRUE"
  fi

  # ── 5. Pickle deserialization ──
  PICKLE_USE=$(grep -nE 'pickle\.(load|loads)\(' "$full_path" 2>/dev/null || true)
  if [ -n "$PICKLE_USE" ]; then
    FILE_ISSUES="$FILE_ISSUES\n    MEDIUM: pickle deserialization (arbitrary code execution risk)\n$PICKLE_USE"
  fi

  # ── 6. Insecure random for security ──
  if [ $IS_TEST -eq 0 ]; then
    INSECURE_RAND=$(grep -nE 'import random\b|random\.(choice|randint|sample)' "$full_path" 2>/dev/null | grep -iv 'secrets\|test' || true)
    if [ -n "$INSECURE_RAND" ]; then
      # Check if it's used in security context
      SEC_CONTEXT=$(grep -nE '(token|secret|key|password|nonce|salt).*random\.' "$full_path" 2>/dev/null || true)
      if [ -n "$SEC_CONTEXT" ]; then
        FILE_ISSUES="$FILE_ISSUES\n    MEDIUM: Insecure random in security context (use secrets module)\n$SEC_CONTEXT"
      fi
    fi
  fi

  # ── 7. Logging secrets ──
  if [ $IS_TEST -eq 0 ]; then
    LOG_SECRETS=$(grep -nE 'log(ger)?\.(info|debug|warning|error|critical).*\b(password|secret|token|api_key|private_key)\b' "$full_path" 2>/dev/null || true)
    if [ -n "$LOG_SECRETS" ]; then
      FILE_ISSUES="$FILE_ISSUES\n    MEDIUM: Possible secret logging\n$LOG_SECRETS"
    fi
  fi

  # ── 8. Naive datetime (without timezone) ──
  if [ $IS_TEST -eq 0 ]; then
    NAIVE_DT=$(grep -nE 'datetime\.now\(\s*\)|datetime\.utcnow\(\)' "$full_path" 2>/dev/null || true)
    if [ -n "$NAIVE_DT" ]; then
      FILE_ISSUES="$FILE_ISSUES\n    LOW: Naive datetime — use datetime.now(tz=timezone.utc) or libs/common helpers\n$NAIVE_DT"
    fi
  fi

  # ── 9. Direct stdlib logging (should use structlog) ──
  if [ $IS_TEST -eq 0 ]; then
    STDLIB_LOG=$(grep -nE '^import logging$|^from logging import|logging\.getLogger' "$full_path" 2>/dev/null || true)
    if [ -n "$STDLIB_LOG" ]; then
      FILE_ISSUES="$FILE_ISSUES\n    LOW: stdlib logging — use structlog (per RULES.md)\n$STDLIB_LOG"
    fi
  fi

  # Report issues for this file
  if [ -n "$FILE_ISSUES" ]; then
    echo "  ── $f ──"
    echo -e "$FILE_ISSUES"
    echo ""
    ISSUES=$((ISSUES + 1))
  fi
done

if [ $ISSUES -gt 0 ]; then
  echo "── Security scan: $ISSUES file(s) with issues ──────────────"
  echo "Review the issues above. CRITICAL and HIGH issues should be fixed before committing."
else
  echo "── Security scan: clean ────────────────────────────────────"
fi

exit 0
