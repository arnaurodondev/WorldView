---
id: PRD-0032
title: Multi-Provider OHLCV Routing and Intraday Resampling
status: draft
created: 2026-04-25
updated: 2026-04-25
authors: [Arnau Rodon]
services: [market-ingestion, market-data]
---

# PRD-0032: Multi-Provider OHLCV Routing and Intraday Resampling

## 1. Problem Statement

The platform currently ingests OHLCV data from EODHD (primary) and Yahoo Finance (secondary), but this combination has critical gaps:

1. **No intraday data**: EODHD intraday endpoints cost 5 API credits per call. At 1000+ symbols × 5-minute resolution, this requires ~390,000 credits/day against a hard quota of 100,000 — fundamentally unviable at scale.
2. **Static provider selection**: The current code picks a provider at policy-creation time or at task-build time; there is no runtime routing layer. When a provider fails or returns empty data, the system retries the same provider indefinitely rather than routing to a more reliable alternative.
3. **No partial/intraday bars**: The `ohlcv_bars` table lacks `is_partial` semantics. There is no way to mark a bar that covers only part of its interval (e.g., at 9:13 the current 5-minute bar runs 9:10–9:13, not a full 9:10–9:15).
4. **No derived intraday timeframes**: Users cannot query 5m, 15m, 30m, 1h, or 4h bars because the platform only ingests 1m bars from intraday sources and has no resampling layer.
5. **Provider stickiness**: When a failover event routes a task to a secondary provider, the primary provider's data is never back-filled, leaving permanent quality gaps in historical records.

## 2. Target Users

- **Platform operators** — need per-(dataset_type, timeframe) provider priority control without restarting services
- **Algorithmic traders / screener users** — need sub-daily OHLCV granularity (1m, 5m, 15m, 30m, 1h, 4h)
- **Frontend / API consumers** — need `is_partial` flag to distinguish live open bars from completed bars

## 3. Functional Requirements

### 3.1 Must-Have (v1)

| ID | Requirement |
|----|-------------|
| FR-01 | System ingests 1-minute bars for NYSE/NASDAQ equities via Alpaca REST API (multi-symbol batch endpoint). |
| FR-02 | System falls back to Polygon REST API when Alpaca returns zero bars for ≥5 consecutive calls on the same (symbol, timeframe). |
| FR-03 | Routing priority for any (dataset_type, timeframe) pair is defined in `Settings` (environment variables) and loaded into an in-memory `ProviderRoutingCache` at startup. No DB table required. |
| FR-04 | Operators can force-reload the in-memory routing cache without restarting any service via `POST /internal/v1/routing/reload`. |
| FR-05 | `ExecuteTaskUseCase` selects the provider with the highest `weight` for the task's (dataset_type, timeframe) using the in-memory cache. No per-task DB query in the hot path. |
| FR-06 | Every `SUCCEEDED` ingestion task records which provider actually fetched the data (`fetched_by_provider` column). |
| FR-07 | `PrimaryProviderReclaimWorker` runs every 4 hours, identifies tasks whose `fetched_by_provider` differs from the current highest-weight enabled provider, and re-creates tasks for the primary provider to overwrite the data. |
| FR-08 | S3 (`market-data`) deploys an `IntradayResamplingWorker` that consumes `market.dataset.fetched` events for 1m OHLCV bars and upserts derived 5m, 15m, 30m, 1h, 4h bars with open-bar semantics. |
| FR-09 | Resampling uses strict open-bar semantics: at time T, the bar for period P is computed from all 1m bars in [floor(T, P), T]. Example: at 9:13, the 5m bar covers 9:10–9:13 (not 9:05–9:10). |
| FR-10 | Resampled bars are marked `is_derived=true, is_partial=true` until a full period has elapsed, then `is_partial=false`. |
| FR-11 | `is_partial` column is added to `ohlcv_bars` (migration 008, `server_default=false`). |
| FR-12 | Alpaca adapter supports multi-symbol batch requests (up to 1000 symbols per request, ~3 requests for 3000 tickers). |
| FR-13 | Polygon adapter supports single-ticker aggregate endpoint (`/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{from}/{to}`). |

### 3.2 Nice-to-Have (deferred)

| ID | Requirement | Rationale for Deferral |
|----|-------------|----------------------|
| FR-D-01 | WebSocket subscription for real-time 1m bars (Alpaca stream) | Requires connection-pool management across replicas; REST polling handles 3000 tickers adequately |
| FR-D-02 | Per-symbol routing overrides | MVP uses per-(dataset_type, timeframe) rules; per-symbol adds complexity without clear demand |
| FR-D-03 | Polygon WebSocket | Same as FR-D-01 |
| FR-D-04 | 4h bars from Alpaca directly | Derivable from 1m via resampling |
| FR-D-05 | Reclaim worker for bulk historical range | MVP re-creates incremental tasks; bulk range requires new task type |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | Alpaca batch fetch for 3000 symbols must complete within 60 seconds (≤3 requests × ~15s each at free tier). |
| NFR-02 | `ProviderRoutingCache` lookup is O(1) — in-memory dict, no async I/O in the hot path. |
| NFR-03 | Resampling worker must process a 1m bar event and upsert all derived timeframes within 5 seconds of event consumption. |
| NFR-04 | Routing configuration is defined in `Settings` (env vars); force-reload via `POST /internal/v1/routing/reload` re-reads `Settings` immediately — no service restart required. |
| NFR-05 | All new DB columns use `server_default` so migrations require no table rewrite. |
| NFR-06 | Alpaca adapter must not expose the API key in any log line or metric label. |
| NFR-07 | Polygon adapter rate-limit guard: free tier is 5 req/min; adapter must enforce a per-second token bucket. |
| NFR-08 | `PrimaryProviderReclaimWorker` must be an independent process (R22 — one concern per process). |

## 5. Out of Scope

- WebSocket ingestion from any provider (deferred, see FR-D-01)
- Per-symbol routing overrides (deferred, see FR-D-02)
- Tick data or order book data
- Options or futures OHLCV
- Any frontend changes (no new UI for this PRD; existing OHLCV chart reads from S3 which will now serve intraday timeframes)
- Changes to S9 API Gateway routing (S3 already exposes `GET /internal/v1/ohlcv/{instrument_id}`)
- Alpha Vantage or Finnhub OHLCV (separate PRD if needed)

---

## 6. Technical Design

### 6.1 Affected Services

| Service | What Changes | Why |
|---------|-------------|-----|
| `market-ingestion` (S2) | New Alpaca + Polygon provider adapters; `ProviderRoutingCache` (config-backed, no DB table); `fetched_by_provider` on `ingestion_tasks`; `PrimaryProviderReclaimWorker`; `POST /internal/v1/routing/reload` | Primary intraday data source + dynamic routing layer |
| `market-data` (S3) | `is_partial` column on `ohlcv_bars`; `IntradayResamplingWorker`; `ResampledOHLCVUseCase` | Intraday bar derivation with open-bar semantics |
| `libs/contracts` | No changes — `market.dataset.fetched.v1` already carries all required fields | N/A |
| `api-gateway` (S9) | No changes — S3 already exposes `GET /internal/v1/ohlcv/{instrument_id}` | N/A |

### 6.2 API Changes

#### POST /internal/v1/routing/reload (S2 — market-ingestion)
- **Purpose**: Force-reloads the in-memory `ProviderRoutingCache` from current `Settings` (environment variables). Useful after a rolling config push where env vars have been updated and the operator wants immediate effect without a full service restart.
- **Auth**: internal-only (X-Internal-JWT required, validated by InternalJWTMiddleware)
- **Request body**: None
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | reloaded | bool | Always `true` |
  | rules_loaded | int | Number of routing rules now in cache |
- **Error responses**: 401 (missing/invalid internal JWT)
- **Rate limit**: internal endpoint, no rate limit

#### GET /internal/v1/routing/rules (S2 — market-ingestion)
- **Purpose**: Returns the current in-memory routing cache state. For operator debugging.
- **Auth**: internal-only (X-Internal-JWT)
- **Request body**: None
- **Response** (200):
  ```json
  {
    "rules": [
      {"dataset_type": "ohlcv", "timeframe": "1m", "provider": "alpaca", "weight": 100, "enabled": true},
      {"dataset_type": "ohlcv", "timeframe": "1m", "provider": "polygon", "weight": 80, "enabled": true},
      {"dataset_type": "ohlcv", "timeframe": "1d", "provider": "yahoo_finance", "weight": 100, "enabled": true},
      {"dataset_type": "ohlcv", "timeframe": "1d", "provider": "eodhd", "weight": 80, "enabled": true}
    ],
    "cache_loaded_at": "2026-04-25T09:00:00Z",
    "ttl_seconds": 300
  }
  ```
- **Error responses**: 401

### 6.3 Event Changes

No new Kafka topics or Avro schema changes. The `IntradayResamplingWorker` consumes the existing `market.dataset.fetched.v1` event.

#### market.dataset.fetched.v1 (existing — read-only)
- **Topic**: `market.dataset.fetched.v1`
- **Producers**: S2 (market-ingestion) — unchanged
- **Consumers (new)**: S3 `IntradayResamplingWorker` — subscribes to this topic filtered by `dataset_type=OHLCV, timeframe=1m`
- **Consumer group**: `market-data-intraday-resampling`
- **Idempotency**: S3 worker deduplicates on `event_id` using Valkey (same pattern as existing S3 OHLCVConsumer)
- **Replay safety**: Resampling is a pure function of 1m bar data. Replaying an event re-computes and re-upserts the same derived rows — idempotent by design.

### 6.4 Database Changes

#### S2 Settings — Routing Configuration (env vars, NOT a DB table)

Routing priority is defined as `Settings` fields (pydantic-settings env vars), not a DB table. This eliminates the need for an ORM model, repository port, `UnitOfWork` extension, and migration DDL for routing data. The `ProviderRoutingCache` reads these at startup and on force-reload.

**Rationale** (see ADR-032-02): ~12 routing rules change on the timescale of months (when a new provider is onboarded). A DB table with entity + ORM + repo + migration for essentially static configuration is over-engineering. Env vars are simpler, version-controlled in deploy configs, and reload faster.

**New fields in `market_ingestion/config.py`** (via `pydantic-settings`):

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `MARKET_INGESTION_ROUTING_OHLCV_INTRADAY` | `str` | `"alpaca:100,polygon:80"` | Ordered `provider:weight` pairs for intraday OHLCV (1m, 5m, 15m, 30m, 1h, 4h) |
| `MARKET_INGESTION_ROUTING_OHLCV_EOD` | `str` | `"yahoo_finance:100,eodhd:80"` | Ordered `provider:weight` pairs for end-of-day OHLCV (1d, 1w, 1M) |
| `MARKET_INGESTION_ROUTING_QUOTES` | `str` | `"eodhd:100"` | Routing for quotes (any timeframe) |
| `MARKET_INGESTION_ROUTING_FUNDAMENTALS` | `str` | `"eodhd:100"` | Routing for fundamentals (any timeframe) |

**Format**: `"provider1:weight1,provider2:weight2"` — comma-separated pairs, parsed at startup by `ProviderRoutingCache.load_from_config(settings)`. Highest weight is selected first. Unknown providers (key not in `Provider` enum) are silently skipped. A `POST /internal/v1/routing/reload` re-reads the current `Settings` and rebuilds the cache immediately.

**Intraday timeframes** covered by `ROUTING_OHLCV_INTRADAY`: `{"1m", "5m", "15m", "30m", "1h", "4h"}`.
**EOD timeframes** covered by `ROUTING_OHLCV_EOD`: `{"1d", "1w", "1M"}`.

#### Table: `ingestion_tasks` (market_ingestion_db — EXTENDED)

Add `fetched_by_provider` column to record which provider actually completed a task (populated on status → `SUCCEEDED`).

| New Column | Type | Nullable | Default | Notes |
|-----------|------|----------|---------|-------|
| fetched_by_provider | VARCHAR(50) | yes | NULL | NULL until task SUCCEEDS; populated by `ExecuteTaskUseCase` after successful fetch |

- **Migration**: 0010 for market-ingestion (only change in this migration — no table creation)
- **server_default**: NULL — forward-compatible; all existing completed rows remain NULL (treated as "unknown provider" by reclaim worker)
- **Index**: `(status, provider, fetched_by_provider)` covering `(dataset_type, timeframe, symbol)` — used by `PrimaryProviderReclaimWorker` to find tasks where `provider != fetched_by_provider`

#### Table: `ohlcv_bars` (market_data_db — EXTENDED)

Add `is_partial` column to distinguish open/partial bars from completed bars.

| New Column | Type | Nullable | Default | Notes |
|-----------|------|----------|---------|-------|
| is_partial | BOOLEAN | no | false | true = bar covers [period_start, now), not a full period; false = bar is complete |

- **Migration**: 008 for market-data (current head: 007)
- **server_default**: `false` — all existing bars (which are daily/weekly/monthly) are complete bars
- **Index**: No dedicated index needed — `is_partial` is typically queried together with `timeframe` which already has good cardinality via the existing composite PK
- **Break surface**: `OHLCVBar` entity in `services/market-data/src/market_data/domain/entities.py` gains `is_partial: bool = False` field; `OHLCVBarModel` in ORM gains `is_partial` mapped column; `_to_domain()` in `PgOHLCVRepository` must map the new field; `bulk_upsert_with_priority()` must include `is_partial` in the upsert values dict; derived upsert method must also include `is_partial`

### 6.5 Domain Model Changes

#### Service/Cache: `ProviderRoutingCache` (S2 — market-ingestion, NEW)
- **Purpose**: In-memory cache of provider routing rules. Populated at startup from `Settings` env vars via `load_from_config()`. Force-reloadable via `POST /internal/v1/routing/reload`. No DB dependency.
- **File**: `services/market-ingestion/src/market_ingestion/application/services/provider_routing_cache.py`
- **Not an entity** — application-layer service; never persisted
- **Internal structure**: `dict[tuple[str, str | None], list[str]]` → `(dataset_type_value, timeframe | None)` → ordered list of provider values (highest weight first)

**Methods**:

| Method | Signature | Behavior |
|--------|-----------|----------|
| `get_providers_for` | `(dataset_type: str, timeframe: str \| None) → list[str]` | Returns provider values sorted by descending weight. Returns `["eodhd"]` as fallback if no rule matches. O(1) dict lookup — no I/O. |
| `primary_for` | `(dataset_type: str, timeframe: str \| None) → str` | Returns the first (highest-weight) provider value. |
| `load_from_config` | `(settings: Settings) → int` | Parses routing env vars, builds the internal dict, sets `loaded_at`. Returns count of entries loaded. No async I/O. |
| `needs_refresh` | `() → bool` | Always `False` — config-backed cache never needs auto-refresh (changes only via force-reload). Kept for interface compatibility. |
| `loaded_at_iso` | `() → str` | ISO timestamp of last `load_from_config()`, or `"never"`. |

**Invariants**:
- Cache is populated before the first routing decision (startup calls `cache.load_from_config(settings)`)
- `get_providers_for()` never performs I/O
- `load_from_config()` is synchronous — no `UnitOfWork` or DB dependency

---

#### Entity: `OHLCVBar` (S3 — market-data, EXTENDED)
- **File**: `services/market-data/src/market_data/domain/entities.py`
- **Existing attributes** (unchanged): `instrument_id, timeframe, bar_date, open, high, low, close, volume, adjusted_close, source, provider_priority, is_derived`
- **New attribute**:

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| is_partial | bool | yes | — | `True` if this bar covers [period_start, current_time) rather than a full period. Only relevant for derived intraday bars. Daily/weekly/monthly bars always have `is_partial=False`. |

- **Default**: `False` (backward-compatible; existing daily/weekly/monthly bars are always complete)
- **Invariants**: `is_partial=True` implies `is_derived=True`. A directly-ingested bar is never partial (the data source provides a closed candle). A bar with `is_partial=True` may be overwritten by a later resample of the same period (same PK: instrument_id, timeframe, bar_date=period_start).

---

#### Port: `ZeroBarTrackerPort` (S2 — market-ingestion, NEW — PLAN-0038 Wave A-5)
> _Already designed in PLAN-0038 §Wave A-5 — included here for completeness_
- **File**: `services/market-ingestion/src/market_ingestion/application/ports/zero_bar_tracker.py`
- **Methods**: `record_zero(provider, symbol, timeframe, dataset_type) → int`, `reset(...)`, `should_failover(streak) → bool`
- `FAILOVER_THRESHOLD: ClassVar[int] = 5`

---

#### Adapter: `AlpacaProviderAdapter` (S2 — market-ingestion, NEW)
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py`
- **Extends**: `BaseProviderAdapter`
- **Provider**: `Provider.ALPACA`

**Supported dataset_type / timeframe combinations**:

| dataset_type | timeframes | EODHD equivalent cost |
|---|---|---|
| OHLCV | 1m, 5m, 15m, 30m, 1h, 4h | — (free) |

**Alpaca API endpoints used**:
- Multi-symbol bars: `GET https://data.alpaca.markets/v2/stocks/bars?symbols={csv}&timeframe={tf}&start={ISO}&end={ISO}&limit=10000&feed=iex&sort=asc`
  - Up to 1000 symbols per request
  - `feed=iex` for free tier (IEX exchange data, ~15-min delayed)
  - Response: `{"bars": {"AAPL": [...], "MSFT": [...]}}`
- Single-symbol bars: same endpoint with one symbol (fallback for per-symbol retries)

**Key attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `_api_key` | `SecretStr` | Alpaca API key from config |
| `_secret_key` | `SecretStr` | Alpaca secret key from config |
| `_base_url` | `str` | Default: `https://data.alpaca.markets` |
| `_client` | `httpx.AsyncClient` | Shared HTTP client |
| `_timeframe_map` | `dict[str, str]` | Maps internal codes to Alpaca API codes: `{"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "4h": "4Hour"}` |

**Methods**:

| Method | Signature | Behavior |
|--------|-----------|----------|
| `provider` | `@property → Provider` | Returns `Provider.ALPACA` |
| `fetch_ohlcv` | `(symbol, timeframe, start, end, exchange) → ProviderFetchResult` | Fetches bars for a single symbol. Constructs URL, calls `_get_bars_for_symbol()`, records API call via `_record_api_call()`. Raises `ProviderUnavailable` on HTTP error. |
| `fetch_intraday` | `(symbol, interval, exchange) → ProviderFetchResult` | Alias for `fetch_ohlcv()` — Alpaca uses the same REST endpoint for both historical and intraday bars. Required because `ExecuteTaskUseCase._fetch()` dispatches intraday timeframes via `fetch_intraday()`. |
| `fetch_ohlcv_batch` | `(symbols: list[str], timeframe, start, end) → dict[str, ProviderFetchResult]` | Multi-symbol batch fetch. Chunks `symbols` into groups of 1000. Returns dict keyed by symbol. Providers that return no bars get `ProviderFetchResult(bars=[], ...)`. |
| `_get_bars_for_symbol` | `(symbol, timeframe, start, end) → list[dict]` | Single-symbol extraction from batch response. |
| `_to_provider_bar` | `(raw: dict) → dict` | Normalizes Alpaca bar dict (`{t, o, h, l, c, v}`) to canonical `{timestamp, open, high, low, close, volume}`. |

**Error classification**:
- HTTP 429 → `ProviderRateLimited` (retryable, Retry-After header respected)
- HTTP 403 → `ProviderUnavailable` (fatal — bad credentials)
- HTTP 422 → `ProviderUnavailable` (fatal — invalid parameters, e.g. unknown symbol)
- HTTP 5xx → `ProviderUnavailable` (retryable after backoff)
- `httpx.TimeoutException` → `ProviderUnavailable` (retryable)

**Config additions** (`market_ingestion/config.py`, prefix `MARKET_INGESTION_`):

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `MARKET_INGESTION_ALPACA_API_KEY` | `SecretStr` | `""` | Alpaca Markets API key (empty = Alpaca disabled) |
| `MARKET_INGESTION_ALPACA_SECRET_KEY` | `SecretStr` | `""` | Alpaca Markets secret key |
| `MARKET_INGESTION_ALPACA_BASE_URL` | `str` | `https://data.alpaca.markets` | Override for testing |
| `MARKET_INGESTION_ALPACA_FEED` | `str` | `iex` | `iex` (free, ~15min delayed) or `sip` (paid, real-time) |

---

#### Adapter: `PolygonProviderAdapter` (S2 — market-ingestion, NEW)
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/polygon.py`
- **Extends**: `BaseProviderAdapter`
- **Provider**: `Provider.POLYGON`

**Supported dataset_type / timeframe combinations**:

| dataset_type | timeframes | Notes |
|---|---|---|
| OHLCV | 1m, 5m, 15m, 30m, 1h, 4h, 1d | Paid account required for > 2-year history |

**Polygon API endpoint used**:
- `GET https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}?adjusted=true&sort=asc&limit=50000&apiKey={key}`
  - `multiplier=1, timespan=minute` for 1m bars
  - `multiplier=5, timespan=minute` for 5m bars
  - `multiplier=1, timespan=hour` for 1h bars
  - Response: `{"results": [{t, o, h, l, c, v, vw, n}]}`

**Rate limit guard**: Free tier = 5 requests/minute. Adapter enforces a `asyncio.Semaphore(5)` + per-minute sliding window to stay under the limit. If rate limit is hit (HTTP 429), adapter raises `ProviderRateLimited`.

**Timeframe mapping**:

| Internal | Polygon multiplier | Polygon timespan |
|---|---|---|
| 1m | 1 | minute |
| 5m | 5 | minute |
| 15m | 15 | minute |
| 30m | 30 | minute |
| 1h | 1 | hour |
| 4h | 4 | hour |
| 1d | 1 | day |

**Key attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `_api_key` | `SecretStr` | Polygon API key from config |
| `_base_url` | `str` | Default: `https://api.polygon.io` |
| `_client` | `httpx.AsyncClient` | Shared HTTP client |
| `_rate_limiter` | `asyncio.Semaphore(5)` | Enforces free-tier rate limit |

**Config additions** (`market_ingestion/config.py`, prefix `MARKET_INGESTION_`):

> Note: `MARKET_INGESTION_POLYGON_API_KEY` already exists in `config.py` as a plain `str`. This wave upgrades it to `SecretStr` and adds `polygon_base_url`.

| Env var | Type | Default | Description |
|---------|------|---------|-------------|
| `MARKET_INGESTION_POLYGON_API_KEY` | `SecretStr` | `""` | Empty string = Polygon disabled (not registered) |
| `MARKET_INGESTION_POLYGON_BASE_URL` | `str` | `https://api.polygon.io` | Override for testing |

---

#### Worker: `PrimaryProviderReclaimWorker` (S2 — market-ingestion, NEW)
- **File**: `services/market-ingestion/src/market_ingestion/infrastructure/workers/reclaim_worker.py`
- **Purpose**: Background worker that runs every 4 hours. Finds completed `ingestion_tasks` where `fetched_by_provider` differs from the current `ProviderRoutingCache.primary_for(dataset_type, timeframe)`, and re-creates new tasks using the primary provider to overwrite the data.
- **Independent process** (R22): launched as a separate `asyncio` loop in its own Kubernetes deployment; does NOT run inside the same process as the task executor.

**Processing loop**:
1. Load `ProviderRoutingCache` (or reuse if already warm)
2. Query `ingestion_tasks WHERE status='SUCCEEDED' AND fetched_by_provider IS NOT NULL`
3. For each row where `fetched_by_provider != routing_cache.primary_for(dataset_type, timeframe)`:
   - Build a new `IngestionTask` with `provider = primary_provider`
   - `dedupe_key` uses today's date (same as incremental scheduler) so same-day reclaim is idempotent
4. Bulk-insert new tasks via `add_many(tasks)` with `ON CONFLICT DO NOTHING`
5. Log `primary_provider_reclaim_complete` with `tasks_reclaimed=N`
6. Sleep 4 hours; repeat

**Attributes**:

| Attribute | Type | Description |
|-----------|------|-------------|
| `_uow` | `UnitOfWork` | DB access |
| `_routing_cache` | `ProviderRoutingCache` | In-memory routing rules |
| `_interval_sec` | `int` | Default: 14400 (4 hours) |
| `_max_reclaim_per_run` | `int` | Default: 5000 (safety cap) |

**Invariants**:
- Never deletes existing data — only re-creates ingestion tasks; S3 upsert conflict resolution determines whether the new data overwrites existing rows (based on `provider_priority`)
- Primary provider bars should have higher `provider_priority` than secondary → new data naturally wins

---

#### Worker: `IntradayResamplingWorker` (S3 — market-data, NEW)
- **File**: `services/market-data/src/market_data/workers/intraday_resampling.py`
- **Purpose**: Consumes `market.dataset.fetched.v1` events for 1m OHLCV bars. For each 1m bar, computes and upserts open-bar derived bars for 5m, 15m, 30m, 1h, 4h timeframes using the `ResampledOHLCVUseCase`.
- **Consumer group**: `market-data-intraday-resampling`
- **Extends**: `BaseKafkaConsumer` (same pattern as existing `OHLCVConsumer`)

**Open-bar resampling semantics**:
- Given bar `b` at timestamp `T` with timeframe `1m`, for target period `P`:
  - `period_start = floor(T, P)` using UTC epoch integer division
  - The derived bar's `bar_date = period_start`
  - Fetch all 1m bars for this instrument in `[period_start, T]` from DB
  - Aggregate: `open = first.open, high = max(highs), low = min(lows), close = b.close, volume = sum(volumes)`
  - `is_partial = (T < period_start + P)` — true if less than a full period has elapsed
  - `is_derived = True`

**Period start computation**:
```python
# UTC epoch seconds floor division
period_start_ts = (bar_ts_utc_epoch // period_seconds) * period_seconds
period_start_dt = datetime.fromtimestamp(period_start_ts, tz=UTC)
```

Where `period_seconds` for each target timeframe:
- 5m = 300
- 15m = 900
- 30m = 1800
- 1h = 3600
- 4h = 14400

**Target timeframes** (derived from 1m):

| Target TF | Period seconds | Derived from |
|---|---|---|
| 5m | 300 | 1m |
| 15m | 900 | 1m |
| 30m | 1800 | 1m |
| 1h | 3600 | 1m |
| 4h | 14400 | 1m |

---

#### Use Case: `ResampledOHLCVUseCase` (S3 — market-data, NEW)
- **File**: `services/market-data/src/market_data/application/use_cases/resample_ohlcv.py`
- **Purpose**: Given a single 1m `OHLCVBar` (the trigger bar), fetches all 1m bars in the current period window from DB, aggregates them into derived bars for each target timeframe, and upserts them.

**Method**: `execute(bar: OHLCVBar, target_timeframes: list[Timeframe]) → list[OHLCVBar]`

1. For each `target_tf` in `target_timeframes`:
   a. Compute `period_start = floor(bar.bar_date, target_tf)`
   b. Fetch all 1m bars for `(instrument_id, "1m")` where `bar_date >= period_start AND bar_date <= bar.bar_date`
   c. Aggregate into one `OHLCVBar(instrument_id, target_tf, bar_date=period_start, ...)`
   d. Set `is_derived=True`
   e. Determine `is_partial`: `is_partial = bar.bar_date < period_end` where `period_end = period_start + timedelta(seconds=period_seconds[target_tf])`
2. Bulk-upsert all derived bars using `bulk_upsert_derived()` (no priority conflict check — derived bars always overwrite derived bars)

**Invariants**:
- Never overwrites a non-derived bar (upsert WHERE is_derived = true OR is_derived IS NULL; if existing row has `is_derived=false`, skip)
- Derived priority = 0 (same as existing `_DERIVED_PRIORITY` in `derive_ohlcv.py`)

### 6.6 Data Flow

#### Flow A: Intraday Ingestion (1m bars from Alpaca)

```
ScheduleDueTasksUseCase (S2 scheduler)
  → creates IngestionTask{provider=ALPACA, dataset_type=OHLCV, timeframe="1m"}
    (routing cache selects ALPACA as primary for ohlcv/1m)

ExecuteTaskUseCase (S2 worker)
  → cache.primary_for("ohlcv", "1m") → Provider.ALPACA
  → AlpacaProviderAdapter.fetch_ohlcv(symbol, "1m", start, end)
    ↳ POST https://data.alpaca.markets/v2/stocks/bars?symbols=AAPL&timeframe=1Min&...
    ↳ returns [{t, o, h, l, c, v}, ...]
  → serialize to JSONL, upload to MinIO (silver bucket)
  → publish market.dataset.fetched.v1 to Kafka
  → task.status = SUCCEEDED, task.fetched_by_provider = "alpaca"

IntradayResamplingWorker (S3 worker)
  ← consumes market.dataset.fetched.v1
  → downloads JSONL from MinIO
  → for each 1m bar:
      ResampledOHLCVUseCase.execute(bar, [5m, 15m, 30m, 1h, 4h])
        → floor(bar_ts, 5m) = 9:10:00 (at 9:13)
        → fetch 1m bars [9:10, 9:13] from DB
        → aggregate → OHLCVBar(timeframe=5m, bar_date=9:10, is_partial=True, is_derived=True)
        → upsert into ohlcv_bars
```

#### Flow B: Zero-Bar Failover (Alpaca → Polygon)

```
ExecuteTaskUseCase
  → fetch from ALPACA → returns 0 bars
  → ZeroBarTracker.record_zero("alpaca", symbol, "1m", "ohlcv") → streak = 5
  → ZeroBarTracker.should_failover(5) → True
  → routing_cache.get_providers_for("ohlcv", "1m") → [ALPACA(100), POLYGON(80)]
  → retry with POLYGON
  → PolygonProviderAdapter.fetch_ohlcv(symbol, "1m", start, end)
  → task.fetched_by_provider = "polygon"
```

#### Flow C: Primary Provider Reclaim

```
PrimaryProviderReclaimWorker (every 4h)
  → query ingestion_tasks WHERE status='SUCCEEDED' AND fetched_by_provider != primary_provider
  → for each: create IngestionTask{provider=primary_provider, ...}
  → add_many() with ON CONFLICT DO NOTHING
  → ExecuteTaskUseCase fetches same date from primary provider
  → S3 upsert: new data has higher provider_priority → overwrites secondary-provider data
```

#### Flow D: Routing Cache Reload

```
Operator: POST /internal/v1/routing/reload
  → RoutingReloadUseCase.execute()
  → cache.load_from_config(settings) → reads ROUTING_* env vars from Settings
  → cache dict rebuilt in memory (synchronous, no DB query)
  → returns {reloaded: true, rules_loaded: 4}
```

### 6.7 Break-Surface Analysis

| Change | Currently Exists | What Will Break | Migration Strategy |
|--------|-----------------|-----------------|-------------------|
| Add `is_partial` to `OHLCVBar` entity | `OHLCVBar` plain `@dataclass` (NOT frozen), 13 fields | All `OHLCVBar(...)` construction calls in tests need `is_partial=False` (or as default — add with `= False`) | Add as `is_partial: bool = False` default; existing tests constructing `OHLCVBar` auto-compatible |
| Replace `_fallback_provider()` call in `ExecuteTaskUseCase` | `_fallback_provider()` at line ~743 returns `None` for intraday (no fallback defined) — Polygon **never reached** under current code | Zero-bar failover silently fails to route to Polygon for intraday tasks | Wave A-4 T-A-4-06: replace `_fallback_provider()` call with `routing_cache.get_providers_for()[1:]` ordered fallback list |
| Add `is_partial` to `OHLCVBarModel` ORM | `OHLCVBarModel` in `ohlcv.py`, no `is_partial` | `_to_domain()` in `PgOHLCVRepository` needs to map it; `bulk_upsert_with_priority()` needs it in upsert dict | Migration 008 with `server_default='false'`; update `_to_domain()` and upsert methods |
| `bulk_upsert_with_priority()` upsert dict | 11 fields in values dict (verified from source) | Tests that assert on column count or upsert SQL shape | Add `"is_partial": bar.is_partial` to values dict in same migration wave |
| Add `ALPACA` to `Provider` enum (S2) | `Provider`: EODHD, ALPHA_VANTAGE, POLYGON, YAHOO_FINANCE, FINNHUB | Tests that enumerate `Provider` members will be unaffected (no exhaustive enum tests) | Add `ALPACA = "alpaca"` — backward-compatible StrEnum extension |
| Add `fetched_by_provider` to `IngestionTaskModel` | `IngestionTaskModel` has no such column | Tests that assert on `IngestionTask` column count; `_to_domain()` mapper | Migration 0010 with `server_default=NULL`; update mapper |
| New consumer group in S3 | S3 has `OHLCVConsumer` group `market-data-ohlcv-consumer` | None — new consumer group is additive | Register in Kafka `create-topics.sh` (or auto-create if enabled) |

---

## 7. Architecture Decisions

### ADR-032-01: REST Polling over WebSocket for Intraday
**Decision**: Use Alpaca REST multi-symbol batch endpoint rather than WebSocket stream for 1m bar ingestion.
**Rationale**: 3000 symbols × 3 requests/minute is well within Alpaca free-tier limits. WebSocket requires connection-pool management across replicas (sticky sessions, re-subscription on reconnect, partition ownership). REST polling integrates naturally with the existing `IngestionTask` scheduler pattern, keeps the system stateless, and is reversible (add WebSocket later as an optimization). The ~1-minute polling lag is acceptable for bar data; real-time quotes already have a separate path.
**Trade-off**: 60-second staleness on 1m bars vs real-time via WebSocket. Acceptable given current product requirements.

### ADR-032-02: Routing via Config (Env Vars) + In-Memory Cache (Not DB Table)
**Decision**: Routing rules are defined as `Settings` fields (pydantic-settings env vars); `ProviderRoutingCache` loads them at startup via `load_from_config(settings)` with a force-reload API.
**Alternatives considered**:
- **DB table (`provider_routing_rules`)**: Allows runtime mutation via SQL without config push. But adds entity + ORM model + repository port + `UnitOfWork` extension + Alembic migration + seed data for ~12 rows that only change when a new provider is onboarded (months timescale). The operational overhead is not justified.
- **Valkey cache**: Adds I/O per task in the hot path; introduces another infrastructure dependency in S2's critical path.
**Chosen**: Env var config-backed in-memory cache. Trade-off: changing routing weights requires a config push + `POST /internal/v1/routing/reload` rather than a SQL UPDATE. Acceptable given the months-timescale change cadence. Eliminates 3–4 implementation tasks and ~150 lines of boilerplate infrastructure code.

### ADR-032-03: Resampling in S3 (Not S2)
**Decision**: `IntradayResamplingWorker` lives in `market-data` (S3), not `market-ingestion` (S2).
**Rationale**: S3 already owns the `ohlcv_bars` table and all OHLCV query logic. Resampling is a read-then-write concern on that table. Placing it in S2 would require S2 to either write directly to `market_data_db` (violating R7: no cross-service DB) or publish additional Kafka events. S3 consumers already handle `market.dataset.fetched.v1` — a second consumer group on the same topic is clean and additive.

### ADR-032-04: Open-Bar Semantics (Partial Bars are Upserted, Not Skipped)
**Decision**: Every incoming 1m bar triggers resampling and upserts the current open bar for all target timeframes, even if the period is not yet complete.
**Rationale**: Queries for intraday charts need the most recent partial bar to show a live candlestick. Skipping until the period closes would leave a gap in the chart for up to 4 hours (for 4h bars). The `is_partial=True` flag lets consumers distinguish open bars from completed bars.

### ADR-032-05: Provider Priority in `ohlcv_bars` Remains as-is
**Decision**: The existing `provider_priority` column on `ohlcv_bars` continues to drive conflict resolution during upsert. Alpaca bars will have higher `provider_priority` than Polygon bars, which will have higher priority than Yahoo bars.
**Rationale**: The conflict-resolution logic (`WHERE EXCLUDED.provider_priority >= ohlcv_bars.provider_priority`) already handles multi-provider writes correctly. No schema change needed.

---

## 8. Security Analysis

| Concern | Mitigation |
|---------|-----------|
| API key exposure in logs | `AlpacaProviderAdapter._sanitize_url_slug()` strips query params (inherits from `BaseProviderAdapter`). API keys passed as HTTP headers (`APCA-API-KEY-ID`, `APCA-API-SECRET-KEY`), never in URL. |
| API key exposure in Polygon URL | Polygon requires `?apiKey=` in URL. `_sanitize_url_slug()` strips query params before logging. Log only path segment. |
| `POST /internal/v1/routing/reload` unauthorized access | `InternalJWTMiddleware` (existing, PRD-0025) validates `X-Internal-JWT` on all `/internal/` routes. |
| Routing config tampering via reload API | `POST /internal/v1/routing/reload` only re-reads current `Settings` (env vars already set at process start); cannot inject new routing values. Protected by `InternalJWTMiddleware`. |
| `fetched_by_provider` injection | Column populated only by `ExecuteTaskUseCase` from `task.provider` (a controlled `Provider` enum value). No user-controlled input path. |
| Polygon rate-limit bypass | `_rate_limiter = asyncio.Semaphore(5)` enforced at adapter level. Even with multiple worker replicas, each replica independently rate-limits; Polygon returns 429 which maps to `ProviderRateLimited` and the circuit breaker. |

---

## 9. Failure Modes

| Failure | Impact | Recovery Strategy |
|---------|--------|-------------------|
| Alpaca API down | 1m bar ingestion stops for affected symbols | `ProviderUnavailable` raised → task retried → after 5 zero-bar strikes, failover to Polygon |
| Polygon API down | Failover unavailable | `ZeroBarTracker` streak increments; circuit breaker (Wave A-5) opens Polygon endpoint; task left in RETRY state until Alpaca recovers |
| `ProviderRoutingCache` not loaded at startup | `get_providers_for()` returns `["eodhd"]` fallback | Startup calls `cache.load_from_config(settings)` synchronously; cannot fail (only reads env vars). Fallback guaranteed even if misconfigured. |
| `ProviderRoutingCache` misconfigured (invalid provider name) | Unknown provider silently skipped; next valid provider used | `load_from_config()` skips unrecognised provider values and logs a warning; at minimum `["eodhd"]` fallback is returned. |
| `IntradayResamplingWorker` crashes | Derived 5m/15m/30m/1h/4h bars stale | Worker is idempotent — on restart, replays recent events and re-upserts all derived bars; no data loss |
| S3 `market_data_db` unavailable during resampling | Worker accumulates Kafka consumer lag | Worker pauses consumption; Kafka retains messages for 7 days (topic retention); resumes on DB recovery |
| `PrimaryProviderReclaimWorker` fails | Missed reclaim cycle | Next run (4h later) picks up the same tasks; idempotent by design |
| `fetched_by_provider` NULL (pre-migration tasks) | Reclaim worker ignores NULL rows | `WHERE fetched_by_provider IS NOT NULL` in worker query; no false positives |
| Alpaca returns partial batch (some symbols missing) | Missing symbols produce 0-bar results | `ZeroBarTracker` catches per-symbol zero runs; failover to Polygon on threshold |
| Routing env var missing or blank | `ProviderRoutingCache.get_providers_for()` returns `["eodhd"]` fallback (hardcoded in `_cache.get()` default) | Fallback guarantees non-empty routing; startup logs a `routing_config_invalid_pair` warning |

---

## 10. Scalability

| Concern | Numbers | Mitigation |
|---------|---------|-----------|
| Alpaca batch requests | 3000 symbols ÷ 1000/request = 3 requests per poll cycle; at 1m interval = 3 req/min | Well within Alpaca free-tier (5 req/s for data API) |
| Resampling write throughput | 3000 symbols × 5 derived timeframes × 1 upsert/min = 15,000 upserts/min | Batch via `bulk_upsert_derived()` — one INSERT per (instrument, timeframe) group per 1m event; TimescaleDB handles this volume |
| Routing config size | ~4 env var entries (~12 rules) | Trivially small; fully fits in L1 cache as in-memory dict; loaded once at startup |
| Reclaim worker query | `ingestion_tasks` scanned for `status=SUCCEEDED` with new index on `(status, provider, fetched_by_provider)` | Index on `fetched_by_provider` limits scan to tasks where secondary provider was used |
| TimescaleDB `ohlcv_bars` partition pressure | New intraday timeframes add up to 5× the row count vs daily-only | TimescaleDB hypertable already partitions on `bar_date` — intraday chunks are smaller in time range but same partition strategy; no schema change needed |

---

## 11. Test Strategy

### Unit Tests (S2 — market-ingestion)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_alpaca_adapter_fetch_ohlcv_success` | `fetch_ohlcv()` parses Alpaca response correctly; returns `ProviderFetchResult` with correct bar count | P0 |
| `test_alpaca_adapter_fetch_ohlcv_zero_bars` | Returns empty `ProviderFetchResult` (not raises) when API returns empty `bars` dict | P0 |
| `test_alpaca_adapter_rate_limited_429` | Raises `ProviderRateLimited` on HTTP 429 | P0 |
| `test_alpaca_adapter_bad_credentials_403` | Raises `ProviderUnavailable` on HTTP 403 | P0 |
| `test_alpaca_adapter_batch_chunks_1000_symbols` | `fetch_ohlcv_batch(1001 symbols, ...)` makes exactly 2 HTTP calls | P0 |
| `test_alpaca_adapter_timeframe_mapping` | All 6 internal timeframes map to correct Alpaca codes | P1 |
| `test_alpaca_adapter_key_not_in_url` | `_record_api_call()` receives a URL slug with no `apiKey` substring | P0 |
| `test_polygon_adapter_fetch_ohlcv_success` | Parses `v2/aggs` response; returns correct bars | P0 |
| `test_polygon_adapter_rate_limit_enforced` | With `Semaphore(5)`, 6th concurrent call waits | P0 |
| `test_polygon_adapter_timeframe_to_params` | Each internal timeframe maps to correct `(multiplier, timespan)` tuple | P1 |
| `test_polygon_adapter_key_not_in_url` | Same as Alpaca test | P0 |
| `test_provider_routing_cache_primary_for` | Returns highest-weight provider for slot | P0 |
| `test_provider_routing_cache_fallback_eodhd` | Missing slot → returns `["eodhd"]` | P0 |
| `test_provider_routing_cache_load_from_config` | `load_from_config()` parses ROUTING_* env vars correctly; ohlcv intraday → alpaca first | P0 |
| `test_provider_routing_cache_load_from_config_invalid_provider` | Unknown provider value in env var silently skipped | P1 |
| `test_provider_routing_cache_load_from_config_resets_stale` | Second `load_from_config()` call replaces previous entries | P0 |
| `test_reclaim_worker_identifies_secondary_tasks` | Worker identifies tasks where `fetched_by_provider != primary_provider` | P0 |
| `test_reclaim_worker_creates_primary_tasks` | Worker creates new `IngestionTask` for each mismatch | P0 |
| `test_reclaim_worker_idempotent_dedupe` | Re-running after tasks already created → `add_many` inserts 0 (ON CONFLICT DO NOTHING) | P0 |
| `test_reclaim_worker_skips_null_fetched_by` | `fetched_by_provider=NULL` rows not reclaimed | P0 |
| `test_reclaim_worker_max_cap` | At 6000 mismatches, only 5000 tasks created (max cap respected) | P1 |

### Unit Tests (S3 — market-data)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_resample_ohlcv_5m_open_bar_9_13` | At 9:13, 5m bar covers 9:10–9:13; `period_start=9:10`, `is_partial=True` | P0 |
| `test_resample_ohlcv_5m_closed_bar_9_15` | At 9:15:00, `is_partial=False` for 5m bar ending 9:15 | P0 |
| `test_resample_ohlcv_1h_open_bar_9_13` | At 9:13, 1h bar covers 9:00–9:13; `period_start=9:00`, `is_partial=True` | P0 |
| `test_resample_ohlcv_aggregation_ohlcv` | open=first bar's open, high=max, low=min, close=last bar's close, volume=sum | P0 |
| `test_resample_ohlcv_single_bar_group` | Single 1m bar in period → derived bar has same OHLCV as source bar | P1 |
| `test_resample_ohlcv_all_timeframes` | `execute(bar, [5m, 15m, 30m, 1h, 4h])` returns 5 derived bars | P0 |
| `test_resample_ohlcv_is_derived_true` | All returned bars have `is_derived=True` | P0 |
| `test_resample_ohlcv_does_not_overwrite_non_derived` | If existing bar has `is_derived=False`, upsert is skipped | P0 |
| `test_ohlcv_bar_entity_is_partial_default_false` | `OHLCVBar()` has `is_partial=False` by default | P0 |
| `test_ohlcv_bar_partial_implies_derived` | Invariant: `is_partial=True, is_derived=False` raises `ValueError` | P0 |
| `test_period_start_floor_5m` | `floor(9:13, 300s) == 9:10:00 UTC` | P0 |
| `test_period_start_floor_1h` | `floor(9:13, 3600s) == 9:00:00 UTC` | P0 |
| `test_period_start_floor_4h` | `floor(09:13, 14400s) == 08:00:00 UTC` | P0 |

### Integration Tests

| Test | What It Verifies | Service |
|------|-----------------|---------|
| `test_routing_cache_load_from_settings` | `ProviderRoutingCache.load_from_config()` with real `Settings` returns correct ordered providers | S2 |
| `test_intraday_resampling_worker_event_to_db` | Worker consumes a mock `market.dataset.fetched.v1` event, upserts derived bars | S3 |
| `test_migration_008_is_partial_column` | After migration 008, `ohlcv_bars` has `is_partial` column with default `false` | S3 |
| `test_migration_0010_fetched_by_provider_column` | After migration 0010, `ingestion_tasks` has `fetched_by_provider` column | S2 |

### DDL Alignment Tests

| Test | What It Verifies | File |
|------|-----------------|------|
| `TestOHLCVBarsDDLAlignment` | ORM model columns match DB schema (add `is_partial` check) | S3 tests |
| `TestIngestionTasksDDLAlignment` | ORM model columns match DB schema (add `fetched_by_provider` check) | S2 tests |

---

## 12. Migration Plan

### S2 Migration 0010 (`add_fetched_by_provider`)
- **Current head**: 0009
- **Alters**: `ingestion_tasks` — adds `fetched_by_provider VARCHAR(50) NULL` + partial index `ix_ingestion_tasks_reclaim ON ingestion_tasks (status, fetched_by_provider) WHERE status = 'succeeded' AND fetched_by_provider IS NOT NULL`
- **No table creation**: `provider_routing_rules` table eliminated (routing defined via env vars — see §6.4)
- **server_default**: NULL — all existing completed tasks remain NULL (treated as "unknown provider" by reclaim worker)
- **Rollback**: `DROP INDEX ix_ingestion_tasks_reclaim; ALTER TABLE ingestion_tasks DROP COLUMN fetched_by_provider`
- **Zero-downtime**: Additive column addition; existing tasks/rows unaffected

### S3 Migration 008 (`add_ohlcv_is_partial`)
- **Current head**: 007
- **Alters**: `ohlcv_bars` — adds `is_partial BOOLEAN NOT NULL DEFAULT false`
- **server_default**: `false` — all existing rows (daily/weekly/monthly) are complete bars
- **Rollback**: drop column `is_partial` from `ohlcv_bars`
- **Zero-downtime**: Column addition with server_default; no table rewrite needed

---

## 13. Observability

All observability follows the existing `BaseProviderAdapter._record_api_call()` pattern.

### New Structured Log Events (S2)

| Event | Level | Fields |
|-------|-------|--------|
| `provider_routing_cache_loaded` | INFO | `rules_count, loaded_at, elapsed_ms` |
| `provider_routing_cache_reload_forced` | INFO | `rules_count, triggered_by` |
| `provider_routing_selected` | DEBUG | `dataset_type, timeframe, provider, weight` |
| `primary_provider_reclaim_start` | INFO | `run_id` |
| `primary_provider_reclaim_complete` | INFO | `tasks_reclaimed, run_duration_ms` |

### New Structured Log Events (S3)

| Event | Level | Fields |
|-------|-------|--------|
| `intraday_resampling_bar_processed` | DEBUG | `instrument_id, source_timeframe, derived_count, is_partial_count` |
| `intraday_resampling_period_complete` | INFO | `instrument_id, timeframe, period_start, bar_count_used` |

### Loki Labels (extends PLAN-0038 observability)

All new events carry `provider`, `dataset_type`, `timeframe` labels for Loki routing.

---

## 14. Open Questions

| ID | Question | Classification | Status |
|----|----------|---------------|--------|
| OQ-001 | Does Alpaca IEX feed provide bars for all NYSE/NASDAQ symbols, including low-volume tickers? Some small-caps may not be traded on IEX. | DEFERRED | Unresolved — treat missing symbols as zero-bar events (ZeroBarTracker fires → Polygon fallback) |
| OQ-002 | Should 5m, 15m, 30m bars be directly fetched from Alpaca (it supports them natively) rather than derived from 1m resampling? | DEFERRED | Deferring to Phase 2 optimization; resampling from 1m is more general and reduces API calls |
| OQ-003 | For Polygon free tier (5 req/min), is single-ticker REST polling viable as a real failover at 3000 symbols? At 5 req/min it takes 10 hours to poll 3000 symbols. | ACKNOWLEDGED | Polygon is a **targeted failover**, not a full-coverage provider on free tier. On free tier, it serves as a per-symbol probe when Alpaca fails for that symbol specifically (not a full 3000-symbol sweep). Polygon paid tier ($29/mo) resolves this. |
| OQ-004 | Should `PrimaryProviderReclaimWorker` also support bulk historical range re-ingestion (e.g. reclaim last 30 days), or just incremental? | DEFERRED | MVP: incremental only (today's day window, same dedupe_key semantics as scheduler). Bulk range deferred to FR-D-05. |

---

## 15. Estimation

### S2 — market-ingestion

| Wave | Description | Estimated Effort |
|------|-------------|-----------------|
| A | `ALPACA` enum value + `AlpacaProviderAdapter` + `PolygonProviderAdapter` + config | 90 min |
| B | Migration 0010 (`fetched_by_provider` column only) + `IngestionTask` entity extension | 30 min |
| C | `ProviderRoutingCache` service + `POST /internal/v1/routing/reload` + `GET /internal/v1/routing/rules` | 60 min |
| D | Wire routing cache into `ExecuteTaskUseCase`; fix `_fallback_provider()` + `_fetch()` dispatch; populate `fetched_by_provider` on SUCCEEDED | 60 min |
| E | `PrimaryProviderReclaimWorker` + Docker/process wiring | 60 min |
| F | Unit + integration tests | 60 min |

**S2 Total**: ~5.75 hours (config-based routing eliminates ~30 min of DB entity/repo work; _fallback_provider fix adds ~15 min)

### S3 — market-data

| Wave | Description | Estimated Effort |
|------|-------------|-----------------|
| A | `is_partial` field on `OHLCVBar` entity + ORM + migration 008 | 30 min |
| B | `ResampledOHLCVUseCase` with period-floor logic and open-bar aggregation | 60 min |
| C | `IntradayResamplingWorker` (Kafka consumer, deduplication, wiring) | 60 min |
| D | Unit + integration tests | 60 min |

**S3 Total**: ~3.5 hours

**Grand Total**: ~9.75 hours across 2 services, 10 implementation waves
