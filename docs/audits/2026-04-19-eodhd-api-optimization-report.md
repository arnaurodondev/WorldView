# EODHD API Usage Optimization Report

**Date**: 2026-04-19
**Author**: Claude Agent (research + codebase analysis)

---

## 1. API Pricing Tiers

| Tier | Monthly | Annual (equiv/mo) | Daily API Calls | Key Endpoints Included |
|------|---------|-------------------|-----------------|------------------------|
| **Free** | €0 | — | 20 | EOD (1yr depth), demo tickers only (6 symbols) |
| **EOD All World** | €19.99 | €16.66 | 100,000 | 30yr OHLCV all tickers, search API |
| **EOD + Intraday** | €29.99 | €24.99 | 100,000 | + intraday, technicals, screener, WebSocket (US/FX/crypto) |
| **Fundamentals Feed** | €59.99 | €49.99 | 100,000 | + fundamentals, insider transactions, macro indicators, earnings/economic calendars |
| **All-In-One** | €99.99 | €83.33 | 100,000 | + financial news, stock logos, bonds data |
| Internal Use | €399 | €332.50 | Unlimited | Commercial license |
| Enterprise | €2,499 | €2,082.50 | Unlimited | Full enterprise |

**Academic discount**: 50% off for 12 months (contact `anna@eodhistoricaldata.com`).

**Worldview needs**: Fundamentals Feed (€59.99/mo) covers everything except news. If the S4 EODHD news adapter is active, upgrade to All-In-One (€99.99/mo). With 50% academic discount: €30.00 or €50.00/mo respectively.

---

## 2. API Call Counting Rules

The critical distinction is: **1 HTTP request != 1 API call**. Different endpoint types consume different numbers of API calls per request.

| Endpoint Type | API Calls per Request | Notes |
|---------------|----------------------|-------|
| **EOD historical prices** | **1** | Full history in 1 call regardless of date range |
| **Live/delayed quotes** | **1 per ticker** | Multi-ticker request with 10 symbols = 10 calls |
| **Search API** | **1** | Ticker/ISIN/company name search |
| **Economic events** | **1** | Full day range in 1 call |
| **Earnings calendar** | **1** | Date range filter |
| **Intraday data** | **5** | Per symbol |
| **Technical indicators** | **5** | Per symbol |
| **News API** | **5 per ticker** | 2 tickers in one request = 10 calls |
| **Screener API** | **5** | Per request |
| **Fundamentals (single)** | **10** | Full company data (all sections) |
| **Options data** | **10** | Per symbol |
| **Insider transactions** | **10** | Per request (up to 1000 results) |
| **Macro indicators** | **10** | Full time series (from 1960) |
| **Marketplace products** | **10** | Per request |
| **Bulk EOD (full exchange)** | **100** | Entire exchange (e.g., all ~45K US tickers) |
| **Bulk EOD (with symbols)** | **100 + N** | N = number of symbols specified |
| **Bulk fundamentals** | **100 + N** | N symbols, max 500/request, Extended plan required |

### Key Insights

1. **EOD history is remarkably cheap**: 1 API call gets you the entire price history for a ticker (e.g., Ford from 1972 to today). There is no per-day or per-year charge.

2. **Fundamentals are expensive**: 10 calls per ticker. For 100 tickers daily, that is 1,000 API calls just for fundamentals.

3. **News is moderately expensive**: 5 calls per ticker per request. A paginated news fetch with `fetch_all_pages` across 4 tickers costs 5 calls per page per ticker.

4. **Bulk EOD is a bargain**: 100 API calls gets you EOD data for the entire US exchange (~45K tickers). Compare: fetching 100 tickers individually = 100 calls; fetching via bulk = 100 calls (same cost, but you get 45K tickers).

5. **Macro indicators are expensive per-indicator**: 10 calls per indicator per country. 6 indicators x 5 countries = 300 calls per weekly run.

6. **The `filter` parameter on fundamentals does NOT reduce the API call cost** -- it only reduces the response size. You still pay 10 calls whether you fetch all sections or one field.

---

## 3. Rate Limiting

| Limit | Value | Scope |
|-------|-------|-------|
| **Requests per minute** | 1,000 | Per API key |
| **Daily API calls** | 100,000 | Per user (all paid tiers), resets at midnight GMT |
| **Free tier daily** | 20 | Per user |
| **WebSocket real-time** | 50 tickers simultaneously | Per connection (does NOT consume API calls) |

### Rate Limit Headers

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 998
```

Best practice: spread requests evenly across the minute rather than bursting all at once.

### Extra API Calls

Additional API calls can be purchased as a buffer. They do not expire and accumulate across billing periods. Useful as insurance against occasional spikes.

---

## 4. Bulk vs Individual Call Comparison

| Operation | Individual Approach | Calls | Bulk Approach | Calls | Savings |
|-----------|-------------------|-------|---------------|-------|---------|
| EOD data for 6 tickers | 6x `GET /eod/{ticker}` | 6 | `GET /eod-bulk-last-day/US?symbols=AAPL,TSLA,...` | 106 | **-100** (bulk is worse for <100 tickers) |
| EOD data for 100 tickers | 100x `GET /eod/{ticker}` | 100 | `GET /eod-bulk-last-day/US` (full exchange) | 100 | **0** (break-even, but get 45K tickers) |
| EOD data for 500+ tickers | 500x `GET /eod/{ticker}` | 500 | `GET /eod-bulk-last-day/US` | 100 | **80% savings** |
| Fundamentals for 6 tickers | 6x `GET /fundamentals/{ticker}` | 60 | Bulk fundamentals (Extended plan) | 106 | **-46** (bulk is worse for <46 tickers) |
| Fundamentals for 100 tickers | 100x `GET /fundamentals/{ticker}` | 1,000 | Bulk fundamentals (100 symbols) | 200 | **80% savings** |
| Live quotes for 6 tickers | 6x `GET /real-time/{ticker}` | 6 | Multi-ticker: `GET /real-time/AAPL.US,TSLA.US,...` | 6 | **0** (same cost) |
| Live quotes for 50 tickers | 50x individual | 50 | WebSocket real-time | 0 | **100% savings** (WebSocket is free) |

### Bulk API Break-Even Points

- **Bulk EOD**: break-even at ~100 tickers (below that, individual calls are cheaper)
- **Bulk Fundamentals**: break-even at ~46 tickers (below that, individual calls are cheaper)
- **WebSocket quotes**: always free; replaces all polling-based quote fetching

---

## 5. Current Worldview Usage

### 5.1 Service Inventory — EODHD Endpoints Used

| Service | Endpoint | Method in Code | Frequency | API Calls/Invocation |
|---------|----------|---------------|-----------|---------------------|
| **S2 (market-ingestion)** | `GET /eod/{ticker}` | `fetch_ohlcv()` | Every 6h (daily), 12h (weekly), 24h (monthly) per ticker | 1 |
| **S2** | `GET /real-time/{ticker}` | `fetch_quotes()` | Every 5min per ticker (adaptive) | 1 |
| **S2** | `GET /fundamentals/{ticker}` | `fetch_fundamentals()` | Every 24h per ticker | 10 |
| **S2** | `GET /intraday/{ticker}` | `fetch_intraday()` | Every 1h (AAPL,TSLA,AMZN,BTC,EUR), 5m (AAPL,TSLA) | 5 |
| **S2** | `GET /calendar/earnings` | `fetch_earnings_calendar()` | Every 24h | 1 |
| **S2** | `GET /economic-events` | `fetch_economic_events()` | Every 24h per country (3 countries) | 1 |
| **S2** | `GET /macro-indicator/{country}` | `fetch_macro_indicator()` | Weekly per indicator (5 indicators x 2 regions) | 10 |
| **S2** | `GET /news` | `fetch_news_sentiment()` | Every 6h per ticker (4 tickers) | 5 |
| **S2** | `GET /insider-transactions` | `fetch_insider_transactions()` | Daily per ticker (3 tickers) | 10 |
| **S2** | `GET /ust/{series}` | `fetch_yield_curve()` | Daily (3 series) | 1 |
| **S2** | `GET /historical-market-cap/{ticker}` | `fetch_historical_market_cap()` | Weekly (5 tickers) | 1 |
| **S4 (content-ingestion)** | `GET /news` | `EODHDClient.fetch_news()` | Per scheduler interval (300s default), paginated | 5 per page per ticker |
| **S7 (knowledge-graph)** | `GET /economic-events` | `EodhDClient.get_economic_events()` | Daily 06:00 UTC (6 countries) | 1 |
| **S7** | `GET /macro-indicator/{country}` | `EodhDClient.get_macro_indicator()` | Weekly Sun 03:00 UTC (5 countries x 6 indicators) | 10 |
| **S7** | `GET /insider-transactions` | `EodhDClient.get_insider_transactions()` | Weekly Mon 02:00 UTC (all US instruments) | 10 |

### 5.2 Estimated Daily API Call Budget (Seed Data: 6 Core Tickers)

| Category | Calculation | Daily Calls |
|----------|------------|-------------|
| **Quotes (5min, 6 tickers)** | 6 tickers x 288 intervals/day x 1 call | 1,728 |
| **OHLCV daily (6 tickers)** | 6 x 4 runs/day x 1 call | 24 |
| **OHLCV weekly (6 tickers)** | 6 x 2 runs/day x 1 call | 12 |
| **OHLCV monthly (6 tickers)** | 6 x 1 run/day x 1 call | 6 |
| **Intraday 1h (5 tickers)** | 5 x 24 runs/day x 5 calls | 600 |
| **Intraday 5m (2 tickers)** | 2 x 288 runs/day x 5 calls | 2,880 |
| **Fundamentals (6 tickers)** | 6 x 1 run/day x 10 calls | 60 |
| **News sentiment (4 tickers, S2)** | 4 x 4 runs/day x 5 calls | 80 |
| **News ingestion (S4, paginated)** | ~4 tickers x ~3 pages x ~48 runs/day x 5 calls | 2,880 |
| **Earnings calendar** | 1 run/day x 1 call | 1 |
| **Economic events (3 countries, S2)** | 3 x 1 run/day x 1 call | 3 |
| **Economic events (6 countries, S7)** | 6 x 1 run/day x 1 call | 6 |
| **Insider transactions (3 tickers, S2)** | 3 x 1 run/day x 10 calls | 30 |
| **Yield curves (3 series)** | 3 x 1 run/day x 1 call | 3 |
| **Macro indicators (weekly ÷ 7)** | (5 indicators x 2 regions x 10) / 7 | 14 |
| **S7 macro indicators (weekly ÷ 7)** | (6 indicators x 5 countries x 10) / 7 | 43 |
| **S7 insider transactions (weekly ÷ 7)** | ~(N instruments x 10) / 7 | variable |
| **Market cap (weekly ÷ 7)** | (5 x 1) / 7 | 1 |
| **Health checks** | ~10 x 1 | 10 |
| **TOTAL (6 tickers, current config)** | | **~8,381/day** |

**Key concern**: The 5-minute intraday polling (2,880 calls/day) and S4 news pagination (2,880 calls/day) consume ~69% of the daily budget. As the ticker universe grows to 50-100 tickers, the budget will blow past 100K/day quickly.

### 5.3 Budget Scaling Projection

| Ticker Universe | Estimated Daily Calls | % of 100K Limit |
|----------------|----------------------|-----------------|
| 6 tickers (current seed) | ~8,400 | 8.4% |
| 20 tickers | ~25,000 | 25% |
| 50 tickers | ~58,000 | 58% |
| 100 tickers | ~110,000 | **110% (over limit)** |
| 200 tickers | ~215,000 | **215% (over limit)** |

### 5.4 Existing Optimizations in Codebase

| Optimization | Implementation | Location |
|-------------|---------------|----------|
| Token-bucket rate limiter | `ProviderBudget` entity (1000 burst, 10/s refill) | `services/market-ingestion/src/.../provider_budget.py` |
| Exponential backoff on failures | `IngestionScheduler._poll_loop()` | `services/content-ingestion/src/.../scheduler.py` |
| Dedup via url_hash | `EODHDAdapter.fetch()` skips already-seen articles | `services/content-ingestion/src/.../adapter.py` |
| Adaptive polling intervals | `PollingPolicy.effective_interval_seconds` hotness-based | `services/market-ingestion/src/.../polling_policy.py` |
| JSON hash comparison (macro) | `MacroIndicatorWorker` only updates on hash change | `services/knowledge-graph/src/.../macro_indicator_worker.py` |
| Cron scheduling (S7 EODHD workers) | Daily/weekly APScheduler cron jobs | `services/knowledge-graph/src/.../scheduler.py` |
| HTTP 429 handling | Both S2 and S4 adapters raise domain errors on 429 | EODHD adapter classes |

### 5.5 Missing Optimizations (Gaps)

| Gap | Impact |
|-----|--------|
| No bulk EOD endpoint usage | Individual calls for each ticker instead of exchange-wide bulk |
| No bulk fundamentals usage | 10 calls per ticker instead of ~2 calls via bulk (at scale) |
| No WebSocket usage for quotes | Polling every 5min costs 1 call/tick; WebSocket costs 0 |
| No response caching/TTL layer | Same data fetched across S2, S4, S7 without sharing |
| S2 and S7 duplicate EODHD calls | Both services independently call economic events, macro indicators, insider transactions |
| No daily call counter/budget tracking | `ProviderBudget` tracks rate (req/s) but not daily call budget (100K limit) |
| Fundamentals fetched every 24h | Company fundamentals rarely change daily; weekly is sufficient |
| News `fetch_all_pages` unbounded | Can paginate indefinitely, consuming 5 calls per page per ticker |

---

## 6. Optimization Opportunities

| # | Optimization | Current Calls/Day | Optimized Calls/Day | Savings/Day | Complexity |
|---|-------------|-------------------|---------------------|-------------|------------|
| 1 | **Replace 5min quote polling with WebSocket** | 1,728 | 0 | **1,728 (100%)** | Medium |
| 2 | **Replace 5min intraday polling with longer interval** (1h for all, remove 5m) | 2,880 | 600 | **2,280 (79%)** | Low |
| 3 | **Cap S4 news pagination** (max 2 pages per ticker per run) | 2,880 | 640 | **2,240 (78%)** | Low |
| 4 | **Use bulk EOD endpoint** (when universe > 100 tickers) | 100+ | 100 | **0-400+** | Medium |
| 5 | **Reduce fundamentals frequency** (weekly instead of daily) | 60 | 9 | **51 (85%)** | Low |
| 6 | **Deduplicate S2/S7 EODHD calls** (shared cache or route S7 through S2) | ~50 overlap | 0 | **50** | High |
| 7 | **Implement daily call budget counter** | N/A (prevents overrun) | N/A | **Safety net** | Medium |
| 8 | **Use fundamentals `filter` parameter** (reduce bandwidth, not calls) | 60 | 60 | **0 calls** (saves bandwidth) | Low |
| 9 | **Market-hours-only quote polling** (skip overnight/weekends) | 1,728 | ~576 | **1,152 (67%)** | Low |
| 10 | **Batch insider transactions to weekly only** (remove S2 daily polling) | 30 | 4 | **26 (87%)** | Low |

### Optimized Daily Budget (6 tickers, all optimizations applied)

| Category | Optimized Calls |
|----------|----------------|
| Quotes (WebSocket) | 0 |
| OHLCV daily | 24 |
| OHLCV weekly/monthly | 18 |
| Intraday 1h only | 600 |
| Fundamentals (weekly) | 9 |
| News (capped pagination) | 640 |
| Earnings calendar | 1 |
| Economic events (S7 only) | 6 |
| Macro indicators (weekly) | 43 |
| Insider transactions (S7 weekly only) | variable |
| Yield curves | 3 |
| Market cap (weekly) | 1 |
| Health checks | 10 |
| **TOTAL** | **~1,355/day** |

**Result**: From ~8,400 calls/day down to ~1,355 calls/day — an **84% reduction**. This leaves headroom to scale to ~450 tickers within the 100K/day budget.

---

## 7. Recommended Changes (Priority Order)

### Priority 1 — Quick Wins (Low effort, high impact)

**7.1 Cap S4 news pagination**
- File: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/eodhd/client.py`
- Change: Add `max_pages` parameter to `fetch_all_pages()`, default to 3 pages
- Savings: ~2,240 calls/day

**7.2 Remove 5-minute intraday polling**
- File: `services/market-ingestion/alembic/versions/0002_initial_seeds.py`
- Change: Remove the 5m intraday policies for AAPL/TSLA; 1h interval is sufficient for EOD-oriented platform
- Savings: ~2,280 calls/day

**7.3 Reduce fundamentals to weekly**
- File: `services/market-ingestion/alembic/versions/0002_initial_seeds.py`
- Change: Set `base_interval_sec` for fundamentals from 86,400 (24h) to 604,800 (7 days)
- Savings: ~51 calls/day

**7.4 Remove S2 daily insider transaction polling**
- File: `services/market-ingestion/alembic/versions/0002_initial_seeds.py`
- Change: Set `base_interval_sec` for insider_transactions from 86,400 to 604,800 (weekly); S7 already handles this weekly
- Savings: ~26 calls/day

### Priority 2 — Medium Effort, High Impact

**7.5 Enable market-hours-only polling for quotes**
- File: `services/market-ingestion/src/market_ingestion/domain/entities/polling_policy.py`
- Change: Add `market_hours_only: bool` flag to PollingPolicy; skip polling when the exchange is closed
- Savings: ~1,152 calls/day (quotes not needed at 3 AM)

**7.6 Implement daily API call budget counter**
- File: `services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py`
- Change: Add `daily_calls_consumed: int`, `daily_calls_limit: int` (default 100,000), and a `daily_budget_exhausted()` check. Track actual API call costs (not just requests) using the cost-per-endpoint table. Reset at midnight GMT.
- Impact: Prevents accidental overrun; enables alerting at 80% threshold

**7.7 Replace quote polling with WebSocket**
- File: New adapter in `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd_ws.py`
- Change: Use EODHD WebSocket real-time API for US stocks, forex, crypto. WebSocket connections do not consume API calls. Fall back to REST polling for unsupported exchanges.
- Savings: 1,728 calls/day (all quotes become free)
- Prerequisite: Requires EOD+Intraday tier or higher

### Priority 3 — Strategic (Higher effort, needed at scale)

**7.8 Use bulk EOD endpoint when ticker universe grows**
- Trigger: When tracking >100 tickers on a single exchange
- Change: Replace individual `fetch_ohlcv()` calls with `GET /eod-bulk-last-day/{EXCHANGE}?date=YYYY-MM-DD` for daily EOD updates
- Break-even: ~100 tickers; at 500 tickers, saves 400 calls/day

**7.9 Deduplicate S2/S7 EODHD calls via shared cache**
- Architecture: S7 workers read from S2's canonical storage (MinIO) or a Valkey cache instead of calling EODHD directly. S2 produces Kafka events that S7 consumes.
- Savings: Eliminates ~50+ duplicate calls/day for economic events, macro indicators, and insider transactions
- Complexity: High — requires cross-service coordination

**7.10 Use bulk fundamentals API at scale**
- Trigger: When tracking >50 tickers
- Change: Replace individual `fetch_fundamentals()` with bulk endpoint. 50 tickers: 10x50 = 500 calls → 150 calls (100 + 50).
- Prerequisite: Extended Fundamentals plan (contact EODHD support)

---

## 8. Data Freshness Strategy

| Data Type | EODHD Update Schedule | Recommended Poll Interval | Rationale |
|-----------|----------------------|--------------------------|-----------|
| **EOD prices** | 2-3h after market close | **Once daily at 23:00 UTC** (after US close + buffer) | Data only changes once/day; polling more often wastes calls |
| **Intraday (1h)** | Near real-time (2-3h delay for finalization) | **Every 1h during market hours only** | No value polling overnight |
| **Intraday (5m)** | Near real-time | **Remove entirely** (or limit to 2 high-priority tickers) | 5m granularity costs 5x per call; not needed for EOD platform |
| **Quotes** | 15-20 min delay | **Use WebSocket** (0 API calls) or poll every 15min (not 5min) | Currently over-polling vs data freshness |
| **Fundamentals** | Updated when company files | **Weekly** (Sunday night) | Earnings are quarterly; daily polling wastes 85% of calls |
| **News** | Continuous aggregation | **Every 6h, max 2 pages** | More frequent = diminishing returns; cap pagination |
| **Economic events** | Day after event | **Daily at 06:00 UTC** (S7 cron) | Already optimal |
| **Macro indicators** | Annual data (World Bank) | **Weekly** (S7 cron, Sunday 03:00) | Already optimal |
| **Insider transactions** | Filed within 2 business days | **Weekly** (S7 cron, Monday 02:00) | Already optimal; remove S2 daily polling |
| **Yield curves** | Daily | **Daily** | 1 call per series; cheap enough |
| **Market cap** | Daily | **Weekly** | Rarely moves dramatically day-to-day |
| **Earnings calendar** | Updated continuously | **Daily** | 1 call; cheap enough |

---

## 9. Tier Recommendation

### For Current Development (6 tickers, thesis)

**Recommended tier**: **Fundamentals Feed (€59.99/mo)** with **50% academic discount = €30.00/mo**

- Covers: EOD, intraday, fundamentals, insider transactions, macro indicators, economic events, earnings calendar
- Does NOT include: financial news API (S4 EODHD news adapter would need to be disabled; use Finnhub free tier for news instead)
- Daily budget: 100,000 calls — more than sufficient for 6 tickers even without optimization

### If S4 EODHD News Adapter Is Required

**Recommended tier**: **All-In-One (€99.99/mo)** with **50% academic discount = €50.00/mo**

- Adds: financial news feed, stock logos
- Justification: S4's `EODHDClient.fetch_news()` uses the `/api/news` endpoint, which is only available on All-In-One

### Cost-Saving Alternative

Use **Fundamentals Feed** and route all news through Finnhub (free tier, 60 req/min). The S4 `FinnhubAdapter` is already implemented. This saves €20-40/month vs All-In-One.

### At Scale (100+ tickers, post-thesis)

**Required tier**: **All-In-One (€99.99/mo)** minimum, with all Priority 1-2 optimizations applied. If WebSocket quotes are needed, ensure EOD+Intraday tier or higher.

At 200+ tickers without optimization, the 100K daily limit becomes a hard constraint. All Priority 1-3 optimizations should be implemented before scaling beyond ~100 tickers.

---

## Sources

- [EODHD Pricing](https://eodhd.com/pricing)
- [EODHD API Limits Documentation](https://eodhd.com/financial-apis/api-limits)
- [EODHD Bulk API for EOD, Splits and Dividends](https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends)
- [EODHD Bulk Fundamentals API](https://eodhd.com/financial-apis/bulk-fundamentals-api-via-extended-fundamentals-plan)
- [EODHD Historical Stock Prices API](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
- [EODHD Financial News API](https://eodhd.com/financial-apis/stock-market-financial-news-api)
- [EODHD Economic Events API](https://eodhd.com/financial-apis/economic-events-data-api)
- [EODHD Macro Indicators API](https://eodhd.com/financial-apis/macroeconomics-data-and-macro-indicators-api)
- [EODHD Insider Transactions API](https://eodhd.com/financial-apis/insider-transactions-api)
- [EODHD Live/Delayed Stock Prices API](https://eodhd.com/financial-apis/live-ohlcv-stocks-api)
- [EODHD Stock Screener API](https://eodhd.com/financial-apis/stock-market-screener-api)
- [EODHD G2 Pricing 2026](https://www.g2.com/products/eodhd-financial-data-apis/pricing)
