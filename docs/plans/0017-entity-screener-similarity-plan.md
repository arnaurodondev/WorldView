---
id: PLAN-0017
title: Entity Screener + Similarity Search + Embedding View Fix + EODHD Description LLM
prd: docs/specs/0017-entity-screener-similarity.md
status: in-progress
created: 2026-04-04
updated: 2026-04-07
total_waves: 11
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

### Wave A-2: S7 — Fix `ensure_rows_exist()` entity type awareness

**Status**: pending

**Tasks**:
- [ ] Add `get_view_types_for_entity_type(entity_type: str) -> tuple[str, ...]` helper
- [ ] `COMPANY_ENTITY_TYPES = frozenset({"financial_instrument"})`
- [ ] Update `ensure_rows_exist(entity_id, entity_type)` — new signature requires `entity_type`
- [ ] Update callers: `instrument_consumer_main.py`, `provisional_enrichment.py`
- [ ] Unit tests: `test_ensure_rows_exist_company`, `test_ensure_rows_exist_non_company`, `test_ensure_rows_exist_all_entity_types`

**Depends on**: A-1 (data cleanup must run before fix is deployed)
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/embedding_state.py` (or wherever `ensure_rows_exist` lives)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/instrument_consumer_main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py`
- `services/knowledge-graph/tests/unit/`

---

### Wave A-3: libs/ml-clients — `EntityDescriptionClient` Protocol + adapters

**Status**: pending

**Tasks**:
- [ ] Add `EntityDescriptionClient` Protocol to `libs/ml-clients/src/ml_clients/`
- [ ] Implement `GeminiDescriptionAdapter` (gemini-3.1-flash-lite via Google AI Studio)
- [ ] Implement `NullDescriptionAdapter` (always returns None; for test/dev)
- [ ] Cost tracking: Valkey counter `s7:desc:cost:{YYYY-MM}`; check cap before API call
- [ ] Unit tests: `test_description_client_cost_cap`, `test_description_client_null_adapter`

**Depends on**: none (parallel with A-2)
**Estimated effort**: 4h
**Files**:
- `libs/ml-clients/src/ml_clients/description_client.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`
- `libs/ml-clients/src/ml_clients/adapters/null_description.py`
- `libs/ml-clients/tests/unit/test_description_client.py`

---

### Wave A-4: S7 — `DefinitionRefreshWorker` non-company description enhancement

**Status**: pending

**Tasks**:
- [ ] Update `DefinitionRefreshWorker.__init__` — add `description_client: EntityDescriptionClient` param
- [ ] Detect `entity_type != 'financial_instrument'` → call `generate_description()`
- [ ] Fallback to deterministic template when client returns None
- [ ] Scheduler wiring: inject `GeminiDescriptionAdapter` (prod) or `NullDescriptionAdapter` (dev)
- [ ] Add env vars: `KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER`, `KNOWLEDGE_GRAPH_GEMINI_API_KEY`, `KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD`
- [ ] Unit test: `test_description_fallback_on_none`

**Depends on**: A-2 (ensure_rows_exist fix), A-3 (EntityDescriptionClient)
**Estimated effort**: 3h
**Files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/email/scheduler.py` (or equivalent worker scheduler)
- `services/knowledge-graph/configs/dev.local.env.example`
- `services/knowledge-graph/tests/unit/infrastructure/test_definition_refresh.py`

---

### Wave B-1: S3 — Enhanced screener response + sort + total + `screen_field_metadata` table

**Status**: pending

**Tasks**:
- [ ] Add `ScreenFieldMetadata` domain object (12 static fields)
- [ ] Extend `ScreenInstrumentResponse` with `ticker`, `name`, `exchange`, `sector`
- [ ] Add `sort_by`, `sort_order`, `total` to request/response (`COUNT(*) OVER()` window function)
- [ ] Tighten limit: max 200, default 50; offset max 5000
- [ ] Alembic migration: `screen_field_metadata` table in `market_data_db`
- [ ] Unit tests: `test_screen_response_includes_instrument_fields`, `test_screen_sort_by_ticker`, `test_screen_sort_by_metric_nulls_last`, `test_screen_total_count`, `test_screen_sort_by_invalid_field`

**Depends on**: none (parallel with A waves)
**Estimated effort**: 4h

---

### Wave B-2: S3 — `GET /screen/fields` endpoint + Valkey cache + APScheduler job

**Status**: pending

**Tasks**:
- [ ] `ScreenFieldsMetadataUseCase` — reads from Valkey (`s3:screen:fields:v1`), fallback DB
- [ ] `GET /api/v1/fundamentals/screen/fields` route (no auth, public)
- [ ] APScheduler job refreshes Valkey every 6 hours
- [ ] `screen_field_metadata` seeded with 12 static field definitions
- [ ] Unit test: `test_screen_field_metadata_static`

**Depends on**: B-1 (table + domain object)
**Estimated effort**: 3h

---

### Wave B-3: S7 — `EntityEmbeddingANNRepository` + pgvector ANN query

**Status**: pending

**Tasks**:
- [ ] Add `EntityEmbeddingANNRepositoryPort` ABC to application ports
- [ ] `AnnResult` dataclass: `entity_id: UUID, distance: float`
- [ ] Implement `SqlalchemyEntityEmbeddingANNRepository` — pgvector `<=>` cosine distance
- [ ] JOIN on `canonical_entities` to filter by `entity_types`
- [ ] Unit tests: `test_similar_entities_no_embedding`, `test_similar_entities_not_found`

**Depends on**: A-2 (ensure_rows_exist fix deployed)
**Estimated effort**: 3h

---

### Wave B-4: S7 — `FindSimilarEntitiesUseCase` + `POST /api/v1/entities/similar` endpoint

**Status**: pending

**Tasks**:
- [ ] `FindSimilarEntitiesUseCase.execute()` — ANN + competes_with boost algorithm (PRD §6.5)
- [ ] `find_competes_with_batch()` — batch bidirectional relation query
- [ ] `POST /api/v1/entities/similar` route — ReadUoWDep (R27), 404/422/503 errors
- [ ] Unit tests: `test_similar_entities_final_score_with_boost`, `test_similar_entities_final_score_cap`

**Depends on**: B-3 (ANN repository port)
**Estimated effort**: 4h

---

### Wave C-1: S9 — Proxy new S3 + S7 endpoints

**Status**: pending

**Tasks**:
- [ ] `POST /api/v1/fundamentals/screen` — update existing proxy (new request/response shape)
- [ ] `GET /api/v1/fundamentals/screen/fields` — new proxy (no auth)
- [ ] `GET /api/v1/fundamentals/timeseries` — new proxy (not currently routed through S9)
- [ ] `POST /api/v1/entities/similar` — new proxy (X-Tenant-ID auth)
- [ ] Follow S9 typed-handler pattern: `clients.py` + `routes/proxy.py`

**Depends on**: B-1 (screener contract), B-4 (similar entities endpoint)
**Estimated effort**: 2h

---

### Wave C-2: Frontend — `ScreenerPage` component

**Status**: pending

**Tasks**:
- [ ] `apps/frontend/src/pages/ScreenerPage.tsx`
- [ ] Dynamic filter form built from `GET /screen/fields` response
- [ ] Results table: Ticker, Name, Exchange, Sector, + active filter metric columns; sortable
- [ ] Pagination: page size selector (25/50/100), prev/next
- [ ] CSV export (client-side)
- [ ] Route: `/screener`

**Depends on**: C-1 (S9 proxy)
**Estimated effort**: 6h

---

### Wave C-3: Frontend — `SimilarCompaniesPanel` component

**Status**: pending

**Tasks**:
- [ ] `apps/frontend/src/components/SimilarCompaniesPanel.tsx`
- [ ] Placement: `CompanyDetailPage` — collapsible card below graph neighborhood section
- [ ] Top-10 list: ticker badge, company name, final_score bar, competitor badge
- [ ] Empty state + loading skeleton
- [ ] "View all (N)" modal with top_k=50

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
