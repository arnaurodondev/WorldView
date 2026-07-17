# Market Ingestion Service (S2)

> **Owner**: Ingestion domain · **Database**: `ingestion_db` (PostgreSQL 16) · **Port**: 8002
> **Status**: Production-ready (migrations 0001–0025 shipped)

---

## Mission

Market Ingestion is the data acquisition workhorse of the platform. It runs scheduled polls against multiple external financial data providers (EODHD, Yahoo Finance, Finnhub, Polygon, Alpaca), stores raw responses verbatim in MinIO bronze tier, transforms them into provider-agnostic canonical NDJSON in MinIO silver tier, and emits lightweight `market.dataset.fetched` claim-check pointer events on Kafka. Downstream services (Market Data / S3) follow those pointers to materialize query-optimized tables.

This service never serves end-user queries. It has no knowledge of portfolios, articles, or NLP pipelines. Its only output is (MinIO object, Kafka event).

---

## Architecture

Market Ingestion uses the hexagonal (ports-and-adapters) architecture mandated by `RULES.md`:

```
┌────────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                      │
│  health/readyz · trigger · backfill · status · policies        │
└─────────────────────────────┬──────────────────────────────────┘
                              │ (use cases only — never infra)
┌─────────────────────────────▼──────────────────────────────────┐
│                    Application Layer                            │
│  ScheduleTasksUseCase · ClaimTasksUseCase · ExecuteTaskUseCase │
│  TriggerIngestionUseCase · BackfillUseCase                     │
│  RunStartupBackfillUseCase · UpdateSymbolTierUseCase           │
│  SnapshotEodhdQuotaUseCase · DailyBudgetTracker               │
│  InvalidateCacheUseCase · RoutingReloadUseCase                │
└───────────┬──────────────────────┬─────────────────────────────┘
            │                      │
┌───────────▼──────────┐  ┌────────▼────────────────────────────┐
│      Domain          │  │       Infrastructure                │
│  IngestionTask       │  │  Providers: EODHD, Yahoo, Finnhub,  │
│  PollingPolicy       │  │    Polygon, Alpaca, AlphaVantage     │
│  ProviderBudget      │  │  DB: Postgres repos + UoW           │
│  Watermark           │  │  Storage: MinIO (bronze + silver)   │
│  SymbolTier          │  │  Messaging: outbox → Kafka          │
│  MarketDatasetFetched│  │  Metrics: Prometheus s2_*           │
└──────────────────────┘  └─────────────────────────────────────┘
```

### Four Independent Processes

All processes ship in the same Docker image with different `command` overrides:

| Process | Entry Point | Purpose |
|---------|-------------|---------|
| API Server | `uvicorn market_ingestion.app:app` | Manual triggers, status, health, quota, cache invalidation |
| Scheduler | `python -m market_ingestion.infrastructure.scheduler.scheduler_main` | Creates ingestion tasks from polling policies on each tick; also spawns the fundamentals-refresh, instrument-policy-sync and insider-universe loops |
| Worker | `python -m market_ingestion.infrastructure.workers.worker_main` | Claims tasks, fetches data, stores in MinIO, writes outbox |
| Outbox Dispatcher | `python -m market_ingestion.infrastructure.messaging.outbox.dispatcher_main` | Publishes outbox events to Kafka |
| Reclaim Worker | `python -m market_ingestion.infrastructure.workers.reclaim_worker_main` | Periodically resets expired-lease tasks back to `RETRY` to prevent crashed-worker deadlock |

The insider-universe loader (`workers/insider_universe_loader.py`) is a standalone one-shot/cron entry point that refreshes the top-N insider-transaction symbol universe.

---

## API Endpoints

All endpoints are served at port 8002. The whole app is wrapped in `InternalJWTMiddleware`
(PRD-0025): every request must carry a valid internal `X-Internal-JWT` bearer token
(verified against S9's JWKS) unless the route is on the public allow-list (`/healthz`,
`/readyz`). There is **no** `X-Internal-Token` static-header scheme. `/metrics` is also
protected by the JWT middleware.

The mounted routers are `routes.router` (no prefix) and `cache_router`
(`/internal/v1/cache`). The `routing_router` (`/internal/v1/routing`) module exists in
`api/routing_routes.py` but is **not** wired into the app — routing is config-only and is
reloaded by restarting the process (see Configuration).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/healthz` | public | Liveness probe — always 200 |
| GET | `/readyz` | public | Readiness (DB + MinIO + Kafka check) |
| GET | `/metrics` | JWT | Prometheus metrics |
| POST | `/api/v1/ingest/trigger` | JWT | Manually enqueue ingestion tasks for one or more symbols (202 Accepted) |
| POST | `/api/v1/ingest/backfill` | JWT | Backfill historical data for a single symbol over a date range (202 Accepted) |
| GET | `/api/v1/ingest/status` | JWT | Task counts grouped by status |
| GET | `/api/v1/policies` | JWT | List all enabled polling policies |
| GET | `/api/v1/eodhd/quota/status` | JWT | Current EODHD monthly + daily budget status |
| DELETE | `/internal/v1/cache/{dataset_type}/{symbol}` | JWT | Invalidate every cached payload for a `(dataset_type, symbol)` coordinate |

**Trigger request body example** (`symbols` is a list):
```json
{
  "provider": "eodhd",
  "symbols": ["AAPL", "MSFT"],
  "dataset_type": "ohlcv",
  "timeframe": "1d",
  "exchange": "US"
}
```

**Backfill request body example** (single `symbol`, `start_date`/`end_date`):
```json
{
  "provider": "eodhd",
  "symbol": "MSFT",
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "timeframe": "1d",
  "chunk_days": 365,
  "exchange": "US"
}
```

**Example curl (trigger):**
```bash
curl -X POST http://localhost:8002/api/v1/ingest/trigger \
  -H "Content-Type: application/json" \
  -H "X-Internal-JWT: $INTERNAL_JWT" \
  -d '{"provider":"eodhd","symbols":["AAPL"],"dataset_type":"ohlcv","timeframe":"1d","exchange":"US"}'
```

---

## Kafka Topics

### Produced

| Topic | Schema File | Key | Description |
|-------|-------------|-----|-------------|
| `market.dataset.fetched` | `infra/kafka/schemas/market.dataset.fetched.avsc` | `symbol` | Claim-check pointer emitted after each successful fetch |

**Avro schema summary** (`MarketDatasetFetched`):

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | string | UUIDv7 unique event ID |
| `event_type` | string | `"market.dataset.fetched"` |
| `schema_version` | int | Schema version (bump on breaking change) |
| `occurred_at` | string | ISO-8601 UTC |
| `task_id` | string | Ingestion task ID |
| `provider` | string | `eodhd`, `yahoo_finance`, `finnhub`, etc. |
| `dataset_type` | string | `ohlcv`, `quotes`, `fundamentals`, `earnings_calendar`, etc. |
| `symbol` | string | Instrument symbol (e.g. `AAPL`) |
| `exchange` | string? | Exchange code (e.g. `US`, `CC`) |
| `timeframe` | string? | OHLCV timeframe (e.g. `1d`, `1m`) |
| `variant` | string? | Fundamentals variant (e.g. `annual`) |
| `range_start` / `range_end` | string? | ISO-8601 date range |
| `bronze_ref_bucket` / `_key` / `_sha256` / `_byte_length` / `_mime_type` | mixed | MinIO bronze object pointer |
| `canonical_ref_bucket` / `_key` / `_sha256` / `_byte_length` / `_mime_type` | mixed | MinIO canonical object pointer |
| `canonical_schema_version` | int | Default 1 |
| `row_count` | long? | Number of records in the canonical dataset |

### Consumed

None — Market Ingestion is a producer-only service.

---

## Data Model

Database: `ingestion_db` (PostgreSQL 16)

```sql
-- Task queue: unit of work for the scheduler-worker pipeline.
CREATE TABLE ingestion_tasks (
    id              UUID PRIMARY KEY,                -- UUIDv7
    provider        VARCHAR(20) NOT NULL,
    dataset_type    VARCHAR(30) NOT NULL,
    symbol          VARCHAR(20) NOT NULL,
    exchange        VARCHAR(10),
    timeframe       VARCHAR(5),
    range_start     DATE,
    range_end       DATE,
    status          VARCHAR(20) DEFAULT 'pending',   -- pending|claimed|running|succeeded|failed|retry
    dedupe_key      TEXT UNIQUE,                     -- prevents duplicate task creation
    lease_owner     TEXT,                            -- worker UUID that holds the lease
    lease_expires   TIMESTAMPTZ,
    attempt_count   INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 5,
    error_message   TEXT,
    fetched_by_provider VARCHAR(20),                 -- which provider actually succeeded
    result_ref_bucket   TEXT,                        -- MinIO bucket for result
    result_ref_key      TEXT,                        -- MinIO key for result
    created_at      TIMESTAMPTZ DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

-- Transactional outbox for market.dataset.fetched events.
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY,
    event_type      VARCHAR(100) NOT NULL,
    payload         JSONB NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT now(),
    published_at    TIMESTAMPTZ,
    dispatched_at   TIMESTAMPTZ,
    lease_owner     TEXT,
    lease_expires   TIMESTAMPTZ,
    attempt_count   INTEGER DEFAULT 0,
    max_attempts    INTEGER DEFAULT 10
);

-- Cron-like schedule: when and how often to poll each symbol+dataset combo.
CREATE TABLE polling_policies (
    id              UUID PRIMARY KEY,
    provider        VARCHAR(20) NOT NULL,
    dataset_type    VARCHAR(30) NOT NULL,
    symbol          VARCHAR(20) NOT NULL,
    exchange        VARCHAR(10),
    timeframe       VARCHAR(5),
    cron_expression TEXT NOT NULL,
    is_enabled      BOOLEAN DEFAULT true,
    market_hours_only BOOLEAN DEFAULT false,  -- set true for quotes
    post_market_only  BOOLEAN DEFAULT false,
    tier            INTEGER DEFAULT 2,         -- 1=hot, 2=standard, 3=cold
    last_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Per-provider daily budget tracking (EODHD credit system).
CREATE TABLE provider_budgets (
    id              UUID PRIMARY KEY,
    provider        VARCHAR(20) NOT NULL UNIQUE,
    daily_limit     INTEGER NOT NULL,
    used_today      INTEGER DEFAULT 0,
    reset_at        TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Incremental polling watermarks — prevents re-fetching already-ingested data.
CREATE TABLE ingestion_watermarks (
    id              UUID PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    dataset_type    VARCHAR(30) NOT NULL,
    provider        VARCHAR(20) NOT NULL,
    high_water_mark DATE NOT NULL,
    last_success_at TIMESTAMPTZ,              -- used by freshness gate
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, dataset_type, provider)
);

-- Symbol tier classification (tier 1 = high-frequency, 2 = standard, 3 = cold).
CREATE TABLE symbol_tiers (
    id              VARCHAR(26) PRIMARY KEY,  -- UUIDv7
    symbol          VARCHAR(20) NOT NULL,
    exchange        VARCHAR(20) NOT NULL,
    tier            INTEGER NOT NULL DEFAULT 2,
    tier_source     VARCHAR(32) NOT NULL DEFAULT 'default',
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_user_refresh_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, exchange)
);
```

### Migration History

| Revision | Description |
|----------|-------------|
| `0001` | Initial schema (ingestion_tasks, outbox_events, polling_policies, provider_budgets, watermarks) |
| `0002` | Seed 64 polling policies (US equities, ETFs, indices, crypto, forex) |
| `0003` | Add `market_hours_only` column to polling_policies |
| `0004` | Expand ticker coverage to 64 symbols (upsert for live systems) |
| `0005` | API call optimization — fundamentals weekly, 1w/1mo OHLCV extended intervals, recalibrate budget |
| `0006` | Change insider_transactions cadence from daily to weekly |
| `0007` | Add economic event polling for JPN, CHN, EU (joins USA, EUR, GBR) |
| `0008` | Add `symbol_tiers` table + `tier`, `post_market_only` columns to polling_policies |
| `0009` | Cadence reduction seeds |
| `0010` | Add `fetched_by_provider` column to ingestion_tasks |
| `0011` | Alpaca 1m intraday polling policies |
| `0012` | Economic events cadence restore |
| `0013` | Add `dispatched_at` to outbox_events |
| `0014` | Expand polling_policies to the full S&P 500 universe + 7 global indices |
| `0015` | Disable EODHD quote polling for US and CC exchanges |
| `0016` | Disable S2 `news_sentiment` polling policies (moved to S4) |
| `0017` | Add weekly `insider_transactions` + `market_cap` policies for top-100 S&P 500 |
| `0018` | Bump Alpaca 1m polling-policy priority to 100 |
| `0019` | Fix EODHD seed symbols that 404 against the provider API |
| `0020` | Disable weekly (1w) and monthly (1mo) OHLCV polling — bars are now DERIVED in S3 |
| `0021` | Add a partial index on `outbox_events` for unpublished rows |
| `0022` | Seed Tier-1-US tickerless-company polling policies (derived-bar-aware) |
| `0023` | Poll daily (1d) OHLCV from Alpaca; disable redundant EODHD 1d polling |
| `0024` | Slow Alpaca 1d OHLCV polling to once-daily (was 6h) |
| `0025` | Seed Alpaca 1d OHLCV policies for the full US+CC universe (86→541); disable redundant EODHD 1d for US+CC (INDX/FOREX/SHG stay on EODHD) — **current head** |

---

## Configuration

All environment variables are prefixed with `MARKET_INGESTION_`.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MARKET_INGESTION_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/ingestion_db` | Yes | Primary (write) DB URL — use SecretStr in production |
| `MARKET_INGESTION_DATABASE_URL_READ` | `""` | No | Optional read-replica URL; falls back to DATABASE_URL when empty |
| `MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Yes | Kafka broker address |
| `MARKET_INGESTION_SCHEMA_REGISTRY_URL` | `http://localhost:8081` | Yes | Confluent Schema Registry URL |
| `MARKET_INGESTION_STORAGE_ENDPOINT` | `http://localhost:7480` | Yes | MinIO / S3-compatible endpoint |
| `MARKET_INGESTION_STORAGE_ACCESS_KEY` | — | **Required** | MinIO access key (no default — startup fails without it) |
| `MARKET_INGESTION_STORAGE_SECRET_KEY` | — | **Required** | MinIO secret key (no default — startup fails without it) |
| `MARKET_INGESTION_STORAGE_BUCKET` | `market-ingestion` | No | General MinIO bucket |
| `MARKET_INGESTION_BRONZE_BUCKET` | `market-bronze` | No | Raw data (bronze tier) bucket |
| `MARKET_INGESTION_CANONICAL_BUCKET` | `market-canonical` | No | Canonical NDJSON (silver tier) bucket |
| `MARKET_INGESTION_VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey (Redis-compatible) URL for zero-bar tracker and quota |
| `MARKET_INGESTION_EODHD_API_KEY` | `demo` | Yes (prod) | EODHD API key. `demo` works for 3 endpoints; set a real key for production. Get at eodhd.com |
| `MARKET_INGESTION_EODHD_BASE_URL` | `https://eodhd.com/api` | No | Override EODHD base URL without image rebuild (useful for staging) |
| `MARKET_INGESTION_FINNHUB_API_KEY` | `""` | No | Finnhub API key — adapter disabled when empty. Free tier: 60 req/min. Get at finnhub.io |
| `MARKET_INGESTION_POLYGON_API_KEY` | `""` | No | Polygon.io API key — adapter disabled when empty |
| `MARKET_INGESTION_POLYGON_BASE_URL` | `https://api.polygon.io` | No | Polygon base URL |
| `MARKET_INGESTION_ALPHA_VANTAGE_API_KEY` | `""` | No | Alpha Vantage API key — disabled when empty |
| `MARKET_INGESTION_ALPACA_API_KEY` | `""` | No | Alpaca API key — adapter disabled when empty |
| `MARKET_INGESTION_ALPACA_SECRET_KEY` | `""` | No | Alpaca secret key |
| `MARKET_INGESTION_ALPACA_BASE_URL` | `https://data.alpaca.markets` | No | Alpaca data base URL |
| `MARKET_INGESTION_ALPACA_FEED` | `iex` | No | `iex` (free, ~15min delayed) or `sip` (paid, real-time) |
| `MARKET_INGESTION_API_GATEWAY_URL` | `http://api-gateway:8000` | No | S9 base URL for JWKS endpoint (internal JWT verification) |
| `MARKET_INGESTION_INTERNAL_JWT_PRIVATE_KEY` | `""` | No | RS256 private key used to mint internal JWTs for outbound calls (e.g. to market-data) |
| `MARKET_INGESTION_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | No | Set `true` only in E2E tests without S9. **NEVER enable in production** — rejected when `APP_ENV=production` |
| `MARKET_INGESTION_MARKET_DATA_URL` | `http://market-data:8003` | No | S3 base URL (used by fundamentals-refresh internal endpoint) |
| `MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS` | `60.0` | No | How often the scheduler checks for due policies |
| `MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK` | `1000` | No | Max tasks enqueued per tick |
| `MARKET_INGESTION_WORKER_BATCH_SIZE` | `10` | No | Tasks claimed per worker batch |
| `MARKET_INGESTION_WORKER_LEASE_SECONDS` | `300` | No | Lease duration for claimed tasks |
| `MARKET_INGESTION_WORKER_CONCURRENCY` | `4` | No | Concurrent task execution slots |
| `MARKET_INGESTION_WORKER_IDLE_SLEEP_SECONDS` | `5.0` | No | Sleep when no tasks are claimable (also the exponential-backoff base) |
| `MARKET_INGESTION_PROVIDER_HTTP_TIMEOUT_SECONDS` | `30.0` | No | HTTP timeout for provider API calls |
| `MARKET_INGESTION_DISPATCHER_BATCH_SIZE` | `50` | No | Outbox events dispatched per batch |
| `MARKET_INGESTION_DISPATCHER_POLL_INTERVAL_SECONDS` | `1.0` | No | Dispatcher poll cadence |
| `MARKET_INGESTION_DISPATCHER_LEASE_SECONDS` | `60` | No | Dispatcher outbox event lease duration |
| `MARKET_INGESTION_DISPATCHER_MAX_ATTEMPTS` | `20` | No | Max publish attempts before an outbox row is dead-lettered |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_ENABLED` | `true` | No | Enable the 6-hourly fundamentals re-trigger loop (scheduler-spawned) |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_INTERVAL_HOURS` | `6.0` | No | Cadence of the fundamentals-refresh loop |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_TOP_N` | `500` | No | Number of top symbols refreshed each cycle |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_PROVIDER` | `eodhd` | No | Provider used by the fundamentals-refresh loop |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_VARIANT` | `quarterly` | No | Fundamentals variant requested by the refresh loop |
| `MARKET_INGESTION_FUNDAMENTALS_REFRESH_USE_INTERNAL_ENDPOINT` | `true` | No | Pull the refresh symbol list from S3's internal endpoint vs static config |
| `MARKET_INGESTION_INSTRUMENT_POLICY_SYNC_ENABLED` | `true` | No | Enable the 6-hourly instrument-policy sync loop |
| `MARKET_INGESTION_INSTRUMENT_POLICY_SYNC_INTERVAL_HOURS` | `6.0` | No | Cadence of the instrument-policy sync loop |
| `MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_ENABLED` | `false` | No | Enable the weekly insider-universe refresh (off by default — ~2,830 credits/cycle) |
| `MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_DAY_OF_WEEK` | `6` | No | Day-of-week (0=Mon) for the insider-universe refresh |
| `MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_HOUR_UTC` | `5` | No | UTC hour for the insider-universe refresh |
| `MARKET_INGESTION_AUTO_BACKFILL_ON_STARTUP` | `false` | No | Enable startup auto-backfill (off by default; gitops flips it on) |
| `MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS` | `14` | No | How many days back to auto-backfill on startup |
| `MARKET_INGESTION_AUTO_BACKFILL_YEARS` | `10` | No | Hard cap on backfill horizon |
| `MARKET_INGESTION_LOG_LEVEL` | `INFO` | No | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `MARKET_INGESTION_LOG_JSON` | `true` | No | Structured JSON logs (set `false` for human-readable dev output) |
| `MARKET_INGESTION_OTLP_ENDPOINT` | `""` | No | OpenTelemetry OTLP endpoint for tracing |

**Provider routing env vars (comma-separated `provider:weight` pairs):**

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_INGESTION_ROUTING_OHLCV_INTRADAY` | `alpaca:100,polygon:80` | Provider priority for 1m/5m/15m/30m/1h/4h OHLCV |
| `MARKET_INGESTION_ROUTING_OHLCV_EOD` | `alpaca:100,eodhd:80` | Provider priority for 1d/1w/1M OHLCV (Yahoo dropped — Alpaca 1Day is the free deep-daily source, EODHD is failover) |
| `MARKET_INGESTION_ROUTING_QUOTES` | `eodhd:100` | Provider priority for real-time quotes |
| `MARKET_INGESTION_ROUTING_FUNDAMENTALS` | `eodhd:100` | Provider priority for fundamentals |
| `MARKET_INGESTION_ROUTING_NEWS_SENTIMENT` | `eodhd:100` | Provider priority for news sentiment |
| `MARKET_INGESTION_ROUTING_EARNINGS_CALENDAR` | `eodhd:100` | Provider priority for earnings calendar |
| `MARKET_INGESTION_ROUTING_INSIDER_TRANSACTIONS` | `eodhd:100` | Provider priority for insider transactions |

---

## External Dependencies

### EODHD (Primary Provider)

- **Purpose**: OHLCV bars (EOD), real-time quotes (15-min delayed), full fundamentals (18 sections), earnings calendar, economic events, macro indicators, insider transactions, news sentiment, yield curve, historical market cap.
- **Auth**: `api_token` query parameter.
- **Rate limits**: Demo key — limited to 3 endpoints; production key — 100,000 credits/month (hard cap). Credit cost: fundamentals=10, intraday=5, news/economic/macro/yield/insider=5, OHLCV EOD=1, quotes=1, **bulk EOD=100/exchange**.
- **Bulk EOD (authoritative daily source)**: `GET /eod-bulk-last-day/{EXCHANGE}` returns EVERY symbol on an exchange for one trading day (US ≈ 33.6k records) in ONE call with `close`, **`adjusted_close`**, and the **correct consolidated `volume`** — a flat 100 credits/exchange. The `bulk_eod_daily` script (`scripts/bulk_eod_daily.py`, run once daily by `infra/k8s/bulk-eod-daily-cronjob.yaml`) fetches this, filters to the covered universe, and produces per-symbol daily bars stamped `eodhd_bulk` → market-data `provider_priority = 120`, ABOVE Alpaca's IEX daily (110). This fixes the wrong daily volume + NULL adjusted_close Alpaca's IEX feed produced. The `backfill_daily_ohlcv.py --authoritative` flag stamps the same `eodhd_bulk` label to CORRECT the ~9.9k historical Alpaca-won daily rows (~550 credits via per-ticker `/eod`).
- **Intraday 1m refinement (post-close)**: Alpaca's live 1m feed is IEX-only (~2-5% of the consolidated tape), so every derived intraday timeframe (5m..4h, volume-summed from 1m) carries ~5% volume — wrong on the 1D/5D chart histogram. The `intraday_refine` script (`scripts/intraday_refine.py`, run once daily by `infra/k8s/intraday-refine-cronjob.yaml` at 23:30 UTC) fetches EODHD's per-ticker 1m feed (`GET /intraday/{SYMBOL}?interval=1m`, correct consolidated CTA/UTP volume, ~5 credits/symbol) for a CLOSED, already-published trading day and produces per-symbol 1m bars stamped `eodhd_intraday` → market-data `provider_priority = 115`, ABOVE Alpaca's live IEX 1m (110). EODHD 1m `datetime` is UTC bar-start on the exact minute, which ALIGNS with Alpaca's 1m `bar_date`, so the S3 upsert guard REPLACES the IEX bar on the same `(instrument, 1m, bar_date)` key (no duplicate); the existing intraday-resampling consumer then re-derives 5m..4h from the corrected 1m with no double-count. Alpaca STAYS the LIVE intra-session 1m source. **Publish lag**: EODHD intraday publishes a day ≥1 trading day late (live-verified 2026-07-17), so the default target is `today − 2 trading days` (`--settle-lag-days`, weekend-aware); an explicit `--date` skips the lag. **Preflight**: before the sweep it probes one liquid symbol (AAPL/MSFT/…) for the target day — 0 bars (unpublished or all-market holiday) ABORTS the whole sweep after a single 5-credit probe, spending NO further budget and writing NO resume-set entries (so a later run still refines the day). US equities only (~530 × 5 = ~2,650 credits/sweep); crypto stays on Alpaca. Resumable (Valkey per-day done-set), advisory-locked, dry-runnable. SEPARATE deploy unit from the daily bulk-EOD fix. See `docs/audits/2026-07-16-consolidated-volume-timeframes.md`.
- **Get your key**: [eodhd.com](https://eodhd.com) — free demo key works for local development.
- **Quota enforcement**: `EodhdQuotaService` in `libs/messaging` enforces 100K/month via atomic Valkey INCRBY. Soft warning at 80%. Hard block retries the task (not fail) so it can run next month.

### Yahoo Finance (Free, OHLCV EOD/weekly/monthly)

- **Purpose**: EOD OHLCV (1d/1w/1mo/1M timeframes only). Free, no API key needed.
- **Implementation**: `yfinance` Python library (blocking — always wrapped in `asyncio.run_in_executor`).
- **Limitation**: No intraday data. Falls back to EODHD after 5 consecutive zero-bar responses.

### Finnhub (Free Tier)

- **Purpose**: News sentiment, earnings calendar (global), insider transactions. Free tier: 60 req/min.
- **Auth**: `token` query parameter (`MARKET_INGESTION_FINNHUB_API_KEY`).
- **Rate limit**: 1.1s sleep enforced after each call to stay under free-tier limit.
- **Activation**: Adapter only registered when `finnhub_api_key != ""`.
- **Get your key**: [finnhub.io](https://finnhub.io) — free developer key.

### Polygon.io (Paid)

- **Purpose**: Multi-symbol batch intraday OHLCV. Free tier: 5 req/min.
- **Auth**: API key in query params.
- **Activation**: Disabled when `polygon_api_key = ""`.

### Alpaca Markets (Data API)

- **Purpose**: 1-minute intraday OHLCV bars (`fetch_ohlcv_batch` for multi-symbol batches).
- **Auth**: `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY` HTTP headers (never in URL).
- **Feed**: `iex` (free, ~15-min delayed) or `sip` (paid, real-time).
- **Activation**: Disabled when `alpaca_api_key = ""`.

---

## Covered Symbols

The seed universe started at 64 symbols (migration 0002/0004) and was expanded to the
**full S&P 500 + 7 global indices** in migration 0014. Later migrations (0015–0024) tuned
the per-policy cadence and provider mix:

| Migration | Effect on the universe / cadence |
|-----------|----------------------------------|
| `0014` | Full S&P 500 equities + 7 global indices |
| `0015` | EODHD `quotes` polling disabled for US + CC exchanges |
| `0016` | `news_sentiment` polling disabled (moved to S4) |
| `0017` | Weekly `insider_transactions` + `market_cap` for top-100 S&P 500 by market cap |
| `0020` | Weekly (1w) + monthly (1mo) OHLCV polling disabled — derived on-read in S3 |
| `0022` | Tier-1-US tickerless-company policies seeded |
| `0023`/`0024` | Daily (1d) OHLCV now polled from Alpaca (once-daily) instead of EODHD 6-hourly |
| `0025` | Alpaca 1d policies expanded to the full US+CC universe (86→541); redundant EODHD 1d disabled for US+CC (INDX/FOREX/SHG stay on EODHD) |

**Current steady-state per-symbol policies** (after the 0020/0023/0024 cleanup):

| Policy | Provider | Cadence | Notes |
|--------|----------|---------|-------|
| `ohlcv 1d` | Alpaca | once daily | Daily bars; EODHD is failover-only |
| `fundamentals` | EODHD | 7 days (+ 6h refresh loop) | Disabled for crypto/indices/commodity ETFs |

1w/1mo OHLCV are **derived-on-read** in market-data (S3) from the polled daily series and
are no longer routed or polled here. `quotes` polling for US/CC was disabled in 0015.

---

## Core Workflows

### Scheduled Ingestion Flow

```
Scheduler tick
  → evaluate polling_policies (cron + freshness gate)
  → INSERT ingestion_task (ON CONFLICT DO NOTHING via dedupe_key)

Worker loop
  → claim_batch (FOR UPDATE SKIP LOCKED, lease-based)
  → check provider_budget (SELECT FOR UPDATE, decrement credits)
  → check watermark (skip if still fresh per FRESHNESS_TTL_SECONDS)
  → _preferred_provider() → select cheapest available provider
  → fetch from provider API
  → PUT raw bytes → MinIO bronze bucket
  → transform → canonical NDJSON
  → PUT canonical → MinIO silver bucket
  → INSERT outbox_event (atomic with task completion)
  → UPDATE task.status = succeeded

Outbox Dispatcher
  → poll outbox_events WHERE status=pending
  → claim + serialize to Avro
  → produce to Kafka market.dataset.fetched
  → UPDATE outbox_event.status = dispatched
```

### Zero-Bar Failover

After 5 consecutive `bars_returned=0` responses from a free provider (tracked in Valkey with a 24h TTL streak counter), the system re-fetches using the fallback provider (Yahoo→EODHD, Finnhub→EODHD). Disabled gracefully when Valkey is unavailable.

### Canonical Passthrough Serialization

Seven dataset types use passthrough serialization (single NDJSON line wrapping raw payload):
`economic_events`, `macro_indicator`, `insider_transactions`, `earnings_calendar`, `news_sentiment`, `yield_curve`, `market_cap`.

Format: `{"dataset_type": "...", "symbol": "...", "source": "eodhd", "payload": <raw>, "fetched_at": "..."}`

---

## How to Run Locally

**Prerequisites**: Docker, Python 3.12, `make`.

```bash
# 1. Start the full platform infra (Postgres, Kafka, MinIO, Valkey)
make dev  # from repo root

# 2. Create the ingestion_db database (if not using make dev)
docker exec -it worldview-postgres psql -U postgres -c "CREATE DATABASE ingestion_db;"

# 3. Set up service
cd services/market-ingestion
cp configs/dev.local.env.example .env
# Edit .env — at minimum set MARKET_INGESTION_STORAGE_ACCESS_KEY and _SECRET_KEY

# 4. Install dependencies
source ../../.venv312/bin/activate
pip install -e ".[dev]"

# 5. Run database migrations
alembic upgrade head

# 6. Start the API server
make run       # port 8002

# 7. (Optional) Start the scheduler and worker in separate terminals
python -m market_ingestion.infrastructure.scheduler.scheduler_main
python -m market_ingestion.infrastructure.workers.worker_main

# 8. Verify health
curl http://localhost:8002/healthz     # → {"status": "ok"}
curl http://localhost:8002/readyz      # → {"status": "ready"} (or 503 if infra missing)
```

**Manual trigger (requires infra running):**
```bash
curl -X POST http://localhost:8002/api/v1/ingest/trigger \
  -H "Content-Type: application/json" \
  -H "X-Internal-JWT: $INTERNAL_JWT" \
  -d '{"provider":"eodhd","symbols":["AAPL"],"exchange":"US","dataset_type":"ohlcv","timeframe":"1d"}'
```

> The API is wrapped in `InternalJWTMiddleware`. For local single-service testing without
> S9, set `MARKET_INGESTION_INTERNAL_JWT_SKIP_VERIFICATION=true` (never in production).

---

## How to Run Tests

```bash
cd services/market-ingestion

# Unit tests only (fast, no Docker needed)
make test
# or equivalently:
python -m pytest tests/unit tests/domain tests/application tests/api -v -m unit

# Contract tests (Avro schema alignment)
make test-contract
# or:
python -m pytest tests/contract -v

# Live tests against real EODHD demo API
make test-live
# or:
python -m pytest tests/live/test_eodhd_live.py -v
# Note: 48 pass, 8 xfail (paid-only endpoints expected to fail with demo key)

# Integration tests (requires Docker)
make test-integration
# or:
python -m pytest tests/integration -v -m integration

# Full test suite
make test-all

# Lint and type checks
make lint
python -m mypy src/ --config-file mypy.ini
```

**Test categories:**

| Category | Location | What is tested | Needs Docker? |
|----------|----------|----------------|---------------|
| Unit | `tests/unit/`, `tests/domain/`, `tests/application/` | Domain entities, use cases with mocked repos, provider adapters with mocked HTTP | No |
| API | `tests/api/` | FastAPI route responses with mocked use cases | No |
| Contract | `tests/contract/` | Avro schema ↔ Python mapper alignment | No |
| Live | `tests/live/` | Real EODHD demo API calls | No (network) |
| Integration | `tests/integration/` | Worker ↔ MinIO round-trip with real containers | Yes |
| E2E | `tests/e2e/` | Full pipeline end-to-end | Yes |

---

## Common Pitfalls

1. **`yfinance` is synchronous** — never call `yf.Ticker.history()` directly in async code. Always wrap in `asyncio.get_running_loop().run_in_executor(None, lambda: ...)`.

2. **EODHD demo key limitations** — The demo key only works for `fetch_ohlcv`, `fetch_quotes`, and `fetch_fundamentals` plus limited `fetch_earnings_calendar`. All other endpoints require a paid subscription. Set `MARKET_INGESTION_EODHD_API_KEY` to a real key in production.

3. **Watermark race condition** — Two workers racing on the same symbol can both try to update the watermark. The loser raises `WatermarkViolation` → `ExecuteTaskUseCase` calls `task.retry()` (not `task.fail()`). The task is re-queued and the worker loop picks it up again.

4. **Token bucket (ProviderBudget) requires SELECT FOR UPDATE** — Load the budget with `get_for_update()` inside a transaction to prevent double-consume by concurrent workers. See BP-036.

5. **Provider routing is config-driven** — The `routing_*` env vars define provider priority. A registered provider with weight 0 is effectively disabled. The `_preferred_provider()` function selects the highest-weight registered provider for the dataset+timeframe combination.

6. **Finnhub earnings calendar has no symbol filter on the free tier** — `fetch_earnings_calendar` returns all upcoming global earnings in the date window. The call site in `execute_task._fetch()` passes only `from_date`/`to_date`, not `symbol`.

7. **Bronze object store uses skip-if-exists on retry** — `put()` is a no-op if the key already exists (idempotent retry path, D-008). This prevents duplicate bronze objects from accumulating on retry storms.

8. **`httpx` stubs return `Any` for `response.content`** — Always use `cast("bytes", response.content)` in provider adapter `_get()` methods or `mypy` will fail with `no-any-return`.

9. **Startup warns on demo EODHD key and default DB credentials** — Both trigger a `structlog` WARNING at startup. This is intentional and not an error; it is a reminder to configure production secrets.

---

## Runbook

**Service is not ingesting data:**
1. Check `GET /readyz` — if 503, check DB/MinIO/Kafka connectivity.
2. Check `GET /api/v1/ingest/status` — are tasks stuck in `running` (expired leases)?
3. Run `GET /api/v1/policies` — are policies enabled (`is_enabled=true`)?
4. Check Prometheus `s2_eodhd_quota_blocked_total` — monthly quota exhausted?
5. Check `s2_eodhd_rate_limited_total` — burst rate limiting?
6. Manually trigger: `POST /api/v1/ingest/trigger`.
7. Check MinIO buckets `market-bronze` and `market-canonical` for recent objects.

**Tasks stuck in RUNNING state:**
- Reclaim worker (`reclaim_worker_main.py`) resets expired-lease tasks to RETRY every N seconds.
- Check `worker_claim_error` log events for DB claim failures.
- If worker crashed, tasks will auto-recover when lease expires.

**EODHD quota exhausted:**
- Check Valkey key `eodhd:v1:quota:{YYYY-MM}:credits_used`.
- Tasks with hard-limit exceeded are retried (not failed) — they will process next month.
- To reset in dev: `DEL eodhd:v1:quota:*` in Valkey.

**MinIO unavailable:**
- Tasks raise `RetryableError` and are re-queued with exponential backoff.
- Check `storage_endpoint` env var and MinIO container health.

**Observability:**
- Metrics: `s2_eodhd_*` (EODHD-specific) and `s2_mi_provider_*` (all providers)
- Grafana dashboard: `infra/grafana/dashboards/api-usage-analytics.json`
- Key log events: `provider_api_call`, `task_claimed`, `task_succeeded`, `task_failed`, `backoff_seconds`
