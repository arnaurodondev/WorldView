-- ============================================================================
-- REVIEW BEFORE RUN — targeted relink for R6 (prediction_markets.event_id NULL)
-- ============================================================================
-- Target DB : market_data_db  (S4 market-data)
-- Issue     : docs/audits/2026-07-16-kg-data-quality-eval.md R6
--             SELECT count(*), count(event_id) FROM prediction_markets; -- 101 | 0
--             All 101 markets have event_id IS NULL despite a populated
--             prediction_events table. The prediction->event linkage
--             (prediction_market_repo.link_markets) is driven by the Polymarket
--             Gamma /events stream, which only carries member conditionIds for
--             ACTIVE events; these 101 are pre-existing ENDED events that are no
--             longer re-polled, so their markets never got the FK stamped.
--
-- Key insight — NO Gamma re-poll needed
-- -------------------------------------
-- prediction_market_snapshots.source_event_id (TEXT, NOT NULL, migration 005)
-- already records the Polymarket event-group id for every snapshot of a market.
-- Historical snapshots persist after a market ends, so we can recover each
-- market's event_id purely IN-DB by joining the market to its most-recent
-- snapshot's source_event_id — the same value link_markets would have stamped.
--
-- What this does
-- --------------
-- For each prediction_markets row with event_id IS NULL, set event_id to the
-- source_event_id of its most-recent snapshot, ONLY when that id actually exists
-- in prediction_events (so we never stamp a dangling group id). Mirrors
-- prediction_market_repo.link_markets semantics (event_id IS DISTINCT FROM guard,
-- updated_at bumped). Same DB as prediction_events — R9-safe, not cross-service.
--
-- Safety
-- ------
--   * Transaction left OPEN with a trailing ROLLBACK → copy-paste run is a
--     DRY-RUN that prints how many of the 101 are recoverable and changes
--     nothing. To APPLY: replace ROLLBACK with COMMIT.
--   * Idempotent: the ``event_id IS NULL`` filter + the DISTINCT-FROM effect
--     means a re-run only touches still-unlinked rows.
--   * Residual (markets with no snapshot carrying a known source_event_id) is
--     reported so the operator knows how many still need a Gamma /events re-poll.
-- ============================================================================

BEGIN;

-- Most-recent snapshot source_event_id per market (defensive: a market's event
-- membership is stable, but take the latest snapshot to be safe).
CREATE TEMP TABLE _market_event ON COMMIT DROP AS
SELECT DISTINCT ON (s.market_id)
       s.market_id,
       s.source_event_id
FROM prediction_market_snapshots s
WHERE s.source_event_id IS NOT NULL
  AND s.source_event_id <> ''
ORDER BY s.market_id, s.snapshot_at DESC;

-- Diagnostic: how many currently-NULL markets are recoverable in-DB?
SELECT
    count(*) FILTER (WHERE pm.event_id IS NULL) AS null_markets_total,
    count(*) FILTER (
        WHERE pm.event_id IS NULL
          AND me.source_event_id IS NOT NULL
          AND pe.event_id IS NOT NULL
    ) AS recoverable_in_db,
    count(*) FILTER (
        WHERE pm.event_id IS NULL
          AND (me.source_event_id IS NULL OR pe.event_id IS NULL)
    ) AS residual_needs_gamma_repoll
FROM prediction_markets pm
LEFT JOIN _market_event me ON me.market_id = pm.market_id
LEFT JOIN prediction_events pe ON pe.event_id = me.source_event_id;

-- The relink.
WITH relinked AS (
    UPDATE prediction_markets pm
    SET event_id = me.source_event_id,
        updated_at = now()
    FROM _market_event me
    JOIN prediction_events pe ON pe.event_id = me.source_event_id
    WHERE pm.market_id = me.market_id
      AND pm.event_id IS NULL
    RETURNING 1
)
SELECT count(*) AS markets_relinked FROM relinked;

-- Post-check: remaining NULLs (== residual_needs_gamma_repoll after a COMMIT).
SELECT count(*) AS event_id_still_null
FROM prediction_markets
WHERE event_id IS NULL;

-- Optionally refresh prediction_events.market_count to reflect the new links
-- (kept commented — enable if the operator wants counts reconciled in the same
-- transaction):
-- UPDATE prediction_events pe
-- SET market_count = sub.cnt, updated_at = now()
-- FROM (SELECT event_id, count(*) cnt FROM prediction_markets
--       WHERE event_id IS NOT NULL GROUP BY event_id) sub
-- WHERE pe.event_id = sub.event_id AND pe.market_count <> sub.cnt;

-- DRY-RUN guard. Change to COMMIT to apply.
ROLLBACK;
