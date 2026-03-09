#!/usr/bin/env bash
# Create all application databases + extensions.
set -euo pipefail

echo "=== Creating worldview databases ==="

DATABASES=(
    portfolio_db
    market_ingestion_db
    market_data_db
    content_ingestion_db
    content_store_db
    nlp_db
    kg_db
    rag_db
    gateway_db
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

# pgvector for nlp_db
echo "Enabling pgvector in nlp_db"
psql -d nlp_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS vector;
SQL

# Apache AGE for kg_db
echo "Enabling AGE in kg_db"
psql -d kg_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS age;
    SET search_path = ag_catalog, "$user", public;
    SELECT create_graph('market_kg');
SQL

echo "=== Database initialisation complete ==="
