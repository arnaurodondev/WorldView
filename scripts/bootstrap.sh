#!/usr/bin/env bash
# Bootstrap the worldview monorepo for local development.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON="${VIRTUAL_ENV}/bin/python"
fi
if [[ -z "$PYTHON" ]]; then
    for _py in python3.12 python3 python; do
        if command -v "$_py" &> /dev/null; then
            PYTHON="$_py"
            break
        fi
    done
fi
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: No Python interpreter found. Install Python 3.12+ and retry."
    exit 1
fi

python_install() {
    if "$PYTHON" -m pip --version >/dev/null 2>&1; then
        "$PYTHON" -m pip install "$@"
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$PYTHON" "$@"
        return
    fi

    echo "ERROR: Neither pip nor uv pip is available for interpreter '$PYTHON'."
    return 1
}

echo "=== worldview bootstrap ==="

# 1. Check prerequisites
echo "Checking prerequisites..."
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: Python executable '$PYTHON' is not executable. See docs/workflows/local-dev.md"
    exit 1
fi
for cmd in docker hatch; do
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
    echo "  WARNING: pre-commit not found. Install with: $PYTHON -m pip install pre-commit (or uv pip install --python $PYTHON pre-commit)"
fi

# 3. Install all libs in editable mode
echo "Installing shared libraries..."
for LIB_DIR in "$ROOT_DIR"/libs/*/; do
    LIB_NAME=$(basename "$LIB_DIR")
    echo "  Installing $LIB_NAME..."
    python_install -e "$LIB_DIR[dev]" --quiet
done

# 4. Install all services in editable mode
echo "Installing services..."
for SVC_DIR in "$ROOT_DIR"/services/*/; do
    SVC_NAME=$(basename "$SVC_DIR")
    echo "  Installing $SVC_NAME..."
    python_install -e "$SVC_DIR[dev]" --quiet
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
