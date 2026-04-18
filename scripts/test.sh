#!/usr/bin/env bash
# scripts/test.sh — Unified test entry point for the worldview platform.
#
# QUICK REFERENCE:
#   ./scripts/test.sh                         # Python unit tests (libs + services)
#   ./scripts/test.sh --integration           # Python unit + integration tests
#   ./scripts/test.sh --all                   # All Python markers (no filter)
#   ./scripts/test.sh --frontend unit         # worldview-web ONLY: Vitest + typecheck
#   ./scripts/test.sh --frontend e2e          # worldview-web ONLY: Playwright e2e
#   ./scripts/test.sh --frontend all          # worldview-web ONLY: unit + e2e
#   ./scripts/test.sh --frontend unit --python # Python unit + frontend unit
#   ./scripts/test.sh --full                  # All Python + all frontend
#
# For Docker-backed integration / e2e with infra:
#   ./scripts/test-full.sh               # Complete suite with compose infra
#   ./scripts/test-libs.sh --integration # Lib integration tests (MinIO)
#
# See docs/testing/RUNBOOK.md for the complete testing guide.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

MARKER="unit"
FRONTEND_MODE=""   # "unit" | "e2e" | "all" | "" (skip)
RUN_PYTHON=true    # false when --frontend is the ONLY flag (no --python/--full)
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --integration)
            MARKER="unit or integration"
            shift
            ;;
        --all)
            MARKER=""
            shift
            ;;
        --frontend)
            # --frontend [unit|e2e|all]: run frontend tests ONLY (skip Python)
            # Combine with --python to run both layers.
            FRONTEND_MODE="${2:-unit}"
            RUN_PYTHON=false   # --frontend alone = frontend only
            shift
            [[ $# -gt 0 && "$1" =~ ^(unit|e2e|all)$ ]] && shift || true
            ;;
        --python)
            # Explicit Python flag — combine with --frontend for both layers
            RUN_PYTHON=true
            shift
            ;;
        --full)
            # Run everything: all Python markers + all frontend layers
            MARKER=""
            FRONTEND_MODE="all"
            RUN_PYTHON=true
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "=== Running tests (python: $RUN_PYTHON, marker: ${MARKER:-all}, frontend: ${FRONTEND_MODE:-skip}) ==="

FAILED=0

# ── Python: Shared libraries ──────────────────────────────────────────────────
if [[ "$RUN_PYTHON" == "true" ]]; then
    for LIB_DIR in "$ROOT_DIR"/libs/*/; do
        if [[ -d "$LIB_DIR/tests" ]]; then
            LIB_NAME=$(basename "$LIB_DIR")
            echo "--- lib: $LIB_NAME ---"
            if [[ -n "$MARKER" ]]; then
                pytest "$LIB_DIR/tests" -m "$MARKER" -q ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
            else
                pytest "$LIB_DIR/tests" -q ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
            fi
        fi
    done

    # ── Python: Microservices ─────────────────────────────────────────────────
    for SVC_DIR in "$ROOT_DIR"/services/*/; do
        if [[ -d "$SVC_DIR/tests" ]]; then
            SVC_NAME=$(basename "$SVC_DIR")
            echo "--- service: $SVC_NAME ---"
            if [[ -n "$MARKER" ]]; then
                pytest "$SVC_DIR/tests" -m "$MARKER" -q ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
            else
                pytest "$SVC_DIR/tests" -q ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
            fi
        fi
    done
fi

# ── Frontend: worldview-web (Next.js 15) ──────────────────────────────────────
# WHY apps/worldview-web (not apps/frontend): worldview-web is the canonical
# production frontend (PLAN-0028). apps/frontend is the legacy Vite app
# being phased out; its tests are no longer part of CI.
if [[ -n "$FRONTEND_MODE" ]]; then
    if ! command -v pnpm &>/dev/null; then
        echo "ERROR: pnpm not found. Install pnpm@10.33.0 to run frontend tests." >&2
        FAILED=1
    elif [[ ! -d "$ROOT_DIR/apps/worldview-web" ]]; then
        echo "ERROR: apps/worldview-web not found." >&2
        FAILED=1
    else
        cd "$ROOT_DIR/apps/worldview-web"

        if [[ "$FRONTEND_MODE" == "unit" || "$FRONTEND_MODE" == "all" ]]; then
            echo "--- worldview-web: typecheck ---"
            pnpm typecheck || FAILED=1

            echo "--- worldview-web: vitest unit ---"
            pnpm test || FAILED=1
        fi

        if [[ "$FRONTEND_MODE" == "e2e" || "$FRONTEND_MODE" == "all" ]]; then
            echo "--- worldview-web: playwright e2e ---"
            # WHY --reporter=list: cleaner output than the default HTML reporter
            # for CI/terminal use. HTML report is still written to playwright-report/.
            pnpm test:e2e --reporter=list || FAILED=1
        fi

        cd "$ROOT_DIR"
    fi
fi

if [[ $FAILED -ne 0 ]]; then
    echo "=== Tests FAILED ==="
    exit 1
fi

echo "=== All tests passed ==="
