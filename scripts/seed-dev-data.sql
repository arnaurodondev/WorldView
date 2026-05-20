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

-- Portfolio instruments — UUIDs MUST match market_data_db.instruments below
-- so that quote/OHLCV/news lookups for a given UUID return the same security
-- in both databases (F-403, QA iter-4 2026-04-28).
--
-- PLAN-0089 F2 Step 8 (M-017): the OLD parallel ``11111111-...`` entity_id
-- namespace has been DROPPED. The portfolio_db.instruments.entity_id column
-- now equals the row PK (instruments.id) which in turn equals the
-- intelligence_db.canonical_entities.entity_id for the same security. One
-- canonical UUID per tradable security across all three DBs.
--
-- source_event_id is a dummy UUIDv4 used only for audit; it is NOT a FK.
INSERT INTO instruments (id, symbol, exchange, name, currency, asset_class, entity_id, source_event_id) VALUES
    ('01900000-0000-7000-8000-000000001001', 'AAPL',  'US', 'Apple Inc.',                 'USD', 'equity', '01900000-0000-7000-8000-000000001001', '23f6eeba-0cd6-4e4f-8824-db0a1b3b4257'),
    ('01900000-0000-7000-8000-000000001002', 'MSFT',  'US', 'Microsoft Corporation',      'USD', 'equity', '01900000-0000-7000-8000-000000001002', 'c77268c3-bbff-4b99-971d-c8cc7f43ab28'),
    ('01900000-0000-7000-8000-000000001003', 'GOOGL', 'US', 'Alphabet Inc.',              'USD', 'equity', '01900000-0000-7000-8000-000000001003', '69722c9f-13bd-4c55-91e0-776661e7789e'),
    ('01900000-0000-7000-8000-000000001004', 'TSLA',  'US', 'Tesla, Inc.',                'USD', 'equity', '01900000-0000-7000-8000-000000001004', 'f8e652de-e7ca-4576-b270-6a7a701bb8de'),
    ('01900000-0000-7000-8000-000000001005', 'AMZN',  'US', 'Amazon.com, Inc.',           'USD', 'equity', '01900000-0000-7000-8000-000000001005', '030536a9-444f-49a6-9987-73baa7cef7e9'),
    ('01900000-0000-7000-8000-000000001006', 'NVDA',  'US', 'NVIDIA Corporation',         'USD', 'equity', '01900000-0000-7000-8000-000000001006', 'a1b2c3d4-0006-4000-8000-000000000006')
ON CONFLICT (id) DO NOTHING;

-- Holdings for the demo portfolio — 5 positions across AAPL/MSFT/NVDA/TSLA/AMZN.
-- F-403 (iter-4): NVDA holding now references UUID 1006 (true NVDA in
-- market_data_db), not 1003 (which is GOOGL).
-- tenant_id must match the demo tenant above (foreign-key enforced via index only).
INSERT INTO holdings (id, portfolio_id, instrument_id, quantity, average_cost, currency, tenant_id, updated_at) VALUES
    ('01900000-0000-7000-8000-000000000400', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001001', 50.0, 178.50, 'USD', '01900000-0000-7000-8000-000000000001', NOW()),
    ('01900000-0000-7000-8000-000000000401', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001002', 30.0, 412.75, 'USD', '01900000-0000-7000-8000-000000000001', NOW()),
    ('01900000-0000-7000-8000-000000000402', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001006', 20.0, 141.20, 'USD', '01900000-0000-7000-8000-000000000001', NOW()),
    ('01900000-0000-7000-8000-000000000403', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001004', 15.0, 245.30, 'USD', '01900000-0000-7000-8000-000000000001', NOW()),
    ('01900000-0000-7000-8000-000000000404', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001005', 25.0, 185.60, 'USD', '01900000-0000-7000-8000-000000000001', NOW())
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
