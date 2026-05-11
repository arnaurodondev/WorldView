# PLAN-0056 — Polymarket Comprehensive Ingestion (Wave 2)

| Field | Value |
|---|---|
| **Created** | 2026-05-01 |
| **Owner** | Arnau Rodon |
| **Status** | draft |
| **Source PRD** | PRD-0033 (`docs/specs/0033-polymarket-comprehensive-ingestion.md`) |
| **Branch** | `feat/polymarket-wave2` (new branch off `main` after PLAN-0055 merges) |

---

## 0. Overview and Decomposition

### 0.1 What this plan delivers

| Sub-plan | Scope | Risk | Effort |
|---|---|---|---|
| **A — S4 New Adapters + Avro Schemas** | 4 new Avro topics, 4 new clients, 4 new adapters (CLOB history, Gamma events, Data trades, Data OI), `SyntheticDocumentEmitter`, 2 new env vars | MEDIUM | M-L |
| **B — intelligence-migrations 0011** | 6 new tables (`prediction_markets`, `prediction_market_outcomes`, `prediction_market_prices` partitioned, `prediction_events`, `prediction_market_trades` partitioned, `prediction_market_oi`) | LOW | XS |
| **C — S7 Consumers + API Endpoints** | Domain entities, 6 repositories, 5 consumers, 7 new S7 API endpoints with ReadOnlyUoW use cases | MEDIUM | L |
| **D — S9 Proxy Routes** | 7 new proxy routes forwarding to S7 | LOW | XS |

### 0.2 Decomposition rationale

- **Sub-plan A first**: Avro schemas and S4 adapters are the data producers; nothing else can be tested without them.
- **Sub-plan B after A**: The intelligence_db tables must exist before S7 consumers can write to them.
- **Sub-plan C after B**: S7 consumers depend on both the Kafka schemas (A) and the DB tables (B). The S7 API endpoints are implemented in the same sub-plan as the repos they depend on.
- **Sub-plan D last**: S9 is a thin proxy; it only needs S7 endpoints (C) to be available.

### 0.3 Plan dependency graph

```
[A-1: Avro schemas + config]
        │
        ▼
[A-2: S4 domain entities + HTTP clients]
        │
        ▼
[A-3: S4 History + Events adapters]
        │
        ▼
[A-4: S4 Trades + OI adapters + SyntheticDocumentEmitter]
        │
        ▼
[A-5: S4 worker routing + scheduler + docker-compose]
        │
        ├──────────► [B-1: intelligence-migrations 0011] ─────────────────┐
        │                                                                  │
        │                                                       [C-1: S7 domain entities + repos]
        │                                                                  │
        │                                                       [C-2: S7 5 consumers]
        │                                                                  │
        │                                                       [C-3: S7 API endpoints]
        │                                                                  │
        └──────────────────────────────────────────────────► [D-1: S9 proxy routes]
```

A-1..A-5 and B-1 can be executed before C-1. C-1..C-3 require both A (Avro) and B (DB). D-1 requires C-3.

### 0.4 Total scope

| Sub-plan | Waves | Tasks | New Avro schemas | New tables | New env vars | New endpoints |
|---|---|---|---|---|---|---|
| A | 5 | 20 | 4 | 0 | 4 | 0 |
| B | 1 | 2 | 0 | 6 | 0 | 0 |
| C | 3 | 12 | 0 | 0 | 0 | 7 |
| D | 1 | 3 | 0 | 0 | 0 | 7 |
| **Total** | **10** | **37** | **4** | **6** | **4** | **14** |

Estimated total effort: 6–9 implementer-days.

---

## 1. Pre-flight Gate

| Check | Result | Notes |
|---|---|---|
| No BLOCKING open questions | ✅ PASS | OQ-1/2/3 are all tentative-resolved, none classified BLOCKING |
| External API verified | ✅ PASS | §2.1 of PRD verified all Polymarket endpoints against docs |
| No active cross-plan conflicts | ✅ PASS | PLAN-0055 8/8 done; PLAN-0057 touches S6/S7 intelligence model layers not prediction market tables; PLAN-0059 frontend only |
| PRD recency | ✅ PASS | PRD-0033 created 2026-04-29 (2 days old) |
| Architecture compliance | ✅ PASS | PRD §11 checks all RULES.md items |

**⚠️ Active risk**: PLAN-0057 has 9 remaining waves (E-F series). If those waves add intelligence-migrations before PLAN-0056 lands, migration 0011 in Sub-plan B must be renumbered. Check `services/intelligence-migrations/alembic/versions/` for the current head before running B-1.

---

## 2. Codebase State Verification

Read from source before writing any wave tasks:

| PRD Reference | Type | Service | Actual Current State (from code) | PRD Expected | Delta |
|---|---|---|---|---|---|
| `market.prediction.history.v1` | Avro schema | S4 | does not exist | NEW | create `infra/kafka/schemas/market.prediction.history.v1.avsc` |
| `market.prediction.event.v1` | Avro schema | S4 | does not exist | NEW | create file |
| `market.prediction.trade.v1` | Avro schema | S4 | does not exist | NEW | create file |
| `market.prediction.oi.v1` | Avro schema | S4 | does not exist | NEW | create file |
| `ContentSourceType` in `libs/contracts/src/contracts/enums.py` | enum | contracts | has `POLYMARKET` only | add `POLYMARKET_HISTORY`, `POLYMARKET_EVENTS`, `POLYMARKET_TRADES`, `POLYMARKET_OI` | 4 new values |
| `PolymarketProviderSettings` in S4 config | config class | S4 | `base_url`, `page_size`, `max_pages_per_cycle` only (for Gamma `/markets`) | add `clob_base_url`, `data_base_url`, `history_backfill_days`, `trades_backfill_days` | extend |
| S4 worker routing (`worker.py:251`) | code | S4 | routes `POLYMARKET` → `_execute_polymarket_task()` | route 4 new source types to new methods | extend `if/elif` chain |
| S4 outbox dispatcher (`dispatcher_main.py`) | code | S4 | serializes `market.prediction.v1` only | add serializers for 4 new topics | extend `_build_factories()` / `SERIALIZER_MAP` |
| `prediction_markets` | DB table | S7 (intel) | does not exist | NEW | migration 0011+ |
| `prediction_market_outcomes` | DB table | S7 (intel) | does not exist | NEW | migration 0011+ |
| `prediction_market_prices` | DB table (partitioned) | S7 (intel) | does not exist | NEW | migration 0011+ |
| `prediction_events` | DB table | S7 (intel) | does not exist | NEW | migration 0011+ |
| `prediction_market_trades` | DB table (partitioned) | S7 (intel) | does not exist | NEW | migration 0011+ |
| `prediction_market_oi` | DB table | S7 (intel) | does not exist | NEW | migration 0011+ |
| `canonical_entities.entity_type` | DB column | S7 | VARCHAR (free text); existing types: financial_instrument, sector, industry, person, country, macro_indicator, geopolitical_region, political_figure | add string constants `PREDICTION_MARKET` + `PREDICTION_EVENT` | new module `knowledge_graph/domain/prediction_entity_types.py` with constants |
| S7 API routes | endpoints | S7 | no `/api/v1/predictions/*` routes | 7 new routes | create new router module |
| S9 proxy routes | endpoints | S9 | `/signals/prediction-markets` routes → S3 (existing, unchanged) | 7 new `/api/v1/predictions/*` routes → S7 | additive, no conflict |
| `docs/services/api-gateway.md` | docs | S9 | describes 55+ routes | add 7 new routes | update |
| `infra/compose/docker-compose.yml` | infra | S4/S7 | no containers for new consumers | add 5 new consumer containers for S7 | extend |
| `services/content-ingestion/configs/dev.local.env.example` | config | S4 | no `HISTORY_BACKFILL_DAYS` / `TRADES_BACKFILL_DAYS` | add 2 new vars | extend |

---

## 3. Sub-Plan A — S4 New Adapters, Avro Schemas, and SyntheticDocumentEmitter

### A.0 Scope

Extend S4 with 4 new Avro topics, 4 new API clients, 4 new adapters, and a `SyntheticDocumentEmitter` that converts market snapshot events into `content.article.raw.v1` events for the S6 NER pipeline. All existing `market.prediction.v1` production is **unchanged**.

---

### Wave A-1: Avro Schemas + contracts enum + S4 config extension

**Goal**: Land all schema artifacts and configuration extensions. No behavior change. Downstream services (S7) can start consuming against these schemas.
**Depends on**: none
**Estimated effort**: 45–60 min
**Architecture layer**: schema / config

#### Tasks

##### T-A-1-01: 4 new Avro schema files

**Type**: schema
**depends_on**: none
**blocks**: [T-A-2-01, T-C-2-01]
**Target files**:
- `infra/kafka/schemas/market.prediction.history.v1.avsc`
- `infra/kafka/schemas/market.prediction.event.v1.avsc`
- `infra/kafka/schemas/market.prediction.trade.v1.avsc`
- `infra/kafka/schemas/market.prediction.oi.v1.avsc`

**What to build**: Create 4 Avro schema files following the exact field specs in PRD §3.3 and the envelope pattern of `market.prediction.v1`. Every new topic: `event_id` (UUIDv7 string), `occurred_at` (ISO-8601 string with sentinel default "1970-01-01T00:00:00Z"), `schema_version` (int, default 1), `correlation_id` (nullable string). Additional fields per schema:

- **`market.prediction.history.v1`** (`PredictionMarketHistory` record):
  - `market_id: string` (Polymarket `conditionId`)
  - `outcome_token_id: string` (CLOB token ID)
  - `outcome_name: ["null","string"] default null`
  - `interval: string` ("1h", "1d", "1w")
  - `window_start_ts: string` (ISO-8601 UTC)
  - `price: double` (implied probability 0–1)
  - `is_backfill: boolean default false`

- **`market.prediction.event.v1`** (`PredictionEventSnapshot` record):
  - `event_id_gamma: string` (Polymarket Event ID — distinct from envelope `event_id`)
  - `title: string`
  - `category: ["null","string"] default null`
  - `start_date: ["null","string"] default null` (ISO-8601 date string)
  - `end_date: ["null","string"] default null`
  - `market_ids: {type: array, items: string} default []` (child market conditionIds)
  - `description: ["null","string"] default null`

- **`market.prediction.trade.v1`** (`PredictionMarketTrade` record):
  - `market_id: string` (conditionId)
  - `trade_id: string` (Polymarket internal trade ID)
  - `outcome_token_id: string`
  - `price: double`
  - `size_usd: double`
  - `side: string` ("buy" or "sell")
  - `trade_ts: string` (ISO-8601 UTC timestamp of the trade)

- **`market.prediction.oi.v1`** (`PredictionMarketOI` record):
  - `market_id: string` (conditionId)
  - `snapshot_date: string` (YYYY-MM-DD)
  - `total_oi_usd: double`
  - `total_volume_24h_usd: double`

**Downstream test impact**:
- `tests/contract/test_avro_schemas.py` (if it counts schemas or validates field names) — verify new schemas are listed

**Acceptance criteria**:
- [ ] All 4 files exist in `infra/kafka/schemas/`
- [ ] Each file follows the `com.worldview` namespace convention
- [ ] Each schema has sentinel default `"1970-01-01T00:00:00Z"` on `occurred_at`
- [ ] `event_id_gamma` in prediction.event schema is named distinctly from the envelope `event_id`
- [ ] `avro-tools validate` (or equivalent) passes on all 4 files

##### T-A-1-02: contracts enum — 4 new ContentSourceType values

**Type**: impl
**depends_on**: none
**blocks**: [T-A-5-01]
**Target files**: `libs/contracts/src/contracts/enums.py`

**What to build**: Add 4 new `ContentSourceType` values:

```python
POLYMARKET_HISTORY = "polymarket_history"   # CLOB /prices-history per token_id
POLYMARKET_EVENTS = "polymarket_events"     # Gamma /events
POLYMARKET_TRADES = "polymarket_trades"     # Data API /trades
POLYMARKET_OI = "polymarket_oi"             # Data API /oi
```

**Downstream test impact**: Any test that asserts `len(ContentSourceType)` or iterates all values will see 4 more members. Search for `ContentSourceType` in `libs/contracts/tests/` and update assertions.

**Acceptance criteria**:
- [ ] All 4 values present in `ContentSourceType` StrEnum
- [ ] `ruff check` passes on `libs/contracts/`
- [ ] `mypy` passes on `libs/contracts/`
- [ ] Existing enum tests pass (update count assertions if any)

##### T-A-1-03: S4 PolymarketProviderSettings extension + 2 new env vars

**Type**: config
**depends_on**: none
**blocks**: [T-A-2-01]
**Target files**:
- `services/content-ingestion/src/content_ingestion/config.py`
- `services/content-ingestion/configs/dev.local.env.example`
- `services/knowledge-graph/configs/dev.local.env.example` (if any KG env needed)

**What to build**: Extend `PolymarketProviderSettings` in S4 config:

```python
class PolymarketProviderSettings(BaseModel):
    base_url: str = "https://gamma-api.polymarket.com/markets"
    events_base_url: str = "https://gamma-api.polymarket.com/events"
    clob_base_url: str = "https://clob.polymarket.com"          # NEW
    data_base_url: str = "https://data-api.polymarket.com"      # NEW
    page_size: int = 500
    max_pages_per_cycle: int = 20
    history_backfill_days: int = 14                             # NEW (PRD §6)
    trades_backfill_days: int = 14                              # NEW (PRD §6)
```

Add to root `Settings`:
```
CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=14
CONTENT_INGESTION_POLYMARKET_TRADES_BACKFILL_DAYS=14
```

Update `dev.local.env.example` for S4 with the 2 new vars plus comments. Note: these can also be bumped in prod gitops later (PRD §6 says 14d initial, configurable up to 6 months / 90 days).

**Acceptance criteria**:
- [ ] `PolymarketProviderSettings` has all 6 fields
- [ ] `Settings` maps `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS` → `polymarket.history_backfill_days`
- [ ] `dev.local.env.example` updated with both env vars and inline comments
- [ ] `mypy` passes on S4 config module

##### T-A-1-04: Tests for Wave A-1

**Type**: test
**depends_on**: [T-A-1-01, T-A-1-02, T-A-1-03]
**blocks**: none
**Target files**: `libs/contracts/tests/test_enums.py` (or nearest enum test)

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_polymarket_source_types_present` | All 4 new enum values exist and are strings | unit |
| `test_polymarket_settings_defaults` | `PolymarketProviderSettings()` has correct defaults for new fields | unit |
| `test_polymarket_env_var_override` | `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS=7` correctly sets `settings.polymarket.history_backfill_days=7` | unit |

**Acceptance criteria**:
- [ ] 3 new tests pass
- [ ] `ruff check` passes

#### Pre-read (agent must read before starting Wave A-1)
- `infra/kafka/schemas/market.prediction.v1.avsc` — existing schema to follow as template
- `libs/contracts/src/contracts/enums.py` — current enum members
- `services/content-ingestion/src/content_ingestion/config.py` lines 51–60 — `PolymarketProviderSettings`

#### Validation Gate
- [ ] ruff check passes on `libs/contracts/` and `services/content-ingestion/`
- [ ] mypy passes on both packages
- [ ] Unit tests: minimum 3 new tests pass
- [ ] All 4 Avro schema files exist and are valid JSON

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `libs/contracts/tests/test_enums.py` (if exists with count assertions) | ContentSourceType gains 4 values | Update count assertions |
| `tests/contract/test_avro_schemas.py` (if exists) | 4 new schema files | Add 4 new schema names to expected list |

#### Regression Guardrails
- BP-017: Outbox payload field names must match Avro schema field names exactly — the 4 new schemas will have their field names validated in Wave A-5 when the dispatcher serializers are added.
- BP-011: Forward-compat schemas — all new fields must have defaults (checked: every new field has a default or is not in the required list).

---

### Wave A-2: S4 Domain Entities + HTTP Clients

**Goal**: Produce the domain entities and HTTP client infrastructure for the 4 new APIs. No adapter logic yet.
**Depends on**: Wave A-1
**Estimated effort**: 60–90 min
**Architecture layer**: domain + infrastructure

#### Tasks

##### T-A-2-01: S4 domain entities for new fetch results

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: [T-A-3-01, T-A-3-02, T-A-4-01, T-A-4-02]
**Target files**: `services/content-ingestion/src/content_ingestion/domain/entities.py`

**What to build**: Add 4 new frozen dataclasses as fetch result types for the new adapters. Follow the frozen-dataclass-with-factory-method pattern of `PredictionMarketFetchResult`.

**Entities / Components**:

- **`PredictionHistoryPoint`** — one price data point from CLOB `/prices-history`:
  - `market_id: str` (conditionId)
  - `outcome_token_id: str`
  - `outcome_name: str | None`
  - `interval: str` ("1h", "1d", "1w")
  - `window_start_ts: datetime` (UTC-aware)
  - `price: float` (implied probability 0–1, clamped)
  - `is_backfill: bool = False`
  - `fetched_at: datetime`
  - Factory method: `from_clob_response(item: dict, market_id: str, outcome_token_id: str, interval: str, fetched_at: datetime, is_backfill: bool) -> PredictionHistoryPoint`

- **`PredictionEventFetchResult`** — one Gamma event:
  - `event_id_gamma: str`
  - `title: str`
  - `category: str | None`
  - `start_date: str | None` (ISO date string from API)
  - `end_date: str | None`
  - `market_ids: list[str]` (child market conditionIds)
  - `description: str | None`
  - `fetched_at: datetime`
  - Factory: `from_gamma_event(event: dict, fetched_at: datetime) -> PredictionEventFetchResult`

- **`PredictionTradeFetchResult`** — one trade from Data `/trades`:
  - `market_id: str`
  - `trade_id: str`
  - `outcome_token_id: str`
  - `price: float`
  - `size_usd: float`
  - `side: str` ("buy" or "sell")
  - `trade_ts: datetime` (UTC-aware, parsed from API)
  - `fetched_at: datetime`
  - Factory: `from_data_trade(trade: dict, market_id: str, fetched_at: datetime) -> PredictionTradeFetchResult`

- **`PredictionOIFetchResult`** — one OI snapshot from Data `/oi`:
  - `market_id: str` (conditionId)
  - `snapshot_date: str` (YYYY-MM-DD, today's date at fetch time)
  - `total_oi_usd: float`
  - `total_volume_24h_usd: float`
  - `fetched_at: datetime`
  - Factory: `from_data_oi(data: dict, market_id: str, fetched_at: datetime) -> PredictionOIFetchResult`

**Logic & Behavior**:
- All datetimes must be UTC-aware: use `datetime.fromisoformat(...).replace(tzinfo=UTC)` or `common.time.utc_now()`
- `PredictionHistoryPoint.price` must be clamped to `[0.0, 1.0]`; warn if outside range
- `PredictionTradeFetchResult.side` must be normalized to lowercase "buy"/"sell"

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_prediction_history_point_from_clob_response` | Valid CLOB API dict → correct entity fields | unit |
| `test_prediction_history_point_price_clamp` | price > 1.0 or < 0.0 → clamped to boundary | unit |
| `test_prediction_event_from_gamma_event` | Gamma event dict with market_ids → entity | unit |
| `test_prediction_trade_from_data_trade` | Data trade dict → entity with UTC datetime | unit |
| `test_prediction_oi_from_data_oi` | Data OI dict → entity | unit |

**Acceptance criteria**:
- [ ] 4 new frozen dataclasses in `entities.py`
- [ ] Each has a `from_*` factory method
- [ ] 5 unit tests pass
- [ ] mypy strict passes

##### T-A-2-02: S4 HTTP clients for CLOB and Data APIs

**Type**: impl
**depends_on**: [T-A-1-03]
**blocks**: [T-A-3-01, T-A-3-02, T-A-4-01, T-A-4-02]
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/clob_client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/data_client.py`
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/event_client.py` (Gamma /events endpoint)

**What to build**: Follow the pattern of `PolymarketClient` — stateless, `httpx.AsyncClient`-injected, raises `AdapterError` on non-200.

**`PolymarketClobClient`**:
- `async def fetch_price_history(token_id: str, *, interval: str, start_ts: int | None = None, end_ts: int | None = None) -> list[dict]`
  - GET `{clob_base_url}/prices-history?token_id={token_id}&interval={interval}&start_ts={start_ts}&end_ts={end_ts}`
  - On 400 or empty list for an active market: caller should retry with `interval="1d"` (document this in docstring)
  - Returns list of `{t: int, p: str}` dicts from the API's `history` array
  - 429 → raise `AdapterError` with message "rate_limited" so caller can backoff

**`PolymarketDataClient`**:
- `async def fetch_trades(market_id: str, *, limit: int = 1000, cursor: str | None = None) -> tuple[list[dict], str | None]`
  - GET `{data_base_url}/trades?market={market_id}&limit={limit}` + optional `&next_cursor={cursor}`
  - Returns `(trades, next_cursor_or_none)`
- `async def fetch_oi(market_id: str) -> dict | None`
  - GET `{data_base_url}/oi?market_id={market_id}`
  - Returns raw dict or None if 404/empty

**`PolymarketEventClient`**:
- `async def fetch_events_page(*, limit: int = 500, next_cursor: str | None = None) -> tuple[list[dict], str | None]`
  - GET `{events_base_url}?limit={limit}` + optional cursor
  - Returns `(events, next_cursor_or_none)`

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_clob_client_fetch_returns_history_list` | Mock HTTP 200 → returns parsed history list | unit |
| `test_clob_client_429_raises_adapter_error` | Mock HTTP 429 → raises AdapterError | unit |
| `test_data_client_fetch_trades_pagination` | Mock response with next_cursor → cursor returned | unit |
| `test_data_client_fetch_oi_404_returns_none` | Mock HTTP 404 → returns None | unit |
| `test_event_client_fetch_events_page` | Mock HTTP 200 → events list + cursor | unit |

**Acceptance criteria**:
- [ ] 3 new client classes
- [ ] All raise `AdapterError` (not raw exceptions) on non-200
- [ ] 5 unit tests pass
- [ ] mypy passes

#### Pre-read (agent must read before starting Wave A-2)
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/client.py` — pattern to follow
- `services/content-ingestion/src/content_ingestion/domain/entities.py` — `PredictionMarketFetchResult.from_gamma_response()` — pattern for factory methods

#### Validation Gate
- [ ] ruff check on `services/content-ingestion/`
- [ ] mypy passes
- [ ] Unit tests: minimum 10 new tests pass (5 entity + 5 client)

#### Break Impact
*(No existing files break — pure additions)*

#### Regression Guardrails
- BP-026: httpx connections — clients receive shared `httpx.AsyncClient` injected by worker, never create their own. Check `PolymarketClient.__init__` pattern.
- BP-005: UTC timestamps — all `datetime` fields in entities must be UTC-aware; enforce in factory methods.

---

### Wave A-3: S4 History and Events Adapters

**Goal**: Implement `PolymarketHistoryAdapter` and `PolymarketEventAdapter` — the two highest-priority new adapters.
**Depends on**: Wave A-2
**Estimated effort**: 90–120 min
**Architecture layer**: infrastructure / adapters

#### Tasks

##### T-A-3-01: PolymarketHistoryAdapter

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/history_adapter.py`

**What to build**: An adapter that fetches `prices-history` per token_id for a given set of markets. Works in two modes:
- **Backfill mode** (`is_backfill=True`): fetches from `now - history_backfill_days` to now; `interval="1h"` for open markets, `interval="1d"` for resolved/closed.
- **Ongoing mode**: fetches from last 6 hours; `interval="1h"`.

**Logic & Behavior**:
1. Accept `source: Source` and `from_date: str = ""` (unused for history, which is token-driven).
2. Fetch the current list of active markets from the existing `PolymarketClient` (or accept a pre-fetched list via constructor injection to avoid duplicated API calls). For each market → for each `outcome_token_id`:
   a. Compute `start_ts` (epoch seconds) from `is_backfill` + `settings.history_backfill_days` vs. 6-hour window.
   b. Call `PolymarketClobClient.fetch_price_history(token_id, interval="1h", start_ts=..., end_ts=now_ts)`
   c. If the response is empty AND the market is not resolved → retry with `interval="1d"` (one retry only, per PRD §8.1).
   d. Convert each `{t, p}` dict to `PredictionHistoryPoint`.
3. Returns `list[PredictionHistoryPoint]`.
4. Rate limit: yield to event loop between markets using `await asyncio.sleep(0)` to avoid blocking; no explicit sleep needed (see PRD §2.3: total consumption ≤ 5% of CLOB rate limit).
5. 429 from CLOB → exponential backoff: `asyncio.sleep(2**attempt)`, max 3 retries, then raise `AdapterError`.

**Error classification**:
- `AdapterError` wrapping HTTP 429 → `Retryable`
- Parse errors on individual history points → log WARNING, skip point (non-fatal)
- `AdapterError` wrapping 5xx → `Retryable` with `task.fail()`

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_history_adapter_fetch_backfill_mode` | is_backfill=True → start_ts is ~14 days ago | unit |
| `test_history_adapter_empty_response_retries_with_1d` | Empty 1h response → retries with 1d interval | unit |
| `test_history_adapter_429_exponential_backoff` | Mock 3× 429 then 200 → backoff sleeps called | unit |
| `test_history_adapter_parse_error_skips_point` | One malformed {t, p} → warning logged, other points returned | unit |
| `test_history_adapter_ongoing_mode_6h_window` | is_backfill=False → start_ts is ~6 hours ago | unit |

**Acceptance criteria**:
- [ ] Adapter returns `list[PredictionHistoryPoint]`
- [ ] Empty-response → 1d retry is implemented and tested
- [ ] 429 → exponential backoff implemented and tested
- [ ] 5 unit tests pass

##### T-A-3-02: PolymarketEventAdapter

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/event_adapter.py`

**What to build**: Adapter that polls Gamma `/events` with cursor pagination (1-hour cadence). No dedup by snapshot time — dedup is done on `event_id_gamma` uniqueness (S7 consumer uses ON CONFLICT DO UPDATE).

**Logic & Behavior**:
1. Cursor-paginated fetch up to `max_pages_per_cycle` pages (reuse the same setting).
2. For each event dict → `PredictionEventFetchResult.from_gamma_event(event, fetched_at)`.
3. Returns `list[PredictionEventFetchResult]`.
4. 429 → raise `AdapterError("rate_limited")`.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_event_adapter_paginates_correctly` | Two pages with cursor → fetches both | unit |
| `test_event_adapter_stops_at_max_pages` | max_pages_per_cycle=1 → stops after first page | unit |
| `test_event_adapter_empty_market_ids` | Event with no child markets → empty list returned | unit |

**Acceptance criteria**:
- [ ] Adapter paginates and returns `list[PredictionEventFetchResult]`
- [ ] 3 unit tests pass

#### Pre-read (agent must read before starting Wave A-3)
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/adapter.py` — PolymarketAdapter pattern
- `services/content-ingestion/src/content_ingestion/domain/exceptions.py` — AdapterError class

#### Validation Gate
- [ ] ruff check + mypy on `services/content-ingestion/`
- [ ] Unit tests: minimum 8 new tests pass
- [ ] No `async def` method holds a DB session across I/O (R22)

#### Break Impact
*(Pure additions — no existing files break)*

#### Regression Guardrails
- BP-016: Advisory lock spanning external I/O — no session held during CLOB/Data API calls
- BP-026: httpx client lifecycle — ensure `PolymarketClobClient` and `PolymarketEventClient` receive injected shared client

---

### Wave A-4: S4 Trades + OI Adapters and SyntheticDocumentEmitter

**Goal**: Implement the remaining 2 adapters and the `SyntheticDocumentEmitter` that converts Polymarket market snapshots into `content.article.raw.v1` events for S6.
**Depends on**: Wave A-2
**Estimated effort**: 90–120 min
**Architecture layer**: infrastructure / adapters + application

#### Tasks

##### T-A-4-01: PolymarketTradesAdapter

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/trades_adapter.py`

**What to build**: Adapter that fetches recent trades from Data `/trades` per market. In backfill mode, fetches last `trades_backfill_days` days of trades; in ongoing mode, uses a cursor-based watermark.

**Logic & Behavior**:
1. Per market_id: cursor-paginated fetch up to 10 pages of trades.
2. For backfill: filter trades where `trade_ts >= (now - trades_backfill_days)`.
3. Dedup by `trade_id` using a set within the fetch cycle (not a DB call — deduplicated by S7 consumer ON CONFLICT DO NOTHING).
4. Returns `list[PredictionTradeFetchResult]`.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_trades_adapter_backfill_filters_old_trades` | trade_ts before backfill window → excluded | unit |
| `test_trades_adapter_deduplicates_by_trade_id` | Same trade_id in two pages → returned once | unit |
| `test_trades_adapter_pagination_stops` | max 10 pages respected | unit |

##### T-A-4-02: PolymarketOIAdapter

**Type**: impl
**depends_on**: [T-A-2-01, T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/oi_adapter.py`

**What to build**: Simple daily adapter that fetches OI snapshot per active market.

**Logic & Behavior**:
1. Get list of active market conditionIds (injected; same pattern as HistoryAdapter).
2. For each market: `PolymarketDataClient.fetch_oi(market_id)` → `PredictionOIFetchResult`.
3. Returns `list[PredictionOIFetchResult]`. 404 per market is non-fatal (log DEBUG, skip).

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_oi_adapter_skips_404_markets` | market returns 404 → skipped, others returned | unit |
| `test_oi_adapter_builds_snapshot` | Valid OI response → PredictionOIFetchResult with today's date | unit |

##### T-A-4-03: SyntheticDocumentEmitter

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-5-01]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/synthetic_doc_emitter.py`

**What to build**: Converts a `PredictionMarketFetchResult` into a `RawArticle`-equivalent payload for `content.article.raw.v1`. This is **not** a `SourceAdapterPort` — it's called by the worker after a successful `PolymarketAdapter.fetch()`. Checks whether the market is first-seen or resolving; emits at most 2 documents per market lifetime.

**Entities / Components**:
- **`SyntheticDocumentEmitter`** class with:
  - `__init__(fetch_log_exists_fn, add_to_outbox_fn)` — both async callables
  - `async def emit_if_new(result: PredictionMarketFetchResult) -> bool`
    - Dedup key: `"polymarket:" + condition_id` → hash as URL hash
    - If `NOT EXISTS` in fetch_log → build doc body → add to outbox as `content.article.raw.v1` → record in fetch_log → return True
    - If the market is now `resolved` AND a resolution doc has not been emitted → emit a second doc with `"[RESOLVED] " + question` title
    - Return False if no doc emitted

**Synthetic document body format** (PRD §5.2):
```
{question}

Outcomes:
- {outcome.name}: {outcome.price * 100:.1f}% (${outcome.volume_24h:,.0f} 24h vol)

Market closes {close_time}.
Category: {category}.
[Belongs to event: {event_name}]
```

**Key points**:
- `source_type = "prediction_market"` (ContentSourceType.POLYMARKET becomes the source, but `source_type` field in the article is `"prediction_market"` per PRD §5.2)
- `external_id = "polymarket:{condition_id}"` used as the URL for hash dedup
- `published_at = close_time` (resolution date as the article date)
- `doc_id = new_uuid7()` (new UUIDv7 per document)

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_emitter_first_seen_market_emits` | New market → outbox populated, fetch_log recorded | unit |
| `test_emitter_duplicate_market_skips` | Same conditionId already in fetch_log → no emit | unit |
| `test_emitter_resolved_market_emits_resolution_doc` | Market resolves → second doc emitted with [RESOLVED] prefix | unit |
| `test_emitter_resolution_doc_not_duplicated` | Resolution already emitted → no third doc | unit |
| `test_emitter_body_format_correct` | Doc body contains outcomes with price% format | unit |

**Acceptance criteria**:
- [ ] `emit_if_new` is idempotent
- [ ] At most 2 docs emitted per market lifetime
- [ ] 5 unit tests pass

#### Pre-read
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/adapter.py` — fetch result pattern
- `services/content-ingestion/src/content_ingestion/domain/entities.py` — `PredictionMarketFetchResult` fields

#### Validation Gate
- [ ] ruff check + mypy on `services/content-ingestion/`
- [ ] Unit tests: minimum 10 new tests pass (3+2+5)

#### Break Impact
*(Pure additions)*

#### Regression Guardrails
- BP-057: No DB session in adapter itself — `SyntheticDocumentEmitter` must receive async callables for DB interaction, never import a repo directly
- BP-017: `content.article.raw.v1` outbox payload field names must exactly match the existing Avro schema — read `infra/kafka/schemas/content.article.raw.v1.avsc` before building the payload dict

---

### Wave A-5: S4 Worker Routing, Scheduler, Dispatcher, and Docker

**Goal**: Wire all 4 new source types into the existing worker-scheduler-dispatcher machinery. Update docker-compose for new S7 consumer containers.
**Depends on**: Waves A-3 and A-4 (all adapters done)
**Estimated effort**: 60–90 min
**Architecture layer**: infrastructure / wiring

#### Tasks

##### T-A-5-01: S4 worker routing for 4 new source types

**Type**: impl
**depends_on**: [T-A-3-01, T-A-3-02, T-A-4-01, T-A-4-02, T-A-4-03, T-A-1-02]
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py`

**What to build**: Extend the `if task.source_type == SourceType.POLYMARKET:` dispatch in `WorkerProcess._execute_task()` with `elif` branches for the 4 new source types. Each branch calls the appropriate adapter + emits Avro events via outbox.

Pattern from `_execute_polymarket_task()`:
```python
elif task.source_type == SourceType.POLYMARKET_HISTORY:
    await self._execute_polymarket_history_task(task)
elif task.source_type == SourceType.POLYMARKET_EVENTS:
    await self._execute_polymarket_events_task(task)
elif task.source_type == SourceType.POLYMARKET_TRADES:
    await self._execute_polymarket_trades_task(task)
elif task.source_type == SourceType.POLYMARKET_OI:
    await self._execute_polymarket_oi_task(task)
```

Each `_execute_polymarket_*_task()` method:
1. Builds the appropriate adapter (history/events/trades/oi) with injected clients
2. Calls `adapter.fetch(source, is_backfill=task.is_backfill)`
3. For each result: calls outbox to serialize + write (via `FetchAndWritePredictionMarketsUseCase` extended or a new use case)
4. Calls `SyntheticDocumentEmitter.emit_if_new()` in the POLYMARKET_EVENTS and base POLYMARKET routes (when market snapshot arrives)

**Note**: The `SyntheticDocumentEmitter` is called from the existing `POLYMARKET` (Gamma /markets) path — add the call after the market snapshot is stored. The history/trades/oi adapters do NOT emit synthetic documents.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_worker_routes_history_task` | Task with POLYMARKET_HISTORY source_type → calls history adapter | unit |
| `test_worker_routes_events_task` | POLYMARKET_EVENTS → calls event adapter | unit |
| `test_worker_synthetic_emitter_called_on_market_snapshot` | POLYMARKET task → SyntheticDocumentEmitter.emit_if_new() called | unit |

##### T-A-5-02: S4 outbox dispatcher serializer extensions

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher_main.py`

**What to build**: Add Avro serializers for the 4 new Kafka topics to `SERIALIZER_MAP` (or equivalent factory in dispatcher). Each serializer maps topic → `(schema_file, record_name)`.

**Acceptance criteria**:
- [ ] `market.prediction.history.v1` → `market.prediction.history.v1.avsc` wired
- [ ] Same for event, trade, OI topics
- [ ] Dispatcher logs "unknown topic" if an outbox event has an unrecognized topic name

##### T-A-5-03: Scheduler source seeding + docker-compose

**Type**: config + impl
**depends_on**: [T-A-1-02, T-A-1-03]
**blocks**: none
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/scheduler/scheduler_process.py` (or scheduler.py — whichever seeds sources)
- `infra/compose/docker-compose.yml` (or docker-compose.dev.yml)

**What to build**:
1. Seed 4 new source rows on startup via `CreateSourceUseCase` (idempotent ON CONFLICT DO NOTHING from PLAN-0055):
   - `POLYMARKET_HISTORY` — interval 6h ongoing, `is_backfill=True` on first run
   - `POLYMARKET_EVENTS` — interval 1h
   - `POLYMARKET_TRADES` — interval 1h
   - `POLYMARKET_OI` — interval 24h
2. Add 5 new Docker containers for S7 consumers (added in Wave C-2):
   - `kg-prediction-market-consumer`
   - `kg-prediction-event-consumer`
   - `kg-prediction-history-consumer`
   - `kg-prediction-trades-consumer`
   - `kg-prediction-oi-consumer`

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_scheduler_seeds_polymarket_history_source` | Idempotent seed → source row in DB | integration (skip if no infra) |

#### Pre-read
- `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py` lines 244–260 — existing POLYMARKET dispatch
- `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher_main.py` — `_build_factories()` / serializer map

#### Validation Gate
- [ ] ruff check + mypy on `services/content-ingestion/`
- [ ] Unit tests: minimum 3 new tests pass
- [ ] Docker compose: 5 new service definitions are syntactically valid
- [ ] Dispatcher SERIALIZER_MAP has all 4 new topic entries

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/content-ingestion/tests/unit/test_worker.py` | Worker dispatch routing has new branches | Ensure new branches don't break existing tests; add new test cases |

#### Regression Guardrails
- BP-017: Avro field names in outbox payload dict must match schema field names exactly — double-check each of the 4 new outbox serializers against their `.avsc` definitions.
- BP-009: Dispatcher config derived from settings — dispatcher must use settings-based URLs for new schema registry entries.

---

## 4. Sub-Plan B — intelligence-migrations 0011

### Wave B-1: 6 New Prediction Market Tables

**Goal**: Add all 6 prediction-market tables to `intelligence_db` in a single migration. All future S7 consumers depend on this.
**Depends on**: None (can run in parallel with Sub-Plan A)
**Estimated effort**: 30–45 min
**Architecture layer**: schema

#### Pre-read
- `services/intelligence-migrations/alembic/versions/0010_index_alias_norm_for_stage2.py` — current head (revision = "0010")
- Verify current head: `ls services/intelligence-migrations/alembic/versions/` — if new migrations exist above 0010, renumber this migration

#### Tasks

##### T-B-1-01: Migration 0011 — 6 prediction market tables

**Type**: schema
**depends_on**: none
**blocks**: [T-C-1-01, T-C-2-01]
**Target files**: `services/intelligence-migrations/alembic/versions/0011_prediction_market_tables.py`

**What to build**: One migration file with `upgrade()` that creates all 6 tables idempotently (`CREATE TABLE IF NOT EXISTS`).

**Table definitions** (from PRD §3.4):

```sql
-- 1. prediction_events (no partition)
CREATE TABLE IF NOT EXISTS prediction_events (
    event_id_gamma    TEXT        PRIMARY KEY,
    title             TEXT        NOT NULL,
    category          TEXT,
    start_date        DATE,
    end_date          DATE,
    market_count      INT         NOT NULL DEFAULT 0,
    description       TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. prediction_markets (no partition)
CREATE TABLE IF NOT EXISTS prediction_markets (
    condition_id       TEXT        PRIMARY KEY,
    event_id_gamma     TEXT        REFERENCES prediction_events(event_id_gamma) ON DELETE SET NULL,
    question           TEXT        NOT NULL,
    category           TEXT,
    status             TEXT        NOT NULL DEFAULT 'open',  -- 'open'|'resolved'|'cancelled'
    close_time         TIMESTAMPTZ,
    resolved_outcome   TEXT,
    market_slug        TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prediction_markets_event ON prediction_markets(event_id_gamma);
CREATE INDEX IF NOT EXISTS idx_prediction_markets_status ON prediction_markets(status);
CREATE INDEX IF NOT EXISTS idx_prediction_markets_category ON prediction_markets(category);

-- 3. prediction_market_outcomes (no partition)
CREATE TABLE IF NOT EXISTS prediction_market_outcomes (
    condition_id       TEXT        NOT NULL REFERENCES prediction_markets(condition_id) ON DELETE CASCADE,
    token_id           TEXT        NOT NULL,
    outcome_name       TEXT,
    last_price         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    last_volume_24h    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (condition_id, token_id)
);

-- 4. prediction_market_prices (RANGE partitioned by month on window_start_ts)
CREATE TABLE IF NOT EXISTS prediction_market_prices (
    condition_id       TEXT        NOT NULL,
    token_id           TEXT        NOT NULL,
    interval           TEXT        NOT NULL,  -- '1h'|'1d'|'1w'
    window_start_ts    TIMESTAMPTZ NOT NULL,
    price              DOUBLE PRECISION NOT NULL,
    source             TEXT        NOT NULL DEFAULT 'clob',
    PRIMARY KEY (condition_id, token_id, interval, window_start_ts)
) PARTITION BY RANGE (window_start_ts);

-- Seed initial monthly partitions (2024-01 through 2026-12)
-- Pattern: CREATE TABLE prediction_market_prices_YYYY_MM PARTITION OF prediction_market_prices
--          FOR VALUES FROM ('YYYY-MM-01') TO ('YYYY-MM+1-01')
-- Create partitions for 2025-01 through 2026-12 (25 partitions)
-- (Agent: write a loop or explicit CREATE statements — explicit is safer for Alembic)

-- 5. prediction_market_trades (RANGE partitioned by month on trade_ts)
CREATE TABLE IF NOT EXISTS prediction_market_trades (
    market_id          TEXT        NOT NULL,
    trade_id           TEXT        NOT NULL,
    token_id           TEXT        NOT NULL,
    price              DOUBLE PRECISION NOT NULL,
    size_usd           DOUBLE PRECISION NOT NULL,
    side               TEXT        NOT NULL,  -- 'buy'|'sell'
    trade_ts           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (market_id, trade_id)
) PARTITION BY RANGE (trade_ts);
-- Seed partitions 2025-01 through 2026-12

-- 6. prediction_market_oi (no partition — daily snapshots, small table)
CREATE TABLE IF NOT EXISTS prediction_market_oi (
    condition_id       TEXT        NOT NULL,
    snapshot_date      DATE        NOT NULL,
    total_oi_usd       DOUBLE PRECISION NOT NULL,
    total_volume_24h_usd DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (condition_id, snapshot_date)
);
```

**Key points**:
- Partitioned tables use explicit `CREATE TABLE ... PARTITION OF ... FOR VALUES FROM ... TO ...` statements (no triggers or functions — Alembic handles static DDL).
- All timestamps `TIMESTAMPTZ` (never plain `TIMESTAMP`).
- `prediction_market_prices` PRIMARY KEY includes the partition key `window_start_ts` (PostgreSQL requirement for partitioned tables).
- `prediction_market_trades` PK is `(market_id, trade_id)` — NOT partition-key-inclusive because `trade_id` uniquely identifies a trade regardless of month. However, PostgreSQL requires partition key in PK for declarative partitioning. **Fix**: use `(market_id, trade_id, trade_ts)` as PK.
- The `downgrade()` drops all tables in reverse dependency order.

**Downstream test impact**:
- `services/knowledge-graph/tests/` integration tests that run against a live intelligence_db will gain these tables; no breakage expected.
- `services/intelligence-migrations/tests/` (if any) — confirm migration chain is unbroken.

**Tests to write** (as part of this task):

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_migration_0011_upgrade` | Migration applies cleanly on clean DB | integration |
| `test_migration_0011_downgrade` | `downgrade()` drops all 6 tables cleanly | integration |

**Acceptance criteria**:
- [ ] Migration file exists with revision "0011" and down_revision "0010"
- [ ] All 6 tables created with `IF NOT EXISTS`
- [ ] Partitions created for 2025-01 through 2026-12 on both partitioned tables
- [ ] `downgrade()` is the reverse of `upgrade()`
- [ ] Migration applies without error on a clean intelligence_db

##### T-B-1-02: Update entity_type constants for S7

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-01]
**Target files**: `services/knowledge-graph/src/knowledge_graph/domain/` (new file: `prediction_entity_types.py`)

**What to build**: Module with two string constants used by S7 when creating canonical entities for prediction markets:

```python
PREDICTION_MARKET_ENTITY_TYPE = "prediction_market"
PREDICTION_EVENT_ENTITY_TYPE = "prediction_event"
```

No enum class — `canonical_entities.entity_type` is a free VARCHAR. These constants prevent typos.

**Acceptance criteria**:
- [ ] Module exists with 2 constants
- [ ] ruff + mypy pass

#### Pre-read (agent must read before starting Wave B-1)
- `services/intelligence-migrations/alembic/versions/0010_index_alias_norm_for_stage2.py` — revision/down_revision chain
- `services/intelligence-migrations/alembic/versions/0004_geopolitical_age_temporal_events.py` — example of a complex migration with partitioned tables

#### Validation Gate
- [ ] Migration file parses (valid Python, no syntax errors)
- [ ] `alembic upgrade head` succeeds on clean intelligence_db (run in test container)
- [ ] `alembic downgrade -1` succeeds
- [ ] All 6 tables exist after upgrade

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/intelligence-migrations/alembic/env.py` | New revision chain must be continuous | Verify `down_revision = "0010"` is correct — if PLAN-0057 added 0011 already, renumber to 0012 |

#### Regression Guardrails
- BP-004: Alembic migration target — always set `down_revision` to the actual current head (read the file listing before writing the migration)
- BP-005: All timestamp columns must be `TIMESTAMPTZ` — verified in every CREATE TABLE above

---

## 5. Sub-Plan C — S7 Consumers + API Endpoints

### Wave C-1: S7 Domain Entities, Ports, and Repositories

**Goal**: Create the S7 domain layer for prediction markets and the 6 new repositories. No consumers yet.
**Depends on**: Waves B-1, A-1 (need Avro schemas + DB tables)
**Estimated effort**: 90–120 min
**Architecture layer**: domain + infrastructure

#### Tasks

##### T-C-1-01: S7 prediction market domain entities

**Type**: impl
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: [T-C-1-02, T-C-2-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/domain/prediction_market.py`

**What to build**: 6 frozen dataclasses matching the DB tables in B-1.

**Entities / Components**:

- **`PredictionEvent`**: `event_id_gamma: str`, `title: str`, `category: str | None`, `start_date: date | None`, `end_date: date | None`, `market_count: int`, `description: str | None`, `updated_at: datetime`

- **`PredictionMarket`**: `condition_id: str`, `event_id_gamma: str | None`, `question: str`, `category: str | None`, `status: str` ("open"/"resolved"/"cancelled"), `close_time: datetime | None`, `resolved_outcome: str | None`, `market_slug: str | None`, `created_at: datetime`, `updated_at: datetime`

- **`PredictionMarketOutcome`**: `condition_id: str`, `token_id: str`, `outcome_name: str | None`, `last_price: float`, `last_volume_24h: float`, `updated_at: datetime`

- **`PredictionMarketPricePoint`**: `condition_id: str`, `token_id: str`, `interval: str`, `window_start_ts: datetime`, `price: float`, `source: str`

- **`PredictionMarketTrade`**: `market_id: str`, `trade_id: str`, `token_id: str`, `price: float`, `size_usd: float`, `side: str`, `trade_ts: datetime`

- **`PredictionMarketOI`**: `condition_id: str`, `snapshot_date: date`, `total_oi_usd: float`, `total_volume_24h_usd: float`

**Acceptance criteria**:
- [ ] 6 frozen dataclasses in domain module
- [ ] All datetime fields have UTC-aware type hints (`datetime` — validated in factory methods of consumers)
- [ ] mypy passes (strict)

##### T-C-1-02: S7 prediction market ports + repositories

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-2-01, T-C-3-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/ports/prediction_market_ports.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/prediction_market_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/prediction_event_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/prediction_price_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/prediction_trade_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/prediction_oi_repository.py`

**What to build**: 5 `@runtime_checkable Protocol` port interfaces + 5 repository implementations (outcomes are part of the market repository).

**Key SQL patterns per repository**:
- `PredictionMarketRepository.upsert(market)` → `INSERT INTO prediction_markets (...) ON CONFLICT (condition_id) DO UPDATE SET question=EXCLUDED.question, status=EXCLUDED.status, ...`; also upserts outcomes
- `PredictionEventRepository.upsert(event)` → `ON CONFLICT (event_id_gamma) DO UPDATE`
- `PredictionPriceRepository.upsert_batch(points: list[PredictionMarketPricePoint])` → `INSERT INTO prediction_market_prices (...) ON CONFLICT (...) DO NOTHING` — idempotent, duplicate is no-op
- `PredictionTradeRepository.upsert_batch(trades)` → `ON CONFLICT (market_id, trade_id, trade_ts) DO NOTHING`
- `PredictionOIRepository.upsert(oi)` → `ON CONFLICT (condition_id, snapshot_date) DO UPDATE`

**Read-side methods** (for use cases in Wave C-3):
- `PredictionMarketRepository.list_markets(category: str | None, event_id_gamma: str | None, status: str | None, q: str | None, limit: int, offset: int) -> tuple[list[PredictionMarket], int]`
- `PredictionMarketRepository.get_by_condition_id(condition_id: str) -> PredictionMarket | None`
- `PredictionMarketRepository.get_outcomes(condition_id: str) -> list[PredictionMarketOutcome]`
- `PredictionPriceRepository.get_history(condition_id: str, token_id: str, interval: str, since: datetime | None, limit: int) -> list[PredictionMarketPricePoint]`
- `PredictionTradeRepository.get_trades(condition_id: str, since: datetime | None, limit: int) -> list[PredictionMarketTrade]`
- `PredictionEventRepository.list_events(limit: int, offset: int) -> tuple[list[PredictionEvent], int]`
- `PredictionEventRepository.get_by_id(event_id_gamma: str) -> PredictionEvent | None`
- `PredictionEventRepository.get_markets_for_event(event_id_gamma: str) -> list[PredictionMarket]`

**For entity predictions via KG** (needed for `GET /entities/{id}/predictions`):
- `PredictionMarketRepository.get_by_entity_id(entity_id: UUID) -> list[PredictionMarket]` — JOIN `relations` table on `(subject_entity_id=entity_id OR object_entity_id=entity_id)` WHERE `canonical_type IN ('references', 'resolved_to')` AND `subject` is a prediction_market entity.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_market_repo_upsert_idempotent` | Same condition_id twice → one row, last write wins | unit (mocked session) |
| `test_price_repo_upsert_batch_no_conflict` | Duplicate (condition_id, token_id, interval, ts) → no error | unit |
| `test_event_repo_upsert_new_and_update` | New event → INSERT; same event_id_gamma again → UPDATE title | unit |
| `test_trade_repo_upsert_batch_dedup` | Same trade_id twice → one row | unit |
| `test_market_repo_list_with_category_filter` | category="crypto" → only crypto markets returned | unit (mocked) |

**Acceptance criteria**:
- [ ] 5 port Protocol classes
- [ ] 5 repository implementations with write (upsert) and read methods
- [ ] 5 unit tests pass
- [ ] R25 compliance: repositories are only instantiated in `api/dependencies.py` factory functions, never in route bodies

#### Pre-read (agent must read before starting Wave C-1)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_repository.py` — repository pattern
- `services/knowledge-graph/src/knowledge_graph/application/ports/` — existing port Protocol pattern

#### Validation Gate
- [ ] ruff check + mypy on `services/knowledge-graph/`
- [ ] Unit tests: minimum 8 new tests
- [ ] R12: domain module has zero `infrastructure/` imports

#### Break Impact
*(Pure additions)*

#### Regression Guardrails
- BP-005: All timestamp columns `TIMESTAMPTZ` — confirmed in migration; repositories must use UTC-aware datetimes
- R25: No direct infrastructure import in API routes — wired through ports in Wave C-3

---

### Wave C-2: S7 Prediction Market Consumers (5 consumers)

**Goal**: Implement all 5 new Kafka consumers for prediction market topics.
**Depends on**: Wave C-1
**Estimated effort**: 90–120 min
**Architecture layer**: infrastructure / messaging

#### Tasks

##### T-C-2-01: PredictionMarketUpserter (market.prediction.v1 → prediction_markets + entities)

**Type**: impl
**depends_on**: [T-C-1-02, T-A-1-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_market_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_market_consumer_main.py`

**What to build**: Consumes **existing** `market.prediction.v1` topic. For each snapshot:
1. Upsert `prediction_markets` row + outcomes.
2. If market is new (first time condition_id seen): create a `canonical_entities` row with `entity_type = "prediction_market"`, `canonical_name = question[:200]`, `ticker = None`, `metadata = {"condition_id": condition_id, "category": category}`.
3. If `event_id_gamma` present: upsert `belongs_to_event` relation in `relations` table (subject=market entity, object=event entity when available).
4. If `resolution_status == "resolved"` and `resolved_answer` is set: upsert `resolved_to` relation.
5. Valkey dedup on `event_id` (same pattern as `TemporalEventConsumer`).

**Logic**: Use `BaseKafkaConsumer` from `libs/messaging`. Consume as JSON (existing `market.prediction.v1` uses JSON, not Confluent Avro wire format). Per-message: parse fields, call use case, commit.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_prediction_market_consumer_upserts_market` | Valid v1 message → prediction_markets row | unit |
| `test_prediction_market_consumer_creates_kg_entity` | First-seen market → canonical_entities row | unit |
| `test_prediction_market_consumer_resolved_creates_relation` | resolved=True → resolved_to relation | unit |
| `test_prediction_market_consumer_valkey_dedup` | Same event_id twice → processed once | unit |

##### T-C-2-02: PredictionEventConsumer, PredictionPriceHistoryConsumer, PredictionTradeConsumer, PredictionOIConsumer

**Type**: impl
**depends_on**: [T-C-1-02, T-A-1-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_event_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_event_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_price_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_price_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_trade_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_trade_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_oi_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/prediction_oi_consumer_main.py`

**What to build**: 4 simple consumers, each:
1. Consumes its topic (`market.prediction.event.v1`, `market.prediction.history.v1`, `market.prediction.trade.v1`, `market.prediction.oi.v1`).
2. Parses Avro/JSON payload into the corresponding domain entity.
3. Calls the appropriate repository upsert.
4. Commits. Valkey dedup on `event_id`.

**PredictionEventConsumer** additionally:
- Creates `canonical_entities` row for the event if first-seen (`entity_type = "prediction_event"`).
- Creates `belongs_to_event` relations for each child `market_id` in `market_ids` list (if the market's canonical entity already exists in KG).

**PredictionPriceHistoryConsumer**:
- Batch-upserts via `PredictionPriceRepository.upsert_batch()` — accumulate messages in the consumer's batch window, then commit.

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_event_consumer_creates_kg_entity` | New event → canonical_entities row created | unit |
| `test_price_consumer_upserts_history` | Valid history message → price row inserted | unit |
| `test_trade_consumer_deduplicates` | Same trade_id twice → one DB row | unit |
| `test_oi_consumer_updates_existing` | Same (condition_id, date) twice → UPDATE | unit |

**Acceptance criteria for Wave C-2**:
- [ ] 5 consumer classes + 5 main entry points
- [ ] All use Valkey dedup
- [ ] All handle `AdapterError`-class decode failures gracefully (log + skip to DLQ)
- [ ] Minimum 8 unit tests pass across all 5 consumers

#### Pre-read (agent must read before starting Wave C-2)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/temporal_event_consumer.py` — Valkey dedup + BaseKafkaConsumer pattern
- `libs/messaging/src/messaging/kafka/consumer/base.py` — BaseKafkaConsumer interface

#### Validation Gate
- [ ] ruff check + mypy on `services/knowledge-graph/`
- [ ] Unit tests: minimum 8 new tests
- [ ] All consumer mains have SIGINT/SIGTERM signal handling

#### Break Impact
*(Pure additions)*

#### Regression Guardrails
- BP-124: Valkey dedup check before `get_unit_of_work` call — consumers must call `is_duplicate(event_id)` before opening any DB session
- BP-057: No DB session in consumer constructor — session opened per-message in `process_message()`

---

### Wave C-3: S7 API Endpoints (7 new routes + use cases)

**Goal**: Implement 7 new S7 FastAPI endpoints for prediction market read queries. All use `ReadOnlyUnitOfWork` (R27).
**Depends on**: Wave C-1 (repos) and Wave C-2 (tables populated by consumers)
**Estimated effort**: 60–90 min
**Architecture layer**: API

#### Tasks

##### T-C-3-01: S7 prediction market read use cases (7)

**Type**: impl
**depends_on**: [T-C-1-02]
**blocks**: [T-C-3-02]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/use_cases/prediction_market_use_cases.py`

**What to build**: 7 read use cases, each accepting a `ReadOnlyUnitOfWork` (R27):

- `ListPredictionMarketsUseCase(uow, category, event_id, status, q, limit, offset) -> PredictionMarketsPage`
- `GetPredictionMarketByIdUseCase(uow, condition_id) -> PredictionMarket | None`
- `GetPredictionMarketHistoryUseCase(uow, condition_id, interval, since, limit) -> list[PredictionMarketPricePoint]`
- `GetPredictionMarketTradesUseCase(uow, condition_id, since, limit) -> list[PredictionMarketTrade]`
- `ListPredictionEventsUseCase(uow, limit, offset) -> PredictionEventsPage`
- `GetPredictionEventByIdUseCase(uow, event_id_gamma) -> tuple[PredictionEvent, list[PredictionMarket]] | None`
- `GetEntityPredictionsUseCase(uow, entity_id) -> list[PredictionMarket]` — queries via KG relations

**Response models** (Pydantic, inline in the module or in a `schemas.py`):
- `PredictionMarketsPage(markets: list[PredictionMarketOut], total: int)`
- `PredictionMarketOut` — flattened from domain entity, includes `outcomes: list[OutcomeOut]`
- `PredictionEventsPage(events: list[PredictionEventOut], total: int)`
- `PredictionEventDetail(event: PredictionEventOut, markets: list[PredictionMarketOut])`

**Tests**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_list_markets_use_case_filters_category` | category filter propagated to repo | unit (mocked repo) |
| `test_get_market_by_id_not_found_returns_none` | Unknown condition_id → None | unit |
| `test_get_entity_predictions_via_kg_relation` | entity_id with related markets → markets returned | unit |

##### T-C-3-02: S7 API router — 7 new endpoints

**Type**: impl
**depends_on**: [T-C-3-01]
**blocks**: [T-D-1-01]
**Target files**: `services/knowledge-graph/src/knowledge_graph/api/routers/predictions.py`

**What to build**: FastAPI router with 7 endpoints. Register in `api/app.py`.

```
GET /api/v1/predictions/markets
GET /api/v1/predictions/markets/{condition_id}
GET /api/v1/predictions/markets/{condition_id}/history
GET /api/v1/predictions/markets/{condition_id}/trades
GET /api/v1/predictions/events
GET /api/v1/predictions/events/{event_id}
GET /api/v1/entities/{entity_id}/predictions
```

All 7 use `ReadUoWDep` (R27). All return `None` → 404. Auth: none (public, same pattern as `similar` endpoint).

**Parameters**:
- `list_markets`: `category: str | None`, `event_id: str | None`, `status: str | None`, `q: str | None`, `limit: int = Query(50, ge=1, le=500)`, `offset: int = 0`
- `market_history`: `interval: str = "1h"`, `since: str | None` (ISO datetime string), `limit: int = 1000`
- `market_trades`: `since: str | None`, `limit: int = Query(100, le=1000)`
- `list_events`: `limit: int = 50`, `offset: int = 0`

**Tests**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_list_markets_returns_200` | GET /predictions/markets → 200 with pagination | unit |
| `test_get_market_not_found_returns_404` | Unknown condition_id → 404 | unit |
| `test_market_history_returns_sorted_by_ts` | History sorted ascending by window_start_ts | unit |
| `test_entity_predictions_empty_returns_empty_list` | Entity with no predictions → 200 empty list | unit |

**Acceptance criteria for Wave C-3**:
- [ ] 7 endpoints registered in S7 app
- [ ] All use ReadOnlyUoW (R27)
- [ ] None-to-404 mapping for all single-item endpoints
- [ ] 7 unit tests pass (mix of use case + router tests)
- [ ] mypy strict passes
- [ ] R25: router imports use cases only, never repositories directly

#### Pre-read (agent must read before starting Wave C-3)
- `services/knowledge-graph/src/knowledge_graph/api/routers/` — existing router pattern
- `services/knowledge-graph/src/knowledge_graph/api/dependencies.py` — `ReadUoWDep`, `get_entity_graph_repos` pattern

#### Validation Gate
- [ ] ruff check + mypy on `services/knowledge-graph/`
- [ ] Unit tests: minimum 7 new tests
- [ ] Endpoint docs at `/docs` include all 7 new routes (verify with ASGI test client)

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/knowledge-graph/src/knowledge_graph/api/app.py` | Router must be registered | Add `app.include_router(predictions_router, prefix="/api/v1")` |

#### Regression Guardrails
- R27: Every endpoint uses `ReadUoWDep` — never `UoWDep` for read-only queries
- R25: API layer imports use cases only, no direct repo imports in route functions

---

## 6. Sub-Plan D — S9 API Gateway Proxy Routes

### Wave D-1: S9 Proxy Routes (7 new routes to S7)

**Goal**: Add 7 new proxy routes in S9 forwarding to S7's new prediction endpoints. The existing `/signals/prediction-markets` routes (→ S3) are **unchanged**.
**Depends on**: Wave C-3 (S7 endpoints)
**Estimated effort**: 30–45 min
**Architecture layer**: API

#### Tasks

##### T-D-1-01: 7 new S9 proxy routes

**Type**: impl
**depends_on**: [T-C-3-02]
**blocks**: none
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py`

**What to build**: Add 7 new routes after the existing prediction market section. These route to S7 (not S3), using `_proxy_to_s7()` (or whichever helper routes to knowledge-graph backend).

**Route table**:

| Method | S9 Path | S7 Backend Path | Auth | Query params forwarded |
|---|---|---|---|---|
| GET | `/api/v1/predictions/markets` | `/api/v1/predictions/markets` | JWT | `category`, `event_id`, `status`, `q`, `limit`, `offset` |
| GET | `/api/v1/predictions/markets/{condition_id}` | `/api/v1/predictions/markets/{condition_id}` | JWT | — |
| GET | `/api/v1/predictions/markets/{condition_id}/history` | `/api/v1/predictions/markets/{condition_id}/history` | JWT | `interval`, `since`, `limit` |
| GET | `/api/v1/predictions/markets/{condition_id}/trades` | `/api/v1/predictions/markets/{condition_id}/trades` | JWT | `since`, `limit` |
| GET | `/api/v1/predictions/events` | `/api/v1/predictions/events` | JWT | `limit`, `offset` |
| GET | `/api/v1/predictions/events/{event_id}` | `/api/v1/predictions/events/{event_id}` | JWT | — |
| GET | `/api/v1/entities/{entity_id}/predictions` | `/api/v1/entities/{entity_id}/predictions` | JWT | — |

Note: `{event_id}` parameter may conflict with the S9 entity detail route `GET /api/v1/entities/{entity_id}`. Ensure the new entity predictions route path is `{entity_id}/predictions` (suffix prevents conflict).

**Tests to write**:

| Test Name | What It Verifies | Type |
|---|---|---|
| `test_list_predictions_markets_proxied_to_s7` | S9 GET /api/v1/predictions/markets → S7 200 | unit (mock httpx) |
| `test_get_entity_predictions_requires_jwt` | Missing Authorization header → 401 | unit |
| `test_s7_404_propagated_as_404` | S7 returns 404 → S9 returns 404 | unit |

##### T-D-1-02: docs + api-gateway context update

**Type**: docs
**depends_on**: [T-D-1-01]
**blocks**: none
**Target files**:
- `docs/services/api-gateway.md`
- `services/api-gateway/.claude-context.md`

**What to build**: Add the 7 new routes to the prediction markets section of both docs. Update endpoint count from 55+ to 62+.

**Acceptance criteria**:
- [ ] Both docs files updated
- [ ] Route table accurate with new paths

#### Pre-read (agent must read before starting Wave D-1)
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 499–595 — existing prediction market proxy routes pattern
- `services/api-gateway/src/api_gateway/` — locate which helper function routes to S7 vs S3

#### Validation Gate
- [ ] ruff check + mypy on `services/api-gateway/`
- [ ] Unit tests: minimum 3 new tests pass
- [ ] All existing 127+ api-gateway tests still pass

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/api-gateway/tests/unit/test_proxy_routes.py` (if route count asserted) | 7 more routes | Update count assertions |

#### Regression Guardrails
- API-004 pattern: S9 proxy must forward query params correctly — test that `category`, `since`, `limit` are forwarded, not swallowed

---

## 7. Cross-Cutting Concerns

### Contract changes
- 4 new Avro schemas → update `infra/kafka/schemas/` and register with Schema Registry on deploy
- `ContentSourceType` enum gains 4 values → `libs/contracts/tests/` may need update

### Migration needs
- **intelligence-migrations 0011** (B-1) — must apply before S7 consumers start
- **No S4 migration** — `prediction_market_fetch_log` is unchanged; new sources are seeded via `CreateSourceUseCase`

### New Kafka topics (must be created in Kafka before consumers start)
| Topic | Config |
|---|---|
| `market.prediction.history.v1` | partitions=4, retention=14d (prices stored in DB) |
| `market.prediction.event.v1` | partitions=2, retention=7d |
| `market.prediction.trade.v1` | partitions=4, retention=7d |
| `market.prediction.oi.v1` | partitions=2, retention=7d |

Add topic creation to `infra/kafka/topics.sh` or equivalent.

### New environment variables
| Variable | Service | Default | Purpose |
|---|---|---|---|
| `CONTENT_INGESTION_POLYMARKET_HISTORY_BACKFILL_DAYS` | S4 | 14 | Initial CLOB history horizon |
| `CONTENT_INGESTION_POLYMARKET_TRADES_BACKFILL_DAYS` | S4 | 14 | Initial trades horizon |
| `CONTENT_INGESTION_POLYMARKET_CLOB_BASE_URL` | S4 | `https://clob.polymarket.com` | CLOB API base (overridable for tests) |
| `CONTENT_INGESTION_POLYMARKET_DATA_BASE_URL` | S4 | `https://data-api.polymarket.com` | Data API base |

Update `services/content-ingestion/configs/dev.local.env.example`.

### Documentation updates
- `docs/services/content-ingestion.md` — add 4 new adapters, topics
- `docs/services/knowledge-graph.md` — add 2 new entity types, 6 new tables, 5 new consumers, 7 new endpoints
- `docs/services/api-gateway.md` — add 7 new routes
- `services/content-ingestion/.claude-context.md` — add new topics and adapter types
- `services/knowledge-graph/.claude-context.md` — add new tables, consumers, entity types
- `docs/MASTER_PLAN.md` — add Polymarket data flow diagram (§4.1 of PRD)

---

## 8. Risk Assessment

### Critical path
A-1 → A-2 → A-3/A-4 (parallel) → A-5 → B-1 (parallel) → C-1 → C-2 → C-3 → D-1

**Highest risk**: Wave A-3 (PolymarketHistoryAdapter) — CLOB API behavior for closed/resolved markets needs careful handling. Empty-response → interval retry is documented in PRD but not verified empirically. Have a fallback: if 1d also returns empty, skip silently.

### Rollback strategy
- Each sub-plan is committed separately. If C fails, A+B are already in; consumers just don't start.
- If B-1 fails midway: `alembic downgrade -1` removes all 6 tables cleanly (DROP TABLE CASCADE removes child partitions).
- S4 changes are additive: new source types not dispatched → tasks created but not claimed by unrecognized handlers (no crash, just queue buildup).

### Testing gaps
- No live Polymarket API call in unit tests — all adapter tests use `httpx` mocks. Integration test against live Polymarket is manual only.
- S7 consumer tests that require `intelligence_db` with partitioned tables are marked `integration` (skip when infra unavailable).

---

## 9. Task ID Summary

| Wave | Task | Type | Est. |
|---|---|---|---|
| A-1 | T-A-1-01: 4 Avro schemas | schema | 20m |
| A-1 | T-A-1-02: contracts enum extension | impl | 10m |
| A-1 | T-A-1-03: S4 config extension | config | 15m |
| A-1 | T-A-1-04: A-1 tests | test | 15m |
| A-2 | T-A-2-01: S4 domain entities | impl | 45m |
| A-2 | T-A-2-02: S4 HTTP clients | impl | 45m |
| A-3 | T-A-3-01: PolymarketHistoryAdapter | impl | 60m |
| A-3 | T-A-3-02: PolymarketEventAdapter | impl | 30m |
| A-4 | T-A-4-01: PolymarketTradesAdapter | impl | 30m |
| A-4 | T-A-4-02: PolymarketOIAdapter | impl | 20m |
| A-4 | T-A-4-03: SyntheticDocumentEmitter | impl | 45m |
| A-5 | T-A-5-01: Worker routing | impl | 30m |
| A-5 | T-A-5-02: Dispatcher serializers | impl | 20m |
| A-5 | T-A-5-03: Scheduler seeding + docker | config | 20m |
| B-1 | T-B-1-01: Migration 0011 | schema | 30m |
| B-1 | T-B-1-02: S7 entity type constants | impl | 5m |
| C-1 | T-C-1-01: S7 domain entities | impl | 30m |
| C-1 | T-C-1-02: S7 ports + repositories | impl | 90m |
| C-2 | T-C-2-01: PredictionMarketUpserter | impl | 45m |
| C-2 | T-C-2-02: 4 more consumers | impl | 90m |
| C-3 | T-C-3-01: 7 read use cases | impl | 45m |
| C-3 | T-C-3-02: S7 router 7 endpoints | impl | 45m |
| D-1 | T-D-1-01: S9 7 proxy routes | impl | 25m |
| D-1 | T-D-1-02: docs update | docs | 15m |

**Total: 37 tasks, estimated 780–1080 min (13–18 h of agent time)**

---

## 10. Execution Order (Recommended)

Run each sub-plan in a separate `/implement` session. B-1 can run in parallel with A-3/A-4.

```
Session 1: /implement PLAN-0056 Wave A-1   (schemas + config)
Session 2: /implement PLAN-0056 Wave A-2   (domain entities + clients)
Session 3: /implement PLAN-0056 Wave A-3   (history + events adapters)
Session 4: /implement PLAN-0056 Wave A-4   (trades + OI + SyntheticDocumentEmitter)
Session 5: /implement PLAN-0056 Wave A-5   (worker routing + dispatcher + docker)
Session 5b (parallel): /implement PLAN-0056 Wave B-1   (migration 0011)
Session 6: /implement PLAN-0056 Wave C-1   (S7 domain + repos)
Session 7: /implement PLAN-0056 Wave C-2   (S7 consumers)
Session 8: /implement PLAN-0056 Wave C-3   (S7 API endpoints)
Session 9: /implement PLAN-0056 Wave D-1   (S9 proxy)
```

After all waves: `/qa PLAN-0056` for full cross-service QA.

---

## 11. Compounding Entries (Post-Implementation)

After implementation, update the following:
- `docs/BUG_PATTERNS.md` — CLOB closed-market 400/empty → interval fallback pattern
- `services/content-ingestion/.claude-context.md` — 4 new adapters, 4 new topics, 4 new SourceType values, SyntheticDocumentEmitter
- `services/knowledge-graph/.claude-context.md` — 2 new entity types, 6 new tables, 5 new consumers, 7 new API endpoints
- `docs/services/content-ingestion.md` — full new adapter section
- `docs/services/knowledge-graph.md` — full new prediction market section
- `docs/MASTER_PLAN.md` — prediction-market data flow diagram
- `docs/services/api-gateway.md` — 7 new routes added
