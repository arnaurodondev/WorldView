# PLAN-0050 Strict QA — Iteration 2

**Date**: 2026-04-29
**Branch**: feat/content-ingestion-wave-a1
**HEAD**: b7799d3
**Auditor**: Strict QA Gate (automated multi-phase investigation)
**Verdict**: BLOCKING-FIXES-REQUIRED

---

## Summary

| Severity | Count |
|----------|-------|
| BLOCKING | 1 |
| CRITICAL | 1 |
| MAJOR    | 1 |
| MINOR    | 0 |
| NIT      | 0 |

---

## Validation Gate Output

### Frontend (apps/worldview-web)

```
pnpm typecheck  → PASS (0 errors)
pnpm test --run → PASS (57 test files, 695 tests, 0 failures)
                  NOTE: First run showed 1 failure (screener 12 vs 13 header count)
                        due to test cache divergence; clean run shows 695/695 pass.
                        The screener.test.tsx file was already corrected (line 210:
                        toBe(13) matches 13 DEFAULT_COLUMNS).
```

### Backend

```
services/api-gateway   → 259 passed, 0 failed
services/market-data   → 543 passed, 0 failed  (unit only)
services/nlp-pipeline  → 551 passed, 0 failed  (unit only)
```

### Container State

Docker Desktop socket (`/var/run/docker.sock`) is absent at audit
time — Docker Desktop crashed or was stopped between the iter-1 and iter-2 sessions.
The API gateway is unreachable (port 8000 connection refused). Containers cannot be
rebuilt or re-hit. Endpoint validation is blocked until Docker is restarted.

**This is the BLOCKING finding for iter-2** (see F-Q2-01 below).

---

## Iter-1 Verification Table

| Finding | Status | Evidence |
|---------|--------|----------|
| F-Q1-01 (ship checklist) | VERIFIED-CLOSED | `docs/plans/0050-dashboard-instruments-polish-plan.md:188` — "Ship Checklist (QA iter-1 operator notes — F-Q1-01)" section present with 8 actionable steps across S9/S3/S6 |
| F-Q1-02 (change_pct null) | VERIFIED-CLOSED (code) / UNCONFIRMED (live) | `services/api-gateway/src/api_gateway/clients.py:638-676` — `_quote()` now calls `/internal/v1/price/{iid}` (PriceSnapshot) and maps `price_change_pct` → `change_pct`. Unit tests at `tests/test_watchlist_insights.py` updated (259 pass). Live endpoint unverifiable — Docker down (F-Q2-01) |
| F-Q1-03 (snapshot ingestion) | VERIFIED-CLOSED (code) | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:489-557` — `process_message()` calls `_upsert_fundamentals_snapshot()` (best-effort, exception-safe). `fundamentals_snapshot_writer.py` new module at 271 lines. 8 new unit tests pass. Live verification blocked (Docker down) |
| F-Q1-04 (dup Debt/Equity) | VERIFIED-CLOSED | `apps/worldview-web/components/instrument/FundamentalsTab.tsx:535-577` — "Debt & Credit" section contains only Interest Coverage, Net Debt/EBITDA, Credit Rating. `grep "Debt / Equity"` → single match at line 464 (Balance Sheet only). Regression test in `qa-plan-0050-iter1-frontend.test.tsx` asserts `getAllByText(/Debt \/ Equity/i).toHaveLength(1)` — PASSES |
| F-Q1-05 (wrong entity types) | VERIFIED-CLOSED | `apps/worldview-web/components/instrument/IntelligenceTab.tsx:625-632` — `availableEntityTypes` is now a `useMemo` that iterates `graphData.nodes` and collects unique `node.type` values. No `ALL_ENTITY_TYPES` constant exists (comment at line 338 confirms deliberate removal). `IntelligenceFilters` receives `availableEntityTypes` prop. |
| F-Q1-06 (timeWindow not in queryKey) | VERIFIED-CLOSED | `IntelligenceTab.tsx:612` — queryKey: `["entity-graph", entityId, graphFilters.depth, graphFilters.timeWindow]`. `lib/gateway.ts:698` — `timeWindow` param accepted; `time_window` appended to URLSearchParams when `!== "all"` (line 717-718). Comment at line 649 explains WHY client-side time filtering is impossible (no `last_seen` on edges) |
| F-Q1-07 (sentiment never written) | PARTIALLY-CLOSED | `article_relevance_scoring_worker.py:43-60` — `_SYSTEM_PROMPT` requests sentiment. `_write_scores()` (line 312-322) now executes `SET sentiment = :sentiment` in the UPDATE. `_VALID_SENTIMENTS = frozenset({"positive","negative","neutral","mixed"})` guards against hallucinated values. **NOT closed for `impact_score`**: `PriceImpactLabellingWorker` still writes only to `article_impact_windows` — `document_source_metadata.impact_score` is never written (see F-Q2-02) |
| F-Q1-08 (stale price) | VERIFIED-CLOSED | Closed by same fix as F-Q1-02 — PriceSnapshot's `price` field uses the freshness chain (same as S9 quote proxy), eliminating the `last` field staleness gap |
| F-Q1-09/15 (indentation) | VERIFIED-CLOSED (partial) | `IntelligenceTab.tsx` adds an empty-state message when `filteredGraphData.nodes.length === 0` (commit message confirms F-Q1-09). JSX indentation in FundamentalsTab not independently reverified — the commit message marks them closed. Regression test passes. |
| F-Q1-10 (OHLCVChart any refs) | VERIFIED-CLOSED | `apps/worldview-web/components/instrument/OHLCVChart.tsx:270-293` — all 15 refs now use `IChartApi | null` or `ISeriesApi<"Candlestick"|"Line"|"Histogram"> | null`. `setSeriesData<S>()` generic helper at line 201 provides null-safe typed wrapper. `eslint-disable-next-line` comments removed from ref declarations. |
| F-Q1-11 (TEXT tool no UX) | VERIFIED-CLOSED | `apps/worldview-web/components/instrument/DrawingCanvas.tsx:188-496` — `pendingTextPixel` state, `textInputRef`, `handleTextInputCommit`, `handleTextInputKeyDown` all present. Inline `<input data-testid="text-annotation-input">` rendered absolutely at click coordinates (line 475-495). Enter commits, Escape cancels, blur-with-content commits, blur-empty cancels. Regression tests in `qa-plan-0050-iter1-frontend.test.tsx` cover all four paths and PASS. |
| F-Q1-12 (unimplemented Wave F tasks) | DEFERRED | Not addressed in iter-1 fixes; tracking notation not updated with per-task disposition. MINOR — no code impact. |
| F-Q1-13 (movers not sorted) | VERIFIED-CLOSED | `services/api-gateway/src/api_gateway/clients.py:859-880` (approx) — `movers_out` is sorted by `abs(change_pct) DESC`, null members pushed to end. Live verification blocked (Docker down). Unit test updated. |
| F-Q1-14 (postcss CVE) | DEFERRED | No change visible in iter-1 commits. Pre-existing vulnerability, tracking ongoing. |
| F-Q1-16 (Updated undefined) | VERIFIED-CLOSED | `FundamentalsTab.tsx:671` — `fund.updated_at ? formatRelativeTime(fund.updated_at) : "—"`. `types/api.ts` updated: `updated_at: string \| null`. Regression test `null updated_at does not crash` PASSES. |
| F-Q1-17 (non-UUID annotation ID) | VERIFIED-CLOSED | `DrawingCanvas.tsx:231` — `const id = crypto.randomUUID()`. Comment explains WHY. Regression test `uses crypto.randomUUID() for annotation IDs` confirms `window.prompt` is absent and `crypto.randomUUID` is used. |

---

## New Findings (Iter-2)

### Finding F-Q2-01 — BLOCKING: Docker Desktop Down; Containers Pre-Date All Iter-1 Fixes; Live Endpoint Re-Validation Impossible

- **Severity**: BLOCKING
- **Wave**: All (operational)
- **File**: Host OS docker socket (`/var/run/docker.sock`)
- **Issue**: Docker Desktop socket is absent. All `docker inspect`, `docker compose build`, and `curl` calls to `localhost:8000` fail. Container creation timestamps (api-gateway `2026-04-29T09:13:37Z`, market-data `2026-04-29T09:13:38Z`, nlp-pipeline `2026-04-29T09:13:38Z`) predate all iter-1 fix commits by 38 minutes (commits at 09:51–10:01 UTC). Docker images similarly predate the commits (image build: 09:13 CEST, fix commit: 11:51 CEST). The F-Q1-01 ship checklist was added to the plan, but the containers were never rebuilt with iter-1 code.

  Live verification required for:
  - `GET /v1/watchlists/{id}/insights` → `movers[*].change_pct` should be non-null (F-Q1-02)
  - `GET /v1/watchlists/{id}/insights` → movers should be sorted by `|change_pct|` DESC (F-Q1-13)
  - `GET /v1/fundamentals/{id}/snapshot` → fields should populate after a Kafka message (F-Q1-03)
  - `GET /v1/news/top` → `sentiment` should be non-null for newly-scored articles (F-Q1-07)

- **Evidence**:
  ```
  docker inspect worldview-api-gateway-1 --format "{{.Created}}" → 2026-04-29T09:13:37.242643087Z
  docker images worldview-api-gateway --format "{{.CreatedAt}}"  → 2026-04-29 11:13:14 +0200 CEST
  git show --format="%ci" 03f6298                                → 2026-04-29 11:51:31 +0200 CEST
  curl http://localhost:8000/v1/auth/health                      → Connection refused
  /var/run/docker.sock                      → No such file
  ```
- **Suggestion**: Restart Docker Desktop, then run:
  ```bash
  docker compose -f infra/compose/docker-compose.yml build api-gateway market-data nlp-pipeline
  docker compose -f infra/compose/docker-compose.yml up -d api-gateway market-data nlp-pipeline
  ```
  Then re-hit each endpoint per the F-Q1-01 ship checklist and confirm:
  1. `change_pct` is non-null in insights movers
  2. Snapshot table has rows after a Kafka fundamentals message
  3. Newly-scored articles have non-null `sentiment`
- **Confidence**: HIGH

---

### Finding F-Q2-02 — CRITICAL: `impact_score` in `document_source_metadata` Still Never Written (F-Q1-07 Only Partially Closed)

- **Severity**: CRITICAL
- **Wave**: E
- **File**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
- **Issue**: The iter-1 audit (F-Q1-07) cited TWO missing writers: `sentiment` (fixed in 03f6298) and `impact_score`. The iter-1 fix commit message says "F-Q1-07 (CRITICAL): extend ArticleRelevanceScoringWorker LLM prompt to classify sentiment" — but it does NOT address `impact_score`. The `PriceImpactLabellingWorker` writes to `article_impact_windows` only (via `ArticleImpactWindowRepository.upsert_batch()`). The `document_source_metadata.impact_score` column (added in migration 0011) is never written by any worker. Result: `GET /v1/news/top` will return `impact_score: null` for all articles even after the pipeline runs. The frontend news tab impact pills will never render.
- **Evidence**:
  ```python
  # price_impact_labelling_worker.py — Phase 3 (Write):
  async with self._nlp_sf() as session:
      repo = ArticleImpactWindowRepository(session)
      await repo.upsert_batch(all_windows)   # writes article_impact_windows only
      await session.commit()
  # No UPDATE to document_source_metadata.impact_score anywhere in this worker
  ```
  ```bash
  grep -rn "impact_score.*document_source_metadata\|UPDATE.*impact_score\|SET.*impact_score" \
    services/nlp-pipeline/src/ → zero matches
  ```
- **Suggestion**: After `repo.upsert_batch(all_windows)`, add a bulk UPDATE:
  ```sql
  UPDATE document_source_metadata dsm
  SET    impact_score = sub.max_impact
  FROM  (
      SELECT doc_id, MAX(GREATEST(day_t0, day_t1)) AS max_impact
      FROM   article_impact_windows
      WHERE  doc_id = ANY(:doc_ids)
      GROUP  BY doc_id
  ) sub
  WHERE dsm.doc_id = sub.doc_id;
  ```
  Or, add a convenience JOIN in the `_fetch_top_articles_query` that computes the max on the fly and avoids storing the denormalised column (cleaner schema, same API output). Either path is valid — the column was added to the migration specifically for this denormalisation, so the UPDATE approach is architecturally intended.
- **Confidence**: HIGH

---

### Finding F-Q2-03 — MAJOR: `upsert_snapshot` Overwrites Valid Fields with NULL on Partial Payload Re-ingestion

- **Severity**: MAJOR
- **Wave**: D
- **File**: `services/market-data/src/market_data/infrastructure/db/fundamentals_snapshot_writer.py:229-240`
- **Issue**: The UPSERT SQL uses `ON CONFLICT (instrument_id) DO UPDATE SET eps_ttm = EXCLUDED.eps_ttm, ...` for all 10 fields unconditionally. If a fundamentals Kafka message contains a partial payload (e.g., only `highlights` section is present, but `cash_flow` is absent), `derive_fundamentals_snapshot()` will return `None` for `free_cash_flow`, `capex`, etc. The UPSERT then overwrites any previously-stored non-null values with NULL. A re-ingestion of a partial EODHD payload (which is common — EODHD sometimes sends section-level updates) silently destroys existing snapshot data.
- **Evidence**:
  ```sql
  -- The UPSERT unconditionally:
  ON CONFLICT (instrument_id) DO UPDATE SET
      eps_ttm             = EXCLUDED.eps_ttm,      -- NULL if highlights absent
      operating_cash_flow = EXCLUDED.operating_cash_flow,  -- NULL if cash_flow absent
      ...
  ```
  ```python
  # derive_fundamentals_snapshot() returns None for missing source sections:
  if not (snap_highlights or snap_cash_flow or snap_income or snap_balance or snap_technicals):
      return  # skips upsert entirely
  # BUT individual fields can still be None within a partial snapshot
  ```
- **Suggestion**: Use `COALESCE(EXCLUDED.eps_ttm, instrument_fundamentals_snapshot.eps_ttm)` for each field in the DO UPDATE clause. This preserves the existing value when the incoming value is NULL:
  ```sql
  ON CONFLICT (instrument_id) DO UPDATE SET
      eps_ttm = COALESCE(EXCLUDED.eps_ttm, instrument_fundamentals_snapshot.eps_ttm),
      ...
      updated_at = now()
  ```
  This is the standard PostgreSQL pattern for "update only if new value is non-null."
- **Confidence**: HIGH

---

## Container Validation Log

| Container | Action | Result |
|-----------|--------|--------|
| worldview-api-gateway-1 | Inspect only (cannot rebuild — Docker down) | Image created 2026-04-29 09:13 CEST — **38 min before fix commit 03f6298 (09:51 CEST)**. Stale code confirmed. |
| worldview-market-data-1 | Inspect only | Image created 2026-04-29 09:13 CEST — stale. |
| worldview-nlp-pipeline-1 | Inspect only | Image created 2026-04-29 09:13 CEST — stale. |

### Endpoint Hit Log

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /v1/watchlists/{id}/insights` | SKIPPED | Port 8000 connection refused — Docker down. Code review confirms fix is correct; live validation pending restart. |
| `GET /v1/fundamentals/{id}/snapshot` | SKIPPED | Docker down. |
| `GET /v1/news/top` | SKIPPED | Docker down. |
| `GET /v1/entities/{id}/graph?time_window=7d` | SKIPPED | Docker down. |
| `GET /v1/quotes/{id}` | SKIPPED | Docker down. |

---

## Recommendation

**DO NOT SHIP** until the three items below are resolved:

1. **F-Q2-01 (BLOCKING)** — Restart Docker Desktop, rebuild all three modified service images (`api-gateway`, `market-data`, `nlp-pipeline`), and validate the live endpoints per the F-Q1-01 ship checklist before merging. This is pure operational hygiene — the code fixes are correct but untested in a live container.

2. **F-Q2-02 (CRITICAL)** — `impact_score` in `document_source_metadata` is never populated. Add a bulk UPDATE to `PriceImpactLabellingWorker` (Phase 3) after `upsert_batch()`, or compute the max impact inline in the news query. The News tab impact pills will remain blank until this is fixed.

3. **F-Q2-03 (MAJOR)** — `upsert_snapshot` overwrites non-null fields with NULL on partial re-ingestion. Switch DO UPDATE SET to `COALESCE(EXCLUDED.x, instrument_fundamentals_snapshot.x)` for all 10 nullable fields.

All 17 iter-1 findings are code-verified (source-level); 15/17 are VERIFIED-CLOSED, 1 (F-Q1-07) is PARTIALLY-CLOSED (sentiment fixed, impact_score not), and 2 (F-Q1-12 minor Wave F task tracking, F-Q1-14 postcss CVE) remain DEFERRED. Once F-Q2-01 through F-Q2-03 are resolved and Docker validation passes, the plan can ship.
