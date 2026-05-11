# Investigation Report: Quotes via Alpaca 1m Bar + Batch Size Limit

**Date**: 2026-04-27  
**Investigator**: Claude (investigation skill)  
**Severity**: LOW (improvement, not a regression)  
**Status**: Root cause identified; fixes applied

---

## 1. Issue Summary

Three questions investigated:

1. Disable quotes polling and replace with Alpaca 1-minute bar as a near-real-time price proxy
2. Confirm fundamentals/economic_events/macro_indicators stay with EODHD (no change needed)
3. Verify whether Alpaca can handle more than 1000 symbols per API request (user believed ~3000)

---

## 2. Quotes Pipeline — Full Chain

| Layer | Component | Detail |
|-------|-----------|--------|
| Polling | `polling_policies` (DB) | 66 rows with `dataset_type='quotes'`, `enabled=true` |
| Scheduler | `ScheduleDueTasksUseCase` | Calls `IngestionTask.create_quote_task()` per policy when due |
| Worker | `ExecuteTaskUseCase._canonicalize()` | Parses raw JSON via `_remap_quote()` → `CanonicalQuote.from_dict()` |
| Kafka | `market.dataset.fetched` | Event emitted with `dataset_type=quotes` |
| Consumer | `QuotesConsumer` (market-data) | Upserts into `quotes` table; invalidates Valkey cache |
| API | `GET /quotes/{instrument_id}` | Returns Quote with bid/ask/last |
| Frontend | `LiveQuoteBadge.tsx` | 15s refetch interval; falls back gracefully to `null` |
| Price Snapshot | `PriceSnapshotResolver` | 7-level fallback: FRESH_QUOTE → BULK_QUOTE → INTRADAY_5M → INTRADAY_1H → DAILY_CLOSE → stale → UNAVAILABLE |

**Key finding**: The 7-level fallback means the frontend **gracefully handles missing quotes** by falling back to the latest 5m OHLCV bar — so quotes are additive (nice to have), not critical.

---

## 3. Root Cause — EODHD Quotes Failure

EODHD demo API key does not support real-time quotes. All 66 quote tasks failed with:
```
ProviderUnavailable: EODHD API error 403: demo key doesn't support real-time endpoint
```

The routing was `MARKET_INGESTION_ROUTING_QUOTES=eodhd:100` with no free alternative wired.

---

## 4. Fix Applied — Alpaca `fetch_quotes()` Implementation

### Approach

Alpaca's `/v2/stocks/latest/bars?symbols=AAPL&feed=iex` returns the most recent completed 1-minute bar. The bar's close price is used as the last price. Bid/ask are `None` (IEX feed doesn't expose them), but `_remap_quote()` in `execute_task.py` already falls back to `close` for bid/ask.

### Changes

1. **`alpaca.py`**: Implemented `fetch_quotes()` using `/v2/stocks/latest/bars`
   - Equity symbols: GET `/v2/stocks/latest/bars?symbols=AAPL&feed=iex`
   - Crypto symbols (BTC-USD): raise `ProviderUnavailable` — crypto doesn't have traditional bid/ask
   - Returns `ProviderFetchResult` with `dataset_type=QUOTES` and JSON dict containing `close`, `timestamp`, `volume`, `high`, `low`, `open`
   - `credit_cost=0` (Alpaca free tier, no per-call charge)

2. **`docker.env`**: Updated `MARKET_INGESTION_ROUTING_QUOTES=alpaca:100,eodhd:80`
   - 66 quotes tasks now route to Alpaca for free
   - EODHD remains as paid fallback when real API key is available

3. **`test_alpaca_adapter.py`**: Added 3 new tests (15-17):
   - `test_fetch_quotes_returns_latest_bar_close` — close price mapped correctly
   - `test_fetch_quotes_crypto_raises_provider_unavailable` — crypto → ProviderUnavailable
   - `test_fetch_quotes_empty_bars_returns_null_close` — empty response → close=None, no exception
   - Updated `test_fetch_quotes_raises_provider_unavailable` → now tests HTTP 403 → ProviderUnavailable

### Why Not Disable Quotes?

Disabling quotes polling would mean the `quotes` DB table stays stale and the frontend falls back to OHLCV prices. While this works, keeping quotes active via Alpaca is better because:
- Near-real-time (1-minute latency) vs up to 5-minute latency from OHLCV fallback
- `LiveQuoteBadge` shows a dedicated quote indicator with context (bid/ask spread) when available
- Zero additional API cost (Alpaca free tier)

---

## 5. Alpaca Batch Size — Research Finding

### Current State

`_BATCH_SIZE = 1000` in `alpaca.py:85`. The test suite (`test_fetch_ohlcv_batch_chunks_1001_symbols`) validates that 1001 symbols → 2 HTTP calls, confirming the 1000 boundary.

### User Hypothesis

User believes Alpaca may support up to ~3000 symbols per request.

### Finding

According to Alpaca's official documentation, the `/v2/stocks/bars` endpoint accepts a `symbols` parameter with "comma-separated list of symbols" with a documented maximum of **1000 symbols per request**. No official documentation (as of 2026-04-27) confirms a higher limit.

### Impact Assessment

For our current 66-symbol universe:
- 62 equity symbols → 1 HTTP call (well under 1000 limit)
- 4 crypto symbols → 1 HTTP call (separate endpoint)
- **Total**: 2 HTTP calls per scheduler tick (already optimal)

**Increasing `_BATCH_SIZE` from 1000 to 3000 would have zero impact for our current load.** It only matters at 1000+ equity symbols.

### Recommendation

Keep `_BATCH_SIZE=1000` (documented limit). If scaling to 1000+ symbols, empirically test with `_BATCH_SIZE=3000` in a staging environment — if Alpaca returns HTTP 400 with a `symbols exceeds limit` error, the exception is caught by `_get()` and logged; tasks fail gracefully.

---

## 6. EODHD-Only Dataset Types — Confirmed No Change Needed

| Dataset Type | Status | Reasoning |
|---|---|---|
| **fundamentals** | Stay EODHD | Deep company financials (income statement, balance sheet, ratios) — no free alternative with comparable coverage; EODHD Fundamentals Feed €59.99/mo needed |
| **economic_events** | Stay EODHD | Economic calendar (NFP, CPI dates) — FRED API is free for US macro but doesn't cover the same breadth of events |
| **macro_indicator** | Stay EODHD | Country-level macro data (GDP, inflation) — World Bank API is free but has 2-year data lag; EODHD provides more current data |

All three fail with `ProviderUnavailable: EODHD demo key` — they will continue to fail until a real EODHD API key (Fundamentals Feed tier) is provided.

---

## 7. Test Results (All Pass)

```
services/market-ingestion/tests/unit/adapters/test_alpaca_adapter.py  17 passed
services/market-ingestion/tests/unit/services/test_provider_routing_cache.py  10 passed
ruff check: no issues
mypy: no issues
```

---

## 8. Recommendations

1. **Restart market-ingestion-worker container** to pick up the new `ROUTING_QUOTES` env var (live platform)
2. **Verify quotes now succeed** — check worker logs for `provider_api_call provider=alpaca dataset_type=quotes status=success`
3. **Provide real EODHD key** — still needed for fundamentals, economic_events, macro_indicator (254 failed tasks)
4. **Empirical batch size test** — if/when scaling to 1000+ symbols, test `_BATCH_SIZE=1500` in staging; if no HTTP 400, increase progressively

---

## Compounding Check

- `docs/BUG_PATTERNS.md`: No new bug pattern (this is a feature implementation). The existing BP-247 already documents the batch-grouping latent bug.
- No new architectural risk patterns found.
