#!/usr/bin/env bash
# schema-guard.sh — Validates Avro schema changes for forward-compatibility.
# Called by Claude Code hook: PostToolUse matcher "Edit.*\.avsc$"
# Exit 0 = ok, non-zero = warning to agent.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCHEMAS_DIR="$ROOT_DIR/infra/kafka/schemas"

echo "── Schema Guard: Avro validation ─────────────────────────────"

if [ ! -d "$SCHEMAS_DIR" ]; then
  echo "✓ No schemas directory found — skipping"
  exit 0
fi

FAILED=0

# Validate all .avsc files (JSON syntax + fastavro parse)
for schema_file in "$SCHEMAS_DIR"/*.avsc; do
  [ ! -f "$schema_file" ] && continue
  fname=$(basename "$schema_file")

  # JSON syntax check
  if ! python3 -c "import json; json.load(open('$schema_file'))" 2>&1; then
    echo "✗ $fname: invalid JSON"
    FAILED=1
    continue
  fi

  # Avro schema validity check
  if ! python3 -c "
import fastavro.schema
fastavro.schema.load_schema('$schema_file')
" 2>&1; then
    echo "✗ $fname: invalid Avro schema"
    FAILED=1
    continue
  fi

  echo "  ✓ $fname valid"
done

# Check for backward-incompatible changes in git diff
echo ""
echo "── Checking for breaking changes ─────────────────────────────"
CHANGED_SCHEMAS=$(cd "$ROOT_DIR" && git diff --name-only HEAD 2>/dev/null | grep '\.avsc$' || true)
if [ -n "$CHANGED_SCHEMAS" ]; then
  for schema in $CHANGED_SCHEMAS; do
    full_path="$ROOT_DIR/$schema"
    [ ! -f "$full_path" ] && continue

    # Get the old version from git
    OLD_CONTENT=$(cd "$ROOT_DIR" && git show "HEAD:$schema" 2>/dev/null || true)
    if [ -z "$OLD_CONTENT" ]; then
      echo "  ✓ $schema is new — no compatibility check needed"
      continue
    fi

    # Check for removed fields (breaking change)
    OLD_FIELDS=$(echo "$OLD_CONTENT" | python3 -c "
import sys, json
try:
    schema = json.load(sys.stdin)
    fields = schema.get('fields', [])
    for f in fields:
        print(f['name'])
except: pass
" 2>/dev/null || true)

    NEW_FIELDS=$(python3 -c "
import json
schema = json.load(open('$full_path'))
fields = schema.get('fields', [])
for f in fields:
    print(f['name'])
" 2>/dev/null || true)

    # Check if any old fields were removed
    for old_field in $OLD_FIELDS; do
      if ! echo "$NEW_FIELDS" | grep -qx "$old_field"; then
        echo "  ✗ BREAKING: field '$old_field' removed from $schema"
        echo "    → Avro schemas must be forward-compatible. Add new fields with defaults instead."
        FAILED=1
      fi
    done

    # Check new fields have defaults
    python3 -c "
import json
old = json.loads('''$OLD_CONTENT''')
new = json.load(open('$full_path'))
old_names = {f['name'] for f in old.get('fields', [])}
new_fields = new.get('fields', [])
for f in new_fields:
    if f['name'] not in old_names:
        if 'default' not in f:
            print(f\"  ⚠ New field '{f['name']}' in $(basename $schema) has no default — may break consumers\")
" 2>/dev/null || true

    echo "  ✓ $schema compatibility checked"
  done
else
  echo "  ✓ No schema changes in working tree"
fi

if [ $FAILED -ne 0 ]; then
  echo ""
  echo "✗ Schema validation FAILED — fix breaking changes"
  exit 1
fi

echo ""
echo "✓ All schemas valid and forward-compatible"
exit 0
