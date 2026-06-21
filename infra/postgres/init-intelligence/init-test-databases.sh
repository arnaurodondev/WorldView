#!/usr/bin/env bash
# Create the OLAP test databases for the dedicated postgres-intelligence instance.
# Runs at container first-start (docker-entrypoint-initdb.d/).
# Uses postgres:postgres credentials (matches *.env URLs).
#
# Mirrors infra/postgres/init/init-test-databases.sh but only for the OLAP group.
# See docs/audits/2026-06-08-postgres-workload-split.md.
set -euo pipefail

echo "=== Creating intelligence (OLAP) test databases ==="

ALL_DBS=(
    nlp_db
    intelligence_db
    intelligence_test_db
)

for DB in "${ALL_DBS[@]}"; do
    echo "Creating database: $DB"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        SELECT 'CREATE DATABASE $DB'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB')
        \gexec
EOSQL
done

for DB in "${ALL_DBS[@]}"; do
    echo "Enabling uuid-ossp in: $DB"
    psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$DB" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOSQL
done

# pgvector required for NLP embeddings + intelligence definition embeddings.
for DB in nlp_db intelligence_db intelligence_test_db; do
    echo "Enabling pgvector in: $DB"
    psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$DB" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
done

echo "=== Intelligence test database initialisation complete ==="
