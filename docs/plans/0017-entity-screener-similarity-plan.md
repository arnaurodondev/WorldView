---
id: PLAN-0017
title: Entity Screener + Similarity Search + Embedding View Fix + EODHD Description LLM
prd: docs/specs/0017-entity-screener-similarity.md
status: in-progress
created: 2026-04-04
updated: 2026-04-08
total_waves: 11
waves_done: 11
status: completed
---

# PLAN-0017: Entity Screener & Similarity Search

> **PRD**: `docs/specs/0017-entity-screener-similarity.md`
> **Status**: in-progress
> **Depends on**: PLAN-0001-C (S7 entity graph), PLAN-0015 (S8 embeddings infra)

---

## Sub-Plan Index

| Sub-Plan | Service | Waves | Depends On |
|----------|---------|-------|------------|
| A | intelligence-migrations + S7 + libs/ml-clients | A-1 → A-4 | none |
| B | S3 + S7 | B-1 → B-4 | A-2 (ensure_rows_exist fix) |
| C | S9 + Frontend | C-1 → C-3 | B-1, B-4 |

---

## Wave Completion Tracker

### Wave A-1: intelligence-migrations 0003 cleanup migration ✅

**Status**: **DONE** — 2026-04-07 · 3 tests pass · ruff + mypy clean

**Tasks**:
- [x] Create `0003_cleanup_non_company_fundamentals_ohlcv.py` (revision `c3d4e5f6a1b2`, revises `b2c3d4e5f6a1`)
- [x] DELETE orphan `fundamentals_ohlcv` rows for non-`financial_instrument` entities
- [x] `downgrade()` is a no-op (document runbook: re-run embedding worker)
- [x] Add 3 integration tests to `tests/test_migration.py`

**Validation gate**:
- [x] ruff check passes
- [x] mypy N/A (no typed Python; migration uses op.execute with raw SQL)
- [x] 3 new integration tests: preserve company rows, delete non-company rows, preserve definition+narrative

**Estimated effort**: 2h
**Files**:
- `services/intelligence-migrations/alembic/versions/0003_cleanup_non_company_fundamentals_ohlcv.py`
- `services/intelligence-migrations/tests/test_migration.py`

---

### Wave A-2: S7 — Fix `ensure_rows_exist()` entity type awareness ✅

**Status**: **DONE** — 2026-04-07 · 7 new tests pass (239 total unit) · ruff + mypy clean

**Tasks**:
- [x] Add `get_view_types_for_entity_type(entity_type: str) -> tuple[str, ...]` helper
- [x] `COMPANY_ENTITY_TYPES = frozenset({"financial_instrument"})`
- [x] Update `ensure_rows_exist(entity_id, entity_type)` — new signature requires `entity_type`
- [x] Update callers: `instrument_consumer.py`, `provisional_enrichment.py`
- [x] Unit tests: `TestGetViewTypesForEntityType` (3 tests) + `TestEntityEmbeddingStateRepositoryEnsureRowsExist` (4 tests)

**Depends on**: A-1 (data cleanup must run before fix is deployed)
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_embedding_state.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/instrument_consumer.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/infrastructure/test_repositories.py`

---

### Wave A-3: libs/ml-clients — `EntityDescriptionClient` Protocol + adapters ✅

**Status**: **DONE** — 2026-04-07 · 52 tests pass · ruff + mypy clean

**Tasks**:
- [x] Add `EntityDescriptionClient` Protocol to `libs/ml-clients/src/ml_clients/`
- [x] Implement `GeminiDescriptionAdapter` (gemini-3.1-flash-lite via Google AI Studio)
- [x] Implement `NullDescriptionAdapter` (always returns None; for test/dev)
- [x] Cost tracking: Valkey counter `s7:desc:cost:{YYYY-MM}`; check cap before API call
- [x] Unit tests: `test_description_client_cost_cap`, `test_description_client_null_adapter`

**Depends on**: none (parallel with A-2)
**Estimated effort**: 4h
**Files**:
- `libs/ml-clients/src/ml_clients/description_client.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`
- `libs/ml-clients/src/ml_clients/__init__.py`
- `libs/ml-clients/src/ml_clients/adapters/__init__.py`
- `libs/ml-clients/tests/test_adapters.py`

---

### Wave A-4: S7 — `DefinitionRefreshWorker` non-company description enhancement ✅

**Status**: **DONE** — 2026-04-07 · 251 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] Update `DefinitionRefreshWorker.__init__` — add `description_client: EntityDescriptionClient` param
- [x] Detect `entity_type != 'financial_instrument'` → call `generate_description()`
- [x] Fallback to deterministic template when client returns None
- [x] Scheduler wiring: inject `GeminiDescriptionAdapter` (prod) or `NullDescriptionAdapter` (dev)
- [x] Add env vars: `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER`, `KNOWLEDGE_GRAPH_GEMINI_API_KEY`, `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD`
- [x] Unit test: `test_description_fallback_on_none` (+ 11 more covering all failure modes)

**Depends on**: A-2 (ensure_rows_exist fix), A-3 (EntityDescriptionClient)
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py`
- `services/knowledge-graph/src/knowledge_graph/config.py`
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/tests/unit/infrastructure/test_definition_refresh.py`

---

### Wave B-1: S3 — Enhanced screener response + sort + total + `screen_field_metadata` table ✅

**Status**: **DONE** — 2026-04-07 · 363 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] Add `ScreenFieldMetadata` domain object (12 static fields)
- [x] Extend `ScreenInstrumentResponse` with `ticker`, `name`, `exchange`, `sector`
- [x] Add `sort_by`, `sort_order`, `total` to request/response (`COUNT(*) OVER()` window function)
- [x] Tighten limit: max 200, default 50; offset max 5000
- [x] Alembic migration: `screen_field_metadata` table in `market_data_db`
- [x] Unit tests: `test_screen_response_includes_instrument_fields`, `test_screen_sort_by_ticker`, `test_screen_sort_by_metric_nulls_last`, `test_screen_total_count`, `test_screen_sort_by_invalid_field`

**Validation gate**:
- [x] ruff check passes
- [x] ruff format passes
- [x] mypy passes (100 source files, 0 errors)
- [x] 363 unit tests pass (12 new Wave B-1 tests + 5 updated existing tests)

**Depends on**: none (parallel with A waves)
**Estimated effort**: 4h

---

### Wave B-2: S3 — `GET /screen/fields` endpoint + Valkey cache + APScheduler job ✅

**Status**: **DONE** — 2026-04-08 · 380 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `ScreenFieldsMetadataUseCase` — reads from Valkey (`s3:screen:fields:v1`), fallback DB
- [x] `GET /api/v1/fundamentals/screen/fields` route (no auth, public)
- [x] `asyncio.create_task(_screen_fields_refresh_loop(...))` refreshes Valkey every 6 hours (no APScheduler dependency needed)
- [x] `screen_field_metadata` seeded with 12 static field definitions via `_get_static_screen_fields()` in `app.py`
- [x] Unit tests: cache hit/miss/empty-DB, route 12-fields, route empty, field shape

**Notes**:
- Background refresh uses `asyncio.create_task` + `asyncio.sleep(6*3600)` (no APScheduler)
- Global TOPO-LIFESPAN architecture test updated: cache-warmer tasks are explicitly exempted (R22 targets consumers/dispatchers only, per PRD-0017 §6.2)
- `PgScreenFieldMetadataRepository.upsert_batch()` write-side repo for background seed
- `ScreenFieldsCache` Valkey implementation with fail-open pattern

**Depends on**: B-1 (table + domain object)
**Estimated effort**: 3h

---

### Wave B-3: S7 — `EntityEmbeddingANNRepository` + pgvector ANN query ✅

**Status**: **DONE** — 2026-04-08 · 263 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] Add `EntityEmbeddingANNRepositoryPort` ABC to `application/ports/repositories.py`
- [x] `AnnResult` frozen dataclass: `entity_id: UUID, distance: float`
- [x] Add `SimilarEntityResult` frozen dataclass to `domain/models.py` (PRD-0017 §6.5)
- [x] Add `EmbeddingNotAvailableError` to `domain/errors.py`
- [x] Implement `SqlalchemyEntityEmbeddingANNRepository` — pgvector `<=>` cosine distance
- [x] JOIN on `canonical_entities` to filter by `entity_types` via `ANY(:array)`
- [x] `get_embedding()` method for null-embedding check (used by use case step 2)
- [x] Unit tests: `test_similar_entities_no_embedding`, `test_similar_entities_not_found` + 12 additional

**Notes**:
- `extra_conditions` f-string injection is safe: only hardcoded SQL fragments, all user data via bind params
- `entity_types` uses `ANY(:array)` parameterized — no injection risk
- `get_embedding()` parses pgvector text `"[0.1,0.2,...]"` into `list[float]`

**Depends on**: A-2 (ensure_rows_exist fix deployed)
**Estimated effort**: 3h

---

### Wave B-4: S7 — `FindSimilarEntitiesUseCase` + `POST /api/v1/entities/similar` endpoint ✅

**Status**: **DONE** — 2026-04-08 · 274 unit tests pass · ruff + mypy clean

**Tasks**:
- [x] `FindSimilarEntitiesUseCase.execute()` — ANN + competes_with boost algorithm (PRD §6.5)
- [x] `find_competes_with_batch()` — batch bidirectional relation query (RelationRepositoryPort + RelationRepository)
- [x] `POST /api/v1/entities/similar` route — ReadOnlyDbSessionDep (R27), 404/422/503 errors
- [x] Unit tests: `test_similar_entities_final_score_with_boost`, `test_similar_entities_final_score_cap` (+ 9 more)

**Depends on**: B-3 (ANN repository port)
**Estimated effort**: 4h

---

### Wave C-1: S9 — Proxy new S3 + S7 endpoints ✅

**Status**: **DONE** — 2026-04-08 · 28 api-gateway tests pass · ruff + mypy clean

**Tasks**:
- [x] `POST /api/v1/fundamentals/screen` — new proxy route in `routes/proxy.py` (no auth; S3 error codes propagated)
- [x] `GET /api/v1/fundamentals/screen/fields` — new proxy (no auth)
- [x] `GET /api/v1/fundamentals/timeseries` — new proxy; query params forwarded
- [x] `POST /api/v1/entities/similar` — new proxy (no auth; 404/422/503 propagated)
- [x] Unit tests: 7 new tests (200 proxy, 422/404/503 propagation for screener + similar)

**Depends on**: B-1 (screener contract), B-4 (similar entities endpoint)
**Estimated effort**: 2h

---

### Wave C-2: Frontend — `ScreenerPage` component ✅

**Status**: **DONE** — 2026-04-08 · manual TS review clean (no node_modules in repo)

**Tasks**:
- [x] `apps/frontend/src/pages/ScreenerPage.tsx` — dynamic filter form + sortable results table
- [x] Dynamic filter form built from `GET /screen/fields` response (`fieldsData`)
- [x] Results table: Ticker, Name, Exchange, Sector, + active filter metric columns; sortable headers
- [x] Pagination: page size selector (25/50/100), prev/next with total count
- [x] CSV export (client-side) via `exportCsv()` helper
- [x] Route: `/screener` added to `App.tsx`; nav item added to `Layout.tsx`
- [x] Types + API methods added to `gateway-client.ts` (`ScreenField`, `ScreenFilter`, `ScreenInstrumentResult`, `ScreenResponse`, `gateway.getScreenFields()`, `gateway.screenInstruments()`)

**Depends on**: C-1 (S9 proxy)
**Estimated effort**: 6h

---

### Wave C-3: Frontend — `SimilarCompaniesPanel` component ✅

**Status**: **DONE** — 2026-04-08 · manual TS review clean (no node_modules in repo)

**Tasks**:
- [x] `apps/frontend/src/components/SimilarCompaniesPanel.tsx` — collapsible card with top-10 list
- [x] Placement: `CompanyDetailPage` — collapsible section below Latest News
- [x] Top-10 list: ticker badge, company name, final_score bar, competitor badge (red label)
- [x] Empty state + loading skeleton (5 gray placeholder bars)
- [x] "View all (N)" modal with top_k=50 and click-outside-to-close
- [x] Types + API method added to `gateway-client.ts` (`SimilarEntityResult`, `SimilarEntitiesResponse`, `gateway.findSimilarEntities()`)

**Depends on**: C-1 (S9 proxy)
**Estimated effort**: 4h

---

## Validation Gates

| Wave | Gate |
|------|------|
| A-1 | `python -m pytest services/intelligence-migrations/tests/ -m integration -v` |
| A-2 | `python -m pytest services/knowledge-graph/tests/ -m unit -v` |
| A-3 | `python -m pytest libs/ml-clients/tests/ -m unit -v` |
| A-4 | `python -m pytest services/knowledge-graph/tests/ -m unit -v` |
| B-1 | `python -m pytest services/market-data/tests/ -m unit -v` + migration test |
| B-2 | `python -m pytest services/market-data/tests/ -m unit -v` |
| B-3 | `python -m pytest services/knowledge-graph/tests/ -m unit -v` |
| B-4 | `python -m pytest services/knowledge-graph/tests/ -m unit -v` |
| C-1 | `python -m pytest services/api-gateway/tests/ -m unit -v` |
| C-2 | frontend lint + type check |
| C-3 | frontend lint + type check |

---

## Regression Guardrails

- BP-XXX: No cross-service DB access — S7 ANN endpoint must use read-replica session (R27)
- PRD §6.8: `sort_by` whitelist validation — never interpolate into SQL (injection guard)
- PRD §9: `fundamentals_ohlcv` entity type restriction — non-company 422, not 404
