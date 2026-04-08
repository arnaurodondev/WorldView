---
id: PLAN-0018
title: Geopolitical Intelligence + EODHD Deep Enrichment + Apache AGE Cypher Shadow Sync
prd: docs/specs/0018-geopolitical-intelligence-age-cypher.md
status: in-progress
created: 2026-04-08
updated: 2026-04-09


total_waves: 10
waves_done: 9
---

# PLAN-0018: Geopolitical Intelligence, EODHD Deep Enrichment & AGE Cypher

> **PRD**: `docs/specs/0018-geopolitical-intelligence-age-cypher.md`
> **Status**: in-progress
> **Depends on**: PLAN-0001-C (S7 graph infra), PLAN-0017 (entity embedding views — migration 0003 must run first)

---

## Sub-Plan Index

| Sub-Plan | Service | Waves | Depends On |
|----------|---------|-------|------------|
| A | intelligence-migrations + infra/kafka/schemas + S7 domain | A-1 | PLAN-0017 A-1 (migration 0003 done) |
| B | S7 Workers — EODHD enrichment | B-1 → B-4 | A-1 |
| C | S7 — Temporal Event consumer + repository | C-1 → C-2 | A-1 |
| D | S7 — AGE shadow sync Worker 13F | D-1 | A-1, C-1 |
| E | S7 — Cypher + Temporal Events API endpoints | E-1 → E-2 | D-1, C-1 |
| F | S6 Block 13E + S8 integration | F-1 | E-1, E-2 |

---

## Wave Completion Tracker

### Wave A-1: Foundation — DB Migration 0004 + Avro Schema + S7 Domain Models ✅

**Status**: **DONE** — 2026-04-08 · 313 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] Create `0004_geopolitical_age_temporal_events.py` (revision `d4e5f6a1b2c3`, revises `c3d4e5f6a1b2`)
- [x] AGE extension + graph schema (worldview_graph, 27 edge labels + EVENT_EXPOSES)
- [x] `relations` table: ADD COLUMN `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- [x] Create `temporal_events` table with 4 indexes + natural key unique index
- [x] Create `entity_event_exposures` table with unique constraint
- [x] Seed 3 new relation types: `has_executive`, `revenue_from_country`, `operates_in_country`
- [x] Create `infra/kafka/schemas/intelligence.temporal_event.v1.avsc`
- [x] Add `EventScope`, `EventType`, `ExposureType` enums to `knowledge_graph/domain/enums.py`
- [x] Add 3 new `RelationType` values to `knowledge_graph/domain/enums.py`
- [x] Add `TemporalEvent`, `EntityEventExposure` frozen dataclasses to `knowledge_graph/domain/models.py`
- [x] New unit tests: `test_temporal_events.py` (lifecycle phases, impact weights, frozen constraint)
- [x] Updated unit tests: `test_enums.py` (RelationType count 8 → 11)
- [x] Migration tests: new 0004 table/column/index assertions

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (88 source files, 0 issues)
- [x] Unit tests pass (domain): 313 tests, 0 failures
- [ ] Integration tests pass (migration): requires running Postgres with AGE extension

**Estimated effort**: 4h
**Files**:
- `services/intelligence-migrations/alembic/versions/0004_geopolitical_age_temporal_events.py`
- `services/intelligence-migrations/tests/test_migration.py`
- `infra/kafka/schemas/intelligence.temporal_event.v1.avsc`
- `services/knowledge-graph/src/knowledge_graph/domain/enums.py`
- `services/knowledge-graph/src/knowledge_graph/domain/models.py`
- `services/knowledge-graph/tests/unit/domain/test_temporal_events.py`
- `services/knowledge-graph/tests/unit/domain/test_enums.py`

---

### Wave B-1: S7 — FundamentalsConsumer Metadata Enrichment ✅

**Status**: **DONE** — 2026-04-08 · 327 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] Extract `General.FullTimeEmployees` → `entity.metadata["employee_count"]`
- [x] Extract `Highlights.RevenueTTM` → `entity.metadata["revenue_ttm_usd"]`
- [x] Extract `SharesStats.PercentInsiders` → `entity.metadata["pct_insiders"]`
- [x] Extract `SharesStats.PercentInstitutions` → `entity.metadata["pct_institutions"]`
- [x] `EntityRepository.update_metadata()` method (partial patch — merge, not replace)
- [x] Idempotency: same payload twice → same metadata, no re-emit of `entity.dirtied.v1`
- [x] Unit tests: happy path, missing fields, idempotent re-processing

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (89 source files, 0 issues)
- [x] Unit tests pass: 327 tests, 0 failures (14 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: A-1
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/fundamentals_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_repository.py`
- `services/knowledge-graph/tests/unit/infrastructure/consumer/test_fundamentals_consumer.py`

---

### Wave B-2: S7 — Worker 13D-6 EODHD Economic Events Ingestion ✅

**Status**: **DONE** — 2026-04-08 · 359 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `EconomicEventsWorker` class (APScheduler daily 06:00 UTC)
- [x] EODHD client method: `get_economic_events(country, from_date)` (new `infrastructure/eodhd/client.py`)
- [x] Processing: skip `actual=null` events; compute surprise magnitude
- [x] `TemporalEventRepository.upsert_by_natural_key()` (idempotent by `(event_type, region, title, active_from::date)`)
- [x] Link to country canonical entity via `entity_event_exposures`
- [x] Config: `KNOWLEDGE_GRAPH_ECONOMIC_EVENT_COUNTRIES` (default: `US,DE,GB,JP,CN,EU`); `KNOWLEDGE_GRAPH_EODHD_API_KEY`; `KNOWLEDGE_GRAPH_EODHD_BASE_URL`
- [x] Prometheus metrics: `s7_economic_events_ingested_total{country}`
- [x] `EntityRepository.find_country_entity(iso2)` — lookup by `metadata->>'country_iso'`
- [x] Unit tests: 10 tests — happy path (title/description/active_until), skips unreleased (null actual), mixed released/unreleased, empty list, deduplication idempotency, no country entity, Prometheus counter

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (6 source files checked, 0 issues)
- [x] Unit tests pass: 359 tests, 0 failures (10 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: A-1, C-1 (TemporalEventRepository)
**Estimated effort**: 4h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/__init__.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/eodhd/client.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/economic_events_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_economic_events_worker.py`

---

### Wave B-3: S7 — Worker 13D-7 EODHD Macro Indicator Enrichment ✅

**Status**: **DONE** — 2026-04-08 · 375 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `MacroIndicatorWorker` class (APScheduler weekly Sunday 03:00 UTC)
- [x] EODHD client method: `get_macro_indicator(iso3_country, indicator_code)` (already in client from B-2)
- [x] 6 indicators: gdp_current_usd, gdp_growth_annual, inflation_consumer_prices_annual, real_interest_rate, unemployment_total_pct, current_account_balance_bop_usd
- [x] JSON hash comparison to detect changes; skip re-embed if unchanged
- [x] Produce `entity.dirtied.v1` when indicators change
- [x] ISO 3166-1 alpha-3 → alpha-2 country code mapping (constructor `country_map: dict[str, str]`)
- [x] `EntityRepository.get_metadata_hash()` — SHA-256 of stored `metadata[key]` JSONB value
- [x] Prometheus metric: `s7_macro_indicator_updates_total{country}`
- [x] Config: `KNOWLEDGE_GRAPH_MACRO_INDICATOR_COUNTRIES` (default: `USA,GBR,DEU,JPN,CHN`)
- [x] Unit tests: 16 tests — update on change, no update on same hash, missing country entity, empty response, partial indicators, no producer, Prometheus counter, _sha256_hex helper

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (95 source files, 0 issues)
- [x] Unit tests pass: 375 tests, 0 failures (16 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: A-1, B-1 (update_metadata pattern established)
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/macro_indicator_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_macro_indicator_worker.py`

---

### Wave B-4: S7 — Worker 13D-8 EODHD Insider Transactions → has_executive Relations ✅

**Status**: **DONE** — 2026-04-09 · 447 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `InsiderTransactionsWorker` class (APScheduler weekly Monday 02:00 UTC)
- [x] EODHD client method: `get_insider_transactions(code, limit)` (already in client from B-2)
- [x] `is_executive_title()` whitelist filter (CEO/CFO/COO/CTO/Director/President/Chairman/VP/General Counsel/10% Owner)
- [x] `EntityRepository.find_or_create_person(name, context_ticker)` — person entity upsert
- [x] `EntityRepository.list_us_instruments()` — filter on exchange US
- [x] `RelationRepository.upsert_relation()` convenience wrapper for `has_executive` (RELATION_STATE, DURABLE, decay_alpha=0.000950)
- [x] Evidence text with transaction direction (insider sentiment)
- [x] Prometheus metrics: `s7_insider_transactions_relations_total{ticker}`, `s7_insider_transactions_skipped_total{reason}`
- [x] Unit tests: 43 new tests — CEO creates relation, VP Sales filtered, same officer deduplicates, direction bought/sold, no name skipped, empty transactions, no US instruments, Prometheus counters, `is_executive_title()` edge cases

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (98 source files, 0 issues)
- [x] Unit tests pass: 447 tests, 0 failures (43 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: A-1
**Estimated effort**: 4h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/insider_transactions_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_insider_transactions_worker.py`

---

### Wave C-1: S7 — TemporalEventRepository + Domain Ports ✅

**Status**: **DONE** — 2026-04-08 · 349 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `TemporalEventRepositoryPort` interface (application layer)
- [x] `TemporalEventRepository` impl (infrastructure layer — SQLAlchemy)
- [x] `upsert_by_natural_key(...)` — idempotent ON CONFLICT DO UPDATE (natural key: event_type, region, title, date_trunc('day', active_from))
- [x] `list_active(scope, entity_id, event_type, region, from_date, to_date, limit, offset)` — dynamic query builder; EXISTS subquery for entity_id; COUNT(*) OVER() for total
- [x] `EntityEventExposureRepositoryPort` + `EntityEventExposureRepository` impl
- [x] `ExposureRepository.upsert(...)` — ON CONFLICT (event_id, entity_id, exposure_type) DO NOTHING
- [x] Unit tests: 24 tests — upsert roundtrip, conflict SQL, all filter combos, pagination, empty result, exposure idempotency

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (91 source files, 0 issues)
- [x] Unit tests pass: 349 tests, 0 failures (24 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: A-1
**Estimated effort**: 4h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/application/ports/temporal_event_repository.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/temporal_event_repository.py`
- `services/knowledge-graph/tests/unit/infrastructure/test_temporal_event_repository.py`

---

### Wave C-2: S7 — TemporalEventConsumer ✅

**Status**: **DONE** — 2026-04-08 · 404 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `TemporalEventConsumer` (Kafka consumer for `intelligence.temporal_event.v1`)
- [x] Avro deserialisation → `TemporalEvent` domain model
- [x] Convert `region=""` → `None` (per PRD §6.5 Avro contract)
- [x] Upsert `temporal_events` via `TemporalEventRepository`
- [x] Create `entity_event_exposures` rows from `exposed_entities[]` (scope-tiered)
- [x] GLOBAL scope: link to sector/industry entities only (not companies)
- [x] DLQ for consumer failures
- [x] Unit tests: Avro message → DB rows, GLOBAL scope sector-only linking, region empty-string → None

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (96 source files, 0 issues)
- [x] Unit tests pass: 404 tests, 0 failures (27 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: C-1
**Estimated effort**: 4h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/temporal_event_consumer.py`
- `services/knowledge-graph/tests/unit/infrastructure/consumer/test_temporal_event_consumer.py`

---

### Wave D-1: S7 — AgeSyncWorker (Worker 13F) ✅

**Status**: **DONE** — 2026-04-08 · 423 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `AgeSyncWorker` class (APScheduler every 15 min)
- [x] `_setup_age_session()` — `LOAD 'age'` + `SET search_path = ag_catalog, public`
- [x] `_sync_entities(since)` — watermark-based `MERGE Entity` vertices (paginated, 1000 per batch)
- [x] `_sync_relations(since)` — watermark-based `MERGE relation edges` (paginated, 5000 per batch); confidence > 0.1 filter
- [x] `_sync_temporal_events(since)` — `MERGE TemporalEvent` vertices + `EVENT_EXPOSES` edges
- [x] Valkey watermark: `s7:age:sync:watermark` (ISO-8601 UTC; default epoch)
- [x] Prometheus metrics: `s7_age_sync_entities_total`, `s7_age_sync_relations_total`, `s7_age_sync_duration_seconds`
- [x] `KNOWLEDGE_GRAPH_CYPHER_ENABLED` feature flag check before each run
- [x] Unit tests: watermark update after run, entities synced, relation edge label derivation, sync skipped when disabled

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (97 source files, 0 issues)
- [x] Unit tests pass: 423 tests, 0 failures (19 new tests added)
- [ ] Integration tests (requires live intelligence_db with AGE extension)

**Depends on**: A-1, C-1
**Estimated effort**: 5h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/metrics/prometheus.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler_main.py`
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/tests/unit/infrastructure/workers/test_age_sync_worker.py`

---

### Wave E-1: S7 — GET /api/v1/temporal-events Endpoint ✅

**Status**: **DONE** — 2026-04-09 · 468 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `ListTemporalEventsUseCase` (read-only use case, `ReadOnlyUnitOfWork`)
- [x] `TemporalEventResponse` Pydantic schema with `lifecycle_phase` computed field
- [x] `GET /api/v1/temporal-events` route with all query params from PRD §6.3
- [x] Pagination: `limit` (1–200) + `offset` response with `total` count
- [x] `exposed_entity_count` from `COUNT(entity_event_exposures)` per event
- [x] Unit tests: all filter combinations, pagination, empty result (19 new tests)
- [x] Architecture test: route uses ReadUoWDep only (verified via fixture pattern)

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (100 source files, 0 issues)
- [x] Unit tests pass: 468 tests, 0 failures (19 new tests added)
- [ ] Integration tests (requires live intelligence_db)

**Depends on**: C-1
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/list_temporal_events.py`
- `services/knowledge-graph/src/knowledge_graph/api/temporal_events.py`
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py`
- `services/knowledge-graph/src/knowledge_graph/api/dependencies.py`
- `services/knowledge-graph/src/knowledge_graph/app.py`
- `services/knowledge-graph/tests/unit/api/test_temporal_events_route.py`
- `services/knowledge-graph/tests/unit/application/test_list_temporal_events.py`

---

### Wave E-2: S7 — POST /api/v1/graph/cypher/path + neighborhood Endpoints

**Status**: pending

**Tasks**:
- [ ] `CypherPathUseCase` — validate entities, execute AGE shortestPath query, parse path result
- [ ] `CypherNeighborhoodUseCase` — egocentric neighborhood via AGE Cypher
- [ ] AGE session setup (LOAD + SET search_path) per request
- [ ] `POST /api/v1/graph/cypher/path` route (PRD §6.3)
- [ ] `POST /api/v1/graph/cypher/neighborhood` route (PRD §6.3)
- [ ] 503 response when `KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`
- [ ] 504 response on AGE timeout (5s `statement_timeout`)
- [ ] Parameterized `$entity_id` — never string-interpolated (security)
- [ ] Unit tests: disabled feature flag → 503, parameterized query construction, timeout → 504

**Depends on**: D-1
**Estimated effort**: 5h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/cypher_path.py`
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/cypher_neighborhood.py`
- `services/knowledge-graph/src/knowledge_graph/api/v1/cypher.py`
- `services/knowledge-graph/tests/unit/api/test_cypher_route.py`
- `services/knowledge-graph/tests/unit/application/test_cypher_use_cases.py`

---

### Wave F-1: S6 Block 13E Temporal Event Detection + S8 Integration

**Status**: pending

**Tasks**:
- [ ] S6 `EnrichedArticleConsumer`: Block 13E — call `extract_temporal_event()` for DEEP-tier articles
- [ ] `extract_temporal_event()` uses Qwen2.5:3b via `ml-clients`; skip if model unavailable
- [ ] Produce `intelligence.temporal_event.v1` if confidence ≥ 0.5
- [ ] S8 `QueryPipeline`: RELATIONSHIP intent → Cypher path when `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`
- [ ] S8: `SIGNAL_INTEL` intent → inject active temporal events into LLM context
- [ ] Global event query-time filtering: match `entity.metadata["country_iso"]` to event `region`
- [ ] S8 new config: `KNOWLEDGE_GRAPH_CYPHER_ENABLED` (default: `false`)
- [ ] Unit tests: S6 event detection confidence filter, S8 Cypher fallback on 503/disabled

**Depends on**: E-2, C-2
**Estimated effort**: 5h
**Files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/enriched_article_consumer.py`
- `services/chat/src/chat/infrastructure/adapters/knowledge_graph_client.py`
- `services/chat/src/chat/application/pipeline/query_pipeline.py`
- `services/nlp-pipeline/tests/unit/test_temporal_event_detection.py`
- `services/chat/tests/unit/test_cypher_integration.py`

---

## Regression Guardrails

- BP-112: `claim_batch` lease expiry — not affected by this plan
- BP-124: consumer idempotency check — `TemporalEventConsumer` must use `event_id` dedup via `is_duplicate()` before processing
- Avro forward-compatibility: `intelligence.temporal_event.v1` has all fields with defaults (except `event_id`, `event_type`, `scope`, `title`, `confidence`, `occurred_at`) — new fields MUST have defaults in future versions
- AGE session setup: every DB session issuing AGE Cypher MUST call `LOAD 'age'` + `SET search_path = ag_catalog, public` before Cypher calls (enforced in `AgeSyncWorker._setup_age_session()` and `CypherPathUseCase`)
