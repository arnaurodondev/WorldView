#!/usr/bin/env bash
# Run unit (and optionally integration) tests for all shared libraries.
#
# Usage:
#   ./scripts/test-libs.sh                  # unit tests only (no infra needed)
#   ./scripts/test-libs.sh --integration    # unit + integration tests (starts MinIO)
#   ./scripts/test-libs.sh --lib observability  # single lib only
#
# Integration test prerequisites:
#   - Docker + Docker Compose available
#   - infra/compose/docker-compose.yml present
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed
#   2 — usage error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$ROOT_DIR/infra/compose/docker-compose.yml"

# ── Resolve Python command ────────────────────────────────────────────────────
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
    echo "ERROR: No Python interpreter found. Set PYTHON= or install python3." >&2
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

    echo "ERROR: Neither pip nor uv pip is available for interpreter '$PYTHON'." >&2
    return 1
}

# ── Defaults ─────────────────────────────────────────────────────────────────
INTEGRATION=false
TARGET_LIB=""
PYTEST_EXTRA_ARGS=()

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --integration)
            INTEGRATION=true
            shift
            ;;
        --lib)
            TARGET_LIB="${2:-}"
            shift 2
            ;;
        --)
            shift
            PYTEST_EXTRA_ARGS+=("$@")
            break
            ;;
        *)
            PYTEST_EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# ── Integration infra lifecycle ───────────────────────────────────────────────
COMPOSE_STARTED=false

start_infra() {
    if ! command -v docker &>/dev/null; then
        echo "ERROR: docker not found — integration tests require Docker." >&2
        exit 1
    fi
    echo "=== Starting lib-test infra (MinIO) ==="
    docker compose -f "$COMPOSE_FILE" --profile lib-test up -d --wait minio || {
        echo "ERROR: Failed to start integration infra." >&2
        exit 1
    }
    echo "=== Initializing MinIO buckets ==="
    docker compose -f "$COMPOSE_FILE" --profile lib-test run --rm minio-init >/dev/null || {
        echo "ERROR: Failed to initialize MinIO buckets." >&2
        exit 1
    }
    COMPOSE_STARTED=true
}

stop_infra() {
    if [[ "$COMPOSE_STARTED" == "true" ]]; then
        echo "=== Stopping lib-test infra ==="
        docker compose -f "$COMPOSE_FILE" --profile lib-test down --remove-orphans || true
    fi
}

trap stop_infra EXIT

if [[ "$INTEGRATION" == "true" ]]; then
    start_infra
fi

# ── Test runner ───────────────────────────────────────────────────────────────
FAILED=0
PASSED=0
SKIPPED=0
MARKER_ARGS=()

if [[ "$INTEGRATION" == "false" ]]; then
    # Run only tests NOT marked as integration when no --integration flag given
    MARKER_ARGS=("-m" "not integration")
fi

run_lib_tests() {
    local lib_dir="$1"
    local lib_name
    lib_name="$(basename "$lib_dir")"

    if [[ ! -d "$lib_dir/tests" ]]; then
        echo "  [SKIP] $lib_name — no tests/ directory"
        return
    fi

    echo ""
    echo "--- Testing lib: $lib_name ---"

    if [[ "$lib_name" == "ml-clients" ]]; then
        local py_minor
        py_minor="$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')"
        if [[ "$py_minor" -lt 12 ]]; then
            echo "  [SKIP] $lib_name — requires Python >=3.12"
            SKIPPED=$((SKIPPED + 1))
            return
        fi
    fi

    # Install lib + dev extras if needed
    if [[ -f "$lib_dir/pyproject.toml" ]]; then
        if ! python_install -q -e "$lib_dir[dev]"; then
            echo "  [FAIL] $lib_name — failed to install test dependencies"
            FAILED=$((FAILED + 1))
            return
        fi
    fi

    if "$PYTHON" -m pytest "$lib_dir/tests" -v ${MARKER_ARGS[@]+"${MARKER_ARGS[@]}"} ${PYTEST_EXTRA_ARGS[@]+"${PYTEST_EXTRA_ARGS[@]}"}; then
        echo "  [PASS] $lib_name"
        PASSED=$((PASSED + 1))
    else
        echo "  [FAIL] $lib_name"
        FAILED=$((FAILED + 1))
    fi
}

echo "=== Running lib tests (integration=$INTEGRATION) ==="

echo "=== Installing all local libs in editable mode (dependency bootstrap) ==="
if ! python_install -q \
    -e "$ROOT_DIR/libs/common" \
    -e "$ROOT_DIR/libs/contracts" \
    -e "$ROOT_DIR/libs/messaging" \
    -e "$ROOT_DIR/libs/storage" \
    -e "$ROOT_DIR/libs/observability"; then
    echo "WARNING: bootstrap install failed; continuing with per-lib installation attempts."
fi

if [[ -n "$TARGET_LIB" ]]; then
    lib_path="$ROOT_DIR/libs/$TARGET_LIB"
    if [[ ! -d "$lib_path" ]]; then
        echo "ERROR: lib '$TARGET_LIB' not found at $lib_path" >&2
        exit 2
    fi
    run_lib_tests "$lib_path"
else
    for lib_dir in "$ROOT_DIR"/libs/*/; do
        run_lib_tests "$lib_dir"
    done
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Summary: $PASSED passed, $FAILED failed, $SKIPPED skipped ==="

if [[ $FAILED -ne 0 ]]; then
    echo "=== FAILED ==="
    exit 1
fi

echo "=== All lib tests passed ==="
