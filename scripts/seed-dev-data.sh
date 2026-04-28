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
    ('01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Tech Watchlist', 'active', NOW()),
    ('01900000-0000-7000-8000-000000000201', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'EV & Clean Energy', 'active', NOW()),
    ('01900000-0000-7000-8000-000000000202', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'E-Commerce & Retail', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

-- Tech Watchlist members: AAPL, MSFT, GOOGL
INSERT INTO watchlist_members (id, watchlist_id, entity_id, entity_type, added_at) VALUES
    ('01900000-0000-7000-8000-000000000300', '01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000001001', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000301', '01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000001002', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000302', '01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000001003', 'company', NOW())
ON CONFLICT (id) DO NOTHING;

-- EV & Clean Energy members: TSLA, NVDA, DIS
INSERT INTO watchlist_members (id, watchlist_id, entity_id, entity_type, added_at) VALUES
    ('01900000-0000-7000-8000-000000000303', '01900000-0000-7000-8000-000000000201', '01900000-0000-7000-8000-000000001004', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000304', '01900000-0000-7000-8000-000000000201', '01900000-0000-7000-8000-000000001006', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000305', '01900000-0000-7000-8000-000000000201', '01900000-0000-7000-8000-000000001010', 'company', NOW())
ON CONFLICT (id) DO NOTHING;

-- E-Commerce & Retail members: AMZN, META, NFLX
INSERT INTO watchlist_members (id, watchlist_id, entity_id, entity_type, added_at) VALUES
    ('01900000-0000-7000-8000-000000000306', '01900000-0000-7000-8000-000000000202', '01900000-0000-7000-8000-000000001005', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000307', '01900000-0000-7000-8000-000000000202', '01900000-0000-7000-8000-000000001007', 'company', NOW()),
    ('01900000-0000-7000-8000-000000000308', '01900000-0000-7000-8000-000000000202', '01900000-0000-7000-8000-000000001009', 'company', NOW())
ON CONFLICT (id) DO NOTHING;

-- Demo holdings for the original 5 instruments
-- F-201 (QA iter-2): seed must be RESET-idempotent so re-running ``make seed``
-- fully restores holdings even if a prior run zeroed them. We use ON CONFLICT
-- DO UPDATE so an existing row's quantity/average_cost are overwritten with
-- the seed values rather than left at whatever the repair script wrote (or
-- whatever the live brokerage sync produced). Other columns are also
-- refreshed for consistency.
INSERT INTO holdings (id, portfolio_id, instrument_id, tenant_id, quantity, average_cost, currency, updated_at) VALUES
    ('01900000-0000-7000-8000-000000000400', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001001', '01900000-0000-7000-8000-000000000001', 50.00000000, 178.50000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000401', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001002', '01900000-0000-7000-8000-000000000001', 30.00000000, 412.75000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000402', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001003', '01900000-0000-7000-8000-000000000001', 20.00000000, 141.20000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000403', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001004', '01900000-0000-7000-8000-000000000001', 15.00000000, 245.30000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000404', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001005', '01900000-0000-7000-8000-000000000001', 25.00000000, 185.60000000, 'USD', NOW())
ON CONFLICT (id) DO UPDATE SET
    quantity = EXCLUDED.quantity,
    average_cost = EXCLUDED.average_cost,
    currency = EXCLUDED.currency,
    updated_at = EXCLUDED.updated_at;
SQL

echo "Seeding market_data_db..."
$PSQL -d market_data_db <<'SQL'
INSERT INTO securities (id, isin, name, sector, industry, country, currency, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000002001', 'US0378331005', 'Apple Inc.', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002002', 'US5949181045', 'Microsoft Corporation', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002003', 'US02079K3059', 'Alphabet Inc.', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002004', 'US88160R1014', 'Tesla, Inc.', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002005', 'US0231351067', 'Amazon.com, Inc.', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002006', 'US67066G1040', 'NVIDIA Corporation', 'Technology', 'Semiconductors', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002007', 'US30303M1027', 'Meta Platforms, Inc.', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002008', 'US46625H1005', 'JPMorgan Chase & Co.', 'Financial Services', 'Banks - Diversified', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002009', 'US64110L1061', 'Netflix, Inc.', 'Communication Services', 'Entertainment', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002010', 'US2546871060', 'The Walt Disney Company', 'Communication Services', 'Entertainment', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO instruments (id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, name, isin, sector, industry, country, currency_code, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000001001', '01900000-0000-7000-8000-000000002001', 'AAPL', 'US', true, true, true, 'Apple Inc.', 'US0378331005', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001002', '01900000-0000-7000-8000-000000002002', 'MSFT', 'US', true, true, true, 'Microsoft Corporation', 'US5949181045', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001003', '01900000-0000-7000-8000-000000002003', 'GOOGL', 'US', true, true, true, 'Alphabet Inc.', 'US02079K3059', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001004', '01900000-0000-7000-8000-000000002004', 'TSLA', 'US', true, true, true, 'Tesla, Inc.', 'US88160R1014', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001005', '01900000-0000-7000-8000-000000002005', 'AMZN', 'US', true, true, true, 'Amazon.com, Inc.', 'US0231351067', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001006', '01900000-0000-7000-8000-000000002006', 'NVDA', 'US', true, true, true, 'NVIDIA Corporation', 'US67066G1040', 'Technology', 'Semiconductors', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001007', '01900000-0000-7000-8000-000000002007', 'META', 'US', true, true, true, 'Meta Platforms, Inc.', 'US30303M1027', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001008', '01900000-0000-7000-8000-000000002008', 'JPM', 'US', true, true, true, 'JPMorgan Chase & Co.', 'US46625H1005', 'Financial Services', 'Banks - Diversified', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001009', '01900000-0000-7000-8000-000000002009', 'NFLX', 'US', true, true, true, 'Netflix, Inc.', 'US64110L1061', 'Communication Services', 'Entertainment', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001010', '01900000-0000-7000-8000-000000002010', 'DIS', 'US', true, true, true, 'The Walt Disney Company', 'US2546871060', 'Communication Services', 'Entertainment', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
SQL

echo "Done. Verifying..."
$PSQL -d portfolio_db -c "SELECT email FROM users LIMIT 3;"
$PSQL -d portfolio_db -c "SELECT w.name, COUNT(wm.id) AS members FROM watchlists w LEFT JOIN watchlist_members wm ON wm.watchlist_id = w.id GROUP BY w.name;"
$PSQL -d portfolio_db -c "SELECT COUNT(*) AS holding_count FROM holdings;"
$PSQL -d market_data_db -c "SELECT symbol, name FROM instruments LIMIT 10;"
echo "Seed complete."
