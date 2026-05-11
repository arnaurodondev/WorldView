-- Seed: GICS sector and industry group entities for intelligence_db
-- Idempotent: ON CONFLICT (entity_id) DO NOTHING
--
-- Populates canonical_entities with:
--   11 GICS sector entities   (entity_type = 'sector')
--   27 GICS industry groups   (entity_type = 'sector')
--
-- entity_ids are pre-generated stable UUIDv7 values — do NOT change them
-- across re-runs; they are referenced by FundamentalsRefreshWorker (Wave C-4)
-- when upserting is_in_sector / is_in_industry relations.
--
-- Source: GICS taxonomy (Global Industry Classification Standard) published
-- by MSCI and S&P Global. Sector names are official GICS Level-1 names.

-- ─── Sector entities ──────────────────────────────────────────────────────────

INSERT INTO canonical_entities (entity_id, canonical_name, entity_type)
VALUES
    ('0195daad-a001-7001-8001-000000000001', 'Energy',                    'sector'),
    ('0195daad-a002-7002-8002-000000000002', 'Materials',                 'sector'),
    ('0195daad-a003-7003-8003-000000000003', 'Industrials',               'sector'),
    ('0195daad-a004-7004-8004-000000000004', 'Consumer Discretionary',    'sector'),
    ('0195daad-a005-7005-8005-000000000005', 'Consumer Staples',          'sector'),
    ('0195daad-a006-7006-8006-000000000006', 'Health Care',               'sector'),
    ('0195daad-a007-7007-8007-000000000007', 'Financials',                'sector'),
    ('0195daad-a008-7008-8008-000000000008', 'Information Technology',    'sector'),
    ('0195daad-a009-7009-8009-000000000009', 'Communication Services',    'sector'),
    ('0195daad-a00a-700a-800a-00000000000a', 'Utilities',                 'sector'),
    ('0195daad-a00b-700b-800b-00000000000b', 'Real Estate',               'sector')
ON CONFLICT (entity_id) DO NOTHING;

-- ─── Industry group entities ──────────────────────────────────────────────────

INSERT INTO canonical_entities (entity_id, canonical_name, entity_type)
VALUES
    -- Energy (2)
    ('0195daad-b001-7001-8001-000000000001', 'Energy Equipment & Services',                      'sector'),
    ('0195daad-b002-7002-8002-000000000002', 'Oil, Gas & Consumable Fuels',                      'sector'),

    -- Materials (3)
    ('0195daad-b003-7003-8003-000000000003', 'Chemicals',                                        'sector'),
    ('0195daad-b004-7004-8004-000000000004', 'Metals & Mining',                                  'sector'),
    ('0195daad-b005-7005-8005-000000000005', 'Paper & Forest Products',                          'sector'),

    -- Industrials (3)
    ('0195daad-b006-7006-8006-000000000006', 'Capital Goods',                                    'sector'),
    ('0195daad-b007-7007-8007-000000000007', 'Commercial & Professional Services',               'sector'),
    ('0195daad-b008-7008-8008-000000000008', 'Transportation',                                   'sector'),

    -- Consumer Discretionary (3)
    ('0195daad-b009-7009-8009-000000000009', 'Automobiles & Components',                         'sector'),
    ('0195daad-b00a-700a-800a-00000000000a', 'Retailing',                                        'sector'),
    ('0195daad-b00b-700b-800b-00000000000b', 'Hotels, Restaurants & Leisure',                    'sector'),

    -- Consumer Staples (2)
    ('0195daad-b00c-700c-800c-00000000000c', 'Food, Beverage & Tobacco',                         'sector'),
    ('0195daad-b00d-700d-800d-00000000000d', 'Household & Personal Products',                    'sector'),

    -- Health Care (2)
    ('0195daad-b00e-700e-800e-00000000000e', 'Health Care Equipment & Services',                 'sector'),
    ('0195daad-b00f-700f-800f-00000000000f', 'Pharmaceuticals, Biotechnology & Life Sciences',  'sector'),

    -- Financials (3)
    ('0195daad-b010-7010-8010-000000000010', 'Banks',                                            'sector'),
    ('0195daad-b011-7011-8011-000000000011', 'Insurance',                                        'sector'),
    ('0195daad-b012-7012-8012-000000000012', 'Capital Markets',                                  'sector'),

    -- Information Technology (3)
    ('0195daad-b013-7013-8013-000000000013', 'Software & Services',                              'sector'),
    ('0195daad-b014-7014-8014-000000000014', 'Technology Hardware & Equipment',                  'sector'),
    ('0195daad-b015-7015-8015-000000000015', 'Semiconductors & Semiconductor Equipment',         'sector'),

    -- Communication Services (2)
    ('0195daad-b016-7016-8016-000000000016', 'Media & Entertainment',                            'sector'),
    ('0195daad-b017-7017-8017-000000000017', 'Telecommunication Services',                       'sector'),

    -- Utilities (2)
    ('0195daad-b018-7018-8018-000000000018', 'Electric Utilities',                               'sector'),
    ('0195daad-b019-7019-8019-000000000019', 'Gas Utilities',                                    'sector'),

    -- Real Estate (2)
    ('0195daad-b01a-701a-801a-00000000001a', 'Equity Real Estate Investment Trusts (REITs)',     'sector'),
    ('0195daad-b01b-701b-801b-00000000001b', 'Real Estate Management & Development',             'sector')
ON CONFLICT (entity_id) DO NOTHING;

-- ─── PLAN-0057 C-5 (T-C-5-03): EXACT self-alias rows ──────────────────────────
--
-- Every sector + industry_group canonical needs an EXACT alias row whose text
-- equals the canonical name so Stage-1 alias-exact resolution in the NLP
-- pipeline can match e.g. "Health Care" → entity_id directly. Without this
-- the resolver would need a name-fallback path (which Wave A makes optional).
--
-- Idempotent via the partial UNIQUE index ``uidx_entity_aliases_entity_norm_type``
-- installed by migration 0008 (Wave A-2). Re-running this seed is safe.
--
-- We restrict the SELECT to the exact pre-generated entity_id namespace
-- (0195daad-a0xx / 0195daad-b0xx) so we do not accidentally touch unrelated
-- canonical rows that may have been inserted by a later seed.

INSERT INTO entity_aliases (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source)
SELECT entity_id, canonical_name, lower(canonical_name), 'EXACT', true, '003_seed'
FROM canonical_entities
WHERE entity_type IN ('sector', 'sector')
  AND (
        entity_id::text LIKE '0195daad-a0%'  -- the 11 sector rows above
     OR entity_id::text LIKE '0195daad-b0%'  -- the 27 industry_group rows above
  )
ON CONFLICT (entity_id, normalized_alias_text, alias_type) WHERE is_active = true
DO NOTHING;
