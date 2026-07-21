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
-- Two classes of junk row, handled differently:
--   CLASS A — the stripped bare name has NO existing canonical twin
--             → safe in-place RENAME of canonical_name (+ its EXACT alias).
--   CLASS B — a proper canonical already owns the bare ticker / bare name
--             (a real duplicate) → must be MERGED (FK repoint across
--             intelligence_db + AGE + nlp_db), which is OUT OF SCOPE for a
--             single UPDATE. Use scripts/kg_merge_org_fi_duplicates.py's repoint
--             machinery (it already lists every FK). This script only REPORTS
--             Class B pairs so the operator can feed them to the merge tool.
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

-- Reusable set of the offending rows + their stripped bare name.
-- The regex strips a leading 2-6 uppercase-letter venue code + ':' + optional ws.
CREATE TEMP TABLE _junk_canon ON COMMIT DROP AS
SELECT
    ce.entity_id,
    ce.canonical_name                                              AS old_name,
    trim(regexp_replace(ce.canonical_name, '^[A-Z]{2,6}:\s*', '')) AS bare_name,
    ce.ticker,
    ce.entity_type
FROM canonical_entities ce
WHERE ce.canonical_name ~ '^[A-Z]{2,6}:\s*\S';

SELECT count(*) AS junk_rows_found FROM _junk_canon;   -- expect ~87

-- Classify: does a DISTINCT canonical already own the bare name (case-insensitive)?
CREATE TEMP TABLE _classified ON COMMIT DROP AS
SELECT
    j.*,
    twin.entity_id AS twin_entity_id,
    twin.canonical_name AS twin_name
FROM _junk_canon j
LEFT JOIN LATERAL (
    SELECT ce2.entity_id, ce2.canonical_name
    FROM canonical_entities ce2
    WHERE ce2.entity_id <> j.entity_id
      AND lower(ce2.canonical_name) = lower(j.bare_name)
    LIMIT 1
) twin ON TRUE;

-- Report the split.
SELECT
    count(*) FILTER (WHERE twin_entity_id IS NULL)     AS class_a_safe_rename,
    count(*) FILTER (WHERE twin_entity_id IS NOT NULL) AS class_b_needs_merge
FROM _classified;

-- Full Class-B report (feed these into the merge tool).
SELECT entity_id AS junk_entity_id, old_name, bare_name,
       twin_entity_id AS merge_into_entity_id, twin_name
FROM _classified
WHERE twin_entity_id IS NOT NULL
ORDER BY bare_name;

-- ── CLASS A: safe in-place rename (only where no twin exists) ───────────────
-- 1) canonical_name
WITH renamed AS (
    UPDATE canonical_entities ce
    SET canonical_name = c.bare_name
    FROM _classified c
    WHERE ce.entity_id = c.entity_id
      AND c.twin_entity_id IS NULL
      AND c.bare_name <> ''
    RETURNING 1
)
SELECT count(*) AS class_a_canonical_renamed FROM renamed;

-- 2) the matching EXACT alias row (keep normalized_alias_text consistent).
--    Only rows whose alias_text still carries the exchange prefix.
WITH alias_fixed AS (
    UPDATE entity_aliases ea
    SET alias_text            = c.bare_name,
        normalized_alias_text = lower(c.bare_name)
    FROM _classified c
    WHERE ea.entity_id = c.entity_id
      AND c.twin_entity_id IS NULL
      AND c.bare_name <> ''
      AND ea.alias_type = 'EXACT'
      AND ea.alias_text ~ '^[A-Z]{2,6}:\s*\S'
    RETURNING 1
)
SELECT count(*) AS class_a_aliases_fixed FROM alias_fixed;

-- Residual check: exchange-prefixed canonical_names remaining (should equal the
-- Class-B count after a Class-A COMMIT).
SELECT count(*) AS exchange_prefixed_remaining
FROM canonical_entities
WHERE canonical_name ~ '^[A-Z]{2,6}:\s*\S';

-- DRY-RUN guard. Change to COMMIT to apply the CLASS-A renames.
-- (Class B still requires scripts/kg_merge_org_fi_duplicates.py --apply.)
ROLLBACK;
