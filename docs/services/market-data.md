# Market Data Service (S3)

> **Owner**: Market Data domain · **Database**: `market_data_db` (TimescaleDB) · **Port**: 8003
> **Status**: Production-ready (waves 01–16 shipped, including intraday resampling, prediction markets, price snapshots, and sector aggregations)

---

## Mission & Boundaries

**Owns**: Materializing OHLCV bars, quotes, and fundamentals from claim-check pointers.
Serving query APIs for charts, fundamentals, and instrument metadata. Security/instrument
master data. Instrument lifecycle events. Materializing Polymarket prediction market
snapshots from `market.prediction.v1` Kafka events.

**Never does**: Fetch data from upstream providers (Market Ingestion's job), store news
or articles, perform NLP processing, manage portfolios.

---

## API Surface (60 routes: 3 ops + 50 public `/api/v1` + 7 internal `/internal/v1`)

| Method | Path | Description | Cache Tier |
|--------|------|-------------|------------|
| GET | `/healthz` | Liveness probe — always 200 | — |
| GET | `/readyz` | Readiness (DB + Valkey + Storage + Kafka) | — |
| GET | `/metrics` | Prometheus metrics — requires `X-Internal-Token` header (M-004) | — |
| GET | `/api/v1/instruments` | List instruments — query params: `query`, `has_ohlcv`, `has_quotes`, `has_fundamentals`, `exchange`, `limit`, `offset` (all DB-side) | — |
| GET | `/api/v1/instruments/lookup` | Unified instrument lookup — query params: `symbol` (icase), `isin`, `id` (UUID), `extra_info` (bool, default false). Priority: id > isin > symbol. `extra_info=true` also returns `name`, `description`, `sector`, `industry`, `country`, `currency_code`. Requires `X-Internal-JWT`. | — |
| GET | `/api/v1/instruments/on-demand-profile` | On-demand instrument profile — query param: `ticker` or `isin`. DB-first (returns `source="db"` if description populated); falls back to EODHD, persists result (`source="eodhd_persisted"`). Raises 429 if EODHD rate-limited. Requires `X-Internal-JWT`. | — |
| GET | `/api/v1/instruments/{instrument_id}/peers` | Top-N market-cap peers in the same GICS industry (PLAN-0100 W5). Query param: `limit`. | — |
| GET | `/api/v1/instruments/{instrument_id}/intraday-stats` | Intraday session stats (B-Q-2) | — |
| GET | `/api/v1/instruments/{instrument_id}/returns` | Multi-period returns (B-Q-3) | — |
| GET | `/api/v1/instruments/{instrument_id}/price-levels` | 52w high/low + distance-from levels (B-Q-4) | — |
| GET | `/api/v1/ohlcv/bars` | OHLCV bars (flexible: query params `instrument_id` or `symbol`, `timeframe`, `start`, `end`) | — |
| GET | `/api/v1/ohlcv/bulk` | Bulk OHLCV for multiple instruments | — |
| GET | `/api/v1/ohlcv/{instrument_id}` | OHLCV bars (query: `timeframe`, `start`, `end`) | — |
| GET | `/api/v1/ohlcv/{instrument_id}/timeframes` | Available timeframes for instrument | — |
| GET | `/api/v1/ohlcv/{instrument_id}/range` | Date range of available OHLCV data | — |
| GET | `/api/v1/quotes/latest` | Batch quotes by query params (`?instrument_ids=…`) | Valkey 5 s |
| GET | `/api/v1/quotes/{instrument_id}` | Latest quote — cache-aside | Valkey 5 s |
| POST | `/api/v1/quotes/batch` | Batch quotes via POST body | Valkey 5 s |
| GET | `/api/v1/fundamentals/{instrument_id}` | Full fundamentals (all 18 sections) — `{instrument_id}` is instrument UUID | — |
| GET | `/api/v1/fundamentals/{instrument_id}/income-statement` | Income statement. `?period_type=quarterly\|annual` selects one periodicity (2026-06-11); omitted = all rows mixed (back-compat) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/balance-sheet` | Balance sheet. `?period_type=quarterly\|annual` (2026-06-11); omitted = QUARTERLY (BP-546 repo default) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/cash-flow` | Cash flow. `?period_type=quarterly\|annual` (2026-06-11); omitted = QUARTERLY (BP-546 repo default) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/highlights` | Highlights (TTM metrics) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/valuation` | Valuation ratios | — |
| GET | `/api/v1/fundamentals/{instrument_id}/analyst-consensus` | Analyst estimates | — |
| GET | `/api/v1/fundamentals/{instrument_id}/dividends` | Dividend history | — |
| GET | `/api/v1/fundamentals/{instrument_id}/earnings` | Earnings history | — |
| GET | `/api/v1/fundamentals/{instrument_id}/company-profile` | Company profile snapshot | — |
| GET | `/api/v1/fundamentals/{instrument_id}/institutional-holders` | Institutional holders | — |
| GET | `/api/v1/fundamentals/{instrument_id}/fund-holders` | Fund holders | — |
| GET | `/api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot` | Insider transactions snapshot | — |
| GET | `/api/v1/fundamentals/{instrument_id}/technicals-snapshot` | Technicals snapshot (52w high/low, beta, etc.) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/share-statistics` | Share statistics (shares outstanding, float) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/splits-dividends` | Splits & dividends section | — |
| GET | `/api/v1/fundamentals/{instrument_id}/earnings-trend` | Earnings trend (quarterly estimates) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/earnings-annual-trend` | Earnings annual trend | — |
| GET | `/api/v1/fundamentals/{instrument_id}/snapshot` | Pre-computed derived metrics snapshot — returns one flat row from `instrument_fundamentals_snapshot` table (eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating, updated_at). Always 200 — all fields null for un-backfilled instruments. PLAN-0050 Wave D. | — |
| GET | `/api/v1/fundamentals/history` | Multi-period fundamentals history across sections (PLAN-0095 W1) — query params: `instrument_id`/`ticker`, `periods`, `period_type`. | — |
| POST | `/api/v1/fundamentals/batch` | Batch fundamentals fan-out — body `{tickers: list[str] (cap 25), periods: int}`. Per-ticker two-phase `asyncio.gather` (resolve → fetch); partial failures isolate. Typed `reason` codes only (`invalid_ticker`/`upstream_timeout`/`upstream_404`/`upstream_error`). For rag-chat screener→fundamentals fan-out (BP-582/592). | — |
| POST | `/api/v1/fundamentals/query` | Generic fundamentals query (section + filters) — `FundamentalsQueryResponse`. | — |
| GET | `/api/v1/fundamentals/timeseries` | Metric timeseries — query params: `instrument_id`, `metric`, `start_date`, `end_date`, `period_type`, `limit`. Returns 422 if `start_date > end_date`. | — |
| GET | `/api/v1/fundamentals/screen` | Convenience GET screen — single metric filter via query params; inherits the default ORDER BY (primary filter metric desc, else `market_capitalization` desc). | — |
| POST | `/api/v1/fundamentals/screen` | Screen instruments by metric thresholds (AND logic) — JSON body: `filters[]` (each filter may include `metric`, `min_value`, `max_value`, `period_type`, `sector`), `limit` (default 50, max 200), `offset` (max 5000), `sort_by` (metric name, `ticker`, or `name`; validated whitelist — SQL injection guard), `sort_order` (`asc`/`desc`). Response rows enriched with `_KEY_METRICS` display set (mkt cap, P/E, daily_return, revenue_ttm, dist_from_52w_*) + `volume`/`high_52w`/`low_52w` + `total` (COUNT(*) OVER()). | — |
| GET | `/api/v1/fundamentals/screen/fields` | Screenable field metadata (label, type, unit, observed min/max) — Valkey-fallback to `screen_field_metadata`. | — |
| GET | `/api/v1/fundamentals/metrics/{instrument_id}` | List available metric names for an instrument | — |
| GET | `/api/v1/securities` | List securities — query params: `figi`, `isin`, `limit`, `offset` (paginated DB scan when unfiltered) | — |
| GET | `/api/v1/securities/{security_id}` | Security detail by FIGI or ISIN | — |
| GET | `/api/v1/prediction-markets` | List prediction markets — query params: `status` (`open`/`resolved`/`cancelled`/`all`), `limit`, `offset`, `category`, `query`. Ordered by latest `volume_24h` DESC (recently-traded first). The latest-volume `LEFT JOIN LATERAL` over `prediction_market_snapshots` is time-bounded to `prediction_market_list_volume_window_days` (default 30d) so the TimescaleDB hypertable prunes to recent chunks — an **unbounded** LATERAL cold-scans every weekly chunk per market and 500s the endpoint under load (PLAN-0056 QA). Markets with no snapshot in-window get `volume_24h=null` and sort last. | — |
| GET | `/api/v1/prediction-markets/categories` | Per-category counts of currently-open markets (PLAN-0053) | — |
| GET | `/api/v1/prediction-markets/events` | List Polymarket event groups (newest first) — query params: `limit` (1..200), `offset` (PLAN-0056 A4) | — |
| GET | `/api/v1/prediction-markets/events/{event_id}` | Single event group (HTTP 404 if unknown) (PLAN-0056 A4) | — |
| GET | `/api/v1/prediction-markets/{market_id}` | Prediction market detail with latest snapshot | — |
| GET | `/api/v1/prediction-markets/{market_id}/history` | Prediction market history — query params: `from`, `to` (HTTP 400 if `from >= to`), `limit` (1..2000). **Default**: probability snapshots (each includes `liquidity`, PLAN-0056 A1). **With `interval=1h\|1d\|1w`** (+ optional `token_id`): per-token interval price bars from the `prediction_market_prices` hypertable — returns `{market_id, interval, points[]}` (PLAN-0056 A4) | — |
| GET | `/api/v1/prediction-markets/{market_id}/trades` | Recent executed fills, newest first — query params: `since` (UTC), `limit` (1..200). HTTP 404 if market unknown (PLAN-0056 A4) | — |
| GET | `/api/v1/market/sector-returns` | Sector heatmap data — query param: `period` (`1D`, `1W`, `1M`). Returns average period return per GICS sector from OHLCV bars. | — |
| GET | `/api/v1/market/period-movers` | Top gainers or losers — query params: `period` (`1W`/`1M`), `type` (`gainers`/`losers`), `limit` (1–50, default 10). Returns instruments sorted by period_return_pct. | — |
| GET | `/internal/v1/price/{instrument_id}` | Price snapshot for a single instrument — cache-aside: Valkey → Quote → OHLCV fallback. Returns 404 if no data available. **Internal endpoint — S9 only.** | Valkey |
| POST | `/internal/v1/price/batch` | Price snapshots for up to 50 instruments. Instruments with no data are silently omitted (partial results valid). **Internal endpoint — S9 only.** | Valkey |
| GET | `/internal/v1/instruments` | Internal instrument list (JWT-guarded). | — |
| GET | `/internal/v1/instruments/top-by-market-cap` | Top-N instruments by market cap — consumed by market-ingestion's `FundamentalsRefreshWorker` (PLAN-0100 T-W5-01). **Internal — JWT required.** | — |
| GET | `/internal/v1/instruments/ohlcv-covered` | Every `has_ohlcv=TRUE` instrument, paginated by symbol ASC — consumed by market-ingestion's `InsiderUniverseLoader` (Wave L-4b). **Internal — JWT required.** | — |
| GET | `/internal/v1/market/tape` | Futures/pre-market tape snapshot for the rag-chat morning brief (PLAN-0102 W3). `session` ∈ `pre-mkt`/`open`/`after-hours`/`closed`/`unavailable`. Symbol list capped at 20; never 500s (per-symbol failures degrade to `unavailable`). **Internal — JWT required.** | — |
| GET | `/internal/v1/calendar/earnings` | Forward-looking earnings calendar from `earnings_calendar` table (PLAN-0102 W3). `when` = BMO/AMC/DMH; range cap 90 days; fail-open (empty `events: []`, never 500). **Internal — JWT required.** | — |

> **Note on path ordering**: Literal-segment routes (`/ohlcv/bars`, `/ohlcv/bulk`, `/quotes/latest`,
> `/instruments/lookup`, `/instruments/on-demand-profile`) are registered **before** path-param routes
> (`/ohlcv/{instrument_id}`, `/quotes/{instrument_id}`)
> to avoid FastAPI matching the literal as a path param. The `fundamental_metrics` router
> is registered before the `fundamentals` router so that `/fundamentals/timeseries`,
> `/fundamentals/screen`, and `/fundamentals/metrics/{id}` are not matched by
> `/fundamentals/{security_id}`.
>
> **Fundamentals path param**: The path parameter is named `instrument_id` and represents
> the **instrument UUID** (primary key of the `instruments` table), not `securities.id`.
> Fundamentals are stored per instrument, not per security.
>
> `/metrics` is exposed by the `observability.metrics.add_prometheus_middleware` middleware,
> not a registered router endpoint.

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose | Idempotency |
|-------|---------------|---------|-------------|
| `market.dataset.fetched` | `market-data-ohlcv` | Materialize OHLCV bars | `event_id` in `ingestion_events` |
| `market.dataset.fetched` | `market-data-quotes` | Materialize quotes | `event_id` |
| `market.dataset.fetched` | `market-data-fundamentals` | Materialize fundamentals (filters `dataset_type=fundamentals`) | `event_id` |
| `market.dataset.fetched` | `market-data-intraday-resampling` | Derive 5m/15m/30m/1h/4h/1d bars from `dataset_type=ohlcv, timeframe=1m` events | `event_id` |
| `market.dataset.fetched` | `market-data-insider-transactions` | Materialize per-transaction insider feed (`dataset_type=insider_transactions`) | `event_id` |
| `market.dataset.fetched` | `market-data-earnings-calendar` | Materialize the global EODHD `/calendar/earnings` feed (`dataset_type=earnings_calendar`) into `earnings_calendar` — ONE message → many companies, each row's `code` (`TICKER.EXCHANGE`) resolved to an instrument; unknown instruments skipped, upsert on `(instrument_id, report_date)`. Feeds the screener `next_earnings_date` column via `fetch_next_earnings_date` | `event_id` + content-hash |
| `market.prediction.v1` | `market-data-prediction-markets` | Materialize prediction market snapshots (PRD-0019) | Atomic `create_if_not_exists` + `insert_if_not_exists` |
| `market.prediction.history.v1` | `market-data-prediction-history` | Materialize per-token interval price bars into `prediction_market_prices` (PLAN-0056 A3) | Atomic `create_if_not_exists` + `insert_if_not_exists` |
| `market.prediction.event.v1` | `market-data-prediction-events` | Upsert Polymarket event groups into `prediction_events` (group_id→event_id) (PLAN-0056 A3) | Atomic `create_if_not_exists` + `ON CONFLICT DO UPDATE` |
| `market.prediction.trade.v1` | `market-data-prediction-trades` | Materialize individual fills into `prediction_market_trades` (PLAN-0056 A3) | Atomic `create_if_not_exists` + `insert_if_not_exists` |
| `market.prediction.oi.v1` | `market-data-prediction-oi` | Upsert daily OI / 24h-volume roll-ups into `prediction_market_oi` (PLAN-0056 A3) | Atomic `create_if_not_exists` + `ON CONFLICT DO UPDATE` |

### Produced

| Topic | Event Type | Key |
|-------|-----------|-----|
| `market.instrument.created` | `InstrumentCreated` (v3) | `instrument_id` |
| `market.instrument.updated` | `InstrumentUpdated` | `instrument_id` |
| `market.instrument.discovered.v1` | `InstrumentDiscovered` | `instrument_id` |
| `market.prediction.move.v1` | `PredictionMarketMove` (`market.prediction.move`) | `market_id` |

PLAN-0056 Wave D1: the `PredictionMoveDetector` periodic worker emits
`market.prediction.move.v1` when an open market's implied probability moves
materially over a lookback window — gated on `|Δ| ≥ τ` AND `liquidity ≥ floor`
AND `volume_24h ≥ floor` (all env-driven) so noise never fires. Payload carries
`market_id` (Polymarket conditionId), `token_id`, `outcome_name`, `interval`,
`prev_price`, `new_price`, `delta`, `direction` (up/down), `liquidity`,
`volume_24h`, `window_start_ts`, `is_backfill=false`.

**QA fix (2026-07-10) — affirmative-outcome move only.** A Polymarket market is
binary (Yes/No) and the two tokens move equal-and-opposite, so emitting a move
per outcome produced two complementary events per `(market_id, window)`. S7's
signal emitter dedups on a `uuid5` that omits `token_id`, so the two collapsed
and an arbitrary one won — inverting polarity/adverseness for the No token. The
detector now emits **at most one** move per market per cycle, for the
**affirmative** outcome: the outcome named `"yes"` (case-insensitive), else the
**first** outcome in the market's static `outcomes` list (JSONB order —
deterministic). This ties the move to the exact frame the polarity classifier
reasons about. Non-binary markets are tracked by their affirmative/first outcome
only (accepted simplification). **Window-start fix:** Δ is now measured from the
true window-start snapshot (`get_earliest_snapshot_at_or_after`, an
`ORDER BY snapshot_at ASC LIMIT 1` read-replica read) instead of the oldest row
of the LIMIT-capped `list_snapshots` page — which was only the true start when a
market had ≤`snapshot_limit` snapshots in the window, otherwise silently
shrinking the window and dropping slow moves below τ.
Emitted through the outbox (R8, `partition_key=market_id`) and dispatched by
`market-data-dispatcher`. Consumed by S7's `PredictionSignalEmitter` (Wave D2)
which joins `market_id` to entity exposures + polarity and fans a per-entity
signal out to the alert pipeline. Dedup: an in-memory watermark per
`(market_id, token_id)` re-emits only when the latest snapshot is strictly
newer than the last emitted; cross-restart duplicates are absorbed by S7's
per-`(condition_id, trigger, window)` idempotency.

PLAN-0057 Wave D-2: ohlcv/quotes consumers emit `market.instrument.discovered.v1`
on first-seen symbols (lightweight: just `instrument_id` + `symbol` + `exchange`).
fundamentals_consumer emits the rich `market.instrument.created` (v3, schema with
the four EODHD identifier fields cusip / figi / lei / primary_ticker — all
nullable + null defaults for forward-compat) on every False→True transition of
`has_fundamentals`, gated on the presence of a real EODHD `Name`. KG subscribes
to both topics: discovered.v1 seeds a placeholder canonical, created promotes it
to a fully-named, alias-rich, embedding-backed canonical via the
UPSERT-after-discover branch in `InstrumentEntityConsumer`.

---

## Database Schema

```sql
-- market_data_db (TimescaleDB extension required)

CREATE TABLE securities (
    id          UUID PRIMARY KEY,
    figi        VARCHAR(12) UNIQUE,
    isin        VARCHAR(12),
    name        TEXT NOT NULL,
    sector      TEXT,
    industry    TEXT,
    country     VARCHAR(3),
    currency    VARCHAR(3),
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE instruments (
    id              UUID PRIMARY KEY,
    security_id     UUID REFERENCES securities(id),
    symbol          VARCHAR(20) NOT NULL,
    exchange        VARCHAR(10) NOT NULL,
    instrument_type VARCHAR(20),
    is_active       BOOLEAN DEFAULT true,
    has_ohlcv       BOOLEAN DEFAULT false,
    has_quotes      BOOLEAN DEFAULT false,
    has_fundamentals BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, exchange)
);

-- TimescaleDB hypertable
CREATE TABLE ohlcv_bars (
    instrument_id   UUID NOT NULL REFERENCES instruments(id),
    timeframe       VARCHAR(5) NOT NULL,
    bar_date        TIMESTAMPTZ NOT NULL,
    open            NUMERIC(18,6),
    high            NUMERIC(18,6),
    low             NUMERIC(18,6),
    close           NUMERIC(18,6),
    adjusted_close  NUMERIC(18,6),
    volume          BIGINT,
    source          VARCHAR(20),
    provider_priority INTEGER DEFAULT 0,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (instrument_id, timeframe, bar_date)
);
SELECT create_hypertable('ohlcv_bars', 'bar_date');
-- Provider-priority ladder (higher wins the `EXCLUDED.provider_priority >=`
-- upsert guard); resolved from the canonical `source` string in
-- `market_data.domain.enums._PROVIDER_PRIORITIES`:
--   eodhd_bulk=120  authoritative DAILY EOD (EODHD /eod-bulk-last-day) — CORRECT
--                   consolidated volume + adjusted_close; one 100-credit call per
--                   exchange/day via the `bulk_eod_daily` CronJob (market-ingestion).
--   eodhd_intraday=115  once-daily POST-CLOSE 1m refinement (EODHD /intraday) —
--                   CORRECT consolidated CTA/UTP volume for the CLOSED day. UTC
--                   bar-start minute timestamps ALIGN with Alpaca's 1m bar_date, so
--                   it REPLACES the IEX 1m bar (110) on the same conflict key; the
--                   intraday_resampling consumer then re-derives 5m..4h from the
--                   corrected 1m. Via the `intraday_refine` CronJob (market-ingestion,
--                   ~5 credits/symbol). Alpaca stays the LIVE intra-session 1m source.
--   alpaca=110      intraday 1m (LIVE source of truth) + polled 1Day daily FALLBACK.
--                   NOTE: Alpaca's free IEX daily volume is ~19-30x understated and
--                   its adjusted_close is NULL — eodhd_bulk (120) overwrites it for 1d;
--                   its intraday 1m volume is IEX-only (~5%) — eodhd_intraday (115)
--                   overwrites it for a CLOSED day.
--   derived=110     locally resampled 5m..4h from the 1m series (Alpaca live +
--                   eodhd_intraday post-close refinement).
--   polygon=100 · yahoo_finance/yahoo=80 (historical only) · eodhd=60 (per-ticker
--   deep-history / failover daily) · alpha_vantage=40 · macrotrends=20 · unknown=0.
-- Requires the `fix/ohlcv-dup-bars` UTC-midnight `bar_date` normalization so
-- per-provider daily bars share one conflict key and the priority guard fires.

CREATE TABLE quotes (
    instrument_id   UUID PRIMARY KEY REFERENCES instruments(id),
    bid             NUMERIC(18,6),
    ask             NUMERIC(18,6),
    last_price      NUMERIC(18,6),
    volume          BIGINT,
    timestamp       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- 18 fundamentals tables:
-- Period-based (14): income_statement, balance_sheet, cash_flow, highlights, valuation_ratios,
--   technicals_snapshot, share_statistics, splits_dividends, analyst_consensus,
--   earnings_history, earnings_trend, earnings_annual_trend, dividend_history, outstanding_shares
-- Non-period (4): company_profiles, institutional_holders, fund_holders, insider_transactions_snapshot

CREATE TABLE ingestion_events (
    event_id    UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ DEFAULT now()
);
-- RETENTION (2026-07-18 disk-full fix): ingestion_events is one idempotency row
-- per processed Kafka event and grew unbounded (~1 GB / 3.7M rows). The
-- market-data dispatcher_main process now runs a periodic pruner
-- (messaging.kafka.maintenance.RetentionCleanupWorker) that batch-deletes rows
-- older than MARKET_DATA_INGESTION_EVENTS_RETENTION_DAYS (default 14) on the
-- actual append column `occurred_at`. See docs/libs/messaging.md "Generic Table
-- Retention Pruner". One-time reclaim of already-bloated files needs a
-- maintenance-window VACUUM FULL / pg_repack.

CREATE TABLE failed_tasks (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL,
    event_type      VARCHAR(100),
    error_message   TEXT,
    attempt_count   INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 5,
    next_retry_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE outbox_events (...);  -- same pattern as Portfolio
-- RETENTION (2026-07-18 disk-full fix): like content-ingestion's, this outbox
-- marks published rows status='delivered' (mark_dispatched) but the claimable
-- index does not cover them, so delivered rows would pile up. The
-- dispatcher_main process prunes delivered rows older than
-- MARKET_DATA_OUTBOX_RETENTION_SECONDS (default 3600) on dispatched_at — NEVER
-- pending/processing/failed/dead_letter. See docs/libs/messaging.md.

-- Read-optimized projection: one row per (instrument_id, as_of_date, metric, period_type)
-- Source of truth remains the 18 section tables; this is a derived projection.
CREATE TABLE fundamental_metrics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id   UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    as_of_date      DATE NOT NULL,
    metric          VARCHAR(64) NOT NULL,
    value_numeric   NUMERIC(24, 6) NULL,
    value_text      TEXT NULL,
    period_type     VARCHAR(20) NULL,   -- ANNUAL | QUARTERLY | SNAPSHOT
    section         VARCHAR(64) NULL,   -- source section (e.g. analyst_consensus)
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_fundamental_metrics_instrument_date_metric
    ON fundamental_metrics (instrument_id, as_of_date, metric, period_type);
CREATE INDEX ix_fundamental_metrics_metric_date
    ON fundamental_metrics (metric, as_of_date);
CREATE INDEX ix_fundamental_metrics_instrument_metric
    ON fundamental_metrics (instrument_id, metric, as_of_date);

-- PLAN-0050 Wave D: One-row-per-instrument pre-computed snapshot of 10 derived metrics.
-- Populated by: services/market-ingestion/scripts/backfill_fundamentals.py (nightly UPSERT).
-- Purpose: avoids multi-section JSONB joins at query time for InstrumentKeyMetrics + FundamentalsTab.
-- Note: credit_rating is always NULL (EODHD does not expose S&P/Moody's ratings).
CREATE TABLE instrument_fundamentals_snapshot (
    instrument_id       UUID PRIMARY KEY REFERENCES instruments(id) ON DELETE CASCADE,
    eps_ttm             NUMERIC(18, 6) NULL,
    beta                NUMERIC(10, 6) NULL,
    avg_volume_30d      BIGINT NULL,
    operating_cash_flow NUMERIC(24, 2) NULL,
    capex               NUMERIC(24, 2) NULL,
    free_cash_flow      NUMERIC(24, 2) NULL,
    fcf_margin          NUMERIC(10, 6) NULL,
    interest_coverage   NUMERIC(12, 4) NULL,
    net_debt_to_ebitda  NUMERIC(12, 4) NULL,
    credit_rating       VARCHAR(10) NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_fundamentals_snapshot_updated_at ON instrument_fundamentals_snapshot (updated_at);

-- PRD-0019: Polymarket prediction markets
CREATE TABLE prediction_markets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id           TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'polymarket',
    question            TEXT NOT NULL,
    description         TEXT,
    outcomes            JSONB NOT NULL DEFAULT '[]',
    close_time          TIMESTAMPTZ,
    resolution_status   VARCHAR(20) NOT NULL DEFAULT 'open',
    resolved_answer     TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_prediction_markets_market_id UNIQUE (market_id)
);
CREATE INDEX ix_pm_status_updated ON prediction_markets (resolution_status, updated_at DESC);

-- PRD-0019: One price snapshot per (market_id, timestamp) — TimescaleDB hypertable
CREATE TABLE prediction_market_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id       TEXT NOT NULL,
    snapshot_at     TIMESTAMPTZ NOT NULL,
    outcomes_prices JSONB NOT NULL DEFAULT '{}',
    volume_24h      NUMERIC(20, 4),
    liquidity       NUMERIC(20, 4),
    source_event_id TEXT NOT NULL,
    CONSTRAINT uq_pms_market_snapshot UNIQUE (market_id, snapshot_at)
);
CREATE INDEX ix_pms_market_time ON prediction_market_snapshots (market_id, snapshot_at DESC);
SELECT create_hypertable('prediction_market_snapshots', 'snapshot_at', if_not_exists => TRUE);

-- PLAN-0056 A1 (PRD-0033 §6.1): prediction deeper streams (models + schema this wave;
-- adapters/consumers/read-routes land in Waves A2–A4). ``event_id`` links a market to
-- its Polymarket event group (backfilled by the event consumer in A3).
ALTER TABLE prediction_markets ADD COLUMN event_id TEXT;

-- Per-token interval price history — TimescaleDB hypertable on window_start_ts.
-- interval is VARCHAR not a PG enum (BP-007) so new interval tokens need no DDL.
CREATE TABLE prediction_market_prices (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    market_id       TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    outcome_name    TEXT,
    interval        VARCHAR(4) NOT NULL,
    window_start_ts TIMESTAMPTZ NOT NULL,
    price           NUMERIC(12, 6) NOT NULL,
    source          TEXT NOT NULL DEFAULT 'polymarket_clob',
    is_backfill     BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (id, window_start_ts)
);
CREATE UNIQUE INDEX uq_pmp_market_token_interval_window
    ON prediction_market_prices (market_id, token_id, interval, window_start_ts);
CREATE INDEX ix_pmp_market_window ON prediction_market_prices (market_id, window_start_ts DESC);
SELECT create_hypertable('prediction_market_prices', 'window_start_ts',
    migrate_data => true, chunk_time_interval => INTERVAL '1 month');

-- Individual trades/fills — TimescaleDB hypertable on ts. side is VARCHAR (BP-007).
CREATE TABLE prediction_market_trades (
    id         UUID NOT NULL DEFAULT gen_random_uuid(),
    market_id  TEXT NOT NULL,
    trade_id   TEXT NOT NULL,
    token_id   TEXT NOT NULL,
    price      NUMERIC(12, 6) NOT NULL,
    size_usd   NUMERIC(20, 4),
    side       VARCHAR(8) NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (id, ts)
);
-- ts is included because TimescaleDB requires every UNIQUE index on a hypertable
-- to contain the partition column; a trade's ts is immutable so dedup is unchanged.
CREATE UNIQUE INDEX uq_pmt_market_trade ON prediction_market_trades (market_id, trade_id, ts);
CREATE INDEX ix_pmt_market_ts ON prediction_market_trades (market_id, ts DESC);
SELECT create_hypertable('prediction_market_trades', 'ts',
    migrate_data => true, chunk_time_interval => INTERVAL '1 month');

-- Daily open-interest / 24h-volume roll-up — NOT a hypertable (one row per market/day).
CREATE TABLE prediction_market_oi (
    id                   UUID NOT NULL DEFAULT gen_random_uuid(),
    market_id            TEXT NOT NULL,
    snapshot_date        DATE NOT NULL,
    total_oi_usd         NUMERIC(20, 4),
    total_volume_24h_usd NUMERIC(20, 4),
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (market_id, snapshot_date)
);

-- Polymarket "event" groups (a set of related markets) — NOT a hypertable.
CREATE TABLE prediction_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id     TEXT NOT NULL,
    name         TEXT NOT NULL,
    category     VARCHAR(50),
    start_date   TIMESTAMPTZ,
    end_date     TIMESTAMPTZ,
    market_count INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_prediction_events_event_id UNIQUE (event_id)
);

-- QA fix (migration 044, 2026-07-10): partial index supporting event_id lookups
-- (the event consumer + entity-predictions API join/filter markets by event).
CREATE INDEX ix_prediction_markets_event_id
    ON prediction_markets (event_id) WHERE event_id IS NOT NULL;

-- QA fix (migration 044): 180-day retention on the two prediction hypertables
-- (trades is unbounded; prices grows per token/interval). Registered only when
-- the timescaledb extension is present (guarded DO block) so a plain-Postgres DB
-- is a no-op; add_retention_policy(..., if_not_exists => true) is idempotent.
SELECT add_retention_policy('prediction_market_trades', INTERVAL '180 days');
SELECT add_retention_policy('prediction_market_prices',  INTERVAL '180 days');
```

### PLAN-0056 A2 — deeper-stream repositories, ports & UoW wiring (no DDL)

Wave A2 adds the persistence layer for the A1 tables (consumers/API/use cases land in A3/A4):

- **Domain entities** (frozen dataclasses in `domain/entities.py`): `PredictionMarketPrice`, `PredictionMarketTrade` (both validate their partition timestamp is UTC-aware in `__post_init__`), `PredictionMarketOI`, `PredictionEvent` (surrogate `id` generated server-side, so not carried on the entity).
- **Ports** (ABCs in `application/ports/repositories.py`, R25 — no use case imports the Pg classes):
  - `PredictionMarketPricesRepository` — `insert_if_not_exists(price) -> bool`, `bulk_insert(prices) -> int`, `list_prices(market_id, token_id, interval, from_dt, to_dt, limit)`
  - `PredictionMarketTradesRepository` — `insert_if_not_exists(trade) -> bool`, `bulk_insert(trades) -> int`, `list_trades(market_id, since, limit)`
  - `PredictionMarketOIRepository` — `upsert(oi)`, `list_oi(market_id, from_date, to_date, limit)`, `get_latest(market_id)`
  - `PredictionMarketEventsRepository` — `upsert(event)`, `find_by_event_id(event_id)`, `list_events(limit, offset) -> (list, total)`
- **Pg implementations** (`infrastructure/db/repositories/prediction_market_repo.py`) mirror `PgPredictionMarketSnapshotRepository`: `ON CONFLICT DO NOTHING` on each UNIQUE index for prices/trades (idempotent inserts, BP-034/035); `bulk_insert` is a single multi-row insert returning the count of rows actually inserted (`RETURNING` + `len(fetchall())`); OI and events use `ON CONFLICT DO UPDATE` (last-write-wins, `updated_at = now()`); `list_*` order DESC on the time key with optional bound-parameter filters.
- **UoW** (R27): `UnitOfWork` gains write accessors `prediction_market_prices` / `prediction_market_trades` / `prediction_market_oi` / `prediction_events` (lazy-init, cached, write session) and read accessors `*_read` (read/replica session); `ReadOnlyUnitOfWork` gains the same `*_read` accessors — wired exactly like the existing snapshot repo.

---

## Runtime Processes (13)

| Process | Purpose |
|---------|---------|
| API Server | Serve query APIs (OHLCV, quotes, fundamentals, instruments, sectors, movers, price snapshots) |
| OHLCV Consumer | Materialize OHLCV bars from claim-check events; emit `InstrumentDiscovered` on first-seen symbols |
| Quotes Consumer | Materialize latest quotes; emit `InstrumentDiscovered` on first-seen symbols |
| Fundamentals Consumer | Materialize all 18 fundamentals sections + derived snapshot; emit `InstrumentCreated` v3 |
| Intraday Resampling Consumer | Consume 1m bars and derive 5m/15m/30m/1h/4h/1d derived bars (`IntradayResamplingWorker`) |
| Outbox Dispatcher | Publish instrument lifecycle events (`InstrumentCreated`, `InstrumentUpdated`, `InstrumentDiscovered`) + `market.prediction.move.v1` |
| Prediction Move Detector | Periodic worker (`infrastructure/workers/prediction_move_detector_main.py`, docker-compose `market-data-prediction-move-detector`) — scans open markets' snapshots, emits `market.prediction.move.v1` on gated material moves (PLAN-0056 D1) |
| Prediction Market Consumer | Materialize `market.prediction.v1` events into `prediction_markets` + `prediction_market_snapshots` |
| Prediction History Consumer | Materialize `market.prediction.history.v1` per-token interval bars into `prediction_market_prices` (PLAN-0056 A3) |
| Prediction Event Consumer | Upsert `market.prediction.event.v1` groups into `prediction_events` (group_id→event_id; market linkage set S4-side later) (PLAN-0056 A3) |
| Prediction Trade Consumer | Materialize `market.prediction.trade.v1` fills into `prediction_market_trades` (PLAN-0056 A3) |
| Prediction OI Consumer | Upsert `market.prediction.oi.v1` daily roll-ups into `prediction_market_oi` (PLAN-0056 A3) |
| Insider Transactions Consumer | Materialize per-transaction insider feed (`dataset_type == "insider_transactions"`) into `insider_transactions` — feeds the 6-hourly `insider_net_buy_90d` rollup. Existed in code since PLAN-0089 L-4b but only added to docker-compose on 2026-06-11 (backend-gaps wave 3) — the table was empty until then |

---

## Core Workflows

### Claim-Check Materialization

```mermaid
sequenceDiagram
    participant KFK as Kafka
    participant CON as OHLCV Consumer
    participant MIO as MinIO
    participant DB as market_data_db

    KFK->>CON: market.dataset.fetched (pointer event)
    CON->>CON: check ingestion_events (idempotency)
    CON->>MIO: GET canonical data (Parquet/JSONL)
    CON->>CON: parse via libs/contracts
    loop each bar
        CON->>DB: UPSERT ohlcv_bars (ON CONFLICT UPDATE)
    end
    CON->>DB: UPSERT instrument (set has_ohlcv=true)
    opt new instrument
        CON->>DB: INSERT outbox_event (InstrumentCreated)
    end
    CON->>DB: INSERT ingestion_events (mark processed)
```

### Fundamentals Data Flow (with read-optimized projection)

```mermaid
flowchart LR
    subgraph Ingestion
        KFK[Kafka] --> FC[FundamentalsConsumer]
        FC --> MIO[MinIO download]
    end

    subgraph Write Path
        MIO --> SEC["Section Tables<br/>(18 tables, source of truth)"]
        MIO --> FM["fundamental_metrics<br/>(read-optimized projection)"]
    end

    subgraph Read Path - Section APIs
        SEC --> API1["GET /fundamentals/{id}<br/>GET /fundamentals/{id}/income-statement<br/>etc."]
    end

    subgraph Read Path - Metrics APIs
        FM --> API2["GET /fundamentals/timeseries<br/>POST /fundamentals/screen<br/>GET /fundamentals/metrics/{id}"]
    end

    style FM fill:#e1f5fe
    style API2 fill:#e1f5fe
```

Both section table and `fundamental_metrics` upserts happen in the **same transaction**.
The metrics API endpoints use the **read session** (replica when configured).

---

## Caching Strategy

Quote data is cached in Valkey using a **cache-aside** pattern implemented in
`src/market_data/infrastructure/cache/quote_cache.py`.

| Key pattern | TTL | Populated by | Invalidated by |
|-------------|-----|-------------|---------------|
| `quote:v1:{instrument_id}` | 5 s | Quote read API on cache miss | `QuotesConsumer.process_message` after DB upsert |

The `QuoteCache` class silently degrades on Valkey connection errors — all cache
failures are logged at `WARNING` level and the request falls through to the DB.

OHLCV bars and instrument metadata are **not cached** at the application layer;
TimescaleDB chunk exclusion and the DB connection pool handle read performance.

---

## Application Layer (wave-03)

### Kafka Consumers

| Consumer class | Consumer group | Input topic | Dataset filter |
|---|---|---|---|
| `OHLCVConsumer` | `market-data-ohlcv` | `market.dataset.fetched` | `dataset_type == "OHLCV"` |
| `QuotesConsumer` | `market-data-quotes` | `market.dataset.fetched` | `dataset_type == "QUOTE"` |
| `FundamentalsConsumer` | `market-data-fundamentals` | `market.dataset.fetched` | `dataset_type == "FUNDAMENTALS"` |

All consumers extend `BaseKafkaConsumer[dict]` from `libs/messaging`. They:
1. Implement idempotency via `ingestion_events` table — atomic `create_if_not_exists()` (INSERT … ON CONFLICT DO NOTHING … RETURNING) records the event_id before any processing begins (BP-035). Content-hash dedup skips download when the canonical object is unchanged but still records the event_id.
2. Fetch the canonical object from MinIO using `canonical_ref_bucket` + `canonical_ref_key`.
3. Parse records using inline `json.loads()` + `CanonicalXxxBar.from_dict()`.
4. Upsert records using the UoW's repository (with provider-priority logic for OHLCV).
5. Upsert the instrument record and update `has_ohlcv / has_quotes / has_fundamentals` flag.
6. Emit `InstrumentCreated` or `InstrumentUpdated` domain events to the outbox.

**FundamentalsConsumer snapshot UPSERT (PLAN-0050 QA iter-1 F-Q1-03)**: After processing all sections, `FundamentalsConsumer` calls `_upsert_fundamentals_snapshot()` which derives all 10 snapshot metrics from the section JSONB data already in `payload` and UPSERTs one row into `instrument_fundamentals_snapshot`. This makes the snapshot table eventually consistent with each fundamentals ingest cycle — no separate backfill run is needed for continuously-ingested instruments. The helper logic lives in `infrastructure/db/fundamentals_snapshot_writer.py`. The call is best-effort: any exception is logged as a warning and does not dead-letter the Kafka message.

**Snapshot UPSERT COALESCE policy (PLAN-0050 QA iter-2 F-Q2-03)**: The `ON CONFLICT DO UPDATE` clause in `_UPSERT_SQL` uses `COALESCE(EXCLUDED.col, instrument_fundamentals_snapshot.col)` for all 10 nullable metric columns (`eps_ttm`, `beta`, `avg_volume_30d`, `operating_cash_flow`, `capex`, `free_cash_flow`, `fcf_margin`, `interest_coverage`, `net_debt_to_ebitda`, `credit_rating`). This prevents a partial EODHD re-poll (e.g., missing cash-flow section) from silently overwriting previously-valid data with NULL. `updated_at` is always refreshed unconditionally via `now()` regardless of which sections were present. A poll that provides no new data for a column simply preserves the existing value.

**Quote NULL semantics (D-004)**: `Quote.bid`, `.ask`, `.last`, `.volume` are `Decimal | None` / `int | None`. `NULL` means "no data available"; `Decimal("0")` means "zero trading activity". `CanonicalQuote.from_dict()` and the quote repo both preserve `None` — no coercion to zero.

The UoW is accessed via `self._current_uow` which is set by the base class before
calling `process_message(event_dict)`.

### API Routers

| Module | Prefix | Tags |
|---|---|---|
| `api/routers/instruments.py` | `/api/v1` | `instruments` |
| `api/routers/market.py` | `/api/v1` | `market` |
| `api/routers/ohlcv.py` | `/api/v1` | `ohlcv` |
| `api/routers/quotes.py` | `/api/v1` | `quotes` |
| `api/routers/fundamental_metrics.py` | `/api/v1` | `fundamental-metrics` (registered **before** `fundamentals` to avoid path-param shadowing) |
| `api/routers/fundamentals.py` | `/api/v1` | `fundamentals` |
| `api/routers/securities.py` | `/api/v1` | `securities` |
| `api/routers/peers.py` | `/api/v1` | `peers` |
| `api/routers/quote_stats.py` | `/api/v1` | `quote-stats` |
| `api/routers/prediction_markets.py` | `/api/v1` | `prediction-markets` |
| `api/routers/price_snapshot.py` | `/internal/v1` | `price-snapshot` |
| `api/routers/internal_instruments.py` | `/internal/v1` | `internal-instruments` |
| `api/routers/internal_market_tape.py` | `/internal/v1` | `internal-market-tape` |
| `api/routers/internal_earnings_calendar.py` | `/internal/v1` | `internal-earnings-calendar` |

The `ohlcv` router validates `start_date < end_date` and returns HTTP 422 on
reversed ranges. The `quotes` router uses the cache-aside pattern described above.

### Application Startup (lifespan)

1. Build **write engine** (`build_write_engine`) from `MARKET_DATA_DATABASE_URL` and **read engine** (`build_read_engine`) from `MARKET_DATA_READ_REPLICA_URL` (falls back to write URL when unset). Both are wrapped in `async_sessionmaker` factories stored as `app.state.write_session_factory` and `app.state.read_session_factory`.
2. Connect to Valkey, create `QuoteCache`.
3. Build `S3ObjectStorage` from `StorageSettings` (degrades gracefully if misconfigured).
4. Start Prometheus metrics + optional OTel tracing middleware.
5. Start 4 periodic background loops via `asyncio.create_task`: `_screen_fields_refresh_loop` (6 h), `_computed_metrics_refresh_loop`, `insider_rollup_loop` (daily at `MARKET_DATA_INSIDER_ROLLUP_HOUR_UTC`), `_intelligence_rollup_loop` (daily at `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC`).

> **Note**: The Kafka **consumers** and the **outbox dispatcher** do NOT run inside
> the API lifespan. Each runs as its own standalone process via a dedicated
> `*_consumer_main.py` / `dispatcher_main.py` entry point (see Runtime Processes),
> wired as separate `command:` entries in docker-compose.

On shutdown: the periodic background loops are cancelled; both DB engines are disposed.

### Read vs Write Session Routing

All API read operations (`GET` routes) use the **read (replica) session** via
`uow.instruments_read`, `uow.securities_read`, `uow.ohlcv_read`, `uow.quotes_read`, and
`uow.get_read_session()`. The fundamentals timeseries and screening endpoints also use
`uow.get_read_session()`. Write operations (Kafka consumers, `upsert`, flag updates) use
the **write session** via `uow.instruments`, `uow.securities`, `uow.fundamental_metrics`, etc.

When `MARKET_DATA_READ_REPLICA_URL` is not set, both sessions point to the same engine
(write URL), so there is no behaviour change on a single-node deployment. When a read
replica is configured, `GET` traffic is automatically routed to it without any application
logic change.

### Environment Variables

All variables are prefixed with `MARKET_DATA_`.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MARKET_DATA_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db` | Yes | Primary (write) DB URL |
| `MARKET_DATA_READ_REPLICA_URL` | `None` | No | Optional read-replica URL. When `None`, reads use the write URL. |
| `MARKET_DATA_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Yes | Kafka broker address |
| `MARKET_DATA_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Yes | Confluent Schema Registry URL |
| `MARKET_DATA_STORAGE_ENDPOINT` | `http://localhost:7480` | Yes | MinIO / S3-compatible endpoint |
| `MARKET_DATA_STORAGE_ACCESS_KEY` | — | **Required** | MinIO access key (no default — startup fails without it) |
| `MARKET_DATA_STORAGE_SECRET_KEY` | — | **Required** | MinIO secret key (no default — startup fails without it) |
| `MARKET_DATA_VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey (Redis-compatible) cache URL for quotes |
| `MARKET_DATA_API_GATEWAY_URL` | `http://api-gateway:8000` | No | S9 URL for JWKS endpoint (internal JWT auth, PRD-0025) |
| `MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | No | Skip JWT signature verification. **Never true in production** (rejected when `APP_ENV=production`). |
| `MARKET_DATA_INTERNAL_JWT_JTI_CHECK_ENABLED` | `false` | No | Enable JTI replay detection. Set `true` in production with proper JWT rotation. |
| `MARKET_DATA_EODHD_API_KEY` | `""` | No | EODHD API key for `GET /instruments/on-demand-profile` fallback enrichment. |
| `MARKET_DATA_EODHD_BASE_URL` | `https://eodhd.com` | No | EODHD base URL (overridable for staging). |
| `MARKET_DATA_OHLCV_MAX_DAYS` | `365` | No | Maximum date range for OHLCV queries. Requests exceeding this receive HTTP 422. |
| `MARKET_DATA_INTRADAY_SOURCE_TF` | `1m` | No | Source timeframe for intraday resampling (`IntradayResamplingWorker`). Valid: `1m`, `5m`, `15m`, `1h`. |
| `MARKET_DATA_HOST` / `MARKET_DATA_PORT` / `MARKET_DATA_DEBUG` | `0.0.0.0` / `8003` / `false` | No | Uvicorn bind + debug flag |
| `MARKET_DATA_FUNDAMENTALS_TIMEOUT_S` | `90` | No | Per-message watchdog for `FundamentalsConsumer` (BP-617). `consumer_main` co-scales `session_timeout_ms`/`heartbeat_interval_ms`. |
| `MARKET_DATA_SCREEN_STATEMENT_TIMEOUT_MS` | `8000` | No | Screener statement-timeout ceiling (ms). `query_screen` issues `SET LOCAL statement_timeout` so a pathological plan is cancelled cleanly (`QueryCanceledError` → 504) instead of hanging. Raise under sustained host contention (NEW-6, 2026-07-06). The DISTINCT ON rewrite keeps the screen well under the default. |
| `MARKET_DATA_INSIDER_ROLLUP_HOUR_UTC` | `3` | No | UTC hour for the daily `insider_net_buy_90d` rollup loop. |
| `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC` | `4` | No | UTC hour for the daily intelligence-rollup sync loop. |
| `MARKET_DATA_DISPATCHER_POLL_INTERVAL_SECONDS` | `5.0` | No | Outbox dispatcher poll interval. |
| `MARKET_DATA_DISPATCHER_LEASE_SECONDS` | `30` | No | Outbox row lease duration. |
| `MARKET_DATA_DISPATCHER_BATCH_SIZE` | `100` | No | Outbox dispatch batch size. |
| `MARKET_DATA_DISPATCHER_MAX_ATTEMPTS` | `20` | No | Max outbox publish attempts before dead-letter. |
| `MARKET_DATA_PREDICTION_MOVE_DETECTOR_INTERVAL_SECONDS` | `900` | No | PLAN-0056 D1 — `PredictionMoveDetector` cycle cadence (seconds). |
| `MARKET_DATA_PREDICTION_MOVE_WINDOW_HOURS` | `24` | No | Lookback window (hours) over which Δ implied-probability is measured. |
| `MARKET_DATA_PREDICTION_MOVE_INTERVAL_LABEL` | `1d` | No | Free-form window label written to the event `interval` field (1h/1d/1w). |
| `MARKET_DATA_PREDICTION_MOVE_DELTA_THRESHOLD` | `0.15` | No | Δ gate: min absolute implied-probability swing (0-1) to emit a move. |
| `MARKET_DATA_PREDICTION_MOVE_MIN_LIQUIDITY_USD` | `5000` | No | Liquidity floor (USD, latest snapshot) — thin markets suppressed. |
| `MARKET_DATA_PREDICTION_MOVE_MIN_VOLUME_USD` | `1000` | No | 24h-volume floor (USD, latest snapshot) — untraded markets suppressed. |
| `MARKET_DATA_PREDICTION_MOVE_MARKET_PAGE_SIZE` | `200` | No | Per-cycle safety cap on open markets scanned per page. |
| `MARKET_DATA_PREDICTION_MOVE_SNAPSHOT_LIMIT` | `500` | No | Per-cycle safety cap on snapshots pulled per market. |
| `MARKET_DATA_KAFKA_*_CONSUMER_INSTANCE_ID` | `""` | No | Static group-instance IDs for the 6 consumers (ohlcv/quotes/fundamentals/insider_transactions/intraday_resampling/prediction_market) — enables Kafka static membership. |
| `MARKET_DATA_NLP_PIPELINE_URL` / `MARKET_DATA_CONTENT_STORE_URL` / `MARKET_DATA_KNOWLEDGE_GRAPH_URL` / `MARKET_DATA_ALERT_SERVICE_URL` / `MARKET_DATA_RAG_CHAT_URL` | service DNS defaults | No | Intelligence-rollup client targets (`application/ports/intelligence_clients.py`). |
| `MARKET_DATA_INTERNAL_JWT_PRIVATE_KEY` | `""` | No | RS256 private key for signing internal service-to-service JWTs (intelligence-rollup outbound calls). |
| `MARKET_DATA_LOG_LEVEL` | `INFO` | No | Log level |
| `MARKET_DATA_LOG_JSON` | `true` | No | Structured JSON logs |
| `MARKET_DATA_OTLP_ENDPOINT` | `""` | No | OpenTelemetry OTLP endpoint |

---

## How to Run Locally

```bash
# 1. Start platform infra (TimescaleDB, Kafka, MinIO, Valkey)
make dev  # from repo root

# 2. Set up the service
cd services/market-data
cp configs/dev.local.env.example .env
# Edit .env — set MARKET_DATA_STORAGE_ACCESS_KEY and _SECRET_KEY

# 3. Install dependencies
source ../../.venv312/bin/activate
pip install -e ".[dev]"

# 4. Run database migrations
make migrate   # → alembic upgrade head

# 5. Start the API server
make run       # API on port 8003

# 6. Verify health
curl http://localhost:8003/healthz     # → {"status": "ok"}
curl http://localhost:8003/readyz      # → {"status": "ready"}

# 7. Example: get available instruments
curl http://localhost:8003/api/v1/instruments?limit=10

# 8. Example: get OHLCV bars
curl "http://localhost:8003/api/v1/ohlcv/INSTRUMENT_UUID?timeframe=1d&start=2024-01-01&end=2024-12-31"
```

**Running background consumers** (in separate terminals after `make dev`):

```bash
# OHLCV consumer (group: market-data-ohlcv)
python -m market_data.infrastructure.messaging.consumers.ohlcv_consumer_main

# Quotes consumer (group: market-data-quotes)
python -m market_data.infrastructure.messaging.consumers.quotes_consumer_main

# Fundamentals consumer (group: market-data-fundamentals)
python -m market_data.infrastructure.messaging.consumers.fundamentals_consumer_main

# Outbox dispatcher (instrument lifecycle events + prediction-move events)
python -m market_data.infrastructure.messaging.outbox.dispatcher_main

# Prediction move detector (periodic worker — PLAN-0056 D1)
python -m market_data.infrastructure.workers.prediction_move_detector_main
```

---

## How to Run Tests

```bash
cd services/market-data

# Unit tests (fast, no Docker needed)
make test
# or:
python -m pytest tests/unit -v -m unit

# Integration tests (requires Docker — TimescaleDB, Kafka, MinIO, Valkey)
make test-integration
# or:
python -m pytest tests/integration/ -v -m integration

# Contract tests (Avro schema alignment)
python -m pytest tests/contract -v

# Live tests (real EODHD demo API)
python -m pytest tests/live/ -v

# Full suite
make test-all

# Lint and type checks
make lint
python -m mypy src/ --config-file mypy.ini
```

**Test categories:**

| Type | Marker | Description | Needs Docker? |
|------|--------|-------------|---------------|
| Unit | `unit` | Domain entities, use cases, routers with mocked deps | No |
| Integration — repositories | `integration slow` | Real TimescaleDB repository tests | Yes |
| Integration — outbox + UoW | `integration slow` | Transactional outbox and UoW tests | Yes |
| Integration — infra smoke | `integration slow` | Container connectivity smoke tests | Yes |
| Integration — contracts | `integration` | Avro schema ↔ Python model alignment | No |
| E2E — pipeline | `integration slow` | Full claim-check pipeline (Kafka → MinIO → DB) | Yes |
| Performance — benchmarks | `integration slow` | TimescaleDB query benchmarks | Yes |

---

## Domain Model

> **Status**: Wave-01 complete. All entities, enums, and value objects implemented in
> `services/market-data/src/market_data/domain/`.

### Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `Timeframe` | `1m 5m 15m 30m 1h 4h 1d 1w 1M` | OHLCV bar granularity |
| `DatasetType` | `OHLCV QUOTE FUNDAMENTALS` | Canonical dataset type stored in object storage |
| `Provider` | `polygon yahoo alpha_vantage macrotrends unknown` | Data provider; carries `.priority` property (higher = preferred) |
| `PeriodType` | `ANNUAL QUARTERLY` | Fundamentals reporting period |
| `FundamentalsSection` | 18 sections (see below) | Logical section of a fundamentals snapshot |

Provider priority order (descending): `POLYGON (100) > YAHOO (80) > ALPHA_VANTAGE (60) > MACROTRENDS (40) > UNKNOWN (0)`

`FundamentalsSection` values: `income_statement`, `balance_sheet`, `cash_flow`, `highlights`,
`valuation_ratios`, `technicals_snapshot`, `share_statistics`, `splits_dividends`, `analyst_consensus`,
`earnings_history`, `earnings_trend`, `earnings_annual_trend`, `dividend_history`, `outstanding_shares`,
`company_profile`, `institutional_holders`, `fund_holders`, `insider_transactions_snapshot`.

### Value Objects

| Class | Fields | Notes |
|-------|--------|-------|
| `InstrumentFlags` | `has_ohlcv: bool`, `has_quotes: bool`, `has_fundamentals: bool` | Frozen dataclass; all default `False` |
| `ProviderPriority` | `provider: str`, `priority: int` | Frozen dataclass; construct via `.for_provider(Provider)` |

### Entities

| Entity | Key Fields | Notes |
|--------|-----------|-------|
| `Security` | `id` (UUID), `figi`, `isin`, `name`, `sector`, `industry`, `country`, `currency` | Auto-generated UUID id |
| `Instrument` | `id` (UUID), `security_id`, `symbol`, `exchange`, `flags: InstrumentFlags`, `is_active` | Exchange-specific listing of a Security |
| `OHLCVBar` | `instrument_id`, `timeframe`, `bar_date`, `open/high/low/close` (Decimal), `volume`, `adjusted_close`, `provider_priority` | Price fields use `Decimal` to match `NUMERIC(18,6)` |
| `Quote` | `instrument_id`, `bid/ask/last` (Decimal), `volume`, `timestamp` | Last-write-wins; one row per instrument |
| `FundamentalsRecord` | `id` (UUID), `security_id`, `section: FundamentalsSection`, `period_end`, `period_type`, `data: dict` | One section per record |

### ER Relationships

```
Security (1) ──── (N) Instrument
                        │
               ┌────────┼────────┐
               │        │        │
           OHLCVBar   Quote  FundamentalsRecord
                               (section discriminator)
```

---

## Domain Events

> **Status**: Wave-01 complete. All events implemented in
> `services/market-data/src/market_data/domain/events.py`.

All events extend `DomainEvent` (frozen dataclass). `event_id` and `occurred_at`
are auto-populated at construction time.

### Envelope Fields (inherited by all events)

| Field | Type | Notes |
|-------|------|-------|
| `event_id` | `str` | Auto-generated UUID |
| `event_type` | `str` | Literal set by each subclass |
| `schema_version` | `int` | Set by each subclass |
| `occurred_at` | `str` | ISO-8601 UTC, auto-populated |
| `correlation_id` | `str / None` | Optional trace correlation |
| `causation_id` | `str / None` | Optional causal event ID |

### Event Types

| Class | `event_type` | `schema_version` | Payload Fields | Trigger |
|-------|-------------|-----------------|----------------|---------|
| `InstrumentCreated` | `market.instrument.created` | 3 | `instrument_id`, `security_id`, `symbol`, `exchange`, `name`, `description`, `isin`, `cusip`, `figi`, `lei`, `primary_ticker` | Fundamentals materialised — first time `has_fundamentals` flips True with a real EODHD `Name`. v3 adds the four EODHD identifier fields (PLAN-0057 Wave C-1). |
| `InstrumentUpdated` | `market.instrument.updated` | 1 | `instrument_id`, `symbol`, `exchange`, `has_ohlcv`, `has_quotes`, `has_fundamentals` | Capability flag transitions OTHER than first-fundamentals. |
| `InstrumentDiscovered` | `market.instrument.discovered.v1` | 1 | `instrument_id`, `symbol`, `exchange`, `entity_id` (= instrument_id) | OHLCV / Quotes saw a previously-unknown symbol; KG seeds a lightweight placeholder canonical from this event (PLAN-0057 Wave D-2). |

### Usage Example

```python
from market_data.domain.events import InstrumentCreated

event = InstrumentCreated(
    instrument_id=str(instrument.id),
    security_id=str(instrument.security_id),
    symbol=instrument.symbol,
    exchange=instrument.exchange,
    correlation_id=correlation_id,
)
# Write into outbox atomically with the domain state change
await uow.outbox.add(OutboxRecord(
    event_type=event.event_type,
    topic="market.instrument.created",
    payload=dataclasses.asdict(event),
))
```

---

## Domain Error Hierarchy

> **Status**: Wave-01 complete. All errors implemented in
> `services/market-data/src/market_data/domain/errors.py`.

```
Exception
└── MarketDataError
    ├── InstrumentNotFoundError
    ├── SecurityNotFoundError
    ├── DuplicateEventError
    ├── IngestionError
    ├── ParseError
    └── StaleDataError
```

| Error | When raised |
|-------|-------------|
| `MarketDataError` | Base; catch-all for all domain errors |
| `InstrumentNotFoundError` | Lookup for a non-existent instrument |
| `SecurityNotFoundError` | Lookup for a non-existent security |
| `DuplicateEventError` | `event_id` already in `ingestion_events` (idempotency guard) |
| `IngestionError` | Business-rule failure during ingestion (valid payload, invalid context) |
| `ParseError` | Payload cannot be deserialized — pure domain exception, no infrastructure dependency |
| `StaleDataError` | Incoming data has lower provider priority than stored record |

`ParseError` is a pure domain exception (R12). Consumer infrastructure code that needs
Kafka dead-lettering should catch `ParseError` and re-raise as `FatalError` from
`messaging.kafka.consumer.errors`. The existing consumers use `MalformedDataError` directly.

---

## Common Pitfalls

1. **Using `float` for price fields in domain entities** — domain entities use `Decimal`
   to match the `NUMERIC(18,6)` DB column type. The `float` decision in `contracts/` applies
   only to canonical transport models (Avro). Converting `Decimal → float` at the DB boundary
   causes silent precision loss.

2. **Raising `IngestionError` for parse failures** — use `ParseError` when data cannot be
   deserialized. `ParseError` is a pure domain exception; consumer infrastructure should
   catch it and re-raise as `FatalError` if immediate dead-lettering is needed.
   `IngestionError` is for business-rule violations where the payload is structurally valid.

3. **Not using the outbox for instrument lifecycle events** — `InstrumentCreated` and
   `InstrumentUpdated` must be written to `outbox_events` in the same DB transaction as
   the domain state change. Direct `producer.produce()` calls create a dual-write that
   silently drops events on crash.

4. **Ignoring provider priority in upsert** — always check `provider_priority` before
   overwriting an `OHLCVBar`. A lower-priority source arriving after a higher-priority
   source must not overwrite the stored record. Use `ON CONFLICT DO UPDATE WHERE
   EXCLUDED.provider_priority >= stored.provider_priority` in the repository.

5. **Using naive datetimes in entities** — all timestamp fields must be UTC-aware.
   The `DTZ` ruff rule enforces this. Use `datetime.now(tz=UTC)` from stdlib or
   `common.time.utc_now()`.

6. **Double-context-manager bug in API routes** — the `get_uow` FastAPI dependency already
   opens the UoW via `async with SqlAlchemyUnitOfWork(...) as uow: yield uow`. Calling
   `async with uow:` **again** inside a route handler invokes `__aenter__` a second time,
   creating an orphaned session that is never closed. All route handlers must use the yielded
   `uow` directly — never wrap it in a context manager.

7. **Confusing instrument UUID with security UUID in fundamentals routes** — the path
   parameter in `/api/v1/fundamentals/{instrument_id}` is the **instrument UUID**
   (`instruments.id`), not `securities.id`. Fundamentals are ingested and stored per
   instrument. Passing a `securities.id` will silently return no records. Use
   `uow.instruments.find_by_symbol_exchange()` to resolve to an instrument ID first.

---

## Database Schema (wave-02, MD-014)

> All tables live in the `market_data_db` database (TimescaleDB on PostgreSQL 16).
> Migrations are in `services/market-data/alembic/versions/`.

### Core tables

| Table | PK | Key columns | Notes |
|---|---|---|---|
| `securities` | `id UUID` | `figi VARCHAR(12) UNIQUE`, `isin`, `name`, `sector`, `industry`, `country`, `currency` | Server default `gen_random_uuid()` |
| `instruments` | `id UUID` | `security_id FK→securities`, `symbol`, `exchange`, `has_ohlcv BOOL`, `has_quotes BOOL`, `has_fundamentals BOOL`, `created_at`, `updated_at` | `UNIQUE(symbol, exchange)` |

### Market data tables

| Table | PK | Key columns | Notes |
|---|---|---|---|
| `ohlcv_bars` | `(instrument_id, timeframe, bar_date)` | `open`, `high`, `low`, `close`, `volume`, `adjusted_close` — all `NUMERIC(18,8)`, `source VARCHAR`, `provider_priority SMALLINT` | **TimescaleDB hypertable** on `bar_date`, 1-month chunks (see migration 002). Index: `ix_ohlcv_bars_instrument_bar_date(instrument_id, bar_date)` |
| `quotes` | `instrument_id UUID` | `bid`, `ask`, `last`, `volume` — `NUMERIC(18,8)`, `timestamp TIMESTAMPTZ`, `updated_at TIMESTAMPTZ` | Latest-quote-per-instrument (single row) |

### Fundamentals tables (18 tables: 14 period-based + 4 non-period-based)

Each table stores one period-specific snapshot of one fundamentals section:

**Period-based tables** (14, share common columns: `id`, `instrument_id FK`, `period_type`, `period_end_date`, `data JSONB`, `ingested_at`):

| Table | Notes |
|---|---|
| `income_statements` | Annual/quarterly P&L data |
| `balance_sheets` | Balance sheet snapshots |
| `cash_flow_statements` | Operating/investing/financing cash flows |
| `highlights` | Company highlights and metadata |
| `valuation_ratios` | PE, PB, EV/EBITDA, etc. |
| `technicals_snapshots` | RSI, moving averages, beta |
| `share_statistics` | Shares outstanding, float, short interest |
| `splits_dividends` | Split/dividend summary metrics |
| `analyst_consensus` | Buy/hold/sell ratings, price targets |
| `earnings_history` | Quarterly EPS actuals vs estimates |
| `earnings_trends` | EPS growth trends by horizon |
| `earnings_annual_trends` | Annual earnings trend data |
| `dividend_history` | Per-payment dividend records |
| `outstanding_shares` | Share count history |

**Non-period-based tables** (4, each with dedicated column schema + `data JSONB`):

| Table | Notes |
|---|---|
| `company_profiles` | Company profile data (ISIN, name, sector, industry, country, currency) |
| `institutional_holders` | Institutional investor holdings |
| `fund_holders` | Fund investor holdings |
| `insider_transactions_snapshot` | Insider trading activity snapshots |

### Read-optimized projection table

| Table | PK | Key columns | Notes |
|---|---|---|---|
| `fundamental_metrics` | `id UUID` | `instrument_id FK→instruments`, `as_of_date DATE`, `metric VARCHAR(64)`, `value_numeric NUMERIC(24,6)`, `value_text TEXT`, `period_type VARCHAR(20)`, `section VARCHAR(64)`, `ingested_at TIMESTAMPTZ` | Derived projection populated on write. UNIQUE on `(instrument_id, as_of_date, metric, period_type)`. Indexes: `(metric, as_of_date)` for screening, `(instrument_id, metric, as_of_date)` for timeseries, and `(metric, instrument_id, as_of_date DESC) INCLUDE (value_numeric)` (`ix_fundamental_metrics_metric_instr_date_val`, migration 038) backing the screener default-sort `DISTINCT ON` latest-per-instrument page selection. |
| `screen_field_metadata` | `field_name TEXT` | `label TEXT`, `field_type TEXT` (CHECK IN `'numeric','text','date'` — `'date'` added by migration 031), `unit TEXT`, `description TEXT`, `observed_min NUMERIC`, `observed_max NUMERIC`, `null_fraction NUMERIC` (CHECK 0–1), `last_computed_at TIMESTAMPTZ` | Metadata for screenable metric fields (PRD-0017 §6.4). ~50 rows; populated by Wave B-2 background job. Used as Valkey fallback for `GET /screen/fields`. |

**Metric catalog** (expanded set extracted from section JSONB data on write):

| Source section | EODHD key(s) | Metric name | Value column |
|---|---|---|---|
| `analyst_consensus` | `TargetPrice` | `target_price` | `value_numeric` |
| `analyst_consensus` | `Rating` | `analyst_rating` | `value_text` (numeric parse attempted) |
| `analyst_consensus` | `Buy`, `Hold`, `Sell`, `StrongBuy`, `StrongSell` | `analyst_buy`, `analyst_hold`, `analyst_sell`, `analyst_strong_buy`, `analyst_strong_sell` | `value_numeric` |
| `valuation_ratios` | `TrailingPE`, `PE` | `pe_ratio` | `value_numeric` |
| `valuation_ratios` | `PriceBookMRQ`, `PB` | `pb_ratio` | `value_numeric` |
| `valuation_ratios` | `EnterpriseValue` | `enterprise_value` | `value_numeric` |
| `valuation_ratios` | `ForwardPE`, `EnterpriseValueEbitda`, `EnterpriseValueRevenue`, `PriceSalesTTM` | `forward_pe`, `enterprise_value_ebitda`, `enterprise_value_revenue`, `price_sales_ttm` | `value_numeric` |
| `highlights` | `RevenueTTM`, `Revenue` | `revenue_ttm` | `value_numeric` |
| `highlights` | `EBITDA`, `EBITDAttm` | `ebitda_ttm` | `value_numeric` |
| `highlights` | `EarningsShare`, `EPS` | `eps_ttm` | `value_numeric` |
| `highlights` | `ReturnOnEquityTTM`, `ROE` | `roe_ttm` | `value_numeric` |
| `highlights` | `ReturnOnAssetsTTM`, `ROA` | `roa_ttm` | `value_numeric` |
| `highlights` | `BookValue`, `DilutedEpsTTM`, `DividendShare`, `DividendYield`, `EPSEstimate*`, `GrossProfitTTM`, `MarketCapitalization*`, `OperatingMarginTTM`, `PEGRatio`, `PERatio`, `ProfitMargin`, `Quarterly*GrowthYOY`, `RevenuePerShareTTM`, `WallStreetTargetPrice` | `book_value`, `diluted_eps_ttm`, `dividend_share`, `dividend_yield`, `eps_estimate_*`, `gross_profit_ttm`, `market_capitalization*`, `operating_margin_ttm`, `peg_ratio`, `pe_ratio`, `profit_margin`, `quarterly_*_growth_yoy`, `revenue_per_share_ttm`, `wall_street_target_price` | `value_numeric` |
| `income_statements` | `totalRevenue` | `revenue` | `value_numeric` |
| `income_statements` | `netIncome` | `net_income` | `value_numeric` |
| `income_statements` | `eps` | `eps` | `value_numeric` |
| `income_statements` | `costOfRevenue`, `grossProfit`, `operatingIncome`, `incomeBeforeTax`, `incomeTaxExpense`, `interestExpense`, `interestIncome`, `ebit`, `ebitda`, `totalOperatingExpenses`, `totalOtherIncomeExpenseNet`, `researchDevelopment`, `sellingGeneralAdministrative`, `sellingAndMarketingExpenses`, `netIncomeApplicableToCommonShares`, `netIncomeFromContinuingOps` | `cost_of_revenue`, `gross_profit`, `operating_income`, `income_before_tax`, `income_tax_expense`, `interest_expense`, `interest_income`, `ebit`, `ebitda`, `total_operating_expenses`, `total_other_income_expense_net`, `research_development`, `selling_general_administrative`, `selling_and_marketing_expenses`, `net_income_applicable_to_common_shares`, `net_income_from_continuing_ops` | `value_numeric` |
| `balance_sheets` | `totalAssets` | `total_assets` | `value_numeric` |
| `balance_sheets` | `totalStockholderEquity` | `total_equity` | `value_numeric` |
| `balance_sheets` | `longTermDebt` | `long_term_debt` | `value_numeric` |
| `balance_sheets` | `cash`, `cashAndEquivalents`, `cashAndShortTermInvestments`, `totalLiab`, `totalCurrentAssets`, `totalCurrentLiabilities`, `shortTermDebt`, `shortLongTermDebt`, `shortLongTermDebtTotal`, `accountsPayable`, `netReceivables`, `inventory`, `retainedEarnings`, `propertyPlantAndEquipmentNet`, `commonStockSharesOutstanding`, `netDebt`, `netWorkingCapital` | `cash`, `cash_and_equivalents`, `cash_and_short_term_investments`, `total_liab`, `total_current_assets`, `total_current_liabilities`, `short_term_debt`, `short_long_term_debt`, `short_long_term_debt_total`, `accounts_payable`, `net_receivables`, `inventory`, `retained_earnings`, `property_plant_and_equipment_net`, `common_stock_shares_outstanding`, `net_debt`, `net_working_capital` | `value_numeric` |
| `cash_flow_statements` | `operatingCashFlow`, `totalCashFromOperatingActivities` | `operating_cash_flow` | `value_numeric` |
| `cash_flow_statements` | `capitalExpenditures`, `freeCashFlow`, `totalCashFromFinancingActivities`, `totalCashflowsFromInvestingActivities`, `dividendsPaid`, `netBorrowings`, `depreciation` | `capital_expenditures`, `free_cash_flow`, `total_cash_from_financing_activities`, `total_cashflows_from_investing_activities`, `dividends_paid`, `net_borrowings`, `depreciation` | `value_numeric` |

**Deterministic `as_of_date` rule**: always derived from `record.period_end.date()` for `ANNUAL`, `QUARTERLY`, and `SNAPSHOT` (never from `ingested_at`). This ensures replay and backfill produce identical `(instrument_id, as_of_date, metric, period_type)` keys.

**Consistency model**: Upserted in the same transaction as section writes (transactionally consistent for processed records). Snapshot sections use last-write-wins at date-level granularity. If `upsert_metrics` raises after a section write, the exception propagates to the caller's transaction manager for rollback.

**Screening semantics**: `POST /fundamentals/screen` uses the **latest** `as_of_date` per instrument for each metric filter. All filters combine with AND logic. Each filter may optionally specify a `sector` (matched against `instruments.sector`); specifying sector on any filter restricts results to that sector.

**Authoritative screener metric names** (PLAN-0051 Wave B, T-B-2-01 — frontend MUST use these names verbatim in `POST /fundamentals/screen` requests):

| UI category | UI label | Metric name (use exactly) | Unit | Source section |
|---|---|---|---|---|
| Valuation | P/E (TTM) | `pe_ratio` | ratio | `valuation_ratios` / `highlights` |
| Valuation | P/B | `pb_ratio` | ratio | `valuation_ratios` |
| Valuation | P/S (TTM) | `price_sales_ttm` | ratio | `valuation_ratios` |
| Valuation | Forward P/E | `forward_pe` | ratio | `valuation_ratios` |
| Valuation | EV / EBITDA | `enterprise_value_ebitda` | ratio | `valuation_ratios` |
| Valuation | Dividend yield | `dividend_yield` | decimal (0.015 = 1.5%) | `highlights` |
| Profitability | ROE (TTM) | `roe_ttm` | decimal | `highlights` |
| Profitability | ROA (TTM) | `roa_ttm` | decimal | `highlights` |
| Profitability | Operating margin (TTM) | `operating_margin_ttm` | decimal | `highlights` |
| Profitability | Net (profit) margin | `profit_margin` | decimal | `highlights` |
| Growth | Quarterly revenue growth YoY | `quarterly_revenue_growth_yoy` | decimal | `highlights` |
| Growth | Quarterly earnings growth YoY | `quarterly_earnings_growth_yoy` | decimal | `highlights` |
| Cap | Market capitalization | `market_capitalization` | USD | `highlights` |
| Risk | Beta | `beta` | ratio | `technicals_snapshot` |

**Documented gaps** (PLAN-0051 T-B-2-01) — frontend renders these inputs as `disabled` with a "Backend pending" badge; fix tracked in `docs/audits/2026-04-29-screener-metric-gap.md`:

- **Gross margin** — only `gross_profit_ttm` and `revenue_ttm` are extracted. The ratio is not stored. Future work: derive in `backfill_fundamental_metrics.py`.
- **Debt / Equity** — only `long_term_debt` and `total_equity` are stored. Ratio not stored.
- **Current ratio** — only `total_current_assets` and `total_current_liabilities` are stored. Ratio not stored.
- **Technical filters** (RSI, distance from 52W high/low, volume vs 30d avg, above 50d MA) — not in `fundamental_metrics`. Some live in `instrument_fundamentals_snapshot` (`avg_volume_30d`, `beta`); others (RSI, MA50, 52W range) require a new extractor or live computation from OHLCV. Frontend applies these as **client-side post-fetch filters** until a server endpoint exists.
- **News & signals filters** (news velocity 7d, controversy score, recent earnings, insider activity) — fields live in S6 / S7 (signals + knowledge graph); a composed S9 endpoint would be required. Frontend stubs them as client-side TODOs.

**Seed mismatch** (`_seed_fields()` in `app.py`): the 12 names seeded into `screen_field_metadata` (e.g. `revenue_usd`, `return_on_equity`, `dividend_yield_pct`, `market_cap_usd`) **do not match** the metric names actually populated by `metric_extractor.py`. Frontend ignores the seeded names and uses the extractor's truth column above. Fixing the seed is in the audit's remediation list.

**Timeseries date validation**: `start_date > end_date` returns HTTP 422 with a descriptive error before querying the DB.

**Unmapped key observability**: extractor logs structured `metric_extractor.unmapped_keys` events with `section`, `instrument_id`, `period_type`, `unmapped_keys_count`, and `unmapped_keys_sample`. Events with ≥20 unmapped keys log at `WARNING`; fewer log at `DEBUG`.

**Backfill command** (idempotent, chunked, resumable):

```bash
cd services/market-data
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db \
    python scripts/backfill_fundamental_metrics.py \
    --batch-size 500 \
    --continue-on-error \
    --json-summary

# Resume a single section from checkpoint
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db \
    python scripts/backfill_fundamental_metrics.py \
    --section valuation_ratios \
    --start-id 00000000-0000-0000-0000-000000000100 \
    --batch-size 500 \
    --continue-on-error \
    --json-summary
```

Backfill summary includes `scanned_rows`, `extracted_metric_rows`, `inserted_rows`, `updated_rows`, `skipped_rows`, `failed_rows`, and runtime.

### Infrastructure tables

| Table | PK | Key columns | Notes |
|---|---|---|---|
| `ingestion_events` | `id UUID` | `event_id UUID UNIQUE`, `event_type VARCHAR`, `occurred_at TIMESTAMPTZ` | Idempotency dedup; `event_id` is the upstream event ID, not the PK |
| `failed_tasks` | `id UUID` | `task_type VARCHAR`, `payload JSONB`, `attempts SMALLINT`, `max_attempts SMALLINT`, `next_attempt_at TIMESTAMPTZ`, `last_error TEXT`, `status VARCHAR`, `created_at TIMESTAMPTZ` | Retry queue for failed ingestion tasks |
| `outbox_events` | `id UUID` | `event_type VARCHAR`, `topic VARCHAR`, `payload JSONB`, `status VARCHAR DEFAULT 'PENDING'`, `claimed_by VARCHAR`, `claimed_at TIMESTAMPTZ`, `lease_expires_at TIMESTAMPTZ`, `attempts SMALLINT DEFAULT 0`, `dispatched_at TIMESTAMPTZ`, `created_at TIMESTAMPTZ` | Transactional outbox for `InstrumentCreated`/`InstrumentUpdated` |

**Legacy column mismatch fixes** (vs. the `platform_repo` source):
- `failed_tasks`: legacy had `event_id`, `event_type`, `error_message`, `attempt_count`, `next_retry_at`. New schema adds `task_type`, `payload JSONB`, `status`, renames counts.
- `outbox_events`: legacy had `leased_until`. New schema renames to `lease_expires_at`, adds `claimed_by`, `claimed_at`, `dispatched_at`.

---

## Migrations (wave-02 through wave-03+, MD-015+)

| Revision | Down-revision | Description |
|---|---|---|
| `001` | `None` | Initial schema — core tables (securities, instruments, ohlcv_bars, quotes) |
| `002` | `001` | Convert `ohlcv_bars` to TimescaleDB hypertable (`create_hypertable`, 1-month chunks) |
| `003` | `002` | Add 14 fundamentals tables (period-based: income_statement, balance_sheet, etc.) |
| `004` | `003` | Add infrastructure tables (ingestion_events, failed_tasks, outbox_events) with new column schema |
| `005` | `004` | Add 4 non-period fundamentals tables (company_profiles, highlights, institutional_holders, fund_holders, insider_transactions_snapshot); drop dividend_summary |
| `002` (consolidated) | `001` (consolidated) | Add `fundamental_metrics` read-optimized projection table with unique constraint and indexes |
| `003` (consolidated) | `002` (consolidated) | Add `lowercase_outbox_status` migration |
| `004` (consolidated) | `003` (consolidated) | Add `screen_field_metadata` table (PRD-0017 Wave B-1) |

> **Note**: Migrations 001–005 were consolidated into a single `001` initial schema.
> The `fundamental_metrics` migration is `002` relative to the consolidated `001`.

**Current head: `047`** (`alembic/versions/047_unique_placeholder_exchange_instruments.py`, down-revision
`046`). The linear chain `001 → … → 047` is the source of truth — the consolidated table above only
documents the early schema. Notable recent migrations:

| Revision | Description |
|---|---|
| `021` | `instruments.last_fundamentals_ingest_at` freshness column (BP-545) |
| `022`, `037` | `ANALYZE`/autovacuum tuning on fundamentals tables (paired with composite indexes, BP-581) |
| `023`, `038` | Composite/covering fundamentals indexes (incl. `ix_fundamental_metrics_metric_instr_date_val` for the screener default-sort dedup scan) |
| `024`/`025`/`029`/`035`/`041` | Seed L2/L4a/L3/L5b/volatility-30d screen fields (lock-step with `app.py::_get_static_screen_fields`) |
| `045` | Dedup duplicate non-intraday OHLCV bars to one UTC-midnight row per day |
| `046` | **NFLX-duplicate-instrument incident (BP-743, 2026-07)**: data-repair migration that merges any group of `instruments` rows sharing the same `upper(symbol)` into one winner (preferring non-empty `exchange`, then freshest `last_fundamentals_ingest_at`, then newest `created_at` — same ordering as the `find_by_symbol_icase` resolver fix), reassigning every FK-referencing child row (17 fundamentals section tables, `company_profiles`, `instrument_fundamentals_snapshot`, `fundamental_metrics`, `insider_transactions`, `earnings_calendar`, `ohlcv_bars`, `quotes`) to the winner before deleting the loser row(s). Irreversible; idempotent; safe to re-run. |
| `047` | Adds a partial unique index `uq_instruments_symbol_placeholder_exchange` on `upper(symbol) WHERE exchange = ''` — caps future placeholder-exchange row proliferation as defense-in-depth alongside the app-level dedup guard (see `_instrument_dedup.py`) |
| `028` | L5c earnings-calendar columns (`earnings_calendar` table) |
| `030`, `032` | `insider_transactions` per-row table (introduced, then schema replaced) |
| `031` | Extend `screen_field_metadata.field_type` CHECK to include `'date'` |
| `033` | `ix_ohlcv_bars_instr_bar_date_daily` |
| `036` | Merge duplicate crypto-USD instruments |
| `040` | `worker_runs` durable last-success tracking |

**Alembic env** (`alembic/env.py`) imports `market_data.infrastructure.db.models` (which registers all models in `Base.metadata`) before calling `autogenerate`.

Run cycle:
```bash
cd services/market-data
alembic upgrade head   # apply all migrations
alembic downgrade base # drop all tables (dev only — data loss)
alembic upgrade head   # re-apply
```

See `docs/architecture/decisions/0006-timescaledb-hypertable-vs-list-partitioning.md` for the rationale for hypertable over LIST partitioning.

---

## Data Access Layer (wave-02, MD-016 + MD-017 + MD-018)

### Repository ABCs

All repository interfaces are in `src/market_data/application/ports/repositories.py`.

| ABC | Key methods |
|---|---|
| `SecurityRepository` | `find_by_figi`, `find_by_isin`, `list(limit, offset) → (list, total)`, `upsert` |
| `InstrumentRepository` | `find_by_symbol_exchange`, `find_by_id`, `find_by_symbol_icase` (deterministic: non-empty `exchange` first, then freshest `last_fundamentals_ingest_at`, then newest `created_at` — see BP-743 / migration 046), `search(query, *, has_ohlcv, has_quotes, has_fundamentals, exchange, limit, offset)` — DB-side filters + pagination, `count(query, *, …)` — matching total, `upsert`, `update_flags`, `update_metadata` |
| `OHLCVRepository` | `bulk_upsert_with_priority` (provider-priority conflict resolution), `find_by_instrument_timeframe_range`, `get_available_timeframes`, `get_date_range` |
| `QuoteRepository` | `upsert`, `find_by_instrument`, `find_by_instruments` |
| `FundamentalsRepository` | `merge_upsert` (dispatches to per-section upsert by `FundamentalsSection`) |
| `IngestionEventRepository` | `exists` (idempotency dedup), `create` |
| `FailedTaskRepository` | `create`, `find_retryable`, `increment_attempts`, `mark_dead` |
| `OutboxEventRepository` | `create`, `find_pending`, `claim` (atomic lease), `mark_dispatched`, `release_stale` |

PostgreSQL adapters live in `src/market_data/infrastructure/db/repositories/`.

**Provider-priority upsert** (OHLCV):
```sql
INSERT INTO ohlcv_bars (...) VALUES (...)
ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE
SET open = EXCLUDED.open, ...
WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority
```
Lower-priority providers never overwrite higher-priority stored records.

### Unit of Work

`SqlAlchemyUnitOfWork` in `src/market_data/infrastructure/db/uow.py`:

```
┌─────────────────────────────────────────────────────────────┐
│                   SqlAlchemyUnitOfWork                       │
│                                                             │
│  write_session ──► PgXxxRepository (mutations)             │
│  read_session  ──► PgXxxRepository (queries — optional RR) │
│                                                             │
│  collected_events: list[DomainEvent]                        │
│  outbox_notifier: Callable | None  ──► dispatch on commit  │
└─────────────────────────────────────────────────────────────┘
```

- Write and read sessions can point to different engines (primary + read replica).
- `commit()` flushes collected domain events to the outbox notifier.
- `__aexit__` rolls back and closes both sessions on exception.

Session factories: `build_write_engine`, `build_read_engine`, `build_session_factory` in `src/market_data/infrastructure/db/session.py`.

### TimescaleDB Query Utilities (MD-018)

`src/market_data/infrastructure/db/queries/ohlcv_queries.py`:

| Function | Description |
|---|---|
| `get_bars_by_range(session, instrument_id, timeframe, start, end)` | Range scan with chunk pruning; `ORDER BY bar_date ASC` |
| `get_latest_bar(session, instrument_id, timeframe)` | `ORDER BY bar_date DESC LIMIT 1` |
| `get_bar_count(session, instrument_id, timeframe)` | `SELECT count(*)` |
| `get_available_date_range(session, instrument_id, timeframe)` | `MIN/MAX(bar_date)` → `(date, date) | None` |
| `downsample_to_timeframe(session, instrument_id, source_tf, target_tf, start, end)` | `time_bucket(:interval, bar_date)` with `MAX(high)`, `MIN(low)`, `SUM(volume)`, first/last open/close |

All functions use parameterized bind parameters — no f-strings or string interpolation with user values. The `time_bucket` interval is looked up from a static `_TIMEFRAME_INTERVAL` dict (never from user input).

---

## Outbox Dispatcher (wave-02, MD-027)

### Topic routing

| Event type | Kafka topic |
|---|---|
| `market.instrument.created` | `market.instrument.created` |
| `market.instrument.updated` | `market.instrument.updated` |
| `market.instrument.discovered` | `market.instrument.discovered.v1` |

> **QA-016 fix**: each event type publishes to its own dedicated topic. Both
> instrument events were previously routed to a single `market.events.v1` topic,
> which meant Portfolio (S1) never received instrument sync events. The
> `market.instrument.discovered` event (PLAN-0057 Wave D-2) is emitted by the
> OHLCV/quotes consumers. See `infrastructure/messaging/outbox/dispatcher.py`
> (`EVENT_TOPIC_MAP`).

### Avro schemas

| Event type | Schema file |
|---|---|
| `market.instrument.created` | `src/market_data/infrastructure/messaging/schemas/instrument.created.v1.avsc` |
| `market.instrument.updated` | `src/market_data/infrastructure/messaging/schemas/instrument.updated.v1.avsc` |
| `market.instrument.discovered` | `infra/kafka/schemas/market.instrument.discovered.v1.avsc` (registry-managed) |

Schema namespace: `market_data.events`.

### Decimal/UUID serialization

`MarketDataOutboxDispatcher._sanitize_payload()` recursively converts:
- `decimal.Decimal` → `str`
- `uuid.UUID` → `str`

before passing the payload to the Confluent AvroSerializer. This prevents `TypeError` on non-primitive Python types that Avro's JSON-based encoding cannot handle.

### Wiring

`MarketDataOutboxDispatcher` is instantiated in `src/market_data/app.py` `lifespan`:
- `await dispatcher.start()` on startup (warms up producer connection)
- `dispatcher.stop()` on shutdown (signals the poll loop to stop)

Full UoW wiring (connecting the outbox notifier to the dispatcher) will be done in a later wave when application service handlers are implemented.

---

## Integration Testing (wave-02, MD-028)

### Container fixtures

| Fixture | Scope | Image | Purpose |
|---|---|---|---|
| `pg_container` | session | `timescale/timescaledb:latest-pg16` | TimescaleDB for repository + migration tests |
| `kafka_container` | session | `confluentinc/cp-kafka:7.6.1` | Kafka producer/consumer tests |
| `minio_container` | session | `minio/minio:latest` | Object storage tests |
| `valkey_container` | session | `valkey/valkey:7` | Cache client tests |
| `db_session` | function | — | `AsyncSession` backed by `pg_container`; truncates all tables after each test |
| `uow` | function | — | `SqlAlchemyUnitOfWork` backed by `db_session` |
| `object_storage` | function | — | MinIO client |
| `valkey_client` | function | — | `valkey.asyncio` client |

### Running integration tests

```bash
# Requires Docker
cd services/market-data

# All integration tests
make test -- tests/integration/ -m integration -v

# Only smoke tests
make test -- tests/integration/test_infra_smoke.py -v

# Unit tests only (no Docker required)
make test -- tests/unit/ -v
```

### Pytest markers

| Marker | Meaning |
|---|---|
| `unit` | Fast isolated unit tests — no Docker required |
| `integration` | Requires external containers (DB, Kafka, MinIO, Valkey) |
| `slow` | Long-running tests excluded from CI fast path |

### Sample data files

| File | Contents |
|---|---|
| `tests/integration/fixtures/sample_ohlcv.jsonl` | 5 valid daily OHLCV bars for `test-inst-001` |
| `tests/integration/fixtures/sample_quotes.json` | 1 valid quote |
| `tests/integration/fixtures/sample_fundamentals.json` | Income statement, balance sheet, valuation ratios (3 of 14 sections) |

---

## External Dependencies

### EODHD (On-Demand Profile Enrichment Only)

Market Data uses EODHD **only** for the `GET /api/v1/instruments/on-demand-profile` fallback path when the instrument description is not yet in the database. The Market Ingestion service (S2) handles all scheduled EODHD data polling.

- **Variable**: `MARKET_DATA_EODHD_API_KEY` (default empty — feature disabled when empty)
- **Rate limit**: 429 is surfaced to the caller as HTTP 429

### MinIO (Object Storage)

Market Data reads canonical NDJSON objects from MinIO silver tier to materialize OHLCV, quotes, and fundamentals data. The service does not write to MinIO directly — that is Market Ingestion's job.

- **Variables**: `MARKET_DATA_STORAGE_ENDPOINT`, `MARKET_DATA_STORAGE_ACCESS_KEY`, `MARKET_DATA_STORAGE_SECRET_KEY`

---

## Runbook

**Service not returning data for an instrument:**
1. Check `GET /readyz` — 503 indicates DB/Valkey/MinIO connectivity issue.
2. Check `GET /api/v1/instruments?query=AAPL` — does the instrument exist? If not, Market Ingestion has not yet emitted an `InstrumentCreated` event.
3. Check `GET /api/v1/ohlcv/{id}/range` — does the instrument have any OHLCV data?
4. Check Kafka consumer lag for `market.dataset.fetched` topic (kafka-ui at port 8080).
5. Check `ingestion_events` table — are events being recorded (idempotency check passing)?

**OHLCV chart shows no data:**
- Check available timeframes: `GET /api/v1/ohlcv/{id}/timeframes`
- Check date range: `GET /api/v1/ohlcv/{id}/range`
- OHLCV max days limit: requests spanning >365 days return HTTP 422. Reduce the range.
- Intraday bars (5m/15m/30m/1h/4h) are derived from 1m bars by the `IntradayResamplingWorker`. If 1m bars are missing, derived timeframes will also be empty.

**Quotes returning stale data:**
- Quotes are cached in Valkey with a 5-second TTL.
- Check Valkey key `quote:v1:{instrument_id}` for the cached value.
- On cache miss, the API reads from the database — check the `quotes` table `updated_at` column.
- Quote data is only as fresh as the last poll by Market Ingestion (typically 5-minute cadence during market hours).

**Fundamentals screener returning no results:**
- The screener uses the `fundamental_metrics` read-optimized projection table.
- Check `GET /api/v1/fundamentals/metrics/{instrument_id}` — are metrics populated?
- The `FundamentalsConsumer` populates `fundamental_metrics` on each ingest cycle. If the instrument has never been ingested, the table will be empty.
- Run the backfill script to populate historical metrics: `python scripts/backfill_fundamental_metrics.py`

**Prediction market consumer not updating:**
- Check consumer group `market-data-prediction-markets` lag on topic `market.prediction.v1`.
- Events use Confluent Avro wire format (0x00 magic byte) — consumer detects and handles both Avro and JSON formats (BP-122 fix).
- `PredictionMarketSnapshot` requires `len(outcomes_prices) >= 2` — consumer pads to 2 entries to avoid crashes on malformed events.
