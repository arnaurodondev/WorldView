#!/usr/bin/env bash
# Bootstrap the worldview monorepo for local development.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== worldview bootstrap ==="

# 1. Check prerequisites
echo "Checking prerequisites..."
for cmd in python3 docker hatch; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "ERROR: $cmd is not installed. See docs/workflows/local-dev.md"
        exit 1
    fi
done
echo "  All prerequisites found."

# 2. Install pre-commit hooks
echo "Installing pre-commit hooks..."
if command -v pre-commit &> /dev/null; then
    cd "$ROOT_DIR" && pre-commit install
else
    echo "  WARNING: pre-commit not found. Install with: pip install pre-commit"
fi

# 3. Install all libs in editable mode
echo "Installing shared libraries..."
for LIB_DIR in "$ROOT_DIR"/libs/*/; do
    LIB_NAME=$(basename "$LIB_DIR")
    echo "  Installing $LIB_NAME..."
    pip install -e "$LIB_DIR[dev]" --quiet
done

# 4. Install all services in editable mode
echo "Installing services..."
for SVC_DIR in "$ROOT_DIR"/services/*/; do
    SVC_NAME=$(basename "$SVC_DIR")
    echo "  Installing $SVC_NAME..."
    pip install -e "$SVC_DIR[dev]" --quiet
done

# 5. Verify Docker is running
echo "Checking Docker..."
if docker info &> /dev/null; then
    echo "  Docker is running."
else
    echo "  WARNING: Docker is not running. Start Docker Desktop before using docker compose."
fi

# 6. Install frontend dependencies (if pnpm available)
if command -v pnpm &> /dev/null; then
    echo "Installing frontend dependencies..."
    cd "$ROOT_DIR/apps/frontend" && pnpm install
    cd "$ROOT_DIR"
else
    echo "  WARNING: pnpm not found. Run: corepack enable && corepack prepare pnpm@9 --activate"
fi

echo ""
echo "=== Bootstrap complete ==="
echo ""
echo "Next steps:"
echo "  1. docker compose --profile infra up -d"
echo "  2. docker compose --profile init up"
echo "  3. cd services/portfolio && make run"
echo "  4. cd apps/frontend && pnpm dev    # Frontend on :5173"
