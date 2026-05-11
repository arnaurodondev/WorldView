#!/usr/bin/env bash
# intelligence-migrations entrypoint
# 1. Run Alembic migrations
# 2. Run seed SQL scripts (idempotent)
# 3. Attempt embedding population (non-blocking on failure)
set -euo pipefail

echo "=== Step 1/3: Running Alembic migrations ==="
alembic upgrade head

# PLAN-0052 QA-R6: assert current revision == head after upgrade.
# Exits non-zero if any migration was not applied (e.g. a new version file
# not reachable from the current revision chain, or a partial apply).
CURRENT_REV=$(alembic current 2>&1 | grep -oE '[0-9a-f]{4}' | head -1)
HEAD_REV=$(alembic heads 2>&1 | grep -oE '[0-9a-f]{4}' | head -1)
if [ "$CURRENT_REV" != "$HEAD_REV" ]; then
    echo "ERROR: migrations not at head. current=$CURRENT_REV head=$HEAD_REV" >&2
    exit 1
fi
echo "  Migrations verified at head ($HEAD_REV)"

echo "=== Step 2/3: Running seed scripts ==="
for sql_file in /app/seeds/*.sql; do
    [ -f "$sql_file" ] || continue
    echo "  Seeding: $(basename "$sql_file")"
    psql "$INTELLIGENCE_DB_URL" -f "$sql_file" --set ON_ERROR_STOP=1
done

echo "=== Step 3/3: Populating relation type embeddings ==="
python /app/scripts/populate_embeddings.py || true

echo "=== intelligence-migrations complete ==="
