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

    # Validate with fastavro
    python3 -c "
import json, fastavro
with open('$SCHEMA_FILE') as f:
    schema = json.load(f)
fastavro.parse_schema(schema)
print('    OK')
" || { echo "    FAILED"; FAILED=1; }

    # Register if requested
    if [[ "$REGISTER" == true ]]; then
        SUBJECT="${SCHEMA_NAME}-value"
        echo "    Registering as subject: $SUBJECT"
        SCHEMA_CONTENT=$(cat "$SCHEMA_FILE")
        curl -s -X POST \
            -H "Content-Type: application/vnd.schemaregistry.v1+json" \
            -d "{\"schema\": $(echo "$SCHEMA_CONTENT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}" \
            "$REGISTRY_URL/subjects/$SUBJECT/versions" \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'    Registered: id={d.get(\"id\", \"error\")}')"
    fi
done

if [[ $FAILED -ne 0 ]]; then
    echo "=== Schema validation FAILED ==="
    exit 1
fi

echo "=== All schemas valid ==="
