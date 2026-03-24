#!/usr/bin/env bash
# Run tests across all packages.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

MARKER="unit"
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
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "=== Running tests (marker: ${MARKER:-all}) ==="

FAILED=0

# Libs
for LIB_DIR in "$ROOT_DIR"/libs/*/; do
    if [[ -d "$LIB_DIR/tests" ]]; then
        LIB_NAME=$(basename "$LIB_DIR")
        echo "--- Testing lib: $LIB_NAME ---"
        if [[ -n "$MARKER" ]]; then
            pytest "$LIB_DIR/tests" -m "$MARKER" -v ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
        else
            pytest "$LIB_DIR/tests" -v ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
        fi
    fi
done

# Services
for SVC_DIR in "$ROOT_DIR"/services/*/; do
    if [[ -d "$SVC_DIR/tests" ]]; then
        SVC_NAME=$(basename "$SVC_DIR")
        echo "--- Testing service: $SVC_NAME ---"
        if [[ -n "$MARKER" ]]; then
            pytest "$SVC_DIR/tests" -m "$MARKER" -v ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
        else
            pytest "$SVC_DIR/tests" -v ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} || FAILED=1
        fi
    fi
done

# Frontend
if command -v pnpm &> /dev/null && [[ -d "$ROOT_DIR/apps/frontend" ]]; then
    echo "--- Testing frontend ---"
    cd "$ROOT_DIR/apps/frontend"
    pnpm test || FAILED=1
    cd "$ROOT_DIR"
fi

if [[ $FAILED -ne 0 ]]; then
    echo "=== Tests FAILED ==="
    exit 1
fi

echo "=== All tests passed ==="
