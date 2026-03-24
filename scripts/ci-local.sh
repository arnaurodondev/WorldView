#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

PYTHON_BIN="python3"
JOB="all"
VENV_DIR=""

LIBS=(common contracts messaging storage observability)
SERVICES=(portfolio market-ingestion market-data content-ingestion content-store nlp-pipeline knowledge-graph rag-chat api-gateway)

usage() {
    cat <<'EOF'
Run CI workflow jobs locally.

Usage:
  ./scripts/ci-local.sh [--job <name>] [--python <python_bin>]

Options:
  --job <name>     One of: all, lint, validate-schemas, validate-service-structure,
                   import-guards, architecture-tests, test-libs, test-services,
                   test-frontend
                   Default: all
  --python <bin>   Python executable to use (default: python3)
  -h, --help       Show this help

Examples:
  ./scripts/ci-local.sh
  ./scripts/ci-local.sh --job validate-service-structure
  ./scripts/ci-local.sh --job import-guards
  ./scripts/ci-local.sh --job architecture-tests
  ./scripts/ci-local.sh --job test-libs
  ./scripts/ci-local.sh --job lint --python python3.12
EOF
}

run_cmd() {
    echo "+ $*"
    "$@"
}

python_install() {
    if "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        run_cmd "$PYTHON_BIN" -m pip install "$@"
        return
    fi

    if command -v uv >/dev/null 2>&1; then
        run_cmd uv pip install --python "$PYTHON_BIN" "$@"
        return
    fi

    echo "ERROR: Neither pip nor uv pip is available for '$PYTHON_BIN'."
    return 1
}

ensure_venv() {
    cd "$ROOT_DIR"

    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        return 0
    fi

    if "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.prefix == sys.base_prefix else 1)'; then
        VENV_DIR="$ROOT_DIR/.venv-ci-local"
        if [[ ! -d "$VENV_DIR" ]]; then
            echo "Creating local virtual environment at $VENV_DIR..."
            run_cmd "$PYTHON_BIN" -m venv "$VENV_DIR"
        fi
        PYTHON_BIN="$VENV_DIR/bin/python"
    fi
}

run_lint() {
    echo "=== Job: lint (Ruff + mypy) ==="

    cd "$ROOT_DIR"
    ensure_venv

    python_install ruff mypy
    run_cmd "$PYTHON_BIN" -m ruff check libs/ services/
    run_cmd "$PYTHON_BIN" -m ruff format --check libs/ services/

    echo "Installing libs with [dev] extras for type-checking..."
    for dir in libs/*/; do
        python_install -e "$dir[dev]" --quiet
    done

    echo "Running mypy (matching CI behavior)..."
    for src in libs/*/src services/*/src; do
        if [[ -d "$src" ]]; then
            echo "=== mypy $src ==="
            "$PYTHON_BIN" -m mypy "$src" || true
        fi
    done
}

run_validate_schemas() {
    echo "=== Job: validate-schemas ==="

    cd "$ROOT_DIR"
    ensure_venv

    python_install fastavro
    run_cmd "$PYTHON_BIN" -c "
import json
import pathlib
import sys

import fastavro

failed = False
for f in sorted(pathlib.Path('infra/kafka/schemas').glob('*.avsc')):
    try:
        schema = json.loads(f.read_text())
        fastavro.parse_schema(schema)
        print(f'  OK: {f.name}')
    except Exception as exc:
        print(f'  FAIL: {f.name}: {exc}')
        failed = True
if failed:
    sys.exit(1)
"
}

run_test_libs() {
    echo "=== Job: test-libs ==="

    cd "$ROOT_DIR"
    ensure_venv

    for lib in "${LIBS[@]}"; do
        echo "--- Testing lib: $lib ---"
        python_install -e "libs/$lib[dev]" --quiet
        run_cmd "$PYTHON_BIN" -m pytest "libs/$lib/tests" -m unit -v --tb=short
    done
}

run_test_services() {
    echo "=== Job: test-services ==="

    cd "$ROOT_DIR"
    ensure_venv

    for service in "${SERVICES[@]}"; do
        echo "--- Testing service: $service ---"
        for dir in libs/*/; do
            python_install -e "$dir" --quiet
        done
        python_install -e "services/$service[dev]" --quiet
        run_cmd "$PYTHON_BIN" -m pytest "services/$service/tests" -m unit -v --tb=short
    done
}

run_validate_service_structure() {
    echo "=== Job: validate-service-structure ==="

    cd "$ROOT_DIR"
    ensure_venv
    python_install pyyaml --quiet

    run_cmd "$PYTHON_BIN" scripts/structure_checks/check_service_structure.py \
        --strict \
        --allow-exceptions-file scripts/structure_checks/exceptions.yaml
}

run_import_guards() {
    echo "=== Job: import-guards ==="

    cd "$ROOT_DIR"
    ensure_venv
    python_install pyyaml --quiet

    run_cmd "$PYTHON_BIN" scripts/import_guards/check_import_guards.py \
        --strict \
        --baseline scripts/import_guards/baseline.json
}

run_architecture_tests() {
    echo "=== Job: architecture-tests ==="

    cd "$ROOT_DIR"
    ensure_venv
    python_install pytest pytest-asyncio --quiet

    run_cmd "$PYTHON_BIN" -m pytest tests/architecture -v --tb=short
}

run_test_frontend() {
    echo "=== Job: test-frontend ==="

    if ! command -v pnpm >/dev/null 2>&1; then
        echo "pnpm is not installed. Install it first: corepack enable && corepack prepare pnpm@9 --activate"
        return 1
    fi

    cd "$ROOT_DIR/apps/frontend"

    run_cmd pnpm install --frozen-lockfile
    run_cmd pnpm typecheck
    run_cmd pnpm lint
    run_cmd pnpm test
    run_cmd pnpm build
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --job)
            JOB="$2"
            shift 2
            ;;
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            exit 2
            ;;
    esac
done

case "$JOB" in
    all)
        run_lint
        run_validate_schemas
        run_validate_service_structure
        run_import_guards
        run_architecture_tests
        run_test_libs
        run_test_services
        run_test_frontend
        ;;
    lint)
        run_lint
        ;;
    validate-schemas)
        run_validate_schemas
        ;;
    validate-service-structure)
        run_validate_service_structure
        ;;
    import-guards)
        run_import_guards
        ;;
    architecture-tests)
        run_architecture_tests
        ;;
    test-libs)
        run_test_libs
        ;;
    test-services)
        run_test_services
        ;;
    test-frontend)
        run_test_frontend
        ;;
    *)
        echo "Invalid --job value: $JOB"
        usage
        exit 2
        ;;
esac

echo "=== Local CI completed successfully (job: $JOB) ==="
