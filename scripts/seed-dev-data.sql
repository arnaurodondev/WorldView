-- scripts/seed-dev-data.sql — Development seed data
-- Run via: make seed (after make dev)
--
-- Creates sample instruments, entities, and test users so the UI
-- has data to display without running the full ingestion pipeline.
--
-- IMPORTANT: All UUIDs use the UUIDv7-ish prefix 01900000-0000-7000-8000-...
-- for easy identification as seed data. They are syntactically valid UUIDs.

-- ── Portfolio DB ─────────────────────────────────────────────────────────────
-- Schema: tenants(id, name, status, created_at)
--         users(id, tenant_id, email, status, created_at, external_id, role)
--         portfolios(id, tenant_id, owner_id, name, currency, status, created_at)
--         watchlists(id, tenant_id, user_id, name, status, created_at)

\connect portfolio_db;

-- Sample tenant (for testing without Zitadel)
INSERT INTO tenants (id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000001', 'Demo Tenant', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

-- Sample user (matches the demo user created by POST /v1/auth/dev-login)
-- external_id = 'dev-user' matches the sub claim in the dev-login JWT
INSERT INTO users (id, tenant_id, email, status, created_at, external_id, role) VALUES
    ('01900000-0000-7000-8000-000000000010', '01900000-0000-7000-8000-000000000001', 'demo@worldview.dev', 'active', NOW(), 'dev-user', 'owner')
ON CONFLICT (id) DO NOTHING;

-- Sample portfolio
INSERT INTO portfolios (id, tenant_id, owner_id, name, currency, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Demo Portfolio', 'USD', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

-- Sample watchlist
INSERT INTO watchlists (id, tenant_id, user_id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Tech Watchlist', 'active', NOW())
ON CONFLICT (id) DO NOTHING;


-- ── Market Data DB ───────────────────────────────────────────────────────────
-- Schema: securities(id, figi, isin, name, sector, industry, country, currency, created_at, updated_at)
--         instruments(id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals,
--                     name, isin, sector, industry, country, currency_code, created_at, updated_at)

\connect market_data_db;

-- Sample securities (parent entities for instruments)
INSERT INTO securities (id, isin, name, sector, industry, country, currency, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000002001', 'US0378331005', 'Apple Inc.', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002002', 'US5949181045', 'Microsoft Corporation', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002003', 'US02079K3059', 'Alphabet Inc.', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002004', 'US88160R1014', 'Tesla, Inc.', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000002005', 'US0231351067', 'Amazon.com, Inc.', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- Sample instruments (one per security — primary listing)
INSERT INTO instruments (id, security_id, symbol, exchange, has_ohlcv, has_quotes, has_fundamentals, name, isin, sector, industry, country, currency_code, created_at, updated_at) VALUES
    ('01900000-0000-7000-8000-000000001001', '01900000-0000-7000-8000-000000002001', 'AAPL', 'US', true, true, true, 'Apple Inc.', 'US0378331005', 'Technology', 'Consumer Electronics', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001002', '01900000-0000-7000-8000-000000002002', 'MSFT', 'US', true, true, true, 'Microsoft Corporation', 'US5949181045', 'Technology', 'Software - Infrastructure', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001003', '01900000-0000-7000-8000-000000002003', 'GOOGL', 'US', true, true, true, 'Alphabet Inc.', 'US02079K3059', 'Technology', 'Internet Content & Information', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001004', '01900000-0000-7000-8000-000000002004', 'TSLA', 'US', true, true, true, 'Tesla, Inc.', 'US88160R1014', 'Consumer Cyclical', 'Auto Manufacturers', 'US', 'USD', NOW(), NOW()),
    ('01900000-0000-7000-8000-000000001005', '01900000-0000-7000-8000-000000002005', 'AMZN', 'US', true, true, true, 'Amazon.com, Inc.', 'US0231351067', 'Consumer Cyclical', 'Internet Retail', 'US', 'USD', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
