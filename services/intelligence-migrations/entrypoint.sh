#!/usr/bin/env bash
# intelligence-migrations entrypoint
# 1. Run Alembic migrations
# 2. Run seed SQL scripts (idempotent)
# 3. Attempt embedding population (non-blocking on failure)
set -euo pipefail

echo "=== Step 1/3: Running Alembic migrations ==="
alembic upgrade head

echo "=== Step 2/3: Running seed scripts ==="
for sql_file in /app/seeds/*.sql; do
    [ -f "$sql_file" ] || continue
    echo "  Seeding: $(basename "$sql_file")"
    psql "$INTELLIGENCE_DB_URL" -f "$sql_file" --set ON_ERROR_STOP=1
done

echo "=== Step 3/3: Populating relation type embeddings ==="
python /app/scripts/populate_embeddings.py || true

echo "=== intelligence-migrations complete ==="
