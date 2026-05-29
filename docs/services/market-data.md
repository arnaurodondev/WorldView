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

## API Surface (38 routes)

| Method | Path | Description | Cache Tier |
|--------|------|-------------|------------|
| GET | `/healthz` | Liveness probe — always 200 | — |
| GET | `/readyz` | Readiness (DB + Valkey + Storage + Kafka) | — |
| GET | `/metrics` | Prometheus metrics — requires `X-Internal-Token` header (M-004) | — |
| GET | `/api/v1/instruments` | List instruments — query params: `query`, `has_ohlcv`, `has_quotes`, `has_fundamentals`, `exchange`, `limit`, `offset` (all DB-side) | — |
| GET | `/api/v1/instruments/lookup` | Unified instrument lookup — query params: `symbol` (icase), `isin`, `id` (UUID), `extra_info` (bool, default false). Priority: id > isin > symbol. `extra_info=true` also returns `name`, `description`, `sector`, `industry`, `country`, `currency_code`. Requires `X-Internal-JWT`. | — |
| GET | `/api/v1/instruments/on-demand-profile` | On-demand instrument profile — query param: `ticker` or `isin`. DB-first (returns `source="db"` if description populated); falls back to EODHD, persists result (`source="eodhd_persisted"`). Raises 429 if EODHD rate-limited. Requires `X-Internal-JWT`. | — |
| GET | `/api/v1/ohlcv/bulk` | Bulk OHLCV for multiple instruments | — |
| GET | `/api/v1/ohlcv/{instrument_id}` | OHLCV bars (query: `timeframe`, `start`, `end`) | — |
| GET | `/api/v1/ohlcv/{instrument_id}/timeframes` | Available timeframes for instrument | — |
| GET | `/api/v1/ohlcv/{instrument_id}/range` | Date range of available OHLCV data | — |
| GET | `/api/v1/quotes/latest` | Batch quotes by query params (`?instrument_ids=…`) | Valkey 5 s |
| GET | `/api/v1/quotes/{instrument_id}` | Latest quote — cache-aside | Valkey 5 s |
| POST | `/api/v1/quotes/batch` | Batch quotes via POST body | Valkey 5 s |
| GET | `/api/v1/fundamentals/{instrument_id}` | Full fundamentals (all 18 sections) — `{instrument_id}` is instrument UUID | — |
| GET | `/api/v1/fundamentals/{instrument_id}/income-statement` | Income statement | — |
| GET | `/api/v1/fundamentals/{instrument_id}/balance-sheet` | Balance sheet | — |
| GET | `/api/v1/fundamentals/{instrument_id}/cash-flow` | Cash flow | — |
| GET | `/api/v1/fundamentals/{instrument_id}/highlights` | Highlights (TTM metrics) | — |
| GET | `/api/v1/fundamentals/{instrument_id}/valuation` | Valuation ratios | — |
| GET | `/api/v1/fundamentals/{instrument_id}/analyst-consensus` | Analyst estimates | — |
| GET | `/api/v1/fundamentals/{instrument_id}/dividends` | Dividend history | — |
| GET | `/api/v1/fundamentals/{instrument_id}/earnings` | Earnings history | — |
| GET | `/api/v1/fundamentals/{instrument_id}/company-profile` | Company profile snapshot | — |
| GET | `/api/v1/fundamentals/{instrument_id}/institutional-holders` | Institutional holders | — |
| GET | `/api/v1/fundamentals/{instrument_id}/fund-holders` | Fund holders | — |
| GET | `/api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot` | Insider transactions snapshot | — |
| GET | `/api/v1/fundamentals/{instrument_id}/snapshot` | Pre-computed derived metrics snapshot — returns one flat row from `instrument_fundamentals_snapshot` table (eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating, updated_at). Always 200 — all fields null for un-backfilled instruments. PLAN-0050 Wave D. | — |
| GET | `/api/v1/fundamentals/timeseries` | Metric timeseries — query params: `instrument_id`, `metric`, `start_date`, `end_date`, `period_type`, `limit`. Returns 422 if `start_date > end_date`. | — |
| POST | `/api/v1/fundamentals/screen` | Screen instruments by metric thresholds (AND logic) — JSON body: `filters[]` (each filter may include `metric`, `min_value`, `max_value`, `period_type`, `sector`), `limit` (default 50, max 200), `offset` (max 5000), `sort_by` (metric name, `ticker`, or `name`; validated whitelist — SQL injection guard), `sort_order` (`asc`/`desc`). Response includes `ticker`, `name`, `exchange`, `sector` fields + `total` (COUNT(*) OVER()). | — |
| POST | `/api/v1/fundamentals/batch` | **PLAN-0095 W2 T-W2-01** — batch quarterly fundamentals history for many tickers in one HTTP call. Body: `{tickers: list[str] (cap 25), periods: int = 5}`. **PLAN-0097 T-W3-02** split execution into two explicit `asyncio.gather` phases (resolve → fetch) so per-phase error classification is unambiguous; lookups run concurrently regardless of N. **PLAN-0097 T-W3-04** replaced raw `str(exc)` in `reason` with one of four typed codes — `invalid_ticker`, `upstream_timeout`, `upstream_404`, `upstream_error` — and routes full exception detail to structlog only (BP-582). Response: `{results: {ticker: {status: "ok"\|"error", periods?, reason?}}}`. Returns 422 if `len(tickers) > 25`. | — |
| GET | `/api/v1/fundamentals/metrics/{instrument_id}` | List available metric names for an instrument | — |
| GET | `/api/v1/securities` | List securities — query params: `figi`, `isin`, `limit`, `offset` (paginated DB scan when unfiltered) | — |
| GET | `/api/v1/securities/{security_id}` | Security detail by FIGI or ISIN | — |
| GET | `/api/v1/prediction-markets` | List prediction markets — query params: `status` (`open`/`resolved`/`cancelled`/`all`), `limit`, `offset` | — |
| GET | `/api/v1/prediction-markets/{market_id}` | Prediction market detail with latest snapshot | — |
| GET | `/api/v1/prediction-markets/{market_id}/history` | Prediction market price history — query params: `from_dt`, `to_dt` (HTTP 400 if `from_dt >= to_dt`) | — |
| GET | `/api/v1/market/sector-returns` | Sector heatmap data — query param: `period` (`1D`, `1W`, `1M`). Returns average period return per GICS sector from OHLCV bars. | — |
| GET | `/api/v1/market/period-movers` | Top gainers or losers — query params: `period` (`1W`/`1M`), `type` (`gainers`/`losers`), `limit` (1–50, default 10). Returns instruments sorted by period_return_pct. | — |
| GET | `/internal/v1/price/{instrument_id}` | Price snapshot for a single instrument — cache-aside: Valkey → Quote → OHLCV fallback. Returns 404 if no data available. **Internal endpoint — S9 only.** | Valkey |
| POST | `/internal/v1/price/batch` | Price snapshots for up to 50 instruments. Instruments with no data are silently omitted (partial results valid). **Internal endpoint — S9 only.** | Valkey |
| GET | `/internal/v1/instruments/top-by-market-cap` | Top-N active instruments sorted by latest market capitalisation (NULLs last). Query params: `n` (1-5000, default 500), `offset` (default 0). Response: `{total, offset, limit, results:[{id,symbol,exchange,market_cap_usd,currency_code}]}`. **Internal endpoint — consumed by market-ingestion's `FundamentalsRefreshWorker` (PLAN-0100 W5).** | — |

> **Note on path ordering**: Literal-segment routes (`/ohlcv/bulk`, `/quotes/latest`,
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

## Symbol Resolution (PLAN-0093 T-C-3-01, 2026-05-23)

Audit 2026-05-23 (F-NPL-FUNDAMENTALS-001) flagged that `PriceImpactLabellingWorker`
and `fundamentals_refresh` were hitting `market-data/api/v1/instruments/symbol/<TICKER>`
and getting 404 for every ticker (AAPL, MSFT, NVDA, ...) → `article_impact_windows`
stayed empty + `fundamentals_ohlcv` embeddings stayed NULL.

**Investigation outcome: (A) — the correct symbol-resolver endpoint already exists.**

| | |
|---|---|
| **Endpoint** | `GET /api/v1/instruments/lookup` |
| **Arg shape** | `?symbol={ticker}` (one of `symbol` / `isin` / `id` is required) |
| **Auth** | `X-Internal-JWT` required (workers mint one via `POST /internal/v1/service-token`) |
| **200 body** | `{"id": "<uuid>", "symbol": "...", "exchange": "...", "is_active": true}` (with `?extra_info=true`, additionally returns `name`, `isin`, `sector`, `industry`, `country`, `currency_code`, `description`) |
| **404** | `{"detail": "Instrument not found"}` — ticker has no row in `instruments` |
| **400** | When none of `symbol`/`isin`/`id` is supplied |
| **Source** | `services/market-data/src/market_data/api/routers/instruments.py` (function `lookup_instrument`) |
| **Use case** | `services/market-data/src/market_data/application/use_cases/lookup_instrument.py` (`InstrumentLookupUseCase.execute`) |

The legacy `GET /api/v1/instruments/symbol/{ticker}` and `GET /api/v1/instruments/{id}`
routes were **removed by PLAN-0073 B-1** and now return 404. The audit-cited 404 storm
was caused by the workers still pointing at the legacy paths. Both workers
(`nlp-pipeline.../market_data_client.py:_resolve_instrument_id` and
`knowledge-graph.../fundamentals_refresh.py`) were already migrated to
`/instruments/lookup?symbol=` before this audit but the workers' Valkey skip-set
was missing — see PLAN-0093 T-C-3-02 (7-day backoff on persistent 404s).

---

## Kafka Topics

### Consumed

| Topic | Consumer Group | Purpose | Idempotency |
|-------|---------------|---------|-------------|
| `market.dataset.fetched` | `market-data-ohlcv` | Materialize OHLCV bars | `event_id` in `ingestion_events` |
| `market.dataset.fetched` | `market-data-quotes` | Materialize quotes | `event_id` |
| `market.dataset.fetched` | `market-data-fundamentals` | Materialize fundamentals | `event_id` |
| `market.prediction.v1` | `market-data-prediction-markets` | Materialize prediction market snapshots (PRD-0019) | Atomic `create_if_not_exists` + `insert_if_not_exists` |

### Produced

| Topic | Event Type | Key |
|-------|-----------|-----|
| `market.instrument.created` | `InstrumentCreated` (v3) | `instrument_id` |
| `market.instrument.updated` | `InstrumentUpdated` | `instrument_id` |
| `market.instrument.discovered.v1` | `InstrumentDiscovered` | `instrument_id` |

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
    -- ── Wave L-4a snapshot fields (PLAN-0089, migration 025) ─────────────────
    -- analyst_consensus + share_statistics JSONB projection. Ownership and
    -- short stored as DECIMAL FRACTIONS (e.g. 0.743 = 74.3%, 0.034 = 3.4%) to
    -- match the fcf_margin convention. Consensus rating on a 1-5 scale where
    -- higher = more bullish (text labels Buy/Hold/Sell map to 4.0/3.0/2.0;
    -- numeric raw EODHD values pass through unchanged).
    analyst_target_price        NUMERIC(18, 4) NULL,
    analyst_consensus_rating    NUMERIC(4, 2)  NULL,
    institutional_ownership_pct NUMERIC(8, 6)  NULL,
    short_percent               NUMERIC(8, 6)  NULL,
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
```

---

## Runtime Processes (7)

| Process | Purpose |
|---------|---------|
| API Server | Serve query APIs (OHLCV, quotes, fundamentals, instruments, sectors, movers, price snapshots) |
| OHLCV Consumer | Materialize OHLCV bars from claim-check events; emit `InstrumentDiscovered` on first-seen symbols |
| Quotes Consumer | Materialize latest quotes; emit `InstrumentDiscovered` on first-seen symbols |
| Fundamentals Consumer | Materialize all 18 fundamentals sections + derived snapshot; emit `InstrumentCreated` v3 |
| Intraday Resampling Consumer | Consume 1m bars and derive 5m/15m/30m/1h/4h/1d derived bars (`IntradayResamplingWorker`) |
| Outbox Dispatcher | Publish instrument lifecycle events (`InstrumentCreated`, `InstrumentUpdated`, `InstrumentDiscovered`) |
| Prediction Market Consumer | Materialize `market.prediction.v1` events into `prediction_markets` + `prediction_market_snapshots` |

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

#### Period-type contract

Fundamentals section tables (`income_statements`, `balance_sheets`,
`cash_flow_statements`) store both QUARTERLY and ANNUAL rows under the same
section enum, distinguished by the `period_type` column. The repository
read helper `query_fundamentals` accepts an optional `period_type` filter:

- **`income_statement`** — the use case (`GetFundamentalsHistoryUseCase`)
  MUST pass `period_type=PeriodType.QUARTERLY` explicitly (PLAN-0095 T-W1-02).
  The repo deliberately does **not** apply a default here so that future
  callers needing ANNUAL rows are forced to be explicit.
- **`balance_sheet`** and **`cash_flow`** — the repo defaults to
  `PeriodType.QUARTERLY` when the caller passes `None` (PLAN-0096 T-W1-01,
  **BP-546**). This is a defensive default: there are no current direct
  callers for these sections, but any future caller would otherwise silently
  inherit the mixed-periodicity trap that BP-540 / BP-543 fixed for income
  statement. Pass `period_type=PeriodType.ANNUAL` explicitly to query annual
  rows.
- **`highlights`** — TTM-only by EODHD contract; intentionally **not**
  filtered by `period_type`. The `GetFundamentalsHistoryUseCase` only reads
  TTM-safe scalar fields (`PERatio`, `MarketCapitalization`) from this
  section, and every row in the use-case response carries an explicit
  `period_type="QUARTERLY"` label so downstream consumers (rag-chat tool
  layer, LLM grounding) can never quote a TTM number as a quarterly figure
  without seeing the mismatch. See PLAN-0097 T-W1-01 / **BP-577**.

##### Contract summary (PLAN-0097 W4 T-W4-05)

The cumulative period-type contract across PLAN-0095 / PLAN-0096 / PLAN-0097
is:

1. **Every fundamentals read MUST be deterministic with respect to
   periodicity.** Callers either pass `period_type` explicitly or rely on a
   repository default that is documented in the function docstring. A read
   path that silently mixes QUARTERLY and ANNUAL rows is a P0 data-integrity
   bug (BP-540, BP-543, BP-546).
2. **Repository defaults are defensive, not implicit.** The repo defaults
   `balance_sheet` and `cash_flow` to QUARTERLY because the EODHD pipeline
   ingests both periodicities into the same table and an unfiltered query
   would interleave them. New section tables MUST adopt the same
   defensive-default pattern unless they only ever store one periodicity.
3. **Every row leaving the use-case layer carries an explicit `period_type`
   field.** This is the second line of defense — even if a future bug
   reintroduces interleaving at the repo, the downstream consumer (rag-chat
   tool layer, frontend cards, LLM grounding payloads) sees the label and
   either filters or surfaces the mismatch.
4. **TTM-only sections (`highlights`, `valuation_ratios`) MUST label their
   rows as the dominant periodicity** so a TTM number is never quoted as a
   quarterly figure without the label disagreeing visibly. See PLAN-0097
   T-W1-01.
5. **Rule R20 — fundamentals queries MUST specify `period_type` explicitly
   or accept a documented repo default** is codified in `RULES.md`
   (R20-companion: PLAN-0097 W4 added the contract; the rule itself
   remains the union of R20 + the docs above). The repo unit tests in
   `services/market-data/tests/unit/test_query_fundamentals.py` enforce the
   default for every section.

#### Freshness tracking

Every successful `FundamentalsConsumer` cycle bumps
`instruments.last_fundamentals_ingest_at` inside the **same UoW** as the
section writes (PLAN-0096 T-W1-02, **BP-545**). The column is observational
only — no Kafka event, no outbox row. The bump is gated on at least one
section having been materialised (a zero-section payload does not lie about
freshness).

The repository method (`PgInstrumentRepository.touch_fundamentals_ingest_at`)
issues the UPDATE *and* immediately `flush()`-es the session (PLAN-0101,
**BP-610**). The flush is load-bearing: the same UoW also runs
`_upsert_fundamentals_snapshot` inside a try/except that swallows exceptions,
so a later snapshot-side failure would otherwise mask the touch UPDATE and
leave the column at its previous value (live observed 0/629 non-NULL rows
before the fix landed). Any future write that targets a tracking column in
this service MUST follow the same flush-inside-the-repo convention so callers
cannot forget.

Operators can identify stale tickers with a single index-friendly query:

```sql
SELECT symbol FROM instruments
 WHERE last_fundamentals_ingest_at < NOW() - INTERVAL '7 days'
    OR last_fundamentals_ingest_at IS NULL;
```

`NULL` means "never ingested" (e.g., the row was seeded by the
OHLCV/quotes consumer before fundamentals arrived) and should typically be
treated as "stale" by freshness alerts.

**No active refresh worker (BP-578)**: there is currently no scheduled
worker polling EODHD for new fundamentals — refresh is opportunistic and
depends on the market-ingestion scheduler / external triggers. Until a
proper `FundamentalsRefreshWorker` lands (deferred to PLAN-0098), use
`scripts/refresh_fundamentals.py` to fan out
`POST /api/v1/ingest/trigger` calls for a configurable ticker set:

```bash
MARKET_INGESTION_URL=http://localhost:8084 \
  python scripts/refresh_fundamentals.py --tickers AMD,NVDA
```

The script accepts `--dry-run`, custom ticker lists, and a `--provider`
override. See its module docstring for the full operational contract and
the 2026-05-27 audit
(`docs/audits/2026-05-27-plan-0097-data-integrity-investigation.md` Part B)
for the underlying freshness-gap analysis.

**Quote NULL semantics (D-004)**: `Quote.bid`, `.ask`, `.last`, `.volume` are `Decimal | None` / `int | None`. `NULL` means "no data available"; `Decimal("0")` means "zero trading activity". `CanonicalQuote.from_dict()` and the quote repo both preserve `None` — no coercion to zero.

The UoW is accessed via `self._current_uow` which is set by the base class before
calling `process_message(event_dict)`.

### API Routers

| Module | Prefix | Tags |
|---|---|---|
| `api/routers/instruments.py` | `/api/v1` | `instruments` |
| `api/routers/ohlcv.py` | `/api/v1` | `ohlcv` |
| `api/routers/quotes.py` | `/api/v1` | `quotes` |
| `api/routers/fundamentals.py` | `/api/v1` | `fundamentals` |
| `api/routers/fundamental_metrics.py` | `/api/v1` | `fundamental-metrics` |
| `api/routers/securities.py` | `/api/v1` | `securities` |

The `ohlcv` router validates `start_date < end_date` and returns HTTP 422 on
reversed ranges. The `quotes` router uses the cache-aside pattern described above.

### Application Startup (lifespan)

1. Build **write engine** (`build_write_engine`) from `MARKET_DATA_DATABASE_URL` and **read engine** (`build_read_engine`) from `MARKET_DATA_READ_REPLICA_URL` (falls back to write URL when unset). Both are wrapped in `async_sessionmaker` factories stored as `app.state.write_session_factory` and `app.state.read_session_factory`.
2. Connect to Valkey, create `QuoteCache`.
3. Build `S3ObjectStorage` from `StorageSettings` (degrades gracefully if misconfigured).
4. Start Prometheus metrics + optional OTel tracing middleware.
5. Start 3 consumer background tasks (`asyncio.create_task`).
6. Start the outbox dispatcher background task.

On shutdown: consumers and dispatcher are signalled to stop; each task is waited
with a 5-second timeout before cancellation; both DB engines are disposed.

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
# PLAN-0102 W6 / BP-617: per-message watchdog default is 90 s (was 45 s in
# the library default). Override with MARKET_DATA_FUNDAMENTALS_TIMEOUT_S if a
# different ceiling is required; session_timeout_ms + heartbeat_interval_ms
# scale automatically to preserve the watchdog-wins-over-coordinator
# invariant. Tail-latency observability: Prometheus histogram
# `fundamentals_consumer_processing_ms` with buckets
# [1s, 5s, 10s, 30s, 45s, 60s, 90s, 120s] — alert on any non-zero count in
# the 60 s bucket sustained for >15 min (next bump imminent).
python -m market_data.infrastructure.messaging.consumers.fundamentals_consumer_main

# Outbox dispatcher (instrument lifecycle events)
python -m market_data.infrastructure.messaging.outbox.dispatcher_main
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
| `InstrumentDiscovered` | `market.instrument.discovered.v1` | 1 | `instrument_id`, `symbol`, `exchange`, `entity_id` (≡ `instrument_id` per M-017 / [ADR-F-16](../architecture/decisions/ADR-F-16-instrument-entity-id-unification.md)) | OHLCV / Quotes saw a previously-unknown symbol; KG seeds a lightweight placeholder canonical from this event (PLAN-0057 Wave D-2). Post-F2: the KG consumer inserts `canonical_entities.entity_id = event.instrument_id` directly (no fresh UUID minted). |

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
| `fundamental_metrics` | `id UUID` | `instrument_id FK→instruments`, `as_of_date DATE`, `metric VARCHAR(64)`, `value_numeric NUMERIC(24,6)`, `value_text TEXT`, `period_type VARCHAR(20)`, `section VARCHAR(64)`, `ingested_at TIMESTAMPTZ` | Derived projection populated on write. UNIQUE on `(instrument_id, as_of_date, metric, period_type)`. Indexes: `(metric, as_of_date)` for screening, `(instrument_id, metric, as_of_date)` for timeseries. |
| `screen_field_metadata` | `field_name TEXT` | `label TEXT`, `field_type TEXT` (CHECK IN `'numeric','text'`), `unit TEXT`, `description TEXT`, `observed_min NUMERIC`, `observed_max NUMERIC`, `null_fraction NUMERIC` (CHECK 0–1), `last_computed_at TIMESTAMPTZ` | Metadata for screenable metric fields (PRD-0017 §6.4). ~50 rows; populated by Wave B-2 background job. Used as Valkey fallback for `GET /screen/fields`. |

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
| Performance | 1M / 3M / 6M / YTD / 1Y / 3Y return | `return_1m`, `return_3m`, `return_6m`, `return_ytd`, `return_1y`, `return_3y` | fraction (0.05 = 5%) | computed from `ohlcv_bars` |
| Technical | Distance from 52-week high / low | `dist_from_52w_high_pct`, `dist_from_52w_low_pct` | fraction (-0.10 = 10% below high) | computed from `ohlcv_bars` |

**Wave L-3 computed metrics (PLAN-0089, shipped 2026-05-28)**: the 8 performance/technical rows above are produced by `ComputedMetricsBackfillWorker` (`market_data.infrastructure.db.computed_metrics_worker`) — 8 LATERAL-JOIN SQL passes against `ohlcv_bars` with `COALESCE(adjusted_close, close)` fallback (counter logged at WARNING when nonzero). Persisted as `fundamental_metrics` rows with `period_type='SNAPSHOT'`, `section='computed_returns'`. Scheduled daily at 02:00 UTC by `_computed_metrics_refresh_loop` in `app.py` (configurable via `COMPUTED_METRICS_REFRESH_HOUR_UTC` env, 0-23; 20-hour minimum-interval guard). Screener API: `POST /v1/fundamentals/screen` accepts 16 shorthand `*_min`/`*_max` fields per `ScreenFilterRequest` (e.g. `return_1y_min: 0.20`); router expands them into `ScreenFilter(metric=…, period_type='SNAPSHOT')` entries. All 8 names accepted as `sort_by` — a no-bound `ScreenFilter` is injected when `sort_by` references a computed metric not in `filters` to ensure the column is projected for `ORDER BY`. Migration `029_seed_l3_computed_metrics_fields.py` seeds the 8 `screen_field_metadata` rows (`field_type='numeric'`, `unit='percent_1'`); byte-equality with `_get_static_screen_fields()` enforced by `test_l3_migration_lockstep.py` (the 6-hour refresh loop overwrites the seed otherwise).

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
| `003` | `002` | Add 18 fundamentals tables (period-based: income_statement, balance_sheet, etc.). Note: of these 18 only 17 are mixin-derived; `CompanyProfileModel` is mixin-exempt (snapshot-only, no `period_type` column). Earlier docs cited "14 tables" — corrected post-PLAN-0097 W4 after migration 022 enumerated all 18 for `ANALYZE`. |
| `004` | `003` | Add infrastructure tables (ingestion_events, failed_tasks, outbox_events) with new column schema |
| `005` | `004` | Add 4 non-period fundamentals tables (company_profiles, highlights, institutional_holders, fund_holders, insider_transactions_snapshot); drop dividend_summary |
| `002` (consolidated) | `001` (consolidated) | Add `fundamental_metrics` read-optimized projection table with unique constraint and indexes |
| `003` (consolidated) | `002` (consolidated) | Add `lowercase_outbox_status` migration |
| `004` (consolidated) | `003` (consolidated) | Add `screen_field_metadata` table (PRD-0017 Wave B-1) |
| `019` | `018` | Add composite `(instrument_id, period_end_date)` indexes on 18 fundamentals section tables (PLAN-0095 T-W1-03) — 30-100x speedup on `query_fundamentals` history reads |
| `020` | `019` | Snapshot `period_type` columns |
| `021` | `020` | Add `instruments.last_fundamentals_ingest_at` (PLAN-0096 T-W1-02, BP-545) |
| `022` | `021` | `ANALYZE` the 18 fundamentals tables post-019 so the planner picks the composite indexes immediately (PLAN-0097 T-W3-01, **BP-581**). Wrapped in `op.get_context().autocommit_block()` because ANALYZE cannot execute inside a transaction. Downgrade is documented no-op. |
| `023` | `022` | Idempotent re-application of 019's composite indexes via `CREATE INDEX IF NOT EXISTS` (PLAN-0097 T-W4-02) |

> **Note**: Migrations 001–005 were consolidated into a single `001` initial schema.
> The `fundamental_metrics` migration is `002` relative to the consolidated `001`.

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
| `InstrumentRepository` | `find_by_symbol_exchange`, `find_by_id`, `search(query, *, has_ohlcv, has_quotes, has_fundamentals, exchange, limit, offset)` — DB-side filters + pagination, `count(query, *, …)` — matching total, `upsert`, `update_flags`, `update_metadata` |
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
| `market.instrument.created` | `market.events.v1` |
| `market.instrument.updated` | `market.events.v1` |

### Avro schemas

| Event type | Schema file |
|---|---|
| `market.instrument.created` | `src/market_data/infrastructure/messaging/schemas/instrument.created.v1.avsc` |
| `market.instrument.updated` | `src/market_data/infrastructure/messaging/schemas/instrument.updated.v1.avsc` |

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
| `tests/integration/fixtures/sample_fundamentals.json` | Income statement, balance sheet, valuation ratios (3 of 18 sections) |

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
