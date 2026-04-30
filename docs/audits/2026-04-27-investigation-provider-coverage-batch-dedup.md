# Investigation Report: Provider Coverage, Deduplication & Batch Efficiency

**Date**: 2026-04-27  
**Investigator**: Claude (investigation skill)  
**Severity**: MEDIUM (suboptimal — data missing due to EODHD key, but fixable)  
**Status**: Root causes identified; 3 fixes applied

---

## 1. Issue Summary

Three questions investigated:
1. Can quotes, fundamentals, economic events, macro indicators, insider transactions, and earnings calendar be loaded from providers other than EODHD?
2. Can duplicates from different sources be deduplicated correctly?
3. Is the Alpaca batch endpoint being used effectively for 60+ tickers to get 1-minute bars written to S3?

---

## 2. Provider Coverage Matrix

| Dataset Type | EODHD | Alpaca | Polygon | Yahoo Finance | Finnhub | Current Routing |
|---|---|---|---|---|---|---|
| ohlcv (intraday) | ✓ | ✓ (primary) | ✓ (fallback) | ✗ | ✗ | `alpaca:100,polygon:80` |
| ohlcv (EOD) | ✓ (fallback) | ✗ | ✗ | ✓ (primary) | ✗ | `yahoo_finance:100,eodhd:80` |
| quotes | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |
| fundamentals | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |
| news_sentiment | ✓ | ✗ | ✗ | ✗ | **✓ (free)** | `finnhub:100,eodhd:80` ← **FIXED** |
| earnings_calendar | ✓ | ✗ | ✗ | ✗ | **✓ (free)** | `finnhub:100,eodhd:80` ← **FIXED** |
| insider_transactions | ✓ | ✗ | ✗ | ✗ | **✓ (free)** | `finnhub:100,eodhd:80` ← **FIXED** |
| economic_events | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |
| macro_indicator | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |
| yield_curve | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |
| market_cap | ✓ | ✗ | ✗ | ✗ | ✗ | `eodhd:100` (DEMO KEY — fails) |

---

## 3. Fix 1 — Finnhub Routing for 3 Dataset Types

### Root Cause

`ProviderRoutingCache.load_from_config()` only parsed 4 routing slots (ohlcv_intraday, ohlcv_eod, quotes, fundamentals). The three dataset types where Finnhub has working implementations (news_sentiment, earnings_calendar, insider_transactions) had no routing configuration — they always fell back to `["eodhd"]` regardless of any env vars set.

The worker's `_resolve_provider()` uses the routing cache, NOT `task.provider` from the DB. So tasks stored with `provider='eodhd'` are correctly executed via Finnhub when the routing cache says Finnhub is primary — the stored provider is only used for task deduplication in the scheduler.

### Fix Applied

1. `config.py`: Added `routing_news_sentiment`, `routing_earnings_calendar`, `routing_insider_transactions` fields with `"eodhd:100"` as default.
2. `provider_routing_cache.py`: Added 3 `_parse_into()` calls for these dataset types in `load_from_config()`.
3. `docker.env`: Set all three to `finnhub:100,eodhd:80`.
4. Reset 7 failed tasks to pending → all 13 tasks now succeeded via Finnhub.

### Verification

Worker logs confirm: `provider_routing_cache_selected dataset_type=insider_transactions selected=finnhub` and `provider_api_call provider=finnhub status=success`.

---

## 4. Deduplication — Fully Implemented (No Action Needed)

The system has **3 independent deduplication layers** that handle data from multiple providers correctly:

### Layer 1 — Task Deduplication (ingestion_db)
- `ingestion_tasks` has `UNIQUE (provider, dedupe_key)` constraint.
- Same (provider, symbol, dataset_type, date_range) cannot be enqueued twice.
- Cross-provider dedup: an EODHD task and a Finnhub task for the same symbol CAN both exist (different provider → different dedupe_key). This is intentional.

### Layer 2 — Watermark/SHA256 Dedup (ingestion → market-data)
- After fetch, the canonical SHA-256 hash is compared against `last_success_sha256` in `ingestion_watermarks`.
- If the hash is unchanged (same data as last run), no Kafka event is emitted — market-data is not even notified.

### Layer 3 — Provider-Priority Upsert (market-data ohlcv_bars)
- `ohlcv_bars` PRIMARY KEY is `(instrument_id, timeframe, bar_date)`.
- Insert uses `ON CONFLICT DO UPDATE SET ... WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`.
- Result: **only the highest-priority provider's data is stored**. Lower-priority data is silently rejected.
- Priority order: Alpaca > Polygon > Yahoo Finance > EODHD.

**Conclusion**: Multiple providers can independently fetch the same bars. The system guarantees exactly one canonical row per `(symbol, timeframe, date)`, always from the highest-priority provider. No manual deduplication is needed.

---

## 5. Fix 2 — Alpaca Batch Size Increased to 100

### Root Cause

`MARKET_INGESTION_WORKER_BATCH_SIZE=10` meant the worker claimed 10 tasks per cycle. With 64 OHLCV 1m symbols, the worker needed 7 claim cycles to process all symbols, making 7 separate Alpaca batch calls (10 symbols each) instead of 1-2 calls (all 64 symbols combined).

### How Batch Works

`_try_batch_execute()` groups all claimed tasks by `(resolved_provider, timeframe)`. For OHLCV intraday, it calls `adapter.fetch_ohlcv_batch(symbols=[...])` with all symbols in that group in a single HTTP request. Alpaca's `/v2/stocks/bars` and `/v1beta3/crypto/us/bars` endpoints accept up to 1000 comma-separated symbols per request.

With batch_size=10: 64 symbols → 7 Alpaca API calls (rounds of 10).  
With batch_size=100: 64 symbols → 2 Alpaca API calls (equity batch + crypto batch).

### Fix Applied

Updated `docker.env`: `MARKET_INGESTION_WORKER_BATCH_SIZE=100`. Worker restarted with `batch_size=100` confirmed in logs.

### Note on Date Range

**Latent bug** (BP-247 candidate): `_try_batch_execute()` uses `group_tasks[0].range_start` for the entire batch. All tasks in a single scheduler tick have identical date ranges (scheduler always uses `today_midnight` to `tomorrow_midnight`), so this doesn't cause data issues in practice. But if backfill tasks with different ranges mix with regular tasks, some symbols could get incorrect date ranges. Add watermark-aware batch grouping if mixed-range batching becomes needed.

---

## 6. Remaining Gaps — No Free Alternative Available

These dataset types have **no free provider implemented**:

| Dataset Type | Gap | Potential Free Alternative |
|---|---|---|
| **quotes** | EODHD real-time quotes require paid key | Alpaca `/v2/stocks/latest/trades` (free, 15-min delayed on IEX feed) |
| **fundamentals** | EODHD fundamentals require paid key | Financial Modeling Prep free tier (250 req/day), SEC EDGAR (US only, free) |
| **economic_events** | EODHD economic calendar requires paid key | FRED API (Federal Reserve, free, US macro only) |
| **macro_indicator** | EODHD macro data requires paid key | World Bank API (free, no key required), FRED API |

**Recommendation for quotes**: Alpaca already has our API key and provides latest bar data for free. `AlpacaProviderAdapter.fetch_quotes()` currently raises `ProviderUnavailable`. Implementing it via `/v2/stocks/latest/bars` (using 1-minute bars as a quote proxy) would be a low-effort fix that covers our 60 equity symbols without requiring a paid EODHD key.

---

## 7. Final Platform State

### Market-Ingestion Tasks (ingestion_db)

| Status | Count | Notes |
|--------|-------|-------|
| succeeded | 456 | All Alpaca, Yahoo Finance, Finnhub-routed |
| failed | 254 | All EODHD demo-key failures (quotes, fundamentals, economic_events, macro, insider old, earnings old, yield, market_cap) |
| running | 0 | |

### Content-Ingestion Tasks (content_ingestion_db)

| Status | Count | Notes |
|--------|-------|-------|
| succeeded | 3191+ | Finnhub, NewsAPI, Polymarket all healthy |
| failed | 11 | EODHD intentionally disabled |

---

## 8. Recommendations (Priority Order)

1. **Provide real EODHD API key** (HIGH) — unlocks 254 failed tasks: quotes, fundamentals, economic_events, macro_indicator, yield_curve, market_cap. Set `MARKET_INGESTION_EODHD_API_KEY=<real_key>` in `configs/docker.env`.

2. **Implement Alpaca quotes** (MEDIUM) — replace EODHD real-time quotes for 66 equity symbols using Alpaca's free latest-bar endpoint. No new API key required. Implementation: add `fetch_quotes()` in `alpaca.py` using `/v2/stocks/latest/bars?symbols=...`.

3. **Add batch date-range grouping** (LOW) — `_try_batch_execute()` should group by `(provider, timeframe, range_start, range_end)` instead of `(provider, timeframe)` to prevent incorrect date ranges when mixing tasks with different watermarks.

4. **Add routing config for economic_events, macro_indicator** (LOW, future) — wire FRED API or World Bank adapter when implemented.
