# F-DB-003 + F-DB-004 — Deferred Investigation

**Date**: 2026-05-26
**Source audit**: `docs/audits/2026-05-26-qa-plan-0093-iter-9-report.md`
**Decision**: DEFER — both findings are blocked on upstream-pipeline fixes; FIX-in-place would either be a no-op (no source data) or would conflict with a parallel agent's work.

---

## F-DB-003 — `document_source_metadata.impact_score` 100% NULL (7,364 / 7,364)

### Confirmed root cause

**Upstream data is empty**. The PLAN-0093 T-C-3-03 write path is wired correctly. The chain is:

1. `PriceImpactLabellingWorker` → upserts `article_impact_windows` AND calls `_update_dsm_impact_scores(session, all_windows)` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py:144-151`).
2. `ArticleRelevanceScoringWorker._write_impact_scores` → `UPDATE document_source_metadata SET impact_score = sub.max_impact FROM (SELECT ... article_impact_windows ...)` (`services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py:445-461`).

Both writers exist and are wired into running containers. The query, however, has nothing to read:

```text
nlp_db> SELECT COUNT(*) FROM article_impact_windows;
0

nlp_db> SELECT COUNT(DISTINCT em.doc_id) AS candidates
        FROM entity_mentions em ... WHERE em.resolved_entity_id IS NOT NULL
        AND em.mention_class = 'financial_instrument' ...
0

nlp_db> SELECT
          COUNT(*) FILTER (WHERE resolved_entity_id IS NOT NULL) AS resolved_mentions,
          COUNT(*) FILTER (WHERE mention_class = 'financial_instrument') AS fi_mentions
        FROM entity_mentions;
resolved_mentions | fi_mentions
0                | 0
```

There are **zero resolved `financial_instrument` mentions in the entire `nlp_db`**. The PriceImpactLabellingWorker query `get_articles_needing_windows` filters on `em.resolved_entity_id IS NOT NULL AND em.mention_class = 'financial_instrument'`, producing 0 candidates per cycle. Therefore `article_impact_windows` stays empty, therefore `_write_impact_scores`/`_update_dsm_impact_scores` UPDATE matches 0 rows.

### Why it can't be fixed in this worktree

The bug is in NLP Block 3/4 (entity extraction + resolution): no FI mentions are being persisted with `resolved_entity_id` set. Looking at the QA audit, F-NPL-001 (mention resolution coverage) and the historic "Block 4 silent drop" pattern (`feedback_prompt_input_mismatch.md`) are the relevant upstream issues. Fixing those is the job of the NLP-pipeline / mention-resolution agent; backfilling `impact_score` from a non-existent source table here would do nothing.

### Concrete next action

Wait for the mention-resolution / FI-canonical-link pipeline to start populating `entity_mentions.resolved_entity_id` for `mention_class='financial_instrument'`. Once that lands, `PriceImpactLabellingWorker` (cycle 4h) will start writing to `article_impact_windows`, and `ArticleRelevanceScoringWorker` will start populating `impact_score`. No PLAN-0093 code change is required.

---

## F-DB-004 — `entity_embedding_state.fundamentals_ohlcv` 100% NULL (2,405 / 2,405)

### Confirmed root cause

**All 2,405 financial_instrument entities are parked in PLAN-0093 D-2 backoff**.

The PLAN-0093 T-C-4-03 scope filter is correct (only `financial_instrument` entities have rows in this view — verified: `intelligence_db.canonical_entities WHERE entity_type='financial_instrument' = 2405`). The worker fires every 5 min (`worker_fundamentals_refresh_interval_s: 300`). Recent cycles show:

```text
{"refreshed": 0, "skipped_non_ticker": 0, "earnings_events_inserted": 0,
 "relations_upserted": 0, "backoff_escalations": 0, "backoff_resets": 0,
 "failure_breakdown": {}, "event": "fundamentals_refresh_worker_complete"}
```

Each cycle logs ~30 `fundamentals_refresh_backoff_skip` events at `backoff_seconds: 3600`. The PLAN-0093 D-2 path (`fundamentals_refresh.py:498-509`) writes `embedding=None` and pushes `next_refresh_at = now + backoff_seconds` for backoff-skipped entities, which is exactly the NULL state we observe.

DB row distribution:

```text
intelligence_db> SELECT date_trunc('day', next_refresh_at), COUNT(*)
                 FROM entity_embedding_state WHERE view_type='fundamentals_ohlcv' GROUP BY 1;
2026-05-27 |   811   ← 1h backoff stage
2026-05-28 |   236   ← 1d backoff stage
2026-05-31 |    53   ← intermediate
2027-05-23 |  1097   ← terminal (1yr) backoff stage
2027-05-24 |   208   ← terminal (1yr) backoff stage
```

**1,305 of 2,405 entities (54%) are parked one year out** because they previously hit the 3rd/terminal backoff escalation. Even though market-data has since recovered (`docker logs worldview-market-data-1` shows fresh 200 OKs for `/api/v1/fundamentals/{id}` and `/company-profile`), the DB-stored `next_refresh_at` keeps `get_due_for_refresh` from returning these rows. Right now: **zero rows have `next_refresh_at < NOW()`** — the worker has literally nothing to do for the 54% that hit terminal.

### Why it can't be fixed in this worktree

This is the symptom of F-LIVE-P (market-data fundamentals failures) cascading into the D-2 escalation chain. Two upstream conditions must be met before a fix here makes sense:

1. The market-data fundamentals path (F-LIVE-P / P1-A agent) must be confirmed healthy across **all** 2,405 tickers, not just the small sample that hit a fresh `/api/v1/fundamentals/{id}` 200 OK in the recent cycle. The market-data container is now returning 200s for some tickers but 401s/404s for others (`history?symbol=AMD ... 401 Unauthorized` in the most recent log line), so backoff escalations would simply restart.
2. A one-shot SQL backfill must reset `next_refresh_at` on the 1,305 terminal-parked rows back to NOW so the 5-min worker can re-attempt them. Issuing that backfill before P1-A lands would just push them straight back into terminal backoff (cost: 2,405 × 4 HTTP calls = ~10K failed market-data hits + ~5K Valkey escalations).

### Concrete next action

Coordination sequence:

1. P1-A (F-LIVE-P) agent confirms `GET /api/v1/fundamentals/{entity_id}` + `/company-profile` + `/earnings` returns 200 for all 2,405 financial_instrument entity_ids (a quick scripted sweep against the live market-data container, expected ~30 s).
2. After that confirmation, run a one-shot SQL backfill in `intelligence_db`:

   ```sql
   -- Clear the next_refresh_at parking so the 5-min worker re-attempts immediately.
   UPDATE entity_embedding_state
   SET next_refresh_at = NOW()
   WHERE view_type = 'fundamentals_ohlcv' AND embedding IS NULL;

   -- Also clear the Valkey backoff keys so _get_backoff_seconds returns None.
   -- Run from any pod with valkey-cli installed:
   --   valkey-cli --scan --pattern 'fundamentals_refresh:backoff:*' | xargs valkey-cli del
   ```

3. Wait ~10 min (2 worker cycles at 5 min) and confirm `SELECT COUNT(*) FILTER (WHERE embedding IS NOT NULL) FROM entity_embedding_state WHERE view_type='fundamentals_ohlcv'` is climbing.

No code change is required in this worktree. The PLAN-0093 T-C-4-03 scope filter is correct and the D-2 backoff path is working exactly as designed; the data plane needs the upstream P1-A fix first.

---

## Summary

| Finding   | Decision | Blocked on |
|-----------|----------|------------|
| F-DB-003  | DEFER    | Mention-resolution / FI canonical linking (no `resolved_entity_id` mentions for FI class) |
| F-DB-004  | DEFER    | F-LIVE-P / P1-A (market-data fundamentals stability) — followed by a one-shot `next_refresh_at = NOW()` SQL backfill + Valkey backoff-key purge |

Time spent on investigation: ~50 min. No code changes shipped (intentional — both root causes are upstream-blocked).
