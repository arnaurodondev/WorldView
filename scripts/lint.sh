#!/usr/bin/env bash
# Run ruff + mypy across all packages.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Linting ==="

FAILED=0

# Ruff check
echo "Running ruff check..."
ruff check "$ROOT_DIR/libs" "$ROOT_DIR/services" || FAILED=1

# Ruff format check
echo "Running ruff format --check..."
ruff format --check "$ROOT_DIR/libs" "$ROOT_DIR/services" || FAILED=1

# mypy
echo "Running mypy..."
for PKG_DIR in "$ROOT_DIR"/libs/*/src "$ROOT_DIR"/services/*/src; do
    if [[ -d "$PKG_DIR" ]]; then
        echo "  mypy $PKG_DIR"
        mypy "$PKG_DIR" || FAILED=1
    fi
done

# Frontend (if pnpm available)
if command -v pnpm &> /dev/null && [[ -d "$ROOT_DIR/apps/frontend" ]]; then
    echo "Running frontend lint..."
    cd "$ROOT_DIR/apps/frontend"
    pnpm lint || FAILED=1
    pnpm typecheck || FAILED=1
    cd "$ROOT_DIR"
fi

if [[ $FAILED -ne 0 ]]; then
    echo "=== Lint FAILED ==="
    exit 1
fi

echo "=== Lint passed ==="
