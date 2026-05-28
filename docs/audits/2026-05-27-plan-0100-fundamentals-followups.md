# PLAN-0100 — Fundamentals Follow-ups

**Date**: 2026-05-27
**Scope**: AMD Q1 FY2026 retrieval gap + top-N-by-market-cap design for `FundamentalsRefreshWorker`

## Part A — AMD Q1 FY2026 retrieval still empty

PLAN-0099 W1-T01 fixed the batch tool row-mix. PLAN-0096 W1 added the period_type=QUARTERLY filter. PLAN-0099 W2-T02 shipped `FundamentalsRefreshWorker` (disabled by default). Yet 4/6 Q4 chat-eval variants still fail because AMD Q1 FY2026 returns empty.

### Ranked hypotheses

| # | Hypothesis | Likelihood | Diagnostic query |
|---|---|---|---|
| H1 | Ingestion never ran for AMD recently | **HIGH** | `SELECT last_fundamentals_ingest_at FROM instruments WHERE symbol='AMD';` — expect NULL or pre-Apr-2026 |
| H2 | EODHD doesn't have Q1 FY2026 yet | medium | manual EODHD API call for AMD fundamentals |
| H3 | period_type filter too aggressive (Q1 row mislabeled ANNUAL) | low | remove filter in a one-off query, see if Q1 appears |
| H4 | Fiscal-calendar labeling mismatch | low | `SELECT fiscal_year_end_month FROM instruments WHERE symbol='AMD';` — expect 12, may be NULL |

### H1 details

The worker is disabled by default (`FUNDAMENTALS_REFRESH_ENABLED=false`). The manual script `scripts/refresh_fundamentals.py` was never triggered for AMD after deploy. Without either path, AMD's `last_fundamentals_ingest_at` stays NULL and EODHD is never re-polled.

**Fix path**:
1. **Immediate**: enable the worker (`FUNDAMENTALS_REFRESH_ENABLED=true`) OR trigger the manual script for AMD via `POST /api/v1/ingest/trigger`.
2. **Sustainable**: flip the worker default to enabled-by-default once PLAN-0100 confirms backoff semantics under EODHD load.
3. **Observability**: surface `last_fundamentals_ingest_at` on an operator dashboard with coverage-by-age binning so this never goes unnoticed again.

### H2 details

AMD fiscal year = calendar year. Q1 FY2026 ends 2026-03-29 (last Saturday). Earnings call typically late Apr / early May. If the chat-eval ran before AMD's actual Q1 earnings, EODHD won't have the data yet. Verify via direct EODHD API call against current date.

### H3 details

Unlikely given the filter explicitly checks `period_type="QUARTERLY"` at `fundamentals_query.py:85`. But if EODHD ships Q1 with `period_type="A"` (annual) by mistake, the filter rejects it silently. Quick verification: remove filter in a one-off and see if Q1 appears.

### H4 details

`fiscal_year_end_month` was added in PLAN-0093 era migration. The audit `2026-05-26-eodhd-fundamentals-deep-dive.md` §6 notes non-US tickers often have NULL `fiscal_year_end_month`. AMD's NULL would fall back to calendar quarters — should still produce a Q1 label. But if the EODHD profile parsing dropped the field, Q1 might be labeled as "Q2 FY2026" (because the fallback uses Q2 mapping for some calendars).

### Investigation order

1. Run H1 query (1 minute). If NULL/stale, trigger refresh and re-test chat-eval. Most likely the whole problem.
2. If H1 passes and Q1 still missing: run H2 (verify EODHD has the data).
3. If EODHD has it but our DB doesn't: H3 (filter issue).
4. If filter is fine: H4 (labeling).

## Part B — Top-N-by-market-cap design

### Current state

The `FundamentalsRefreshWorker` (`services/market-ingestion/src/market_ingestion/infrastructure/workers/fundamentals_refresh_worker.py`) uses a **curated static CSV** of 30 mega-cap tickers (`FUNDAMENTALS_REFRESH_SYMBOLS`) because cross-service DB query (market-ingestion reading market-data's `instruments.market_cap`) violates **R9 — no cross-service DB access**.

### Two design options

**Option 1 — Internal endpoint** (RECOMMENDED):
- New endpoint on market-data: `GET /internal/v1/instruments/top-by-market-cap?n=500&offset=0`
- Caller: `FundamentalsRefreshWorker` once per day (or on startup)
- Auth: `X-Internal-JWT` (existing pattern)
- Caching: worker memoizes list for the 6-hour refresh cycle

Pros: minimal new code (1 handler, 3 tests); R9-clean (REST not DB); 1-day staleness is fine for quarterly fundamentals; no Kafka surface.

Cons: 1 network hop per refresh day (~10-50 ms); worker needs JWT plumbing (already present via `InternalJWTMiddleware`).

**Option 2 — Kafka event**:
- Topic: `market.instruments.top_by_cap.v1`, daily emit from market-data
- Consumer: `FundamentalsRefreshWorker`

Pros: full audit trail, eventual consistency, no coupling at call time.

Cons: new Avro schema + producer + consumer + topic lifecycle; overkill for a static daily list; harder to test.

### Recommendation: Option 1

Worker is fundamentally pull-based (worker decides when to refresh, not market-data). Market cap changes infrequently. Kafka is for state propagation, not reads.

**Sketch — endpoint contract**:

```
GET /internal/v1/instruments/top-by-market-cap?n=500&offset=0
Headers: X-Internal-JWT: <signed-jwt>

200 OK
{
  "total": 2847,
  "offset": 0,
  "limit": 500,
  "results": [
    {"id": "uuid-1", "symbol": "AAPL", "exchange": "NASDAQ",
     "market_cap_usd": 2850000000000.0, "currency_code": "USD"},
    {"id": "uuid-2", "symbol": "MSFT", "exchange": "NASDAQ",
     "market_cap_usd": 2410000000000.0, "currency_code": "USD"}
  ]
}
```

Sorted descending by `market_cap_usd`, NULLs last. Limit clamped to [1, 5000].

**Handler location**: `services/market-data/src/market_data/api/routers/instruments.py` (new file or extend existing).

**SQL sketch** (using the existing `fundamental_metrics` table for market cap):
```sql
WITH latest_mktcap AS (
    SELECT DISTINCT ON (instrument_id)
        instrument_id, value_numeric AS market_cap_usd
    FROM fundamental_metrics
    WHERE field_name = 'market_capitalization'
    ORDER BY instrument_id, ingested_at DESC
)
SELECT i.id, i.symbol, i.exchange,
       COALESCE(lm.market_cap_usd, 0) AS market_cap_usd,
       i.currency_code
FROM instruments i
LEFT JOIN latest_mktcap lm ON i.id = lm.instrument_id
WHERE i.is_active = TRUE
ORDER BY lm.market_cap_usd DESC NULLS LAST
LIMIT :limit OFFSET :offset;
```

**Tests**: happy path (top-10); edge cases (n=1, n=5001 clamped, offset=10000 empty); auth (missing JWT → 401); all-NULL market caps fallback to symbol order.

**Worker wiring**: at boot or every 24 h, the worker calls the endpoint, replaces its in-memory ticker list, runs the next 6-hour refresh cycle against the fresh list.

## Pain point + solution

### Part A
**Pain point**: AMD Q1 FY2026 fundamentals stay empty months after PLAN-0096/0099 fixes because no scheduled refresh runs (worker disabled by default) and no observability surfaces the staleness.
**Solution**: enable `FUNDAMENTALS_REFRESH_ENABLED=true` (or run the manual script once), verify `last_fundamentals_ingest_at` updates within 24 h, add coverage-by-age dashboard panels so future staleness pages an operator. If post-trigger Q1 still missing, run H2-H4 in order.

### Part B
**Pain point**: `FundamentalsRefreshWorker` is stuck on a 30-ticker static CSV because the natural source of market-cap rankings lives in a different service's DB.
**Solution**: ship a `GET /internal/v1/instruments/top-by-market-cap` endpoint on market-data, callable from the worker via internal JWT auth. ~50 LOC handler + 3 tests. R9-clean. Sorts descending on `fundamental_metrics.market_capitalization`. Worker caches the response per 6-hour cycle.
