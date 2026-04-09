# PLAN-0019 — Polymarket Prediction Markets Integration + EDGAR Market-Hours Polling

> **PRD**: `docs/specs/0019-polymarket-prediction-markets.md`
> **Status**: in-progress
> **Created**: 2026-04-09
> **Updated**: 2026-04-09
> **Waves**: 6 across 4 sub-plans

---

## Pre-Flight Gate Results

| Check | Result | Notes |
|-------|--------|-------|
| No unresolved BLOCKING open questions | PASS | OQ-001/002/003 are design-time decisions with safe defaults; none BLOCKING |
| No unverified external API fields | PASS | Polymarket Gamma API is free/public; fields verified against live API |
| No active cross-plan conflicts | PASS | No other in-progress plan modifies S3/S4 prediction-market tables/topics |
| PRD recency (written 2026-04-06, 3 days ago) | PASS | Architecture unchanged since PRD was written |
| Architecture compliance | PASS | All decisions follow R7–R27; outbox pattern for dual writes |

---

## Sub-Plan Overview

| Sub-Plan | Service | Description | Waves |
|----------|---------|-------------|-------|
| A | S4 Content Ingestion | Avro schema + domain entities + S4 DB migration + PolymarketAdapter + EDGAR interval fix | 2 |
| B | S3 Market Data | DB migrations + consumer + repository + API endpoints | 2 |
| C | S9 API Gateway | Proxy routes for prediction markets | 1 |
| D | Frontend | PredictionMarketsPanel component | 1 |

## Dependency Graph

```
A-1 (schema + domain + migration)
  │
  └──→ A-2 (PolymarketAdapter + EDGAR fix + outbox routing)
            │
            └──→ B-1 (S3 migration + domain + consumer)
                       │
                       └──→ B-2 (S3 API endpoints + use cases + read repos)
                                    │
                                    └──→ C-1 (S9 proxy routes)
                                                │
                                                └──→ D-1 (Frontend panel)
```

**Critical path**: A-1 → A-2 → B-1 → B-2 → C-1 → D-1 (fully sequential)
**Parallelizable**: None — producer-consumer dependency forces sequential execution

---

## SUB-PLAN A — S4 Content Ingestion

### Wave A-1: Avro Schema + Domain Entities + S4 DB Migration ✅

**Goal**: Lay foundational contracts (Avro schema, new domain types, DB table) so A-2 and B-1 can proceed.
**Depends on**: none
**Estimated effort**: 45–75 min
**Architecture layer**: domain + schema
**Status**: **DONE** — 2026-04-09 · 507 S4 unit tests + 106 contracts tests pass · ruff + mypy clean

#### Tasks

---

##### T-A-1-01: Create `market.prediction.v1.avsc` Avro Schema

**Type**: schema
**depends_on**: none
**blocks**: [T-A-2-03, T-B-1-07]
**Target files**: `infra/kafka/schemas/market.prediction.v1.avsc`
**PRD reference**: §6.3

**What to build**:
Create the Avro schema for the `market.prediction.v1` Kafka topic. This schema defines the contract between S4 (producer) and S3 (consumer). File name must match the topic name exactly.

**Schema definition**:
```json
{
  "type": "record",
  "name": "PredictionMarketSnapshot",
  "namespace": "com.worldview",
  "fields": [
    {"name": "event_id",          "type": "string"},
    {"name": "event_type",        "type": "string", "default": "market.prediction.snapshot"},
    {"name": "schema_version",    "type": "int",    "default": 1},
    {"name": "occurred_at",       "type": "string"},
    {"name": "market_id",         "type": "string"},
    {"name": "source",            "type": "string", "default": "polymarket"},
    {"name": "question",          "type": "string"},
    {"name": "description",       "type": ["null", "string"], "default": null},
    {"name": "outcomes",          "type": {
      "type": "array",
      "items": {
        "type": "record",
        "name": "OutcomeRecord",
        "fields": [
          {"name": "name",     "type": "string"},
          {"name": "token_id", "type": "string"},
          {"name": "price",    "type": "double"}
        ]
      }
    }, "default": []},
    {"name": "volume_24h",        "type": ["null", "double"], "default": null},
    {"name": "liquidity",         "type": ["null", "double"], "default": null},
    {"name": "close_time",        "type": ["null", "string"], "default": null},
    {"name": "resolution_status", "type": "string", "default": "open"},
    {"name": "resolved_answer",   "type": ["null", "string"], "default": null},
    {"name": "minio_bronze_key",  "type": ["null", "string"], "default": null},
    {"name": "correlation_id",    "type": ["null", "string"], "default": null}
  ]
}
```

**Downstream test impact**:
- `libs/contracts/tests/test_avro_alignment.py` — if this file performs schema inventory checks, add the new schema
- `services/content-ingestion/tests/contract/test_avro_schemas.py` — if schema file count is asserted, update expected count
- `services/market-data/tests/contract/test_avro_schemas.py` — same

**Acceptance criteria**:
- [ ] File parses via `fastavro.schema.parse_schema(json.load(open(...)))` without exception
- [ ] All fields have defaults (except `event_id`, `occurred_at`, `market_id`, `question`)
- [ ] File is at `infra/kafka/schemas/market.prediction.v1.avsc` (filename == topic name)

---

##### T-A-1-02: Add `POLYMARKET` to `ContentSourceType` in `libs/contracts`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03, T-A-2-01]
**Target files**: `libs/contracts/src/contracts/enums.py`, `libs/contracts/tests/test_enums.py`
**PRD reference**: §6.2

**What to build**:
Extend the shared `ContentSourceType` StrEnum with a new `POLYMARKET` value. This is a shared lib change — all services that import `ContentSourceType` will gain the new member.

**Entities / Components**:
- **Name**: `ContentSourceType.POLYMARKET`
- **Purpose**: Identifies Polymarket as a data source
- **Key attributes**: `value = "polymarket"` (lowercase, matches Avro `source` field default)
- **Invariants**: StrEnum value must be stable and never renamed (R15 forward-compatible)

**Logic & Behavior**:
- Add `POLYMARKET = "polymarket"` to `ContentSourceType` in alphabetical order (RUF022)
- The alias `SourceType = ContentSourceType` in `content_ingestion/domain/entities.py` automatically includes the new value

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_content_source_type_polymarket` | `ContentSourceType.POLYMARKET == "polymarket"` | unit |
| `test_polymarket_in_all_values` | `"polymarket" in [v.value for v in ContentSourceType]` | unit |

**Acceptance criteria**:
- [ ] `ContentSourceType.POLYMARKET` accessible from `libs.contracts.enums`
- [ ] `libs/contracts` tests pass with 2 new tests

---

##### T-A-1-03: Create `OutcomeSnapshot` and `PredictionMarketFetchResult` domain entities (S4)

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: [T-A-2-03]
**Target files**: `services/content-ingestion/src/content_ingestion/domain/entities.py`, `services/content-ingestion/tests/unit/test_domain_entities.py`
**PRD reference**: §6.5

**What to build**:
Add two new frozen dataclasses to S4's domain layer. These are pure domain objects with no infrastructure imports.

**Entities / Components**:

- **Name**: `OutcomeSnapshot`
- **Purpose**: Represents a single binary outcome of a prediction market (e.g., "Yes" or "No")
- **Key attributes**:
  - `name: str` — outcome name, 1–100 chars
  - `token_id: str` — Polymarket token identifier, 1–200 chars
  - `price: float` — probability [0.0, 1.0] inclusive
- **Invariants**: `0.0 <= price <= 1.0`; name and token_id non-empty

- **Name**: `PredictionMarketFetchResult`
- **Purpose**: Immutable result of fetching one prediction market from Polymarket; input to the outbox use case
- **Key attributes**:
  - `id: UUID` — UUIDv7, `default_factory=new_uuid7`
  - `source_type: SourceType` — `SourceType.POLYMARKET`
  - `market_id: str` — Polymarket conditionId
  - `question: str` — the market question
  - `description: str | None`
  - `outcomes: list[OutcomeSnapshot]` — min length 2
  - `volume_24h: float | None`
  - `liquidity: float | None`
  - `close_time: datetime | None` — UTC-aware if present
  - `resolution_status: str` — `"open"` | `"resolved"` | `"cancelled"` (NOT "closed")
  - `resolved_answer: str | None`
  - `raw_bytes: bytes` — original JSON response from Gamma API
  - `fetched_at: datetime` — UTC-aware
  - `minio_bronze_key: str | None = None` — set by adapter via `dataclasses.replace()` after MinIO storage
- **Key methods**:
  - `@classmethod from_gamma_response(cls, raw: dict, fetched_at: datetime) -> PredictionMarketFetchResult`
    - Maps: `conditionId → market_id`, `question`, `description`, `tokens → outcomes`, `volume24hr → volume_24h`, `liquidity`, `endDate → close_time`, `active/closed/resolved flags → resolution_status` (map "closed" API value → `"cancelled"`), `resolvedAnswer → resolved_answer`
    - `raw_bytes = json.dumps(raw).encode()`, `minio_bronze_key=None`
    - Guard: defensive `.get()` with defaults for all optional fields (Polymarket API fields may be absent)
- **Invariants**: `len(outcomes) >= 2`; `fetched_at` must be UTC-aware (else ValueError)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_outcome_snapshot_price_below_zero` | price=-0.01 → ValueError | unit |
| `test_outcome_snapshot_price_above_one` | price=1.01 → ValueError | unit |
| `test_outcome_snapshot_price_boundary_zero` | price=0.0 succeeds | unit |
| `test_outcome_snapshot_price_boundary_one` | price=1.0 succeeds | unit |
| `test_prediction_market_fetch_result_empty_outcomes` | len(outcomes)<2 → ValueError | unit |
| `test_prediction_market_fetch_result_naive_datetime` | naive fetched_at → ValueError | unit |
| `test_prediction_market_fetch_result_from_gamma_response_happy` | all fields mapped correctly | unit |
| `test_prediction_market_fetch_result_from_gamma_response_missing_optional` | absent optional fields → None defaults | unit |

**Acceptance criteria**:
- [ ] Both dataclasses are frozen with `slots=True`
- [ ] No infrastructure imports in domain layer (R12)
- [ ] All 8 tests pass

---

##### T-A-1-04: S4 Alembic migration — `prediction_market_fetch_log` table

**Type**: schema
**depends_on**: none
**blocks**: [T-A-2-05]
**Target files**: `services/content-ingestion/alembic/versions/0004_add_prediction_market_fetch_log.py`, `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py`
**PRD reference**: §6.4 (prediction_market_fetch_log table)

**What to build**:
Add the `prediction_market_fetch_log` table used by S4 for deduplication across Polymarket poll cycles. Also add the corresponding ORM model.

**DDL**:
```sql
CREATE TABLE prediction_market_fetch_log (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES sources(id),
    market_id TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'open',
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_pmfl_market_snapshot
  ON prediction_market_fetch_log (market_id, snapshot_at);
CREATE INDEX ix_pmfl_source_fetched
  ON prediction_market_fetch_log (source_id, fetched_at);
```

**ORM model** (`PredictionMarketFetchLogModel`):
- `id`: `UUID`, **no** `server_default` — always app-generated via `new_uuid7()` (S4 pitfall: "DDL must never use gen_random_uuid() defaults on UUID PKs")
- `created_at`: `server_default=text("now()")` for the timestamp column
- `resolution_status`: `String(20)` with `server_default=text("'open'")`
- Guard: BP-126 applies to new NOT NULL columns on existing tables (ALTER TABLE), not to PKs on new tables — do NOT add `server_default` to `id`

**Acceptance criteria**:
- [ ] `alembic upgrade head` applies cleanly in test container
- [ ] `alembic downgrade -1` drops the table cleanly
- [ ] ORM model column names/types match DDL exactly (BP-019)

---

#### Pre-read (agent must read before starting Wave A-1)
- `services/content-ingestion/src/content_ingestion/domain/entities.py` — existing entity patterns
- `services/content-ingestion/alembic/versions/0003_*.py` — migration numbering convention
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py` — ORM model patterns
- `libs/contracts/src/contracts/enums.py` — StrEnum conventions
- `infra/kafka/schemas/content.article.raw.v1.avsc` — existing schema pattern

#### Validation Gate A-1
- [x] `uvx ruff check services/content-ingestion/src/ libs/contracts/` — zero violations
- [x] `uvx ruff format --check services/content-ingestion/src/ libs/contracts/` — zero violations
- [x] `uvx mypy services/content-ingestion/src/ --strict` — zero errors
- [x] `python -m pytest services/content-ingestion/tests/unit/test_domain_entities.py -v` — 16 tests pass (8 required + 8 additional edge cases)
- [x] `python -m pytest libs/contracts/tests/ -v` — 106 pass (14 enum tests including 2 new POLYMARKET tests)
- [x] Avro schema parses: `python -c "import fastavro.schema, json; fastavro.schema.parse_schema(json.load(open('infra/kafka/schemas/market.prediction.v1.avsc')))"`
- [ ] Alembic migration `0004` applies and reverts cleanly (requires live DB — not run in unit validation)

#### Regression Guardrails
- **BP-119**: Avro schema must be in `.avsc` file; no inline Python dicts for schema definition
- **BP-019**: ORM-DDL alignment — `PredictionMarketFetchLogModel` must mirror DDL exactly; add DDL alignment assertion to `test_models.py`
- **BP-126**: Every NOT NULL column must have `server_default` in Alembic migration
- **R15**: Forward-compatible schema — all new Avro fields except required ones have defaults; never remove fields

---

### Wave A-2: PolymarketAdapter + EDGAR Market-Hours Fix + Outbox Routing

**Goal**: Implement the S4 adapter polling Polymarket Gamma API and the EDGAR polling interval logic; wire both into the existing scheduler/worker/outbox pipeline.
**Depends on**: Wave A-1 (schema, domain entities, DB table must exist)
**Estimated effort**: 90–120 min
**Architecture layer**: infrastructure + application

#### Tasks

---

##### T-A-2-01: Create `PolymarketClient`

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: [T-A-2-03]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/client.py`, `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/__init__.py`
**PRD reference**: §6.4

**What to build**:
HTTP client wrapping the Polymarket Gamma API. Stateless — receives an `httpx.AsyncClient` as a dependency (no DB session).

**Entities / Components**:
- **Name**: `GammaMarketsPage`
- **Purpose**: Typed result from a single paginated API call
- **Key attributes**: `markets: list[dict]`, `next_cursor: str | None`

- **Name**: `PolymarketClient`
- **Purpose**: Low-level HTTP adapter for Gamma API
- **Key methods**:
  - `async def fetch_markets_page(self, *, limit: int = 500, next_cursor: str | None = None) -> GammaMarketsPage`
    - GET `{base_url}?active=true&limit={limit}[&next_cursor={cursor}]`
    - 200 → parse response JSON → `GammaMarketsPage(markets=data["markets"], next_cursor=data.get("next_cursor"))`
    - Non-200 → raise `AdapterError(f"Gamma API HTTP {resp.status_code}")`
    - Timeout: 30s default
- **Invariants**: No API key; no DB calls; no state beyond config

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_client_parses_markets_page` | valid JSON response → GammaMarketsPage fields | unit |
| `test_client_next_cursor_absent` | response without `next_cursor` → `GammaMarketsPage.next_cursor = None` | unit |
| `test_client_http_error_raises_adapter_error` | HTTP 429 → `AdapterError` | unit |

**Acceptance criteria**:
- [ ] `PolymarketClient` exposed from `__init__.py`
- [ ] No DB session in constructor or method signatures (BP-057)
- [ ] 3 unit tests pass

---

##### T-A-2-02: Create `PolymarketProviderSettings` in S4 config

**Type**: config
**depends_on**: none
**blocks**: [T-A-2-03, T-A-2-06]
**Target files**: `services/content-ingestion/src/content_ingestion/config.py`
**PRD reference**: §8

**What to build**:
Extend S4's `Settings` with Polymarket-specific provider config.

**Fields**:
- `PolymarketProviderSettings(BaseModel)`:
  - `base_url: str = "https://gamma-api.polymarket.com/markets"`
  - `page_size: int = Field(default=500, ge=1, le=1000)`
  - `max_pages_per_cycle: int = Field(default=20, ge=1, le=100)` — safety cap: 20 × 500 = 10,000 markets
- Add `polymarket: PolymarketProviderSettings = PolymarketProviderSettings()` to `Settings`
- Env var prefix: `CONTENT_INGESTION_POLYMARKET__` (nested settings pattern)

**Acceptance criteria**:
- [ ] Settings parse cleanly from env vars with `CONTENT_INGESTION_POLYMARKET__PAGE_SIZE=100`
- [ ] `mypy --strict` passes on `config.py`

---

##### T-A-2-03: Create `PolymarketAdapter`

**Type**: impl
**depends_on**: [T-A-1-02, T-A-1-03, T-A-2-01, T-A-2-02]
**blocks**: [T-A-2-04]
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/polymarket/adapter.py`
**PRD reference**: §6.4

**What to build**:
S4 source adapter that paginates through Polymarket Gamma API, deduplicates via `prediction_market_fetch_log`, stores raw bytes to MinIO bronze, and returns `PredictionMarketFetchResult` list.

**Entities / Components**:
- **Name**: `PolymarketAdapter`
- **Purpose**: Implements `SourceAdapter` protocol for Polymarket
- **Key methods**:
  - `async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[PredictionMarketFetchResult]`

**Logic & Behavior**:
1. `fetched_at = utc_now()` rounded to the nearest minute (stable dedup key)
2. Start cursor-paginated loop:
   - Call `client.fetch_markets_page(limit=settings.polymarket.page_size, next_cursor=cursor)`
   - For each market dict in page:
     a. `snapshot_at = fetched_at` (all markets in same cycle share the same snapshot time)
     b. Skip if `await fetch_log_exists_fn(market_id=market["conditionId"], snapshot_at=snapshot_at)` is True
     c. Parse: `result = PredictionMarketFetchResult.from_gamma_response(market, fetched_at)`
     d. Compute MinIO key: `minio_key = f"content-ingestion/polymarket/{YYYY}/{MM}/{DD}/{market_id}_{snapshot_at.isoformat()}.json"`
        Store to bronze MinIO; then: `result = dataclasses.replace(result, minio_bronze_key=minio_key)`
        (use `dataclasses.replace()` because `PredictionMarketFetchResult` is frozen)
     e. On parse failure: `log.warning("polymarket_market_parse_failed", market_id=..., exc_info=True)`, continue
        On MinIO failure: log warning, keep `result.minio_bronze_key = None` (non-fatal; continue)
   - Break if `page.next_cursor is None` or `page_count >= settings.polymarket.max_pages_per_cycle`
3. Return all successfully parsed results
- **Idempotency**: `fetch_log_exists_fn` prevents duplicate processing of same (market_id, snapshot_at)
- **Error classification**: HTTP errors → `AdapterError` (retryable); parse errors → logged, skipped (non-fatal)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_adapter_dedup_skips_existing` | `fetch_log_exists_fn` returns True → result excluded | unit |
| `test_adapter_pagination_stops_at_max_pages` | stops after `max_pages_per_cycle` | unit |
| `test_adapter_parse_failure_continues` | one bad market dict → warning logged, others processed | unit |
| `test_adapter_stores_raw_bytes_to_minio` | MinIO `put_object` called once per result | unit |
| `test_adapter_integration_end_to_end` | wiremock Gamma API + Postgres → fetch_log row created | integration |
| `test_adapter_idempotent_repoll` | same markets polled twice → 1 fetch_log row per (market_id, snapshot_at) | integration |

**Acceptance criteria**:
- [ ] Adapter returns `PredictionMarketFetchResult` list with correct field values
- [ ] No DB session passed to `fetch()` method; `fetch_log_exists_fn` is the only DB interaction (BP-057)
- [ ] Bronze MinIO key format matches `content-ingestion/polymarket/{YYYY}/{MM}/{DD}/...`

---

##### T-A-2-04: Create `FetchAndWritePredictionMarketsUseCase`

**Type**: impl
**depends_on**: [T-A-1-04, T-A-2-03, T-A-2-05]
**blocks**: [T-A-2-06]
**Target files**: `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write_prediction_markets.py`
**PRD reference**: §6.4

**What to build**:
Application use case that atomically writes `prediction_market_fetch_log` + `outbox_events` in one transaction per result (outbox pattern).

**Logic & Behavior**:
For each `PredictionMarketFetchResult`:
1. Skip if `await uow.fetch_log.exists_by_market_snapshot(result.market_id, result.snapshot_at)` (event-level idempotency)
2. Build outbox payload dict matching `market.prediction.v1.avsc` field names:
   ```python
   {
     "event_id": str(new_uuid7()),
     "event_type": "market.prediction.snapshot",
     "schema_version": 1,
     "occurred_at": result.fetched_at.isoformat(),
     "market_id": result.market_id,
     "source": result.source_type.value,
     "question": result.question,
     "description": result.description,
     "outcomes": [{"name": o.name, "token_id": o.token_id, "price": o.price} for o in result.outcomes],
     "volume_24h": result.volume_24h,
     "liquidity": result.liquidity,
     "close_time": result.close_time.isoformat() if result.close_time else None,
     "resolution_status": result.resolution_status,
     "resolved_answer": result.resolved_answer,
     "minio_bronze_key": result.minio_bronze_key,
     "correlation_id": None,
   }
   ```
3. In single transaction: `INSERT prediction_market_fetch_log` + `INSERT outbox_events` with `topic='market.prediction.v1'`
4. `await uow.commit()`
- **Guard R8**: outbox pattern — both writes in one transaction, never separate
- **Guard BP-017**: payload dict keys must exactly match Avro schema field names

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_use_case_writes_fetch_log_and_outbox_atomically` | both rows in same tx | unit |
| `test_use_case_skips_duplicate` | exists_by_market_snapshot=True → no rows written | unit |
| `test_use_case_outbox_payload_matches_avro_schema` | all required Avro fields present in payload dict | unit |

**Acceptance criteria**:
- [ ] `prediction_market_fetch_log` + `outbox_events` rows created in one transaction
- [ ] Duplicate call (same market_id + snapshot_at) writes nothing
- [ ] Outbox payload keys exactly match `market.prediction.v1.avsc` field names (BP-017)

---

##### T-A-2-05: Extend `FetchLogPort` and implementation for prediction markets

**Type**: impl
**depends_on**: [T-A-1-04]
**blocks**: [T-A-2-04]
**Target files**: `services/content-ingestion/src/content_ingestion/application/ports/repositories.py`, `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/fetch_log.py`
**PRD reference**: §7.1

**What to build**:
Extend existing `FetchLogPort` ABC with two new abstract methods for prediction market log operations, then implement them in the SQLAlchemy concrete repository.

**New port methods**:
```python
@abstractmethod
async def exists_by_market_snapshot(self, market_id: str, snapshot_at: datetime) -> bool: ...

@abstractmethod
async def create_market_fetch_log(
    self, *, source_id: UUID | None, market_id: str, snapshot_at: datetime,
    resolution_status: str, fetched_at: datetime
) -> UUID: ...
```

**Implementation**:
- `exists_by_market_snapshot`: `SELECT EXISTS (SELECT 1 FROM prediction_market_fetch_log WHERE market_id = :market_id AND snapshot_at = :snapshot_at)`
- `create_market_fetch_log`: `INSERT INTO prediction_market_fetch_log (...) VALUES (...) RETURNING id`
- Guard BP-076: no `::type` PostgreSQL cast; use `CAST(:param AS type)` or typed SQLAlchemy columns

**Acceptance criteria**:
- [ ] `mypy --strict` passes (abstract methods implemented)
- [ ] `exists_by_market_snapshot` returns False for unknown (market_id, snapshot_at)
- [ ] `create_market_fetch_log` returns the inserted UUID

---

##### T-A-2-06: Wire `PolymarketAdapter` into S4 worker dispatch

**Type**: impl
**depends_on**: [T-A-2-02, T-A-2-03, T-A-2-04]
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py` (or equivalent dispatcher), `services/content-ingestion/src/content_ingestion/infrastructure/adapters/__init__.py`
**PRD reference**: §6.4

**What to build**:
Register `PolymarketAdapter` in the `ADAPTER_REGISTRY` and wire the dispatcher to call `FetchAndWritePredictionMarketsUseCase` for `SourceType.POLYMARKET` tasks.

**Logic**:
- Add to `ADAPTER_REGISTRY`: `SourceType.POLYMARKET: PolymarketAdapter`
- In use-case dispatch table: `SourceType.POLYMARKET: FetchAndWritePredictionMarketsUseCase`
- Guard BP-079: `worker_lease_seconds` must cover Polymarket fetch cycle (20 pages × ~2s = 40s; 300s lease is sufficient — confirm in code)

**Acceptance criteria**:
- [ ] S4 worker starts with `POLYMARKET` source configured in env without errors
- [ ] Task with `source_type="polymarket"` routes to `FetchAndWritePredictionMarketsUseCase`

---

##### T-A-2-07: EDGAR market-hours polling interval fix

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py`, `services/content-ingestion/src/content_ingestion/config.py`
**PRD reference**: §9 (EDGAR interval fix)

**What to build**:
Add market-hours-aware polling interval to `SECEdgarAdapter` so it polls every 60s during market hours (09:30–16:00 ET, Mon–Fri) and every 30 min outside.

**New settings** (extend `SECEdgarProviderSettings`):
```python
market_hours_interval_seconds: int = 60
off_hours_interval_seconds: int = 1800
```

**New methods on `SECEdgarAdapter`**:
```python
from zoneinfo import ZoneInfo
_NY_TZ = ZoneInfo("America/New_York")

def _is_market_hours(self, now_utc: datetime) -> bool:
    now_ny = now_utc.astimezone(_NY_TZ)
    return (
        now_ny.weekday() < 5
        and time(9, 30) <= now_ny.time() <= time(16, 0)
    )

def calculate_next_run_time(self, now_utc: datetime) -> datetime:
    interval = (
        self._provider_cfg.market_hours_interval_seconds
        if self._is_market_hours(now_utc)
        else self._provider_cfg.off_hours_interval_seconds
    )
    return now_utc + timedelta(seconds=interval)
```

- Guard R11: `now_utc` must be UTC-aware; use `zoneinfo.ZoneInfo` (never pytz)
- Env vars: `CONTENT_INGESTION_SEC_EDGAR__MARKET_HOURS_INTERVAL_SECONDS=60`, `CONTENT_INGESTION_SEC_EDGAR__OFF_HOURS_INTERVAL_SECONDS=1800`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_is_market_hours_tuesday_10am_et` | Tuesday 10:00 ET → True | unit |
| `test_is_market_hours_saturday_noon_et` | Saturday noon ET → False | unit |
| `test_is_market_hours_weekday_before_open` | Tuesday 8:00 ET → False | unit |
| `test_is_market_hours_weekday_after_close` | Tuesday 17:00 ET → False | unit |
| `test_is_market_hours_dst_transition` | March DST switch day at 10:00 local → True | unit |
| `test_calculate_next_run_market_hours` | during hours → `now + 60s` | unit |
| `test_calculate_next_run_off_hours` | outside hours → `now + 1800s` | unit |

**Acceptance criteria**:
- [ ] 7 new tests pass
- [ ] `_is_market_hours` uses only UTC-aware input (no naive datetimes)

---

##### T-A-2-08: Add Kafka topic and update docker-compose / infra

**Type**: config
**depends_on**: [T-A-1-01]
**blocks**: [T-B-1-07]
**Target files**: `infra/kafka/create-topics.sh` (or equivalent), `services/content-ingestion/docker-compose.yml` (env vars)
**PRD reference**: §8

**What to build**:
1. Add `market.prediction.v1` topic to Kafka topic initialization script:
   - `--topic market.prediction.v1 --partitions 8 --replication-factor 1 --config retention.ms=2592000000`
2. Add new S4 env vars to docker-compose.yml:
   - `CONTENT_INGESTION_SEC_EDGAR__MARKET_HOURS_INTERVAL_SECONDS=60`
   - `CONTENT_INGESTION_SEC_EDGAR__OFF_HOURS_INTERVAL_SECONDS=1800`
3. Confirm `infra/kafka/schemas/` is included in S4 Dockerfile COPY steps (BP-106)

**Acceptance criteria**:
- [ ] `market.prediction.v1` topic created in Docker Compose startup
- [ ] Avro schema file is reachable from S4 container at `/app/infra/kafka/schemas/market.prediction.v1.avsc`

---

#### Pre-read (agent must read before starting Wave A-2)
- `services/content-ingestion/src/content_ingestion/infrastructure/adapters/sec_edgar/adapter.py` — adapter pattern
- `services/content-ingestion/src/content_ingestion/application/use_cases/fetch_and_write.py` — outbox use case pattern
- `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/fetch_log.py` — existing fetch log repo
- `services/content-ingestion/src/content_ingestion/config.py` — settings structure
- `services/content-ingestion/src/content_ingestion/infrastructure/workers/worker.py` — dispatch table pattern
- `infra/kafka/create-topics.sh` — topic creation syntax

#### Validation Gate A-2
- [ ] `uvx ruff check + format --check services/content-ingestion/src/` — zero violations
- [ ] `uvx mypy services/content-ingestion/src/ --strict` — zero errors
- [ ] `python -m pytest services/content-ingestion/tests/unit/ -v` — all pass (17+ new tests)
- [ ] `python -m pytest services/content-ingestion/tests/integration/ -v` — `test_adapter_integration_end_to_end` + `test_adapter_idempotent_repoll` pass
- [ ] S4 worker starts in Docker Compose with POLYMARKET source; `outbox_events` table has `topic='market.prediction.v1'` rows after a test poll

#### Regression Guardrails
- **BP-057**: No DB sessions in `PolymarketClient.fetch_markets_page()` or `PolymarketAdapter.fetch()` — sessions only enter via `FetchAndWritePredictionMarketsUseCase`
- **BP-017**: Outbox payload must match Avro schema exactly — `test_use_case_outbox_payload_matches_avro_schema` enforces this
- **BP-079**: Lease duration check — confirm `worker_lease_seconds >= 120` to cover 20-page poll cycle
- **BP-106**: Avro schema file must be copied into S4 Docker image — verify `COPY` step in `services/content-ingestion/Dockerfile`
- **R8**: Outbox pattern — `prediction_market_fetch_log` + `outbox_events` must be in single transaction; never two separate commits

---

## SUB-PLAN B — S3 Market Data

### Wave B-1: DB Migration + Domain + Consumer

**Goal**: Materialize incoming `market.prediction.v1` events into `prediction_markets` + `prediction_market_snapshots` tables via a new Kafka consumer.
**Depends on**: Wave A-1 (Avro schema must exist for consumer deserialization)
**Estimated effort**: 75–105 min
**Architecture layer**: infrastructure + domain

#### Tasks

---

##### T-B-1-01: S3 Alembic migration — `prediction_markets` + `prediction_market_snapshots`

**Type**: schema
**depends_on**: none
**blocks**: [T-B-1-02, T-B-1-07]
**Target files**: `services/market-data/alembic/versions/005_add_prediction_markets.py`
**PRD reference**: §7.2

**DDL**:
```sql
CREATE TABLE prediction_markets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'polymarket',
    question TEXT NOT NULL,
    description TEXT,
    outcomes JSONB NOT NULL DEFAULT '[]',
    close_time TIMESTAMPTZ,
    resolution_status VARCHAR(20) NOT NULL DEFAULT 'open',
    resolved_answer TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_prediction_markets_market_id
  ON prediction_markets (market_id);
CREATE INDEX ix_pm_status_updated
  ON prediction_markets (resolution_status, updated_at DESC);

CREATE TABLE prediction_market_snapshots (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    outcomes_prices JSONB NOT NULL DEFAULT '{}',
    volume_24h NUMERIC(20, 4),
    liquidity NUMERIC(20, 4),
    source_event_id TEXT NOT NULL
);
SELECT create_hypertable('prediction_market_snapshots', 'snapshot_at',
  chunk_time_interval => INTERVAL '7 days',
  if_not_exists => TRUE);
CREATE UNIQUE INDEX uq_pms_market_snapshot
  ON prediction_market_snapshots (market_id, snapshot_at);
CREATE INDEX ix_pms_market_time
  ON prediction_market_snapshots (market_id, snapshot_at DESC);
```

**OQ-003 mitigation** (TimescaleDB in tests):
- Wrap `create_hypertable` call in migration with a check: only execute if `timescaledb` extension is present
- Existing `market_data_db` Docker Compose service already has TimescaleDB — integration tests use it

**Downgrade**: `DROP TABLE prediction_market_snapshots; DROP TABLE prediction_markets;`

**Acceptance criteria**:
- [ ] Migration applies cleanly in TimescaleDB test container
- [ ] Downgrade reverts cleanly
- [ ] All columns have correct types and NOT NULL constraints

---

##### T-B-1-02: S3 ORM models

**Type**: impl
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-05, T-B-1-07]
**Target files**: `services/market-data/src/market_data/infrastructure/db/models/prediction_markets.py`
**PRD reference**: §7.2

**What to build**:
ORM models mapping to the two new tables.

**Models**:
- `PredictionMarketModel(TimestampMixin, Base)`: mirrors `prediction_markets` DDL
- `PredictionMarketSnapshotModel(Base)`: mirrors `prediction_market_snapshots` DDL
  - No `TimestampMixin` (hypertable doesn't use `updated_at`)
  - `__table_args__`: UniqueConstraint on `(market_id, snapshot_at)`, Index on `(market_id, snapshot_at.desc())`

**Guards**: BP-019 (ORM-DDL alignment), BP-021 (don't name columns `metadata`)

**Acceptance criteria**:
- [ ] Models import cleanly; `mypy --strict` passes
- [ ] Column types exactly match DDL (BP-019)

---

##### T-B-1-03: S3 domain entities for prediction markets

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-04, T-B-1-07]
**Target files**: `services/market-data/src/market_data/domain/entities.py`
**PRD reference**: §6.5

**Entities**:
- `PredictionMarket` (dataclass, mutable):
  - `id: UUID`, `market_id: str`, `source: str`, `question: str`, `description: str | None`
  - `outcomes: list[dict]` (JSONB, shape: `[{"name": str, "token_id": str}]` — **no price**; prices are in `PredictionMarketSnapshot.outcomes_prices`)
  - `close_time: datetime | None`, `resolution_status: str`, `resolved_answer: str | None`
  - `created_at: datetime`, `updated_at: datetime`
  - `id: UUID = field(default_factory=new_uuid7)`, `created_at/updated_at: datetime = field(default_factory=utc_now)`
- `PredictionMarketSnapshot` (frozen dataclass):
  - `id: UUID`, `market_id: str`, `snapshot_at: datetime`, `outcomes_prices: dict[str, float]`
  - `volume_24h: Decimal | None`, `liquidity: Decimal | None`, `source_event_id: str`
  - `__post_init__`: validate `snapshot_at.tzinfo is not None`, `len(outcomes_prices) >= 2`

**Acceptance criteria**:
- [ ] Entities have no infrastructure imports (R12)
- [ ] `PredictionMarketSnapshot` validates UTC-aware `snapshot_at` and `len(outcomes_prices) >= 2`

---

##### T-B-1-04: S3 repository ports for prediction markets

**Type**: impl
**depends_on**: [T-B-1-03]
**blocks**: [T-B-1-05, T-B-1-06]
**Target files**: `services/market-data/src/market_data/application/ports/repositories.py`
**PRD reference**: §6.5

**New ABCs**:
```python
class PredictionMarketRepository(ABC):
    @abstractmethod
    async def upsert(self, market: PredictionMarket) -> PredictionMarket: ...
    @abstractmethod
    async def find_by_market_id(self, market_id: str) -> PredictionMarket | None: ...
    @abstractmethod
    async def list_markets(self, *, status: str | None, query: str | None, limit: int, offset: int) -> tuple[list[PredictionMarket], int]: ...

class PredictionMarketSnapshotRepository(ABC):
    @abstractmethod
    async def insert_if_not_exists(self, snapshot: PredictionMarketSnapshot) -> bool: ...
    @abstractmethod
    async def list_snapshots(self, market_id: str, *, from_dt: datetime | None, to_dt: datetime | None, limit: int) -> list[PredictionMarketSnapshot]: ...
```

**Acceptance criteria**:
- [ ] ABCs added; `mypy --strict` passes
- [ ] Methods have correct signatures with all type annotations

---

##### T-B-1-05: S3 repository implementations

**Type**: impl
**depends_on**: [T-B-1-02, T-B-1-04]
**blocks**: [T-B-1-06]
**Target files**: `services/market-data/src/market_data/infrastructure/db/repositories/prediction_market_repo.py`
**PRD reference**: §7.2

**Implementations**:
- `SqlaPredictionMarketRepository`:
  - `upsert`: `INSERT INTO prediction_markets (...) ON CONFLICT (market_id) DO UPDATE SET question=..., resolution_status=..., updated_at=now() RETURNING *`
  - `list_markets`: dynamic WHERE clause with optional `resolution_status =` and `question ILIKE` filters; `COUNT(*) OVER()` for total
- `SqlaPredictionMarketSnapshotRepository`:
  - `insert_if_not_exists`: `INSERT INTO prediction_market_snapshots (...) ON CONFLICT (market_id, snapshot_at) DO NOTHING RETURNING id`; returns `True` if row returned, `False` if conflict
  - `list_snapshots`: ordered by `snapshot_at DESC`, optional time range filters

**Guards**: BP-076 (no `::type` cast syntax), BP-032 (use `.returning()` on upsert), BP-077 (ON CONFLICT must reference exact unique index)

**Acceptance criteria**:
- [ ] `upsert` updates existing `question`/`resolution_status` correctly
- [ ] `insert_if_not_exists` returns `False` on duplicate `(market_id, snapshot_at)`
- [ ] `list_markets` with `status=None` returns all; with `status="open"` filters correctly

---

##### T-B-1-06: Extend S3 UoW with prediction market repositories

**Type**: impl
**depends_on**: [T-B-1-04, T-B-1-05]
**blocks**: [T-B-1-07]
**Target files**: `services/market-data/src/market_data/application/ports/uow.py`, `services/market-data/src/market_data/infrastructure/db/uow.py`
**PRD reference**: §7.2

**What to build**:
- Extend `UnitOfWork` ABC with write-side repos:
  - `@property @abstractmethod def prediction_markets(self) -> PredictionMarketRepository`
  - `@property @abstractmethod def prediction_market_snapshots(self) -> PredictionMarketSnapshotRepository`
- Extend `ReadOnlyUnitOfWork` ABC with read-side repos (same interfaces):
  - `@property @abstractmethod def prediction_markets_read(self) -> PredictionMarketRepository`
  - `@property @abstractmethod def prediction_market_snapshots_read(self) -> PredictionMarketSnapshotRepository`
- Implement in `SqlAlchemyUnitOfWork` and `SqlAlchemyReadOnlyUnitOfWork` wiring concrete repos

**Guard R27**: read-only endpoints must use `ReadOnlyUnitOfWork`

**Acceptance criteria**:
- [ ] Both ABCs and implementations have the 4 new properties
- [ ] `mypy --strict` passes

---

##### T-B-1-07: Implement `PredictionMarketConsumer`

**Type**: impl
**depends_on**: [T-A-1-01 — schema must exist, T-B-1-02, T-B-1-03, T-B-1-06]
**blocks**: none
**Target files**: `services/market-data/src/market_data/infrastructure/messaging/consumers/prediction_market_consumer.py`, `services/market-data/src/market_data/infrastructure/messaging/consumers/prediction_market_consumer_main.py`
**PRD reference**: §6.4

**What to build**:
Kafka consumer that materializes `market.prediction.v1` events into S3's prediction market tables.

**Class**: `PredictionMarketConsumer(BaseKafkaConsumer[dict])`
- Topic: `market.prediction.v1`
- Consumer group: `market-data-prediction-markets`
- `deserialize_value`: Confluent Avro deserialization via `_SCHEMA_DIR / "market.prediction.v1.avsc"` (same as `OHLCVConsumer`) — detect magic byte `0x00` for Confluent wire format (BP-122)
- `extract_event_id`: `return str(value["event_id"])`
- `is_duplicate`: `return False` (dedup done atomically in `process_message`)
- `mark_processed`: no-op
- `process_message` logic:
  1. `event_id = value["event_id"]`
  2. Atomic event-id dedup: `created = await uow.processed_events.create_if_not_exists(event_id, "market.prediction.v1", None)` → if `not created`: return (duplicate)
  3. Build `PredictionMarket` from event fields
  4. `await uow.prediction_markets.upsert(market)`
  5. Build `PredictionMarketSnapshot`: `snapshot_at = parse_datetime(value["occurred_at"])`, `outcomes_prices = {o["name"]: o["price"] for o in value["outcomes"]}`, `source_event_id = event_id`
  6. `await uow.prediction_market_snapshots.insert_if_not_exists(snapshot)` (idempotent)
  7. `await uow.commit()`

**Main entry point** (`prediction_market_consumer_main.py`):
- `asyncio.run(main())` with SIGINT/SIGTERM handling
- R22: independent process (own `docker-compose` entry)

**Docker Compose** (add to `services/market-data/docker-compose.yml`):
```yaml
market-data-prediction-market-consumer:
  image: market-data
  command: python -m market_data.infrastructure.messaging.consumers.prediction_market_consumer_main
  depends_on: [kafka, market-data-db]
  env_file: .env
```

**Guards**: BP-034 (event-id dedup before any early returns), BP-035 (atomic `create_if_not_exists`), BP-122 (Confluent magic byte detection), R9 (idempotency), R22 (independent process)

**Tests to write** (in `services/market-data/tests/unit/test_prediction_market_consumer.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_process_message_upserts_market` | valid event → prediction_markets upserted | unit |
| `test_process_message_inserts_snapshot` | valid event → snapshot inserted | unit |
| `test_process_message_idempotent` | same event_id twice → 1 snapshot | unit |
| `test_process_message_duplicate_event_skipped` | `create_if_not_exists` returns False → no writes | unit |
| `test_process_message_malformed_market_id` | missing `market_id` → MalformedDataError | unit |
| `test_consumer_integration_upserts_metadata` | end-to-end with Postgres | integration |
| `test_consumer_integration_idempotent` | same event consumed twice → 1 row | integration |

**Acceptance criteria**:
- [ ] Consumer processes test event and writes both rows
- [ ] Duplicate event (same `event_id`) → no additional rows written
- [ ] Consumer starts cleanly in Docker Compose

---

#### Pre-read (agent must read before starting Wave B-1)
- `services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py` — canonical consumer pattern
- `services/market-data/src/market_data/application/ports/uow.py` — UoW extension pattern
- `services/market-data/alembic/versions/004_*.py` — migration numbering
- `services/market-data/src/market_data/infrastructure/db/models/` — ORM model patterns

#### Validation Gate B-1
- [ ] `uvx ruff check + format --check + mypy --strict services/market-data/src/` — zero violations
- [ ] `python -m pytest services/market-data/tests/unit/ -v` — all 516+ existing tests pass; 7+ new tests pass
- [ ] `python -m pytest services/market-data/tests/integration/ -v` — 2 new integration tests pass
- [ ] Migration applies cleanly in TimescaleDB Docker container
- [ ] Consumer process starts and processes a manually crafted test event

#### Regression Guardrails
- **BP-122**: Confluent Avro wire format deserialization — detect `0x00` magic byte; copy exact pattern from `OHLCVConsumer`
- **BP-034**: Event-id dedup must be the FIRST operation in `process_message` before any domain logic
- **BP-035**: Use atomic `create_if_not_exists`, not separate check-then-insert (race condition)
- **BP-019**: ORM-DDL alignment for both new models; extend DDL alignment test
- **BP-076**: No `::type` cast syntax in repository raw SQL; use `CAST(:param AS type)`
- **R22**: Consumer must be an independent process (own main + docker-compose entry)

---

### Wave B-2: S3 API Endpoints + Use Cases + Read Repositories

**Goal**: Expose the three prediction market query endpoints from S3.
**Depends on**: Wave B-1 complete
**Estimated effort**: 60–90 min
**Architecture layer**: application + API

#### Tasks

---

##### T-B-2-01: S3 prediction market query use cases

**Type**: impl
**depends_on**: [T-B-1-06]
**blocks**: [T-B-2-04]
**Target files**: `services/market-data/src/market_data/application/use_cases/query_prediction_markets.py`
**PRD reference**: §6.2

**Use cases** (all use `ReadOnlyUnitOfWork`, per R27):
```python
class ListPredictionMarketsUseCase:
    async def execute(self, *, status: str | None = "open", query: str | None = None,
                      limit: int = 50, offset: int = 0) -> tuple[list[tuple[PredictionMarket, dict[str, float]]], int]
    # Returns (market, outcomes_prices) tuples; outcomes_prices from latest snapshot per market
    # Repository fetches latest snapshot prices in the same query via subquery (avoid N+1)

class GetPredictionMarketUseCase:
    async def execute(self, market_id: str) -> tuple[PredictionMarket, dict[str, float]] | None
    # Returns (market, outcomes_prices) or None; outcomes_prices from latest snapshot

class GetPredictionMarketHistoryUseCase:
    async def execute(self, market_id: str, *, from_dt: datetime | None = None,
                      to_dt: datetime | None = None, limit: int = 500) -> list[PredictionMarketSnapshot]
    # Validates: if from_dt and to_dt: assert from_dt < to_dt else raise ValueError
```

**OutcomePrice[] assembly** (performed by router using data from use case):
```python
# market.outcomes = [{"name": "Yes", "token_id": "..."}, {"name": "No", "token_id": "..."}]
# outcomes_prices = {"Yes": 0.72, "No": 0.28}
outcomes_response = [
    OutcomePriceResponse(name=o["name"], token_id=o["token_id"],
                         price=outcomes_prices.get(o["name"], 0.0))
    for o in market.outcomes
]
```

**Guard R27**: These are read-only use cases; they MUST use `ReadOnlyUnitOfWork`, never `UnitOfWork`

**Acceptance criteria**:
- [ ] 3 use cases implemented with correct signatures
- [ ] `ListPredictionMarketsUseCase` returns latest prices without N+1 queries
- [ ] `GetPredictionMarketHistoryUseCase.execute` raises `ValueError` when `from_dt > to_dt`

---

##### T-B-2-02: S3 API response schemas

**Type**: impl
**depends_on**: none
**blocks**: [T-B-2-04]
**Target files**: `services/market-data/src/market_data/api/schemas/prediction_markets.py`
**PRD reference**: §6.2

**Pydantic models**:
```python
class OutcomePriceResponse(BaseModel):
    name: str; token_id: str; price: float

class PredictionMarketSummaryResponse(BaseModel):
    market_id: str; question: str; outcomes: list[OutcomePriceResponse]
    volume_24h: float | None; close_time: datetime | None
    resolution_status: str; resolved_answer: str | None; updated_at: datetime

class PredictionMarketDetailResponse(PredictionMarketSummaryResponse):
    description: str | None; created_at: datetime

class PredictionMarketsListResponse(BaseModel):
    items: list[PredictionMarketSummaryResponse]; total: int; limit: int; offset: int

class SnapshotPointResponse(BaseModel):
    snapshot_at: datetime; outcomes_prices: dict[str, float]
    volume_24h: float | None

class PredictionMarketHistoryResponse(BaseModel):
    market_id: str; snapshots: list[SnapshotPointResponse]
```

**Guard BP-043**: Use `Annotated[str, StringConstraints(strip_whitespace=True)]` where applicable

**Acceptance criteria**:
- [ ] All models parse cleanly; `mypy --strict` passes

---

##### T-B-2-03: S3 API router for prediction markets

**Type**: impl
**depends_on**: [T-B-2-01, T-B-2-02]
**blocks**: [T-B-2-04]
**Target files**: `services/market-data/src/market_data/api/routers/prediction_markets.py`, `services/market-data/src/market_data/api/dependencies.py`
**PRD reference**: §6.2

**Endpoints**:
```
GET /api/v1/prediction-markets                     → list (status, query, limit, offset params)
GET /api/v1/prediction-markets/{market_id}         → detail (404 if not found)
GET /api/v1/prediction-markets/{market_id}/history → history (from_dt, to_dt, limit params)
```

**All routes use `ReadUoWDep`** (R27)

**Guards**:
- R25: No infrastructure imports in router; all reads via use cases
- R16: API layer uses only use cases
- Register literal routes before path-param routes to avoid matching conflicts

**Acceptance criteria**:
- [ ] `GET /api/v1/prediction-markets?status=open` returns 200 with `PredictionMarketsListResponse`
- [ ] `GET /api/v1/prediction-markets/unknown-id` returns 404
- [ ] `GET /api/v1/prediction-markets/{id}/history?from=invalid` returns 422

---

##### T-B-2-04: Register router in S3 app

**Type**: impl
**depends_on**: [T-B-2-03]
**blocks**: none
**Target files**: `services/market-data/src/market_data/app.py`
**PRD reference**: §6.2

**What to build**:
Import and register `prediction_markets_router` in `app.py` under the existing API prefix.

**Acceptance criteria**:
- [ ] `GET /api/v1/prediction-markets` returns 200 (empty list) against the running Docker Compose S3 service

---

##### T-B-2-05: Tests for Wave B-2

**Type**: test
**depends_on**: [T-B-2-03]
**blocks**: none
**Target files**: `services/market-data/tests/unit/test_prediction_markets_api.py`, `services/market-data/tests/unit/test_prediction_markets_use_cases.py`, `services/market-data/tests/integration/test_prediction_markets_api_integration.py`
**PRD reference**: §11

**Unit tests**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_list_markets_endpoint_200` | GET /api/v1/prediction-markets returns 200 + PredictionMarketsListResponse | unit |
| `test_get_market_endpoint_200` | GET /api/v1/prediction-markets/{id} returns PredictionMarketDetailResponse | unit |
| `test_get_market_endpoint_404` | unknown market_id → 404 | unit |
| `test_get_history_endpoint_200` | valid market_id → time-series SnapshotPointResponse list | unit |
| `test_list_markets_filters_by_status` | ?status=resolved returns only resolved markets | unit |
| `test_list_markets_query_filter` | ?query= substring matches question (case-insensitive) | unit |
| `test_list_markets_invalid_limit` | ?limit=0 → 422 | unit |
| `test_history_invalid_date_range` | from_dt > to_dt → 400 | unit |
| `test_use_case_history_from_equals_to_raises` | from_dt == to_dt → ValueError | unit |
| `test_outcome_price_assembly` | OutcomePrice[] built from market.outcomes + latest snapshot prices; fallback to 0.0 for unknown outcome | unit |

**Acceptance criteria**:
- [ ] All 10 unit tests pass
- [ ] Zero regressions in existing 516+ S3 tests

---

#### Pre-read (agent must read before starting Wave B-2)
- `services/market-data/src/market_data/api/routers/` — existing router patterns
- `services/market-data/src/market_data/application/use_cases/` — use case patterns
- `services/market-data/src/market_data/api/dependencies.py` — dependency injection patterns
- `services/market-data/src/market_data/app.py` — router registration

#### Validation Gate B-2
- [ ] `uvx ruff check + format --check + mypy --strict services/market-data/src/` — zero violations
- [ ] `python -m pytest services/market-data/tests/ -v` — all 516+ existing tests pass; 9+ new tests pass
- [ ] Docker Compose: `curl http://localhost:8003/api/v1/prediction-markets` → 200 with `{"items":[],"total":0,...}`
- [ ] `GET /api/v1/prediction-markets/unknown` → 404

#### Regression Guardrails
- **R25**: No infrastructure imports in router file — router must only call use cases
- **R16**: API layer uses only use cases — verify no direct repository calls in router
- **R27**: All prediction market endpoints use `ReadUoWDep`, not `UoWDep`
- **BP-043**: Pydantic validators use `StringConstraints(strip_whitespace=True)` not deprecated `Field(strip_whitespace=True)`

---

## SUB-PLAN C — S9 API Gateway

### Wave C-1: Gateway Proxy Routes for Prediction Markets

**Goal**: Expose prediction market endpoints through S9 with JWT auth and tenant forwarding.
**Depends on**: Wave B-2 complete (S3 endpoints must exist)
**Estimated effort**: 30–45 min
**Architecture layer**: API (proxy layer)

#### Tasks

---

##### T-C-1-01: Add prediction market proxy routes to S9

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-03]
**Target files**: `services/api-gateway/src/api_gateway/routes/proxy.py` (or equivalent proxy router)
**PRD reference**: §6.2

**Endpoints** (under existing `/v1` prefix):
```
GET /v1/signals/prediction-markets          → proxy → S3 GET /api/v1/prediction-markets
GET /v1/signals/prediction-markets/{id}     → proxy → S3 GET /api/v1/prediction-markets/{id}
GET /v1/signals/prediction-markets/{id}/history → proxy → S3 GET /api/v1/prediction-markets/{id}/history
```

**Pattern**: Forward query params via `dict(request.query_params)`, forward JWT/tenant headers via `_auth_headers(request)`, stream S3 response to client.

**JWT auth**: S9's existing `JWTMiddleware` already validates JWT on all `/v1/*` routes — no additional auth code needed.

**Acceptance criteria**:
- [ ] `GET /v1/signals/prediction-markets` with valid JWT → 200
- [ ] `GET /v1/signals/prediction-markets` without JWT → 401
- [ ] Query params (`?status=open`) forwarded correctly to S3

---

##### T-C-1-02: Tests for Wave C-1

**Type**: test
**depends_on**: [T-C-1-01]
**blocks**: none
**Target files**: `services/api-gateway/tests/test_prediction_market_proxy.py`
**PRD reference**: §10

**Tests**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_list_proxy_forwards_query_params` | ?status=open forwarded to S3 | unit |
| `test_detail_proxy_404_passthrough` | S3 returns 404 → gateway returns 404 | unit |
| `test_history_proxy_forwards_date_params` | from/to/limit params forwarded | unit |
| `test_jwt_required` | missing JWT → 401 | unit |

**Acceptance criteria**:
- [ ] All 4 tests pass; all 28 existing gateway tests still pass

---

#### Pre-read (agent must read before starting Wave C-1)
- `services/api-gateway/src/api_gateway/routes/proxy.py` — existing proxy pattern
- `services/api-gateway/src/api_gateway/middleware/` — JWT middleware
- `services/api-gateway/tests/` — existing test patterns

#### Validation Gate C-1
- [ ] `uvx ruff check + format --check + mypy --strict services/api-gateway/src/` — zero violations
- [ ] `python -m pytest services/api-gateway/tests/ -v` — all 28+ existing tests pass; 4 new tests pass
- [ ] End-to-end: gateway proxies to S3 in Docker Compose with a test JWT

#### Regression Guardrails
- **R14**: Frontend must only talk to S9 — these proxy routes are the correct integration point
- No direct S3 imports or imports from other services in S9 router

---

## SUB-PLAN D — Frontend

### Wave D-1: PredictionMarketsPanel Component

**Goal**: Surface open prediction markets in the UI with probability bars and volume indicators.
**Depends on**: Wave C-1 complete (S9 endpoints must be accessible)
**Estimated effort**: 45–75 min
**Architecture layer**: frontend

#### Tasks

---

##### T-D-1-01: TypeScript interfaces for prediction market API

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-02]
**Target files**: `apps/frontend/src/lib/types.ts` or `apps/frontend/src/lib/predictionMarkets.ts`
**PRD reference**: §6.6

```typescript
interface OutcomePrice {
  name: string;
  token_id: string;
  price: number;  // 0.0–1.0
}

interface PredictionMarketSummary {
  market_id: string;
  question: string;
  outcomes: OutcomePrice[];
  volume_24h: number | null;
  close_time: string | null;   // ISO-8601 UTC
  resolution_status: string;
  resolved_answer: string | null;
  updated_at: string;
}

interface PredictionMarketsListResponse {
  items: PredictionMarketSummary[];
  total: number;
  limit: number;
  offset: number;
}
```

**Acceptance criteria**:
- [ ] TypeScript compiles without errors
- [ ] Interfaces match S3 API response schema exactly

---

##### T-D-1-02: Create `PredictionMarketsPanel` component

**Type**: impl
**depends_on**: [T-D-1-01]
**blocks**: [T-D-1-03]
**Target files**: `apps/frontend/src/components/PredictionMarketsPanel.tsx`
**PRD reference**: §6.6

**What to build**:
React component that fetches open prediction markets from S9 and displays them as cards.

**Logic**:
- React Query: `useQuery(['prediction-markets'], fetchMarkets, { refetchInterval: 5 * 60 * 1000 })`
- API: `GET /api/v1/signals/prediction-markets?status=open&limit=20`
- Sort: `volume_24h DESC` (client-side, null values last)
- Per card:
  - Market question (truncated at 120 chars with `title` tooltip for full text)
  - Probability bar: `width: ${yes.price * 100}%` CSS, green/red colors
  - Labels: `"72% Yes · 28% No"` (using outcome names from API)
  - Volume: `"Vol: $1.2M"` (formatted via `Intl.NumberFormat`)
  - Close time: `"closes in 3 days"` (via `date-fns` `formatDistanceToNow`)
- Loading: 3 skeleton rows
- Empty: `"No active prediction markets"` centered
- Error: `"Failed to load prediction markets"` with retry button
- TypeScript: fully typed, no `any`

**Acceptance criteria**:
- [ ] Component renders without TypeScript errors
- [ ] Probability bar width proportional to Yes price (e.g., 0.72 → 72% width)
- [ ] Loading/empty/error states implemented

---

##### T-D-1-03: Integrate `PredictionMarketsPanel` into the page

**Type**: impl
**depends_on**: [T-D-1-02]
**blocks**: none
**Target files**: `apps/frontend/src/pages/NewsPage.tsx` (or appropriate page — read existing layout first)
**PRD reference**: §6.6

**What to build**:
Read `NewsPage.tsx` layout first, then add `<PredictionMarketsPanel />` in the most natural position (below news list or as sidebar section under a "Prediction Markets" heading).

**Acceptance criteria**:
- [ ] Panel appears in UI; `pnpm build` succeeds

---

##### T-D-1-04: Frontend tests for `PredictionMarketsPanel`

**Type**: test
**depends_on**: [T-D-1-02]
**blocks**: none
**Target files**: `apps/frontend/src/__tests__/PredictionMarketsPanel.test.tsx`
**PRD reference**: §10

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `renders_skeleton_while_loading` | skeleton rows during loading state | unit |
| `renders_market_cards_on_success` | mocked response → correct card count | unit |
| `renders_empty_state_when_no_markets` | empty items → "No active prediction markets" | unit |
| `renders_error_state_on_api_failure` | API throws → error message shown | unit |
| `probability_bar_proportional_to_price` | Yes=0.72 → bar width ≥70% | unit |
| `close_time_formatted_as_relative` | close_time in future → "closes in N days" | unit |

**Acceptance criteria**:
- [ ] All 6 tests pass
- [ ] All existing frontend tests still pass

---

#### Pre-read (agent must read before starting Wave D-1)
- `apps/frontend/src/pages/NewsPage.tsx` — layout and import patterns
- `apps/frontend/src/components/` — existing component patterns
- `apps/frontend/src/lib/` — existing API fetch patterns
- `apps/frontend/package.json` — test runner and available libraries

#### Validation Gate D-1
- [ ] `pnpm build` (or `npm run build`) — zero TypeScript errors
- [ ] All existing frontend tests pass; 6 new tests pass
- [ ] Visual inspection in Docker Compose dev server shows panel with mock/live data

#### Regression Guardrails
- **R14**: Frontend only talks to S9 at `/api/v1/signals/...` — never directly to S3/S4
- No direct service URLs hardcoded; use the same API base URL pattern as existing components

---

## Cross-Cutting Concerns

### Observability Metrics (add in respective waves)
- S4: `s4_polymarket_polls_total{status}`, `s4_polymarket_markets_fetched_total`, `s4_polymarket_markets_skipped_total{reason}`
- S3: `s3_prediction_market_events_consumed_total{status}`, `s3_prediction_market_snapshots_total`, `s3_prediction_market_api_requests_total{endpoint, status_code}`

### Documentation Updates (mandatory per R15)
After each sub-plan, update:
- `services/content-ingestion/.claude-context.md`: Add POLYMARKET to source types, `prediction_market_fetch_log` to tables, `market.prediction.v1` to topics
- `services/market-data/.claude-context.md`: Add 3 new endpoints, 2 new tables, `market.prediction.v1` topic
- `docs/MASTER_PLAN.md`: Add `market.prediction.v1` to the Kafka event topology

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Polymarket Gamma API schema changes | Medium | High | `from_gamma_response()` is single mapping point; use defensive `.get()` with defaults for all optional fields |
| TimescaleDB `create_hypertable` in non-TS test containers | Medium | Medium | Wrap in presence check; existing `market_data_db` already has TimescaleDB enabled |
| asyncpg `::type` cast syntax (BP-076) | High | Medium | Enforce `CAST(:param AS type)` syntax; add guard in code review |
| Consumer dedup race (BP-035) | High | Medium | Copy atomic `create_if_not_exists` pattern exactly from `OHLCVConsumer`; no reimplementation |
| ORM-DDL alignment drift (BP-019) | Medium | High | DDL alignment test must cover new models; checked in each sub-plan's validation gate |
| Avro schema inline dict instead of file (BP-119) | High | Medium | Consumer loads from `_SCHEMA_DIR / filename`; no inline schema dicts |
| Missing schema COPY in Docker image (BP-106) | High | High | Verify S3 and S4 Dockerfiles contain `COPY infra/kafka/schemas /app/infra/kafka/schemas` |

---

## Effort Summary

| Sub-Plan | Waves | Tasks | Estimated Effort |
|----------|-------|-------|-----------------|
| A (S4) | 2 | 10 | 2.5–3.5 hours |
| B (S3) | 2 | 12 | 2.5–3.5 hours |
| C (S9) | 1 | 2 | 30–45 min |
| D (Frontend) | 1 | 4 | 45–75 min |
| **Total** | **6** | **28** | **6–8 hours** |

---

## Recommended Execution Order

1. **Session 1** — Wave A-1 (schema + domain + migration — unblocks everything)
2. **Session 2** — Wave A-2 (PolymarketAdapter + EDGAR fix — S4 producer goes live)
3. **Session 3** — Wave B-1 (S3 migration + consumer — materializer goes live)
4. **Session 4** — Wave B-2 (S3 API endpoints — query layer goes live)
5. **Session 5** — Wave C-1 (S9 proxy — gateway exposes prediction markets)
6. **Session 6** — Wave D-1 (Frontend panel — end-user visible)
