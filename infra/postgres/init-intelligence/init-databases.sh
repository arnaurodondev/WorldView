#!/usr/bin/env bash
# Create the OLAP (intelligence) databases + extensions for the dedicated
# postgres-intelligence instance.
#
# This instance is split off from the main `postgres` container so that heavy
# KG/NLP analytical queries (multi-hour AGE relation scans, multi-minute FTS)
# can no longer starve latency-sensitive OLTP queries. See
# docs/audits/2026-06-08-postgres-workload-split.md.
#
# POSTGRES_USER must be a superuser (postgres:postgres is the default for this stack).
set -euo pipefail

echo "=== Creating worldview intelligence (OLAP) databases ==="

DATABASES=(
    nlp_db
    intelligence_db
    kg_db
)

for DB in "${DATABASES[@]}"; do
    echo "Creating database: $DB"
    psql -v ON_ERROR_STOP=0 <<SQL
        SELECT 'CREATE DATABASE $DB'
        WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB')
        \gexec
SQL
done

# Enable uuid-ossp in each database
for DB in "${DATABASES[@]}"; do
    echo "Enabling extensions in: $DB"
    psql -d "$DB" -v ON_ERROR_STOP=0 <<SQL
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL
done

# pgvector for nlp_db
echo "Enabling pgvector in nlp_db"
psql -d nlp_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS vector;
SQL

# pgvector + pg_trgm for intelligence_db (owned by intelligence-migrations; used by S6 + S7)
echo "Enabling pgvector and pg_trgm in intelligence_db"
psql -d intelligence_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL

# Apache AGE — the live KG graph `worldview_graph` lives in intelligence_db (the KG
# service runs LOAD 'age' against KNOWLEDGE_GRAPH_DATABASE_URL = intelligence_db).
# intelligence-migrations owns creation of the worldview_graph graph itself, so here
# we only ensure the extension is present.
echo "Enabling AGE in intelligence_db"
psql -d intelligence_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS age;
SQL

# kg_db retains the legacy `market_kg` graph + holds ticker_aliases (intelligence-migrations
# alembic 0040). Keep parity with the original init for fresh bring-ups.
echo "Enabling AGE in kg_db"
psql -d kg_db -v ON_ERROR_STOP=0 <<SQL
    CREATE EXTENSION IF NOT EXISTS age;
    SET search_path = ag_catalog, "\$user", public;
    SELECT create_graph('market_kg');
SQL

echo "=== Intelligence database initialisation complete ==="
