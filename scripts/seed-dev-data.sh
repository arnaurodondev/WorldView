#!/usr/bin/env bash
# scripts/seed-dev-data.sh — Load development seed data into PostgreSQL
#
# Splits the SQL into per-database sections because \connect does not work
# when piped via docker exec. Each section is executed against its target DB.
set -euo pipefail

CONTAINER="${1:-worldview-postgres-1}"
PSQL="docker exec -i $CONTAINER psql -U postgres"

echo "Seeding portfolio_db..."
$PSQL -d portfolio_db <<'SQL'
INSERT INTO tenants (id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000001', 'Demo Tenant', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, tenant_id, email, status, created_at, external_id, role) VALUES
    ('01900000-0000-7000-8000-000000000010', '01900000-0000-7000-8000-000000000001', 'demo@worldview.dev', 'active', NOW(), 'dev-user', 'owner')
ON CONFLICT (id) DO NOTHING;

INSERT INTO portfolios (id, tenant_id, owner_id, name, currency, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Demo Portfolio', 'USD', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO watchlists (id, tenant_id, user_id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Tech Watchlist', 'active', NOW())
ON CONFLICT (id) DO NOTHING;
SQL

echo "Seeding market_data_db..."
$PSQL -d market_data_db <<'SQL'
INSERT INTO securities (id, isin, name, sector, industry, country, currency, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000002001', 'US0378331005', 'Apple Inc.', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002002', 'US5949181045', 'Microsoft Corporation', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002003', 'US02079K3059', 'Alphabet Inc.', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002004', 'US88160R1014', 'Tesla, Inc.', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002005', 'US0231351067', 'Amazon.com, Inc.', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO instruments (id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, name, isin, sector, industry, country, currency_code, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000001001', '01900000-0000-7000-8000-000000002001', 'AAPL', 'US', true, true, true, 'Apple Inc.', 'US0378331005', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001002', '01900000-0000-7000-8000-000000002002', 'MSFT', 'US', true, true, true, 'Microsoft Corporation', 'US5949181045', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001003', '01900000-0000-7000-8000-000000002003', 'GOOGL', 'US', true, true, true, 'Alphabet Inc.', 'US02079K3059', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001004', '01900000-0000-7000-8000-000000002004', 'TSLA', 'US', true, true, true, 'Tesla, Inc.', 'US88160R1014', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001005', '01900000-0000-7000-8000-000000002005', 'AMZN', 'US', true, true, true, 'Amazon.com, Inc.', 'US0231351067', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
SQL

echo "Done. Verifying..."
$PSQL -d portfolio_db -c "SELECT email FROM users LIMIT 3;"
$PSQL -d market_data_db -c "SELECT symbol, name FROM instruments LIMIT 5;"
echo "Seed complete."
