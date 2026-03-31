#!/usr/bin/env bash
# scripts/run-unit-tests.sh [<service-dir>]
#
# Run unit + contract tests for all services (or a single one if given).
# Uses the same Python-detection logic as test-full.sh: per-service .venv if
# present, otherwise the activated venv or python3.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Python detection (mirrors test-full.sh) ──────────────────────────────────
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi
if [[ -z "$PYTHON" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON="${VIRTUAL_ENV}/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
  for _py in python3.12 python3 python; do
    if command -v "$_py" &>/dev/null; then
      PYTHON="$_py"
      break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: No Python found. Activate a venv or set PYTHON=..." >&2
  exit 1
fi

# ── Run function ──────────────────────────────────────────────────────────────

run_service_unit() {
  local svc_dir="$1"
  local svc
  svc="$(basename "$svc_dir")"

  [[ -d "$svc_dir/tests" ]] || return 0

  local py="$PYTHON"
  if [[ -x "$svc_dir/.venv/bin/python" ]]; then
    py="$svc_dir/.venv/bin/python"
  fi

  echo "=== $svc ==="
  local rc=0
  (cd "$svc_dir" && "$py" -m pytest tests/ \
    -m "not integration and not e2e and not live" \
    --ignore tests/integration --ignore tests/e2e --ignore tests/live \
    --tb=short -q 2>&1) || rc=$?
  # rc=5 means "no tests collected" — acceptable for services with only integration tests
  if [[ $rc -ne 0 && $rc -ne 5 ]]; then
    return $rc
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

if [[ $# -ge 1 ]]; then
  # Single service
  run_service_unit "$1"
else
  # All services
  failed=""
  for svc_dir in "$ROOT_DIR"/services/*/; do
    run_service_unit "$svc_dir" || failed="$failed $(basename "$svc_dir")"
  done
  if [[ -n "$failed" ]]; then
    echo ""
    echo "FAILED services:$failed"
    exit 1
  fi
  echo ""
  echo "All service unit tests passed."
fi
