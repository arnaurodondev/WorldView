# Market Data Service

> **Owner**: Market Data domain · **Database**: `market_data_db` (TimescaleDB) · **Port**: 8003
> **Status**: Complete (waves 01–04 shipped)

---

## Mission & Boundaries

**Owns**: Materializing OHLCV bars, quotes, and fundamentals from claim-check pointers.
Serving query APIs for charts, fundamentals, and instrument metadata. Security/instrument
master data. Instrument lifecycle events.

**Never does**: Fetch data from upstream providers (Market Ingestion's job), store news
or articles, perform NLP processing, manage portfolios.

---

## API Surface (30 routes)

| Method | Path | Description | Cache Tier |
|--------|------|-------------|------------|
| GET | `/healthz` | Liveness probe — always 200 | — |
| GET | `/readyz` | Readiness (DB + Valkey + Storage + Kafka) | — |
| GET | `/metrics` | Prometheus metrics (via middleware) | — |
| GET | `/api/v1/instruments` | List instruments — query params: `query`, `has_ohlcv`, `has_quotes`, `has_fundamentals`, `exchange`, `limit`, `offset` (all DB-side) | — |
| GET | `/api/v1/instruments/symbol/{symbol}` | Instrument by symbol (query param: `exchange`) | — |
| GET | `/api/v1/instruments/{instrument_id}` | Instrument detail by UUID | — |
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
| GET | `/api/v1/fundamentals/timeseries` | Metric timeseries — query params: `instrument_id`, `metric`, `start_date`, `end_date`, `period_type`, `limit`. Returns 422 if `start_date > end_date`. | — |
| POST | `/api/v1/fundamentals/screen` | Screen instruments by metric thresholds (AND logic) — JSON body: `filters[]` (each filter may include `metric`, `min_value`, `max_value`, `period_type`, `sector`), `limit`, `offset` | — |
| GET | `/api/v1/fundamentals/metrics/{instrument_id}` | List available metric names for an instrument | — |
| GET | `/api/v1/securities` | List securities — query params: `figi`, `isin`, `limit`, `offset` (paginated DB scan when unfiltered) | — |
| GET | `/api/v1/securities/{security_id}` | Security detail by FIGI or ISIN | — |

> **Note on path ordering**: Literal-segment routes (`/ohlcv/bulk`, `/quotes/latest`,
> `/instruments/symbol/{symbol}`) are registered **before** path-param routes
> (`/ohlcv/{instrument_id}`, `/quotes/{instrument_id}`, `/instruments/{instrument_id}`)
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
| `market.dataset.fetched` | `market-data-fundamentals` | Materialize fundamentals | `event_id` |

### Produced

| Topic | Event Type | Key |
|-------|-----------|-----|
| `market.instrument.created` | `InstrumentCreated` | `instrument_id` |
| `market.instrument.updated` | `InstrumentUpdated` | `instrument_id` |

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
```

---

## Runtime Processes (5)

| Process | Purpose |
|---------|---------|
| API Server | Serve query APIs (OHLCV, quotes, fundamentals, instruments) |
| OHLCV Consumer | Materialize OHLCV bars from claim-check events |
| Quotes Consumer | Materialize latest quotes |
| Fundamentals Consumer | Materialize fundamentals data |
| Outbox Dispatcher | Publish instrument lifecycle events |

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

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKET_DATA_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db` | Primary (write) DB |
| `MARKET_DATA_READ_REPLICA_URL` | _(unset)_ | Optional read replica URL. When unset, reads use `DATABASE_URL` |
| `MARKET_DATA_VALKEY_URL` | `redis://localhost:6379/0` | Valkey (Redis-compatible) cache URL |
| `MARKET_DATA_KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |
| `MARKET_DATA_STORAGE_ENDPOINT` | `localhost:7480` | MinIO / S3-compatible endpoint |

---

## Testing Plan

| Type | Marker | Count | Command |
|------|--------|-------|---------|
| Unit | `unit` | 180 | `make test` (fast path, no Docker) |
| Integration — repositories | `integration slow` | 19 | `make test -- tests/integration/test_repositories.py` |
| Integration — outbox + UoW | `integration slow` | 9 | `make test -- tests/integration/test_outbox_integration.py` |
| Integration — infra smoke | `integration slow` | 5 | `make test -- tests/integration/test_infra_smoke.py` |
| Integration — contracts | `integration` | 13 | `make test -- tests/integration/test_contracts.py` |
| E2E — pipeline | `integration slow` | 4 | `make test -- tests/integration/test_e2e_pipeline.py` |
| Performance — benchmarks | `integration slow` | 5 | `make test -- tests/integration/test_benchmarks.py` |

---

## Local Run

```bash
cd services/market-data
cp configs/dev.local.env.example .env
make run       # API on port 8003
make test
make lint
make migrate
```

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
| `InstrumentCreated` | `market.instrument.created` | 1 | `instrument_id`, `security_id`, `symbol`, `exchange` | First-seen instrument |
| `InstrumentUpdated` | `market.instrument.updated` | 1 | `instrument_id`, `symbol`, `exchange`, `has_ohlcv`, `has_quotes`, `has_fundamentals` | Capability flags change |

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
    ├── ParseError          ← also inherits FatalError (messaging lib)
    └── StaleDataError
```

| Error | When raised |
|-------|-------------|
| `MarketDataError` | Base; catch-all for all domain errors |
| `InstrumentNotFoundError` | Lookup for a non-existent instrument |
| `SecurityNotFoundError` | Lookup for a non-existent security |
| `DuplicateEventError` | `event_id` already in `ingestion_events` (idempotency guard) |
| `IngestionError` | Business-rule failure during ingestion (valid payload, invalid context) |
| `ParseError` | Payload cannot be deserialized — also a `FatalError` so consumer dead-letters immediately |
| `StaleDataError` | Incoming data has lower provider priority than stored record |

`ParseError` uses multiple inheritance (`MarketDataError, FatalError`) so Kafka consumer
routing can treat it as `FatalError` without knowing the domain-specific type.

---

## Common Pitfalls

1. **Using `float` for price fields in domain entities** — domain entities use `Decimal`
   to match the `NUMERIC(18,6)` DB column type. The `float` decision in `contracts/` applies
   only to canonical transport models (Avro). Converting `Decimal → float` at the DB boundary
   causes silent precision loss.

2. **Raising `IngestionError` for parse failures** — use `ParseError` when data cannot be
   deserialized. `ParseError` inherits `FatalError` so the consumer dead-letters immediately.
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
| `tests/integration/fixtures/sample_fundamentals.json` | Income statement, balance sheet, valuation ratios (3 of 14 sections) |
