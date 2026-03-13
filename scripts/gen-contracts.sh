#!/usr/bin/env bash
# Validate all Avro schemas and optionally register them with Schema Registry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SCHEMA_DIR="$ROOT_DIR/infra/kafka/schemas"

REGISTRY_URL="${SCHEMA_REGISTRY_URL:-http://localhost:8081}"
REGISTER=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --register)
            REGISTER=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo "=== Validating Avro schemas ==="

FAILED=0

for SCHEMA_FILE in "$SCHEMA_DIR"/*.avsc; do
    SCHEMA_NAME=$(basename "$SCHEMA_FILE" .avsc)
    echo "  Validating: $SCHEMA_NAME"
    python3 -c "
import json, fastavro
with open('$SCHEMA_FILE') as f:
    schema = json.load(f)
fastavro.parse_schema(schema)
print('    OK')
" || { echo "    FAILED"; FAILED=1; }
done

if [[ $FAILED -ne 0 ]]; then
    echo "=== Schema validation FAILED ==="
    exit 1
fi

echo "=== All schemas valid ==="

if [[ "$REGISTER" == true ]]; then
    echo ""
    echo "=== Registering schemas ==="
    python3 "$SCRIPT_DIR/../infra/kafka/init/register-schemas.py" \
        --schema-dir "$SCHEMA_DIR" \
        --registry-url "$REGISTRY_URL"
fi
