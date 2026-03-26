#!/usr/bin/env bash
# migration-guard.sh — Warns when domain entities change without a migration.
# Called by Claude Code hook: PostToolUse matcher "Edit.*(entities|models).*\.py$"
# Exit 0 always (informational only — does not block).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

# ─── Detect changed entity/model files ───────────────────────────────────────
CHANGED_FILES=$(cd "$ROOT_DIR" && git diff --name-only 2>/dev/null || true)
ENTITY_FILES=$(echo "$CHANGED_FILES" | grep -E '(domain/entities|domain/value_objects|infrastructure/db/models)' | grep '\.py$' || true)

if [ -z "$ENTITY_FILES" ]; then
  exit 0
fi

echo "── Migration Guard ───────────────────────────────────────────"
echo ""

WARNINGS=0

for f in $ENTITY_FILES; do
  # Extract service name
  SVC=$(echo "$f" | sed -n 's|^services/\([^/]*\)/.*|\1|p')
  [ -z "$SVC" ] && continue

  ALEMBIC_DIR="$ROOT_DIR/services/$SVC/alembic"

  # Check if this service has Alembic
  if [ ! -d "$ALEMBIC_DIR" ]; then
    echo "  ⚠ $f changed but services/$SVC has no alembic/ directory"
    WARNINGS=$((WARNINGS + 1))
    continue
  fi

  # Check if there's a new migration in the current diff
  NEW_MIGRATION=$(echo "$CHANGED_FILES" | grep "services/$SVC/alembic/versions/" || true)

  if [ -z "$NEW_MIGRATION" ]; then
    echo "  ⚠ $f changed but no new Alembic migration found"
    echo "    → If this changes the DB schema, run:"
    echo "      cd services/$SVC && alembic revision --autogenerate -m \"description\""
    echo "    → If this is a domain-only change (no DB impact), you can ignore this warning."
    WARNINGS=$((WARNINGS + 1))
  else
    echo "  ✓ $f changed and migration exists"
  fi
done

if [ $WARNINGS -gt 0 ]; then
  echo ""
  echo "  $WARNINGS entity file(s) changed without corresponding migrations."
  echo "  Review each warning above and create migrations if needed."
fi

exit 0
