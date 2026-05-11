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
-- ── F-403 (CRITICAL, QA iter-4 2026-04-28) ──────────────────────────────────
-- Single source of truth for the seeded ``instruments.id → symbol`` mapping.
-- Both ``portfolio_db.instruments`` and ``market_data_db.instruments`` MUST
-- agree on this map; otherwise quote/OHLCV/news lookups quote the wrong
-- ticker (the iter-4 bug: same UUID was NVDA in portfolio_db but GOOGL in
-- market_data_db, so a Demo holding tagged "NVDA" silently received GOOGL
-- prices). The market_data_db side is canonical because it is the upstream
-- producer of ``market.instrument.created`` events; portfolio_db.instruments
-- is the local cache that consumes those events.
--
-- Mapping (matches market_data_db.instruments below):
--   1001 AAPL, 1002 MSFT, 1003 GOOGL, 1004 TSLA, 1005 AMZN,
--   1006 NVDA, 1007 META,  1008 JPM,  1009 NFLX, 1010 DIS

INSERT INTO tenants (id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000001', 'Demo Tenant', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO users (id, tenant_id, email, status, created_at, external_id, role) VALUES
    ('01900000-0000-7000-8000-000000000010', '01900000-0000-7000-8000-000000000001', 'demo@worldview.dev', 'active', NOW(), 'dev-user', 'owner')
ON CONFLICT (id) DO NOTHING;

INSERT INTO portfolios (id, tenant_id, owner_id, name, kind, currency, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Demo Portfolio', 'manual', 'USD', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

-- F-402 (MAJOR, QA iter-4): extend portfolio_db.instruments to mirror
-- market_data_db.instruments for all 10 seeded symbols. The Kafka
-- ``market.instrument.created`` consumer normally fills this cache, but the
-- seed flow doesn't replay events (the consumer only sees forward-going
-- traffic). Watchlist rows referencing 1006/1007/1009/1010 stayed stuck in
-- "resolving…" forever because the local cache had nothing to join on.
--
-- F-403 (CRITICAL, QA iter-4): UUID 1003 must be GOOGL (matching
-- market_data_db). Demo's NVDA holding moved to UUID 1006 below.
INSERT INTO instruments (id, symbol, exchange, name, currency, asset_class, entity_id, source_event_id) VALUES
    ('01900000-0000-7000-8000-000000001001', 'AAPL',  'US', 'Apple Inc.',                 'USD', 'equity', '11111111-0001-7000-8000-000000000001', '23f6eeba-0cd6-4e4f-8824-db0a1b3b4257'),
    ('01900000-0000-7000-8000-000000001002', 'MSFT',  'US', 'Microsoft Corporation',      'USD', 'equity', '11111111-0002-7000-8000-000000000001', 'c77268c3-bbff-4b99-971d-c8cc7f43ab28'),
    ('01900000-0000-7000-8000-000000001003', 'GOOGL', 'US', 'Alphabet Inc.',              'USD', 'equity', '11111111-0003-7000-8000-000000000001', '69722c9f-13bd-4c55-91e0-776661e7789e'),
    ('01900000-0000-7000-8000-000000001004', 'TSLA',  'US', 'Tesla, Inc.',                'USD', 'equity', '11111111-0005-7000-8000-000000000001', 'f8e652de-e7ca-4576-b270-6a7a701bb8de'),
    ('01900000-0000-7000-8000-000000001005', 'AMZN',  'US', 'Amazon.com, Inc.',           'USD', 'equity', '11111111-0004-7000-8000-000000000001', '030536a9-444f-49a6-9987-73baa7cef7e9'),
    ('01900000-0000-7000-8000-000000001006', 'NVDA',  'US', 'NVIDIA Corporation',         'USD', 'equity', '11111111-0006-7000-8000-000000000001', 'a1b2c3d4-0006-4000-8000-000000000006'),
    ('01900000-0000-7000-8000-000000001007', 'META',  'US', 'Meta Platforms, Inc.',       'USD', 'equity', '11111111-0007-7000-8000-000000000001', 'a1b2c3d4-0007-4000-8000-000000000007'),
    ('01900000-0000-7000-8000-000000001008', 'JPM',   'US', 'JPMorgan Chase & Co.',       'USD', 'equity', '11111111-0008-7000-8000-000000000001', 'a1b2c3d4-0008-4000-8000-000000000008'),
    ('01900000-0000-7000-8000-000000001009', 'NFLX',  'US', 'Netflix, Inc.',              'USD', 'equity', '11111111-0009-7000-8000-000000000001', 'a1b2c3d4-0009-4000-8000-000000000009'),
    ('01900000-0000-7000-8000-000000001010', 'DIS',   'US', 'The Walt Disney Company',    'USD', 'equity', '11111111-0010-7000-8000-000000000001', 'a1b2c3d4-0010-4000-8000-000000000010')
ON CONFLICT (id) DO UPDATE SET
    -- F-403 reseed: when re-running ``make seed`` against a DB that already
    -- holds the OLD (incorrect) NVDA-on-1003 mapping we MUST overwrite the
    -- symbol/name fields, otherwise the cache stays poisoned. The columns
    -- listed here are the ones that uniquely identify a security; we leave
    -- ``entity_id`` alone so that any production-style entity already
    -- linked to this row by the consumer is preserved.
    symbol = EXCLUDED.symbol,
    name = EXCLUDED.name,
    exchange = EXCLUDED.exchange,
    currency = EXCLUDED.currency,
    asset_class = EXCLUDED.asset_class;

INSERT INTO watchlists (id, tenant_id, user_id, name, status, created_at) VALUES
    ('01900000-0000-7000-8000-000000000200', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'Tech Watchlist', 'active', NOW()),
    ('01900000-0000-7000-8000-000000000201', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'EV & Clean Energy', 'active', NOW()),
    ('01900000-0000-7000-8000-000000000202', '01900000-0000-7000-8000-000000000001', '01900000-0000-7000-8000-000000000010', 'E-Commerce & Retail', 'active', NOW())
ON CONFLICT (id) DO NOTHING;

-- F-304 (QA iter-3 2026-04-28): the entity_id stored on watchlist_members
-- is the *KG entity id*, which equals the value populated on
-- ``instruments.entity_id`` by the market.instrument.created Kafka
-- consumer. Pre-fix the seed used the ``instruments.id`` row PK
-- (01900000-0000-7000-8000-0000000010xx) for both columns, which is
-- correct for ``watchlist_members.entity_id == instruments.id`` lookups
-- but fails the ``JOIN ON instruments.entity_id`` path used by the
-- denorm backfill. We now insert the *same* UUID into both
-- ``watchlist_members.entity_id`` AND ``instruments.entity_id`` (see
-- the matching market_data_db section below) so either join path
-- resolves cleanly. Combined with the dual-key fallback in
-- ``backfill_watchlist_member_denorm.py``, both seed-style and
-- production-style data resolve successfully.
--
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

-- F-304: ensure portfolio_db's ``instruments.entity_id`` is populated to
-- match the seed's watchlist_members.entity_id. Without this the backfill
-- script's join ``ON instruments.entity_id = wm.entity_id`` returns no
-- rows. We set entity_id = id (the seed's convention) so either join key
-- works. Idempotent — only writes when the column is NULL so production
-- rows with a real KG entity_id are never overwritten.
UPDATE instruments
SET entity_id = id
WHERE entity_id IS NULL
  AND id IN (
    '01900000-0000-7000-8000-000000001001',
    '01900000-0000-7000-8000-000000001002',
    '01900000-0000-7000-8000-000000001003',
    '01900000-0000-7000-8000-000000001004',
    '01900000-0000-7000-8000-000000001005',
    '01900000-0000-7000-8000-000000001006',
    '01900000-0000-7000-8000-000000001007',
    '01900000-0000-7000-8000-000000001008',
    '01900000-0000-7000-8000-000000001009',
    '01900000-0000-7000-8000-000000001010'
  );

-- Demo holdings for the original 5 instruments
-- F-201 (QA iter-2): seed must be RESET-idempotent so re-running ``make seed``
-- fully restores holdings even if a prior run zeroed them. We use ON CONFLICT
-- DO UPDATE so an existing row's quantity/average_cost are overwritten with
-- the seed values rather than left at whatever the repair script wrote (or
-- whatever the live brokerage sync produced). Other columns are also
-- refreshed for consistency.
--
-- F-403 (QA iter-4 2026-04-28): Demo's NVDA position moved from instrument_id
-- 1003 (which is now GOOGL — matching market_data_db) to instrument_id 1006
-- (the real NVDA UUID). Cost basis $141.20 stays — that was originally NVDA's
-- cost. Without this remap, every Demo "NVDA" market-data lookup would still
-- return GOOGL data despite the cache fix above.
--
-- Hardening: we delete any orphan Demo holdings that point at the OLD NVDA
-- mapping (instrument_id=1003) BEFORE the upsert so a leftover row from a
-- pre-iter-4 seed doesn't leave Demo with an extra GOOGL position. Scoped
-- to the demo portfolio so it's safe to run against any DB state.
DELETE FROM holdings
WHERE portfolio_id = '01900000-0000-7000-8000-000000000100'
  AND instrument_id = '01900000-0000-7000-8000-000000001003'
  AND id <> '01900000-0000-7000-8000-000000000402';

INSERT INTO holdings (id, portfolio_id, instrument_id, tenant_id, quantity, average_cost, currency, updated_at) VALUES
    ('01900000-0000-7000-8000-000000000400', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001001', '01900000-0000-7000-8000-000000000001', 50.00000000, 178.50000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000401', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001002', '01900000-0000-7000-8000-000000000001', 30.00000000, 412.75000000, 'USD', NOW()),
    -- holding 0402 was NVDA on the (now-corrected) UUID 1003. Move to 1006.
    ('01900000-0000-7000-8000-000000000402', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001006', '01900000-0000-7000-8000-000000000001', 20.00000000, 141.20000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000403', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001004', '01900000-0000-7000-8000-000000000001', 15.00000000, 245.30000000, 'USD', NOW()),
    ('01900000-0000-7000-8000-000000000404', '01900000-0000-7000-8000-000000000100', '01900000-0000-7000-8000-000000001005', '01900000-0000-7000-8000-000000000001', 25.00000000, 185.60000000, 'USD', NOW())
ON CONFLICT (id) DO UPDATE SET
    -- F-403 reseed: instrument_id is part of the upsert payload — old DBs
    -- where holding 0402 still points at 1003 must be remapped to 1006.
    instrument_id = EXCLUDED.instrument_id,
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
