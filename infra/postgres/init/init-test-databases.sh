#!/usr/bin/env bash
# Create databases required for the test docker-compose stack.
# Runs at postgres container first-start (docker-entrypoint-initdb.d/).
# Uses postgres:postgres credentials (matches dev.local.env connection URLs).
set -euo pipefail

echo "=== Creating test databases ==="

ALL_DBS=(
    portfolio_db
    ingestion_db
    content_ingestion_db
    content_ingestion_test_db
    content_store_db
    nlp_db
    alert_db
    intelligence_db
    rag_db
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

# pgvector required for NLP embeddings (section_embeddings, chunk_embeddings VECTOR(1024))
for DB in nlp_db intelligence_db; do
    echo "Enabling pgvector in: $DB"
    psql -v ON_ERROR_STOP=0 --username "$POSTGRES_USER" --dbname "$DB" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
EOSQL
done

echo "=== Test database initialisation complete ==="
