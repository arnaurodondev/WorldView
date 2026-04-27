---
id: PLAN-0040
title: Multi-Provider OHLCV Routing and Intraday Resampling
prd: PRD-0032
status: completed
created: 2026-04-25
updated: 2026-04-26
services: [market-ingestion, market-data]
waves: 10
---

# PLAN-0040 — Multi-Provider OHLCV Routing and Intraday Resampling

## Overview

Implements PRD-0032: Alpaca + Polygon intraday provider adapters, a config-backed dynamic routing cache (env vars, no DB table), zero-bar failover with Polygon, primary provider reclaim worker, and intraday resampling (1m → 5m/15m/30m/1h/4h) with open-bar semantics.

**Two service plans**:
- **Plan A: market-ingestion (S2)** — adapters, routing infrastructure, reclaim worker (6 waves)
- **Plan B: market-data (S3)** — `is_partial`, resampling worker and use case (4 waves)

## Prerequisites (Blocking)

**PLAN-0038 Waves A-4 and A-5 must be completed before starting Plan A Wave A-4.**

- **PLAN-0038 Wave A-5**: Provides `ZeroBarTrackerPort` + `ValkeyZeroBarTracker` which PRD-0032 Plan A Wave A-4 wires into `ExecuteTaskUseCase`
- **PLAN-0038 Wave A-4**: Adds `_preferred_provider()` static routing — **this code will be superseded** by Plan A Wave A-4's `ProviderRoutingCache`. The implementing agent for Wave A-4 MUST remove the `_preferred_provider()` function and replace its call site with the cache lookup

Waves A-1, A-2, A-3 and all Plan B waves are independent of PLAN-0038 and can begin immediately.

## Dependency Graph

```
Plan A (S2):
  A-1 (domain + schema — no ProviderRoutingRule entity; migration 0010 = fetched_by_provider only)
    ├─→ A-2 (adapters — AlpacaProviderAdapter incl. fetch_intraday alias)
    └─→ A-3 (routing cache from config + registry wiring; no DB repository)
               ↓
  A-4 (ExecuteTask wiring + fix _fallback_provider)  ← PLAN-0038 A-4+A-5 done
               ↓
  A-5 (PrimaryProviderReclaimWorker)
               ↓
  A-6 (integration tests + docs)

Plan B (S3):
  B-1 (OHLCVBar is_partial + migration)
               ↓
  B-2 (ResampledOHLCVUseCase)
               ↓
  B-3 (IntradayResamplingWorker)
               ↓
  B-4 (integration tests + docs)

Plan A and Plan B are independent of each other — can run in parallel.
```

## Codebase State Verification

| PRD Reference | Type | Service | Actual State (from code) | PRD Expected State | Delta |
|---|---|---|---|---|---|
| `Provider` enum | StrEnum | S2 | `EODHD, ALPHA_VANTAGE, POLYGON, YAHOO_FINANCE, FINNHUB` | Add `ALPACA` | Add `ALPACA = "alpaca"` |
| `OHLCVBar.is_partial` | entity field | S3 | Not present | `is_partial: bool = False` | Add field |
| `OHLCVBarModel.is_partial` | ORM col | S3 | Not present | `is_partial BOOLEAN NOT NULL DEFAULT false` | Migration 008 + ORM |
| `PgOHLCVRepository._to_domain()` | method | S3 | 12 fields, no `is_partial` | Map `is_partial=bool(row.is_partial)` | Update mapper |
| `bulk_upsert_with_priority()` | method | S3 | 11 fields (verified), no `is_partial` | Add `is_partial` | Update upsert |
| `bulk_upsert_derived()` | method | S3 | No `is_partial` field | Add `is_partial` to values + ON CONFLICT SET | Update upsert |
| `ingestion_tasks.fetched_by_provider` | DB col | S2 | Does not exist | `VARCHAR(50) NULL` | Migration 0010 (only change) |
| `IngestionTask.fetched_by_provider` | entity field | S2 | Does not exist | `fetched_by_provider: str \| None = None` | Add field |
| `IngestionTaskModel.fetched_by_provider` | ORM col | S2 | Does not exist | `Mapped[str \| None]` nullable | Update model |
| `AlpacaProviderAdapter` | class | S2 | Does not exist | New class extending `BaseProviderAdapter` (with `fetch_intraday()` alias) | Create |
| `PolygonProviderAdapter` | class | S2 | Stub only (raises ProviderUnavailable) | Real implementation | Implement |
| `ProviderRoutingCache` service | class | S2 | Does not exist | New application service (config-backed, no DB) | Create |
| `ExecuteTaskUseCase._fallback_provider()` | function | S2 | Returns `None` for intraday (Polygon never reached) | Route via `routing_cache.get_providers_for()[1:]` | Fix in Wave A-4 T-A-4-06 |
| `POST /internal/v1/routing/reload` | endpoint | S2 | Does not exist | New internal route | Create |
| `GET /internal/v1/routing/rules` | endpoint | S2 | Does not exist | New internal route | Create |
| `PrimaryProviderReclaimWorker` | class | S2 | Does not exist | New worker process | Create |
| `IntradayResamplingWorker` | class | S3 | Does not exist | New Kafka consumer | Create |
| `ResampledOHLCVUseCase` | class | S3 | Does not exist | New use case | Create |
| `OHLCVRepository.find_by_datetime_range()` | port method | S3 | Only `find_by_instrument_timeframe_range(date, date)` | Add datetime-precision variant | Add port method |
| S2 migration head | alembic | S2 | `0009_cadence_reduction_seeds.py` | 0010 | Create migration |
| S3 migration head | alembic | S3 | `007_add_ohlcv_is_derived.py` | 008 | Create migration |

---

# Plan A: market-ingestion (S2)

## Wave A-1: Domain + Schema Foundations ✅

**Goal**: Add `ALPACA` provider enum value, extend `IngestionTask` with `fetched_by_provider`, and create migration 0010 (only `fetched_by_provider` column — no `provider_routing_rules` table).
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: domain + schema

### Pre-read (agent must read before starting)
- `services/market-ingestion/src/market_ingestion/domain/enums.py`
- `services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py`
- `services/market-ingestion/alembic/versions/0009_cadence_reduction_seeds.py` (current head)

### Tasks

#### T-A-1-01: Add `ALPACA` to `Provider` enum

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-01, T-A-2-02]
**Target files**: `services/market-ingestion/src/market_ingestion/domain/enums.py`

**What to build**: Add `ALPACA = "alpaca"` to the `Provider` StrEnum after `FINNHUB`. No other changes.

**Acceptance criteria**:
- [ ] `Provider.ALPACA.value == "alpaca"`
- [ ] Existing enum values unchanged
- [ ] mypy passes

---

#### T-A-1-02: Extend `IngestionTask` entity + ORM with `fetched_by_provider`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03, T-A-4-03]
**Target files**:
- `services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py` (update `_to_domain()`)

**What to build**: Add `fetched_by_provider: str | None = None` to `IngestionTask` domain entity (after `result_ref` field). Add corresponding ORM column to `IngestionTaskModel`. Update `_to_domain()` in the task repository to map the new field.

**Entity addition**:
```python
# In IngestionTask dataclass, after result_ref:
fetched_by_provider: str | None = None
# Populated when task transitions to SUCCEEDED; records which provider actually fetched the data
```

**ORM column** (in `IngestionTaskModel`):
```python
# After result_ref_* columns:
fetched_by_provider: Mapped[str | None] = mapped_column(
    String(50), nullable=True
    # server_default=None — forward-compatible; historical tasks remain NULL
)
```

**Repository `_to_domain()` update**: Add `fetched_by_provider=row.fetched_by_provider` to the `IngestionTask(...)` constructor call.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_ingestion_task_fetched_by_provider_default_none` | Default is `None` | unit |
| `test_ingestion_task_to_domain_maps_fetched_by` | Repository mapper includes `fetched_by_provider` | unit |

**Downstream test impact**:
- Any test constructing `IngestionTask(...)` with positional args may break → verify all use keyword args (they should already)
- Tests asserting column count on `IngestionTaskModel` → update expected count

**Acceptance criteria**:
- [ ] `IngestionTask.fetched_by_provider: str | None = None`
- [ ] ORM model has `fetched_by_provider` column nullable
- [ ] `_to_domain()` maps the column
- [ ] mypy passes

---

#### T-A-1-03: Migration 0010 — `fetched_by_provider` column only

**Type**: schema
**depends_on**: [T-A-1-02]
**blocks**: none
**Target files**: `services/market-ingestion/alembic/versions/0010_add_fetched_by_provider.py` (NEW)

> **Architecture decision (ADR-032-02)**: `provider_routing_rules` DB table eliminated. Routing is defined via `Settings` env vars. This migration only adds the `fetched_by_provider` column.

**What to build**: Alembic migration with `upgrade()` that:
1. Adds `fetched_by_provider VARCHAR(50) NULL` to `ingestion_tasks`
2. Creates partial index for the reclaim worker

**Column addition** (`ingestion_tasks`):
```sql
ALTER TABLE ingestion_tasks ADD COLUMN fetched_by_provider VARCHAR(50);
CREATE INDEX ix_ingestion_tasks_reclaim
    ON ingestion_tasks (status, fetched_by_provider)
    WHERE status = 'succeeded' AND fetched_by_provider IS NOT NULL;
```

**`downgrade()`**: `DROP INDEX ix_ingestion_tasks_reclaim; ALTER TABLE ingestion_tasks DROP COLUMN fetched_by_provider;`

**`revision`**: `"0010"`, `down_revision = "0009"`, `branch_labels = None`, `depends_on = None`

**Downstream test impact**:
- `services/market-ingestion/tests/integration/test_migrations.py` (if exists) → add test for 0010 head
- `TestIngestionTasksDDLAlignment` — update expected column count

**Acceptance criteria**:
- [ ] Migration runs `alembic upgrade 0010` without error
- [ ] `ingestion_tasks` gains `fetched_by_provider` column (nullable, no server_default needed)
- [ ] Partial index created
- [ ] `downgrade()` reverts cleanly
- [ ] No `provider_routing_rules` table created (config-based routing — see ADR-032-02)

### Validation Gate
- [ ] `ruff check` passes on all changed files
- [ ] `mypy` passes on `market-ingestion` package
- [ ] Minimum 2 new unit tests pass (`fetched_by_provider` default + mapper)
- [ ] `alembic upgrade head` runs without error (0010 only adds column + index)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-ingestion/tests/unit/entities/test_ingestion_task.py` | `IngestionTask` gains new field | Add `fetched_by_provider=None` assertion (should auto-pass with default) |
| DDL alignment tests (if they check `ingestion_tasks` column count) | New column added | Update expected column count by 1 |
| `services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py` | `_to_domain()` must map new field | Updated in T-A-1-02 |

### Regression Guardrails
- **BP-007 (Missing migration for ORM changes)**: `IngestionTaskModel` gains `fetched_by_provider` in T-A-1-02 — migration 0010 must be created in the same wave. Do not commit the ORM change without the migration.
- **BP-019 (Missing server_default for NOT NULL column)**: `fetched_by_provider` is nullable — no server_default required.

---

## Wave A-2: Alpaca + Polygon Provider Adapters ✅

**Goal**: Implement real `AlpacaProviderAdapter` and `PolygonProviderAdapter` extending `BaseProviderAdapter`.
**Depends on**: Wave A-1 (for `Provider.ALPACA` enum value)
**Estimated effort**: 60–75 min
**Architecture layer**: infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/base.py`
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/yahoo.py` (pattern for executor-based adapter)
- `services/market-ingestion/src/market_ingestion/application/ports/adapters.py` (`ProviderAdapter` ABC, `ProviderFetchResult`)
- `services/market-ingestion/src/market_ingestion/domain/errors.py` (error hierarchy)
- `services/market-ingestion/src/market_ingestion/config.py` (pydantic-settings pattern)

### Tasks

#### T-A-2-01: `AlpacaProviderAdapter`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-3-03]
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/alpaca.py` (NEW)
- `services/market-ingestion/src/market_ingestion/config.py`

**What to build**: A concrete `BaseProviderAdapter` for Alpaca REST multi-symbol bars API (PRD §6.5).

**Class skeleton**:
```python
class AlpacaProviderAdapter(BaseProviderAdapter):
    """Alpaca Markets REST adapter for intraday OHLCV bars.

    Uses the multi-symbol batch endpoint (up to 1000 symbols per request).
    API keys are passed as HTTP headers — never in the URL — to prevent
    credential leakage in logs (BP-025).
    """

    _BATCH_SIZE: ClassVar[int] = 1000
    _TIMEFRAME_MAP: ClassVar[dict[str, str]] = {
        "1m": "1Min", "5m": "5Min", "15m": "15Min",
        "30m": "30Min", "1h": "1Hour", "4h": "4Hour",
    }

    def __init__(
        self,
        api_key: SecretStr,
        secret_key: SecretStr,
        client: httpx.AsyncClient,
        base_url: str = "https://data.alpaca.markets",
        feed: str = "iex",
    ) -> None: ...

    @property
    def provider(self) -> Provider:
        return Provider.ALPACA
```

**`fetch_ohlcv(symbol, timeframe, start, end, exchange=None) → ProviderFetchResult`**:
- Builds URL: `{base_url}/v2/stocks/bars?symbols={symbol}&timeframe={tf_map[timeframe]}&start={start.isoformat()}&end={end.isoformat()}&limit=10000&feed={feed}&sort=asc`
- Passes API keys as headers: `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`
- Returns `ProviderFetchResult(raw_data=json.dumps(bars_list).encode(), bars_returned=len(bars_list), ...)`
- Calls `self._record_api_call(dataset_type="ohlcv", symbol=symbol, timeframe=timeframe, bars_returned=..., latency_ms=..., credit_cost=0)` after success
- Error mapping: 429 → `ProviderRateLimited`, 403 → `ProviderUnavailable` (fatal), 422 → `ProviderUnavailable` (fatal), 5xx → `ProviderUnavailable` (retryable)
- `self._record_rate_limited()` on 429; `self._record_error()` on 5xx

**`fetch_ohlcv_batch(symbols, timeframe, start, end) → dict[str, ProviderFetchResult]`**:
- Chunks symbols into groups of `_BATCH_SIZE` (1000)
- For each chunk: builds `symbols=AAPL,MSFT,...` CSV query param
- Response: `{"bars": {"AAPL": [{t,o,h,l,c,v}, ...], ...}}`
- Returns dict keyed by symbol; symbols with no bars get `ProviderFetchResult(bars_returned=0, raw_data=b"[]", ...)`
- URL sanitized (no API key): use `self._sanitize_url_slug(url)` for log events

**`_to_provider_bars(raw: dict) → list[dict]`**: Normalizes Alpaca bar dict `{t, o, h, l, c, v}` to `{timestamp, open, high, low, close, volume}`. Timestamp: `bar["t"]` (ISO8601).

**`fetch_intraday(symbol, interval, exchange=None) → ProviderFetchResult`**: Alias for `fetch_ohlcv()` — Alpaca uses the same REST endpoint for both intraday and historical bars. This method is required because `ExecuteTaskUseCase._fetch()` dispatches intraday timeframes via `fetch_intraday()`. Also extend the intraday dispatch set in `_fetch()` to include `"15m"`, `"30m"`, `"4h"` (currently only `{"1m", "5m", "1h"}` — see execute_task.py lines ~382–396).

**`fetch_quotes` and `fetch_fundamentals`**: Raise `ProviderUnavailable("Alpaca does not provide quotes/fundamentals; use EODHD")`.

**Config additions** (to `services/market-ingestion/src/market_ingestion/config.py`, env prefix `MARKET_INGESTION_`):
```python
alpaca_api_key: SecretStr = SecretStr("")    # noqa: S106 — empty = Alpaca disabled
alpaca_secret_key: SecretStr = SecretStr("") # noqa: S106
alpaca_base_url: str = "https://data.alpaca.markets"
alpaca_feed: str = "iex"  # "iex" (free, ~15min delayed) | "sip" (paid, real-time)
# Routing weights (PRD §6.4, ADR-032-02): comma-separated provider:weight pairs
routing_ohlcv_intraday: str = "alpaca:100,polygon:80"    # timeframes: 1m,5m,15m,30m,1h,4h
routing_ohlcv_eod: str = "yahoo_finance:100,eodhd:80"    # timeframes: 1d,1w,1M
routing_quotes: str = "eodhd:100"
routing_fundamentals: str = "eodhd:100"
```

**Tests to write** (inline with T-A-2-03):
Refer to PRD §11 tests for Alpaca adapter.

**Acceptance criteria**:
- [ ] `AlpacaProviderAdapter` extends `BaseProviderAdapter`
- [ ] `fetch_ohlcv` maps all 6 timeframes via `_TIMEFRAME_MAP`
- [ ] `fetch_ohlcv_batch` chunks at 1000 symbols
- [ ] API keys passed as headers, NEVER in URL or log fields
- [ ] `_record_api_call(credit_cost=0)` called on every success
- [ ] mypy passes with `SecretStr` properly typed

---

#### T-A-2-02: `PolygonProviderAdapter` (real implementation)

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-3-03]
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/polygon.py`
- `services/market-ingestion/src/market_ingestion/config.py`

**What to build**: Replace the stub with a real implementation extending `BaseProviderAdapter`. Single-ticker aggregate endpoint (PRD §6.5). Enforces 5-req/min free-tier rate limit via `asyncio.Semaphore(5)`.

**Timeframe mapping** (Polygon multiplier, timespan):

| Internal | multiplier | timespan |
|---|---|---|
| 1m | 1 | minute |
| 5m | 5 | minute |
| 15m | 15 | minute |
| 30m | 30 | minute |
| 1h | 1 | hour |
| 4h | 4 | hour |
| 1d | 1 | day |

**Endpoint**: `GET {base_url}/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{from}/{to}?adjusted=true&sort=asc&limit=50000&apiKey={key}`

**Rate limiter**: `_rate_limiter: asyncio.Semaphore = asyncio.Semaphore(5)` — acquire before each request, release after. On 429 → `ProviderRateLimited`. On 403 → `ProviderUnavailable` (fatal). On 5xx → `ProviderUnavailable` (retryable).

**Security**: Polygon requires `?apiKey=` in URL. Use `self._sanitize_url_slug(url)` to strip query params for logging (strips `apiKey` from log). Never log the raw URL with query params.

**Response parse**: `data["results"]` list of `{t, o, h, l, c, v, vw, n}` → normalize to `{timestamp: t/1000 as ISO, open: o, high: h, low: l, close: c, volume: v}`.

**Config additions** (upgrade existing `polygon_api_key: str = ""` to `SecretStr`):
```python
# Upgrade existing str to SecretStr (breaking change — see acceptance criteria):
polygon_api_key: SecretStr = SecretStr("")   # noqa: S106 — empty = Polygon disabled
polygon_base_url: str = "https://api.polygon.io"  # NEW
```
> **Note**: `polygon_api_key` already exists in `config.py` as a plain `str`. This task upgrades it to `SecretStr` and adds `polygon_base_url`. Callers that use `.polygon_api_key` directly must be updated to call `.get_secret_value()`.

**Acceptance criteria**:
- [ ] Extends `BaseProviderAdapter`
- [ ] `asyncio.Semaphore(5)` rate limiter enforced
- [ ] All 7 timeframes mapped correctly
- [ ] `apiKey` never appears in any log field
- [ ] `_record_api_call(credit_cost=0)` called on success
- [ ] mypy passes

---

#### T-A-2-03: Unit tests — Alpaca adapter

**Type**: test
**depends_on**: [T-A-2-01]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/adapters/test_alpaca_adapter.py` (NEW)

**Tests to write** (all P0/P1 from PRD §11):

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_fetch_ohlcv_success` | Parses Alpaca response; returns `ProviderFetchResult` with correct bar count | unit |
| `test_fetch_ohlcv_zero_bars` | Empty `bars` dict → returns result with `bars_returned=0`, does NOT raise | unit |
| `test_fetch_ohlcv_rate_limited_429` | HTTP 429 → raises `ProviderRateLimited` | unit |
| `test_fetch_ohlcv_bad_credentials_403` | HTTP 403 → raises `ProviderUnavailable` | unit |
| `test_fetch_ohlcv_batch_chunks_1001_symbols` | 1001 symbols → exactly 2 HTTP calls | unit |
| `test_fetch_ohlcv_timeframe_mapping` | All 6 timeframes map to correct Alpaca codes | unit |
| `test_api_key_not_in_url` | URL slug passed to `_record_api_call()` contains no `apiKey` substring | unit |
| `test_provider_api_call_credit_cost_zero` | `credit_cost=0` in log event | unit |

- Minimum: 8 unit tests, all `pytest.mark.unit`
- Use `pytest-httpx` for HTTP mocking; `structlog.testing.capture_logs()` for event assertions

**Acceptance criteria**:
- [ ] 8 tests pass
- [ ] ruff + mypy pass

---

#### T-A-2-04: Unit tests — Polygon adapter

**Type**: test
**depends_on**: [T-A-2-02]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/adapters/test_polygon_adapter.py` (NEW)

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_fetch_ohlcv_success` | Parses `v2/aggs` response; returns correct bars | unit |
| `test_rate_limit_semaphore_enforced` | Semaphore(5): 6th concurrent call waits | unit |
| `test_timeframe_to_params` | Each timeframe maps to correct `(multiplier, timespan)` | unit |
| `test_api_key_not_in_log` | `_sanitize_url_slug` strips `?apiKey=` from logged URL | unit |
| `test_429_raises_provider_rate_limited` | HTTP 429 → `ProviderRateLimited` | unit |
| `test_polygon_disabled_when_key_empty` | `polygon_api_key=""` → adapter not registered | unit |

- Minimum: 6 unit tests

**Acceptance criteria**:
- [ ] 6 tests pass
- [ ] ruff + mypy pass

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes on `market-ingestion`
- [ ] 14 new unit tests pass (A-2-03 + A-2-04)
- [ ] No API key appears in any log field in tests

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-ingestion/tests/unit/adapters/test_polygon_adapter.py` (existing stub test) | Stub now replaced with real impl | Replace stub assertions with real implementation tests |

### Regression Guardrails
- **BP-025 (API credential leakage)**: Both adapters pass keys as HTTP headers (Alpaca) or URL query params (Polygon). URL query params MUST be stripped via `_sanitize_url_slug()` before any logging. Test explicitly verifies no `apiKey` substring in logged URLs.
- **BP-023 (ruff format divergence)**: Run `ruff format` on all modified `.py` files before committing.

---

## Wave A-3: ProviderRoutingCache + Registry Wiring ✅

**Goal**: Config-backed `ProviderRoutingCache` service (no DB/ORM), register Alpaca + Polygon in provider registry.
**Depends on**: Wave A-1 (for `MARKET_INGESTION_ROUTING_*` config additions in T-A-2-01) and Wave A-2 (adapters)
**Estimated effort**: 30–45 min
**Architecture layer**: application + infrastructure

### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/__init__.py`
- `services/market-ingestion/src/market_ingestion/config.py` (pydantic-settings pattern for new routing fields)
- `services/market-ingestion/src/market_ingestion/infrastructure/adapters/circuit_breaker.py` (Valkey-backed port pattern — for conditional registration pattern)

### Tasks

#### T-A-3-01: `ProviderRoutingCache` application service

**Type**: impl
**depends_on**: none (within this wave)
**blocks**: [T-A-4-02]
**Target files**: `services/market-ingestion/src/market_ingestion/application/services/provider_routing_cache.py` (NEW)

> **Architecture note (ADR-032-02)**: T-A-3-01 (ORM model + repository) is **eliminated**. Routing rules come from `Settings` env vars, not a DB table. `ProviderRoutingCache.load_from_config()` is synchronous and has no UoW dependency.

**What to build**: In-memory cache loaded from `Settings` (PRD §6.5).

**Full class spec**:
```python
_INTRADAY_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})
_EOD_TFS: frozenset[str] = frozenset({"1d", "1w", "1M"})


class ProviderRoutingCache:
    """In-memory routing cache populated from Settings env vars.

    No DB dependency. load_from_config() is synchronous (reads env vars).
    Force-reload via POST /internal/v1/routing/reload re-reads Settings.

    get_providers_for() and primary_for() are O(1) — no I/O in the hot path.
    """

    def __init__(self) -> None:
        # key: (dataset_type, timeframe | None) → ordered list of provider values
        self._cache: dict[tuple[str, str | None], list[str]] = {}
        self._loaded_at: datetime | None = None

    def get_providers_for(
        self, dataset_type: str, timeframe: str | None
    ) -> list[str]:
        """Return providers sorted by descending weight. Falls back to ["eodhd"]. O(1) — no I/O."""
        return self._cache.get((dataset_type, timeframe), ["eodhd"])

    def primary_for(self, dataset_type: str, timeframe: str | None) -> str:
        """Return first (highest-weight) provider for this slot."""
        providers = self.get_providers_for(dataset_type, timeframe)
        return providers[0] if providers else "eodhd"

    def load_from_config(self, settings: "Settings") -> int:
        """Parse ROUTING_* env vars from Settings, rebuild cache dict.
        Synchronous — no I/O. Returns count of distinct slots loaded."""
        new_cache: dict[tuple[str, str | None], list[str]] = {}
        # Parse each routing string and populate the cache for all covered timeframes
        _parse_into(new_cache, "ohlcv", _INTRADAY_TFS, settings.routing_ohlcv_intraday)
        _parse_into(new_cache, "ohlcv", _EOD_TFS, settings.routing_ohlcv_eod)
        _parse_into(new_cache, "quotes", {None}, settings.routing_quotes)
        _parse_into(new_cache, "fundamentals", {None}, settings.routing_fundamentals)
        self._cache = new_cache
        self._loaded_at = utc_now()
        log.info("provider_routing_cache_loaded", slots_count=len(new_cache))
        return len(new_cache)

    def needs_refresh(self) -> bool:
        """Always False — config-backed cache only refreshes via force-reload."""
        return False

    def loaded_at_iso(self) -> str:
        """ISO timestamp of last load_from_config(), or 'never'."""
        return self._loaded_at.isoformat() if self._loaded_at else "never"


def _parse_into(
    cache: dict[tuple[str, str | None], list[str]],
    dataset_type: str,
    timeframes: set[str | None],
    routing_str: str,
) -> None:
    """Parse 'provider1:weight1,provider2:weight2' into ordered cache entries."""
    pairs = [p.strip() for p in routing_str.split(",") if p.strip()]
    ordered: list[tuple[int, str]] = []
    for pair in pairs:
        parts = pair.rsplit(":", 1)
        if len(parts) != 2:
            log.warning("routing_config_invalid_pair", pair=pair)
            continue
        provider_val, weight_str = parts
        try:
            weight = int(weight_str)
        except ValueError:
            log.warning("routing_config_invalid_weight", pair=pair)
            continue
        ordered.append((weight, provider_val.strip()))
    # Sort descending by weight, extract provider values
    providers = [p for _, p in sorted(ordered, reverse=True)]
    for tf in timeframes:
        cache[(dataset_type, tf)] = providers
```

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_cache_primary_for_returns_highest_weight` | Highest-weight provider is first in list | unit |
| `test_cache_fallback_eodhd_when_no_rules` | Missing slot → `["eodhd"]` | unit |
| `test_cache_load_from_config_intraday` | `routing_ohlcv_intraday="alpaca:100,polygon:80"` → alpaca first for ohlcv/1m | unit |
| `test_cache_load_from_config_eod` | `routing_ohlcv_eod="yahoo_finance:100,eodhd:80"` → yahoo first for ohlcv/1d | unit |
| `test_cache_load_from_config_invalid_pair` | Malformed entry skipped, valid entries still loaded | unit |
| `test_cache_load_from_config_resets_stale` | Second `load_from_config()` call replaces all previous entries | unit |

**Acceptance criteria**:
- [ ] `get_providers_for()` and `primary_for()` are pure, no I/O
- [ ] `load_from_config()` is synchronous — no `await`, no `UnitOfWork`
- [ ] All intraday timeframes (`1m/5m/15m/30m/1h/4h`) populated from `routing_ohlcv_intraday`
- [ ] All EOD timeframes (`1d/1w/1M`) populated from `routing_ohlcv_eod`
- [ ] 6 unit tests pass
- [ ] mypy passes

---

#### T-A-3-03: Register Alpaca + Polygon in `build_provider_registry()`

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/__init__.py`

**What to build**: Conditionally register Alpaca and Polygon adapters when their API keys are non-empty. Follow the same pattern as the Finnhub conditional registration.

```python
# Register Alpaca when keys are configured
alpaca_api_key = getattr(settings, "alpaca_api_key", SecretStr(""))
alpaca_secret_key = getattr(settings, "alpaca_secret_key", SecretStr(""))
if alpaca_api_key.get_secret_value() and alpaca_secret_key.get_secret_value():
    from market_ingestion.infrastructure.adapters.providers.alpaca import AlpacaProviderAdapter
    registry.register(AlpacaProviderAdapter(
        api_key=alpaca_api_key,
        secret_key=alpaca_secret_key,
        client=httpx.AsyncClient(),
        base_url=getattr(settings, "alpaca_base_url", "https://data.alpaca.markets"),
        feed=getattr(settings, "alpaca_feed", "iex"),
    ))

# Register Polygon when API key is configured
polygon_api_key = getattr(settings, "polygon_api_key", SecretStr(""))
if polygon_api_key.get_secret_value():
    from market_ingestion.infrastructure.adapters.providers.polygon import PolygonProviderAdapter
    registry.register(PolygonProviderAdapter(
        api_key=polygon_api_key,
        client=httpx.AsyncClient(),
        base_url=getattr(settings, "polygon_base_url", "https://api.polygon.io"),
    ))
```

**Acceptance criteria**:
- [ ] Alpaca only registered when both `alpaca_api_key` and `alpaca_secret_key` are non-empty
- [ ] Polygon only registered when `polygon_api_key` is non-empty
- [ ] mypy passes

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes on `market-ingestion`
- [ ] 6 new unit tests for `ProviderRoutingCache` pass
- [ ] Registry conditional registration verified by test
- [ ] No `UnitOfWork` changes (ADR-032-02: no DB repository)

### Break Impact

No `UnitOfWork` changes needed (routing cache no longer reads from DB).

### Regression Guardrails
- **BP-025 (credential leakage)**: Alpaca/Polygon keys from `settings` are `SecretStr` — always call `.get_secret_value()` only in adapter constructors. Never log or pass the raw secret value.
- **ADR-032-02**: Do NOT add `routing_rules: RoutingRuleRepository` to `UnitOfWork`. Routing is config-backed — any drift back to DB is a regression.

---

## Wave A-4: ExecuteTaskUseCase Integration + Routing API Endpoints ✅

**Goal**: Wire `ProviderRoutingCache` into `ExecuteTaskUseCase` (replacing static `_preferred_provider()`), add routing API endpoints, populate `fetched_by_provider` on SUCCEEDED.
**Depends on**: Wave A-2, Wave A-3, **PLAN-0038 Waves A-4 and A-5 must be complete**
**Estimated effort**: 60–75 min
**Architecture layer**: application + API

> ⚠️ **Prerequisite check**: Before starting this wave, verify that PLAN-0038 Wave A-4 (static `_preferred_provider()`) and Wave A-5 (`ZeroBarTrackerPort` + `ValkeyZeroBarTracker`) are committed. The `_preferred_provider()` function added by Wave A-4 of PLAN-0038 will be **removed** in this wave and replaced by the cache lookup.

### Pre-read
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` (entire file)
- `services/market-ingestion/src/market_ingestion/api/` (existing routers for auth/middleware pattern)
- `services/market-ingestion/src/market_ingestion/app.py` (startup wiring)
- `services/market-ingestion/src/market_ingestion/application/ports/zero_bar_tracker.py` (from PLAN-0038 A-5)

### Tasks

#### T-A-4-01: `RoutingReloadUseCase` + routing API endpoints

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**:
- `services/market-ingestion/src/market_ingestion/application/use_cases/routing_reload.py` (NEW)
- `services/market-ingestion/src/market_ingestion/api/routers/routing.py` (NEW)
- `services/market-ingestion/src/market_ingestion/app.py`

**What to build**:

**`RoutingReloadUseCase`**:
```python
class RoutingReloadUseCase:
    def __init__(self, cache: ProviderRoutingCache, settings: Settings) -> None: ...

    def execute(self) -> dict[str, object]:
        """Force-reload the routing cache from Settings (synchronous — no DB).
        Returns {reloaded, rules_loaded}."""
        slots_loaded = self._cache.load_from_config(self._settings)
        log.info("provider_routing_cache_reload_forced",
                 slots_count=slots_loaded, triggered_by="api")
        return {"reloaded": True, "rules_loaded": slots_loaded}
```
> Note: `execute()` is **synchronous** — `load_from_config()` is synchronous. No `await` needed. The API router can call it directly without `await`.

**Router** (`routing.py`):

`POST /internal/v1/routing/reload`:
- Auth: `InternalJWTMiddleware` (existing — applies to all `/internal/` routes automatically)
- Request body: none
- Response 200: `{"reloaded": true, "rules_loaded": int}`

`GET /internal/v1/routing/rules`:
- Auth: same as above
- Response 200:
  ```json
  {
    "rules": [{"dataset_type": "ohlcv", "timeframe": "1m", "provider": "alpaca", ...}],
    "cache_loaded_at": "ISO",
    "ttl_seconds": 300
  }
  ```
- Returns the current in-memory cache state (not DB — the cached view)

Mount the routing router in `app.py`.

**Acceptance criteria**:
- [ ] `POST /internal/v1/routing/reload` → 200 `{reloaded: true, rules_loaded: N}`
- [ ] `GET /internal/v1/routing/rules` → 200 with rules list and metadata
- [ ] Both routes require `X-Internal-JWT` (validated by `InternalJWTMiddleware`)
- [ ] `RoutingReloadUseCase` only imports from domain/application layers (R25)
- [ ] mypy passes

---

#### T-A-4-02: Wire `ProviderRoutingCache` into `ExecuteTaskUseCase`

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: [T-A-4-03]
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**: Replace the static `_preferred_provider()` function (added by PLAN-0038 Wave A-4) with `ProviderRoutingCache` lookup. Update the constructor to accept `routing_cache: ProviderRoutingCache | None = None`.

**Constructor addition**:
```python
def __init__(
    self,
    ...,
    routing_cache: ProviderRoutingCache | None = None,  # NEW
    zero_bar_tracker: ZeroBarTrackerPort | None = None,  # from PLAN-0038 A-5
) -> None:
    ...
    self._routing_cache = routing_cache
```

**Routing logic** (replace the `_preferred_provider()` call with):
```python
# In execute() — adapter selection:
if self._routing_cache is not None:
    # Dynamic DB-backed routing (PRD-0032 primary path)
    primary_provider_str = self._routing_cache.primary_for(
        str(task.dataset_type), task.timeframe
    )
    try:
        preferred = Provider(primary_provider_str)
        adapter = self._registry.get(preferred)
    except (ValueError, ProviderUnavailable):
        # Unknown/unregistered provider from cache → fall back to task.provider
        adapter = self._registry.get(task.provider)
        preferred = task.provider
else:
    # Fallback: use task.provider directly (static routing from PLAN-0038 A-4 path)
    preferred = _preferred_provider(task.dataset_type, task.timeframe, self._registry)
    adapter = self._registry.get(preferred)
```

**Note**: Retain `_preferred_provider()` as a fallback for services that don't wire the cache. This ensures backward compatibility during the deployment window. The function can be removed in a future cleanup wave.

**Logging**:
```python
if preferred != task.provider:
    log.info("provider_routing_cache_selected",
             requested=str(task.provider),
             selected=preferred.value,
             dataset_type=str(task.dataset_type),
             timeframe=task.timeframe or "")
```

**EODHD quota/CB guard**: Keep the existing gate: `if self._quota_service is not None and preferred == Provider.EODHD:` — no change needed if PLAN-0038 A-4 already gated this correctly.

**Acceptance criteria**:
- [ ] When `routing_cache` is set: routing uses `cache.primary_for()`
- [ ] When `routing_cache` is None: falls back to `_preferred_provider()` (backward compat)
- [ ] `provider_routing_cache_selected` event logged on override
- [ ] EODHD quota/CB only applied when `preferred == Provider.EODHD`
- [ ] mypy passes

---

#### T-A-4-03: Populate `fetched_by_provider` on task SUCCEEDED

**Type**: impl
**depends_on**: [T-A-1-03, T-A-4-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**What to build**: After a successful fetch in `execute()`, set `task.fetched_by_provider` to the actual provider that fetched the data (from `fetch_result.provider.value`). This happens before step 5 (DB transaction).

```python
# After fetch_result is obtained and before step 2 (bronze store):
task.fetched_by_provider = fetch_result.provider.value
```

This requires that `IngestionTask.fetched_by_provider` is set on the entity (done in T-A-1-03), and that the task repository's `save()` method persists it (the ORM mapper will handle this automatically since the column is mapped).

**Acceptance criteria**:
- [ ] `task.fetched_by_provider` set to `fetch_result.provider.value` after successful fetch
- [ ] Value persisted in DB when task transitions to SUCCEEDED
- [ ] mypy passes

---

#### T-A-4-04: Wire routing cache startup in `app.py`

**Type**: impl
**depends_on**: [T-A-3-02, T-A-4-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/app.py`

**What to build**: In the application factory, construct `ProviderRoutingCache` and load it synchronously at startup from `settings`. Pass it to `ExecuteTaskUseCase` and `RoutingReloadUseCase`.

```python
# app.py — after settings are loaded:
from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache

routing_cache = ProviderRoutingCache()
# Synchronous — no DB query, no async context needed
routing_cache.load_from_config(settings)

# Pass routing_cache to both use cases:
execute_use_case = ExecuteTaskUseCase(
    ...,
    routing_cache=routing_cache,
    zero_bar_tracker=zero_bar_tracker,  # from PLAN-0038 A-5
)
routing_reload_use_case = RoutingReloadUseCase(cache=routing_cache, settings=settings)
```

> **No background TTL refresh needed**: `load_from_config()` is synchronous and env vars don't change at runtime. Force-reload is available via `POST /internal/v1/routing/reload`. Remove any TTL background task.

**Acceptance criteria**:
- [ ] Cache loaded synchronously at startup before first task
- [ ] No async startup block required for routing cache
- [ ] `routing_cache` passed to both `ExecuteTaskUseCase` and `RoutingReloadUseCase`
- [ ] mypy passes

---

#### T-A-4-05: Unit tests — routing use case + execute task routing

**Type**: test
**depends_on**: [T-A-4-01, T-A-4-02, T-A-4-03]
**blocks**: none
**Target files**:
- `services/market-ingestion/tests/unit/use_cases/test_routing_reload.py` (NEW)
- `services/market-ingestion/tests/unit/use_cases/test_execute_task_routing.py` (update or new)

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_routing_reload_calls_load_from_config` | `execute()` calls `cache.load_from_config(settings)` and returns correct slot count | unit |
| `test_ohlcv_1m_routes_to_alpaca_via_cache` | Cache has alpaca/100 for ohlcv/1m → selects Alpaca adapter | unit |
| `test_ohlcv_1d_routes_to_yahoo_via_cache` | Cache has yahoo_finance/100 for ohlcv/1d → selects Yahoo adapter | unit |
| `test_cache_none_falls_back_to_preferred_provider` | `routing_cache=None` → `_preferred_provider()` still used | unit |
| `test_fetched_by_provider_set_on_succeed` | After `execute()`, task `fetched_by_provider == fetch_result.provider.value` | unit |
| `test_routing_override_logged` | When cache selects different provider than task.provider → log event emitted | unit |

**Acceptance criteria**:
- [ ] 6 unit tests pass
- [ ] ruff + mypy pass

---

#### T-A-4-06: Fix `_fallback_provider()` — wire routing cache for zero-bar failover

**Type**: impl
**depends_on**: [T-A-4-02]
**blocks**: none
**Target files**: `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py`

**Problem**: `_fallback_provider()` (lines ~743–766 in `execute_task.py`) currently returns `None` for intraday timeframes ("no free intraday alternative"). This means Polygon is **never reached** during zero-bar failover — the entire failover chain silently fails.

Additionally, `_fetch()` (lines ~382–396) dispatches intraday timeframes via `fetch_intraday()` but only covers `{"1m", "5m", "1h"}` — missing `"15m"`, `"30m"`, `"4h"`.

**What to build**: Two targeted fixes in `execute_task.py`:

**Fix 1 — Extend `_fetch()` intraday dispatch set** (lines ~382–396):
```python
# Before (PLAN-0038 Wave A-4 code):
_INTRADAY_TFS = {"1m", "5m", "1h"}

# After (extend to all supported intraday timeframes):
_INTRADAY_TFS = {"1m", "5m", "15m", "30m", "1h", "4h"}
```

**Fix 2 — Replace `_fallback_provider()` call with routing cache ordered list**:

In the zero-bar failover path (around line ~222 where `_fallback_provider()` is called):

```python
# Before:
fallback = _fallback_provider(task.dataset_type, task.timeframe)
if fallback is None:
    # no alternative → task stays at 0 bars
    return result

# After:
if self._routing_cache is not None:
    # Use routing cache to get ordered provider list; skip current provider
    ordered = self._routing_cache.get_providers_for(
        str(task.dataset_type), task.timeframe
    )
    # Try each provider in order, skipping the one that already returned 0 bars
    for fallback_str in ordered:
        if fallback_str == adapter.provider.value:
            continue  # skip the provider that already failed
        try:
            fallback_provider = Provider(fallback_str)
            fallback_adapter = self._registry.get(fallback_provider)
        except (ValueError, KeyError, ProviderUnavailable):
            continue  # provider not registered
        log.info("zero_bar_failover", from_provider=adapter.provider.value,
                 to_provider=fallback_str, symbol=task.symbol, streak=streak)
        return await self._fetch(task, fallback_adapter)
    # All providers exhausted
    return result
else:
    # Legacy fallback path
    fallback = _fallback_provider(task.dataset_type, task.timeframe)
    if fallback is None:
        return result
    ...
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_zero_bar_failover_reaches_polygon` | Alpaca returns 0 bars × 5 → routing cache → Polygon adapter called | unit |
| `test_fetch_dispatch_covers_15m_30m_4h` | `_fetch()` with `"15m"` / `"30m"` / `"4h"` calls `fetch_intraday()` (not `fetch_ohlcv()`) | unit |

**Acceptance criteria**:
- [ ] `_INTRADAY_TFS` (or equivalent) includes `{"1m", "5m", "15m", "30m", "1h", "4h"}`
- [ ] Zero-bar failover with routing cache iterates provider list rather than calling `_fallback_provider()`
- [ ] `_fallback_provider()` static function retained as backward-compat fallback when `routing_cache=None`
- [ ] 2 new unit tests pass
- [ ] mypy passes

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] 8 routing unit tests pass (6 original + 2 new from T-A-4-06)
- [ ] `POST /internal/v1/routing/reload` and `GET /internal/v1/routing/rules` respond correctly in unit test with mock cache

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-ingestion/tests/unit/use_cases/test_execute_task.py` | `ExecuteTaskUseCase.__init__` gains `routing_cache` param | Add `routing_cache=None` to all test constructors |
| `services/market-ingestion/tests/unit/use_cases/test_execute_task_routing.py` (PLAN-0038 A-4) | PLAN-0038 A-4 added tests for `_preferred_provider()` — still valid as fallback path | Update tests to also cover cache-based routing path |

### Regression Guardrails
- **BP-034 (mark_processed before early return)**: Confirm `task.fetched_by_provider` assignment does NOT create an early-return path. It's an in-memory mutation before step 2 — no return point between assignment and step 5 DB commit.
- **BP-032 (missing NULL check on new DB column)**: `fetched_by_provider` is nullable. All queries that filter on it use `IS NOT NULL` explicitly (reclaim worker). Do not use `== None` comparisons in SQLAlchemy — use `.is_(None)` and `.is_not(None)`.

---

## Wave A-5: PrimaryProviderReclaimWorker ✅

**Goal**: Implement `PrimaryProviderReclaimWorker` and wire it as an independent process.
**Depends on**: Wave A-3 (routing cache), Wave A-4 (`fetched_by_provider` on tasks)
**Estimated effort**: 60 min
**Architecture layer**: infrastructure + domain

### Pre-read
- `services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py` (existing worker pattern)
- `services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py` (task creation pattern)
- `docker-compose.yml` (process entry point pattern)

### Tasks

#### T-A-5-01: `PrimaryProviderReclaimWorker` class

**Type**: impl
**depends_on**: none (within this wave)
**blocks**: [T-A-5-02]
**Target files**: `services/market-ingestion/src/market_ingestion/infrastructure/workers/reclaim_worker.py` (NEW)

**What to build** (PRD §6.5 Worker spec):

```python
class PrimaryProviderReclaimWorker:
    """Background worker that runs every 4h.

    Finds SUCCEEDED tasks where fetched_by_provider != primary provider
    from ProviderRoutingCache, then re-creates tasks for the primary provider.
    Independent process (R22): NOT co-located with the task executor.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        routing_cache: ProviderRoutingCache,
        interval_sec: int = 14_400,           # 4 hours
        max_reclaim_per_run: int = 5_000,     # safety cap
    ) -> None: ...

    async def run(self) -> None:
        """Main loop: reclaim, sleep, repeat."""
        while True:
            await self._run_once()
            await asyncio.sleep(self._interval_sec)

    async def _run_once(self) -> None:
        """One reclaim cycle."""
        run_id = str(new_uuid7())
        log.info("primary_provider_reclaim_start", run_id=run_id)
        t0 = time.monotonic()

        async with self._uow_factory() as uow:
            # Query tasks where status=SUCCEEDED AND fetched_by_provider IS NOT NULL
            # AND fetched_by_provider != primary_for(dataset_type, timeframe)
            tasks = await uow.tasks.find_succeeded_with_secondary_provider(
                routing_cache=self._routing_cache,
                limit=self._max_reclaim_per_run,
            )
            # Create new tasks for primary provider (ON CONFLICT DO NOTHING via dedupe_key)
            new_tasks = [
                self._make_reclaim_task(t) for t in tasks
                if self._needs_reclaim(t)
            ]
            if new_tasks:
                await uow.tasks.add_many(new_tasks)
            await uow.commit()

        log.info("primary_provider_reclaim_complete",
                 tasks_reclaimed=len(new_tasks),
                 run_duration_ms=int((time.monotonic() - t0) * 1000))

    def _needs_reclaim(self, task: IngestionTask) -> bool:
        """True if task was fetched by non-primary provider."""
        if task.fetched_by_provider is None:
            return False
        primary = self._routing_cache.primary_for(
            str(task.dataset_type), task.timeframe
        )
        return task.fetched_by_provider != primary

    def _make_reclaim_task(self, original: IngestionTask) -> IngestionTask:
        """Create a new task targeting the primary provider for the same date."""
        primary = self._routing_cache.primary_for(
            str(original.dataset_type), original.timeframe
        )
        return IngestionTask(
            id=str(new_uuid7()),
            provider=Provider(primary),
            dataset_type=original.dataset_type,
            symbol=original.symbol,
            exchange=original.exchange,
            timeframe=original.timeframe,
            range_start=original.range_start,
            range_end=original.range_end,
            # dedupe_key same as scheduler → ON CONFLICT DO NOTHING if already exists
            dedupe_key=original.dedupe_key,
            status=IngestionTaskStatus.PENDING,
        )
```

**Repository addition**: `find_succeeded_with_secondary_provider(routing_cache, limit) → list[IngestionTask]` — query `WHERE status='succeeded' AND fetched_by_provider IS NOT NULL`, then filter in Python (or SQL via NOT IN subquery on primary providers).

**Acceptance criteria**:
- [ ] Worker loop runs `_run_once()` every 4 hours
- [ ] Only creates tasks for rows where `fetched_by_provider != primary`
- [ ] `NULL fetched_by_provider` rows skipped
- [ ] `ON CONFLICT DO NOTHING` semantics via `dedupe_key` reuse
- [ ] Max 5000 tasks per run (safety cap)
- [ ] mypy passes

---

#### T-A-5-02: Docker/process wiring

**Type**: config
**depends_on**: [T-A-5-01]
**blocks**: none
**Target files**:
- `docker-compose.yml`
- `services/market-ingestion/src/market_ingestion/workers/reclaim_worker_main.py` (NEW entry point)

**What to build**: New entry point `reclaim_worker_main.py` (follows `worker.py` pattern):
```python
"""Entry point for the PrimaryProviderReclaimWorker process."""
import asyncio
from market_ingestion.app import create_reclaim_worker

if __name__ == "__main__":
    worker = create_reclaim_worker()
    asyncio.run(worker.run())
```

New docker-compose service (add alongside `market-ingestion-worker`):
```yaml
market-ingestion-reclaim-worker:
  build:
    context: .
    dockerfile: services/market-ingestion/Dockerfile
  command: python -m market_ingestion.workers.reclaim_worker_main
  environment: *market-ingestion-env
  depends_on: *market-ingestion-deps
  profiles: ["full"]
```

**Acceptance criteria**:
- [ ] `reclaim_worker_main.py` entry point runnable
- [ ] `create_reclaim_worker()` factory in `app.py`
- [ ] docker-compose service added under `profiles: ["full"]`

---

#### T-A-5-03: Unit tests — reclaim worker

**Type**: test
**depends_on**: [T-A-5-01]
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/workers/test_reclaim_worker.py` (NEW)

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_reclaim_identifies_secondary_tasks` | Tasks where `fetched_by_provider != primary` are reclaimed | unit |
| `test_reclaim_creates_primary_tasks` | `_make_reclaim_task()` creates task with primary provider | unit |
| `test_reclaim_idempotent_dedupe` | Same `dedupe_key` → `add_many()` with `ON CONFLICT DO NOTHING` | unit |
| `test_reclaim_skips_null_fetched_by` | `fetched_by_provider=None` → not reclaimed | unit |
| `test_reclaim_max_cap_5000` | 6000 mismatches → only 5000 tasks created | unit |
| `test_reclaim_logs_complete_event` | `primary_provider_reclaim_complete` event present in structlog | unit |

**Acceptance criteria**:
- [ ] 6 unit tests pass

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] 6 unit tests pass
- [ ] No direct DB calls in `PrimaryProviderReclaimWorker` domain logic (all via UoW)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-ingestion/src/market_ingestion/app.py` | New `create_reclaim_worker()` factory needed | Add factory function |

### Regression Guardrails
- **R22 (one concern per process)**: `PrimaryProviderReclaimWorker` MUST be its own process, NOT co-located with the task executor (`WorkerProcess`). Verify the docker-compose service is a separate container.
- **BP-005 (bulk inserts with ON CONFLICT)**: `add_many()` must use `INSERT ... ON CONFLICT DO NOTHING` — not `INSERT ... ON CONFLICT DO UPDATE`. Reclaim creates duplicate tasks intentionally (same `dedupe_key`); the conflict should be silently ignored.

---

## Wave A-6: Integration Tests + Documentation ✅

**Goal**: Integration tests (migration DDL alignment, routing cache from DB), documentation updates.
**Depends on**: All prior Plan A waves
**Estimated effort**: 45–60 min
**Architecture layer**: integration + docs

### Tasks

#### T-A-6-01: Integration tests

**Type**: test
**depends_on**: none (within this wave)
**blocks**: none
**Target files**:
- `services/market-ingestion/tests/integration/test_migration_0010.py` (NEW)
- `services/market-ingestion/tests/integration/test_routing_cache_config.py` (NEW)

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_migration_0010_fetched_by_provider_column` | After upgrade 0010, `ingestion_tasks.fetched_by_provider` column and index exist | integration |
| `test_migration_0010_no_routing_rules_table` | After upgrade 0010, `provider_routing_rules` table does NOT exist (config-based routing) | integration |
| `test_routing_cache_load_from_settings` | `load_from_config(settings)` with real `Settings` returns alpaca first for ohlcv/1m | integration |

#### T-A-6-02: DDL alignment tests

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**: `services/market-ingestion/tests/unit/db/test_ddl_alignment.py`

Update one DDL alignment test class:
- `TestIngestionTasksDDLAlignment`: Update expected column count to include `fetched_by_provider`

#### T-A-6-03: Documentation

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**:
- `docs/services/market-ingestion.md` — add "Intraday Providers" section, update routing table
- `services/market-ingestion/.claude-context.md` — add ALPACA/POLYGON, routing cache, reclaim worker
- `docs/MASTER_PLAN.md` — update S2 section with intraday provider support
- `services/market-ingestion/configs/dev.local.env.example` — add ALPACA/POLYGON env vars

### Validation Gate
- [ ] Integration tests pass against real test DB
- [ ] DDL alignment tests pass
- [ ] Documentation updated

### Break Impact
No new breaks expected (integration tests are additive).

### Regression Guardrails
- **BP-126 (Alembic migration head mismatch)**: Run `alembic history` in CI to confirm 0010 is the new head. Ensure `down_revision = "0009"`.

---

# Plan B: market-data (S3)

## Wave B-1: OHLCVBar Entity Extension + Migration 008 ✅

**Goal**: Add `is_partial` to `OHLCVBar` entity, ORM model, migration 008, and update all repository methods.
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: domain + schema

### Pre-read
- `services/market-data/src/market_data/domain/entities.py` (OHLCVBar — current: 12 fields, last: `is_derived`)
- `services/market-data/src/market_data/infrastructure/db/models/ohlcv.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py`
- `services/market-data/alembic/versions/007_add_ohlcv_is_derived.py` (current head pattern)

### Tasks

#### T-B-1-01: Add `is_partial: bool = False` to `OHLCVBar` entity

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-02, T-B-2-02]
**Target files**: `services/market-data/src/market_data/domain/entities.py`

**What to build**: Add `is_partial: bool = False` field to `OHLCVBar` dataclass immediately after `is_derived` (PRD §6.4). Add invariant validation.

```python
# After: is_derived: bool = False
is_partial: bool = False
# True if this bar covers [period_start, current_time) — an open/live bar.
# Only relevant for intraday derived bars. Daily/weekly/monthly bars
# are always complete (is_partial=False).
```

**Invariant**: Add `__post_init__` or validation — `is_partial=True` implies `is_derived=True`:
```python
def __post_init__(self) -> None:
    if self.is_partial and not self.is_derived:
        raise ValueError("is_partial=True implies is_derived=True; a directly-ingested bar cannot be partial")
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_ohlcv_bar_is_partial_default_false` | `OHLCVBar()` has `is_partial=False` | unit |
| `test_ohlcv_bar_partial_implies_derived` | `OHLCVBar(is_partial=True, is_derived=False)` raises `ValueError` | unit |
| `test_ohlcv_bar_partial_with_derived_ok` | `OHLCVBar(is_partial=True, is_derived=True)` passes | unit |

**Downstream test impact**:
- All existing `OHLCVBar(...)` constructors that don't pass `is_partial` → auto-compatible (default=False)
- Tests that verify `OHLCVBar.__dataclass_fields__` count → update count from 12 to 13

**Acceptance criteria**:
- [ ] `is_partial: bool = False` as the last field
- [ ] `__post_init__` raises `ValueError` when `is_partial=True, is_derived=False`
- [ ] 3 unit tests pass
- [ ] mypy passes

---

#### T-B-1-02: Migration 008 — `add_ohlcv_is_partial`

**Type**: schema
**depends_on**: none
**blocks**: [T-B-1-03]
**Target files**: `services/market-data/alembic/versions/008_add_ohlcv_is_partial.py` (NEW)

**What to build**:
```python
revision = "008"
down_revision = "007"

def upgrade() -> None:
    op.add_column(
        "ohlcv_bars",
        sa.Column(
            "is_partial",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

def downgrade() -> None:
    op.drop_column("ohlcv_bars", "is_partial")
```

**Downstream test impact**:
- `services/market-data/tests/integration/test_migrations.py` → add test for migration 008
- `TestOHLCVBarsDDLAlignment` (if exists) → update expected column count

**Acceptance criteria**:
- [ ] Migration upgrades cleanly
- [ ] `ohlcv_bars` gains `is_partial BOOLEAN NOT NULL DEFAULT false`
- [ ] Downgrade removes column cleanly
- [ ] All existing rows get `is_partial=false` (backward-compatible)

---

#### T-B-1-03: Update `OHLCVBarModel` ORM + `_to_domain()` + upsert methods

**Type**: impl
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: [T-B-2-02]
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/models/ohlcv.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py`

**What to build**:

**ORM model addition** (after `is_derived`):
```python
is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
```

**`_to_domain()` update**:
```python
return OHLCVBar(
    ...,
    is_derived=bool(row.is_derived),
    is_partial=bool(row.is_partial),  # NEW
)
```

**`bulk_upsert_with_priority()` values dict**: Add `"is_partial": bar.is_partial`. Add `is_partial` to ON CONFLICT `set_` dict.

**`bulk_upsert_derived()` values dict**: Add `"is_partial": bar.is_partial`. Add `is_partial` to ON CONFLICT `set_` dict. (Currently hardcodes `is_derived=True` in values — keep that, add `is_partial` alongside.)

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| `test_to_domain_maps_is_partial` | ORM row with `is_partial=True` → domain entity `is_partial=True` | unit |
| `test_bulk_upsert_with_priority_includes_is_partial` | Values dict contains `is_partial` key | unit |
| `test_bulk_upsert_derived_includes_is_partial` | Derived upsert includes `is_partial` | unit |

**Acceptance criteria**:
- [ ] ORM model has `is_partial` column
- [ ] `_to_domain()` maps `is_partial`
- [ ] Both upsert methods include `is_partial` in values and SET clauses
- [ ] mypy passes

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes on `market-data`
- [ ] 6 new unit tests pass
- [ ] `alembic upgrade 008` runs without error on test DB

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-data/tests/` tests constructing `OHLCVBar(...)` with `is_derived=True` but no `is_partial` | `__post_init__` is NOT triggered because `is_partial` defaults to `False` | No action needed — default handles it |
| DDL alignment tests for `ohlcv_bars` | Column count increases | Update expected count by 1 |

### Regression Guardrails
- **BP-019 (Missing server_default for NOT NULL)**: `is_partial` must have `server_default="false"` on the migration column. Confirmed in T-B-1-02 spec.
- **BP-126 (Alembic migration head mismatch)**: Confirm `down_revision = "007"` in migration 008.

---

## Wave B-2: ResampledOHLCVUseCase ✅

**Goal**: `ResampledOHLCVUseCase` with period-floor logic, open-bar aggregation semantics, and the new datetime-range query method on the repository.
**Depends on**: Wave B-1
**Estimated effort**: 60 min
**Architecture layer**: application

### Pre-read
- `services/market-data/src/market_data/application/use_cases/derive_ohlcv.py` (aggregation pattern)
- `services/market-data/src/market_data/application/ports/repositories.py` (`OHLCVRepository` ABC)
- `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py`
- PRD §6.5 `ResampledOHLCVUseCase` and §6.6 Flow A (resampling semantics)

### Tasks

#### T-B-2-01: Add `find_by_instrument_timeframe_datetime_range()` to port + implementation

**Type**: impl
**depends_on**: none
**blocks**: [T-B-2-02]
**Target files**:
- `services/market-data/src/market_data/application/ports/repositories.py`
- `services/market-data/src/market_data/infrastructure/db/repositories/ohlcv_repo.py`

**What to build**: A new query method on `OHLCVRepository` that accepts `datetime` (not `date`) boundaries, needed for intraday period queries.

**Port addition**:
```python
@abstractmethod
async def find_by_instrument_timeframe_datetime_range(
    self,
    instrument_id: str,
    timeframe: Timeframe,
    start_dt: datetime,
    end_dt: datetime,
) -> list[OHLCVBar]:
    """Return bars for the given datetime range (inclusive on both ends)."""
```

**Implementation** (`PgOHLCVRepository`):
```python
async def find_by_instrument_timeframe_datetime_range(
    self, instrument_id, timeframe, start_dt, end_dt
) -> list[OHLCVBar]:
    result = await self._session.execute(
        select(OHLCVBarModel)
        .where(
            OHLCVBarModel.instrument_id == instrument_id,
            OHLCVBarModel.timeframe == str(timeframe),
            OHLCVBarModel.bar_date >= start_dt,
            OHLCVBarModel.bar_date <= end_dt,
        )
        .order_by(OHLCVBarModel.bar_date.asc())
    )
    return [self._to_domain(row) for row in result.scalars().all()]
```

**Downstream test impact**: All test mocks of `OHLCVRepository` must now implement the new abstract method.

**Acceptance criteria**:
- [ ] Port ABC defines the method
- [ ] `PgOHLCVRepository` implements it
- [ ] mypy passes

---

#### T-B-2-02: `ResampledOHLCVUseCase`

**Type**: impl
**depends_on**: [T-B-1-01, T-B-2-01]
**blocks**: [T-B-3-01]
**Target files**: `services/market-data/src/market_data/application/use_cases/resample_ohlcv.py` (NEW)

**What to build** (PRD §6.5 full spec):

```python
"""ResampledOHLCVUseCase — derive intraday bars from 1m bars with open-bar semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from market_data.domain.entities import OHLCVBar
from market_data.domain.enums import Timeframe
from market_data.domain.value_objects import ProviderPriority
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_data.application.ports.uow import UnitOfWork

logger = get_logger(__name__)

# Period durations in seconds per target timeframe
_PERIOD_SECONDS: dict[Timeframe, int] = {
    Timeframe.FIVE_MINUTES: 300,
    Timeframe.FIFTEEN_MINUTES: 900,
    Timeframe.THIRTY_MINUTES: 1800,
    Timeframe.ONE_HOUR: 3600,
    Timeframe.FOUR_HOURS: 14400,
}

_DERIVED_SOURCE = "derived"
_DERIVED_PRIORITY = ProviderPriority(provider="unknown", priority=0)

# Default target timeframes derived from 1m
_DEFAULT_TARGET_TIMEFRAMES: list[Timeframe] = [
    Timeframe.FIVE_MINUTES,
    Timeframe.FIFTEEN_MINUTES,
    Timeframe.THIRTY_MINUTES,
    Timeframe.ONE_HOUR,
    Timeframe.FOUR_HOURS,
]


def _floor_to_period(bar_dt: datetime, period_seconds: int) -> datetime:
    """Floor a UTC datetime to the nearest period boundary.

    Uses UTC epoch integer division — same semantics as the PRD spec.
    Example: floor(9:13 UTC, 300s) == 9:10:00 UTC
    """
    epoch_seconds = int(bar_dt.timestamp())
    period_start_epoch = (epoch_seconds // period_seconds) * period_seconds
    return datetime.fromtimestamp(period_start_epoch, tz=UTC)


class ResampledOHLCVUseCase:
    """Derive intraday bars (5m/15m/30m/1h/4h) from a single 1m trigger bar.

    Open-bar semantics (ADR-032-04): every incoming 1m bar triggers
    resampling for all target timeframes, even if the period is not yet
    complete. The is_partial flag distinguishes open bars from closed bars.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        bar: OHLCVBar,
        target_timeframes: list[Timeframe] | None = None,
    ) -> list[OHLCVBar]:
        """Resample a 1m bar into all target timeframes.

        For each target timeframe:
        1. Compute period_start = floor(bar.bar_date, period_seconds)
        2. Fetch all 1m bars for [period_start, bar.bar_date]
        3. Aggregate OHLCV: open=first.open, high=max, low=min, close=last.close, volume=sum
        4. is_partial = bar.bar_date < period_start + timedelta(seconds=period_seconds)
        5. Upsert via bulk_upsert_derived()

        Returns: list of derived OHLCVBar objects (one per target timeframe).
        """
        if target_timeframes is None:
            target_timeframes = _DEFAULT_TARGET_TIMEFRAMES

        derived_bars: list[OHLCVBar] = []

        for target_tf in target_timeframes:
            period_sec = _PERIOD_SECONDS[target_tf]
            period_start = _floor_to_period(bar.bar_date, period_sec)
            period_end = period_start + timedelta(seconds=period_sec)

            # Fetch all 1m bars in the current period window
            source_bars = await self._uow.ohlcv.find_by_instrument_timeframe_datetime_range(
                instrument_id=bar.instrument_id,
                timeframe=Timeframe.ONE_MINUTE,
                start_dt=period_start,
                end_dt=bar.bar_date,
            )

            if not source_bars:
                # No 1m bars found for this period (e.g., trigger bar not yet in DB)
                # Use the trigger bar itself as the sole source
                source_bars = [bar]

            derived = _aggregate_bars(
                instrument_id=bar.instrument_id,
                target_tf=target_tf,
                period_start=period_start,
                period_end=period_end,
                source_bars=source_bars,
                trigger_bar=bar,
            )
            derived_bars.append(derived)

        if derived_bars:
            await self._uow.ohlcv.bulk_upsert_derived(derived_bars)
            logger.debug(
                "intraday_resampling_bar_processed",
                instrument_id=bar.instrument_id,
                source_timeframe="1m",
                derived_count=len(derived_bars),
                is_partial_count=sum(1 for b in derived_bars if b.is_partial),
            )

        return derived_bars


def _aggregate_bars(
    instrument_id: str,
    target_tf: Timeframe,
    period_start: datetime,
    period_end: datetime,
    source_bars: list[OHLCVBar],
    trigger_bar: OHLCVBar,
) -> OHLCVBar:
    """Aggregate source 1m bars into one derived bar for target_tf.

    source_bars must be sorted ascending by bar_date.
    """
    first = source_bars[0]
    last = source_bars[-1]
    is_partial = trigger_bar.bar_date < period_end

    return OHLCVBar(
        instrument_id=instrument_id,
        timeframe=target_tf,
        bar_date=period_start,
        open=first.open,
        high=max(b.high for b in source_bars),
        low=min(b.low for b in source_bars),
        close=last.close,
        volume=sum((b.volume or 0) for b in source_bars),
        adjusted_close=None,
        source=_DERIVED_SOURCE,
        provider_priority=_DERIVED_PRIORITY,
        is_derived=True,
        is_partial=is_partial,
    )
```

**Note**: `Timeframe` enum must have `FIVE_MINUTES`, `FIFTEEN_MINUTES`, `THIRTY_MINUTES`, `FOUR_HOURS`, `ONE_MINUTE` values. Check `services/market-data/src/market_data/domain/enums.py` — if these values do not exist, add them in this task.

**Acceptance criteria**:
- [ ] `execute()` produces `len(target_timeframes)` derived bars
- [ ] All derived bars have `is_derived=True`
- [ ] `is_partial=True` when `bar.bar_date < period_end`; `False` when bar closes the period
- [ ] `open=first.open, high=max, low=min, close=last.close, volume=sum` aggregation
- [ ] `_floor_to_period(9:13 UTC, 300) == 9:10:00 UTC` (test this explicitly)
- [ ] mypy passes

---

#### T-B-2-03: Unit tests for ResampledOHLCVUseCase

**Type**: test
**depends_on**: [T-B-2-02]
**blocks**: none
**Target files**: `services/market-data/tests/unit/use_cases/test_resample_ohlcv.py` (NEW)

All tests from PRD §11 "Unit Tests (S3)":

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_resample_5m_open_bar_at_9_13` | `period_start=9:10`, `is_partial=True`, covers 9:10–9:13 | unit |
| `test_resample_5m_closed_bar_at_9_15` | At 9:15:00, 5m bar `is_partial=False` | unit |
| `test_resample_1h_open_bar_at_9_13` | At 9:13, 1h bar: `period_start=9:00`, `is_partial=True` | unit |
| `test_resample_aggregation_ohlcv` | open=first, high=max, low=min, close=last, volume=sum | unit |
| `test_resample_single_bar_group` | Single 1m bar → derived bar has same OHLCV as source | unit |
| `test_resample_all_five_timeframes` | `execute(bar, [5m,15m,30m,1h,4h])` → 5 derived bars | unit |
| `test_all_derived_bars_have_is_derived_true` | All returned bars: `is_derived=True` | unit |
| `test_period_floor_5m` | `_floor_to_period(9:13, 300) == 9:10:00 UTC` | unit |
| `test_period_floor_1h` | `_floor_to_period(9:13, 3600) == 9:00:00 UTC` | unit |
| `test_period_floor_4h` | `_floor_to_period(09:13, 14400) == 08:00:00 UTC` | unit |
| `test_partial_bar_invariant_upheld` | Derived bar with `is_partial=True` has `is_derived=True` | unit |

- Minimum: 11 unit tests, all `pytest.mark.unit`
- Use `AsyncMock` for UoW/repository

**Acceptance criteria**:
- [ ] 11 tests pass
- [ ] ruff + mypy pass

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] 11 new unit tests pass
- [ ] `_floor_to_period` period boundary tests pass (edge case: exactly at 9:10:00)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| All test mocks of `OHLCVRepository` | New abstract method `find_by_instrument_timeframe_datetime_range` | Add `AsyncMock` implementation to all mock repos in tests |
| `services/market-data/src/market_data/domain/enums.py` | `Timeframe` enum must have `FIVE_MINUTES`, `THIRTY_MINUTES`, `FOUR_HOURS`, `ONE_MINUTE` values | Check and add missing values if not present |

### Regression Guardrails
- **BP-032 (ORM scalar vs None)**: `sum((b.volume or 0) for b in source_bars)` — correctly handles `volume=None` bars.
- **BP-async-blocking**: All DB calls in `ResampledOHLCVUseCase` are `await` — no blocking I/O.

---

## Wave B-3: IntradayResamplingWorker ✅

**Goal**: Kafka consumer that triggers resampling on every incoming 1m OHLCV event.
**Depends on**: Wave B-2
**Estimated effort**: 60 min
**Architecture layer**: infrastructure

### Pre-read
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` (follow exactly)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer_main.py` (entry point pattern)
- `infra/kafka/init/create-topics.sh` (topic registration)

### Tasks

#### T-B-3-01: `IntradayResamplingWorker` Kafka consumer

**Type**: impl
**depends_on**: none
**blocks**: [T-B-3-02]
**Target files**: `services/market-data/src/market_data/infrastructure/messaging/consumers/intraday_resampling_consumer.py` (NEW)

**What to build**: A `BaseKafkaConsumer` subscriber to `market.dataset.fetched` topic with consumer group `market-data-intraday-resampling`. Processes only `dataset_type=ohlcv, timeframe=1m` events.

**Class design** (follows `OHLCVConsumer` pattern exactly):

```python
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "ohlcv"
_TIMEFRAME_FILTER = "1m"
_GROUP_ID = "market-data-intraday-resampling"


class IntradayResamplingWorker(BaseKafkaConsumer[dict]):
    """Consumes market.dataset.fetched events for 1m OHLCV bars.

    For each event, downloads the silver JSONL from MinIO and calls
    ResampledOHLCVUseCase for each 1m bar to upsert derived 5m/15m/30m/1h/4h bars.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None

    async def process_message(self, value: dict, uow: UnitOfWork) -> None:
        """Process a single market.dataset.fetched event.

        Filters: dataset_type must be 'ohlcv', timeframe must be '1m'.
        If not matching, logs a debug message and returns (no error).
        """
        dataset_type = value.get("dataset_type", "")
        timeframe = value.get("timeframe", "")

        # Filter: only process 1m OHLCV events
        if dataset_type.lower() != _DATASET_TYPE or timeframe != _TIMEFRAME_FILTER:
            logger.debug(
                "intraday_resampling_skipping_non_1m_event",
                dataset_type=dataset_type,
                timeframe=timeframe,
            )
            return

        # Download 1m bars from MinIO silver bucket
        silver_ref = value.get("silver_ref") or value.get("result_ref", {})
        bucket = silver_ref.get("bucket", "")
        key = silver_ref.get("key", "")

        if not bucket or not key:
            logger.warning("intraday_resampling_missing_silver_ref", event=value)
            return

        raw_bytes = await self._object_storage.get_bytes(bucket=bucket, key=key)
        bars = _parse_1m_bars(raw_bytes)

        if not bars:
            logger.debug("intraday_resampling_no_bars", bucket=bucket, key=key)
            return

        # Resample each 1m bar into derived timeframes
        use_case = ResampledOHLCVUseCase(uow)
        for bar in bars:
            await use_case.execute(bar)
```

**`_parse_1m_bars(raw: bytes) → list[OHLCVBar]`**: Parse JSONL from silver bucket into `OHLCVBar` domain entities. Must look up `instrument_id` from `value["instrument_id"]` in the Kafka event (canonical bars don't embed instrument_id).

**Deduplication**: Follow same pattern as `OHLCVConsumer` — `extract_event_id()` returns `value["event_id"]`; `BaseKafkaConsumer` handles Valkey-based dedup.

**Acceptance criteria**:
- [ ] Consumer group ID: `market-data-intraday-resampling`
- [ ] Skips non-1m events gracefully (no error)
- [ ] Processes 1m events → calls `ResampledOHLCVUseCase.execute()` per bar
- [ ] Deduplication via `event_id` (inherits from `BaseKafkaConsumer`)
- [ ] mypy passes

---

#### T-B-3-02: Entry point + process wiring

**Type**: config
**depends_on**: [T-B-3-01]
**blocks**: none
**Target files**:
- `services/market-data/src/market_data/infrastructure/messaging/consumers/intraday_resampling_consumer_main.py` (NEW)
- `docker-compose.yml` (new service)
- `infra/kafka/init/create-topics.sh` (add consumer group registration if needed)

**Entry point** (follows `ohlcv_consumer_main.py` pattern):
```python
"""Entry point for the IntradayResamplingWorker process."""
from market_data.app import create_intraday_resampling_worker
worker = create_intraday_resampling_worker()
asyncio.run(worker.run())
```

**docker-compose service**:
```yaml
market-data-intraday-resampling:
  build:
    context: .
    dockerfile: services/market-data/Dockerfile
  command: python -m market_data.infrastructure.messaging.consumers.intraday_resampling_consumer_main
  environment: *market-data-env
  depends_on: *market-data-deps
  profiles: ["full"]
```

**Acceptance criteria**:
- [ ] `create_intraday_resampling_worker()` factory in `app.py`
- [ ] docker-compose service added
- [ ] Consumer group `market-data-intraday-resampling` registered (or auto-created if Kafka auto-create topics enabled)

---

#### T-B-3-03: Unit tests for IntradayResamplingWorker

**Type**: test
**depends_on**: [T-B-3-01]
**blocks**: none
**Target files**: `services/market-data/tests/unit/consumers/test_intraday_resampling_worker.py` (NEW)

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_worker_processes_1m_ohlcv_event` | Valid 1m event → `ResampledOHLCVUseCase.execute()` called once per bar | unit |
| `test_worker_skips_non_1m_event` | `timeframe=1d` event → no `execute()` call | unit |
| `test_worker_skips_non_ohlcv_event` | `dataset_type=fundamentals` → no `execute()` call | unit |
| `test_worker_skips_missing_silver_ref` | Event with no `silver_ref` → logs warning, no crash | unit |
| `test_worker_event_id_extracted` | `extract_event_id()` returns `value["event_id"]` | unit |
| `test_worker_consumer_group_id` | Consumer group is `market-data-intraday-resampling` | unit |

**Acceptance criteria**:
- [ ] 6 unit tests pass
- [ ] ruff + mypy pass

### Validation Gate
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] 6 unit tests pass
- [ ] Consumer group name confirmed as `market-data-intraday-resampling`

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/market-data/src/market_data/app.py` | New `create_intraday_resampling_worker()` factory needed | Add factory |

### Regression Guardrails
- **BP-034 (mark_processed before early return)**: The `process_message` method has early returns (skip non-1m events). Verify `BaseKafkaConsumer.mark_processed()` is called by the base class AFTER `process_message()` returns — check the base class contract to confirm no mark_processed call is needed in the early return path.
- **M-04 (Consumer process_message must NOT call `uow.commit()`)**: `ResampledOHLCVUseCase.execute()` calls `bulk_upsert_derived()` on the UoW but does NOT call `uow.commit()`. The base class owns the single commit. Verify `ResampledOHLCVUseCase` does not call `commit()`.

---

## Wave B-4: Integration Tests + Documentation ✅

**Goal**: Integration tests for migration 008 and worker event-to-DB flow. Documentation updates.
**Depends on**: All prior Plan B waves
**Estimated effort**: 45 min
**Architecture layer**: integration + docs

### Tasks

#### T-B-4-01: Integration tests

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/market-data/tests/integration/test_migration_008.py` (NEW)
- `services/market-data/tests/integration/test_intraday_resampling_worker.py` (NEW)

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_migration_008_is_partial_column` | After migration 008, `ohlcv_bars` has `is_partial BOOLEAN NOT NULL DEFAULT false` | integration |
| `test_migration_008_existing_rows_unchanged` | Rows inserted before upgrade have `is_partial=false` | integration |
| `test_intraday_resampling_worker_event_to_db` | Worker consumes mock 1m event → derived bars in DB with `is_partial=True/False` correctly set | integration |

#### T-B-4-02: DDL alignment tests

**Type**: test
**depends_on**: none
**Target files**: `services/market-data/tests/unit/db/test_ddl_alignment.py`

Add `TestOHLCVBarsDDLAlignment` update to include `is_partial` column.

#### T-B-4-03: Documentation

**Type**: docs
**depends_on**: none
**Target files**:
- `docs/services/market-data.md` — document `is_partial` field, `IntradayResamplingWorker`, `ResampledOHLCVUseCase`
- `services/market-data/.claude-context.md` — add `IntradayResamplingWorker` to consumers, `is_partial` pitfall
- `docs/MASTER_PLAN.md` — S3 section: add intraday resampling capability

### Validation Gate
- [ ] Integration tests pass
- [ ] DDL alignment tests pass
- [ ] Documentation updated

### Regression Guardrails
- **BP-126**: Confirm `down_revision = "007"` in 008; run `alembic history` to verify linear chain.
- **BP-019**: `is_partial BOOLEAN NOT NULL DEFAULT false` — server_default confirmed in T-B-1-02.

---

# Cross-Cutting Concerns

## Contract Changes
- No Avro schema changes — `IntradayResamplingWorker` consumes the existing `market.dataset.fetched.v1` schema read-only
- No new Kafka topics — new consumer group `market-data-intraday-resampling` on existing topic

## Migration Needs
| Service | Migration | Changes |
|---|---|---|
| market-ingestion | 0010 | `fetched_by_provider VARCHAR(50) NULL` + partial index on `ingestion_tasks` (no table creation — routing is config-based) |
| market-data | 008 | `is_partial BOOLEAN NOT NULL DEFAULT false` on `ohlcv_bars` |

## Configuration Changes
New env vars (add to `services/market-ingestion/configs/dev.local.env.example`):
```bash
# Alpaca Markets (intraday OHLCV)
MARKET_INGESTION_ALPACA_API_KEY=
MARKET_INGESTION_ALPACA_SECRET_KEY=
MARKET_INGESTION_ALPACA_FEED=iex
MARKET_INGESTION_ALPACA_BASE_URL=https://data.alpaca.markets

# Polygon.io (intraday OHLCV failover)
MARKET_INGESTION_POLYGON_API_KEY=
MARKET_INGESTION_POLYGON_BASE_URL=https://api.polygon.io

# Provider routing weights (ADR-032-02: config-based, not DB table)
MARKET_INGESTION_ROUTING_OHLCV_INTRADAY=alpaca:100,polygon:80
MARKET_INGESTION_ROUTING_OHLCV_EOD=yahoo_finance:100,eodhd:80
MARKET_INGESTION_ROUTING_QUOTES=eodhd:100
MARKET_INGESTION_ROUTING_FUNDAMENTALS=eodhd:100
```

## Documentation Updates
- `docs/services/market-ingestion.md` — Alpaca/Polygon adapter coverage, routing cache
- `docs/services/market-data.md` — `is_partial`, resampling worker
- `docs/MASTER_PLAN.md` — S2 and S3 intraday capability

---

# Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PLAN-0038 A-4/A-5 not yet complete when A-4 starts | Medium | High | Block Wave A-4 explicitly; waves A-1/A-2/A-3 and all Plan B are independent |
| Alpaca IEX feed missing small-cap symbols (OQ-001) | Medium | Low | `ZeroBarTracker` fires → Polygon failover after 5 misses |
| `Timeframe` enum missing intraday values (ONE_MINUTE, FIVE_MINUTES, etc.) | Low | High | Agent must check `domain/enums.py` in Wave B-2 and add if missing |
| `bulk_upsert_derived()` conflict behavior with `is_partial` | Low | Medium | PRD ADR-032-04: always upsert partial bars; they overwrite prior partials for same PK |
| Routing env vars missing in a deployed replica | Low | Low | `ProviderRoutingCache` falls back to `["eodhd"]` — service degrades gracefully to EODHD-only routing |

**Critical path**: A-1 → A-2 → A-3 → (PLAN-0038 A-4+A-5 complete) → A-4 → A-5 → A-6

**Highest risk wave**: A-4 — wires routing cache into `ExecuteTaskUseCase`, removes `_preferred_provider()`, depends on PLAN-0038 completion.

**Rollback strategy**: All changes are additive. Rolling back means:
- S2: Remove Alpaca/Polygon adapters from registry (config flag `ALPACA_API_KEY=""`) and roll back migration 0010
- S3: Roll back migration 008; `IntradayResamplingWorker` process can be stopped independently
- `ProviderRoutingCache=None` in `ExecuteTaskUseCase` → falls back to `_preferred_provider()` (backward compat)

---

# Task Summary

| Plan | Wave | Tasks | Estimated Effort | Depends On |
|---|---|---|---|---|
| A | A-1: Domain + Schema | 4 | 45–60 min | none |
| A | A-2: Adapters | 4 | 60–75 min | A-1 |
| A | A-3: Routing Cache + Registry | 3 | 45–60 min | A-1, A-2 |
| A | A-4: ExecuteTask Wiring + API | 5 | 60–75 min | A-2, A-3, PLAN-0038 done |
| A | A-5: Reclaim Worker | 3 | 60 min | A-3, A-4 |
| A | A-6: Integration Tests + Docs | 3 | 45–60 min | all A |
| B | B-1: OHLCVBar + Migration | 3 | 30–45 min | none |
| B | B-2: ResampledOHLCVUseCase | 3 | 60 min | B-1 |
| B | B-3: IntradayResamplingWorker | 3 | 60 min | B-2 |
| B | B-4: Integration Tests + Docs | 3 | 45 min | all B |
| **Total** | **10 waves** | **34 tasks** | **~9–10 hours** | |

**Parallelizable**: Plan A and Plan B are fully independent and can be executed in parallel worktrees.
Within Plan A: waves A-1, A-2, and A-3 share no files and A-2/A-3 can begin as soon as A-1 finishes.
