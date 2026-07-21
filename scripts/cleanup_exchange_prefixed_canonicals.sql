-- ============================================================================
-- REVIEW BEFORE RUN — cleanup for R2 (exchange-prefixed junk canonical names)
-- ============================================================================
-- Target DB : intelligence_db  (owned by S6/S7; DDL by intelligence-migrations)
-- Issue     : docs/audits/2026-07-16-kg-data-quality-eval.md R2
--             87 canonical_entities rows whose canonical_name is a raw
--             exchange-prefixed ticker string minted from the news backfill:
--                 SELECT count(*) FROM canonical_entities
--                 WHERE canonical_name ~ '^(NYSE|NASDAQ|LSE|NSE):';   -- 87
--             e.g. 'NYSE: BCS', 'NYSE:GDDY', 'NASDAQ: AAPL'.
--
-- Code fix (prevents NEW ones): common.tickers.strip_exchange_prefix is now
-- applied at all three canonical-name mint sites (provisional_enrichment_core,
-- provisional_enrichment, provisional_queued_consumer). This script REPAIRS the
-- 87 rows that were already written before that guard.
--
-- THREE classes of junk row, handled differently:
--   CLASS A — the stripped bare name has NO existing canonical twin AND no other
--             junk row of the same entity_type strips to the same bare name
--             → safe in-place RENAME of canonical_name (+ its EXACT alias).
--   CLASS B — a proper canonical already owns the bare ticker / bare name
--             (a real duplicate) → must be MERGED (FK repoint across
--             intelligence_db + AGE + nlp_db), which is OUT OF SCOPE for a
--             single UPDATE. Use scripts/kg_merge_org_fi_duplicates.py's repoint
--             machinery (it already lists every FK). This script only REPORTS
--             Class B pairs so the operator can feed them to the merge tool.
--   CLASS C — INTRA-JUNK collision: two or more junk rows of the SAME entity_type
--             strip to the SAME bare name (e.g. "NYSE: BCS" + "LSE: BCS" -> "BCS",
--             a real cross-venue ADR case). Auto-renaming both would violate the
--             migration-0026 partial unique index (lower(canonical_name) WHERE
--             entity_type != 'financial_instrument') → the 2nd UPDATE aborts the
--             whole Class-A COMMIT (fail-safe today, but nothing applies). For FI
--             type it would silently create duplicate canonicals. So these are
--             ROUTED OUT of Class A and REPORTED for manual merge (pick a survivor,
--             merge the rest with the merge tool, THEN the survivor is bare).
--
-- Safety
-- ------
--   * Wrapped in a transaction left OPEN with a trailing ROLLBACK → copy-paste
--     run is a DRY-RUN (prints counts + the Class-A/B classification, changes
--     nothing). To APPLY the Class-A renames: replace ROLLBACK with COMMIT.
--   * Class B is NEVER auto-mutated here.
--   * Idempotent: after apply the '^EXCHANGE:' rows are renamed away, so a
--     re-run's regex match set shrinks toward the Class-B residual only.
-- ============================================================================

BEGIN;

-- Venue prefix regex — RECOGNISED exchange codes only (the four the audit's 87
-- rows actually carry, plus the most common global venues). Anchored + followed
-- by ':'. Using a venue ALTERNATION rather than a blind ``^[A-Z]{2,6}:`` avoids
-- mangling the ``TOKEN: REST`` shape shared by financial ratios / labels
-- (``EV:EBITDA`` -> "EBITDA", ``AI: Foundry`` -> "Foundry"). Mirrors the code
-- guard in common.tickers.strip_exchange_prefix (_EXCHANGE_PREFIX_CODES).
-- Pattern is duplicated in the WHERE, the regexp_replace, and the residual check
-- below — keep the three in sync if you extend the venue set.
--   '^(NYSE|NASDAQ|LSE|NSE|AMEX|OTC|OTCMKTS|TSX|TSXV|ASX|HKEX|SEHK|SGX|EPA|ETR|
--     LON|BME|SIX|JSE|TSE|JPX):\s*'

-- Reusable set of the offending rows + their stripped bare name.
CREATE TEMP TABLE _junk_canon ON COMMIT DROP AS
SELECT
    ce.entity_id,
    ce.canonical_name AS old_name,
    trim(regexp_replace(
        ce.canonical_name,
        '^(NYSE|NASDAQ|LSE|NSE|AMEX|OTC|OTCMKTS|TSX|TSXV|ASX|HKEX|SEHK|SGX|EPA|ETR|LON|BME|SIX|JSE|TSE|JPX):\s*',
        ''
    )) AS bare_name,
    ce.ticker,
    ce.entity_type
FROM canonical_entities ce
WHERE ce.canonical_name ~ '^(NYSE|NASDAQ|LSE|NSE|AMEX|OTC|OTCMKTS|TSX|TSXV|ASX|HKEX|SEHK|SGX|EPA|ETR|LON|BME|SIX|JSE|TSE|JPX):\s*\S';

SELECT count(*) AS junk_rows_found FROM _junk_canon;   -- expect ~87

-- ── Classification (3-way) ───────────────────────────────────────────────────
-- twin_entity_id       : a DISTINCT canonical already owns the bare name → CLASS B
-- intra_junk_siblings  : how many OTHER junk rows strip to the SAME bare_name with
--                        the SAME entity_type → the intra-junk collision. If >0 the
--                        rows would BOTH rename to the same lower(canonical_name);
--                        for entity_type != 'financial_instrument' the migration-0026
--                        partial unique index (lower(canonical_name) WHERE
--                        entity_type != 'financial_instrument') rejects the 2nd
--                        UPDATE → the whole Class-A COMMIT aborts. For FI type it
--                        would silently create duplicate canonicals. EITHER way we
--                        must NOT auto-rename → route to CLASS C (manual merge).
CREATE TEMP TABLE _classified ON COMMIT DROP AS
SELECT
    j.*,
    twin.entity_id     AS twin_entity_id,
    twin.canonical_name AS twin_name,
    (
        SELECT count(*)
        FROM _junk_canon j2
        WHERE j2.entity_id <> j.entity_id
          AND lower(j2.bare_name) = lower(j.bare_name)
          AND j2.entity_type = j.entity_type
    ) AS intra_junk_siblings
FROM _junk_canon j
LEFT JOIN LATERAL (
    SELECT ce2.entity_id, ce2.canonical_name
    FROM canonical_entities ce2
    WHERE ce2.entity_id <> j.entity_id
      AND lower(ce2.canonical_name) = lower(j.bare_name)
    LIMIT 1
) twin ON TRUE;

-- Derive the class label. Precedence: intra-junk collision (C) is checked FIRST,
-- because two colliding junk rows must be merged among themselves before either
-- can safely take the bare name — even if an external twin also exists.
-- Class A applies ONLY when there is exactly one safe owner: no external twin AND
-- no same-type intra-junk sibling.
CREATE TEMP TABLE _classified_labelled ON COMMIT DROP AS
SELECT c.*,
       CASE
           WHEN c.intra_junk_siblings > 0            THEN 'C_intra_junk_collision'
           WHEN c.twin_entity_id IS NOT NULL         THEN 'B_external_twin_merge'
           WHEN c.bare_name = ''                     THEN 'C_intra_junk_collision'  -- defensive: never rename to blank
           ELSE                                            'A_safe_rename'
       END AS cls
FROM _classified c;

-- Report the 3-way split.
SELECT
    count(*) FILTER (WHERE cls = 'A_safe_rename')          AS class_a_safe_rename,
    count(*) FILTER (WHERE cls = 'B_external_twin_merge')  AS class_b_external_twin_merge,
    count(*) FILTER (WHERE cls = 'C_intra_junk_collision') AS class_c_intra_junk_collision
FROM _classified_labelled;

-- Full Class-B report (feed these into scripts/kg_merge_org_fi_duplicates.py).
SELECT entity_id AS junk_entity_id, old_name, bare_name, entity_type,
       twin_entity_id AS merge_into_entity_id, twin_name
FROM _classified_labelled
WHERE cls = 'B_external_twin_merge'
ORDER BY bare_name;

-- Full Class-C report (intra-junk collisions — cross-venue ADR duplicates like
-- "NYSE: BCS" + "LSE: BCS" both -> "BCS". Pick a survivor and merge the rest with
-- the merge tool BEFORE renaming; this script never auto-touches them).
SELECT entity_id AS junk_entity_id, old_name, bare_name, entity_type, ticker,
       intra_junk_siblings
FROM _classified_labelled
WHERE cls = 'C_intra_junk_collision'
ORDER BY lower(bare_name), entity_type, old_name;

-- ── CLASS A: safe in-place rename (single safe owner only) ──────────────────
-- 1) canonical_name
WITH renamed AS (
    UPDATE canonical_entities ce
    SET canonical_name = c.bare_name
    FROM _classified_labelled c
    WHERE ce.entity_id = c.entity_id
      AND c.cls = 'A_safe_rename'
    RETURNING 1
)
SELECT count(*) AS class_a_canonical_renamed FROM renamed;

-- 2) the matching EXACT alias row (keep normalized_alias_text consistent).
--    Only rows whose alias_text still carries the exchange prefix. Defensive
--    NOT EXISTS guard: skip if ANOTHER entity already owns that normalized alias
--    (avoids any residual unique-constraint abort on entity_aliases).
WITH alias_fixed AS (
    UPDATE entity_aliases ea
    SET alias_text            = c.bare_name,
        normalized_alias_text = lower(c.bare_name)
    FROM _classified_labelled c
    WHERE ea.entity_id = c.entity_id
      AND c.cls = 'A_safe_rename'
      AND ea.alias_type = 'EXACT'
      AND ea.alias_text ~ '^(NYSE|NASDAQ|LSE|NSE|AMEX|OTC|OTCMKTS|TSX|TSXV|ASX|HKEX|SEHK|SGX|EPA|ETR|LON|BME|SIX|JSE|TSE|JPX):\s*\S'
      AND NOT EXISTS (
          SELECT 1 FROM entity_aliases ea2
          WHERE ea2.entity_id <> ea.entity_id
            AND ea2.normalized_alias_text = lower(c.bare_name)
      )
    RETURNING 1
)
SELECT count(*) AS class_a_aliases_fixed FROM alias_fixed;

-- Residual check: recognised-venue-prefixed canonical_names remaining after a
-- Class-A COMMIT (should equal class_b + class_c).
SELECT count(*) AS exchange_prefixed_remaining
FROM canonical_entities
WHERE canonical_name ~ '^(NYSE|NASDAQ|LSE|NSE|AMEX|OTC|OTCMKTS|TSX|TSXV|ASX|HKEX|SEHK|SGX|EPA|ETR|LON|BME|SIX|JSE|TSE|JPX):\s*\S';

-- DRY-RUN guard. Change to COMMIT to apply the CLASS-A renames.
-- (Class B and Class C still require scripts/kg_merge_org_fi_duplicates.py --apply.)
ROLLBACK;
