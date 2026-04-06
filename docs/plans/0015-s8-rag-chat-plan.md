# PLAN-0015: S8 RAG/Chat Hybrid Intelligence Pipeline

> **PRD**: `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md`
> **Status**: in-progress
> **Created**: 2026-04-02
> **Updated**: 2026-04-06
> **Sub-plans**: 7 (A–G)
> **Total waves**: 22
> **Total estimated effort**: 12–20 agent-hours
> **Critical path**: A-1 → B-1 → B-2 → B-3 → (C-1, C-3 parallel) → D-1 → D-2 → D-3 → D-4 → E-1 → E-2 → E-3 → F-1 → F-2 → F-3 → F-4 → G-1

---

## Sub-Plan Index

| Sub-Plan | Service | Waves | Phase | Depends On |
|----------|---------|-------|-------|------------|
| PLAN-0015-A | intelligence-migrations + S5 + S1 | 3 | Phase 1 | none |
| PLAN-0015-B | S6 NLP Pipeline | 3 | Phase 1 | A-1 (schema) |
| PLAN-0015-C | S7 Knowledge Graph | 4 | Phase 1+3 | A-1 (for C-2,C-4) |
| PLAN-0015-D | S8 RAG/Chat scaffold | 4 | Phase 2 | A, B, C-1, C-2 |
| PLAN-0015-E | S8 pipeline (early) | 3 | Phase 2 | D |
| PLAN-0015-F | S8 pipeline (late) | 4 | Phase 2 | E |
| PLAN-0015-G | S9 + docs | 1 | Phase 3 | F |

---

## Dependency Graph

```
Phase 1 (all parallelizable after A-1):
  A-1 (intelligence-migrations 0002+003) ──→ C-2 (events/search uses new columns)
                                         ──→ C-4 (FundamentalsWorker writes to new columns)
  A-2 (S5 batch endpoint) ──────────────────────┐
  A-3 (S1 portfolio context) ──────────────────→│
  B-1 (S6 document_source_metadata) ───────────→│→ Phase 2 (S8 core)
  B-2 (S6 entity resolve) ─────────────────────→│
  B-3 (S6 enhanced chunk search) ──────────────→│
  C-1 (S7 claims + contradictions) ────────────→│
  C-3 (S7 relation ANN search) ────────────────→│
  C-2 (S7 events/search) ──────────────────────→│

Phase 2 (sequential within S8):
  D-1 (domain) → D-2 (rag_db) → D-3 (scaffold) → D-4 (conversation CRUD)
  → E-1 (input validation) → E-2 (intent + HyDE) → E-3 (service clients)
  → F-1 (parallel retrieval) → F-2 (rerank + context) → F-3 (LLM chain)
  → F-4 (chat endpoints + persistence)

Phase 3:
  F-4 → G-1 (S9 routing + docs)
  C-4 (FundamentalsWorker enhancements) runs parallel with Phase 2

Phase 4 (deferred — not in this plan):
  S7 Cypher endpoint + S8 Cypher integration → PLAN-0015-H (future, after Block 14 stable)
```

---

## Wave Completion Tracker

| Wave | Title | Status | Validated |
|------|-------|--------|-----------|
| A-1 | intelligence-migrations 0002 + 003 seed | ✅ done | 2026-04-05 |
| A-2 | S5 batch documents endpoint | ✅ done | 2026-04-05 |
| A-3 | S1 portfolio context endpoint | ✅ done | 2026-04-05 |
| B-1 | S6 document_source_metadata | ✅ done | 2026-04-05 |
| B-2 | S6 entity resolve endpoint | ✅ done | 2026-04-05 |
| B-3 | S6 enhanced chunk search | ✅ done | 2026-04-06 |
| C-1 | S7 claims/search + contradictions | ✅ done | 2026-04-06 |
| C-2 | S7 events/search | pending | — |
| C-3 | S7 relation ANN search | pending | — |
| C-4 | S7 FundamentalsWorker enhancements | pending | — |
| D-1 | S8 domain layer | pending | — |
| D-2 | S8 rag_db infrastructure | pending | — |
| D-3 | S8 service scaffold + config | pending | — |
| D-4 | S8 conversation management CRUD | pending | — |
| E-1 | S8 input validation + rate limiting | pending | — |
| E-2 | S8 intent classifier + HyDE | pending | — |
| E-3 | S8 upstream service clients | pending | — |
| F-1 | S8 parallel retrieval + fusion | pending | — |
| F-2 | S8 reranking + context assembly | pending | — |
| F-3 | S8 LLM provider chain + streaming | pending | — |
| F-4 | S8 chat endpoints + persistence | pending | — |
| G-1 | S9 routing + documentation | pending | — |

---

## PLAN-0015-A: Phase 1 Prerequisites

**Services**: intelligence-migrations, S5 Content Store, S1 Portfolio
**Rationale**: These three changes are small (0.5 waves each per PRD), independent of each other,
and are required by S8 core (Phase 2). Running them first unblocks all parallel Phase 1 work.

---

### Wave A-1: intelligence-migrations Schema Additions ✅

**Goal**: Add new columns to `events` table, new relation types to `relation_type_registry`, and seed sector/industry entities.
**Depends on**: none
**Estimated effort**: 20–30 min
**Status**: **DONE** — 2026-04-05 · 4 new integration tests pass · ruff + mypy clean
**Architecture layer**: schema

**Pre-read (agent must read before starting)**:
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` — existing schema baseline
- `services/intelligence-migrations/seeds/001_model_registry.sql` — seed file format example
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.4 "intelligence-migrations: New Alembic Migration"

#### T-A-1-01: Alembic Migration 0002

**Type**: schema
**depends_on**: none
**blocks**: [T-C-2-01, T-C-4-01]
**Target files**:
- `services/intelligence-migrations/alembic/versions/0002_enhance_events_and_relations.py` (new)

**What to build**:
Forward migration: Add 3 nullable columns to `events`, add composite index, insert 4 new rows into
`relation_type_registry`. Downgrade: DROP columns, DROP index, DELETE the 4 new rows.

All changes are backward-compatible (new nullable columns, new registry rows).

**Logic & Behavior**:
```sql
-- Upgrade
ALTER TABLE events ADD COLUMN event_subtype VARCHAR(50) NULL;
ALTER TABLE events ADD COLUMN source_type VARCHAR(50) NULL;
ALTER TABLE events ADD COLUMN structured_data JSONB NULL;
CREATE INDEX ix_events_entity_type_date
  ON events(subject_entity_id, event_type, event_subtype, event_date DESC);

INSERT INTO relation_type_registry
  (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
  ('is_in_sector',     'RELATION_STATE',  'PERMANENT', 0.90, 'GICS sector membership from EODHD'),
  ('is_in_industry',   'RELATION_STATE',  'DURABLE',   0.85, 'GICS industry group from EODHD'),
  ('earnings_released','TEMPORAL_CLAIM',  'FAST',      0.95, 'Quarterly/annual earnings event'),
  ('corporate_action', 'TEMPORAL_CLAIM',  'DURABLE',   0.90, 'Dividend, split, buyback events')
ON CONFLICT (canonical_type) DO NOTHING;

-- Downgrade
DROP INDEX IF EXISTS ix_events_entity_type_date;
ALTER TABLE events DROP COLUMN IF EXISTS event_subtype;
ALTER TABLE events DROP COLUMN IF EXISTS source_type;
ALTER TABLE events DROP COLUMN IF EXISTS structured_data;
DELETE FROM relation_type_registry
  WHERE canonical_type IN ('is_in_sector','is_in_industry','earnings_released','corporate_action');
```

**Downstream test impact**:
- `services/intelligence-migrations/tests/test_migrations.py` — if exists, add forward/rollback test for 0002

**Acceptance criteria**:
- [ ] `alembic upgrade head` succeeds on a clean intelligence_db
- [ ] `alembic downgrade -1` removes all added artifacts
- [ ] Migration file has `revision`, `down_revision`, both `upgrade()` and `downgrade()` functions

---

#### T-A-1-02: Sector/Industry Seed File

**Type**: schema
**depends_on**: [T-A-1-01]
**blocks**: [T-C-4-01]
**Target files**:
- `services/intelligence-migrations/seeds/003_seed_sector_entities.sql` (new)

**What to build**:
SQL seed file that inserts 11 GICS sector entities and ~24 industry group entities into
`canonical_entities`. These are static reference data used by `FundamentalsRefreshWorker` as
target nodes for `is_in_sector` / `is_in_industry` relations.

**Logic & Behavior**:
- `entity_type = 'sector'` for the 11 GICS sectors
- `entity_type = 'industry_group'` for the ~24 GICS industry groups
- `canonical_name` = official GICS sector/industry group name
- `entity_id` = UUIDv7 (pre-generated stable UUIDs in seed — must NOT change across runs)
- `ON CONFLICT (entity_id) DO NOTHING` for idempotency

GICS Sectors (11):
Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care,
Financials, Information Technology, Communication Services, Utilities, Real Estate

Industry Groups (~24, abbreviated set covering major ones):
Energy (Equipment & Services, Oil Gas & Consumable Fuels), Materials (Chemicals, Metals & Mining,
Paper & Forest Products), Industrials (Capital Goods, Commercial Services, Transportation),
Consumer Discretionary (Automobiles, Retailing, Hotels Restaurants), Consumer Staples (Food,
Beverages, Household Products), Health Care (Equipment, Pharmaceuticals, Biotechnology),
Financials (Banks, Insurance, Capital Markets), IT (Software, Hardware, Semiconductors),
Communication Services (Media, Telecom), Utilities (Electric, Gas), Real Estate (REITs, RE Mgmt)

**Acceptance criteria**:
- [ ] Seed file runs without error against a fresh intelligence_db after 0002 migration
- [ ] Idempotent: running twice produces no duplicate rows
- [ ] All sector/industry names match official GICS taxonomy

---

**Validation Gate (Wave A-1)**:
- [x] `alembic -c services/intelligence-migrations/alembic.ini upgrade head` passes
- [x] `alembic -c services/intelligence-migrations/alembic.ini downgrade -1` passes
- [x] `psql -f services/intelligence-migrations/seeds/003_seed_sector_entities.sql` passes (idempotent)
- [x] ruff check passes on any Python files changed
- [x] mypy passes on intelligence-migrations package

---

### Wave A-2: S5 Content Store — Batch Documents Endpoint ✅

**Goal**: Add `POST /api/v1/documents/batch` so S8 can fetch citation metadata for up to 50 doc_ids in one call.
**Depends on**: none (independent of A-1)
**Estimated effort**: 25–40 min
**Status**: **DONE** — 2026-04-05 · 13 new unit tests pass · ruff + mypy clean
**Architecture layer**: application + API

**Pre-read**:
- `services/content-store/src/content_store/api/` — existing route structure
- `services/content-store/src/content_store/application/use_cases/` — existing use case patterns
- `services/content-store/.claude-context.md` — key tables, pitfalls

#### T-A-2-01: BatchDocumentsUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-02]
**Target files**:
- `services/content-store/src/content_store/application/use_cases/batch_documents.py` (new)
- `services/content-store/src/content_store/application/ports/document_repository.py` — add `batch_get_metadata` method

**What to build**:
Read-only use case: accepts a list of doc_ids (max 50), returns document metadata for each found doc.
Missing doc_ids are silently omitted (not an error — S8 must handle partial results).

**Entities / Components**:
- **`DocumentMetadataDTO`** (dataclass in use case file):
  - `doc_id: UUID`
  - `title: str | None`
  - `url: str | None`
  - `published_at: datetime | None` (UTC-aware)
  - `source_name: str | None`
  - `source_type: str | None`
  - `word_count: int | None`

**Logic & Behavior**:
1. Validate `len(doc_ids) <= 50`; raise `DomainError("Too many doc_ids")` if exceeded
2. Call `document_repo.batch_get_metadata(doc_ids)` → list of `DocumentMetadataDTO`
3. Return list (preserves order for found docs; missing doc_ids not in result)

Repository port method:
```python
async def batch_get_metadata(self, doc_ids: list[UUID]) -> list[DocumentMetadataDTO]:
    # SELECT id, title, url, published_at, source_name, source_type, word_count
    # FROM documents WHERE id = ANY(:ids)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_batch_documents_returns_found_only` | 3 ids given, 2 found → 2 in result | unit |
| `test_batch_documents_too_many_ids` | 51 ids → raises DomainError | unit |
| `test_batch_documents_empty_list` | empty list → empty result | unit |

**Acceptance criteria**:
- [ ] Use case depends on `ReadOnlyUnitOfWork` (R27)
- [ ] Missing doc_ids not in result (no KeyError)
- [ ] Unit tests pass

---

#### T-A-2-02: POST /api/v1/documents/batch Endpoint

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: none
**Target files**:
- `services/content-store/src/content_store/api/routes/documents.py` (new or add to existing)
- `services/content-store/src/content_store/api/schemas.py` — add `BatchDocumentsRequest`, `BatchDocumentsResponse`, `DocumentMetadataResponse`

**What to build**:
Internal-only endpoint (no user auth; rate-limited by service mesh). Returns document metadata
for a batch of `doc_ids`. Auth: none required (internal service-to-service).

**Pydantic Schemas**:
```python
class BatchDocumentsRequest(BaseModel):
    doc_ids: list[UUID] = Field(..., min_length=1, max_length=50)

class DocumentMetadataResponse(BaseModel):
    doc_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None
    source_type: str | None
    word_count: int | None

class BatchDocumentsResponse(BaseModel):
    documents: list[DocumentMetadataResponse]
```

**Logic & Behavior**:
```
POST /api/v1/documents/batch
  → validate request (Pydantic)
  → call BatchDocumentsUseCase.execute(doc_ids)
  → return 200 BatchDocumentsResponse
  Errors: 400 (too many ids), 422 (validation)
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_batch_documents_endpoint_found` | 2 existing doc_ids → 200 with 2 docs | unit |
| `test_batch_documents_endpoint_empty` | no matching ids → 200 with empty list | unit |
| `test_batch_documents_endpoint_too_many` | 51 ids → 400 | unit |

**Acceptance criteria**:
- [ ] Route registered in S5 `app.py`
- [ ] Uses `ReadUoWDep` (R27)
- [ ] No auth required (internal endpoint)
- [ ] Unit tests pass with ASGI test client

---

**Validation Gate (Wave A-2)**:
- [x] ruff check + mypy pass on `services/content-store/`
- [x] `python -m pytest services/content-store/tests/ --ignore=services/content-store/tests/integration -v` passes (266 passed)
- [x] New endpoint registered and accessible in test client

---

### Wave A-3: S1 Portfolio — Portfolio Context Endpoint ✅

**Goal**: Add `GET /internal/v1/users/{user_id}/portfolio/context` for PORTFOLIO-intent queries in S8.
**Depends on**: none
**Estimated effort**: 25–40 min
**Status**: **DONE** — 2026-04-05 · 13 new unit tests pass · ruff + mypy clean
**Architecture layer**: application + API

**Pre-read**:
- `services/portfolio/src/portfolio/api/routes/` — existing route structure
- `services/portfolio/src/portfolio/application/use_cases/` — use case patterns
- `services/portfolio/.claude-context.md` — internal endpoint patterns, `X-Internal-Token` requirement

#### T-A-3-01: PortfolioContextUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-A-3-02]
**Target files**:
- `services/portfolio/src/portfolio/application/use_cases/portfolio_context.py` (new)

**What to build**:
Read-only use case that fetches the user's active holdings and watchlist, returning a denormalized
summary for S8 to use as portfolio context in PORTFOLIO-intent queries.

**Entities / Components**:
- **`HoldingContext`** (frozen dataclass):
  - `ticker: str | None`
  - `entity_id: UUID | None` — from `instruments.entity_id`
  - `canonical_name: str | None` — from `instruments.name`
  - `quantity: Decimal`
  - `current_weight: float | None` — computed: quantity × price / total_portfolio_value (use 0.0 if no price)

- **`WatchlistContext`** (frozen dataclass):
  - `ticker: str | None`
  - `entity_id: UUID | None`
  - `canonical_name: str | None`

- **`PortfolioContextDTO`** (frozen dataclass):
  - `user_id: UUID`
  - `tenant_id: UUID`
  - `holdings: list[HoldingContext]`
  - `watchlist: list[WatchlistContext]`
  - `total_positions: int`

**Logic & Behavior**:
1. Verify user exists and belongs to tenant (SELECT users WHERE id = ? AND tenant_id = ?)
2. Query holdings: `SELECT h.*, i.ticker, i.entity_id, i.name FROM holdings h JOIN instruments i ON h.instrument_id = i.id WHERE h.user_id = ? AND h.deleted_at IS NULL`
3. Query watchlist: `SELECT wm.*, i.ticker, i.entity_id, i.name FROM watchlist_members wm JOIN watchlists w ON wm.watchlist_id = w.id JOIN instruments i ON wm.instrument_id = i.id WHERE w.user_id = ? AND wm.status != 'deleted'`
4. Build PortfolioContextDTO (entity_id may be null for instruments not yet linked)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_portfolio_context_returns_holdings_and_watchlist` | Holdings + watchlist returned | unit |
| `test_portfolio_context_user_not_in_tenant` | User belongs to different tenant → 404 | unit |
| `test_portfolio_context_empty_portfolio` | No holdings → empty list | unit |

**Acceptance criteria**:
- [ ] Uses `ReadOnlyUnitOfWork` (R27)
- [ ] `entity_id` populated from `instruments.entity_id` when available; null otherwise
- [ ] Unit tests pass

---

#### T-A-3-02: GET /api/v1/users/{user_id}/portfolio/context Endpoint

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**:
- `services/portfolio/src/portfolio/api/routes/internal.py` — add to existing internal routes
- `services/portfolio/src/portfolio/api/schemas.py` — add `PortfolioContextResponse`

**What to build**:
Internal endpoint protected by `X-Internal-Token` (same pattern as existing `GET /internal/v1/watchlists/by-entity/{entity_id}`). Ownership check: `user_id` must match `X-User-Id` header.

**Pydantic Schemas**:
```python
class HoldingContextItem(BaseModel):
    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None
    quantity: Decimal
    current_weight: float

class WatchlistContextItem(BaseModel):
    ticker: str | None
    entity_id: UUID | None
    canonical_name: str | None

class PortfolioContextResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    holdings: list[HoldingContextItem]
    watchlist: list[WatchlistContextItem]
    total_positions: int
```

**Logic & Behavior**:
```
GET /api/v1/users/{user_id}/portfolio/context
  → validate X-Internal-Token (hmac.compare_digest)
  → verify X-User-Id == user_id path param; 403 otherwise (ownership check)
  → call PortfolioContextUseCase.execute(user_id, tenant_id)
  → return 200 PortfolioContextResponse
  Errors: 401 (missing/invalid token), 403 (wrong user), 404 (user not found)
```

**Note**: Cache header `Cache-Control: max-age=300` (5 min). S8 implements the Valkey cache itself.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_portfolio_context_endpoint_success` | Valid token + matching user → 200 | unit |
| `test_portfolio_context_wrong_user` | X-User-Id != path user_id → 403 | unit |
| `test_portfolio_context_missing_token` | No X-Internal-Token → 401 | unit |

**Acceptance criteria**:
- [ ] Protected by `X-Internal-Token` auth (R13 compliant: token in env var)
- [ ] Ownership check: X-User-Id must match path user_id
- [ ] Route registered; unit tests pass

---

**Validation Gate (Wave A-3)**:
- [x] ruff check + mypy pass on `services/portfolio/`
- [x] `python -m pytest services/portfolio/tests -m unit -v` passes (311 passed, no existing tests broken)
- [x] New endpoint accessible via ASGI test client with correct auth

---

## PLAN-0015-B: S6 NLP Pipeline Enhancements

**Service**: S6 (`services/nlp-pipeline/`)
**Rationale**: S8 needs S6 for (a) document source metadata in chunk results, (b) query-time entity
resolution, and (c) enhanced chunk search with entity annotations. All three are new endpoints/table
additions that extend S6 without modifying existing behavior.

---

### Wave B-1: document_source_metadata Table + Consumer Extension ✅

**Goal**: Add `document_source_metadata` table to `nlp_db` and extend the article consumer to populate it.
**Depends on**: none (independent of A-1)
**Estimated effort**: 35–50 min
**Architecture layer**: infrastructure + domain
**Status**: **DONE** — 2026-04-05 · 245 tests pass · ruff + mypy clean

**Pre-read**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/models/` — existing ORM models
- `services/nlp-pipeline/alembic/versions/` — latest migration for down_revision
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` — extend this
- `services/nlp-pipeline/.claude-context.md` — Block 7-10 behaviors, consumer entry points

#### T-B-1-01: DocumentSourceMetadata Domain Entity + Repository Port

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-02, T-B-1-03]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/domain/entities/document_source_metadata.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/document_source_metadata_repository.py` (new)

**What to build**:
Frozen dataclass representing cached article citation metadata. Used by S6's enhanced chunk search
endpoint to return citation data inline (no round-trip to S5).

**Entities / Components**:
- **`DocumentSourceMetadata`** (frozen dataclass):
  - `doc_id: UUID` — from `content.article.stored.v1`
  - `title: str | None`
  - `url: str | None`
  - `published_at: datetime | None` — UTC-aware
  - `source_name: str | None` — e.g. "SEC EDGAR", "Finnhub"
  - `source_type: str | None` — e.g. "sec_10q", "eodhd_news"
  - `word_count: int | None`
  - `created_at: datetime` — UTC, set on INSERT

Repository port interface:
```python
class DocumentSourceMetadataRepository(ABC):
    async def upsert(self, metadata: DocumentSourceMetadata) -> None:
        # ON CONFLICT (doc_id) DO NOTHING — idempotent
    async def batch_get(self, doc_ids: list[UUID]) -> dict[UUID, DocumentSourceMetadata]:
        # returns only found doc_ids
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_document_source_metadata_frozen` | Cannot mutate after creation | unit |
| `test_document_source_metadata_none_fields_allowed` | All optional fields can be None | unit |

---

#### T-B-1-02: Alembic Migration + SQLAlchemy Model

**Type**: schema
**depends_on**: [T-B-1-01]
**blocks**: [T-B-1-03, T-B-1-04]
**Target files**:
- `services/nlp-pipeline/alembic/versions/0002_add_document_source_metadata.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/models/document_source_metadata.py` (new)

**What to build**:
Migration adds `document_source_metadata` table to `nlp_db`. SQLAlchemy ORM model for persistence.

**Table DDL**:
```sql
CREATE TABLE document_source_metadata (
    doc_id UUID PRIMARY KEY,
    title TEXT,
    url TEXT,
    published_at TIMESTAMPTZ,
    source_name VARCHAR(100),
    source_type VARCHAR(50),
    word_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- No additional indexes needed: access is always by PK or batch IN clause
```

**Downstream test impact**:
- `services/nlp-pipeline/tests/unit/infrastructure/test_ddl_alignment.py` — add DDL alignment test for new table

**Acceptance criteria**:
- [ ] Migration runs and rolls back cleanly
- [ ] ORM model column names/types match migration DDL
- [ ] DDL alignment test added

---

#### T-B-1-03: SQLAlchemy Repository Implementation

**Type**: impl
**depends_on**: [T-B-1-02]
**blocks**: [T-B-1-04]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/document_source_metadata.py` (new)

**What to build**:
Repository implementation using SQLAlchemy async session. `upsert()` uses `INSERT ... ON CONFLICT DO NOTHING`
for idempotency (S6 consumer may process the same article twice on replay).

**Logic & Behavior**:
- `upsert()`: `INSERT INTO document_source_metadata (...) VALUES (...) ON CONFLICT (doc_id) DO NOTHING`
- `batch_get()`: `SELECT * FROM document_source_metadata WHERE doc_id = ANY(:ids)` → dict

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_upsert_idempotent` | Second upsert same doc_id → no error, no duplicate | unit |
| `test_batch_get_partial` | 3 doc_ids, 2 exist → dict with 2 entries | unit |

---

#### T-B-1-04: Extend ArticleProcessingConsumer

**Type**: impl
**depends_on**: [T-B-1-03]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` — extend `_handle_message`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/app_factory.py` (or wherever consumer is wired) — inject repository

**What to build**:
After the article consumer commits the NLP processing result, also call
`document_source_metadata_repo.upsert()` with metadata extracted from the incoming
`content.article.stored.v1` event. This is an idempotent side effect.

**Logic & Behavior**:
```python
# In ArticleProcessingConsumer._handle_message, after super()._handle_message call:
metadata = DocumentSourceMetadata(
    doc_id=event.doc_id,
    title=event.title,       # if present in content.article.stored.v1
    url=event.url,
    published_at=event.published_at,
    source_name=event.source_name,
    source_type=event.source_type.value if event.source_type else None,
    word_count=event.word_count,
    created_at=utc_now(),
)
await self._metadata_repo.upsert(metadata)
# Note: This is best-effort. Failure should log warning and NOT raise.
```

**Important**: Wrap in try/except; metadata write failure must not cause NLP processing to fail
(don't want to lose article processing for a cache miss).

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_consumer_writes_metadata_on_success` | `metadata_repo.upsert` called with correct fields | unit |
| `test_consumer_continues_on_metadata_failure` | metadata write raises → consumer still succeeds | unit |

**Acceptance criteria**:
- [x] Metadata write is best-effort (exception caught, warning logged, not re-raised)
- [x] Existing consumer tests still pass (no regression)

---

**Validation Gate (Wave B-1)**:
- [x] ruff check + mypy pass on `services/nlp-pipeline/`
- [x] `python -m pytest services/nlp-pipeline/tests/unit/ -v` passes (245 tests pass)
- [x] Alembic migration runs and rolls back cleanly
- [x] DDL alignment test added and passes

---

### Wave B-2: Entity Resolution Endpoint ✅

**Goal**: Add `POST /api/v1/entities/resolve` — query-time entity resolution using 5-stage cascade.
**Depends on**: B-1 (nlp_db and intelligence_db sessions already wired)
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-04-05 · 257 tests pass · ruff + mypy clean
**Architecture layer**: application + API

**Pre-read**:
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` — existing Block 9 entity resolution logic
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/alias_repository.py` — existing alias lookup methods
- `services/nlp-pipeline/.claude-context.md` — Block 9 stages and batch methods

#### T-B-2-01: QueryEntityResolverUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-B-2-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/query_entity_resolver.py` (new)

**What to build**:
Lightweight entity resolver for query text (not a full article). Uses a 5-stage cascade adapted
from Block 9, but operates on short query text (< 200 chars typically).

**Entities / Components**:
- **`EntityResolutionResult`** (frozen dataclass):
  - `entity_id: UUID`
  - `canonical_name: str`
  - `entity_type: str`
  - `confidence: float`
  - `ticker: str | None`
  - `isin: str | None`
  - `matched_text: str`
  - `resolution_stage: int` — 1=exact alias, 2=ticker/ISIN, 3=fuzzy, 4=GLiNER, 5=ANN

- **`QueryEntityResolverUseCase`**:
  - `__init__(alias_repo, ner_client, embedding_client, valkey_client)`
  - `async execute(query_text: str, top_k_per_mention: int = 3, min_confidence: float = 0.45) -> list[EntityResolutionResult]`

**Logic & Behavior**:
Resolution cascade:
1. Normalize query text (lowercase, strip punctuation)
2. Stage 1: `alias_repo.batch_exact_match([query_text])` → direct alias match
3. Stage 2: Extract ticker patterns (`[A-Z]{1,5}` regex) + ISIN patterns → `alias_repo.batch_ticker_isin_match`
4. Stage 3: `alias_repo.batch_fuzzy_trigram([query_text], threshold=0.70, top_k=3)`
5. Stage 4: If NER client available → `ner_client.batch_extract_entities([query_text])` → for each mention, run stages 1-3
6. Stage 5: ANN fallback for any unresolved mentions (only if clear_margin > 0.10 in embedding space)

Filter results: `confidence >= min_confidence`. Deduplicate by `entity_id` (keep highest confidence).
Cache result in Valkey: `s6:v1:resolve:{sha256(normalize(query_text))}` TTL=600s.

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_resolve_exact_alias_match` | "Apple" → entity_id from alias table, stage=1 | unit |
| `test_resolve_ticker_match` | "AAPL" → Apple Inc entity, stage=2 | unit |
| `test_resolve_fuzzy_match` | "Appl" (typo) → Apple Inc via trigram, stage=3 | unit |
| `test_resolve_cache_hit` | Second call with same text → Valkey cache returned | unit |
| `test_resolve_below_min_confidence_filtered` | Low confidence entity → not in result | unit |

---

#### T-B-2-02: POST /api/v1/entities/resolve Endpoint

**Type**: impl
**depends_on**: [T-B-2-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/entities.py` — add resolve endpoint
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` — add request/response schemas

**What to build**:
Internal endpoint for query-time entity resolution. No user auth required.

**Pydantic Schemas**:
```python
class EntityResolveRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=2000)
    top_k_per_mention: int = Field(default=3, ge=1, le=10)
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)

class ResolvedEntityResponse(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    confidence: float
    ticker: str | None
    isin: str | None
    matched_text: str
    resolution_stage: int

class EntityResolveResponse(BaseModel):
    entities: list[ResolvedEntityResponse]
    query_text_normalized: str
```

**Logic & Behavior**:
```
POST /api/v1/entities/resolve
  → Pydantic validation
  → call QueryEntityResolverUseCase.execute(query_text, top_k_per_mention, min_confidence)
  → return 200 EntityResolveResponse
  Errors: 400 (validation)
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_resolve_endpoint_success` | Valid request → 200 with entities | unit |
| `test_resolve_endpoint_empty_query` | Empty string → 422 | unit |

---

**Validation Gate (Wave B-2)**:
- [x] ruff check + mypy pass
- [x] `python -m pytest services/nlp-pipeline/tests/unit/ -v` passes
- [x] Resolve endpoint accessible; cache key follows `s6:v1:resolve:*` pattern

---

### Wave B-3: Enhanced Chunk Search Endpoint ✅

**Goal**: Add `POST /api/v1/search/chunks` — ANN search with inline entity annotations and source metadata.
**Depends on**: B-1 (document_source_metadata table required for inline metadata)
**Estimated effort**: 45–60 min
**Status**: **DONE** — 2026-04-06 · 271 tests pass · ruff + mypy clean
**Architecture layer**: application + API

**Pre-read**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/` — existing vector-search endpoint
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/` — chunk embedding repo
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.3 S6 enhanced chunk search spec

#### T-B-3-01: EnhancedChunkSearchUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-B-3-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py` (new)

**What to build**:
Use case that combines ANN vector search on `chunk_embeddings` / `section_embeddings` HNSW indexes
with JOIN to `chunk_entity_mentions` → `entity_mentions` → `canonical_entities` (for entity annotations)
and JOIN to `document_source_metadata` (for citation metadata). Returns enriched results.

**Entities / Components**:
- **`SourceMetadata`** (frozen dataclass):
  - `title: str | None`, `url: str | None`, `published_at: datetime | None`
  - `source_name: str | None`, `source_type: str | None`

- **`ChunkEntityAnnotation`** (frozen dataclass):
  - `entity_id: UUID`, `canonical_name: str`, `entity_type: str`, `confidence: float`

- **`EnrichedChunkResult`** (frozen dataclass):
  - `chunk_id: UUID`, `doc_id: UUID`, `section_id: UUID | None`
  - `granularity: str` ("chunk" or "section")
  - `text: str`, `score: float`
  - `source_metadata: SourceMetadata`
  - `entities: list[ChunkEntityAnnotation]`
  - `section_type: str | None`, `heading_path: str | None`

**Logic & Behavior**:
1. If `query_embedding` provided: skip embedding step; else call `EmbeddingClient.embed(query_text)` → cache `s6:v1:emb:{sha256(query_text)}` 1h
2. Run HNSW ANN query on `chunk_embeddings` (or `section_embeddings` for granularity=section): `ORDER BY embedding <=> :vec LIMIT :top_k`
3. Apply `min_score` filter on cosine similarity (1 - distance)
4. Apply `date_from/date_to` filter via JOIN to `document_source_metadata.published_at`
5. Apply `source_types` filter via JOIN to `document_source_metadata.source_type`
6. If `include_entities=true`: LEFT JOIN `chunk_entity_mentions` → `entity_mentions` → fetch canonical entity name; filter `resolution_confidence >= 0.45`
7. Batch lookup `document_source_metadata.batch_get(doc_ids)` for citation metadata
8. Build and return list of `EnrichedChunkResult`

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_chunk_search_returns_enriched_results` | Vector search returns entities + source_metadata | unit |
| `test_chunk_search_date_filter` | Chunks outside date range excluded | unit |
| `test_chunk_search_pre_embedded_query` | query_embedding provided → embed call skipped | unit |
| `test_chunk_search_embedding_cached` | Second call same text → Valkey cache hit | unit |

---

#### T-B-3-02: POST /api/v1/search/chunks Endpoint

**Type**: impl
**depends_on**: [T-B-3-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` — add new endpoint alongside existing `/vector-search`
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` — request/response schemas

**What to build**:
New endpoint `POST /api/v1/search/chunks`. Old `POST /api/v1/search/vector` (or `/vector-search`) remains unchanged.

**Pydantic Schemas**:
```python
class ChunkSearchRequest(BaseModel):
    query_text: str | None = Field(None, min_length=1, max_length=2000)
    query_embedding: list[float] | None = Field(None, min_length=1024, max_length=1024)
    granularity: Literal["chunk", "section", "both"] = "chunk"
    top_k: int = Field(default=20, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    include_entities: bool = True
    date_from: date | None = None
    date_to: date | None = None
    source_types: list[str] = []

    @model_validator(mode="after")
    def exactly_one_query(self) -> "ChunkSearchRequest":
        if (self.query_text is None) == (self.query_embedding is None):
            raise ValueError("Exactly one of query_text or query_embedding must be provided")
        return self
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_chunk_search_endpoint_200` | Valid request → 200 | unit |
| `test_chunk_search_both_query_fields_rejected` | Both text + embedding → 422 | unit |
| `test_chunk_search_neither_query_fields_rejected` | Neither provided → 422 | unit |

**Acceptance criteria**:
- [x] Old `/vector-search` endpoint unchanged and still passing tests
- [x] New `/search/chunks` endpoint registered
- [x] Model validator enforces exactly-one query pattern
- [x] Unit tests pass

---

**Validation Gate (Wave B-3)**:
- [x] ruff check + mypy pass
- [x] `python -m pytest services/nlp-pipeline/tests/unit/ -v` passes (271 tests, no regression)
- [x] Both endpoints accessible; old endpoint still works

---

## PLAN-0015-C: S7 Knowledge Graph API Additions

**Service**: S7 (`services/knowledge-graph/`)
**Rationale**: S8 needs S7 for claims, events, contradictions, relation ANN search, and egocentric graph.
The first two waves (C-1/C-2) are Phase 1 queries against existing tables.
Relation ANN (C-3) is also Phase 1 (prerequisite for D — S8 needs it for hybrid retrieval).
FundamentalsWorker enhancement (C-4) is Phase 3 (runs parallel with Phase 2).
All four are independent of the S8 core build and can run in parallel with PLAN-0015-D.

---

### Wave C-1: Claims Search + Contradictions Endpoint ✅

**Goal**: Add `POST /api/v1/claims/search` and `GET /api/v1/entities/{entity_id}/contradictions`.
**Depends on**: none (queries existing `article_claims` and `contradiction_links` tables)
**Estimated effort**: 40–55 min
**Status**: **DONE** — 2026-04-06 · 198 tests pass · ruff + mypy clean
**Architecture layer**: application + API

**Pre-read**:
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` — `article_claims` and `contradiction_links` schema
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/` — existing repo patterns
- `services/knowledge-graph/.claude-context.md` — API endpoints, critical rules

#### T-C-1-01: ArticleClaimSearchUseCase + ContradictionRepository Methods

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-02, T-C-1-03]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/claim_search.py` (new)
- `services/knowledge-graph/src/knowledge_graph/application/ports/claim_repository.py` — add `search_claims` method
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/claim_repository.py` — implement method

**What to build**:
`ArticleClaimSearchUseCase` queries `article_claims` by entity_ids, optional claim_types, date range,
and minimum confidence. Returns ordered by `extraction_confidence DESC`.

**Entities / Components**:
- **`ClaimSearchResult`** (frozen dataclass):
  - `claim_id: UUID`, `subject_entity_id: UUID`
  - `claim_type: str`, `polarity: str` ("positive", "negative", "neutral")
  - `claim_text: str`, `extraction_confidence: float`
  - `doc_id: UUID | None`, `created_at: datetime`

**Logic & Behavior**:
```sql
SELECT claim_id, subject_entity_id, claim_type, polarity, claim_text,
       extraction_confidence, doc_id, created_at
FROM article_claims
WHERE subject_entity_id = ANY(:entity_ids)
  AND (:claim_types IS NULL OR claim_type = ANY(:claim_types))
  AND (:date_from IS NULL OR created_at >= :date_from)
  AND (:date_to IS NULL OR created_at <= :date_to)
  AND extraction_confidence >= :min_confidence
ORDER BY extraction_confidence DESC
LIMIT :top_k
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_claim_search_by_entity` | Returns claims for given entity_ids | unit |
| `test_claim_search_claim_type_filter` | Filtered by claim_type | unit |
| `test_claim_search_date_range` | Outside date range excluded | unit |
| `test_claim_search_min_confidence` | Low confidence excluded | unit |

---

#### T-C-1-02: POST /api/v1/claims/search Endpoint

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/routes/claims.py` (new)
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` — add request/response schemas

**Pydantic Schemas**:
```python
class ClaimsSearchRequest(BaseModel):
    entity_ids: list[UUID] = Field(..., min_length=1, max_length=10)
    claim_types: list[str] = []
    date_from: date | None = None
    date_to: date | None = None
    top_k: int = Field(default=20, ge=1, le=100)
    min_confidence: float = Field(default=0.45, ge=0.0, le=1.0)

class ClaimResponse(BaseModel):
    claim_id: UUID
    subject_entity_id: UUID
    claim_type: str
    polarity: str
    claim_text: str
    extraction_confidence: float
    doc_id: UUID | None
    created_at: datetime

class ClaimsSearchResponse(BaseModel):
    claims: list[ClaimResponse]
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_claims_search_endpoint_200` | Valid request → 200 | unit |
| `test_claims_search_too_many_entity_ids` | >10 ids → 422 | unit |

---

#### T-C-1-03: EntityContradictionsUseCase + GET /entities/{id}/contradictions

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/contradiction_lookup.py` (new)
- `services/knowledge-graph/src/knowledge_graph/api/routes/entities.py` — add contradiction endpoint
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` — add response schemas

**What to build**:
Read-only use case that fetches active contradictions for an entity from `contradiction_links`.
Groups by `claim_type`, returns top-k by combined `strength`.

**Entities / Components**:
- **`ContradictionSide`**: `{polarity, confidence, doc_id, claim_text, evidence_date}`
- **`ContradictionResponse`**: `{claim_type, strength: float, detected_at: datetime, sides: list[ContradictionSide]}`

**Logic & Behavior**:
```sql
SELECT cl.*, c1.polarity, c1.confidence, c1.doc_id, c1.claim_text, c1.created_at,
       c2.polarity, c2.confidence, c2.doc_id, c2.claim_text, c2.created_at
FROM contradiction_links cl
JOIN article_claims c1 ON cl.claim_a_id = c1.claim_id
JOIN article_claims c2 ON cl.claim_b_id = c2.claim_id
WHERE (c1.subject_entity_id = :entity_id OR c2.subject_entity_id = :entity_id)
  AND (:claim_type IS NULL OR cl.claim_type = :claim_type)
ORDER BY cl.strength DESC
LIMIT :top_k
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_contradictions_endpoint_200` | Valid entity_id → 200 | unit |
| `test_contradictions_endpoint_404_on_unknown` | Unknown entity → empty contradictions list | unit |

---

**Validation Gate (Wave C-1)**:
- [x] ruff check + mypy pass on `services/knowledge-graph/`
- [x] `python -m pytest services/knowledge-graph/tests/ -m unit -v` passes
- [x] Two new endpoints accessible and returning correct schemas

---

### Wave C-2: Events Search Endpoint

**Goal**: Add `POST /api/v1/events/search` using the new columns added by migration 0002.
**Depends on**: A-1 (migration 0002 adds event_subtype, source_type, structured_data columns)
**Estimated effort**: 30–45 min
**Architecture layer**: application + API

**Pre-read**:
- Migration 0002 definition (from A-1) — new columns on `events` table
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` — existing events columns

#### T-C-2-01: EventSearchUseCase

**Type**: impl
**depends_on**: [T-A-1-01] (migration)
**blocks**: [T-C-2-02]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/event_search.py` (new)
- `services/knowledge-graph/src/knowledge_graph/application/ports/event_repository.py` — add `search_events` method
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/event_repository.py` — implement (or add to existing)

**What to build**:
Queries `events` table by entity_ids, event_types, date range. Returns events including
new structured_data column.

**Entities / Components**:
- **`EventSearchResult`** (frozen dataclass):
  - `event_id: UUID`, `event_type: str`, `event_subtype: str | None`
  - `subject_entity_id: UUID`, `event_date: datetime | None`
  - `event_text: str`, `structured_data: dict | None`
  - `extraction_confidence: float`, `doc_id: UUID | None`
  - `source_type: str | None`

**Logic & Behavior**:
```sql
SELECT event_id, event_type, event_subtype, subject_entity_id,
       event_date, event_text, structured_data, extraction_confidence,
       doc_id, source_type
FROM events
WHERE (:entity_ids IS NULL OR subject_entity_id = ANY(:entity_ids))
  AND (:event_types IS NULL OR event_type = ANY(:event_types))
  AND (:date_from IS NULL OR event_date >= :date_from)
  AND (:date_to IS NULL OR event_date <= :date_to)
ORDER BY event_date DESC
LIMIT :top_k
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_event_search_returns_structured_data` | Events with structured_data returned correctly | unit |
| `test_event_search_event_type_filter` | Only matching event_types returned | unit |
| `test_event_search_date_range` | Events outside range excluded | unit |

---

#### T-C-2-02: POST /api/v1/events/search Endpoint

**Type**: impl
**depends_on**: [T-C-2-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/routes/events.py` (new)
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` — add schemas

**Pydantic Schemas**:
```python
class EventsSearchRequest(BaseModel):
    entity_ids: list[UUID] = []
    event_types: list[str] = []
    date_from: date | None = None
    date_to: date | None = None
    top_k: int = Field(default=20, ge=1, le=100)

class EventResponse(BaseModel):
    event_id: UUID
    event_type: str
    event_subtype: str | None
    subject_entity_id: UUID
    event_date: datetime | None
    event_text: str
    structured_data: dict | None
    extraction_confidence: float
    doc_id: UUID | None

class EventsSearchResponse(BaseModel):
    events: list[EventResponse]
```

---

**Validation Gate (Wave C-2)**:
- [ ] ruff check + mypy pass
- [ ] Unit tests pass (including test that structured_data is returned as dict)
- [ ] Endpoint returns 501 if called before migration 0002 (handled by schema-level null)

---

### Wave C-3: Relation Summary ANN Search

**Goal**: Add `POST /api/v1/search/relations` — HNSW ANN search on `relation_summaries.summary_embedding`.
**Depends on**: none (table and HNSW index already exist from intelligence-migrations 0001)
**Estimated effort**: 35–50 min
**Architecture layer**: application + API

**Pre-read**:
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` — `relation_summaries` table with HNSW index
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/relation_summary_repository.py` — existing repo (likely has `get_by_id` but not ANN search)

#### T-C-3-01: RelationSummarySearchUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-C-3-02]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/relation_summary_search.py` (new)
- `services/knowledge-graph/src/knowledge_graph/application/ports/relation_summary_repository.py` — add `search_by_embedding` method
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/relation_summary_repository.py` — implement

**What to build**:
ANN search on `relation_summaries.summary_embedding` HNSW index. Returns relations ranked by
semantic similarity to query embedding, filtered by entity_ids, min_confidence, relation_types.

**Entities / Components**:
- **`RelationSummarySearchResult`** (frozen dataclass):
  - `relation_id: UUID`, `subject_entity_id: UUID`, `object_entity_id: UUID`
  - `subject_canonical_name: str`, `object_canonical_name: str`
  - `canonical_type: str`, `summary: str`
  - `confidence: float`, `evidence_count: int`
  - `latest_evidence_at: datetime | None`
  - `semantic_mode: str`
  - `summary_authority: float` — computed: `confidence * log1p(evidence_count)` (NOT stored in DB)

**Logic & Behavior**:
```sql
SELECT rs.relation_id, r.subject_entity_id, r.object_entity_id,
       se.canonical_name AS subject_name, oe.canonical_name AS object_name,
       r.canonical_type, rs.summary_text, r.confidence, r.evidence_count,
       r.latest_evidence_at, r.semantic_mode,
       rs.summary_embedding <=> :query_embedding AS distance
FROM relation_summaries rs
JOIN relations r ON rs.relation_id = r.relation_id
JOIN canonical_entities se ON r.subject_entity_id = se.entity_id
JOIN canonical_entities oe ON r.object_entity_id = oe.entity_id
WHERE r.confidence >= :min_confidence
  AND (:entity_ids = '{}' OR r.subject_entity_id = ANY(:entity_ids) OR r.object_entity_id = ANY(:entity_ids))
  AND (:relation_types = '{}' OR r.canonical_type = ANY(:relation_types))
  AND (:semantic_mode IS NULL OR r.semantic_mode = :semantic_mode)
ORDER BY distance ASC
LIMIT :top_k
```

`summary_authority` computed in Python after fetch: `confidence * math.log1p(evidence_count)`.

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_relation_search_returns_summary_authority` | summary_authority computed correctly | unit |
| `test_relation_search_entity_filter` | Only relations involving entity_ids returned | unit |
| `test_relation_search_min_confidence` | Low confidence relations excluded | unit |

---

#### T-C-3-02: POST /api/v1/search/relations Endpoint

**Type**: impl
**depends_on**: [T-C-3-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/routes/search.py` (new)
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` — add schemas

**Pydantic Schemas**:
```python
class RelationSearchRequest(BaseModel):
    query_embedding: list[float] = Field(..., min_length=1024, max_length=1024)
    top_k: int = Field(default=15, ge=1, le=50)
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    entity_ids: list[UUID] = []
    relation_types: list[str] = []
    semantic_mode: Literal["RELATION_STATE", "TEMPORAL_CLAIM"] | None = None

class RelationSearchResultItem(BaseModel):
    relation_id: UUID
    subject: str  # canonical_name
    relation_type: str
    object: str   # canonical_name
    summary: str
    confidence: float
    summary_authority: float
    evidence_count: int
    latest_evidence_at: datetime | None
    semantic_mode: str

class RelationSearchResponse(BaseModel):
    relations: list[RelationSearchResultItem]
```

---

**Validation Gate (Wave C-3)**:
- [ ] ruff check + mypy pass
- [ ] Unit tests pass
- [ ] Endpoint accessible and returns correct schema
- [ ] `summary_authority` is computed in Python (not from DB column)

---

### Wave C-4: FundamentalsRefreshWorker Enhancements

**Goal**: Extend `FundamentalsRefreshWorker` to insert earnings events and upsert is_in_sector/is_in_industry relations.
**Depends on**: A-1 (migration 0002 columns + 003 sector entities seed)
**Estimated effort**: 50–70 min
**Architecture layer**: infrastructure (worker enhancement)

**Pre-read**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/scheduler.py` — Block 13 workers
- Existing `FundamentalsRefreshWorker` code — understand current behavior
- `docs/services/market-data.md` — S3 API for `/fundamentals/{id}/earnings` and `/fundamentals/{id}/company-profile`
- Migration 003 seed file (from A-1-02) — sector entity UUIDs to look up

#### T-C-4-01: Earnings Event Insertion

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/workers/fundamentals_worker.py` — extend

**What to build**:
After existing entity definition + embedding refresh, also call S3 `/fundamentals/{id}/earnings`
and insert earnings events into the `events` table.

**Logic & Behavior**:
1. `GET {S3_BASE_URL}/api/v1/fundamentals/{instrument_id}/earnings` → list of quarterly earnings
2. For each earnings record not yet in `events` WHERE `event_type='earnings_release'` AND `structured_data->>'quarter' = :quarter AND structured_data->>'fiscal_year' = :fy`:
   ```sql
   INSERT INTO events (event_id, event_type, event_subtype, subject_entity_id,
     event_date, event_text, structured_data, extraction_confidence, source_type)
   VALUES (new_uuid7(), 'earnings_release', :quarter_type, :entity_id,
     :report_date, :generated_text, :structured_data_json, 0.95, 'earnings_data')
   ON CONFLICT DO NOTHING
   ```
   - `event_subtype` = "quarterly" or "annual"
   - `structured_data` = `{"eps_actual": ..., "eps_estimate": ..., "revenue_actual": ..., "revenue_estimate": ..., "quarter": "Q3", "fiscal_year": 2024, "beat": true}`
   - `event_text` = f"{entity_name} reported Q{quarter} FY{year} EPS of ${eps_actual:.2f} vs. estimate ${eps_estimate:.2f}"

3. Error handling: HTTP 404 from S3 (no earnings data) → skip; log debug. HTTP 5xx → log warning; continue.

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_earnings_event_inserted` | New earnings record → INSERT called | unit |
| `test_earnings_event_idempotent` | Same earnings record on second run → ON CONFLICT DO NOTHING | unit |
| `test_earnings_s3_404_skipped` | S3 returns 404 → no error, continue | unit |

---

#### T-C-4-02: Sector/Industry Relation Upsert

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/scheduler/workers/fundamentals_worker.py` — extend (same file as T-C-4-01)

**What to build**:
After earnings event insertion, call S3 `/fundamentals/{id}/company-profile` to get sector + industry,
look up the corresponding sector/industry `canonical_entity` (from 003 seed), then upsert
`is_in_sector` and `is_in_industry` relations using the existing advisory-lock upsert path.

**Logic & Behavior**:
1. `GET {S3_BASE_URL}/api/v1/fundamentals/{instrument_id}/company-profile` → `{sector, industry, ...}`
2. Look up sector entity: `SELECT entity_id FROM canonical_entities WHERE canonical_name = :sector AND entity_type = 'sector'`
3. Look up industry entity: similarly
4. For each found entity:
   - Acquire advisory lock on `(subject_entity_id, object_entity_id, canonical_type)` triple hash
   - Upsert `relations` row: `(subject=company_entity, object=sector_entity, canonical_type='is_in_sector', confidence=0.90, semantic_mode='RELATION_STATE')`
   - Insert `relation_evidence_raw` row (source = "EODHD fundamentals", source_weight = 0.90)
5. If sector/industry not found in `canonical_entities` (not seeded) → log warning, skip

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_sector_relation_upserted` | Valid sector → relation inserted | unit |
| `test_sector_entity_not_found_skipped` | Unknown sector name → warning, no error | unit |
| `test_sector_relation_idempotent` | Same company + sector on second run → advisory lock, upsert | unit |

---

**Validation Gate (Wave C-4)**:
- [ ] ruff check + mypy pass on `services/knowledge-graph/`
- [ ] `python -m pytest services/knowledge-graph/tests/ -m unit -v` passes
- [ ] Earnings event insertion is idempotent (ON CONFLICT tested)
- [ ] Sector/industry lookup handles missing entity gracefully


---

## PLAN-0015-D: S8 RAG/Chat Service Foundation

**Service**: S8 (`services/rag-chat/`) — new service
**Rationale**: S8 must be scaffolded before any pipeline work begins. This plan covers the service
skeleton, `rag_db` persistence layer, and conversation management CRUD endpoints.
Depends on all Phase 1 sub-plans (A, B, C-1, C-2) being complete — the clients
used in pipeline waves (E, F) call those new S6/S7 endpoints.

---

### Wave D-1: S8 Domain Layer

**Goal**: Define all domain entities, enums, errors, and value objects for S8. No infrastructure imports.
**Depends on**: none (pure domain)
**Estimated effort**: 35–50 min
**Architecture layer**: domain

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.5 Domain Model Changes (all entities + attributes)
- `services/portfolio/src/portfolio/domain/` — mature service domain layer as structural reference
- `RULES.md` R10 (UUIDv7), R11 (UTC timestamps), R21 (DomainError base class)

#### T-D-1-01: Core Request/Response Domain Entities

**Type**: impl
**depends_on**: none
**blocks**: [T-D-1-02, T-D-1-03, T-D-1-04]
**Target files**:
- `services/rag-chat/src/rag_chat/domain/entities/__init__.py` (new)
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` (new)
- `services/rag-chat/src/rag_chat/domain/enums.py` (new)
- `services/rag-chat/src/rag_chat/domain/value_objects.py` (new)
- `services/rag-chat/src/rag_chat/domain/errors.py` (new)

**What to build**:
All domain types defined in PRD §6.5. Frozen dataclasses (immutable after creation).

**Entities / Components**:

**`QueryIntent` enum**:
```python
class QueryIntent(str, Enum):
    FACTUAL_LOOKUP = "FACTUAL_LOOKUP"
    RELATIONSHIP = "RELATIONSHIP"
    SIGNAL_INTEL = "SIGNAL_INTEL"
    FINANCIAL_DATA = "FINANCIAL_DATA"
    COMPARISON = "COMPARISON"
    REASONING = "REASONING"
    PORTFOLIO = "PORTFOLIO"
```

**`ItemType` enum**: `chunk`, `relation`, `claim`, `event`, `financial`, `cypher_path`
**`MessageRole` enum**: `user`, `assistant`

**`DateRange`** (frozen dataclass, value object):
- `start: date | None`, `end: date | None`
- `__post_init__`: if both set, assert start <= end

**`ChatContext`** (frozen dataclass):
- `entity_ids: tuple[UUID, ...] = ()` — tuple (immutable); max 5 (validated in __post_init__)
- `date_range: DateRange | None = None`

**`ChatRequest`** (frozen dataclass):
- `message: str` — 1–2000 chars, HTML-stripped before construction
- `thread_id: UUID | None`
- `context: ChatContext`
- `tenant_id: UUID`
- `user_id: UUID`

**`ResolvedEntity`** (frozen dataclass):
- `entity_id: UUID`, `canonical_name: str`, `entity_type: str`
- `confidence: float`, `ticker: str | None`, `matched_text: str`

**`CitationMeta`** (frozen dataclass):
- `title: str | None`, `url: str | None`
- `source_name: str | None`, `published_at: datetime | None`
- `entity_name: str | None`

**`RetrievedItem`** (frozen dataclass):
- `item_id: str`, `item_type: ItemType`, `text: str`
- `score: float`, `recency_score: float`, `trust_weight: float`
- `fusion_score: float` — MUST equal `score * recency_score * trust_weight`
- `entity_id: UUID | None`, `doc_id: UUID | None`
- `published_at: datetime | None`
- `citation_meta: CitationMeta`
- `graph_enrichment: tuple[dict, ...] = ()`
- **Invariant**: `abs(fusion_score - score * recency_score * trust_weight) < 1e-9`
- **Factory**: `@classmethod def create(...) -> "RetrievedItem"` — computes fusion_score automatically

`recency_score` computation:
```python
import math
def compute_recency_score(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.5
    days_old = (datetime.now(tz=timezone.utc) - published_at).days
    return math.exp(-0.005 * days_old)
```

**`ResolvedQuery`** (frozen dataclass):
- `intent: QueryIntent`, `sub_questions: tuple[str, ...]`
- `resolved_entities: tuple[ResolvedEntity, ...]`
- `rephrased_query: str`, `hyde_hypothesis: str | None`

**`RetrievalPlan`** (frozen dataclass):
- `use_chunks: bool`, `use_relations: bool`, `use_graph: bool`
- `use_claims: bool`, `use_events: bool`, `use_contradictions: bool`
- `use_financial: bool`, `use_portfolio: bool`, `use_cypher: bool`
- `entity_ids: tuple[UUID, ...]`, `date_filter: DateRange | None`

**`RagError`** (base, extends DomainError):
```python
class RagError(Exception): pass  # R21: DomainError base
class InsufficientRetrievalError(RagError): pass
class ThreadNotFoundError(RagError): pass
class RateLimitExceededError(RagError): pass
class ProviderUnavailableError(RagError): pass
class PromptInjectionError(RagError): pass
class PIIDetectedError(RagError): pass
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_retrieved_item_fusion_score_invariant` | `fusion_score = score * recency * trust` | HIGH/unit |
| `test_recency_score_365_days` | 365-day-old item → ~0.16 | HIGH/unit |
| `test_recency_score_none_published_at` | None published_at → 0.5 | unit |
| `test_chat_context_max_5_entity_ids` | 6 entity_ids → ValueError | unit |
| `test_date_range_start_after_end` | start > end → ValueError | unit |
| `test_query_intent_all_7_values` | All 7 enum values accessible | unit |

**Acceptance criteria**:
- [ ] No infrastructure imports anywhere in `domain/`
- [ ] All dataclasses are frozen (immutable)
- [ ] `RagError` base class follows R21 (inherits from `Exception` with `DomainError` alias)
- [ ] `fusion_score` invariant tested and enforced in `__post_init__`
- [ ] All 6 unit tests pass

---

#### T-D-1-02: Conversation Domain Entities

**Type**: impl
**depends_on**: [T-D-1-01]
**blocks**: [T-D-2-01]
**Target files**:
- `services/rag-chat/src/rag_chat/domain/entities/conversation.py` (new)

**What to build**:
`ConversationThread`, `Message`, `Citation`, `ContradictionRef` entities for conversation persistence.

**Entities / Components**:

**`Citation`** (frozen dataclass):
- `ref: int`, `item_type: str` ("chunk"|"relation"|"claim"|"event"|"financial")
- `id: str`, `title: str | None`, `url: str | None`
- `source_name: str | None`, `published_at: datetime | None`
- `entity_name: str | None`, `confidence: float | None`

**`ContradictionRef`** (frozen dataclass):
- `claim_type: str`, `strength: float`
- `sides: tuple[dict, ...]`

**`Message`** (frozen dataclass):
- `message_id: UUID`, `thread_id: UUID`
- `role: MessageRole`, `content: str`
- `intent: QueryIntent | None`
- `resolved_entities: tuple[ResolvedEntity, ...]`
- `citations: tuple[Citation, ...]`
- `contradiction_refs: tuple[ContradictionRef, ...]`
- `provider: str | None`, `model: str | None`
- `token_count_in: int | None`, `token_count_out: int | None`
- `latency_ms: int | None`, `created_at: datetime`

**`ConversationThread`** (frozen dataclass):
- `thread_id: UUID`, `tenant_id: UUID`, `user_id: UUID`
- `title: str | None`, `entity_ids: tuple[UUID, ...]`
- `messages: tuple[Message, ...]`
- `archived_at: datetime | None`, `created_at: datetime`, `updated_at: datetime`
- **Invariant**: `len(messages) >= 0`
- **Property**: `is_active: bool` = `archived_at is None`
- **Property**: `recent_history(n: int) -> tuple[Message, ...]` — last n messages

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_thread_is_active_when_not_archived` | archived_at=None → is_active=True | unit |
| `test_thread_recent_history` | 7 messages, n=5 → last 5 returned | unit |

---

**Validation Gate (Wave D-1)**:
- [ ] ruff check + mypy (strict) pass on `services/rag-chat/src/rag_chat/domain/`
- [ ] No imports from `infrastructure/`, `application/`, or third-party libs in domain files
- [ ] All 8 unit tests pass

---

### Wave D-2: rag_db Infrastructure (Models + Alembic + UoW)

**Goal**: Create SQLAlchemy models, Alembic migration, repository implementations, and UoW for `rag_db`.
**Depends on**: D-1 (domain entities)
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure

**Pre-read**:
- `services/portfolio/src/portfolio/infrastructure/db/` — mature UoW + session factory pattern
- `RULES.md` R23 (dual DB URLs), R26 (no auto-commit in aexit), R27 (ReadOnlyUoW)
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.4 — exact column types, indexes

#### T-D-2-01: SQLAlchemy Models

**Type**: impl
**depends_on**: [T-D-1-02]
**blocks**: [T-D-2-02, T-D-2-03]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/db/models/__init__.py`
- `services/rag-chat/src/rag_chat/infrastructure/db/models/thread.py`
- `services/rag-chat/src/rag_chat/infrastructure/db/models/message.py`

**What to build**:

**`ThreadModel`**:
```python
class ThreadModel(Base):
    __tablename__ = "threads"
    thread_id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID, nullable=False)
    user_id: Mapped[UUID] = mapped_column(PgUUID, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    entity_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID), default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    last_msg_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    messages: Mapped[list["MessageModel"]] = relationship(
        "MessageModel", back_populates="thread", order_by="MessageModel.created_at"
    )
```

**`MessageModel`**:
```python
class MessageModel(Base):
    __tablename__ = "messages"
    message_id: Mapped[UUID] = mapped_column(PgUUID, primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(PgUUID, ForeignKey("threads.thread_id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50))
    resolved_entities: Mapped[dict | None] = mapped_column(JSONB)
    retrieval_plan: Mapped[dict | None] = mapped_column(JSONB)
    citations: Mapped[dict | None] = mapped_column(JSONB)
    contradiction_refs: Mapped[dict | None] = mapped_column(JSONB)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    token_count_in: Mapped[int | None] = mapped_column(Integer)
    token_count_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False)
    thread: Mapped["ThreadModel"] = relationship("ThreadModel", back_populates="messages")
```

---

#### T-D-2-02: Alembic Migration + DDL Alignment Test

**Type**: schema
**depends_on**: [T-D-2-01]
**blocks**: [T-D-2-03]
**Target files**:
- `services/rag-chat/alembic/versions/0001_create_rag_db.py` (new)
- `services/rag-chat/tests/unit/infrastructure/test_ddl_alignment.py` (new)

**Migration DDL** (exact columns from PRD §6.4):
```sql
-- threads table
CREATE TABLE threads (
    thread_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    title TEXT,
    entity_ids UUID[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_msg_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ
);
CREATE INDEX ix_threads_user_active ON threads(user_id, tenant_id, last_msg_at DESC)
    WHERE archived_at IS NULL;
CREATE INDEX ix_threads_tenant_active ON threads(tenant_id, last_msg_at DESC)
    WHERE archived_at IS NULL;

-- messages table
CREATE TABLE messages (
    message_id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    intent VARCHAR(50),
    resolved_entities JSONB,
    retrieval_plan JSONB,
    citations JSONB,
    contradiction_refs JSONB,
    provider VARCHAR(50),
    model VARCHAR(100),
    token_count_in INT,
    token_count_out INT,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_messages_thread_created ON messages(thread_id, created_at ASC);
```

**Downstream test impact**: DDL alignment test verifies ORM column names/types match migration.

---

#### T-D-2-03: Repositories + UnitOfWork

**Type**: impl
**depends_on**: [T-D-2-02]
**blocks**: [T-D-3-01]
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/thread_repository.py` (port interface)
- `services/rag-chat/src/rag_chat/application/ports/message_repository.py` (port interface)
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/thread_repository.py`
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/message_repository.py`
- `services/rag-chat/src/rag_chat/infrastructure/db/unit_of_work.py`

**What to build**:
Repository implementations + R26-compliant UoW (no auto-commit in `__aexit__`).

**`ThreadRepository`** methods:
- `async get(thread_id: UUID, user_id: UUID) -> ConversationThread | None` — includes messages; ownership check embedded
- `async list_active(user_id: UUID, tenant_id: UUID, limit: int, offset: int) -> tuple[list[ConversationThread], int]`
- `async create(thread: ConversationThread) -> None`
- `async update_last_msg(thread_id: UUID, last_msg_at: datetime, entity_ids: list[UUID]) -> None`
- `async soft_delete(thread_id: UUID) -> datetime` — sets archived_at, returns value

**`MessageRepository`** methods:
- `async create(message: Message) -> None`
- `async list_by_thread(thread_id: UUID, limit: int) -> list[Message]`

**UoW** (R26 — no auto-commit):
```python
class RagUnitOfWork:
    async def __aenter__(self) -> "RagUnitOfWork": ...
    async def __aexit__(self, exc_type, exc, tb) -> None:
        # ONLY rollback on exception; NEVER commit; close session in finally
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

**R23 dual-URL support**: `create_rag_session_factory(write_url, read_url=None)` with read fallback.

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_uow_no_auto_commit_on_exit` | Context exit without commit → no DB write | unit |
| `test_thread_repo_get_ownership` | get() with wrong user_id → None | unit |
| `test_thread_repo_soft_delete` | archived_at set; list_active excludes it | unit |

---

**Validation Gate (Wave D-2)**:
- [ ] ruff check + mypy pass
- [ ] `alembic upgrade head` + `downgrade -1` succeed on fresh rag_db
- [ ] DDL alignment test passes
- [ ] UoW `__aexit__` does NOT call `commit()` (enforced by test)

---

### Wave D-3: Service Scaffold + Config + Docker

**Goal**: Create pyproject.toml, settings, app.py, health endpoints, Docker compose entry, and env example.
**Depends on**: D-2 (session factory needed in lifespan)
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure + config

**Pre-read**:
- `services/alert/pyproject.toml` — recent service pyproject.toml as template
- `services/portfolio/src/portfolio/infrastructure/app_factory.py` — PLAN-0003 lifespan pattern
- `infra/compose/docker-compose.yml` — existing service entries

#### T-D-3-01: pyproject.toml + Settings

**Type**: config
**depends_on**: none
**blocks**: [T-D-3-02]
**Target files**:
- `services/rag-chat/pyproject.toml` (new)
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py` (new)

**pyproject.toml dependencies** (key):
```
python = ">=3.11,<3.13"
fastapi = ">=0.111"
uvicorn = ">=0.27"
sqlalchemy = {version = ">=2.0", extras = ["asyncio"]}
asyncpg = ">=0.29"
alembic = ">=1.13"
pydantic-settings = ">=2.0"
httpx = ">=0.27"          # upstream service clients
sse-starlette = ">=1.6"   # SSE streaming
bleach = ">=6.0"          # HTML strip
structlog = ">=24.1"
redis = {version = ">=5.0", extras = ["asyncio"]}  # Valkey
prometheus-client = ">=0.20"
openai = ">=1.12"         # OpenAI-compatible SDK for DeepInfra + OpenRouter
```

**`RagChatSettings`** (Pydantic BaseSettings, env_prefix="RAG_CHAT_"):
```python
class RagChatSettings(BaseSettings):
    # Database
    rag_db_url: str                    # RAG_CHAT_RAG_DB_URL
    rag_db_url_read: str | None = None # RAG_CHAT_RAG_DB_URL_READ

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_classification_model: str = "qwen2.5:3b"
    ollama_completion_model: str = "deepseek-r1:32b"  # emergency last resort only
    ollama_reranker_model: str = "bge-reranker-v2-m3"

    # LLM API providers (primary + fallback; same model different providers)
    deepinfra_api_key: str | None = None      # primary: deepseek-r1-distill-qwen-32b
    openrouter_api_key: str | None = None     # fallback: deepseek/deepseek-r1-distill-qwen-32b

    # Upstream services
    s6_base_url: str = "http://nlp-pipeline:8006"
    s7_base_url: str = "http://knowledge-graph:8007"
    s3_base_url: str = "http://market-data:8003"
    s1_base_url: str = "http://portfolio:8001"
    s1_internal_token: str

    # Feature flags
    cypher_enabled: bool = False

    # Rate limiting
    rate_limit_per_tenant: int = 10   # requests per minute
    upstream_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(env_prefix="RAG_CHAT_", env_file=".env")
```

---

#### T-D-3-02: app.py Lifespan + Health Endpoints + Docker

**Type**: impl
**depends_on**: [T-D-3-01]
**blocks**: [T-D-4-01]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/app.py` (new)
- `services/rag-chat/src/rag_chat/__main__.py` — uvicorn entry point
- `infra/compose/docker-compose.yml` — add rag-chat service entry
- `services/rag-chat/configs/rag-chat.env.example` (new)

**app.py lifespan** (R22 — no background tasks):
```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(service_name="rag-chat")
    configure_tracing(service_name="rag-chat")
    settings = get_settings()
    app.state.rag_session_factory = create_rag_session_factory(settings.rag_db_url, settings.rag_db_url_read)
    app.state.valkey = await create_valkey_client(settings.valkey_url)
    yield
    await app.state.valkey.aclose()
```

**Health endpoints**:
- `GET /healthz` → always `{"status": "ok"}` 200
- `GET /readyz` → SELECT 1 on rag_db + Ollama GET /api/tags + Valkey PING; 503 if any fail
- `GET /metrics` → Prometheus text format

**GET /api/v1/providers/status**:
```python
# Returns current provider availability from negative cache
# {"providers": [{"name": "deepinfra", "available": true, "last_failure_at": null, "model": "deepseek-r1-distill-qwen-32b"}, {"name": "openrouter", ...}, {"name": "ollama", ...}]}
```

**Docker compose entry**:
```yaml
rag-chat:
  build: services/rag-chat
  command: python -m rag_chat
  ports: ["8008:8008"]
  environment:
    - RAG_CHAT_RAG_DB_URL=${RAG_CHAT_DB_URL}
    - RAG_CHAT_VALKEY_URL=${VALKEY_URL}
    - RAG_CHAT_OLLAMA_BASE_URL=${OLLAMA_BASE_URL}
  depends_on: [postgres, valkey, ollama]
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_healthz_always_200` | GET /healthz → 200 even with no infra | unit |
| `test_readyz_503_on_db_failure` | DB unavailable → 503 | unit |
| `test_providers_status_200` | GET /api/v1/providers/status → 200 | unit |

---

**Validation Gate (Wave D-3)**:
- [ ] ruff check + mypy pass on all new files
- [ ] Service starts with `python -m rag_chat` (lifespan completes)
- [ ] All 3 health endpoint tests pass
- [ ] Docker compose entry is valid YAML

---

### Wave D-4: Conversation Management CRUD

**Goal**: Implement thread/message use cases and `/threads` API endpoints.
**Depends on**: D-3 (UoW dependency injection wired in app.py)
**Estimated effort**: 45–60 min
**Architecture layer**: application + API

**Pre-read**:
- `services/portfolio/src/portfolio/application/use_cases/` — use case structure
- `services/portfolio/src/portfolio/api/routes/` — route/dependency pattern
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.2 thread endpoints

#### T-D-4-01: Thread Use Cases

**Type**: impl
**depends_on**: [T-D-2-03]
**blocks**: [T-D-4-02]
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/create_thread.py` (new)
- `services/rag-chat/src/rag_chat/application/use_cases/list_threads.py` (new)
- `services/rag-chat/src/rag_chat/application/use_cases/get_thread.py` (new)
- `services/rag-chat/src/rag_chat/application/use_cases/delete_thread.py` (new)

**`CreateThreadUseCase`**:
```python
async def execute(user_id: UUID, tenant_id: UUID, title: str | None, entity_ids: list[UUID]) -> ConversationThread:
    thread = ConversationThread(
        thread_id=new_uuid7(), tenant_id=tenant_id, user_id=user_id,
        title=title, entity_ids=tuple(entity_ids), messages=(),
        archived_at=None, created_at=utc_now(), updated_at=utc_now()
    )
    await uow.threads.create(thread)
    await uow.commit()
    return thread
```

**`ListThreadsUseCase`** (ReadOnlyUoW — R27):
- Returns paginated active threads for `(user_id, tenant_id)`
- `limit` max 100; `offset` ≥ 0

**`GetThreadUseCase`** (ReadOnlyUoW — R27):
- Calls `thread_repo.get(thread_id, user_id)` → returns thread with messages or raises `ThreadNotFoundError`

**`DeleteThreadUseCase`**:
- Sets `archived_at = utc_now()`; raises `ThreadNotFoundError` if not found or wrong owner

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_create_thread_uses_uuidv7` | thread_id is valid UUIDv7 | unit |
| `test_delete_thread_sets_archived_at` | Soft delete → archived_at set | unit |
| `test_list_threads_excludes_archived` | Archived threads not returned | unit |
| `test_get_thread_wrong_owner_raises` | Wrong user_id → ThreadNotFoundError | unit |

---

#### T-D-4-02: Thread API Endpoints

**Type**: impl
**depends_on**: [T-D-4-01]
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/api/routes/threads.py` (new)
- `services/rag-chat/src/rag_chat/api/schemas.py` — Thread/Message Pydantic schemas
- `services/rag-chat/src/rag_chat/api/dependencies.py` — inject UoW, headers

**Request/Response schemas**:
```python
class CreateThreadRequest(BaseModel):
    title: str | None = Field(None, max_length=200)
    entity_ids: list[UUID] = Field(default=[], max_length=5)

class ThreadSummaryResponse(BaseModel):
    thread_id: UUID; title: str | None; last_msg_at: datetime | None
    message_count: int; entity_ids: list[UUID]; created_at: datetime

class ThreadDetailResponse(BaseModel):
    thread_id: UUID; title: str | None; created_at: datetime
    messages: list[MessageResponse]

class MessageResponse(BaseModel):
    message_id: UUID; role: str; content: str; intent: str | None
    citations: list[dict]; created_at: datetime
```

**Endpoints**:
- `POST /api/v1/threads` → 201 `{thread_id, title, created_at}`
- `GET /api/v1/threads?limit=20&offset=0&archived=false` → 200 `{threads: [...], total}`
- `GET /api/v1/threads/{thread_id}` → 200 `ThreadDetailResponse` or 404
- `DELETE /api/v1/threads/{thread_id}` → 200 `{thread_id, archived_at}` or 404

**Auth**: Extract `X-Tenant-Id` and `X-User-Id` headers (injected by S9); 401 if missing.

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_create_thread_endpoint` | POST /threads → 201 | unit |
| `test_list_threads_endpoint` | GET /threads → 200 with pagination | unit |
| `test_get_thread_endpoint_not_found` | Unknown thread_id → 404 | unit |
| `test_delete_thread_endpoint` | DELETE → 200 with archived_at | unit |
| `test_threads_require_auth_headers` | Missing X-Tenant-Id → 401 | unit |

**Acceptance criteria**:
- [ ] All endpoints use use cases (R25: no direct infra imports in routes)
- [ ] Thread endpoints reject missing auth headers with 401
- [ ] 5 unit tests pass

---

**Validation Gate (Wave D-4)**:
- [ ] ruff check + mypy pass
- [ ] All 9 domain + thread use case tests pass
- [ ] Thread endpoints accessible and returning correct schemas

---

## PLAN-0015-E: S8 Pipeline — Query Processing

**Service**: S8 (`services/rag-chat/`)
**Rationale**: Steps 0–4 of the pipeline (input validation, intent classification, HyDE, service clients).
These are prerequisites for the retrieval and response waves (F).
**Depends on**: D-4 complete (service scaffold wired)

---

### Wave E-1: Input Validation + Rate Limiting + Completion Cache

**Goal**: Implement the security and caching layer that fronts every chat request.
**Depends on**: D-3 (Valkey client available)
**Estimated effort**: 40–55 min
**Architecture layer**: application (security + caching)

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Step 0, §8.3 Input Validation
- `docs/BUG_PATTERNS.md` — BP relevant to prompt injection patterns
- `RULES.md` R15 (input sanitization)

#### T-E-1-01: InputValidator

**Type**: impl
**depends_on**: none
**blocks**: [T-E-1-04]
**Target files**:
- `services/rag-chat/src/rag_chat/application/security/input_validator.py` (new)

**What to build**:
Stateless input validator for chat messages. Applied before any LLM or DB interaction.

**Logic & Behavior**:
```python
class InputValidator:
    # PII patterns (compile once at class level)
    _PHONE_RE = re.compile(r'\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
    _EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
    _SSN_RE = re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b')
    _CARD_RE = re.compile(r'\b(?:\d[ -]?){13,19}\b')

    # Prompt injection patterns (case-insensitive)
    _INJECTION_PATTERNS = [
        r"ignore\s+(previous|prior|all)\s+instructions",
        r"system\s*:",
        r"you\s+are\s+now",
        r"pretend\s+to\s+be",
        r"forget\s+your\s+instructions",
        r"<\s*/?system\s*>",
        r"assistant\s*:",  # context-sensitive: only block if at start of line
    ]

    def validate(self, message: str) -> str:
        # 1. HTML strip
        message = bleach.clean(message, tags=[], strip=True)
        # 2. Truncate to 2000 chars
        message = message[:2000]
        # 3. PII check
        for pattern in [self._PHONE_RE, self._EMAIL_RE, self._SSN_RE, self._CARD_RE]:
            if pattern.search(message):
                raise PIIDetectedError("Message contains PII")
        # 4. Injection heuristic
        for pattern in self._INJECTION_PATTERNS:
            if re.search(pattern, message, re.IGNORECASE):
                raise PromptInjectionError("Potential prompt injection detected")
        # 5. XML-wrap to prevent injection bleed
        token = secrets.token_hex(4)
        return f"<Q_{token}>{message}</Q_{token}>"
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_validate_strips_html` | `<script>alert()</script>` stripped | CRITICAL/unit |
| `test_validate_blocks_phone_pii` | US phone number → PIIDetectedError | CRITICAL/unit |
| `test_validate_blocks_email_pii` | email@example.com → PIIDetectedError | CRITICAL/unit |
| `test_validate_blocks_injection_ignore_prev` | "ignore previous instructions" → PromptInjectionError | CRITICAL/unit |
| `test_validate_blocks_injection_system_colon` | "system:" → PromptInjectionError | CRITICAL/unit |
| `test_validate_wraps_in_xml_tag` | Output starts with `<Q_` | unit |
| `test_validate_truncates_2000_chars` | 2500 char input → 2000 chars in output | unit |

---

#### T-E-1-02: RateLimiter + CompletionCache

**Type**: impl
**depends_on**: none (uses Valkey client via dependency injection)
**blocks**: [T-E-1-04]
**Target files**:
- `services/rag-chat/src/rag_chat/application/caching/rate_limiter.py` (new)
- `services/rag-chat/src/rag_chat/application/caching/completion_cache.py` (new)

**`RateLimiter`** (sliding window):
```python
class RateLimiter:
    async def check_and_increment(self, tenant_id: UUID) -> None:
        key = f"rag:v1:rl:{tenant_id}"
        # ZADD key now score=member; ZREMRANGEBYSCORE key 0 (now-60s); ZCARD key
        # If count >= limit: raise RateLimitExceededError
        # Key TTL: 60s (set on every check)
```

**`CompletionCache`**:
```python
class CompletionCache:
    async def get(self, message: str, thread_id: UUID | None) -> dict | None:
        key = f"rag:v1:completion:{sha256(f'{message}:{thread_id}')}"
        data = await self._valkey.get(key)
        return json.loads(data) if data else None

    async def set(self, message: str, thread_id: UUID | None, response: dict) -> None:
        # SETEX key 86400 (24h) json.dumps(response)
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_rate_limiter_allows_10_per_min` | 10 requests → allowed | unit |
| `test_rate_limiter_blocks_11th` | 11th in 60s window → RateLimitExceededError | unit |
| `test_completion_cache_hit` | Get after set → returns cached response | unit |
| `test_completion_cache_miss` | New key → None | unit |

---

**Validation Gate (Wave E-1)**:
- [ ] ruff check + mypy pass
- [ ] 11 security tests pass (all CRITICAL marked)
- [ ] Rate limiter uses Valkey sliding window (not simple counter)

---

### Wave E-2: Intent Classifier + HyDE Expander + Retrieval Plan Builder

**Goal**: Steps 3 and 4 of the pipeline — classify query intent and generate HyDE hypothesis.
**Depends on**: E-1 (settings pattern established)
**Estimated effort**: 50–65 min
**Architecture layer**: application (ML orchestration)

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Steps 3–4, AD-06 (local LLM)
- `services/knowledge-graph/src/knowledge_graph/application/` — how other services call Ollama
- `services/nlp-pipeline/.claude-context.md` — OllamaEmbeddingAdapter pattern (for HyDE embedding)

#### T-E-2-01: Intent Classifier (Ollama + Keyword Fallback)

**Type**: impl
**depends_on**: none
**blocks**: [T-E-2-03]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` (new)

**What to build**:
Two-tier classifier: Ollama qwen2.5:3b primary, keyword heuristic fallback.

**`OllamaIntentClassifier`**:
```python
class OllamaIntentClassifier:
    async def classify(self, message: str, conversation_history: list[dict],
                       resolved_entities: list[ResolvedEntity]) -> tuple[QueryIntent, list[str], str]:
        # Returns (intent, sub_questions, rephrased_query)
        prompt = build_intent_classification_prompt(message, conversation_history, resolved_entities)
        response = await httpx.post(f"{self._ollama_url}/api/generate",
            json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False, "format": "json"},
            timeout=5.0)
        result = parse_intent_response(response.json()["response"])
        return result.intent, result.sub_questions, result.rephrased_query
```

Classification prompt (few-shot, 7 examples — one per intent):
```
You are a query intent classifier for a financial intelligence system.
Classify the query into exactly one of: FACTUAL_LOOKUP, RELATIONSHIP, SIGNAL_INTEL,
FINANCIAL_DATA, COMPARISON, REASONING, PORTFOLIO.

For COMPARISON queries with multiple entities, extract sub_questions (one per entity).
For REASONING queries, rephrase as a standalone question using the conversation context.

Examples:
- "Who is Apple's CEO?" → {"intent": "FACTUAL_LOOKUP", "sub_questions": [], "rephrased_query": "Who is the CEO of Apple Inc.?"}
- "Why is Apple's margin declining?" → {"intent": "REASONING", ...}
- "Compare TSLA vs RIVN margins" → {"intent": "COMPARISON", "sub_questions": ["What are Tesla's margins?", "What are Rivian's margins?"], ...}
- "What risks affect my holdings?" → {"intent": "PORTFOLIO", ...}
[... all 7 examples ...]

Query: {message}
Conversation context: {history}
Resolved entities: {entities}
Respond with JSON only: {"intent": "...", "sub_questions": [...], "rephrased_query": "..."}
```

**`KeywordHeuristicClassifier`** (fallback when Ollama down):
```python
_INTENT_KEYWORDS = {
    QueryIntent.PORTFOLIO: ["portfolio", "holdings", "my stocks", "my shares", "watchlist"],
    QueryIntent.COMPARISON: ["compare", "vs", "versus", "difference between", "better than"],
    QueryIntent.REASONING: ["why", "reason", "explain", "cause", "because", "how come"],
    QueryIntent.RELATIONSHIP: ["supply chain", "subsidiaries", "owns", "acquired", "parent company"],
    QueryIntent.FINANCIAL_DATA: ["price", "p/e", "revenue", "earnings", "ratio", "ebitda"],
    QueryIntent.SIGNAL_INTEL: ["news", "announced", "filed", "reported", "allegations"],
    # default: FACTUAL_LOOKUP
}
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_keyword_classifier_portfolio` | "my holdings" → PORTFOLIO | unit |
| `test_keyword_classifier_comparison` | "compare X vs Y" → COMPARISON | unit |
| `test_keyword_classifier_reasoning` | "why is X falling" → REASONING | unit |
| `test_keyword_classifier_default` | "who is the CEO" → FACTUAL_LOOKUP | unit |
| `test_ollama_classifier_falls_back_on_error` | Ollama timeout → keyword heuristic used | unit |

---

#### T-E-2-02: HyDE Expander + Retrieval Plan Builder

**Type**: impl
**depends_on**: none
**blocks**: [T-E-2-03]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/hyde_expander.py` (new)
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py` (new)

**`HydeExpander`**:
```python
class HydeExpander:
    _HYDE_INTENTS = {QueryIntent.SIGNAL_INTEL, QueryIntent.FACTUAL_LOOKUP,
                     QueryIntent.RELATIONSHIP, QueryIntent.REASONING}

    async def expand(self, rephrased_query: str, intent: QueryIntent) -> tuple[str | None, list[float] | None]:
        # Returns (hypothesis_text, hypothesis_embedding)
        if intent not in self._HYDE_INTENTS:
            return None, None

        # Check Valkey cache
        cache_key = f"rag:v1:hyde:{sha256(rephrased_query)}"
        cached = await self._valkey.get(cache_key)
        if cached:
            data = json.loads(cached)
            return data["text"], data["embedding"]

        # Generate hypothesis via DeepInfra DeepSeek R1 Distill 32B (fallback: OpenRouter)
        prompt = (
            f"Write a factual 80-120 word answer paragraph as if it appeared in a financial report:\n\n{rephrased_query}"
        )
        hypothesis = ""
        async for chunk in self._llm_provider_chain.stream(prompt, max_tokens=200, temperature=0.1):
            hypothesis += chunk
        hypothesis = hypothesis.strip()

        # Embed hypothesis using S6 embedding (nomic-embed-text)
        embedding = await self._embedding_client.embed(hypothesis)

        # Cache 30 min
        await self._valkey.setex(cache_key, 1800, json.dumps({"text": hypothesis, "embedding": embedding}))
        return hypothesis, embedding
```

**`RetrievalPlanBuilder`** — maps `QueryIntent` → `RetrievalPlan`:
```python
_INTENT_TO_PLAN = {
    QueryIntent.FACTUAL_LOOKUP:  RetrievalPlan(use_chunks=True, use_relations=True, use_graph=True, use_claims=True, use_events=False, use_contradictions=True, use_financial=False, use_portfolio=False, use_cypher=False),
    QueryIntent.RELATIONSHIP:    RetrievalPlan(use_chunks=False, use_relations=True, use_graph=True, use_claims=False, use_events=False, use_contradictions=False, use_financial=False, use_portfolio=False, use_cypher=True),
    QueryIntent.SIGNAL_INTEL:    RetrievalPlan(use_chunks=True, use_relations=False, use_graph=False, use_claims=True, use_events=True, use_contradictions=True, use_financial=False, use_portfolio=False, use_cypher=False),
    QueryIntent.FINANCIAL_DATA:  RetrievalPlan(use_chunks=False, use_relations=False, use_graph=False, use_claims=True, use_events=True, use_contradictions=False, use_financial=True, use_portfolio=False, use_cypher=False),
    QueryIntent.COMPARISON:      RetrievalPlan(use_chunks=True, use_relations=True, use_graph=False, use_claims=True, use_events=True, use_contradictions=True, use_financial=True, use_portfolio=False, use_cypher=False),
    QueryIntent.REASONING:       RetrievalPlan(use_chunks=True, use_relations=True, use_graph=True, use_claims=True, use_events=True, use_contradictions=True, use_financial=True, use_portfolio=False, use_cypher=True),
    QueryIntent.PORTFOLIO:       RetrievalPlan(use_chunks=True, use_relations=True, use_graph=True, use_claims=True, use_events=True, use_contradictions=True, use_financial=True, use_portfolio=True, use_cypher=False),
}
# use_cypher is ANDed with settings.cypher_enabled at runtime
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_hyde_skipped_for_financial_data` | FINANCIAL_DATA → (None, None) | HIGH/unit |
| `test_hyde_generates_hypothesis` | REASONING → non-empty hypothesis string | unit |
| `test_hyde_cached` | Second call same query → Valkey hit, LLM API not called | unit |
| `test_retrieval_plan_portfolio` | PORTFOLIO → use_portfolio=True | unit |
| `test_retrieval_plan_cypher_gated` | cypher_enabled=False → use_cypher=False even for RELATIONSHIP | unit |

---

**Validation Gate (Wave E-2)**:
- [ ] ruff check + mypy pass
- [ ] All 9 tests pass
- [ ] `use_cypher` is `False` when `settings.cypher_enabled=False` regardless of intent

---

### Wave E-3: Upstream Service HTTP Clients

**Goal**: Implement all HTTP client adapters for upstream services (S6, S7, S3, S1).
**Depends on**: D-3 (settings with base URLs)
**Estimated effort**: 45–60 min
**Architecture layer**: infrastructure (adapters)

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.3 — each endpoint's request/response schema
- `services/portfolio/src/portfolio/infrastructure/` — HTTP client patterns if any

#### T-E-3-01: Base HTTP Client + S6 Client

**Type**: impl
**depends_on**: none
**blocks**: [T-F-1-01]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/clients/base.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/clients/s6_client.py` (new)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (port interfaces)

**`BaseUpstreamClient`**:
```python
class BaseUpstreamClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = await self._client.post(path, json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return {}
        except httpx.HTTPStatusError as exc:
            logger.warning("upstream_http_error", path=path, status=exc.response.status_code)
            return {}
```

**`S6Client`**:
- `async resolve_entities(query_text: str) -> list[ResolvedEntity]`
  → POST `/api/v1/entities/resolve`
- `async search_chunks(request: ChunkSearchRequest) -> list[EnrichedChunkResult]`
  → POST `/api/v1/search/chunks`; returns empty list on timeout (R9 — safe degradation)

---

#### T-E-3-02: S7 Client

**Type**: impl
**depends_on**: none
**blocks**: [T-F-1-01]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/clients/s7_client.py` (new)

**`S7Client`**:
- `async search_relations(embedding: list[float], entity_ids: list[UUID], ...) -> list[RelationResult]`
  → POST `/api/v1/search/relations`
- `async get_egocentric_graph(entity_id: UUID, min_confidence: float, limit: int) -> EgocentricGraph`
  → GET `/api/v1/entities/{id}/graph`
- `async search_claims(entity_ids: list[UUID], ...) -> list[ClaimResult]`
  → POST `/api/v1/claims/search`
- `async search_events(entity_ids: list[UUID], ...) -> list[EventResult]`
  → POST `/api/v1/events/search`
- `async get_contradictions(entity_id: UUID, top_k: int) -> list[ContradictionResult]`
  → GET `/api/v1/entities/{id}/contradictions`
- `async cypher_traverse(cypher: str, params: dict, max_results: int) -> list[dict]`
  → POST `/api/v1/graph/cypher`; raises `FeatureDisabledError` if 501 returned

---

#### T-E-3-03: S3 + S1 Clients

**Type**: impl
**depends_on**: none
**blocks**: [T-F-1-01]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/clients/s3_client.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/clients/s1_client.py` (new)

**`S3Client`** (financial data):
- `async get_fundamentals_highlights(instrument_id: UUID) -> dict`
  → GET `/api/v1/fundamentals/{id}/highlights`
- `async get_earnings(instrument_id: UUID) -> list[dict]`
  → GET `/api/v1/fundamentals/{id}/earnings`
- `async get_quote(instrument_id: UUID) -> dict`
  → GET `/api/v1/quotes/{id}`
- `async find_instrument_by_ticker(ticker: str) -> UUID | None`
  → GET `/api/v1/instruments/symbol/{ticker}`

**`S1Client`** (portfolio context):
- `async get_portfolio_context(user_id: UUID, tenant_id: UUID, x_internal_token: str) -> PortfolioContext | None`
  → GET `/api/v1/users/{user_id}/portfolio/context`; include `X-Internal-Token` and `X-User-Id` headers
  → Cache in Valkey: `s1:v1:portfolio_ctx:{user_id}` TTL=300s

**Tests to write** (one per client):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_s6_client_resolve_returns_empty_on_timeout` | Timeout → empty list, no exception | unit |
| `test_s7_client_claims_returns_empty_on_5xx` | 503 → empty list | unit |
| `test_s1_client_portfolio_ctx_cached` | Second call → Valkey cache hit | unit |
| `test_s7_cypher_501_returns_empty` | 501 response → empty list (feature disabled gracefully) | unit |

**Acceptance criteria**:
- [ ] ALL client methods return empty/None on timeout or HTTP error (never raise to caller)
- [ ] S1 client includes required auth headers
- [ ] Unit tests pass

---

**Validation Gate (Wave E-3)**:
- [ ] ruff check + mypy pass
- [ ] All 4 client tests pass
- [ ] No client method propagates an exception on network/timeout error

---

## PLAN-0015-F: S8 Pipeline — Retrieval + Response + Chat Endpoints

**Service**: S8 (`services/rag-chat/`)
**Rationale**: Steps 5–13 — parallel retrieval, fusion, reranking, context assembly,
LLM completion, and the public `/chat` API endpoints.
**Depends on**: E-3 complete (all upstream clients available)

---

### Wave F-1: Parallel Retrieval Orchestrator + Fusion Scoring

**Goal**: Step 5 (parallel retrieval via asyncio.gather) + Steps 6-7 (graph enrichment + fusion).
**Depends on**: E-3
**Estimated effort**: 50–70 min
**Architecture layer**: application (orchestration)

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Steps 5–7
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` — `RetrievedItem`, `RetrievalPlan`

#### T-F-1-01: Parallel Retrieval Orchestrator

**Type**: impl
**depends_on**: [T-E-3-01, T-E-3-02, T-E-3-03]
**blocks**: [T-F-1-02]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (new)

**What to build**:
Executes Steps 5A–5I concurrently. Each step is wrapped in `asyncio.wait_for(timeout=5.0)`.
On timeout or error, the step returns an empty result (logged at warning level — not fatal).

**Logic & Behavior**:
```python
class ParallelRetrievalOrchestrator:
    async def retrieve(self, plan: RetrievalPlan, resolved_query: ResolvedQuery,
                       request: ChatRequest) -> list[RetrievedItem]:
        tasks = []
        entity_ids = [e.entity_id for e in resolved_query.resolved_entities]

        if plan.use_chunks:
            tasks.append(self._fetch_chunks(resolved_query, plan))
        if plan.use_relations:
            tasks.append(self._fetch_relations(resolved_query, entity_ids))
        if plan.use_graph:
            for eid in entity_ids[:3]:  # max 3 entities
                tasks.append(self._fetch_graph(eid))
        if plan.use_claims:
            tasks.append(self._fetch_claims(entity_ids, plan.date_filter))
        if plan.use_events:
            tasks.append(self._fetch_events(entity_ids, plan.date_filter))
        if plan.use_contradictions:
            for eid in entity_ids[:3]:
                tasks.append(self._fetch_contradictions(eid))
        if plan.use_financial:
            for entity in resolved_query.resolved_entities[:3]:
                if entity.ticker:
                    tasks.append(self._fetch_financial(entity))
        if plan.use_portfolio:
            tasks.append(self._fetch_portfolio(request))
        if plan.use_cypher and entity_ids:
            tasks.append(self._fetch_cypher(entity_ids[0]))

        results_nested = await asyncio.gather(*tasks, return_exceptions=True)
        items = []
        for r in results_nested:
            if isinstance(r, Exception):
                logger.warning("retrieval_task_failed", error=str(r))
            elif isinstance(r, list):
                items.extend(r)
        return items
```

Each `_fetch_*` method:
- Calls the appropriate client method
- Converts raw API response to `RetrievedItem` list (with correct `item_type`, `score`, etc.)
- Wraps in `asyncio.wait_for(..., timeout=5.0)`
- Returns empty list on any exception

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_retrieval_orchestrator_parallel` | All tasks run concurrently (asyncio.gather) | unit |
| `test_retrieval_task_timeout_returns_empty` | One task times out → other tasks still return | unit |
| `test_retrieval_portfolio_intent` | PORTFOLIO plan includes portfolio task | unit |
| `test_retrieval_entity_count_capped_at_3` | 5 entities → max 3 graph tasks | unit |

---

#### T-F-1-02: Fusion Scorer + Deduplicator + Graph Enricher

**Type**: impl
**depends_on**: [T-F-1-01]
**blocks**: [T-F-2-01]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/fusion.py` (new)

**What to build**:

**`SourceTrustWeights`** (config-loaded dict):
```python
DEFAULT_TRUST_WEIGHTS = {
    "sec_10k": 0.95, "sec_10q": 0.95, "sec_8k": 0.90,
    "earnings_data": 0.95, "corporate_action": 0.90,
    "eodhd_news": 0.70, "finnhub_news": 0.65,
    "relation": 0.85, "claim": 0.80,
    "financial": 0.90, "default": 0.60,
}
```

**`FusionPipeline.process(items: list[RetrievedItem]) -> list[RetrievedItem]`**:
1. Compute `recency_score` for each item (already on domain entity via `compute_recency_score`)
2. Look up `trust_weight` from `source_trust_weights[item.citation_meta.source_type or "default"]`
3. Compute `fusion_score = score * recency_score * trust_weight`
4. Deduplicate by `doc_id` (keep highest fusion_score per doc_id)
5. Sort by `fusion_score DESC`
6. Return top 30

**`GraphEnricher.enrich(items: list[RetrievedItem], relation_results: list) -> list[RetrievedItem]`**:
For each chunk item with `entities[]`:
- For each entity in chunk.entities (max 2 per chunk):
  - Find entity's top-3 relations from relation_results by `summary_authority`
  - Attach as `graph_enrichment = [relation_summary, ...]`
Returns new list of enriched items (domain entities are frozen, create new instances).

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_fusion_dedup_keeps_max_score` | Two items same doc_id → keep higher fusion_score | HIGH/unit |
| `test_fusion_sorts_by_fusion_score` | Items sorted DESC by fusion_score | unit |
| `test_fusion_trust_weight_applied` | SEC filing (0.95) scores higher than news (0.65) | unit |
| `test_graph_enricher_injects_top3_relations` | Chunk with entity → top-3 relations attached | unit |
| `test_graph_enricher_caps_at_2_entities_per_chunk` | Chunk with 5 entities → only 2 enriched | unit |

---

**Validation Gate (Wave F-1)**:
- [ ] ruff check + mypy pass
- [ ] 9 tests pass
- [ ] Dedup preserves max fusion_score (not first-seen)

---

### Wave F-2: BGE Reranker + Context Assembly + Prompt Construction

**Goal**: Steps 8–10 — rerank top-30 to top-12, assemble context block, build final prompt.
**Depends on**: F-1
**Estimated effort**: 45–60 min
**Architecture layer**: application

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Steps 8–10

#### T-F-2-01: BGE Reranker

**Type**: impl
**depends_on**: none
**blocks**: [T-F-2-02]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/reranker.py` (new)

**What to build**:
Cross-encoder reranking using Ollama `bge-reranker-v2-m3`. Input: 30 (query, candidate) pairs.
Output: top-12 by cross-encoder score.

```python
class BGEReranker:
    async def rerank(self, query: str, items: list[RetrievedItem]) -> list[RetrievedItem]:
        if not items:
            return []
        # Batch POST to Ollama BGE reranker
        # Input: {"model": "bge-reranker-v2-m3", "query": query, "documents": [item.text for item in items]}
        # Output: list of scores ordered by input index
        # Ollama reranker endpoint: POST /api/rerank (or similar — check Ollama docs)
        # Sort items by score DESC, return top 12
        # Fallback on timeout: return items[:12] sorted by fusion_score
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_reranker_returns_top_12` | 30 items in → max 12 out | unit |
| `test_reranker_falls_back_on_timeout` | Ollama timeout → top 12 by fusion_score | unit |
| `test_reranker_empty_input` | 0 items → empty list | unit |

---

#### T-F-2-02: Context Assembler + Prompt Builder

**Type**: impl
**depends_on**: [T-F-2-01]
**blocks**: [T-F-3-01]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/context_assembler.py` (new)
- `services/rag-chat/src/rag_chat/application/pipeline/prompt_builder.py` (new)

**`ContradictionAssembler`**:
Processes contradiction results from Step 5E; builds a formatted contradiction block
for the prompt if any entities have contradictions.

**`ContextAssembler`**:
Builds the numbered context block from top-12 items:
```
[1] {item.text}
    Source: {source_name} ({published_at})
    Confidence: {score:.2f}
    [Graph context: {graph_enrichment[0].summary}]
```
Token budget: 8000 context tokens total (approximate by char count × 0.25).
Truncation strategy: trim oldest evidence first (lowest fusion_score items).

**`PromptBuilder`**:
Assembles the full LLM prompt from components:
```
System: "You are a financial intelligence analyst..."
Context block (numbered items)
Contradiction block (if any)
Financial data block (if financial data retrieved)
Conversation history (last 5 turns)
Query: "{rephrased_query}"
Sub-questions: [if COMPARISON/REASONING]
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_context_assembler_numbers_items` | First item gets [1] marker | unit |
| `test_context_assembler_respects_token_budget` | >8000 chars → truncated | unit |
| `test_prompt_builder_includes_system_prompt` | Output contains safety instruction | unit |
| `test_prompt_builder_includes_contradiction_block` | Contradictions present → ⚠️ block included | unit |
| `test_prompt_builder_includes_conversation_history` | Last 5 turns in prompt | unit |

---

**Validation Gate (Wave F-2)**:
- [ ] ruff check + mypy pass
- [ ] 8 tests pass
- [ ] Contradiction block only appears when contradictions are non-empty

---

### Wave F-3: LLM Provider Chain + SSE Streaming

**Goal**: Steps 11 — implement 3-tier LLM provider fallback chain with SSE streaming.
**Depends on**: F-2
**Estimated effort**: 50–70 min
**Architecture layer**: infrastructure (LLM adapters)

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Step 11
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py` — provider API key settings

#### T-F-3-01: LLM Provider Adapters + Fallback Chain

**Type**: impl
**depends_on**: none
**blocks**: [T-F-3-02]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/llm/openrouter_adapter.py` (new)
- `services/rag-chat/src/rag_chat/infrastructure/llm/ollama_adapter.py` (new, emergency fallback)
- `services/rag-chat/src/rag_chat/infrastructure/llm/provider_chain.py` (new)
- `services/rag-chat/src/rag_chat/application/ports/llm_provider.py` (protocol)

**`LLMProviderProtocol`**:
```python
class LLMProviderProtocol(Protocol):
    name: str
    async def stream(self, prompt: str, max_tokens: int, temperature: float) -> AsyncIterator[str]: ...
```

**`DeepInfraCompletionAdapter`**: POST /openai/chat/completions (OpenAI-compatible), model=deepseek-r1-distill-qwen-32b, stream=true, timeout=30s
**`OpenRouterCompletionAdapter`**: OpenRouter OpenAI-compat API, model=deepseek/deepseek-r1-distill-qwen-32b, stream=true, timeout=30s
**`OllamaCompletionAdapter`**: POST /api/chat, model=deepseek-r1:32b, stream=true, timeout=60s (emergency only)

**`LLMProviderChain`**:
```python
class LLMProviderChain:
    _providers = [DeepInfraAdapter, OpenRouterAdapter, OllamaAdapter]

    async def stream(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.1) -> AsyncIterator[str]:
        for provider in self._providers:
            neg_key = f"rag:v1:neg:{provider.name}"
            if await self._valkey.exists(neg_key):
                continue  # skip negative-cached provider
            try:
                async for chunk in provider.stream(prompt, max_tokens, temperature):
                    yield chunk
                return  # success
            except Exception as exc:
                logger.warning("provider_failed", provider=provider.name, error=str(exc))
                await self._valkey.setex(neg_key, 60, "1")  # negative cache 60s
                counter_provider_fallback.inc({"from": provider.name})
        raise ProviderUnavailableError("All LLM providers unavailable")
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_provider_chain_skips_negative_cached` | Provider in neg cache → skipped | unit |
| `test_provider_chain_falls_back_on_error` | Primary fails → secondary used | unit |
| `test_provider_chain_all_failed_raises` | All providers fail → ProviderUnavailableError | unit |
| `test_provider_chain_sets_negative_cache` | Failure → 60s neg cache set | unit |

---

#### T-F-3-02: SSE Streaming Response Helper

**Type**: impl
**depends_on**: [T-F-3-01]
**blocks**: [T-F-4-01]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` (new)

**What to build**:
Helper that converts pipeline events into SSE data frames using `sse-starlette`.

```python
class SSEEmitter:
    async def emit_status(self, step: str) -> dict:
        return {"event": "status", "data": json.dumps({"step": step})}

    async def emit_token(self, text: str) -> dict:
        return {"event": "token", "data": json.dumps({"text": text})}

    async def emit_citations(self, citations: list[Citation]) -> dict:
        return {"event": "citations", "data": json.dumps([c.__dict__ for c in citations])}

    async def emit_contradictions(self, contradictions: list[ContradictionRef]) -> dict:
        return {"event": "contradictions", "data": json.dumps([...for c in contradictions])}

    async def emit_metadata(self, thread_id: UUID, message_id: UUID,
                             intent: str, provider: str, latency_ms: int) -> dict:
        return {"event": "metadata", "data": json.dumps({...})}

    async def emit_error(self, code: str, message: str) -> dict:
        return {"event": "error", "data": json.dumps({"code": code, "message": message})}
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_sse_event_types` | Each emitter method returns correct event type | unit |

---

**Validation Gate (Wave F-3)**:
- [ ] ruff check + mypy pass
- [ ] All 5 provider chain tests pass
- [ ] Provider fallback sequence is: DeepInfra → OpenRouter → Ollama (emergency)

---

### Wave F-4: Output Processing + Chat Endpoints + Integration Tests

**Goal**: Steps 12–13 — output sanitization, citation injection, persistence, and public /chat endpoints.
**Depends on**: F-3
**Estimated effort**: 60–80 min
**Architecture layer**: application + API

**Pre-read**:
- `docs/specs/0015-s8-rag-chat-hybrid-pipeline.md` §6.7 Steps 12–13, §6.2 /chat endpoints

#### T-F-4-01: OutputProcessor + ChatPersistenceUseCase

**Type**: impl
**depends_on**: none
**blocks**: [T-F-4-02]
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/output_processor.py` (new)
- `services/rag-chat/src/rag_chat/application/use_cases/persist_chat.py` (new)

**`OutputProcessor`**:
```python
class OutputProcessor:
    _THINK_RE = re.compile(r'<(think|reasoning|scratchpad)>.*?</\1>', re.DOTALL | re.IGNORECASE)
    _CITATION_RE = re.compile(r'\[(\d+)\]')

    def process(self, raw_output: str, retrieved_items: list[RetrievedItem]) -> tuple[str, list[Citation]]:
        # 1. Strip <think>/<reasoning> blocks
        text = self._THINK_RE.sub('', raw_output).strip()
        # 2. PII scan on output
        if self._pii_detector.contains_pii(text):
            logger.warning("pii_in_llm_output")
            text = self._pii_detector.redact(text)
        # 3. Parse [N] citation markers
        refs = set(int(m) for m in self._CITATION_RE.findall(text))
        # 4. Build citations list
        citations = []
        for ref in sorted(refs):
            idx = ref - 1
            if 0 <= idx < len(retrieved_items):
                item = retrieved_items[idx]
                citations.append(Citation(
                    ref=ref, item_type=item.item_type.value, id=item.item_id,
                    title=item.citation_meta.title, url=item.citation_meta.url,
                    source_name=item.citation_meta.source_name,
                    published_at=item.citation_meta.published_at,
                    entity_name=item.citation_meta.entity_name,
                    confidence=item.score,
                ))
        return text, citations
```

**`ChatPersistenceUseCase`**:
Inserts user + assistant messages into rag_db and updates thread metadata.
```python
async def execute(thread_id: UUID, user_message: str, assistant_response: AssistantResponse) -> tuple[UUID, UUID]:
    user_msg_id = new_uuid7()
    asst_msg_id = new_uuid7()
    await uow.messages.create(Message(message_id=user_msg_id, thread_id=thread_id, role=MessageRole.user, ...))
    await uow.messages.create(Message(message_id=asst_msg_id, thread_id=thread_id, role=MessageRole.assistant, ...))
    await uow.threads.update_last_msg(thread_id, utc_now(), new_entity_ids)
    await uow.commit()
    return user_msg_id, asst_msg_id
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_output_strips_think_tags` | `<think>...</think>` removed from output | HIGH/unit |
| `test_output_parses_citation_markers` | `[1]` in answer → citations[0] | HIGH/unit |
| `test_output_citation_out_of_range_ignored` | `[99]` when only 5 items → ignored | unit |
| `test_persistence_inserts_both_messages` | user + assistant messages created | unit |

---

#### T-F-4-02: ChatOrchestrator

**Type**: impl
**depends_on**: [T-F-4-01]
**blocks**: [T-F-4-03]
**Target files**:
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (new)

**What to build**:
Top-level orchestrator that chains all 13 pipeline steps for both sync (`/chat`) and streaming
(`/chat/stream`) paths.

```python
class ChatOrchestrator:
    async def execute_streaming(self, request: ChatRequest) -> AsyncGenerator[dict, None]:
        start = utc_now()
        # Step 0: validate
        validated_message = self._validator.validate(request.message)

        # Check completion cache
        cached = await self._cache.get(request.message, request.thread_id)
        if cached:
            yield self._emitter.emit_from_cache(cached)
            return

        # Rate limit
        await self._rate_limiter.check_and_increment(request.tenant_id)

        # Step 1: context load
        yield self._emitter.emit_status("entity_resolution")
        thread = await self._load_thread(request)
        conversation_history = list(thread.recent_history(5)) if thread else []

        # Step 2: entity resolution
        entities = await self._s6_client.resolve_entities(validated_message)
        yield self._emitter.emit_status(f"intent_classification")

        # Step 3: intent + plan
        intent, sub_questions, rephrased = await self._classifier.classify(
            validated_message, conversation_history, entities
        )
        plan = self._plan_builder.build(intent, entities, request.context)
        yield self._emitter.emit_status("query_expansion")

        # Step 4: HyDE
        hypothesis, hyde_embedding = await self._hyde.expand(rephrased, intent)
        query_embedding = hyde_embedding or await self._embedding_client.embed(rephrased)

        yield self._emitter.emit_status("parallel_retrieval")

        # Step 5: parallel retrieval
        raw_items = await self._retrieval.retrieve(plan, ResolvedQuery(...), request)

        # Steps 6-7: graph enrichment + fusion
        enriched = self._graph_enricher.enrich(raw_items, ...)
        fused = self._fusion.process(enriched)

        yield self._emitter.emit_status("ranking_evidence")

        # Step 8: reranking
        reranked = await self._reranker.rerank(rephrased, fused[:30])

        # Steps 9-10: contradiction + prompt
        contradiction_block = self._contradiction_assembler.build(raw_items)
        prompt = self._prompt_builder.build(reranked, conversation_history, rephrased, sub_questions, contradiction_block)

        # Step 11: LLM streaming
        full_text = ""
        async for chunk in self._llm_chain.stream(prompt):
            full_text += chunk
            yield self._emitter.emit_token(chunk)

        # Steps 12-13: output processing + persistence
        answer, citations = self._output_processor.process(full_text, reranked)
        latency_ms = int((utc_now() - start).total_seconds() * 1000)

        yield self._emitter.emit_citations(citations)
        yield self._emitter.emit_contradictions(contradiction_block.refs)

        # Persist (best-effort: don't fail the response on DB error)
        try:
            user_msg_id, asst_msg_id = await self._persistence.execute(
                thread_id, request.message, AssistantResponse(...)
            )
        except Exception as exc:
            logger.error("persistence_failed", error=str(exc))
            asst_msg_id = new_uuid7()  # generate ID for metadata event

        yield self._emitter.emit_metadata(thread_id, asst_msg_id, intent.value, provider_name, latency_ms)
```

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_orchestrator_insufficient_retrieval_422` | 0 items retrieved → ProviderNotCalledError | HIGH/unit |
| `test_orchestrator_cache_hit_skips_pipeline` | Cached response → LLM not called | unit |
| `test_orchestrator_rate_limit_raises` | 11th request → RateLimitExceededError | unit |

---

#### T-F-4-03: POST /api/v1/chat + POST /api/v1/chat/stream Endpoints

**Type**: impl
**depends_on**: [T-F-4-02]
**blocks**: [T-F-4-04]
**Target files**:
- `services/rag-chat/src/rag_chat/api/routes/chat.py` (new)
- `services/rag-chat/src/rag_chat/api/schemas.py` — chat request/response schemas

**`POST /api/v1/chat`** (sync):
```python
@router.post("/chat", status_code=200)
async def chat(request: ChatRequestSchema, ...) -> ChatResponse:
    chat_req = ChatRequest(message=request.message, ...)
    result = await orchestrator.execute_sync(chat_req)
    return ChatResponse(...)
```

**`POST /api/v1/chat/stream`** (SSE):
```python
@router.post("/chat/stream")
async def chat_stream(request: ChatRequestSchema, ...) -> EventSourceResponse:
    async def event_generator():
        async for event in orchestrator.execute_streaming(chat_req):
            yield event
    return EventSourceResponse(event_generator())
```

**Error handling** (HTTP status codes):
- `RateLimitExceededError` → 429
- `PIIDetectedError` / `PromptInjectionError` → 400
- `ThreadNotFoundError` → 404
- `InsufficientRetrievalError` → 422
- `ProviderUnavailableError` → 503

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_chat_endpoint_200` | Full pipeline with mock orchestrator → 200 | unit |
| `test_chat_stream_sse_events` | Streaming path emits status, token, citations, metadata events in order | unit |
| `test_chat_rate_limit_429` | Rate limit exceeded → 429 | unit |
| `test_chat_injection_blocked_400` | Injection detected → 400 | unit |
| `test_chat_all_providers_down_503` | ProviderUnavailableError → 503 | unit |

---

#### T-F-4-04: Prometheus Metrics Registration

**Type**: impl
**depends_on**: [T-F-4-03]
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/metrics/prometheus.py` (new)

**What to build**:
All 10 Prometheus metrics from PRD §13.1:
```python
rag_queries_total = Counter("rag_chat_queries_total", "Total queries", ["intent","provider","tenant_id"])
rag_latency = Histogram("rag_chat_latency_seconds", "Per-step latency", ["intent","step"])
rag_first_token = Histogram("rag_chat_first_token_seconds", "Time to first token", ["provider"])
rag_retrieval_items = Histogram("rag_retrieval_items_total", "Items retrieved", ["source_type"])
rag_cache_hits = Counter("rag_cache_hit_total", "Cache hits", ["cache_type"])
rag_provider_fallback = Counter("rag_provider_fallback_total", "Fallbacks", ["from_provider","to_provider"])
rag_provider_unavail = Counter("rag_provider_unavailable_total", "Neg cache activations", ["provider"])
rag_thread_count = Gauge("rag_thread_count", "Active threads", ["tenant_id"])
rag_contradiction_surfaced = Counter("rag_contradiction_surfaced_total", "Contradictions surfaced", ["claim_type"])
rag_injection_blocked = Counter("rag_injection_blocked_total", "Injection attempts blocked")
```

---

**Validation Gate (Wave F-4)**:
- [ ] ruff check + mypy pass
- [ ] All 14 F-4 tests pass
- [ ] All 10 Prometheus metrics registered and exported via GET /metrics
- [ ] `/chat/stream` returns `Content-Type: text/event-stream`
- [ ] Error codes map to correct HTTP status codes

---

## PLAN-0015-G: Integration Completions

**Service**: S9 API Gateway + documentation updates
**Rationale**: S9 routing additions and comprehensive documentation updates for all changed services.
**Depends on**: F-4 complete (S8 service fully implemented)

---

### Wave G-1: S9 Route Additions + Documentation Updates

**Goal**: Wire S8 into S9 API Gateway and update all service docs to reflect new capabilities.
**Depends on**: F-4
**Estimated effort**: 35–50 min
**Architecture layer**: infrastructure (gateway) + docs

**Pre-read**:
- `services/api-gateway/src/api_gateway/` — existing routing structure
- `docs/services/rag-chat.md`, `docs/services/nlp-pipeline.md`, etc. — docs to update
- `services/api-gateway/.claude-context.md` — gateway routing patterns

#### T-G-1-01: S9 Route Additions

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routes/rag_chat.py` (new or add to existing)
- `services/api-gateway/src/api_gateway/config.py` or routing dict — add RAG_CHAT service

**What to build**:
Add 7 S9 routes that proxy to S8 (`rag-chat:8008`). Critical: `/chat/stream` must NOT buffer
the response (SSE requires chunked transfer; set `proxy_buffering off` or equivalent in httpx proxy).

```python
RAG_CHAT_ROUTES = {
    ("POST", "/api/v1/chat"):              ("rag-chat", 8008, "/api/v1/chat"),
    ("POST", "/api/v1/chat/stream"):       ("rag-chat", 8008, "/api/v1/chat/stream"),
    ("POST", "/api/v1/threads"):           ("rag-chat", 8008, "/api/v1/threads"),
    ("GET",  "/api/v1/threads"):           ("rag-chat", 8008, "/api/v1/threads"),
    ("GET",  "/api/v1/threads/{id}"):      ("rag-chat", 8008, "/api/v1/threads/{id}"),
    ("DELETE","/api/v1/threads/{id}"):     ("rag-chat", 8008, "/api/v1/threads/{id}"),
    ("GET",  "/api/v1/providers/status"):  ("rag-chat", 8008, "/api/v1/providers/status"),
}
```

**SSE Proxy behavior**: For `/chat/stream`, the gateway must forward without buffering.
Use `httpx.stream()` and `StreamingResponse` in FastAPI with `media_type="text/event-stream"`.
Inject `X-Tenant-Id` and `X-User-Id` headers from JWT before forwarding (standard S9 behavior).

**Tests to write**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_s9_chat_route_proxied` | POST /api/v1/chat → forwarded to S8 | unit |
| `test_s9_chat_stream_not_buffered` | /chat/stream → streaming response type | unit |
| `test_s9_injects_tenant_user_headers` | JWT decoded → X-Tenant-Id, X-User-Id injected | unit |

---

#### T-G-1-02: Documentation Updates

**Type**: docs
**depends_on**: none
**blocks**: none
**Target files**:
- `docs/services/rag-chat.md` — full update: new endpoints, rag_db schema, pipeline, entities
- `docs/services/nlp-pipeline.md` — new endpoints (entities/resolve, search/chunks), new table
- `docs/services/knowledge-graph.md` — 5 new endpoints, FundamentalsWorker enhancements
- `docs/services/portfolio.md` — portfolio context endpoint
- `docs/services/content-store.md` — batch documents endpoint
- `services/rag-chat/.claude-context.md` — full rewrite (was minimal stub)
- `services/nlp-pipeline/.claude-context.md` — add new endpoints, pitfalls for document_source_metadata
- `services/knowledge-graph/.claude-context.md` — add 5 new endpoints, C-4 worker changes

**`docs/services/rag-chat.md`** updates (major rewrite of stub):
- Port: 8008, DB: rag_db
- All 7 public endpoints
- Pipeline steps 0–13 summary
- Domain entities
- Configuration settings
- Process topology (API only — no background processes; R22 compliant)
- Valkey cache keys
- LLM provider fallback chain
- Prometheus metrics

**`services/rag-chat/.claude-context.md`** rewrite:
```markdown
# RAG / Chat Service (S8) — Agent Context

**Port**: 8008 | **DB**: rag_db (owned) | **Status**: Phase 2 complete

## Mission
[updated mission with hybrid pipeline description]

## Domain Entities
ChatRequest, ChatContext, QueryIntent (7 values), RetrievedItem (fusion_score invariant),
ConversationThread, Message, Citation, ContradictionRef

## Kafka Topics
None — no Kafka (chat is request-response)

## Database (rag_db)
- threads table (with partial index for active threads)
- messages table (FK threads, JSONB citations/contradiction_refs)

## LLM Provider Fallback Chain
DeepInfra (30s) → OpenRouter (30s) → Ollama emergency (60s)
Negative cache 60s per provider.

## API Endpoints (public)
- POST /api/v1/chat — sync chat
- POST /api/v1/chat/stream — SSE streaming chat
- POST /api/v1/threads — create thread
- GET /api/v1/threads — list threads
- GET /api/v1/threads/{id} — thread detail
- DELETE /api/v1/threads/{id} — soft delete thread
- GET /api/v1/providers/status — provider health

## Critical Rules
- Rate limit: 10 queries/min per tenant (Valkey sliding window)
- Token budget: 4000 output, 8000 context
- Output sanitization: strip <think>/<reasoning> blocks
- fusion_score invariant: score * recency_score * trust_weight (tested)
- Thread ownership: user_id must match X-User-Id on every thread operation

## Pitfalls
- /chat/stream requires SSE proxy in S9 (no buffering)
- Persistence is best-effort: DB failure returns response without saving
- HyDE only for SIGNAL_INTEL, FACTUAL_LOOKUP, RELATIONSHIP, REASONING
- PORTFOLIO intent: S1 returns entity_ids for holdings/watchlist → prepend to retrieval
- Cypher: CYPHER_ENABLED=false (default) → 501 from S7; S8 returns empty cypher results
```

---

**Validation Gate (Wave G-1)**:
- [ ] ruff check + mypy pass on `services/api-gateway/`
- [ ] S9 unit tests pass (gateway proxy tests)
- [ ] SSE streaming response not buffered (Content-Type: text/event-stream preserved)
- [ ] All 8 service docs updated with new endpoints/schemas
- [ ] All 3 `.claude-context.md` files updated

---

## Cross-Cutting Concerns

### Contract Changes
- S6 adds 2 new endpoints (no Avro — REST only)
- S7 adds 5 new endpoints (no Avro — REST only)
- S5 adds 1 new endpoint (REST only)
- S1 adds 1 new endpoint (internal, REST only)
- S8 is a new service (no existing contracts to break)
- intelligence-migrations adds 3 nullable columns + 4 registry rows (backward-compatible)

### Migration Needs
| Service | Migration | When |
|---------|-----------|------|
| intelligence-migrations | 0002_enhance_events_and_relations.py | Wave A-1 (first) |
| S6 nlp-pipeline | 0002_add_document_source_metadata.py | Wave B-1 |
| S8 rag-chat | 0001_create_rag_db.py | Wave D-2 |

**Order**: intelligence-migrations 0002 BEFORE S7 C-2/C-4 (depends on new columns).
**S6 and S8 migrations are independent** of each other.

### Configuration Changes
New env vars in `configs/dev.local.env.example`:
- `RAG_CHAT_RAG_DB_URL` (required)
- `RAG_CHAT_VALKEY_URL`
- `RAG_CHAT_OLLAMA_BASE_URL`
- `RAG_CHAT_DEEPINFRA_API_KEY` (required for primary completion)
- `RAG_CHAT_OPENROUTER_API_KEY` (required for fallback completion)
- `RAG_CHAT_S1_INTERNAL_TOKEN` (required for PORTFOLIO intent)
- `RAG_CHAT_CYPHER_ENABLED` (default false)
- `POSTGRES_RAG_DB` (new DB in Postgres init)

### Documentation Updates (consolidated in G-1)
All service docs updated as described in Wave G-1 T-G-1-02.

---

## Risk Assessment

### Critical Path
`A-1 → B-1 → B-2 → B-3 → D-1 → D-2 → D-3 → D-4 → E-1 → E-2 → E-3 → F-1 → F-2 → F-3 → F-4 → G-1`

Note: D depends on **all** of A, B, C-1, C-2 being complete. B-2 and B-3 both depend on B-1 and run in parallel (B-3 is on the critical path as it has the same or longer duration). C-1 and C-2 also run in parallel with B and can be done before D starts.

### Highest Risk Waves

| Wave | Risk | Mitigation |
|------|------|------------|
| F-3 (LLM chain) | DeepInfra/OpenRouter API key management; rate limits | Test each adapter independently; mock in unit tests |
| F-4 (chat endpoints) | SSE streaming + persistence atomicity | Persistence is best-effort; SSE tested end-to-end in integration test |
| E-2 (intent classifier) | Qwen 3B quality for 7-way classification | Keyword fallback always available; test all 7 intents |
| C-4 (FundamentalsWorker) | S3 API schema changes breaking earnings parsing | Defensive parsing; log warning on parse failure |

### Rollback Strategy
- **intelligence-migrations 0002**: `alembic downgrade -1` (adds columns; downgrade drops them; safe if S7 C-2/C-4 not yet deployed)
- **S8 service**: Remove from Docker compose; no existing service affected
- **S6 enhancements**: Old `/vector-search` endpoint remains; new endpoints are additive
- **S7 enhancements**: New endpoints are additive; worker changes are idempotent (ON CONFLICT)

### Testing Gaps
- **Eval harness** (NF03/NF04/NF05/NF06): 100-query eval suite deferred to separate milestone
- **Cypher integration** (Phase 4): Not testable until Block 14 is stable
- **Multi-turn conversation**: Covered by integration tests but not E2E with real LLM

### Regression Guards
| Rule | Wave | How Applied |
|------|------|-------------|
| BP-019 (DDL alignment) | D-2 | DDL alignment test for `threads` + `messages` |
| R26 (no UoW auto-commit) | D-2 | Explicit test: context exit without commit → no DB write |
| R27 (ReadOnly UoW for reads) | D-4, A-2, A-3 | `ListThreadsUseCase` depends on `ReadOnlyUnitOfWork` |
| R22 (standalone processes) | D-3 | S8 lifespan has NO `asyncio.create_task()` — tested |
| R25 (no infra in API layer) | D-4, F-4 | Import guard rule `IG-LAYER-002` enforcement |
| R15 (input sanitization) | E-1 | 7 security tests cover injection + PII |

---

## Phase 4 — Deferred (PLAN-0015-H)

Cypher integration is NOT included in this plan. A separate `PLAN-0015-H` will be created when:
- S7 Block 14 shadow migration reaches 0 lag and is stable for 24+ hours
- `shadow_migration_lag` Prometheus metric confirms stability

PLAN-0015-H scope:
- Wave H-1: S7 `POST /api/v1/graph/cypher` endpoint (allowlist validation, `statement_timeout`)
- Wave H-2: S8 cypher integration path in `ParallelRetrievalOrchestrator` (enable when `settings.cypher_enabled=True`)
