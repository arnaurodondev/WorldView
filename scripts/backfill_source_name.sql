-- ============================================================================
-- REVIEW BEFORE RUN — one-off backfill for R7 (document_source_metadata.source_name)
-- ============================================================================
-- Target DB : nlp_db  (S6 nlp-pipeline)
-- Issue     : docs/audits/2026-07-16-kg-data-quality-eval.md R7
--             15,325 / 15,325 rows have source_name IS NULL / '' after the news
--             backfill re-produced rows through a write path that had lost the
--             ISSUE-B derive-from-source_type fix (now re-applied in code:
--             article_consumer._display_source_name).
--
-- What this does
-- --------------
-- Populates source_name for existing rows by deriving a human-readable label
-- from the canonical source_type, using the SAME mapping the code now applies at
-- write time (_SOURCE_TYPE_DISPLAY_NAME). Only touches rows where source_name is
-- currently NULL or '' — never overwrites an already-populated value.
--
-- Safety
-- ------
--   * Wrapped in a transaction. It is left OPEN with a final ROLLBACK so a
--     copy-paste run is a DRY-RUN that prints the affected-row count and changes
--     nothing. To APPLY: replace the trailing ROLLBACK with COMMIT.
--   * Idempotent: re-running finds fewer/zero NULL rows and is a no-op on
--     already-populated rows.
--   * source_type='' / NULL rows are left untouched (nothing to label) — they
--     are counted separately below so the residual is visible.
-- ============================================================================

BEGIN;

-- Diagnostic: current empty count (expect ~15,325 before apply)
SELECT
    count(*) FILTER (WHERE source_name IS NULL OR source_name = '') AS empty_before,
    count(*) FILTER (WHERE source_name IS NULL OR source_name = '')
             FILTER (WHERE source_type IS NULL OR source_type = '') AS empty_and_no_source_type,
    count(*) AS total_rows
FROM document_source_metadata;

-- The derivation: explicit map first, else title-cased literal (sec_edgar -> 'Sec Edgar').
-- Mirrors article_consumer._display_source_name exactly.
WITH updated AS (
    UPDATE document_source_metadata dsm
    SET source_name = CASE dsm.source_type
            WHEN 'eodhd'              THEN 'EODHD'
            WHEN 'eodhd_ticker_news'  THEN 'EODHD'
            WHEN 'finnhub'            THEN 'Finnhub'
            WHEN 'newsapi'            THEN 'NewsAPI'
            WHEN 'sec_edgar'          THEN 'SEC EDGAR'
            WHEN 'polymarket'         THEN 'Polymarket'
            WHEN 'manual'             THEN 'Manual Upload'
            WHEN 'tenant_upload'      THEN 'Tenant Upload'
            -- Unknown/future adapter: title-case the literal (initcap approximates
            -- Python str.title(); acceptable for a display label).
            ELSE initcap(replace(dsm.source_type, '_', ' '))
        END
    WHERE (dsm.source_name IS NULL OR dsm.source_name = '')
      AND dsm.source_type IS NOT NULL
      AND dsm.source_type <> ''
    RETURNING 1
)
SELECT count(*) AS rows_updated FROM updated;

-- Diagnostic: residual empty count after the update (should be only the
-- source_type-less rows, if any).
SELECT count(*) FILTER (WHERE source_name IS NULL OR source_name = '') AS empty_after
FROM document_source_metadata;

-- DRY-RUN guard. Change to COMMIT to apply.
ROLLBACK;
