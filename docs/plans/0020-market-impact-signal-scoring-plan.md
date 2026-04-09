# PLAN-0020 — Market-Impact Signal Scoring (Option A)

> **PRD**: `docs/specs/0020-market-impact-signal-scoring.md`
> **Status**: in-progress
> **Updated**: 2026-04-09
> **Author**: Arnau Rodon
> **Generated**: 2026-04-09
> **Services affected**: S6 (NLP Pipeline), `nlp_db` (Alembic migration owned by S6)
> **Depends on**: PLAN-0015 complete ✅, PLAN-0019 complete ✅

---

## Phase 0.5 — PRD Pre-Flight Gate

| Check | Result | Notes |
|-------|--------|-------|
| **PC-1: External API fields exist** | PASS | No external API fields — OHLCV lookup uses S3 REST API internally, which is already production-ready (PLAN-0018 complete) |
| **PC-2: PRD < 14 days old** | PASS | PRD dated 2026-04-06, plan generated 2026-04-09 (3 days) |
| **PC-3: Dependency plans complete** | PASS | PLAN-0015 ✅ (S8 infra), PLAN-0019 ✅ (S3 OHLCV API). PRD says "S3 OHLCV API" but notes that S3 is the Market Data service (port 8003) — verified |
| **PC-4: No cross-PRD conflicts** | PASS | PLAN-0021 (Flash Alerts) consumes `nlp.signal.detected.v1` — the new `market_impact_score` field is forward-compatible (default 0.0), PLAN-0021 unaffected |
| **PC-5: Architecture alignment** | PASS — with one clarification | PRD §6.5 says "Query `intelligence_db.article_claims`" — actual source for unlabelled articles should be `nlp_db.entity_mentions` (doc_id + resolved_entity_id joins) since `article_claims` lives in `intelligence_db` (cross-service DB access prohibited, R7). Resolution: worker queries `nlp_db.entity_mentions` for articles with resolved entities, then calls S3 REST API. Confirmed compliant with R7. |

**Pre-flight verdict**: APPROVED — one architecture clarification resolved in task specs below.

---

## Codebase State Verification (Delta Table)

| PRD Claim | Actual State | Delta |
|-----------|-------------|-------|
| Block 5 has 7 signals summing to 1.0 | CONFIRMED — `routing.py` has exactly 7 signals (`entity_density=0.30, source_reliability=0.20, novelty=0.15, recency=0.10, watchlist=0.10, document_type=0.10, extraction_yield=0.05`). Note: PRD uses key name `watchlist_match` but code uses `watchlist`. | Key name mismatch: PRD says `watchlist_match`, code key is `watchlist`. Plan uses `watchlist` to match code. |
| `article_price_impacts` table exists | DOES NOT EXIST — nlp_db has 0001–0004 migrations, no price impact table | Must create migration 0005 |
| `PriceImpactLabellingWorker` exists | DOES NOT EXIST — `infrastructure/workers/` only has `embedding_retry_worker.py` | Must create |
| `market.signal.v1` Kafka topic | NOT referenced in PRD — PRD uses existing `nlp.signal.detected.v1` with new `market_impact_score` field | Correct, no new topic needed |
| `nlp.signal.detected.v1.avsc` has `market_impact_score` | DOES NOT EXIST — current schema has 13 fields, no market_impact_score | Must add field with `"default": 0.0` |
| S6 API signals endpoint | EXISTS — `GET /api/v1/signals` at `api/routes/signals.py`, `SignalListResponse` model | Must add `market_impact_score` field to `SignalResponse` and `SignalData` |
| `workers/` directory exists | EXISTS — `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/` | New worker fits here |
| S6 config has impact settings | DOES NOT EXIST — `config.py` has no `impact_normalisation_cap_pct` or cycle settings | Must add 3 new settings |
| Docker Compose S6 has 4 processes (API, dispatcher, article-consumer, watchlist-consumer) | CONFIRMED — 4 services in docker-compose.yml | Must add 5th: `nlp-pipeline-price-impact-worker` |
| S3 OHLCV endpoint available internally | CONFIRMED — Market Data service at port 8003 serves `GET /api/v1/market-data/ohlcv/{symbol}?date={date}` (PLAN-0018 complete) | Need internal HTTP client |

---

## Dependency Graph

```
Wave A-1: Alembic migration (article_price_impacts table in nlp_db)
    │
    ▼
Wave A-2: Domain entity (ArticlePriceImpact) + port interface (PriceImpactRepository)
    │
    ├──────────────────────────────────────────────────────────┐
    ▼                                                          ▼
Wave A-3: Avro schema update (nlp.signal.detected.v1)      Wave B-1: PriceImpactLabellingWorker + S3 HTTP client
    │                                                          │
    ▼                                                          ▼
Wave A-4: Block 5 weight rebalance + price_impact signal   Wave B-2: Worker process entry point + Docker Compose
    │                                                          │
    ▼                                                          │
Wave A-5: API signals endpoint + schema updates                │
    │                                                          │
    └─────────────────────────┬────────────────────────────────┘
                              ▼
                     Wave A-6: Tests + docs
```

**Critical path**: A-1 → A-2 → (A-3 || B-1) → A-4 → A-5 → A-6
**Parallelizable**: A-3 and B-1 can run in parallel after A-2; B-2 can run in parallel with A-4/A-5.

---

## Sub-Plan A: S6 Core Signal Changes

**Scope**: DB migration, domain model, Avro schema, Block 5 rebalance, API endpoint update.
**Service**: `services/nlp-pipeline/`
**DB**: `nlp_db` (S6-owned via Alembic)

---

### Wave A-1: Database Migration — `article_price_impacts` ✅

**Goal**: Add `article_price_impacts` table to `nlp_db` via a new Alembic migration.
**Depends on**: none (first wave)
**Estimated effort**: 0.5 wave (Low complexity)
**Status**: **DONE** — 2026-04-09 · 14 tests pass · ruff + mypy clean
**Architecture layer**: Infrastructure — Database

#### Tasks

##### T-A-1-01: Alembic migration `0005_add_article_price_impacts.py`

**Type**: schema
**depends_on**: none
**blocks**: [T-A-2-01, T-A-2-02]
**Target files**:
- `services/nlp-pipeline/alembic/versions/0005_add_article_price_impacts.py`

**PRD reference**: §6.4 (Database Changes)

**What to build**: Create a new Alembic migration that adds the `article_price_impacts` table to `nlp_db`. The migration must use `op.execute()` for the partial index on `impact_score` (SQLAlchemy's `create_index()` does not support `WHERE` clauses). The migration must be idempotent and include a `downgrade()` that drops the table and all indexes.

**Entities / Components**:
- **Name**: `article_price_impacts` table
  - **Purpose**: Stores retrospective price-impact labels for processed articles
  - **Key attributes**:
    - `id UUID PK NOT NULL DEFAULT gen_random_uuid()` — application sets UUIDv7 via `new_uuid7()`; migration uses `gen_random_uuid()` as server default (pattern from existing migrations in this service)
    - `article_id UUID UNIQUE NOT NULL` — logical FK to `content_store_db.documents.id`; UNIQUE enforces one-row-per-article
    - `entity_id UUID NOT NULL` — canonical entity whose OHLCV was used
    - `symbol TEXT NOT NULL` — ticker symbol
    - `published_at TIMESTAMPTZ NOT NULL` — article publication time UTC
    - `ohlcv_date DATE NOT NULL` — OHLCV bar date covering publication time
    - `price_open NUMERIC(18,8) NOT NULL` — opening price
    - `price_close NUMERIC(18,8) NOT NULL` — closing price
    - `price_delta_pct NUMERIC(10,6) NOT NULL` — `(close-open)/open*100`
    - `next_day_delta_pct NUMERIC(10,6) NULL` — optional next-day close-to-close delta
    - `max_intraday_range_pct NUMERIC(10,6) NULL` — optional `(high-low)/open*100`
    - `impact_score NUMERIC(6,4) NOT NULL` — normalised 0.0–1.0
    - `computed_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - **Indexes**:
    - `(article_id) UNIQUE` — implicit from UNIQUE constraint
    - `ix_api_entity_date ON (entity_id, ohlcv_date)` — batch lookups by entity
    - `ix_api_impact_score_partial` — `CREATE INDEX ... ON article_price_impacts (impact_score DESC) WHERE impact_score > 0.3` — partial via `op.execute()`
  - **Invariants**: `impact_score` in `[0.0, 1.0]`. `price_open > 0`, `price_close > 0`. No FK constraints (cross-service logical FK, not a physical FK per R7).

**Logic & Behavior**:
1. Set `down_revision` to `'0004'` (current head: `0004_add_embedding_pending.py`)
2. Use `sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))` matching the pattern from migration 0001
3. Use `NUMERIC` type via `sa.Numeric(18, 8)` and `sa.Numeric(10, 6)` and `sa.Numeric(6, 4)`
4. Use `sa.Date()` for `ohlcv_date` (not TIMESTAMPTZ)
5. Create normal indexes via `op.create_index()`
6. Create partial index via `op.execute("CREATE INDEX ix_api_impact_score_partial ON article_price_impacts (impact_score DESC) WHERE impact_score > 0.3")`
7. `downgrade()`: drop indexes, then `op.drop_table("article_price_impacts")`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ddl_alignment_includes_article_price_impacts` | Update `test_ddl_alignment.py` to assert `article_price_impacts` table exists in DB schema and all 13 columns present | unit |

**Acceptance criteria**:
- [x] Migration `0005` runs cleanly against a fresh `nlp_db` (after 0001–0004)
- [x] `article_price_impacts` table exists with all 13 columns
- [x] Three indexes exist: UNIQUE on `article_id`, composite on `(entity_id, ohlcv_date)`, partial on `impact_score > 0.3`
- [x] `downgrade()` drops table and all indexes without error
- [x] DDL alignment test passes

#### Pre-read
- `services/nlp-pipeline/alembic/versions/0004_add_embedding_pending.py` — understand migration format and `down_revision`
- `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py` — UUID column pattern with `gen_random_uuid()`
- `services/nlp-pipeline/tests/unit/infrastructure/test_ddl_alignment.py` — how to extend DDL alignment tests

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/infrastructure/test_ddl_alignment.py -v -m unit
python -m ruff check src/ alembic/
python -m mypy src/ --config-file mypy.ini
```

#### Regression Guardrails
- **BP-019**: Migration DDL vs ORM column mismatch — add ORM model in same wave (T-A-2-01) and verify alignment test
- **BP-126**: Alembic migration NOT NULL column missing `server_default` — `computed_at` uses `server_default=sa.text("now()")`, not Python-side default
- **BP-068**: Use `timescale/timescaledb:latest-pg16` image for integration tests (has pgvector); plain `postgres:16-alpine` is missing the vector extension

---

### Wave A-2: Domain Entity + ORM Model + Repository Port ✅

**Goal**: Add `ArticlePriceImpact` frozen dataclass (domain), `ArticlePriceImpactModel` ORM model, and `PriceImpactRepository` port.
**Depends on**: T-A-1-01 (migration must be in place before ORM alignment test can pass)
**Estimated effort**: 0.5 wave (Low-Medium complexity)
**Status**: **DONE** — 2026-04-09 · 360 tests pass · ruff + mypy clean
**Architecture layer**: Domain + Application (ports) + Infrastructure (ORM model)

#### Tasks

##### T-A-2-01: `ArticlePriceImpact` domain entity

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-3-01, T-B-1-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py` — append `ArticlePriceImpact` dataclass
- `services/nlp-pipeline/src/nlp_pipeline/domain/errors.py` — append `PriceImpactError` (subclass of `DomainError`)

**PRD reference**: §6.5 (Domain Model Changes)

**What to build**: A frozen dataclass `ArticlePriceImpact` representing a retrospective price-impact label. Include a `compute()` class method that validates inputs and computes `impact_score` using the normalisation formula. All monetary fields use `Decimal` (not `float`) for precision. Include a `PriceImpactError` exception subclassing `DomainError` (R21).

**Entities / Components**:
- **Name**: `ArticlePriceImpact`
  - **Purpose**: Immutable domain record of a retrospective price-impact label
  - **Key attributes**:
    - `id: UUID` — UUIDv7, generated by caller via `new_uuid7()`
    - `article_id: UUID` — must be UUIDv7; the article from content store
    - `entity_id: UUID` — canonical entity whose OHLCV was used
    - `symbol: str` — 1–20 chars ticker symbol, stripped of whitespace
    - `published_at: datetime` — UTC-aware (enforce: `tzinfo is not None`)
    - `ohlcv_date: date` — Python `datetime.date` (not datetime)
    - `price_open: Decimal` — must be > 0
    - `price_close: Decimal` — must be > 0
    - `price_delta_pct: Decimal` — `(close-open)/open*100`; can be negative
    - `next_day_delta_pct: Decimal | None` — optional
    - `max_intraday_range_pct: Decimal | None` — optional
    - `impact_score: Decimal` — must be in `[Decimal("0.0"), Decimal("1.0")]`
  - **Key methods**:
    - `ArticlePriceImpact.compute(article_id, entity_id, symbol, published_at, price_open, price_close, normalisation_cap_pct) -> ArticlePriceImpact` — class method factory; computes `price_delta_pct` and `impact_score` internally
    - `ArticlePriceImpact.zero(article_id, entity_id, symbol, published_at, ohlcv_date) -> ArticlePriceImpact` — factory for no-data case (impact_score=0.0, price_open=price_close=Decimal("0"))
  - **Invariants**:
    - `published_at.tzinfo is not None` — UTC-aware required (raises `PriceImpactError` if violated)
    - `Decimal("0.0") <= impact_score <= Decimal("1.0")` — raises `PriceImpactError` if violated
    - `1 <= len(symbol.strip()) <= 20` — raises `PriceImpactError` if violated
    - `price_open >= 0` and `price_close >= 0` — zero allowed for no-data case

**Logic & Behavior**:
1. `compute()` factory:
   a. Validate `published_at.tzinfo is not None`; raise `PriceImpactError` otherwise
   b. Validate `price_open > 0`; raise `PriceImpactError` if not
   c. Compute `price_delta_pct = (price_close - price_open) / price_open * 100`
   d. `impact_score = min(Decimal("1.0"), abs(price_delta_pct) / normalisation_cap_pct)` where `normalisation_cap_pct` defaults to `Decimal("5.0")`
   e. `ohlcv_date = published_at.date()` (date of publication)
   f. Return frozen `ArticlePriceImpact` with `id=new_uuid7()`
2. `zero()` factory: returns impact with all prices at 0 and `impact_score=Decimal("0.0")`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_impact_score_normalisation_zero` | `price_delta_pct=0% → impact_score=0.0` | unit |
| `test_impact_score_at_cap` | `abs(price_delta_pct)=5% → impact_score=1.0` | unit |
| `test_impact_score_exceeds_cap_capped` | `abs(price_delta_pct)=10% → impact_score=1.0 (capped)` | unit |
| `test_impact_score_partial` | `abs(price_delta_pct)=2.5% → impact_score=0.5` | unit |
| `test_negative_delta_uses_abs` | `price_delta_pct=-3% → impact_score=0.6 (abs applied)` | unit |
| `test_naive_datetime_raises` | `published_at without tzinfo → PriceImpactError` | unit |
| `test_impact_score_out_of_range_raises` | Direct construction with `impact_score=-0.1 → PriceImpactError` via `__post_init__` | unit |
| `test_symbol_too_long_raises` | `symbol="X"*21 → PriceImpactError` | unit |
| `test_zero_factory` | `zero()` creates entity with `impact_score=Decimal("0.0")` | unit |

**Acceptance criteria**:
- [x] `ArticlePriceImpact` is frozen dataclass in `domain/models.py`
- [x] `PriceImpactError(DomainError)` in `domain/errors.py`
- [x] All 9 unit tests pass
- [x] mypy strict passes on domain layer (no infrastructure imports)

##### T-A-2-02: ORM model + repository port

**Type**: impl
**depends_on**: [T-A-1-01, T-A-2-01]
**blocks**: [T-B-1-01, T-A-4-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` — append `ArticlePriceImpactModel`
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` — append `PriceImpactRepositoryPort`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/price_impact.py` — new file: `ArticlePriceImpactRepository`

**PRD reference**: §6.4, §6.5

**What to build**: SQLAlchemy ORM model mapping `article_price_impacts` table. Abstract port `PriceImpactRepositoryPort` for the application layer. Concrete `ArticlePriceImpactRepository` backed by SQLAlchemy async session. Repository exposes methods used by the worker and Block 5.

**Entities / Components**:
- **Name**: `ArticlePriceImpactModel`
  - **Purpose**: SQLAlchemy ORM representation of `article_price_impacts`
  - **Key attributes**: Mirror all 13 columns from migration. Use `sa.Numeric` types. `ohlcv_date: Mapped[date]` using `sa.Date()`.
  - **Invariants**: Column types must match migration exactly (BP-019)

- **Name**: `PriceImpactRepositoryPort`
  - **Purpose**: Abstract interface for the worker and Block 5 to interact with `article_price_impacts` without infrastructure imports
  - **Key methods**:
    - `async def upsert(self, impact: ArticlePriceImpact) -> None` — INSERT ON CONFLICT (article_id) DO NOTHING (idempotent, R9)
    - `async def get_by_article_id(self, article_id: UUID) -> ArticlePriceImpact | None`
    - `async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal` — returns max `impact_score` across all entities for an article; returns `Decimal("0.0")` if none found
    - `async def get_unlabelled_articles(self, min_age_hours: int, batch_size: int) -> list[tuple[UUID, list[UUID]]]` — returns `[(doc_id, [entity_id, ...])]` for articles with resolved entities not yet in `article_price_impacts`, published > `min_age_hours` ago

- **Name**: `ArticlePriceImpactRepository`
  - **Purpose**: Concrete SQLAlchemy implementation of `PriceImpactRepositoryPort`
  - **Key attributes**: `_session: AsyncSession`
  - **Key methods**: implement all 4 port methods
  - **Invariants**: `upsert()` uses `INSERT ON CONFLICT (article_id) DO NOTHING` (idempotency); `get_unlabelled_articles()` joins `entity_mentions` on `doc_id` where `resolved_entity_id IS NOT NULL` and `doc_id NOT IN (SELECT article_id FROM article_price_impacts)` and `published_at < now() - :min_age_hours * INTERVAL '1 hour'` — query uses `document_source_metadata.published_at` (available in `nlp_db`)

**Logic & Behavior**:
1. `upsert()`: convert `ArticlePriceImpact` domain object to ORM model; `session.add()`; `await session.flush()` (not commit — caller commits via UoW)
2. `get_max_impact_for_doc()`: `SELECT MAX(impact_score) FROM article_price_impacts WHERE article_id = :doc_id` (note: article_id in the table IS the doc_id from content store — one row per article, not per entity)
3. `get_unlabelled_articles()`: complex query joining `document_source_metadata` (for `published_at`) with `entity_mentions` (for resolved entities), excluding `doc_id`s already in `article_price_impacts`. Group by `doc_id`, aggregate entity_ids. LIMIT `batch_size`.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_upsert_idempotent` | Inserting same `article_id` twice → second insert is a no-op | unit (mock session) |
| `test_get_by_article_id_returns_none` | Unknown article_id → `None` | unit |
| `test_get_max_impact_no_rows` | No rows for doc → `Decimal("0.0")` | unit |
| `test_price_impact_repo_port_is_abstract` | `PriceImpactRepositoryPort` cannot be instantiated directly | unit |

**Acceptance criteria**:
- [x] `ArticlePriceImpactModel` in `models.py` with all 13 columns
- [x] DDL alignment test still passes (update to include new model)
- [x] `PriceImpactRepositoryPort` abstract methods defined
- [x] `ArticlePriceImpactRepository` implements all 4 methods
- [x] mypy strict passes on all 3 files

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/domain/errors.py` — existing DomainError base
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` — port interface pattern
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/signals_query.py` — SqlA query pattern

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/domain/ tests/unit/infrastructure/test_ddl_alignment.py -v -m unit
python -m ruff check src/
python -m mypy src/ --config-file mypy.ini
```

#### Regression Guardrails
- **BP-019**: ORM model must match migration DDL column for column (type, nullability, default)
- **BP-076**: Do not use `::type` cast in `text()` queries — use `bindparam()` with typed SQLAlchemy types
- **BP-021**: Do not name any ORM column `metadata` — use an alias (no collision risk here, but be aware)

---

### Wave A-3: Avro Schema Update ✅

**Goal**: Add `market_impact_score` field to `nlp.signal.detected.v1.avsc` with backward-compatible default.
**Depends on**: T-A-2-01 (domain entity must exist before schema update)
**Estimated effort**: 0.25 wave (Low complexity)
**Status**: **DONE** — 2026-04-09 · 3 contract tests pass · ruff clean
**Architecture layer**: Infrastructure — Contracts

#### Tasks

##### T-A-3-01: Update `nlp.signal.detected.v1.avsc`

**Type**: schema
**depends_on**: [T-A-2-01]
**blocks**: [T-A-5-01]
**Target files**:
- `infra/kafka/schemas/nlp.signal.detected.v1.avsc`

**PRD reference**: §6.3 (Event Changes)

**What to build**: Add `market_impact_score` as the last field in `nlp.signal.detected.v1.avsc` with type `"double"` and `"default": 0.0`. This field is forward-compatible per R5 — existing consumers that do not read this field are unaffected. Must be added at the END of the fields list (Avro forward-compat requires new fields with defaults to be appended, not inserted).

**Entities / Components**:
- **Name**: `market_impact_score` Avro field
  - **Purpose**: Carry the normalised price-impact score (0.0–1.0) on every emitted signal
  - **Key attributes**:
    - `"name": "market_impact_score"`
    - `"type": "double"` — not `"float"` (Avro `float` is 32-bit; `double` is 64-bit, matches Python `float`)
    - `"default": 0.0` — REQUIRED for forward compatibility (R5)
    - `"doc": "Normalised market impact score 0.0–1.0. 0.0 = no OHLCV data or article < 25h old."`

**Logic & Behavior**:
1. Open `infra/kafka/schemas/nlp.signal.detected.v1.avsc`
2. Append the new field as the last element of `"fields"` array
3. Do NOT modify or reorder any existing fields
4. Do NOT change `schema_version` in the envelope — schema version is in the event payload, not the Avro schema itself

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_signal_detected_v1_backward_compatible` | Avro schema with new field can deserialize old messages (no `market_impact_score` field) | contract |
| `test_signal_detected_v1_new_field_defaults` | Old messages deserialized with new schema get `market_impact_score = 0.0` | contract |
| `test_signal_detected_v1_serialise_with_score` | Signal with `market_impact_score=0.75` serialises/deserialises correctly | contract |

**Acceptance criteria**:
- [x] `nlp.signal.detected.v1.avsc` has new `market_impact_score` field as the last field
- [x] `"default": 0.0` is present
- [x] `scripts/gen-contracts.sh` passes (or equivalent avro-tools validation)
- [x] 3 contract tests pass

#### Pre-read
- `infra/kafka/schemas/nlp.signal.detected.v1.avsc` — current schema (13 fields)
- `infra/kafka/schemas/nlp.article.enriched.v1.avsc` — example of another S6 schema

#### Validation Gate
```bash
# Validate Avro schema file is valid JSON and parses correctly
python -c "import json; json.load(open('infra/kafka/schemas/nlp.signal.detected.v1.avsc'))"
cd services/nlp-pipeline
python -m pytest tests/contract/ -v -m contract --no-header 2>/dev/null || echo "contract tests dir may not exist yet"
```

#### Regression Guardrails
- **R5**: New field MUST have a `"default"` value — without default, old consumers crash on deserialization
- **BP-017**: Avro field name `market_impact_score` must match the Python field name used when constructing the outbox event payload

---

### Wave A-4: Block 5 Weight Rebalance + `price_impact` Signal

**Goal**: Rebalance Block 5 routing weights and add `price_impact` as the 8th signal.
**Depends on**: T-A-2-02 (repository port must exist for Block 5 to query impact scores)
**Estimated effort**: 0.5 wave (Low-Medium complexity)
**Architecture layer**: Application — Business logic

#### Tasks

##### T-A-4-01: Update Block 5 routing score with price_impact signal

**Type**: impl
**depends_on**: [T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py`
- `services/nlp-pipeline/tests/unit/application/blocks/test_routing.py`

**PRD reference**: §6.5 (Block 5 Routing Score weight rebalance)

**What to build**: Update `SIGNAL_WEIGHTS` dict to include `price_impact` at weight `0.10` and reduce `entity_density` from `0.30` to `0.25` and `document_type` from `0.10` to `0.05`. Update `compute_routing_score()` to accept an optional `price_impact_score: float = 0.0` parameter. The module-level assertion `sum(SIGNAL_WEIGHTS.values()) == 1.0` must continue to pass (auto-verified).

**Entities / Components**:
- **Name**: `SIGNAL_WEIGHTS` constant update
  - **Purpose**: Defines routing weights for all 8 signals
  - **Key attributes** (new weights):
    - `entity_density: 0.25` (was 0.30, -0.05)
    - `source_reliability: 0.20` (unchanged)
    - `novelty: 0.15` (unchanged)
    - `recency: 0.10` (unchanged)
    - `watchlist: 0.10` (unchanged — note: code key is `watchlist`, not `watchlist_match`)
    - `document_type: 0.05` (was 0.10, -0.05)
    - `extraction_yield: 0.05` (unchanged)
    - `price_impact: 0.10` (NEW)
  - **Invariants**: `sum(SIGNAL_WEIGHTS.values()) == 1.0` — enforced by existing module-level assertion

- **Name**: `compute_routing_score()` signature update
  - **Purpose**: Accept the price_impact signal value from the caller (Block 5 orchestrator)
  - **Key methods**:
    - New parameter: `price_impact_score: float = 0.0` — keyword-only argument added after existing keyword args
  - **Invariants**: `price_impact_score` must be in `[0.0, 1.0]`; clamp silently if out of range

**Logic & Behavior**:
1. Update `SIGNAL_WEIGHTS` dict — the module-level `assert` immediately validates the sum
2. Add `price_impact_score: float = 0.0` as keyword-only param to `compute_routing_score()`
3. Add `"price_impact": max(0.0, min(1.0, price_impact_score))` to `feature_scores` dict
4. `feature_scores` dict now has 8 keys — update any type annotation or docstring that says "7"
5. Callers that don't pass `price_impact_score` default to 0.0 (backward compatible at Python call level)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_weights_sum_to_one_after_rebalance` | `sum(SIGNAL_WEIGHTS.values()) == 1.0` (update existing test, or rename to be clear) | unit |
| `test_eight_signals` | `len(SIGNAL_WEIGHTS) == 8` (update existing `test_seven_signals`) | unit |
| `test_price_impact_zero_when_not_provided` | `compute_routing_score(...)` without `price_impact_score` → `feature_scores["price_impact"] == 0.0` | unit |
| `test_price_impact_included_in_composite` | `price_impact_score=1.0` increases composite score by approximately 0.10 (weight * 1.0) | unit |
| `test_price_impact_clamped_below_zero` | `price_impact_score=-0.5` → clamped to 0.0 in feature_scores | unit |
| `test_price_impact_clamped_above_one` | `price_impact_score=1.5` → clamped to 1.0 in feature_scores | unit |
| `test_feature_scores_has_8_keys` | `len(decision.feature_scores) == 8` | unit |

**Acceptance criteria**:
- [ ] `SIGNAL_WEIGHTS` has 8 entries summing to exactly 1.0
- [ ] Module-level assertion still passes (verified at import time)
- [ ] `compute_routing_score()` signature accepts `price_impact_score: float = 0.0`
- [ ] `feature_scores` dict has 8 keys including `price_impact`
- [ ] All existing routing tests pass (no regression)
- [ ] 7 new tests pass

##### T-A-4-02: Wire price_impact into article consumer pipeline

**Type**: impl
**depends_on**: [T-A-4-01, T-A-2-02]
**blocks**: [T-A-5-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`

**PRD reference**: §6.7 (Routing Score Integration)

**What to build**: Update the article consumer's Block 5 call to query `article_price_impacts` for the doc_id and pass the result as `price_impact_score`. Since labels are only available for articles > 25h old, newly ingested articles will always get 0.0 (correct per PRD §6.7 Note).

**Entities / Components**:
- **Name**: Article consumer Block 5 integration
  - **Purpose**: Pass real-time price_impact signal to routing score computation
  - **Key attributes**: `price_impact_score: float` — fetched from `article_price_impacts` or 0.0 if not found
  - **Invariants**: Must not hold DB session across external I/O (R24). The lookup is a local DB call (fast, safe).

**Logic & Behavior**:
1. After Block 4 (NER), before calling `compute_routing_score()`, call `impact_repo.get_max_impact_for_doc(doc_id)`
2. Cast `Decimal` result to `float` for the routing score
3. Pass `price_impact_score=float(max_impact)` to `compute_routing_score()`
4. The `impact_repo` is injected via the consumer's session factory (same `nlp_db` session as the rest of the pipeline)
5. On any exception querying `article_price_impacts`: log warning, default to 0.0 (best-effort)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_consumer_uses_price_impact_zero_when_no_label` | Consumer with no `article_price_impacts` row → `price_impact_signal=0.0` in routing decision | unit |
| `test_consumer_uses_max_price_impact_across_entities` | Consumer with two labels (0.3 and 0.7) → `price_impact_signal=0.7` | unit |

**Acceptance criteria**:
- [ ] Article consumer passes `price_impact_score` to `compute_routing_score()`
- [ ] Consumer falls back to 0.0 on `PriceImpactRepository` error
- [ ] 2 unit tests pass

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` — current implementation
- `services/nlp-pipeline/tests/unit/application/blocks/test_routing.py` — existing tests (do not delete)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` — consumer pipeline

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/application/blocks/test_routing.py tests/unit/infrastructure/test_consumer.py -v -m unit
python -m ruff check src/
python -m mypy src/ --config-file mypy.ini
# Verify module-level assertion passes at import time
python -c "from nlp_pipeline.application.blocks.routing import SIGNAL_WEIGHTS; print(sum(SIGNAL_WEIGHTS.values()))"
```

#### Regression Guardrails
- **R19**: Do NOT delete any existing routing tests — update the `test_seven_signals` test to `test_eight_signals`, do not remove it
- **BP-038**: The module-level `assert sum(...) == 1.0` uses `assert` — this is acceptable for a startup invariant (not runtime error handling); the test suite also validates it explicitly

---

### Wave A-5: API Signals Endpoint Update

**Goal**: Add `market_impact_score` to `GET /api/v1/signals` response and support `min_impact_score` / `order_by` query params.
**Depends on**: T-A-3-01 (Avro schema must be updated), T-A-4-01 (Block 5 must emit market_impact_score)
**Estimated effort**: 0.5 wave (Low complexity)
**Architecture layer**: API + Application

#### Tasks

##### T-A-5-01: Add `market_impact_score` to signals API

**Type**: impl
**depends_on**: [T-A-3-01, T-A-4-01, T-A-2-02]
**blocks**: [T-A-6-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` — update `SignalResponse`
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/signals.py` — update `SignalData` + `ListSignalsUseCase`
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` — update `SignalsQueryPort.list_signal_events` signature
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/signals_query.py` — update `SqlaSignalsQueryRepo`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py` — update `list_signals` handler
- `services/nlp-pipeline/src/nlp_pipeline/config.py` — add 3 new settings

**PRD reference**: §6.2 (API Changes), §12 (Config)

**What to build**: Extend the signals API to return `market_impact_score` on each signal. Add optional `min_impact_score` (filter) and `order_by` (sort) query params. Add 3 new config settings for the labelling worker. Update `SignalData`, `SignalResponse`, `ListSignalsUseCase`, and `SqlaSignalsQueryRepo` accordingly. The `market_impact_score` must be read from `article_price_impacts` table (JOIN on `doc_id = article_id`).

**Entities / Components**:
- **Name**: `SignalData` (application layer DTO update)
  - **Purpose**: Carry `market_impact_score` to the API layer
  - **Key attributes**: Add `market_impact_score: float = 0.0`

- **Name**: `SignalResponse` (Pydantic schema update)
  - **Purpose**: Expose `market_impact_score` in REST response
  - **Key attributes**: Add `market_impact_score: float = Field(default=0.0, ge=0.0, le=1.0)`

- **Name**: `ListSignalsUseCase` update
  - **Purpose**: Pass `min_impact_score` and `order_by` to repo; map `market_impact_score` from rows
  - **Key methods**: Update `execute()` signature: `min_impact_score: float = 0.0`, `order_by: str = "created_at"`

- **Name**: `SignalsQueryPort.list_signal_events` update
  - **Purpose**: Accept `min_impact_score` and `order_by` filters
  - **Key methods**: `list_signal_events(limit, offset, doc_id, min_impact_score=0.0, order_by="created_at")`

- **Name**: `SqlaSignalsQueryRepo.list_signal_events` update
  - **Purpose**: JOIN `outbox_events` with `article_price_impacts` (via `partition_key` = doc_id = `article_id`) to fetch `impact_score`
  - **Logic**: `LEFT JOIN article_price_impacts ON article_price_impacts.article_id = outbox_events.partition_key::uuid`. Filter `WHERE impact_score >= min_impact_score OR impact_score IS NULL` when min_impact_score > 0. Order by `impact_score DESC` when `order_by == "market_impact_score"`, else `created_at DESC`.

- **Name**: New Settings fields
  - `impact_normalisation_cap_pct: float = 5.0` — denominator for impact_score formula
  - `price_impact_cycle_seconds: int = 14400` — worker sleep between cycles (4h)
  - `price_impact_min_age_hours: int = 25` — minimum article age before labelling
  - `market_data_internal_url: str = "http://market-data:8003"` — S3 OHLCV API base URL

**Logic & Behavior**:
1. `SqlaSignalsQueryRepo.list_signal_events()`:
   a. Build LEFT JOIN: `outbox_events` JOIN `article_price_impacts` ON `article_price_impacts.article_id = CAST(outbox_events.partition_key AS UUID)`
   b. Select `impact_score` alongside existing columns; coalesce NULL to 0.0
   c. Apply `WHERE coalesce(impact_score, 0) >= :min_impact_score` when `min_impact_score > 0`
   d. Apply `ORDER BY impact_score DESC NULLS LAST` when `order_by == "market_impact_score"`, else `ORDER BY outbox_events.created_at DESC`
2. `list_signals` route: add query params `min_impact_score: float = Query(default=0.0, ge=0.0, le=1.0)` and `order_by: str = Query(default="created_at", pattern="^(created_at|market_impact_score)$")`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_signal_response_has_market_impact_score` | `SignalResponse` Pydantic model has `market_impact_score` field defaulting to 0.0 | unit |
| `test_list_signals_filter_by_min_impact` | `min_impact_score=0.5` excludes signals with lower scores | unit |
| `test_list_signals_order_by_impact_score` | `order_by=market_impact_score` returns signals sorted by impact DESC | unit |
| `test_signals_api_returns_market_impact_score` | Integration: `GET /api/v1/signals` response includes `market_impact_score` field | integration |
| `test_signals_api_min_impact_filter` | Integration: `?min_impact_score=0.5` filters correctly | integration |

**Acceptance criteria**:
- [ ] `SignalResponse` has `market_impact_score: float` field
- [ ] `GET /api/v1/signals` response includes `market_impact_score` (defaults to 0.0)
- [ ] `?min_impact_score=0.5` query param filters signals correctly
- [ ] `?order_by=market_impact_score` sorts by impact DESC
- [ ] 4 new config settings present in `Settings` (`impact_normalisation_cap_pct`, `price_impact_cycle_seconds`, `price_impact_min_age_hours`, `market_data_internal_url`)
- [ ] All unit + integration tests pass

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py` — current signals route
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` — current Pydantic schemas
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/signals.py` — current use case

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/api/ tests/unit/application/use_cases/test_signals.py -v -m unit
python -m ruff check src/
python -m mypy src/ --config-file mypy.ini
```

#### Regression Guardrails
- **R25**: API route must NOT import from `infrastructure/` — `list_signals` calls use case only; use case calls port only
- **R27**: `list_signal_events` is a read-only operation — `SignalsQueryRepoDep` uses `ReadUoWDep` (verify existing dep injection is read-only)
- **BP-043**: Do not use `Field(strip_whitespace=True)` (Pydantic V2 deprecated); use `Annotated[str, StringConstraints(...)]` if needed

---

### Wave A-6: Unit + Contract Tests + Docs

**Goal**: Complete test coverage for all new components. Update service docs and context file.
**Depends on**: All preceding waves (A-1 through A-5, B-1, B-2)
**Estimated effort**: 1 wave (Medium complexity)
**Architecture layer**: Tests + Documentation

#### Tasks

##### T-A-6-01: Contract tests for Avro schema evolution

**Type**: test
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/tests/contract/` (create directory if not exists)
- `services/nlp-pipeline/tests/contract/__init__.py`
- `services/nlp-pipeline/tests/contract/test_signal_schema_compat.py`

**PRD reference**: §11 (Contract Tests)

**What to build**: Contract tests that validate Avro backward/forward compatibility of `nlp.signal.detected.v1.avsc`. Test that old messages (without `market_impact_score`) deserialize correctly with the new schema (using the default value).

**Logic & Behavior**:
1. Load `nlp.signal.detected.v1.avsc` from `infra/kafka/schemas/`
2. Serialize a minimal message WITHOUT `market_impact_score` using old-style dict
3. Deserialize with new schema — verify `market_impact_score` is `0.0`
4. Serialize a message WITH `market_impact_score=0.75`
5. Deserialize and verify round-trip fidelity

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_signal_detected_v1_backward_compatible` | Old schema messages decode with default 0.0 | contract |
| `test_signal_detected_v1_new_field_defaults_to_zero` | `market_impact_score` default 0.0 when not present | contract |
| `test_signal_detected_v1_full_roundtrip` | Signal with `market_impact_score=0.75` round-trips | contract |

**Acceptance criteria**:
- [ ] 3 contract tests pass under `pytest -m contract`
- [ ] Tests use `fastavro` or `avro-python3` for schema validation (add to `pyproject.toml` if not present)

##### T-A-6-02: Documentation updates

**Type**: docs
**depends_on**: [T-A-5-01, T-B-2-01]
**blocks**: none
**Target files**:
- `docs/services/nlp-pipeline.md` — update API surface, Block 5 weights, new process
- `services/nlp-pipeline/.claude-context.md` — update routing weights table, new worker
- `docs/MASTER_PLAN.md` — update S6 mission description (now 8 signals; new `price_impact` worker)
- `services/nlp-pipeline/configs/dev.local.env.example` — add 4 new env vars

**PRD reference**: R3

**What to build**: Update all docs to reflect the 8-signal routing model, `market_impact_score` on the signals API, and `PriceImpactLabellingWorker` process.

**Logic & Behavior**:
1. `docs/services/nlp-pipeline.md`:
   - Update Block 5 weight table (8 signals)
   - Add `price_impact` to API Surface table (note: added to `GET /api/v1/signals` response)
   - Add `PriceImpactLabellingWorker` to process list
   - Add `article_price_impacts` to Database Schema section
2. `.claude-context.md`:
   - Update Routing Signal Weights table to 8 rows
   - Add `PriceImpactLabellingWorker` process
3. `configs/dev.local.env.example`:
   - `NLP_PIPELINE_IMPACT_NORMALISATION_CAP_PCT=5.0`
   - `NLP_PIPELINE_PRICE_IMPACT_CYCLE_SECONDS=14400`
   - `NLP_PIPELINE_PRICE_IMPACT_MIN_AGE_HOURS=25`
   - `NLP_PIPELINE_MARKET_DATA_INTERNAL_URL=http://market-data:8003`

**Acceptance criteria**:
- [ ] `docs/services/nlp-pipeline.md` updated with 8-signal table
- [ ] `.claude-context.md` routing weights updated
- [ ] `dev.local.env.example` has 4 new env vars
- [ ] `docs/MASTER_PLAN.md` S6 entry updated

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/ -v -m "unit or contract" --tb=short
python -m ruff check src/ tests/
python -m mypy src/ --config-file mypy.ini
```

#### Regression Guardrails
- **R3**: Every API/event/schema/config change requires doc update — enforced here
- **R19**: Must not delete any existing tests; all 293+ existing unit tests must still pass

---

## Sub-Plan B: `PriceImpactLabellingWorker`

**Scope**: New background process that retroactively labels articles with price-impact scores.
**Service**: `services/nlp-pipeline/`
**Entry point**: `python -m nlp_pipeline.workers.price_impact_labelling_worker`

---

### Wave B-1: `PriceImpactLabellingWorker` Implementation

**Goal**: Implement the worker that queries unlabelled articles, calls S3 OHLCV API, and writes `article_price_impacts` rows.
**Depends on**: T-A-2-01 (domain entity), T-A-2-02 (repository port)
**Estimated effort**: 1.5 waves (Medium complexity)
**Architecture layer**: Infrastructure — Workers

#### Tasks

##### T-B-1-01: S3 OHLCV HTTP client

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-B-1-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py` — new file

**PRD reference**: §6.5 (PriceImpactLabellingWorker — dependencies)

**What to build**: An async HTTP client that calls the Market Data service (S3) `GET /api/v1/market-data/ohlcv/{symbol}?date={date}` endpoint to fetch daily OHLCV bars. Uses `httpx.AsyncClient`. Returns a typed `OHLCVBar` dataclass or `None` on 404/error.

**Entities / Components**:
- **Name**: `OHLCVBar`
  - **Purpose**: Typed response from S3 OHLCV endpoint
  - **Key attributes**:
    - `symbol: str`
    - `date: date` — Python date
    - `open: Decimal`
    - `close: Decimal`
    - `high: Decimal`
    - `low: Decimal`
    - `volume: int | None`

- **Name**: `MarketDataClient`
  - **Purpose**: HTTP adapter to call S3 Market Data OHLCV API
  - **Key attributes**: `_client: httpx.AsyncClient`, `_base_url: str`
  - **Key methods**:
    - `async def get_ohlcv(self, symbol: str, date: date) -> OHLCVBar | None` — returns None on 404 or HTTP error
  - **Invariants**: Does NOT hold DB sessions (R24). Logs warning on HTTP error. Raises nothing — caller handles None.

**Logic & Behavior**:
1. `GET {base_url}/api/v1/market-data/ohlcv/{symbol}?date={date.isoformat()}`
2. On 200: parse JSON response into `OHLCVBar`; validate `open > 0` and `close > 0`
3. On 404: return `None` (symbol/date not found — normal)
4. On any `httpx.RequestError` or non-200/404 status: log warning with `symbol`, `date`, `status_code`; return `None`
5. Timeout: 10 seconds per request
6. SSRF protection: `base_url` comes from config (`NLP_PIPELINE_MARKET_DATA_INTERNAL_URL`) — internal service URL, not user-supplied (no SSRF risk per PRD §8)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_market_data_client_parses_ohlcv` | `get_ohlcv()` with 200 JSON response → `OHLCVBar` populated | unit (httpx mock) |
| `test_market_data_client_returns_none_on_404` | `get_ohlcv()` with 404 → `None`, no exception | unit (httpx mock) |
| `test_market_data_client_returns_none_on_timeout` | `get_ohlcv()` with `RequestTimeout` → `None`, warning logged | unit (httpx mock) |

**Acceptance criteria**:
- [ ] `MarketDataClient` in `infrastructure/http/market_data_client.py`
- [ ] Returns `OHLCVBar | None` (no exceptions propagated)
- [ ] 3 unit tests pass (use `respx` or `httpx` mock transport)

##### T-B-1-02: `PriceImpactLabellingWorker` class

**Type**: impl
**depends_on**: [T-B-1-01, T-A-2-02]
**blocks**: [T-B-2-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py` — new file

**PRD reference**: §6.5 (PriceImpactLabellingWorker process lifecycle)

**What to build**: Async worker class `PriceImpactLabellingWorker` that periodically queries unlabelled articles, fetches OHLCV data via `MarketDataClient`, computes `ArticlePriceImpact` labels, and inserts them into `article_price_impacts`. Follows the same structural pattern as `EmbeddingRetryWorker`. Independent process per R22.

**Entities / Components**:
- **Name**: `PriceImpactLabellingWorker`
  - **Purpose**: Background process that retroactively labels articles with price-impact scores
  - **Key attributes**:
    - `_nlp_session_factory: async_sessionmaker[AsyncSession]`
    - `_market_data_client: MarketDataClient`
    - `_normalisation_cap_pct: float = 5.0`
    - `_cycle_seconds: int = 14400`
    - `_min_age_hours: int = 25`
    - `_batch_size: int = 100`
  - **Key methods**:
    - `async def run_once(self) -> int` — run one labelling cycle; returns count of labels created
    - `async def run_forever(self, stop: asyncio.Event) -> None` — main loop; calls `run_once()` then sleeps `_cycle_seconds`
  - **Invariants**:
    - Must NOT hold DB session across HTTP calls to MarketDataClient (R24) — read, release session, call HTTP, acquire new session to write
    - Must NOT fail the entire batch on a single article error — skip and continue
    - Must be idempotent — `PriceImpactRepository.upsert()` uses `ON CONFLICT DO NOTHING`

**Logic & Behavior**:
1. `labelling_cycle()` (called by `run_once()`):
   a. Open `nlp_sf()` session → call `impact_repo.get_unlabelled_articles(min_age_hours, batch_size)` → returns `[(doc_id, [entity_id_1, ...])]`
   b. Close session (R24 — release before HTTP calls)
   c. For each `(doc_id, entity_ids)`:
      i. For each `entity_id`, query `entity_mentions` to get `symbol` (look up `mention_text` for `financial_instrument` class mentions; or use `canonical_entities.ticker` if available). **Approach**: join `entity_mentions` + `document_source_metadata` to get `published_at`. Call `market_data_client.get_ohlcv(symbol, published_at.date())`.
      ii. If `get_ohlcv()` returns `None` → create `ArticlePriceImpact.zero(...)` with `impact_score=0.0` (marks article as processed, no data)
      iii. If `get_ohlcv()` returns bar → create `ArticlePriceImpact.compute(...)` with real prices
      iv. Collect max-impact `ArticlePriceImpact` across all entities for this doc
   d. Open new `nlp_sf()` session → `impact_repo.upsert(label)` for each → `await session.commit()` → close session
   e. `asyncio.sleep(0.1)` between batches (throttle, per PRD §9 failure mode table)
2. `run_forever()`:
   a. Call `run_once()` immediately on startup
   b. `await asyncio.sleep(_cycle_seconds)` or `stop.wait()`, whichever comes first
   c. Loop until `stop.is_set()`
3. Error handling:
   - Per-article error: log `warning`, skip article, increment error counter
   - DB unavailable: `run_once()` raises, caller (`run_forever`) logs and retries next cycle

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_labelling_worker_skips_young_articles` | Articles published < 25h ago not included in query | unit (mock repo) |
| `test_labelling_worker_creates_zero_impact_on_missing_ohlcv` | `get_ohlcv()` returns `None` → `ArticlePriceImpact.zero()` upserted | unit (mock client + repo) |
| `test_labelling_worker_computes_impact_from_ohlcv` | Valid OHLCV bar → `ArticlePriceImpact.compute()` with correct `impact_score` | unit |
| `test_labelling_worker_idempotent` | Running twice on same articles → `upsert()` called with same data, no duplicate rows | unit |
| `test_labelling_worker_uses_max_impact_across_entities` | Doc with 2 entities (scores 0.3, 0.7) → upserts row with `impact_score=0.7` | unit |
| `test_labelling_worker_skips_article_on_http_error` | `get_ohlcv()` raises → article skipped, cycle continues | unit |
| `test_labelling_worker_run_forever_stops_on_event` | `stop.set()` causes `run_forever()` to exit cleanly | unit |
| `test_labelling_worker_e2e` | Integration: real DB + wiremock (S3 OHLCV mock) → worker inserts `article_price_impacts` rows | integration |
| `test_labelling_worker_handles_missing_ohlcv_integration` | Integration: S3 returns 404 → row with `impact_score=0.0` inserted | integration |

**Acceptance criteria**:
- [ ] `PriceImpactLabellingWorker` follows `EmbeddingRetryWorker` structure pattern
- [ ] DB session released before HTTP calls (R24 compliance)
- [ ] `ON CONFLICT DO NOTHING` idempotency (R9)
- [ ] 7 unit tests + 2 integration tests pass
- [ ] `asyncio.sleep(0.1)` throttle between batches

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/embedding_retry_worker.py` — structural pattern to follow
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/price_impact.py` — repository interface (T-A-2-02)

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/infrastructure/ -k "price_impact or labelling" -v -m unit
python -m ruff check src/infrastructure/workers/price_impact_labelling_worker.py
python -m mypy src/infrastructure/workers/price_impact_labelling_worker.py --config-file mypy.ini
```

#### Regression Guardrails
- **R24**: Session must NOT be held during `get_ohlcv()` HTTP calls — split read/release/I/O/acquire/write
- **R9**: Upsert must use `ON CONFLICT DO NOTHING` — verify `PriceImpactRepository.upsert()` implementation
- **BP-057**: Same as R24 — explicit pattern to follow from `EmbeddingRetryWorker`

---

### Wave B-2: Worker Entry Point + Docker Compose

**Goal**: Create the standalone process entry point and register it in Docker Compose.
**Depends on**: T-B-1-02 (worker class must exist)
**Estimated effort**: 0.25 wave (Low complexity)
**Architecture layer**: Infrastructure — Process Architecture

#### Tasks

##### T-B-2-01: Entry point + Docker Compose service

**Type**: config
**depends_on**: [T-B-1-02]
**blocks**: [T-A-6-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/workers/__init__.py` — create (empty)
- `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` — entry point (not same as infrastructure worker class)
- `infra/compose/docker-compose.yml` — add `nlp-pipeline-price-impact-worker` service

**PRD reference**: §6.5 (process lifecycle), R22

**What to build**: A standalone entry point `nlp_pipeline/workers/price_impact_labelling_worker.py` with SIGINT/SIGTERM handling, logging configuration, and the async main loop. Register in Docker Compose as a new service using the same S6 image with a different `command`.

**NOTE**: Distinction between:
- Infrastructure worker class: `nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py` (T-B-1-02)
- Entry point module: `nlp_pipeline/workers/price_impact_labelling_worker.py` (this task) — run via `python -m nlp_pipeline.workers.price_impact_labelling_worker`

**Entities / Components**:
- **Name**: `nlp_pipeline/workers/price_impact_labelling_worker.py`
  - **Purpose**: Process entry point — configures logging, wires dependencies, starts worker loop
  - **Key attributes**:
    - SIGINT/SIGTERM handler sets `asyncio.Event()`
    - Uses `Settings` from `config.py`
    - Wires `MarketDataClient` with `httpx.AsyncClient`
    - Wires `nlp_session_factory` from `_build_nlp_factories(settings)`
    - Calls `PriceImpactLabellingWorker.run_forever(stop_event)`
  - **Invariants**: Must exit with code 0 on clean shutdown, code 1 on startup failure (DB unavailable)

- **Name**: `nlp-pipeline-price-impact-worker` Docker Compose service
  - **Purpose**: Run the price impact worker as an independent process
  - **Key attributes**:
    - Same image as `nlp-pipeline`
    - `command: python -m nlp_pipeline.workers.price_impact_labelling_worker`
    - `depends_on: [nlp-pipeline-migrate, kafka-init]`
    - `profiles: [infra, all]`
    - No healthcheck (background worker pattern — same as other S6 workers)
    - Env file: `../../services/nlp-pipeline/configs/docker.env`

**Logic & Behavior**:
1. `async def main()`:
   a. `configure_logging(...)` first
   b. `settings = Settings()`
   c. `engine, nlp_sf, _ = _build_nlp_factories(settings)` — write session factory only
   d. `async with httpx.AsyncClient(timeout=10.0) as http_client:`
   e. `market_client = MarketDataClient(http_client, settings.market_data_internal_url)`
   f. `worker = PriceImpactLabellingWorker(nlp_sf, market_client, ...settings...)`
   g. Setup SIGINT/SIGTERM → `stop.set()`
   h. `await worker.run_forever(stop)`
2. `if __name__ == "__main__": asyncio.run(main())`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_entrypoint_importable` | `from nlp_pipeline.workers.price_impact_labelling_worker import main` imports without error | unit |

**Acceptance criteria**:
- [ ] `python -m nlp_pipeline.workers.price_impact_labelling_worker --help` does not crash
- [ ] `nlp-pipeline-price-impact-worker` service in `docker-compose.yml` under `[infra, all]` profile
- [ ] Entry point test passes
- [ ] No healthcheck on this service (background worker pattern)

#### Pre-read
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer_main.py` — SIGINT/SIGTERM pattern
- `infra/compose/docker-compose.yml` lines 850–950 — existing S6 services as template

#### Validation Gate
```bash
cd services/nlp-pipeline
python -m pytest tests/unit/test_entrypoints.py -v -m unit
python -m ruff check src/nlp_pipeline/workers/
python -m mypy src/nlp_pipeline/workers/ --config-file mypy.ini
```

#### Regression Guardrails
- **R22**: Must be a standalone process — no background threads/tasks spawned in the API lifespan
- **BP-010**: No healthcheck on background worker containers in Docker Compose — `--wait` flag must not be used with this service

---

## Cross-Cutting Concerns

### Security

| Concern | Mitigation | Rule |
|---------|-----------|------|
| `market_data_internal_url` config | Internal URL from env var only; no user-supplied URLs → no SSRF | R13, R15 |
| SQL injection via `symbol` in OHLCV URL | Symbol comes from `entity_mentions.mention_text` (internal trusted data), not user input | R15 |
| No secrets in new code | `impact_normalisation_cap_pct`, cycle seconds, etc. are operational config, not secrets | R13 |

### Observability

The following Prometheus metrics must be added to `services/nlp-pipeline/src/nlp_pipeline/infrastructure/metrics/prometheus.py`:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s6_price_impact_labels_computed_total` | Counter | `status={success,no_ohlcv,error}` | Labels computed per cycle |
| `s6_price_impact_cycle_duration_seconds` | Histogram | — | Time per 4h labelling cycle |
| `s6_routing_score_price_impact_histogram` | Histogram | — | Distribution of price_impact signal values |

Log fields (structlog):
- Worker: `service=nlp-pipeline`, `worker=price_impact_labelling`, `article_id`, `entity_id`, `impact_score`
- Block 5: `price_impact_signal`, `price_impact_source={label,no_data}`

### Forward-Compatibility Notes

The `market_impact_score` field in `nlp.signal.detected.v1.avsc` with `"default": 0.0` ensures:
- PLAN-0021 (Flash Alerts) consumers that read `nlp.signal.detected.v1` and do not yet read `market_impact_score` continue to work — the field defaults to 0.0 on deserialization.
- PLAN-0021 can optionally consume `market_impact_score` when it becomes available for alert severity scoring.

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| S3 OHLCV API shape differs from expected | Low | Medium | Read S3 route code before implementing `MarketDataClient`; add test with real response shape |
| `document_source_metadata` table missing `published_at` for some articles | Low | Low | `get_unlabelled_articles()` handles NULL `published_at` — skip those articles (can't compute age) |
| Block 5 routing score shift causes unexpected tier changes | Low | Medium | Keep `price_impact_score=0.0` default — only articles with labels (>25h old) are affected; tier thresholds unchanged |
| Alembic migration `0005` conflicts if migration chain was modified | Low | Low | Verify `down_revision='0004'` matches current head before implementing |
| Partial index `WHERE impact_score > 0.3` not honored by `SqlaSignalsQueryRepo` sort | Low | Low | Planner will use the standard `(entity_id, ohlcv_date)` index for the JOIN; partial index is for high-score ranking queries only |

---

## Wave Execution Order Summary

| Wave | Description | Depends On | Parallelizable With |
|------|-------------|-----------|---------------------|
| A-1 | DB migration `article_price_impacts` | none | — |
| A-2 | Domain entity + ORM + port | A-1 | — |
| A-3 | Avro schema `nlp.signal.detected.v1` | A-2 | B-1 |
| B-1 | `PriceImpactLabellingWorker` | A-2 | A-3 |
| A-4 | Block 5 weight rebalance | A-2 | B-1, B-2 |
| B-2 | Worker entry point + Docker Compose | B-1 | A-4, A-5 |
| A-5 | API signals endpoint update | A-3, A-4 | B-2 |
| A-6 | Tests + docs | A-5, B-2 | — |

**Recommended execution sequence**:
1. A-1 (migration)
2. A-2 (domain + ORM)
3. A-3 + B-1 in parallel
4. A-4 + B-2 in parallel
5. A-5
6. A-6

---

## Task Status

| Task ID | Title | Status | Wave |
|---------|-------|--------|------|
| T-A-1-01 | Alembic migration `article_price_impacts` | pending | A-1 |
| T-A-2-01 | `ArticlePriceImpact` domain entity | pending | A-2 |
| T-A-2-02 | ORM model + repository port | pending | A-2 |
| T-A-3-01 | Update Avro schema `nlp.signal.detected.v1` | pending | A-3 |
| T-A-4-01 | Block 5 weight rebalance + `price_impact` signal | pending | A-4 |
| T-A-4-02 | Wire price_impact into article consumer | pending | A-4 |
| T-B-1-01 | S3 OHLCV HTTP client | pending | B-1 |
| T-B-1-02 | `PriceImpactLabellingWorker` class | pending | B-1 |
| T-B-2-01 | Entry point + Docker Compose | pending | B-2 |
| T-A-5-01 | API signals endpoint update | pending | A-5 |
| T-A-6-01 | Contract tests — Avro schema evolution | pending | A-6 |
| T-A-6-02 | Documentation updates | pending | A-6 |
