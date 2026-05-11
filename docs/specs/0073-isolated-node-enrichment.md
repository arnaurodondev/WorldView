# PRD-0073 — Isolated Node Enrichment

> **Version**: 1.0 | **Date**: 2026-05-05
> **Status**: Draft | **Owner**: Arnau Rodon
> **Affected Services**: S7 (knowledge-graph), S3 (market-data, API extension), intelligence-migrations, S9 (api-gateway), worldview-web

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Target Users](#2-target-users)
3. [Requirements](#3-requirements)
4. [Out of Scope](#4-out-of-scope)
5. [Affected Services](#5-affected-services)
6. [API Changes](#6-api-changes)
7. [Kafka Events](#7-kafka-events)
8. [Database Changes](#8-database-changes)
9. [Domain Model Changes](#9-domain-model-changes)
10. [Data Flow](#10-data-flow)
11. [Architecture Decisions](#11-architecture-decisions)
12. [Security Analysis](#12-security-analysis)
13. [Failure Modes](#13-failure-modes)
14. [Scalability](#14-scalability)
15. [Test Strategy](#15-test-strategy)
16. [Migration Plan](#16-migration-plan)
17. [Observability](#17-observability)
18. [Open Questions](#18-open-questions)
19. [Estimation](#19-estimation)

---

## 1. Problem Statement

Approximately 68% of canonical entities in `intelligence_db` are **isolated nodes**: they were created by the NLP extraction pipeline (S6 Block 13E, via `entity.canonical.created.v1`) but received no structured enrichment. When a company like "Apple Inc." is created as a canonical entity it has:

- No description
- No sector, industry, or country metadata
- No exchange, ISIN, or ticker embedded in the `canonical_entities` row
- No relation-type edges derived from structured data (e.g., `OPERATES_IN_SECTOR`)

These gaps propagate downstream:

- **Graph UI** is uninformative — entity cards show only a name and type.
- **RAG retrieval** misses sector-filtered and metadata-enriched queries.
- **Screener** cannot filter by sector, country, or exchange when those fields are absent.
- **Similar-entity search** degrades because the `fundamentals_ohlcv` HNSW embedding is built from descriptions that do not exist.

The root cause is architectural: `canonical_entities` was designed as a lookup table (name + type only), and all enrichment was left to ad-hoc workers that only fire for `financial_instrument` entities with a known EODHD ticker. Person, concept, location, and event entities are never enriched at all.

### Success Criteria

| Metric | Baseline | Target |
|--------|----------|--------|
| Isolated node rate | ~68% | < 20% within 72 h of first periodic sweep |
| `data_completeness` ≥ 0.5 (financial_instrument) | ~5% | > 70% |
| `data_completeness` ≥ 0.5 (person) | ~0% | > 60% |
| Entity graph cards with description | ~10% | > 75% |
| Daily enrichment failure rate | — | < 5% of attempted entities |

---

## 2. Target Users

| User | Benefit |
|------|---------|
| **Finance analyst (primary)** | Entity graph and intelligence tab show real company descriptions, sector, and country metadata instead of empty cards |
| **Platform operator** | Operational visibility via `data_completeness` score; enrichment failure counter enables triage without full DB inspection |
| **RAG/Chat pipeline (internal)** | More grounded entity context improves graph-enriched chat responses (S8 retrieval step 8.0) |

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-01 | A new Worker 13J (`StructuredEnrichmentWorker`) MUST enrich canonical entities using a three-source cascade: S3 existing data lookup → S3 on-demand EODHD profile → LLM generation |
| FR-02 | Worker 13J MUST be triggered hot-path for `financial_instrument` and `company` entity types upon receiving an `entity.canonical.created.v1` Kafka event |
| FR-03 | Worker 13J MUST run a daily periodic sweep (02:00 UTC) over all entities WHERE `enriched_at IS NULL OR data_completeness < 0.5` AND `enrichment_attempts < 3` |
| FR-04 | Hot-path enrichment MUST skip entity types other than `financial_instrument` and `company`; those types are covered only by the periodic sweep |
| FR-05 | `data_completeness` MUST be computed at write-time using a per-type formula (see §9) and stored on the `canonical_entities` row |
| FR-06 | After enrichment, Worker 13J MUST seed relations from `relation_type_registry` rows whose `data_source` matches the current enrichment source and `source_field` is present in the response payload |
| FR-07 | `enrichment_attempts` MUST be incremented on non-retryable failure. Retryable errors (HTTP 429, 503) MUST NOT count against the attempt counter |
| FR-08 | After 3 failed attempts an entity MUST be skipped permanently until `enrichment_attempts` is manually reset |
| FR-09 | The LLM enrichment step MUST generate descriptions for all entity types: financial instruments, companies, persons (biography), concepts (definition), locations, events |
| FR-10 | `GET /api/v1/entities/{entity_id}` MUST return the new `description`, `metadata`, `data_completeness`, and `enriched_at` fields |
| FR-11 | The intelligence tab in the frontend MUST display the entity description/narrative panel when `description` is non-null |

### 3.2 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | Hot-path enrichment MUST complete within 30 s of receiving `entity.canonical.created.v1` (p95, single entity) |
| NFR-02 | LLM calls MUST be guarded by `asyncio.wait_for` with a 25 s timeout to prevent blocking the consumer |
| NFR-03 | Periodic sweep MUST process entities in batches of 50 to avoid holding long-running DB sessions |
| NFR-04 | The periodic sweep MUST be idempotent — re-running it on already-enriched entities MUST be a no-op |
| NFR-05 | All external HTTP calls (market-data REST, DeepInfra) MUST use `httpx.AsyncClient` with `httpx.Timeout` set (never rely on defaults) |
| NFR-06 | The `ENRICHMENT_LLM_MODEL_ID` env var MUST be read via pydantic-settings; no hardcoded model IDs in application code |

---

## 4. Out of Scope

- **Embedding refresh**: after enrichment, the entity's description embedding (`definition` view in `entity_embedding_state`) is updated by the existing `EmbeddingRetryWorker` / `entity.dirtied.v1` signal — Worker 13J MUST produce `entity.dirtied.v1` after a successful write, but does not own the embedding step itself
- **Financial statements enrichment**: income statement, balance sheet, and earnings data are handled by `FundamentalsRefreshWorker` (Worker 13D-5) and are not duplicated here
- **Relation evidence from articles**: `relation_evidence_raw` population is owned by the existing Block 11/12 hot path; Worker 13J only seeds structural relations from `relation_type_registry` mappings
- **Frontend Settings page changes**: no new settings surface is added
- **Community detection re-trigger**: `CommunityDetectionWorker` (PRD-0023) is not re-triggered by enrichment; community membership updates on its own schedule
- **Backfill orchestration UI**: no admin endpoint to manually trigger enrichment for specific entities (manual reset of `enrichment_attempts` is done directly in the DB by operators)
- **Multi-tenant isolation in intelligence_db**: `canonical_entities` is a platform-wide shared table; per-tenant enrichment policy is out of scope for this PRD

---

## 5. Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S7 knowledge-graph** | Feature addition | Worker 13J (`StructuredEnrichmentWorker`), new consumer entrypoint wired to `entity.canonical.created.v1`, APScheduler job slot 10J, Prometheus metrics |
| **S3 market-data** | API refactor + extension | Replaces the two existing single-item lookup endpoints (`GET /instruments/symbol/{symbol}` and `GET /instruments/{instrument_id}`) with a single unified `GET /api/v1/instruments/lookup` endpoint (query params: `symbol`, `isin`, `id`; optional `extra_info=true` flag for enrichment fields). Adds internal `GET /api/v1/instruments/on-demand-profile` (EODHD on-demand, internal JWT, persists to DB). Also adds `description TEXT NULL` to the `securities` table via a market-data Alembic migration. S3 becomes the unified structured data gateway. |
| **intelligence-migrations** | DDL owner | Migrations **0024–0027** (shifted from 0020–0023 — those are now occupied by PLAN-0072): `canonical_entities` column additions, `relation_type_registry` column additions, `relations` column addition, EODHD relation-type seed data |
| **S9 api-gateway** | Response schema extension | `EntityPublic` gains 4 new nullable fields; existing proxy route `GET /api/v1/entities/{entity_id}` inherits them |
| **worldview-web** | UI feature | Intelligence tab entity detail panel gains description + metadata display when `description` is non-null |

---

## 6. API Changes

### 6.1 `GET /api/v1/entities/{entity_id}` — Extended Response

**Route**: New route added to both S7 and S9. S9 proxies to S7 `GET /api/v1/entities/{entity_id}`.

**No request changes.**

**Response schema additions** (all nullable, backward-compatible):

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `description` | `string` | yes | LLM-generated or EODHD-sourced description of the entity |
| `metadata` | `object` | yes | Structured key-value bag (see schema below) |
| `data_completeness` | `number` | yes | 0.0–1.0 completeness score, `null` until first enrichment attempt completes |
| `enriched_at` | `string (ISO-8601 UTC)` | yes | Timestamp of last successful enrichment; `null` if never enriched |

**`metadata` object schema** (all fields optional within the object):

```json
{
  "sector": "string | null",
  "industry": "string | null",
  "country": "string | null",
  "exchange": "string | null",
  "isin": "string | null",
  "ticker": "string | null",
  "currency_code": "string | null",
  "employee_count": "integer | null",
  "founded_year": "integer | null",
  "headquarters_city": "string | null",
  "headquarters_country": "string | null",
  "role": "string | null",
  "organization": "string | null",
  "nationality": "string | null",
  "category": "string | null",
  "macro_indicators": "object | null"
}
```

**Example response delta** (only new fields shown):

```json
{
  "entity_id": "01936a1b-...",
  "canonical_name": "Apple Inc.",
  "entity_type": "financial_instrument",
  "description": "Apple Inc. designs, manufactures, and markets consumer electronics, computer software, and online services worldwide. The company's flagship products include the iPhone, Mac, iPad, Apple Watch, and Apple TV, complemented by a growing Services segment encompassing the App Store, Apple Music, iCloud, and Apple Pay.",
  "metadata": {
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "country": "USA",
    "exchange": "NASDAQ",
    "isin": "US0378331005",
    "ticker": "AAPL",
    "employee_count": 164000,
    "founded_year": 1976,
    "headquarters_city": "Cupertino",
    "headquarters_country": "United States"
  },
  "data_completeness": 0.9,
  "enriched_at": "2026-05-05T02:14:32Z"
}
```

### 6.2 S7 Internal Endpoint: `GET /api/v1/entities/{entity_id}` (S7-side)

S7's existing entity endpoint is extended with the same fields. The `CanonicalEntityRepository.get_by_id()` query is updated to SELECT the four new columns.

### 6.3 S3 Endpoint Changes (API refactor + extension)

#### Refactored: GET /api/v1/instruments/lookup

**Replaces** the two existing single-item lookup endpoints (`GET /instruments/symbol/{symbol}` and `GET /instruments/{instrument_id}`). S9 proxy routes and frontend callers are updated accordingly. The existing `GET /instruments` (list/search) is unchanged.

- **Auth**: Bearer JWT (public-facing via S9)
- **Query params**:
  | Param | Type | Required | Notes |
  |-------|------|----------|-------|
  | symbol | string | no | Case-insensitive ticker, 1–20 chars, `^[A-Za-z0-9.\-]+$` |
  | isin | string | no | 12-char ISIN format `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` |
  | id | UUID | no | `instrument_id` primary key |
  | extra_info | bool | no | Default `false`. When `true`, adds enrichment fields to response |

  At least one of `symbol`, `isin`, `id` required. If multiple provided, priority: `id > isin > symbol` (lower-priority params ignored).
- **Response (200)** without `extra_info`:
  | Field | Type | Nullable |
  |-------|------|----------|
  | id | UUID | no |
  | symbol | string | no |
  | exchange | string | no |
  | is_active | bool | no |
- **Response (200)** with `extra_info=true` adds:
  | Field | Type | Nullable | Notes |
  |-------|------|----------|-------|
  | name | string | yes | Company/security name |
  | isin | string | yes | |
  | sector | string | yes | |
  | industry | string | yes | |
  | country | string | yes | |
  | currency_code | string | yes | |
  | description | string | yes | From `securities.description` column (null until EODHD on-demand profile is called) |
- **Response (404)**: `{"detail": "Instrument not found"}` — not yet ingested in S3
- **Error responses**: 400 (no identifier param provided), 422 (invalid format)

#### Internal: GET /api/v1/instruments/on-demand-profile

DB-first lookup; if `description` (or other enrichment fields) missing, fetches from EODHD in real time and **persists the result** to `securities`/`instruments` tables. Internal-only — not proxied through S9.

- **Auth**: X-Internal-JWT (system JWT, internal services only)
- **Query params**:
  | Param | Type | Required | Notes |
  |-------|------|----------|-------|
  | ticker | string | no | Uppercase, validated: `^[A-Z0-9.\-]{1,20}$` (server-side enforcement) |
  | isin | string | no | 12-char ISIN format |

  At least one param required.
- **Response (200)**:
  | Field | Type | Nullable | Notes |
  |-------|------|----------|-------|
  | description | string | yes | From `securities.description` (DB) or EODHD `General.Description` |
  | sector | string | yes | |
  | industry | string | yes | |
  | country | string | yes | |
  | exchange | string | yes | |
  | isin | string | yes | |
  | ticker | string | yes | |
  | currency_code | string | yes | |
  | source | string | no | `"db"` or `"eodhd_persisted"` — `"eodhd_persisted"` means EODHD was called and result saved |
- **Persistence behaviour**: When EODHD is called and returns data, the result is upserted into `securities` (description, sector, industry, country, currency) and `instruments` (isin, exchange) so that subsequent `GET /instruments/lookup?extra_info=true` returns `description` from DB instead of repeating the EODHD call.
- **Response (404)**: `{"detail": "No profile found for this ticker/ISIN in S3 or EODHD"}` — EODHD has no data for this identifier
- **Response (429)**: Propagated from EODHD rate limit — Worker 13J treats this as retryable (does not increment `enrichment_attempts`)
- **Error responses**: 400 (no params), 422 (invalid format)
- **SSRF mitigation**: ticker and ISIN validated against allowlists inside S3 before inclusion in the EODHD request path

---

## 7. Kafka Events

### 7.1 Consumed Topics

| Topic | Schema | Producer | Consumed By |
|-------|--------|----------|-------------|
| `entity.canonical.created.v1` | Avro (PLAN-0062 schema) | S7 (existing) | Worker 13J hot-path consumer |

**Consumer group**: `kg-structured-enrichment-group`

No new Avro schemas required — the consumed event carries `entity_id`, `entity_type`, `canonical_name`, and `correlation_id`. **The event does NOT carry `ticker`** — the actual Avro schema for `entity.canonical.created.v1` has no ticker field. Worker 13J looks up `ticker` and `isin` from the `canonical_entities` row (using `entity_id`) before calling S3.

### 7.2 Produced Topics

| Topic | Schema | Notes |
|-------|--------|-------|
| `entity.dirtied.v1` | Compacted, direct produce | Produced after a successful enrichment write so `EmbeddingRetryWorker` refreshes the description embedding. Key = `entity_id`. NOT via outbox (same pattern as existing producers). |

No new output topic is required. The enrichment result is a write-back to `canonical_entities` in `intelligence_db`. The `entity.dirtied.v1` signal triggers the existing downstream embedding refresh.

---

## 8. Database Changes

All DDL is owned exclusively by **intelligence-migrations**. S7 sets `ALEMBIC_ENABLED=false` and never runs migrations itself.

### 8.1 `canonical_entities` — New Columns

Migration: `0024_add_enrichment_fields_to_canonical_entities.py`

| Column | PostgreSQL Type | Nullable | Default | Notes |
|--------|-----------------|----------|---------|-------|
| `description` | `TEXT` | YES | `NULL` | LLM-generated or EODHD-sourced natural-language description |
| `data_completeness` | `DOUBLE PRECISION` | YES | `NULL` | 0.0–1.0 computed at write time; `NULL` means never attempted |
| `enriched_at` | `TIMESTAMPTZ` | YES | `NULL` | UTC timestamp of last successful enrichment pass |
| `enrichment_attempts` | `INTEGER` | NO | `0` | Incremented on non-retryable failure; capped at 3 for permanent skip |

> **Note on `metadata JSONB`**: The `metadata` column already exists on `canonical_entities` (created in migration 0001). Likewise `isin VARCHAR(20)`, `ticker VARCHAR(20)`, and `exchange VARCHAR(20)` are already present. Migration 0024 adds only the **4 columns** above. Worker 13J writes enrichment data into BOTH the dedicated columns (`isin`, `ticker`, `exchange`) AND the `metadata` JSONB bag so that existing consumers reading from `metadata` continue to work.

**Forward-compatibility**: All additions are nullable or have server-side defaults. No existing rows are affected. `enrichment_attempts DEFAULT 0` means all existing entities start at 0 attempts, correctly eligible for the periodic sweep.

**Index**: Add `CREATE INDEX CONCURRENTLY ix_canonical_entities_enrichment_sweep ON canonical_entities (enrichment_attempts, enriched_at) WHERE enrichment_attempts < 3;` — supports the periodic sweep `WHERE enriched_at IS NULL OR data_completeness < 0.5 AND enrichment_attempts < 3` efficiently.

### 8.2 `relation_type_registry` — New Columns + Seed Data

Migration: `0025_add_source_fields_to_relation_type_registry.py`

| Column | PostgreSQL Type | Nullable | Default | Notes |
|--------|-----------------|----------|---------|-------|
| `data_source` | `TEXT` | YES | `NULL` | Origin of the structured data that produces this relation type: `'eodhd'`, `'market_data'`, `'llm'` |
| `source_field` | `TEXT` | YES | `NULL` | JSON path within the source response that maps to this relation type, e.g. `'General.Sector'`, `'General.Country'`, `'General.Exchange'` |

**Forward-compatibility**: Both columns are nullable with no server-side constraint; existing registry rows are unaffected.

**Seed data** (included in the same migration — no separate backfill migration needed since there is no production instance):

| `canonical_type` | `data_source` | `source_field` |
|-----------------|---------------|----------------|
| `OPERATES_IN_SECTOR` | `eodhd` | `General.Sector` |
| `OPERATES_IN_INDUSTRY` | `eodhd` | `General.Industry` |
| `HEADQUARTERED_IN` | `eodhd` | `General.Country` |
| `LISTED_ON` | `eodhd` | `General.Exchange` |
| `OPERATES_IN_SECTOR` | `market_data` | `sector` |
| `HEADQUARTERED_IN` | `market_data` | `country` |

The seed `UPDATE` is idempotent: `WHERE canonical_type = :type AND data_source IS NULL`. Rows not yet present in the registry are skipped (no INSERT).

### 8.2b `securities` — New Column (market-data Alembic migration)

**Service**: S3 market-data (not intelligence-migrations). Migration file: `services/market-data/alembic/versions/<rev>_add_description_to_securities.py`

| Column | PostgreSQL Type | Nullable | Default | Notes |
|--------|-----------------|----------|---------|-------|
| `description` | `TEXT` | YES | `NULL` | EODHD `General.Description` for the security; populated by `OnDemandProfileUseCase` when an on-demand fetch occurs |

**Forward-compatibility**: Nullable; existing rows unaffected. S2 Market Ingestion may also populate this field in a future sprint when fetching `company_profile` fundamentals.

### 8.3 `relations` — New Column

Migration: `0026_add_relation_source_to_relations.py`

| Column | PostgreSQL Type | Nullable | Default | Notes |
|--------|-----------------|----------|---------|-------|
| `relation_source` | `TEXT` | YES | `NULL` | Origin of the relation: `'structured_enrichment'` \| `'llm_extraction'` \| `'manual'`. Existing relations default to `NULL` (semantically: pre-enrichment / unknown origin) |

**Forward-compatibility**: Nullable column with no constraint. All existing `relations` rows remain valid with `NULL` source.

**Note on hash-partitioned table**: `relations` is hash-partitioned ×8 on `subject_entity_id`. Adding a nullable column with no default constraint is DDL-safe on partitioned tables in PostgreSQL 16. Migration uses `ALTER TABLE relations ADD COLUMN` — PostgreSQL propagates it to all child partitions automatically.

---

## 9. Domain Model Changes

### 9.1 `EnrichmentResult` — New Value Object (S7 Domain)

Location: `services/knowledge-graph/src/knowledge_graph/domain/entities/enrichment_result.py`

```python
@dataclass(frozen=True)
class EnrichmentResult:
    entity_id: UUID
    description: str | None
    metadata: dict[str, object]
    data_completeness: float
    enriched_at: datetime          # UTC
    source: EnrichmentSource       # enum: MARKET_DATA | EODHD | LLM | NONE
    seeded_relations: list[str]    # canonical_type values of relations seeded
```

**Invariants**:
- `data_completeness` in `[0.0, 1.0]`
- `enriched_at` must be UTC (timezone-aware)
- `seeded_relations` may be empty; never None

### 9.2 `EnrichmentSource` — New Enum

```python
class EnrichmentSource(str, Enum):
    MARKET_DATA = "market_data"    # description came from S3 existing DB data
    EODHD = "eodhd"               # description came via S3 on-demand EODHD fetch
    LLM = "llm"                   # description generated by LLM
    NONE = "none"                 # enrichment attempted but no description obtained
```

### 9.3 `data_completeness` Computation

Computed by a pure function `compute_data_completeness(entity_type, description, metadata)` in `domain/entities/enrichment_result.py`. All field lookups treat empty strings as absent (`None or ""`).

**For `financial_instrument` and `company`** (10 expected fields):

```
expected = [
    description,
    metadata.get("sector"),
    metadata.get("industry"),
    metadata.get("country"),
    metadata.get("exchange"),
    metadata.get("isin"),
    metadata.get("ticker"),
    metadata.get("employee_count"),
    metadata.get("founded_year"),
    metadata.get("headquarters_country"),
]
data_completeness = len([f for f in expected if f]) / 10
```

**For `person`** (4 expected fields):

```
expected = [
    description,
    metadata.get("role"),
    metadata.get("organization"),
    metadata.get("nationality"),
]
data_completeness = len([f for f in expected if f]) / 4
```

**For `concept`, `location`, `event`** (2 expected fields):

```
expected = [
    description,
    metadata.get("category"),
]
data_completeness = len([f for f in expected if f]) / 2
```

### 9.4 `EntityEnrichmentPort` — New Application Port

Location: `services/knowledge-graph/src/knowledge_graph/application/ports/entity_enrichment.py`

```python
class EntityEnrichmentPort(Protocol):
    async def write_enrichment_result(
        self,
        result: EnrichmentResult,
        uow: UnitOfWork,
    ) -> None: ...

    async def increment_attempts(
        self,
        entity_id: UUID,
        uow: UnitOfWork,
    ) -> None: ...

    async def list_unenriched(
        self,
        batch_size: int,
    ) -> list[CanonicalEntity]: ...
```

### 9.5 `StructuredEnrichmentUseCase` — New Use Case

Location: `services/knowledge-graph/src/knowledge_graph/application/use_cases/structured_enrichment.py`

Owns the orchestration logic for a single entity enrichment run:

1. Attempt S3 lookup via `GET /api/v1/instruments/lookup?extra_info=true` (existing S3 DB data including enrichment fields)
2. If description absent → call `GET /api/v1/instruments/on-demand-profile` (DB-first → EODHD on-demand via S3; persists result to DB)
3. **Conditional** LLM description generation — only if description is still null after Steps 1–2 OR entity type is `person`, `concept`, `location`, `event` (EODHD never has data for these types). When structured description already found: skip LLM entirely for that entity.
4. Compute `data_completeness`
5. Seed relations from `relation_type_registry`
6. Persist via `EntityEnrichmentPort`
7. Produce `entity.dirtied.v1` post-commit

The use case is injected with: `EntityEnrichmentPort`, `RelationTypeRegistryRepository`, `MarketDataClient` (internal HTTP — calls both S3 endpoints), `ExtractionClient` (LLM), `DirectKafkaProducer` (for `entity.dirtied.v1`).

---

## 10. Data Flow

### 10.1 Hot-Path (Event-Driven)

Triggered by `entity.canonical.created.v1` events. Only fires for entity types `financial_instrument` and `company`.

```
[S6 NLP Pipeline]
    │
    │  entity.canonical.created.v1 (Avro)
    ▼
[S7 StructuredEnrichmentConsumer]  consumer group: kg-structured-enrichment-group
    │
    │  1. Check entity_type — skip if not financial_instrument / company
    │  2. Valkey dedup on event_id (fail-open: if Valkey unavailable, proceed)
    │
    ▼
[StructuredEnrichmentUseCase.enrich(entity)]
    │
    ├─► Step 1: GET /api/v1/instruments/lookup?ticker=...&isin=...&extra_info=true
    │     ticker/isin read from canonical_entities row (NOT from Kafka event)
    │     S3 returns enriched instrument row (sector, industry, country, isin, description) or 404
    │     If description found in S3 DB → source = MARKET_DATA, skip Steps 2 and 3
    │
    ├─► Step 2: (if description still None) GET /api/v1/instruments/on-demand-profile?ticker=...
    │     S3 DB-first → EODHD on-demand if description missing
    │     PERSISTS result: upserts description/sector/industry/country/currency into securities table
    │     Extract: description, sector, industry, country, exchange, isin
    │     source = EODHD_PERSISTED
    │     Retryable on 429 (EODHD rate limit propagated by S3); non-retryable on 404
    │     If description found → skip Step 3
    │
    ├─► Step 3: LLM enrichment (CONDITIONAL — only when description still null OR
    │     entity type is person/concept/location/event)
    │     DeepInfra ENRICHMENT_LLM_MODEL_ID
    │     Few-shot prompt with EODHD example descriptions as anchors
    │     Output: high-quality multi-sentence description
    │
    ├─► Step 4: compute_data_completeness(entity_type, description, metadata)
    │
    ├─► Step 5: Seed relations from relation_type_registry
    │     SELECT * FROM relation_type_registry WHERE data_source IN ('eodhd','market_data')
    │       AND source_field IS NOT NULL
    │     For each registry row: if source_field key present in enrichment payload →
    │       upsert relation (subject=entity_id, object=sector/country/exchange entity,
    │       canonical_type=registry.canonical_type, relation_source='structured_enrichment')
    │
    ├─► Step 6: Write EnrichmentResult to canonical_entities
    │     UPDATE canonical_entities SET
    │       description=..., metadata=..., data_completeness=...,
    │       enriched_at=utc_now(), enrichment_attempts=0  -- reset on success
    │     WHERE entity_id=...
    │
    └─► Step 7: Produce entity.dirtied.v1 (direct produce, post-commit)
              Key = entity_id (UTF-8 bytes)
```

**On non-retryable failure** (e.g., EODHD 400, LLM JSON parse error):
```
UPDATE canonical_entities SET enrichment_attempts = enrichment_attempts + 1
WHERE entity_id = ...
```

**On retryable failure** (HTTP 429, 503): raise exception to let Kafka consumer retry delivery; do NOT increment `enrichment_attempts`.

### 10.2 Periodic Sweep (APScheduler)

Scheduled: daily at 02:00 UTC. APScheduler job id: `worker_13j_enrichment_sweep`.

```
[APScheduler: 02:00 UTC]
    │
    ▼
[StructuredEnrichmentWorker.run()]
    │
    │  1. Query batch of up to 50 entities:
    │     SELECT * FROM canonical_entities
    │     WHERE (enriched_at IS NULL OR data_completeness < 0.5)
    │       AND enrichment_attempts < 3
    │     ORDER BY created_at ASC
    │     LIMIT 50
    │
    │  2. For each entity: call StructuredEnrichmentUseCase.enrich(entity)
    │     (same logic as hot-path, but covers all entity_types)
    │
    │  3. If batch size == 50: re-query for next batch (loop until 0 results)
    │
    │  4. Emit Prometheus counter: s7_enrichment_sweep_entities_processed_total
    │
    └─► End of sweep: log summary (processed, succeeded, failed, skipped)
```

**Batch ordering**: `ORDER BY created_at ASC` ensures newer entities are processed last, giving priority to entities that have been waiting longest. (`first_seen_at` does not exist on `canonical_entities` — the correct column is `created_at`.) In practice the sweep processes all pending entities on first run (the bootstrap sweep), then incrementally covers new entities on subsequent daily runs.

**Session management** (R25 / ARCH-003 compliance): DB session is opened per-batch, not held across LLM or HTTP calls. The 3-phase pattern is used: (1) read batch rows and close session, (2) call external APIs with no session open, (3) open new session for writes.

---

## 11. Architecture Decisions

### ADR-0073-001: S3 as Unified Structured Data Gateway (Unified Lookup + On-Demand EODHD with Persistence)

**Decision**: Consolidate S3's two existing single-item lookup endpoints (`GET /instruments/symbol/{symbol}` and `GET /instruments/{instrument_id}`) into a single `GET /instruments/lookup` with `symbol`, `isin`, `id` query params and an `extra_info` flag for enrichment fields. Add an internal `GET /instruments/on-demand-profile` that fetches from EODHD and **persists the result** to the `securities` table. Worker 13J never calls EODHD directly.

**Rationale**: A unified lookup endpoint eliminates the three-way identifier fragmentation, gives the frontend and S9 a single call surface, and reduces cognitive load for API consumers. Adding `extra_info=true` cleanly separates the lightweight use case (just need the id/symbol) from the enrichment use case (need description, sector, etc.) without creating a new endpoint. Persisting EODHD on-demand results means that a ticker fetched once never triggers another EODHD call — it becomes part of the S3 universe and is eligible for S2's regular ingestion polling. This is the right long-term architecture: on-demand fetch is the bootstrap mechanism that seeds the universe, not a perpetual live lookup.

**Alternative considered**: Keep separate symbol/{symbol} and /{instrument_id} endpoints alongside the new /lookup. Rejected — duplicates routing logic, complicates S9 proxy and frontend call sites, and leaves a permanent maintenance burden with three endpoints where one suffices.

**Constraint**: Worker 13J calls the on-demand-profile endpoint with an RS256 system JWT. Public callers (frontend via S9) use Bearer JWT and access only the `/lookup` endpoint.

### ADR-0073-002: LLM Called Conditionally (Only When Structured Description Is Absent)

**Decision**: LLM enrichment is called only when `description` is still null after Steps 1–2, OR when the entity type is `person`, `concept`, `location`, or `event` (for which EODHD never has data). For `financial_instrument` and `company` entities where EODHD or S3 DB already provided a description, the LLM call is skipped entirely.

**Rationale**: Calling LLM for every entity regardless of whether structured data succeeded wastes tokens, adds latency (25 s timeout per entity × thousands of entities), and provides no benefit when EODHD has already given a high-quality description. The LLM is the enrichment source of last resort for financial entities and the primary source for non-financial entities — not a supplement to structured data. This distinction produces a cleaner enrichment pipeline and reduces per-entity cost by >70% in a universe dominated by financial instruments.

**Alternative considered**: LLM always attempted for quality enhancement (previous design). Rejected — EODHD descriptions are factually grounded and finance-professional quality; an LLM supplement stored in `metadata["llm_description"]` adds storage complexity and dual-source confusion without measurable user benefit.

### ADR-0073-003: Few-Shot LLM Prompt with EODHD Anchors

**Decision**: The LLM enrichment prompt uses few-shot examples drawn from high-quality EODHD descriptions of well-known companies (Apple, Microsoft, JPMorgan) as style anchors.

**Rationale**: Raw zero-shot prompts for financial entities produce inconsistent quality. Few-shot examples constrain the model to finance-professional prose style, appropriate length (3–5 sentences), and factual grounding. The examples are embedded directly in the system prompt for the ENRICHMENT_LLM_MODEL_ID model and do not require external retrieval.

**Prompt location**: `libs/prompts/src/prompts/knowledge/entity_enrichment.py` — follows the central prompt library pattern established by PLAN-0034.

### ADR-0073-004: `relation_source` Column on Partitioned `relations` Table

**Decision**: Add `TEXT NULL` column `relation_source` to the `relations` table (hash-partitioned ×8).

**Rationale**: Knowing the provenance of each relation edge is essential for quality audits. Structured enrichment relations (sector, country, exchange) should be distinguishable from NLP-extracted and manually curated relations for downstream filtering and scoring.

**Risk**: PostgreSQL propagates `ADD COLUMN NULL` to all child partitions automatically — this is safe. The migration MUST NOT specify `NOT NULL` without a default.

**Alternative considered**: Separate `relation_provenance` table (FK to `relations`). Rejected — adds a join on an already-partitioned table; inline column is simpler and sufficient for thesis scope.

### ADR-0073-005: `enrichment_attempts` as Fail-Fast Counter (Max 3)

**Decision**: Permanently skip entities after 3 non-retryable failures; reset only via manual DB update.

**Rationale**: Prevents infinite retry storms against permanently invalid entities (e.g., generic concept entities like "recession" that will never have EODHD data and whose LLM prompt consistently fails). The 3-attempt threshold covers transient infrastructure failures while terminating pathological retry loops. Operators can reset `enrichment_attempts = 0` individually.

**Alternative considered**: Exponential backoff with no hard cap. Rejected — thesis scope does not require a distributed backoff scheduler; APScheduler daily sweep plus a 3-attempt cap is sufficient.

### ADR-0073-006: `Qwen/Qwen3-235B-A22B-Instruct-2507` as Primary Enrichment Model

**Decision**: Default `ENRICHMENT_LLM_MODEL_ID=Qwen/Qwen3-235B-A22B-Instruct-2507` with `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` as fallback.

**Rationale**: Qwen3-235B is the highest-quality available DeepInfra model as of 2026-05-05. Description quality directly affects RAG retrieval and entity graph UX; this is worth the cost delta. The Turbo Llama fallback is confirmed available (2026-05-01 to 2026-06-01 window) and activates only when the primary returns a non-200.

**Important**: `Qwen/Qwen2.5-0.5B-Instruct` and `Qwen/Qwen2.5-1.5B-Instruct` return 404 on this DeepInfra account — never use these as fallbacks.

---

## 12. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| **Prompt injection via entity name** | Entity `canonical_name` inserted into LLM prompt MUST be enclosed in delimiter markers (`<entity>` tags) and stripped of control characters before inclusion. Use the `prompts.knowledge.alias.sanitize_description` helper (established by PLAN-0057 F-SEC-02) |
| **SSRF via ticker/ISIN in S3 on-demand request** | S3's `on-demand-profile` endpoint validates ticker against `^[A-Z0-9.\-]{1,20}$` and ISIN against `^[A-Z]{2}[A-Z0-9]{9}[0-9]$` before including in the EODHD request path. Worker 13J sends raw query params to S3 — S3 owns SSRF mitigation for the EODHD leg |
| **SSRF via market-data internal URL** | `MARKET_DATA_INTERNAL_URL` is a configured server-to-server endpoint, not user-controlled. No runtime validation needed beyond confirming the env var is set |
| **LLM cost exhaustion** | DeepInfra usage is bounded by `enrichment_attempts < 3` (9 LLM calls max per entity over its lifetime). Periodic sweep batch cap of 50 entities per run limits per-day spend. A future `ENRICHMENT_MAX_MONTHLY_USD` budget guard may be added (DEFERRED — see §18) |
| **Internal JWT exposure** | Worker 13J signs an RS256 system JWT when calling S3 `GET /api/v1/instruments/on-demand-profile`. The signing key is read from `KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY` (already an established secret). Never logged |
| **Metadata JSONB injection** | `metadata` JSONB is written exclusively from controlled enrichment code paths, not from user input. No sanitization gap. The EODHD response is parsed field-by-field — raw EODHD JSON is never stored verbatim |

---

## 13. Failure Modes

### 13.1 S3 Market-Data REST Unreachable

**Symptom**: `httpx.ConnectError` or `httpx.TimeoutException` on `GET /api/v1/instruments/lookup` or `GET /api/v1/instruments/on-demand-profile`.

**Handling**: Log `WARN` with `entity_id` and service context. Fall through to EODHD step. Do NOT increment `enrichment_attempts` — S3 unavailability is a transient infrastructure failure, not an entity-level problem.

**Metric**: `s7_enrichment_market_data_miss_total{reason="timeout|connect_error|not_found"}`.

### 13.2 S3 On-Demand Profile 429 (EODHD Rate Limit Propagated)

**Symptom**: `GET /api/v1/instruments/on-demand-profile` returns 429 (S3 propagates EODHD rate limit upstream).

**Handling**: Treat as retryable. Raise exception back to the consumer; Kafka will redeliver. Do NOT increment `enrichment_attempts`. The consumer uses the existing `BaseKafkaConsumer` backoff mechanism.

**Note**: For the periodic sweep, a 429 aborts the current sweep iteration. The entity remains eligible for the next daily sweep.

### 13.3 S3 On-Demand Profile 404 (EODHD Has No Data for This Ticker)

**Symptom**: `GET /api/v1/instruments/on-demand-profile` returns 404 (neither S3 DB nor EODHD has a profile for this ticker/ISIN).

**Handling**: Non-retryable for the on-demand step. Log `INFO` (not `WARN` — expected for non-US, non-listed, or concept/location entities). Fall through to LLM step. If LLM also fails, increment `enrichment_attempts`.

### 13.4 LLM DeepInfra Unavailable (503) or Timeout

**Symptom**: DeepInfra returns 503 or the `asyncio.wait_for` 25 s timeout fires.

**Handling**: Retryable. Raise exception. Do NOT increment `enrichment_attempts`. The entity remains eligible for the next sweep or consumer retry.

**Fallback**: If primary model (`ENRICHMENT_LLM_MODEL_ID`) returns 404 or 500, retry once with `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`. If fallback also fails, treat as transient failure.

### 13.5 LLM Returns Malformed or Empty Description

**Symptom**: LLM response is parseable JSON but the description field is empty, null, or shorter than 20 characters.

**Handling**: Non-retryable for this entity on this attempt. Increment `enrichment_attempts`. Log `WARN` with entity context and response excerpt. The entity will be re-attempted on the next daily sweep (if `enrichment_attempts < 3`).

### 13.6 Relation Seeding Fails (object entity missing)

**Symptom**: `OPERATES_IN_SECTOR` seeding fails because the sector entity (e.g., "Technology") does not yet exist in `canonical_entities`.

**Handling**: Log `INFO`. Skip this relation silently. The sector entity is seeded by migration 0003 (GICS entities) and `FundamentalsRefreshWorker` uses `CanonicalEntityRepository.find_by_name_and_type()` — Worker 13J uses the same lookup. If the sector canonical entity is missing (edge case: custom sector name from EODHD), the relation is skipped rather than creating an orphan. This is safe — the enrichment write still proceeds.

### 13.7 `entity.dirtied.v1` Produce Fails Post-Commit

**Symptom**: Direct Kafka produce fails after the DB commit succeeds.

**Handling**: Log `ERROR` with entity_id. The entity enrichment IS persisted (the commit succeeded). The embedding refresh will be missed for this entity on this event. No increment to `enrichment_attempts`.

**Recovery path** (explicit, not silent): `EmbeddingRetryWorker` (Worker 13E-4) runs on a periodic schedule and queries for entities where `enriched_at > last_embedding_computed_at` (or where the embedding simply does not exist). This means the worker will detect the gap on its next run and trigger the embedding refresh without any manual intervention. The worst case is a delay of up to one `WORKER_EMBEDDING_REFRESH_INTERVAL_S` (default 3600 s) before the description embedding is updated in `entity_embedding_state`.

**Note on outbox**: `entity.dirtied.v1` intentionally uses direct produce (not the transactional outbox) consistent with the existing pattern for this topic across all producers. A platform-wide outbox adoption — which would eliminate this failure mode entirely — is tracked as a separate architectural initiative (see §18 OQ-006).

---

## 14. Scalability

### Current Thesis Scope

- `canonical_entities` table has O(1000–10000) rows in thesis scope.
- The periodic sweep processes 50 entities per batch. A full table of 10,000 entities with 80% unenriched = 8,000 entities = 160 batches. At ~2 s per entity (dominated by LLM latency), the first full sweep takes ~4.5 hours. This is acceptable for an overnight bootstrap run.
- Subsequent daily sweeps only process newly created entities (typically < 100 per day in thesis load), completing in minutes.

### Concurrency Constraints

- **Hot-path consumer**: single partition assignment per consumer group instance. No parallel enrichment for the same entity. Safe.
- **Periodic sweep**: single APScheduler instance. No risk of parallel sweep runs.
- **LLM concurrency**: `asyncio.gather` is NOT used within a single sweep batch to avoid overwhelming DeepInfra. Entities are enriched sequentially within each batch to respect rate limits and the 25 s per-entity timeout.

### Future Scale Considerations

If `canonical_entities` grows to O(100K+) entities (post-thesis production):

1. Add `CONCURRENTLY` index on `(enrichment_attempts, enriched_at)` (already planned in migration 0024 — see §8.1).
2. Increase sweep batch size and add `asyncio.gather` with bounded concurrency (semaphore of 5).
3. Consider moving the sweep to a dedicated container outside APScheduler to avoid blocking other workers.

These are operational configuration changes, not architectural ones.

---

## 15. Test Strategy

### 15.1 Unit Tests

Location: `services/knowledge-graph/tests/unit/application/use_cases/`

| Test Name | What It Covers |
|-----------|---------------|
| `test_enrich_financial_instrument_market_data_first` | Market-data REST returns description → EODHD is NOT called; `source=MARKET_DATA` in result |
| `test_enrich_financial_instrument_on_demand_profile_fallback` | S3 lookup returns 404 → S3 on-demand-profile called; description and sector extracted correctly |
| `test_enrich_financial_instrument_llm_only` | Both market-data 404 and EODHD 404 → LLM called; description stored; `source=LLM` |
| `test_enrich_person_llm_only` | Person entity → market-data and EODHD skipped; LLM generates biography; `data_completeness` formula uses 4 fields |
| `test_enrich_concept_llm_generates_definition` | Concept entity → LLM generates definition; `data_completeness` formula uses 2 fields |
| `test_data_completeness_financial_instrument_full` | All 10 fields present → `data_completeness == 1.0` |
| `test_data_completeness_financial_instrument_partial` | 5 of 10 fields present → `data_completeness == 0.5` |
| `test_data_completeness_empty_strings_treated_as_absent` | Fields set to `""` → treated as missing in completeness calculation |
| `test_enrichment_attempts_not_incremented_on_retryable_error` | HTTP 429 raises exception without incrementing attempts |
| `test_enrichment_attempts_incremented_on_llm_parse_failure` | LLM returns empty description → `enrichment_attempts` incremented |
| `test_entity_skipped_after_max_attempts` | Entity with `enrichment_attempts=3` → `StructuredEnrichmentUseCase.enrich()` returns early without calling any external APIs |
| `test_relation_seeding_eodhd_sector` | EODHD returns sector "Technology" → `OPERATES_IN_SECTOR` relation upserted with `relation_source='structured_enrichment'` |
| `test_relation_seeding_skips_missing_object_entity` | Sector entity not in `canonical_entities` → relation skipped; enrichment write proceeds |
| `test_entity_dirtied_produced_after_commit` | Successful enrichment → `entity.dirtied.v1` produced; NOT produced before commit |
| `test_llm_prompt_sanitizes_entity_name` | `canonical_name` containing `<script>` tag → sanitized before insertion into prompt |

Location: `services/knowledge-graph/tests/unit/domain/`

| Test Name | What It Covers |
|-----------|---------------|
| `test_compute_data_completeness_financial_instrument` | Parameterized: 0/1/5/10 fields present; correct formula applied |
| `test_compute_data_completeness_person` | 0/2/4 fields present |
| `test_compute_data_completeness_concept_event_location` | 0/1/2 fields present |
| `test_enrichment_source_enum_values` | `str(EnrichmentSource.MARKET_DATA) == "market_data"` |

### 15.2 Integration Tests

Location: `services/knowledge-graph/tests/integration/`

| Test Name | What It Covers |
|-----------|---------------|
| `test_enrichment_full_pipeline_financial_instrument` | Live `intelligence_db` testcontainer: entity created → `StructuredEnrichmentUseCase` runs with mocked S3/EODHD/LLM → new columns written → verify `SELECT description, metadata, data_completeness, enriched_at, enrichment_attempts FROM canonical_entities WHERE entity_id=...` |
| `test_enrichment_sweep_processes_unenriched_batch` | Insert 10 unenriched entities → run `StructuredEnrichmentWorker.run()` → verify all 10 have `enriched_at IS NOT NULL` |
| `test_enrichment_sweep_skips_maxed_attempts` | Insert 5 entities with `enrichment_attempts=3` → run sweep → verify none are touched |
| `test_relation_seeding_writes_to_relations_table` | Full pipeline with mocked EODHD returning sector="Healthcare" → verify `relations` row exists with `relation_source='structured_enrichment'` and `canonical_type='OPERATES_IN_SECTOR'` |

### 15.3 Contract Tests

Location: `services/knowledge-graph/tests/contract/`

| Test Name | What It Covers |
|-----------|---------------|
| `test_entity_public_schema_includes_enrichment_fields` | `EntityPublic` Pydantic model validates a response containing `description`, `metadata`, `data_completeness`, `enriched_at` |
| `test_entity_public_schema_allows_null_enrichment_fields` | `EntityPublic` validates a response where all four new fields are `null` (backward compat) |
| `test_get_entity_endpoint_includes_enrichment_fields` | S7 `GET /api/v1/entities/{entity_id}` response shape validated against `EntityPublic` with new fields |

### 15.4 Architecture Tests

The existing architecture guard `TestLayerIsolation` (95 tests) validates that:
- `StructuredEnrichmentWorker` (infrastructure) does NOT import from `domain/`'s external I/O adapters
- `StructuredEnrichmentUseCase` (application) does NOT import from `infrastructure/`
- `EntityEnrichmentPort` (application port) is defined as a Protocol, not a concrete class

No new architecture test file required — the existing guards cover these invariants.

---

## 16. Migration Plan

Migrations are applied in order by the `intelligence-migrations` init container. S7 and S6 do NOT run Alembic (`ALEMBIC_ENABLED=false`).

> **Migration numbering note**: IDs 0020–0023 are occupied by PLAN-0072 (KG Data Quality Enhancement). PLAN-0073 starts at **0024**. Do not implement PLAN-0073 Wave A until PLAN-0072 migrations are merged to `main`.

**intelligence-migrations** (3 migrations, down from 4 — seed data folded into 0025):

| Order | Migration ID | File | Table(s) Affected | Notes |
|-------|-------------|------|------------------|-------|
| 1 | `0024` | `0024_add_enrichment_fields_to_canonical_entities.py` | `canonical_entities` | Add 4 columns + sweep index (`CONCURRENTLY`). All nullable or `DEFAULT 0`. (`metadata JSONB` already exists from migration 0001 — not added again.) |
| 2 | `0025` | `0025_add_source_fields_to_relation_type_registry.py` | `relation_type_registry` | Add 2 nullable columns + seed 6 EODHD/market-data relation type mappings in same migration (no backfill migration needed — no production data to treat). |
| 3 | `0026` | `0026_add_relation_source_to_relations.py` | `relations` (+ all 8 partitions) | Add 1 nullable column. PostgreSQL propagates to child partitions automatically. |

**market-data migrations** (separate Alembic chain, owned by S3):

| Order | Migration | Table(s) Affected | Notes |
|-------|-----------|------------------|-------|
| 1 | `<rev>_add_description_to_securities.py` | `securities` | Add `description TEXT NULL`. Populated by `OnDemandProfileUseCase` when EODHD is called. Additive-only. |

**Downgrade path**:
- `0024` downgrade: `DROP COLUMN` for 4 columns; index dropped automatically.
- `0025` downgrade: `DROP COLUMN` for 2 columns (seed data rows become unreachable — acceptable since no production instance).
- `0026` downgrade: `DROP COLUMN relation_source` from `relations`. PostgreSQL drops from all partitions.
- market-data `description` downgrade: `DROP COLUMN description` from `securities`.

**Zero-downtime deployment**: All migrations are additive-only (new nullable columns, index `CONCURRENTLY`). S7 and S6 can continue operating on the old schema while migrations apply. After migration 0024 completes, the new S7 deployment picks up the columns.

**Important**: `CREATE INDEX CONCURRENTLY` cannot run inside a transaction. Migration 0024 MUST use `op.execute("CREATE INDEX CONCURRENTLY ...")` outside any Alembic transaction block. Use Alembic's `with op.get_context().autocommit_block():` pattern.

---

## 17. Observability

### 17.1 Structured Logging (structlog)

All log entries include `service="knowledge-graph"`, `worker="structured_enrichment"`, and `entity_id`.

| Event | Level | Fields |
|-------|-------|--------|
| Enrichment started | DEBUG | `entity_id`, `entity_type`, `trigger` (hot_path\|sweep) |
| Market-data hit | INFO | `entity_id`, `ticker`, `description_length` |
| Market-data miss | INFO | `entity_id`, `reason` (not_found\|timeout\|error) |
| EODHD hit | INFO | `entity_id`, `ticker`, `sector`, `industry` |
| EODHD miss | INFO | `entity_id`, `reason` |
| LLM success | INFO | `entity_id`, `model_id`, `description_length`, `latency_ms` |
| LLM failure | WARN | `entity_id`, `model_id`, `error_type`, `response_excerpt` |
| Enrichment complete | INFO | `entity_id`, `data_completeness`, `source`, `seeded_relations_count`, `duration_ms` |
| Enrichment failed (non-retryable) | WARN | `entity_id`, `enrichment_attempts`, `error` |
| Enrichment skipped (max attempts) | INFO | `entity_id`, `enrichment_attempts=3` |
| Sweep started | INFO | `batch_size`, `cursor` |
| Sweep completed | INFO | `processed`, `succeeded`, `failed`, `skipped`, `duration_s` |

### 17.2 Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `s7_enrichment_entities_total` | Counter | `trigger` (hot_path\|sweep), `result` (success\|failure\|skip) | Total enrichment attempts by trigger and outcome |
| `s7_enrichment_source_total` | Counter | `source` (market_data\|eodhd\|llm\|none) | How many entities got description from each source |
| `s7_enrichment_market_data_miss_total` | Counter | `reason` (not_found\|timeout\|connect_error) | S3 REST misses |
| `s7_enrichment_llm_latency_seconds` | Histogram | `model_id` | LLM call duration; buckets: 1, 5, 10, 25 s |
| `s7_enrichment_data_completeness` | Histogram | `entity_type` | Distribution of `data_completeness` scores at write time; buckets: 0.1, 0.3, 0.5, 0.7, 0.9, 1.0 |
| `s7_enrichment_sweep_entities_processed_total` | Counter | — | Total entities processed in all sweep runs combined |
| `s7_enrichment_relations_seeded_total` | Counter | `canonical_type` | Relations created by structured enrichment seeding |

### 17.3 Alerts

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| `EnrichmentFailureRateHigh` | `rate(s7_enrichment_entities_total{result="failure"}[1h]) / rate(s7_enrichment_entities_total[1h]) > 0.1` | WARNING | Check LLM provider status; inspect DLQ |
| `EnrichmentSweepNotRunning` | `time() - last_sweep_start > 90000` (25 h) | WARNING | Check APScheduler health; verify scheduler_main is running |

---

## 18. Open Questions

| ID | Question | Status |
|----|----------|--------|
| OQ-002 | Should a `ENRICHMENT_MAX_MONTHLY_USD` budget guard be added to prevent LLM cost overruns during large bootstrap sweeps? | DEFERRED — track DeepInfra usage dashboard manually until volume warrants automated budget enforcement |
| OQ-003 | Should the periodic sweep fire more frequently (e.g., every 6 hours) for newly created entities during active ingestion periods? | DEFERRED — the hot-path consumer covers `financial_instrument` and `company` entities immediately; other types can wait 24 hours without impacting critical path |
| OQ-004 | Should `relation_source` be added to the `relation_evidence_raw` table as well, for evidence-level provenance? | DEFERRED — evidence rows already have `source_document_id`; adding a free-text `relation_source` field is low priority |
| OQ-005 | Should Worker 13J also trigger a `definition` embedding refresh directly (bypassing the `entity.dirtied.v1` → `EmbeddingRetryWorker` chain) to reduce end-to-end latency? | DEFERRED — the indirect path is architecturally cleaner; `EmbeddingRetryWorker` provides recovery within one interval |
| OQ-006 | Platform-wide transactional outbox adoption — should all Kafka produces (including `entity.dirtied.v1`) be routed through a transactional outbox table + background dispatcher to eliminate the post-commit produce failure class? | ACTIVE OPEN QUESTION — user-directed architectural initiative. This eliminates the R8 violation class entirely. Should be a dedicated PRD (e.g. PRD-0076) modelled on PLAN-0062 (Avro enforcement) in scope. Will touch all services that currently use direct produce. |

---

## 19. Estimation

### Complexity Breakdown

| Component | Effort | Notes |
|-----------|--------|-------|
| intelligence-migrations: 3 migrations (0024–0026) | 0.5 d | DDL + seed data in 0025; index CONCURRENTLY pattern established |
| market-data migration: `securities.description` column | 0.25 d | Additive nullable column; simple migration |
| S3 unified `/lookup` endpoint (refactor + `extra_info` flag) | 0.75 d | Replaces 2 endpoints; adds enrichment fields; S9 + frontend propagation |
| S3 `on-demand-profile` endpoint with DB persistence | 0.5 d | DB upsert of EODHD result added to existing use case |
| `EnrichmentResult` domain entity + port + use case | 1 d | Core logic; conditional LLM; 3-phase session management |
| `StructuredEnrichmentWorker` (hot-path consumer + APScheduler job) | 1 d | Consumer wiring, backoff handling, Valkey dedup |
| `MarketDataClient` in S7 + new endpoint wiring | 0.5 d | Client patterns established; new `/lookup?extra_info=true` call |
| LLM enrichment prompt + `libs/prompts` entry | 0.5 d | Few-shot prompt design + integration with `ExtractionClient` |
| Relation seeding logic | 0.5 d | Registry lookup + upsert with `relation_source` field |
| `GetEntityDetailUseCase` + `EntityPublic` schema (S7 + S9) | 0.5 d | Use case wrapper required by R25; 4 nullable fields |
| Frontend intelligence tab description panel | 0.5 d | Conditional render when `description` non-null |
| Unit tests | 1 d | Coverage of all enrichment paths, completeness formula, sanitization, conditional LLM |
| Integration tests (4 tests) | 0.5 d | Testcontainer for intelligence_db |
| Contract tests (3 tests) | 0.25 d | Schema shape validation |
| Observability (metrics + logging + alerts) | 0.25 d | Follows established S7 patterns |
| QA pass + docs updates | 0.5 d | `.claude-context.md` S3 + S7 + docs + TRACKING.md |

**Total estimated effort**: ~9 days (+2 d from original estimate due to S3 endpoint refactor + endpoint propagation)

### Implementation Wave Suggestion

| Wave | Scope |
|------|-------|
| **Wave A** | intelligence-migrations 0024–0026 (with seed in 0025) + market-data `securities.description` migration |
| **Wave B** | S3 unified `/lookup` refactor + `extra_info` flag + `on-demand-profile` with persistence + S9 proxy update + frontend caller update |
| **Wave C** | S7 domain entities + port + config + LLM prompt (`libs/prompts`) + `MarketDataClient` + `StructuredEnrichmentUseCase` + worker + unit tests |
| **Wave D** | `GetEntityDetailUseCase` + `EntityPublic` (S7 + S9) + frontend description panel + integration/contract tests + QA |

---

*This PRD is the authoritative spec for PRD-0073. All implementation waves generated by `/plan 0073` reference this document.*
