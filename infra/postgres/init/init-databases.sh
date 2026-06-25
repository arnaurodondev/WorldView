#!/usr/bin/env bash
# Create the OLTP application databases + extensions for the main `postgres` instance.
#
# WORKLOAD SPLIT (2026-06-08): nlp_db, intelligence_db and kg_db moved to the
# dedicated `postgres-intelligence` (OLAP) instance — see
# docs/audits/2026-06-08-postgres-workload-split.md and
# infra/postgres/init-intelligence/. They are intentionally NOT created here.
#
# POSTGRES_USER must be a superuser (postgres:postgres is the default for this stack).
set -euo pipefail

echo "=== Creating worldview databases ==="

DATABASES=(
    portfolio_db
    ingestion_db
    market_data_db
    content_ingestion_db
    content_store_db
    rag_db
    gateway_db
    alert_db
)

for DB in "${DATABASES[@]}"; do
    echo "Creating database: $DB"
    psql -v ON_ERROR_STOP=0 <<SQL
        SELECT 'CREATE DATABASE $DB'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB')
        \gexec
SQL
done

# Enable extensions in each database
for DB in "${DATABASES[@]}"; do
    echo "Enabling extensions in: $DB"
    psql -d "$DB" -v ON_ERROR_STOP=0 <<SQL
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL
done

# TimescaleDB for market_data_db
echo "Enabling TimescaleDB in market_data_db"
psql -d market_data_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS timescaledb;
SQL

# pgcrypto for content_ingestion_db (required by PLAN-0055 B-1 config_hash GENERATED column)
echo "Enabling pgcrypto in content_ingestion_db"
psql -d content_ingestion_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS pgcrypto;
SQL

# NOTE: nlp_db (pgvector), intelligence_db (pgvector + pg_trgm + AGE) and kg_db (AGE)
# now live on the postgres-intelligence instance — see
# infra/postgres/init-intelligence/init-databases.sh.

echo "=== Database initialisation complete ==="
