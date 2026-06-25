# Alpaca Ingestion Opportunities Audit

**Date**: 2026-06-16
**Author**: Principal Data-Platform Engineer (read-only investigation)
**Scope**: What additional data Worldview could ingest from Alpaca's API beyond the current 1-minute OHLCV bars

---

## 1. Executive Summary

- **Alpaca is under-exploited.** We use ~1 of 10+ available data products: only 1-minute OHLCV bars for US equities and crypto. The adapter's `fetch_quotes` and `fetch_fundamentals` are wired but either limited (quotes) or raise `ProviderUnavailable` immediately (fundamentals).
- **News is the highest-leverage opportunity.** Alpaca News (Benzinga-sourced, 600-900 headlines/day + 130-160 full articles, dating back to 2015) is **free at 200 req/min** and could supplement or replace EODHD news, which was disabled in migration 0016 (PLAN-0106 Wave C-0) because its per-article credit cost was burning quota. The `NEWS_SENTIMENT` dataset type already exists in the domain.
- **Snapshots enable a zero-cost real-time quote layer.** The `GET /v2/stocks/snapshots` batch endpoint returns latest trade + latest quote + minute bar + daily bar + previous daily bar per symbol in a single request. This is significantly better than the current approach of deriving quotes from the last 1-minute bar (`fetch_quotes` workaround).
- **Corporate actions + split-adjusted bars would eliminate a data-quality gap.** The bars endpoint supports an `adjustment` parameter (`raw`, `split`, `dividend`, `all`) but the adapter never passes it, meaning all stored OHLCV bars are unadjusted. The corporate actions endpoint (`/v1/corporate-actions`) covers 14 action types back to April 2020 at no cost.

---

## 2. Current Alpaca Usage

### What we actually use

| Capability | Adapter Method | Used? | Notes |
|---|---|---|---|
| Single-symbol 1m bars | `fetch_ohlcv()` | Yes | Primary intraday path |
| Batch multi-symbol bars | `fetch_ohlcv_batch()` | Yes | Up to 1000 symbols/request — the key efficiency |
| Intraday alias | `fetch_intraday()` | Yes | Delegates to `fetch_ohlcv` |
| Quote (latest bar proxy) | `fetch_quotes()` | Partial | Returns last 1-min bar close; no real bid/ask |
| Fundamentals | `fetch_fundamentals()` | No | Raises `ProviderUnavailable` by design |
| Crypto bars | `fetch_ohlcv_batch(is_crypto=True)` | Yes | Via `v1beta3/crypto/us/bars` |

### Polling policy coverage

Migration 0011 seeded 50 symbols (US equities/ETFs + 10 crypto). Migration 0014 expanded to ~440 S&P 500 symbols. `InstrumentPolicySyncWorker` (PLAN-0106 Wave D-1) dynamically adds any new US/CC instruments every 6 hours. Migration 0018 bumped Alpaca-1m priority to 100 so these tasks are never preempted. The adapter already batches up to 1000 symbols per HTTP call.

### What is **not** used

The adapter has **zero code** for: news, snapshots, corporate actions, screener/movers/most-actives, options, trades (tick-level), quotes stream (WebSocket), or the assets universe endpoint. The domain `DatasetType` enum also has no entry for these new data types.

### Feed tier

Config: `alpaca_feed = "iex"` (default). IEX = ~15-minute delayed data, free. SIP = real-time, requires Algo Trader Plus ($99/month). All current ingestion uses IEX.

---

## 3. Alpaca Data Product Catalog

### 3.1 Bars (OHLCV)

- **Endpoint**: `GET /v2/stocks/bars` (equity) / `GET /v1beta3/crypto/us/bars` (crypto)
- **Timeframes**: 1Min–59Min, 1Hour–23Hour, 1Day, 1Week, 1Month–12Month (flexible)
- **Adjustment**: `raw` (default), `split`, `dividend`, `spin-off`, `all`, combinable
- **Limit**: 1–10,000 data points per request (shared across symbols in batch)
- **Pagination**: `next_page_token`
- **Extra fields**: `vwap`, `trade_count` (not currently extracted by adapter)
- **Gap vs current**: We already use this. However, we never request `adjustment=all` — all stored bars are **unadjusted**, which distorts historical charts for any symbol that split post-ingestion.

### 3.2 Snapshots

- **Endpoint**: `GET /v2/stocks/snapshots`
- **Data per symbol**: latest trade (price, size, exchange, conditions), latest quote (bid/ask/size), minute bar (OHLCV), daily bar (OHLCV), previous daily bar (OHLCV)
- **Multi-symbol**: Yes — comma-separated list; IEX feed on free tier
- **Rate limit**: 200 calls/min (free), 10,000/min (paid)
- **Cost**: $0 (free tier)
- **Gap vs current**: Significant. Our `fetch_quotes` method fabricates a quote from the last 1-minute bar with no real bid/ask. Snapshots would give us the **actual NBBO quote** (on SIP) or IEX best quote, plus the previous day's close (for day-change computation) in one call.

### 3.3 News

- **Endpoint**: `GET /v1beta1/news`
- **Parameters**: `symbols` (multi-ticker), `start`/`end` (date range), `limit` (1–50/call), `include_content` (boolean for full text), `sort`, `page_token`
- **Fields**: `headline`, `summary`, `content` (full body, if available), `url`, `source`, `author`, `images`, `symbols`, `created_at`, `updated_at`
- **Provider**: Benzinga exclusively
- **Volume**: ~600–900 real-time headlines/day; ~130–160 full articles/day with images
- **History**: Back to 2015
- **Rate limit**: 200 calls/min (free), 10,000/min (paid)
- **Cost**: Currently free (beta status; pricing may change with notice)
- **Delay**: 15-min delay for free tier on real-time; historical is unrestricted
- **Gap vs current**: EODHD `news_sentiment` was **fully disabled** (migration 0016, PLAN-0106 Wave C-0) because news ingestion moved to S4 (content-ingestion). Alpaca News could feed S4's article pipeline as a **zero-cost supplement** to the existing `article_sources` table, reducing dependency on EODHD's 100k credit/day quota.

### 3.4 Corporate Actions

- **Endpoint**: `GET /v1/corporate-actions`
- **14 supported types**: reverse splits, forward splits, unit splits, cash dividends, stock dividends, spin-offs, mergers (cash/stock/mixed), redemptions, name changes, worthless removals, rights distributions, partial calls, reorganizations
- **Filtering**: by symbols, CUSIPs, action types, date range (start/end)
- **History**: Back to April 2020
- **Timeliness**: Available typically before market open on T+1 after declaration; intraday announcements available after market close
- **Rate limit**: 200 calls/min (free); follows market data subscription limits
- **Cost**: $0 (free tier)
- **Gap vs current**: No corporate actions pipeline exists in Worldview. This is the data source that would enable serving **split-adjusted and dividend-adjusted OHLCV bars** (using the `adjustment` parameter on the bars endpoint, and also for backfill correction). Current bars endpoint already supports `adjustment=all`; we just never use it. Having corporate actions in a dedicated table would also power dividend yield calculations in the KG.

### 3.5 Screener: Most Actives

- **Endpoint**: `GET /v1beta1/screener/stocks/most-actives`
- **Parameters**: `by` (volume or trades), `top` (1–100, default 10)
- **Data**: Top N most active US stocks by volume or trade count based on real-time SIP data
- **Rate limit**: 200 calls/min (free)
- **Cost**: $0
- **Gap vs current**: S3 (`market-data`) has `GET /api/v1/market/period-movers` and sector returns, but these are derived from stored OHLCV bars — they are not real-time and do not cover the full universe. The Alpaca most-actives endpoint is a real-time snapshot from SIP (the consolidated tape), covering the entire US equity universe regardless of whether Worldview has ingested bars for those symbols.

### 3.6 Screener: Market Movers (Top Gainers/Losers)

- **Endpoint**: `GET /v1beta1/screener/{market_type}/movers`
- **Parameters**: `market_type` (stocks or crypto), `top` (1–50, default 10)
- **Data**: Top gainers + top losers based on real-time SIP data; % change from prior close; resets at market open
- **Rate limit**: 200 calls/min (free)
- **Cost**: $0
- **Gap vs current**: Same as most-actives. Our `period-movers` endpoint is limited to the symbols we have bars for and uses TimescaleDB aggregation rather than live SIP data. Alpaca's movers cover the full universe in real time.

### 3.7 Assets Universe

- **Endpoint**: `GET /v2/assets`
- **Fields**: `symbol`, `name`, `exchange`, `asset_class`, `status` (active/inactive), `tradable`, `fractionable`, `easy_to_borrow`, `shortable`, `options_enabled`, `overnight_tradable`
- **Coverage**: All US equities + crypto tradable on Alpaca; estimated 8,000–12,000+ active US equity symbols
- **Rate limit**: Trading API limit (200/min free, same key pair)
- **Cost**: $0 (Trading API endpoint, not Market Data API)
- **Gap vs current**: The `instrument_policy_sync_worker` dynamically adds Alpaca 1m policies for all US/CC instruments **registered in Worldview's market-data service**. But there is no path to discover instruments that do not yet exist in Worldview's DB. The Alpaca assets list could seed **new instrument registrations** for any tradable US stock not yet in the universe, expanding coverage cheaply.

### 3.8 Trades (Tick-Level)

- **Endpoint**: `GET /v2/stocks/trades`
- **Data**: Individual executed transactions — timestamp, exchange, price, size, conditions, tape
- **Rate limit**: 200/min (free, IEX feed)
- **Cost**: $0
- **Gap vs current**: We have no tick-level trade data. Not immediately useful for the current thesis scope (chart display and intelligence pipeline do not consume tick data), but foundational for future VWAP calculations or HFT-style signals. Low priority.

### 3.9 Quotes (Historical)

- **Endpoint**: `GET /v2/stocks/quotes`
- **Data**: Historical bid/ask quote ticks; NBBO on SIP, IEX-best on free tier
- **Rate limit**: 200/min (free)
- **Gap vs current**: No historical quote tick storage. Lower priority than snapshots.

### 3.10 Options

- **Free tier**: Indicative pricing only (not real-time OPRA)
- **Paid (OPRA)**: $99/month (Algo Trader Plus)
- **Gap vs current**: No options pipeline. Would require significant new domain model. Out of scope for current thesis.

---

## 4. Ranked Recommendations Table

| Rank | Data Product | Worldview Use Case | Gap Filled | Rate Limit / Cost | Integration Effort | Reuses Existing Plumbing |
|---|---|---|---|---|---|---|
| 1 | **News (Benzinga)** | Feed S4 content-ingestion article pipeline; NLP → KG; morning brief | Replaces disabled EODHD news (0016); zero EODHD quota spend | 200 req/min free; $0 | M — new `DatasetType.NEWS`, new S2 adapter method + S4 consumer OR direct S4 Alpaca client | Partially — `DatasetType`, `ProviderFetchResult`, Kafka outbox, `market.dataset.fetched` topic all reusable |
| 2 | **Snapshots** | Dashboard real-time quotes; day-change calculation; morning brief tape | Replaces fabricated-quote workaround in `fetch_quotes` (no real bid/ask today) | 200 req/min free; $0 | S — one new method on existing adapter; maps to existing `DatasetType.QUOTES` | Yes — same adapter, same dataset type, same consumer |
| 3 | **Split-adjusted bars (`adjustment=all`)** | Correct historical charts for post-split symbols; accurate backtest data | Eliminates unadjusted-bar data quality bug for all split events post-ingestion | 0 extra calls; parameter change only | S — one-line change to `_TIMEFRAME_MAP` / `fetch_ohlcv` + optional backfill flag | Yes — identical endpoint, no new consumer |
| 4 | **Corporate Actions** | Dividend yield enrichment in KG; audit trail for split-adjusted price jumps | No corporate actions data source exists | 200 req/min free; $0 | M — new `DatasetType.CORPORATE_ACTIONS`; new DB table + consumer in S3; new adapter method | Partially — adapter, polling policy, `DatasetType` enum, Kafka outbox reuse; new S3 table needed |
| 5 | **Most Actives / Movers** | Screener "Top by activity" widget; dashboard daily briefing | Extends period-movers beyond stored-bar universe to full SIP coverage | 200 req/min free; $0 | S — no storage needed; direct S9/API gateway proxy or S3 pass-through | No — no polling/storage needed; pure pass-through or on-demand call |
| 6 | **Assets Universe** | Expand instrument coverage to full Alpaca tradable universe | New symbols not in Worldview DB cannot get Alpaca 1m policies today | 200 req/min free; $0 | M — new bootstrap/sync job; calls `/v2/assets` and creates `market.instrument.discovered.v1` events | Partially — event emission reusable; new job or extension of `InstrumentPolicySyncWorker` |

---

## 5. Top 3 Highest-Leverage Picks

### Pick 1: Alpaca News (Rank 1)

**Rationale**: EODHD news was disabled (migration 0016, June 2026) because S4 content-ingestion took over the news pipeline — but S4's actual news volume depends on EODHD's `api/news` endpoint, which costs **5 credits per call** against a 100k/day quota shared with fundamentals, quotes, and economic data. Alpaca News is currently **free** (beta), covers 600-900 headlines/day from Benzinga with full text available via `include_content=true`, and dates back to 2015.

The `DatasetType.NEWS_SENTIMENT` enum already exists. Integration options:
- **Option A** (minimal): Add `fetch_news` to `AlpacaProviderAdapter`, create an Alpaca-routed polling policy in migration `002X` for `dataset_type=news_sentiment`, and let the existing `market.dataset.fetched` → S4 consumer path handle it. The S4 consumer already reads `raw_data` from MinIO and inserts into `article_sources`.
- **Option B** (preferred for long-term): Add a direct Alpaca client in S4 (`content-ingestion`) so news does not route through S2 at all, keeping separation of concerns cleaner. S2 is for market data; news content belongs in S4.

The `routing_news_sentiment` config string currently defaults to `"eodhd:100"` but all policies are disabled. Adding `"alpaca:100"` after enabling would work with zero adapter changes if Option A is chosen.

**Tradeoffs**: Benzinga-only sourcing (no Reuters/AP diversity). 15-min delay on free tier (acceptable for daily sentiment; irrelevant for most intelligence use cases). Pricing may change post-beta (mitigate by abstracting behind `DatasetType.NEWS`).

### Pick 2: Snapshots for Real-Time Quotes (Rank 2)

**Rationale**: The current `fetch_quotes()` in the Alpaca adapter returns a fabricated quote derived from the last 1-minute bar's close price. The adapter comment explicitly acknowledges: "Alpaca IEX feed does not expose [bid/ask] — left as None". This means every dashboard `Quote` record sourced from Alpaca has `bid=None, ask=None`, and `last_price = close_of_last_1m_bar` — a stale proxy. The snapshots endpoint fixes this with minimal effort.

Implementation: Add `fetch_snapshots_batch(symbols: list[str]) -> dict[str, ProviderFetchResult]` to `AlpacaProviderAdapter`. The endpoint returns one response object per symbol containing: `latestTrade.price`, `latestQuote.ap`/`bp` (ask/bid), `minuteBar`, `dailyBar`, `prevDailyBar`. Map `latestTrade.price` → `last`, `latestQuote.ap`/`bp` → `ask`/`bid`, and `prevDailyBar.c` → `prev_close`. The `prev_close` field is what S3's `PriceSnapshotResolver` uses to compute `price_change_pct` (see BP-628 / PLAN-0102 context in `.claude-context.md`). Today the resolver has to look up `ohlcv_bars(1d)` for prior close; snapshots would deliver it in the same call as the quote.

**Cost**: Zero extra calls if snapshots replace per-symbol `fetch_quotes` calls (same 200/min budget, but one call for up to ~N symbols instead of N calls).

### Pick 3: Split-Adjusted Bars via `adjustment=all` (Rank 3)

**Rationale**: The current `fetch_ohlcv` and `fetch_ohlcv_batch` methods do not pass any `adjustment` parameter to the Alpaca bars endpoint. The Alpaca API defaults to `raw` (unadjusted). This means every chart rendered for a symbol that split after its bars were ingested shows a price discontinuity (e.g., NVDA's 10:1 split in June 2024 would create a 90% drop visible in historical charts).

Implementation is **a single parameter addition** — add `"adjustment": "all"` to the `params` dict in both `fetch_ohlcv()` and `_fetch_chunk()` inside `fetch_ohlcv_batch()`. This has zero architectural impact. The only downstream consideration is that any existing stored bars become "stale" (unadjusted), so a backfill of historical data with `adjustment=all` would be advisable. The existing `BackfillUseCase` handles this.

**Tradeoffs**: Unadjusted bars are the correct choice for **price monitoring / alert thresholds** (you want the raw traded price for an active stop-loss). For chart display and backtesting, adjusted bars are correct. A clean solution would add an `adjustment` setting to `PollingPolicy` so both can coexist in the DB — but even a simple global default of `adjustment=all` for the chart-display use case would be a significant improvement over the current zero-adjustment status.

---

## 6. Current Adapter Efficiency Gaps

### Gap 1: `fetch_quotes` is a 1-minute bar proxy, not a real quote

`fetch_quotes()` calls `GET /v2/stocks/bars?limit=1&sort=desc&timeframe=1Min` and extracts the bar's close price as the "last" price. This is not a quote — it is the close price of the most recently completed 1-minute bar, which could be up to 75 seconds stale. The snapshots endpoint (`/v2/stocks/snapshots`) returns the true latest trade and NBBO quote in the same request.

**Quick win**: Replace `fetch_quotes` with a snapshots call. No routing or consumer changes needed.

### Gap 2: All bars are unadjusted (no `adjustment` parameter)

As described in Pick 3 above. A one-line parameter addition to `fetch_ohlcv` and `_fetch_chunk` would correct this for all future ingestion.

### Gap 3: `vwap` and `trade_count` fields are discarded

The Alpaca bars endpoint returns `vwap` (volume-weighted average price) and `trade_count` per bar in its response. The `_normalize_bars` method currently extracts only `{datetime, open, high, low, close, volume}` and silently drops `vwap` and `trade_count`. These fields are not in the `CanonicalOHLCVBar` model either. VWAP is highly useful for algorithmic trading signals and screener metrics. Adding it would require: a new column on `ohlcv_bars`, a schema migration, and updating `_normalize_bars`. Medium effort, high analytical value.

### Gap 4: `next_page_token` pagination is never followed

Both `fetch_ohlcv` and `_fetch_chunk` make a single HTTP call with `limit=10000`. If a symbol has more than 10,000 bars in the requested range (roughly ~7 trading days at 1-minute resolution), the response will include a `next_page_token` indicating truncation — but the adapter ignores it and returns only the first page. For backfill scenarios spanning weeks or months, this silently truncates history. A pagination loop inside `_fetch_chunk` would fix this.

### Gap 5: No retry on `next_page_token` for batch calls

Related to Gap 4. For batch calls where `limit` is shared across all symbols, a batch of 10 symbols over a 1-week range could easily exceed 10,000 total bars (10 symbols × ~5 trading days × ~390 bars/day ≈ 19,500 bars). The adapter does not detect the truncation. Smaller batch sizes or per-symbol pagination would be required.

### Gap 6: `routing_news_sentiment` still routes to EODHD despite all policies being disabled

After migration 0016 disabled all `news_sentiment` policies, the config default (`routing_news_sentiment = "eodhd:100"`) was not updated. This is a latent mismatch — if a news policy is re-enabled manually, it would attempt EODHD routing and consume quota. Should be updated to `"alpaca:100"` when a news adapter method is added.

---

## 7. Rate Limit and Cost Analysis

### Alpaca vs EODHD comparison

| Dimension | EODHD (current primary) | Alpaca (current supplemental) |
|---|---|---|
| **Daily quota** | 100,000 credits/day (hard cap) | Effectively unlimited for free-tier data products; 200 req/min |
| **News cost** | 5 credits/call (~50 articles) | $0; 200 req/min; 130-160 full articles/day |
| **Intraday bars** | 5 credits/call (per symbol) | $0; batched (1000 symbols/request) |
| **EOD bars** | 1 credit/call | Not used (Yahoo Finance handles EOD for free) |
| **Quotes** | 1 credit/call | $0 (via snapshot) |
| **Fundamentals** | 10 credits/call | Not available |
| **Corporate actions** | Not available | $0 |
| **Screener / Movers** | Not available | $0 |
| **Real-time data** | Intraday: 5 credits, ~15-min delayed | IEX: ~15-min delayed (free); SIP real-time = $99/month |

### Quota pressure relief

EODHD's 100k/day credit budget is consumed by:
1. Fundamentals (10 credits each × ~500 symbols × quarterly = ~5,000 credits/refresh cycle but ~300-500/day during active refresh)
2. Quotes (1 credit × universe size × polling cadence)
3. News sentiment — **was 5 credits/call, but was disabled precisely because of quota pressure**
4. Economic events, macro indicators, earnings calendar, yield curve (1-5 credits each)
5. Insider transactions (1 credit each)

Offloading news to Alpaca directly frees ~5 credits per news fetch cycle, compounding across the symbol universe. For 500 symbols fetched daily at 50 articles/call, that is 500 × 5 = 2,500 credits/day saved — a 2.5% budget relief, meaningful during fundamentals refresh cycles.

### Risk: Alpaca news beta pricing

The news endpoint is labeled "currently available as a limited-time beta at no cost" with a warning that "after the limited-time beta period... there may be additional pricing changes." This is a real dependency risk. Mitigation: abstract Alpaca news behind `DatasetType.NEWS_SENTIMENT` with a routing config so EODHD or Finnhub can be substituted by changing `routing_news_sentiment` without code changes.

### Risk: Alpaca free-tier rate limit (200 req/min)

For the current universe size (~500-700 Alpaca 1m policies), the batch endpoint (1000 symbols/request) means 1-2 HTTP calls per 1-minute tick — well within 200 req/min. Adding snapshots for 700 symbols adds 1 more call/tick (batch of 700 commas). Adding news adds ~15 calls/day across the full universe. Total projected Alpaca call rate: well under 10 req/min, leaving 190 req/min headroom before approaching the free-tier cap.

---

*Generated from read-only investigation of codebase + Alpaca API documentation. No code changes were made.*
