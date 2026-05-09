---
id: PLAN-0086
title: Multi-Tenant Content Pipeline Isolation & Tenant Document Ingestion
prd: PRD-0075
status: in-progress
created: 2026-05-08
updated: 2026-05-08
---

# PLAN-0086 — Multi-Tenant Content Pipeline Isolation & Tenant Document Ingestion

## Overview

PRD: [PRD-0075](../specs/0075-multi-tenant-content-pipeline-isolation.md)
Services affected: S4 (content-ingestion), S5 (content-store), S6 (nlp-pipeline), S8 (rag-chat), S9 (api-gateway), libs/contracts
Total waves: 10 (+ 3 new tasks added by revise-prd: T-A-1-07, T-A-1-08, T-C-1-05)
Estimated total effort: 9–14 hours

## Pre-Flight ID Verification (recorded 2026-05-08)

| ID class | Current highest | New IDs in this plan |
|----------|----------------|----------------------|
| PLAN-XXXX | PLAN-0085 | **PLAN-0086** |
| R## (RULES.md) | R34 | none — no new rules |
| content-ingestion Alembic | 0006 | **0007** |
| content-store Alembic | 0004 | **0005** |
| nlp-pipeline Alembic | 0018 | **0019** |
| rag-chat Alembic | 0006 | none |

## Sub-Plans

| Sub-Plan | Title | Waves | Depends on |
|----------|-------|-------|------------|
| A | Avro Schema Foundation | A-1 | none |
| B | Database Schema Changes | B-1, B-2 | A-1 |
| C | Phase 1 Pipeline Wiring | C-1 | A-1, B-1, B-2 |
| D | Tenant Upload Domain & Infrastructure | D-1, D-2 | A-1 |
| E | Tenant Upload Application & API | E-1, E-2 | D-1, D-2 |
| F | Event Consumers & Status Feedback | F-1 | A-1, B-2, E-2 |
| G | Integration Tests & Contract Coverage | G-1 | C-1, E-2, F-1 |

## Dependency Graph

```
A-1 (Avro schemas + ContentSourceType)
 ├── B-1 (S5 migration 0005)  ──┐
 ├── B-2 (S6 migration 0019)  ──┤
 │                              └── C-1 (Phase 1 wiring)
 └── D-1 (S4 domain + ports)
      └── D-2 (S4 infra)
           └── E-1 (S4 use cases)
                └── E-2 (S4 API + dispatcher + S9)
                     └── F-1 (consumers)
                          └── G-1 (integration + contract tests)
```

B-1 and B-2 can run **in parallel** (different databases, different services).
D-1 can run **in parallel** with B-1/B-2.

## Name Verification (BP-405 pass — all names verified against codebase)

| Name | Kind | Status |
|------|------|--------|
| `ContentSourceType` | enum in `libs/contracts/src/contracts/enums.py` | EXISTS |
| `ChunkSearchRequest` | dataclass in `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` | EXISTS |
| `_fetch_chunks` | method in `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` | EXISTS |
| `DedupHashRepository.check_exists` | method in `services/content-store/src/content_store/infrastructure/db/repositories/dedup.py` | EXISTS |
| `ContentIngestionOutboxDispatcher._get_value_serializer` | method in `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher.py` | EXISTS |
| `ChunkSearchPort` | ABC in `services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py` | EXISTS |
| `ArticleProcessingConsumer.process_message` | method in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py` | EXISTS |
| `TenantDocumentUpload` | S4 domain entity | **NEW — created in Wave D-1** |
| `UploadStatus` | S4 enum | **NEW — created in Wave D-1** |
| `TenantDocumentUploadRepositoryPort` | S4 port ABC | **NEW — created in Wave D-1** |
| `UploadRateLimitPort` | S4 port ABC | **NEW — created in Wave D-1** |
| `DocumentDeletionConsumer` | S6 consumer | **NEW — created in Wave F-1** |
| `DocumentReadyConsumer` | S4 consumer | **NEW — created in Wave F-1** |
| `content.document.deleted.v1` | Avro schema / Kafka topic | **NEW — created in Wave A-1** |
| `nlp.document.ready.v1` | Avro schema / Kafka topic | **NEW — created in Wave A-1** |
| `ContentDocumentDeleted` | canonical model in `libs/contracts/src/contracts/events/content/document_deleted.py` | **NEW — created in Wave A-1 (T-A-1-07)** |
| `NlpDocumentReady` | canonical model in `libs/contracts/src/contracts/events/nlp/document_ready.py` | **NEW — created in Wave A-1 (T-A-1-08)** |
| `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py:ChunkSearchRequest.tenant_id` | field (Pydantic model) | **NEW — added in Wave C-1 (T-C-1-05)** |
| `services/api-gateway/src/api_gateway/routes/proxy.py` | target file for S9 document proxy routes | EXISTS — all S9 proxy routes live here (no `routers/` directory) |

---

## Sub-Plan A — Avro Schema Foundation

### Wave A-1: Avro Schema Updates + ContentSourceType Extension

**Goal**: Add `tenant_id` to three existing Avro schemas; create two new event schemas; add `TENANT_UPLOAD` to the shared enum. All downstream consumers start receiving `tenant_id = null` on existing events — zero behaviour change.
**Depends on**: none
**Estimated effort**: 45–60 min
**Architecture layer**: schema + contracts

#### Tasks

##### T-A-1-01: Add `tenant_id` to content.article.raw.v1.avsc

**Type**: schema
**depends_on**: none
**blocks**: T-B-1-01, T-C-1-01, T-D-1-01
**Target files**:
- `infra/kafka/schemas/content.article.raw.v1.avsc`

**What to build**:
Add a nullable `tenant_id` field at the end of the existing field list. The field must use Avro union type `["null", "string"]` with `"default": null` to satisfy R5 (forward-compatible schema evolution). `null` means public news visible to all tenants; a UUID string identifies the owning tenant for private uploads.

**Exact field to add** (append after `correlation_id`):
```json
{
  "name": "tenant_id",
  "type": ["null", "string"],
  "default": null,
  "doc": "Owning tenant UUID string. null = public news visible to all tenants. Set only for tenant-uploaded documents."
}
```

**Downstream test impact**:
- `libs/contracts/tests/test_avro_alignment.py` — if it asserts field count for this schema, update expected count
- Any contract test checking `content.article.raw.v1` field list

**Acceptance criteria**:
- [ ] Field appended as last item in `"fields"` array
- [ ] `"default": null` present (R5 compliance)
- [ ] Avro schema validates via `fastavro.parse_schema`

---

##### T-A-1-02: Add `tenant_id` to content.article.stored.v1.avsc

**Type**: schema
**depends_on**: none
**blocks**: T-C-1-01
**Target files**:
- `infra/kafka/schemas/content.article.stored.v1.avsc`

**What to build**: Same field addition as T-A-1-01. S5 passes `tenant_id` through from the raw event.

**Exact field** (append after `correlation_id`):
```json
{
  "name": "tenant_id",
  "type": ["null", "string"],
  "default": null,
  "doc": "Owning tenant UUID string. Propagated from content.article.raw.v1."
}
```

**Acceptance criteria**:
- [ ] Field appended with `"default": null`
- [ ] Schema validates

---

##### T-A-1-03: Add `tenant_id` to nlp.article.enriched.v1.avsc

**Type**: schema
**depends_on**: none
**blocks**: T-C-1-02
**Target files**:
- `infra/kafka/schemas/nlp.article.enriched.v1.avsc`

**What to build**: Same field addition. S6 passes `tenant_id` through from the stored event.

**Exact field** (append after `correlation_id`):
```json
{
  "name": "tenant_id",
  "type": ["null", "string"],
  "default": null,
  "doc": "Owning tenant UUID string. Propagated from content.article.stored.v1."
}
```

**Acceptance criteria**:
- [ ] Field appended with `"default": null`
- [ ] Schema validates

---

##### T-A-1-04: Create content.document.deleted.v1.avsc (NEW)

**Type**: schema
**depends_on**: none
**blocks**: T-E-2-02, T-F-1-01
**Target files**:
- `infra/kafka/schemas/content.document.deleted.v1.avsc` *(NEW)*

**What to build**: New Avro schema for the soft-delete event published by S4 when a tenant deletes their document. All fields are required (non-nullable) because deletions are always tenant-scoped.

**Full schema**:
```json
{
  "type": "record",
  "name": "ContentDocumentDeleted",
  "namespace": "com.worldview.content_ingestion.events",
  "doc": "Emitted by S4 when a tenant document is soft-deleted. S6 consumes this to remove chunks, sections, and entity_mentions.",
  "fields": [
    {"name": "event_id",       "type": "string", "doc": "UUIDv7"},
    {"name": "event_type",     "type": "string", "default": "content.document.deleted"},
    {"name": "schema_version", "type": "int",    "default": 1},
    {"name": "occurred_at",    "type": "string", "doc": "ISO-8601 UTC"},
    {"name": "doc_id",         "type": "string", "doc": "UUIDv7 of the deleted document"},
    {"name": "tenant_id",      "type": "string", "doc": "Owning tenant UUID — always set for deletions"}
  ]
}
```

**Acceptance criteria**:
- [ ] File exists at `infra/kafka/schemas/content.document.deleted.v1.avsc`
- [ ] Record name `ContentDocumentDeleted`, namespace `com.worldview.content_ingestion.events`
- [ ] All envelope fields present (event_id, event_type, schema_version, occurred_at)
- [ ] `tenant_id` is non-nullable string (deletions are always tenant-scoped)

---

##### T-A-1-05: Create nlp.document.ready.v1.avsc (NEW)

**Type**: schema
**depends_on**: none
**blocks**: T-F-1-02, T-F-1-03
**Target files**:
- `infra/kafka/schemas/nlp.document.ready.v1.avsc` *(NEW)*

**What to build**: New Avro schema emitted by S6 after it finishes processing a tenant-uploaded document. S4 consumes this to transition `tenant_document_uploads.status` → `READY`. This resolves OQ-001 (R7-compliant — no cross-service DB access).

**Full schema**:
```json
{
  "type": "record",
  "name": "NlpDocumentReady",
  "namespace": "com.worldview.nlp_pipeline.events",
  "doc": "Emitted by S6 after a tenant document is fully processed (chunks, embeddings, entity_mentions complete). S4 consumes to set status=READY.",
  "fields": [
    {"name": "event_id",       "type": "string", "doc": "UUIDv7"},
    {"name": "event_type",     "type": "string", "default": "nlp.document.ready"},
    {"name": "schema_version", "type": "int",    "default": 1},
    {"name": "occurred_at",    "type": "string", "doc": "ISO-8601 UTC"},
    {"name": "doc_id",         "type": "string", "doc": "UUIDv7 of the processed document"},
    {"name": "tenant_id",      "type": "string", "doc": "Owning tenant UUID"},
    {"name": "chunk_count",    "type": "int",    "doc": "Number of chunks created"},
    {"name": "word_count",     "type": "int",    "doc": "Total word count of processed document"}
  ]
}
```

**Acceptance criteria**:
- [ ] File exists at `infra/kafka/schemas/nlp.document.ready.v1.avsc`
- [ ] `chunk_count` and `word_count` fields present (S4 uses them to update `tenant_document_uploads`)
- [ ] Schema validates

---

##### T-A-1-06: Add TENANT_UPLOAD to ContentSourceType in libs/contracts

**Type**: impl
**depends_on**: none
**blocks**: T-D-1-01, T-C-1-01, T-C-1-02
**Target files**:
- `libs/contracts/src/contracts/enums.py`

**What to build**: Add `TENANT_UPLOAD = "tenant_upload"` to the `ContentSourceType` enum. This value flows through S4 → S5 → S6 as the `source_type` field in Avro events for tenant-uploaded documents. Since `source_type` in the Avro schemas is already a `string` type (confirmed — not an Avro enum), no schema change is needed.

**Exact change** in `ContentSourceType`:
```python
TENANT_UPLOAD = "tenant_upload"
```

**Downstream test impact**:
- Any test that asserts exhaustive `ContentSourceType` values must add `TENANT_UPLOAD`

**Acceptance criteria**:
- [ ] `ContentSourceType.TENANT_UPLOAD == "tenant_upload"`
- [ ] `ruff check` passes (enum member naming follows existing pattern)

---

##### T-A-1-07: Create canonical model for content.document.deleted.v1 in libs/contracts (NEW — R28)

**Type**: impl
**depends_on**: T-A-1-04
**blocks**: T-G-1-01
**Target files**:
- `libs/contracts/src/contracts/events/content/document_deleted.py` *(NEW — create `content/` sub-package if absent)*

**Why**: R28 requires every Kafka topic to have a canonical model in `libs/contracts` mirroring the Avro schema field-for-field. Without this, the architecture test `test_kafka_avro_enforcement.py` has no contract anchor for this topic.

**What to build**:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ContentDocumentDeleted:
    event_id: str
    event_type: str
    schema_version: int
    occurred_at: str
    doc_id: str
    tenant_id: str
```

**Acceptance criteria**:
- [ ] File exists; frozen dataclass with all 6 fields matching Avro schema
- [ ] `libs/contracts/src/contracts/events/content/__init__.py` created
- [ ] `ruff + mypy` pass on libs/contracts

---

##### T-A-1-08: Create canonical model for nlp.document.ready.v1 in libs/contracts (NEW — R28)

**Type**: impl
**depends_on**: T-A-1-05
**blocks**: T-G-1-01
**Target files**:
- `libs/contracts/src/contracts/events/nlp/document_ready.py` *(NEW)*

**What to build**:
```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class NlpDocumentReady:
    event_id: str
    event_type: str
    schema_version: int
    occurred_at: str
    doc_id: str
    tenant_id: str
    chunk_count: int
    word_count: int
```

**Acceptance criteria**:
- [ ] File exists; frozen dataclass with all 8 fields matching Avro schema
- [ ] `ruff + mypy` pass on libs/contracts

---

#### Pre-read (agent must read before starting)
- `infra/kafka/schemas/content.article.raw.v1.avsc` (to understand existing field structure)
- `libs/contracts/src/contracts/enums.py` (to see existing ContentSourceType values)
- `libs/contracts/src/contracts/events/nlp/` (to see existing event canonical model pattern)
- `libs/contracts/tests/` (to identify which tests assert on schema field counts)

#### Validation Gate
- [ ] `ruff check libs/contracts/` passes
- [ ] `mypy libs/contracts/src/` passes
- [ ] `python -m pytest libs/contracts/tests/ -m unit -v` — all pass
- [ ] `fastavro.parse_schema` validates all 5 modified/new Avro schema files (run: `python -c "import fastavro, json; [fastavro.parse_schema(json.load(open(f))) for f in ['content.article.raw.v1.avsc', 'content.article.stored.v1.avsc', 'nlp.article.enriched.v1.avsc', 'content.document.deleted.v1.avsc', 'nlp.document.ready.v1.avsc']]"` from `infra/kafka/schemas/`)
- [ ] `libs/contracts/src/contracts/events/content/document_deleted.py` exists with 6 fields
- [ ] `libs/contracts/src/contracts/events/nlp/document_ready.py` exists with 8 fields

#### Architecture Compliance
- [ ] R5 — All additions use `["null", "string"]` with `"default": null` ✓
- [ ] R28 — Both new event topics have canonical models in `libs/contracts` ✓

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `libs/contracts/tests/test_avro_alignment.py` | Field counts for 3 updated schemas may be asserted | Update expected field counts for the 3 schemas (+1 each) |
| Any test asserting `len(ContentSourceType)` | New enum member | Update expected count |

#### Regression Guardrails
- **R5**: Adding nullable field with `"default": null` is the ONLY forward-compatible Avro change. Never add a required (non-nullable, no default) field. If a test fails with `SchemaResolutionException`, a field was added without a default.
- **R28**: New Kafka topics (`content.document.deleted.v1`, `nlp.document.ready.v1`) MUST have canonical models in `libs/contracts` before consumers are implemented. The architecture test will fail without them.

---

## Sub-Plan B — Database Schema Changes

### Wave B-1: S5 Content-Store Migration 0005

**Goal**: Add `tenant_id` to `documents` and `dedup_hashes`; fix the unique constraints so global and per-tenant dedup coexist correctly.
**Depends on**: Wave A-1 (conceptual dependency; migration itself has no code dep)
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure (DB migration)

#### Tasks

##### T-B-1-01: Alembic Migration 0005 — content_store_db tenant isolation

**Type**: schema
**depends_on**: none
**blocks**: T-C-1-01
**Target files**:
- `services/content-store/alembic/versions/0005_add_tenant_id_to_content_store.py` *(NEW)*
- `services/content-store/src/content_store/infrastructure/db/models.py` (add `tenant_id` columns to ORM models)

**What to build**:

Migration `0005` with `down_revision = "0004_rename_dedup_hashes_constraint"`.

**Upgrade DDL** (exact SQL):

```sql
-- 1. Add tenant_id to documents (NULL = public news)
ALTER TABLE documents ADD COLUMN tenant_id UUID;
CREATE INDEX idx_documents_tenant_id ON documents(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- 2. Fix documents.content_hash uniqueness:
--    Currently: UNIQUE on content_hash (global)
--    After: partial unique per (public OR per-tenant)
-- Drop the existing unique constraint/index on content_hash
DROP INDEX IF EXISTS uq_documents_content_hash;
-- (also try: ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_content_hash_key)
CREATE UNIQUE INDEX uq_documents_content_hash_global
    ON documents(content_hash) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_documents_content_hash_tenant
    ON documents(tenant_id, content_hash) WHERE tenant_id IS NOT NULL;

-- 3. Add tenant_id to dedup_hashes
ALTER TABLE dedup_hashes ADD COLUMN tenant_id UUID;

-- 4. Fix dedup_hashes unique constraint
--    Current: uq_dedup_hashes_type_value on (hash_type, hash_value)
DROP INDEX IF EXISTS uq_dedup_hashes_type_value;
CREATE UNIQUE INDEX uq_dedup_hashes_global
    ON dedup_hashes(hash_type, hash_value) WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_dedup_hashes_tenant
    ON dedup_hashes(tenant_id, hash_type, hash_value) WHERE tenant_id IS NOT NULL;
```

**Downgrade DDL**:
```sql
DROP INDEX IF EXISTS uq_dedup_hashes_tenant;
DROP INDEX IF EXISTS uq_dedup_hashes_global;
CREATE UNIQUE INDEX uq_dedup_hashes_type_value ON dedup_hashes(hash_type, hash_value);
ALTER TABLE dedup_hashes DROP COLUMN tenant_id;
DROP INDEX IF EXISTS uq_documents_content_hash_tenant;
DROP INDEX IF EXISTS uq_documents_content_hash_global;
ALTER TABLE documents DROP COLUMN tenant_id;
```

**ORM model updates** in `models.py`:
- `DocumentModel`: add `tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=False)` — the index is created manually in the migration, not via `index=True` (avoids SQLAlchemy auto-index conflict)
- `DedupHashModel`: add `tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)`
- Remove `unique=True` from `DocumentModel.content_hash` (constraint is now via partial index)

**Also update `DedupHashRepository.check_exists()`** to accept optional `tenant_id`:
```python
async def check_exists(
    self, hash_type: str, hash_value: str, tenant_id: UUID | None = None
) -> UUID | None:
    stmt = select(DedupHashModel.doc_id).where(
        DedupHashModel.hash_type == hash_type,
        DedupHashModel.hash_value == hash_value,
        DedupHashModel.tenant_id == tenant_id,  # NULL == NULL in Python, but SQL needs IS NULL
    )
    # NOTE: SQLAlchemy == None generates IS NULL, which is correct here
```

**Acceptance criteria**:
- [ ] Migration runs cleanly on fresh DB (`alembic upgrade head`)
- [ ] Migration is reversible (`alembic downgrade -1`)
- [ ] Existing rows have `tenant_id = NULL` after upgrade
- [ ] Two partial unique indexes exist on `dedup_hashes` (verify via `\d dedup_hashes` in psql)
- [ ] Two partial unique indexes exist on `documents` for `content_hash`
- [ ] `DedupHashRepository.check_exists(hash_type, hash_value, tenant_id=None)` compiles and passes type check

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/content-store/tests/unit/infrastructure/test_dedup_repo.py` | `check_exists()` signature changed | Add `tenant_id=None` to all existing call sites |
| `services/content-store/tests/integration/test_pipeline.py` | May assert unique constraint behaviour | Update any dedup assertions that rely on global uniqueness semantics |

#### Validation Gate
- [ ] `python -m pytest services/content-store/tests/ -m unit -v` passes
- [ ] Migration upgrade + downgrade cycle passes on test DB
- [ ] `mypy services/content-store/src/ --config-file services/content-store/mypy.ini` passes

#### Regression Guardrails
- **BP-007** (NULL in unique indexes): PostgreSQL partial unique indexes correctly handle the NULL=public sentinel. The `WHERE tenant_id IS NULL` partial index guarantees global uniqueness for public news; the `WHERE tenant_id IS NOT NULL` partial index guarantees per-tenant uniqueness. Do NOT use a regular unique index with a COALESCE trick — it breaks the ON CONFLICT path.
- **BP-019** (DDL vs ORM mismatch): The `unique=True` on `DocumentModel.content_hash` MUST be removed — leaving it causes SQLAlchemy to still enforce a unique constraint at the model level even after the migration removes it.
- **BP-077** (ON CONFLICT with partial index): Any `INSERT ... ON CONFLICT` targeting `dedup_hashes` must specify `index_where="tenant_id IS NULL"` or `index_where="tenant_id IS NOT NULL"` as appropriate. Without the `index_where` predicate, Postgres cannot identify which partial index to use and raises an error.

---

### Wave B-2: S6 NLP-Pipeline Migration 0019

**Goal**: Add `tenant_id` to `chunks` and `sections`; add `document_title` to `chunks` for RAG citation denormalization (resolves OQ-002).
**Depends on**: none (can run in parallel with B-1)
**Estimated effort**: 30–45 min
**Architecture layer**: infrastructure (DB migration)

#### Tasks

##### T-B-2-01: Alembic Migration 0019 — nlp_db tenant isolation + document_title

**Type**: schema
**depends_on**: none
**blocks**: T-C-1-02, T-C-1-05
**Target files**:
- `services/nlp-pipeline/alembic/versions/0019_add_tenant_id_to_chunks_sections.py` *(NEW)*
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` (add columns to ORM models)

**What to build**:

Migration `0019` with `down_revision = "0018_add_entity_mentions_jsonb_to_chunks"`.

**Upgrade DDL**:
```sql
-- sections: tag which tenant's document produced these sections
ALTER TABLE sections ADD COLUMN tenant_id UUID;
CREATE INDEX idx_sections_tenant_id ON sections(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- chunks: primary table for HNSW filtering
ALTER TABLE chunks ADD COLUMN tenant_id UUID;
CREATE INDEX idx_chunks_tenant_id ON chunks(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- document_title: denormalized for RAG citations (avoids cross-service lookup)
ALTER TABLE chunks ADD COLUMN document_title VARCHAR(512);
```

**Downgrade DDL**:
```sql
ALTER TABLE chunks DROP COLUMN document_title;
ALTER TABLE chunks DROP COLUMN tenant_id;
DROP INDEX IF EXISTS idx_chunks_tenant_id;
ALTER TABLE sections DROP COLUMN tenant_id;
DROP INDEX IF EXISTS idx_sections_tenant_id;
```

**ORM model updates** in `models.py`:
- `SectionModel`: add `tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)`
- `ChunkModel`: add `tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)`
- `ChunkModel`: add `document_title: Mapped[str | None] = mapped_column(String(512), nullable=True)`

**Acceptance criteria**:
- [ ] Migration runs and reverses cleanly
- [ ] All existing rows have `tenant_id = NULL`, `document_title = NULL` after upgrade
- [ ] `idx_chunks_tenant_id` partial index created (verify in psql)

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| Any test constructing `ChunkModel(...)` | New columns with nullable defaults — usually no break; verify no `NOT NULL` assertion tests | Confirm tests still pass |
| `services/nlp-pipeline/tests/unit/test_chunk_model_no_tsv.py` | May assert exact column set | Update if it checks column count |

#### Validation Gate
- [ ] Migration upgrade + downgrade cycle passes
- [ ] `python -m pytest services/nlp-pipeline/tests/ -m unit -v` passes

#### Regression Guardrails
- **BP-019**: ORM model must reflect the migration DDL exactly — both `tenant_id` and `document_title` columns on `ChunkModel`, `tenant_id` on `SectionModel`. If ORM and migration diverge, integration tests against real DB will fail.

---

## Sub-Plan C — Phase 1 Pipeline Wiring

### Wave C-1: Consumer Propagation + S6 Chunk Filter + S8 Pass-Through

**Goal**: Wire `tenant_id` through the entire pipeline: S5 writes it to `documents`, S6 writes it to `chunks`/`sections` and filters HNSW search by it, S8 passes it from chat request into chunk search. After this wave, existing tenants see no change (NULL filter includes all public chunks). Private chunks from Phase 2 uploads will be correctly isolated once they exist.
**Depends on**: A-1 (Avro schemas), B-1 (S5 migration), B-2 (S6 migration)
**Estimated effort**: 75–90 min
**Architecture layer**: infrastructure + application

#### Tasks

##### T-C-1-01: S5 ArticleStorageConsumer — propagate tenant_id to documents

**Type**: impl
**depends_on**: T-A-1-02, T-B-1-01
**blocks**: none
**Target files**:
- `services/content-store/src/content_store/infrastructure/messaging/consumers/article_consumer.py`
- `services/content-store/src/content_store/infrastructure/db/repositories/document.py`

**What to build**:

The `ArticleStorageConsumer.process_message()` currently reads fields from the Avro event dict (doc_id, content_hash, etc.). It must also read `tenant_id` from `value.get("tenant_id")` (returns `None` for existing public news events) and pass it through to the `DocumentRepository.create()` call and to the `dedup_hashes` inserts.

Changes:
1. In `process_message()`: extract `tenant_id: str | None = value.get("tenant_id")`. Convert to `UUID | None` if non-None: `UUID(tenant_id) if tenant_id else None`.
2. Pass `tenant_id` into `CanonicalDocument` construction (or directly into the repository call).
3. In `DocumentRepository.create()`: set `model.tenant_id = doc.tenant_id`.
4. In `DedupHashRepository.insert()` calls: pass `tenant_id=tenant_id` to ensure the correct partial index is used for ON CONFLICT.

**Read/Write**: Write use case. Uses `UnitOfWork`.

**Acceptance criteria**:
- [ ] Public news events (tenant_id=null in Avro) → `documents.tenant_id = NULL`
- [ ] Tenant-upload events (tenant_id=uuid string) → `documents.tenant_id = UUID`
- [ ] Dedup hash inserts carry the correct `tenant_id`
- [ ] Unit tests for both paths (null and non-null tenant_id)

---

##### T-C-1-02: S6 ArticleProcessingConsumer — propagate tenant_id + document_title to chunks/sections

**Type**: impl
**depends_on**: T-A-1-03, T-B-2-01
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_repo.py` (or wherever `INSERT INTO chunks` lives)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/section_repo.py`

**What to build**:

1. In `process_message()`: extract `tenant_id: str | None = value.get("tenant_id")` and `title: str | None = value.get("title")` from the enriched event.
2. Pass `tenant_id` (as `UUID | None`) into section-creation and chunk-creation calls.
3. Pass `document_title = title` (truncated to 512 chars) into chunk-creation calls — this populates `chunks.document_title` for RAG citations.
4. Pass `tenant_id` into `entity_mentions` inserts (already has the column — verify the existing write path already handles it from migration 0010; if not, add it here).

**Read/Write**: Write. Uses `UnitOfWork`.

**Acceptance criteria**:
- [ ] `chunks.tenant_id` = NULL for public news, UUID for tenant uploads
- [ ] `sections.tenant_id` = NULL for public news, UUID for tenant uploads
- [ ] `chunks.document_title` = document title string (from event payload `title` field)
- [ ] Unit tests: null tenant → null in DB; non-null tenant → UUID in DB; document_title truncated at 512 chars

---

##### T-C-1-03: S6 ChunkSearchPort + ChunkANNRepository — add tenant_id filter

**Type**: impl
**depends_on**: T-B-2-01
**blocks**: T-C-1-04
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`

**What to build**:

1. **Port update** — add `tenant_id: str | None = None` parameter to `ann_search()` and `lexical_search()` method signatures in the `ChunkSearchPort` ABC. Default `None` is backward-compatible.

2. **Repository update** — in `ChunkANNRepository.ann_search()`, add tenant filter to the WHERE clause:

```python
# Add to existing WHERE clause (after embedding_status = 'ready'):
if tenant_id is not None:
    tid_uuid = UUID(tenant_id)
    stmt = stmt.where(
        or_(ChunkModel.tenant_id.is_(None), ChunkModel.tenant_id == tid_uuid)
    )
else:
    stmt = stmt.where(ChunkModel.tenant_id.is_(None))
```

The same filter must be applied in `lexical_search()`.

3. **Return `document_title`** in search results — add `ChunkModel.document_title` to the SELECT columns and expose it in the result object (`ChunkSearchResult` or equivalent).

**Read/Write**: Read-only. Uses `ReadOnlyUnitOfWork`.

**Acceptance criteria**:
- [ ] `tenant_id=None` → only public chunks (tenant_id IS NULL) returned
- [ ] `tenant_id="<uuid>"` → public chunks (IS NULL) AND that tenant's private chunks returned
- [ ] `document_title` present in search results
- [ ] Unit tests for both filter variants

---

##### T-C-1-04: S8 ChunkSearchRequest + _fetch_chunks() pass-through

**Type**: impl
**depends_on**: T-C-1-03
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py`
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py`

**What to build**:

1. Add `tenant_id: str | None = None` to `ChunkSearchRequest` dataclass (after existing fields, with default for backward compatibility).

2. In `_fetch_chunks()`, pass `tenant_id=resolved_query.tenant_id` (or wherever `request.tenant_id` is accessible in the orchestrator context). The orchestrator receives a `ChatRequest` which has `tenant_id` — verify the exact attribute name and pass it through.

**Read/Write**: Read-only call to S6 port.

**Acceptance criteria**:
- [ ] `ChunkSearchRequest` has `tenant_id: str | None = None`
- [ ] `_fetch_chunks()` passes `tenant_id` from the chat request context
- [ ] Unit test: `_fetch_chunks()` produces `ChunkSearchRequest` with correct `tenant_id`
- [ ] Existing `ChunkSearchRequest` construction calls outside this file compile without changes (default None)

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| Any test constructing `ChunkSearchRequest(...)` with positional args | New field added — if positional, breaks | All construction uses keyword args (verify); if positional, add `tenant_id=None` |

#### Pre-read (agent must read before starting)
- `services/content-store/src/content_store/infrastructure/messaging/consumers/article_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/chunk_search.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (to understand existing Pydantic ChunkSearchRequest)
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` (to understand how ann_search/lexical_search are called)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py`
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py`

#### Validation Gate
- [ ] `ruff check services/content-store/ services/nlp-pipeline/ services/rag-chat/` passes
- [ ] `mypy` passes on all three services
- [ ] `python -m pytest services/content-store/tests/ -m unit -v` passes
- [ ] `python -m pytest services/nlp-pipeline/tests/ -m unit -v` passes
- [ ] `python -m pytest services/rag-chat/tests/ -m unit -v` passes
- [ ] Architecture tests pass: `python -m pytest tests/architecture/ -v`

#### Architecture Compliance
- [ ] R27 — S6 chunk search remains `ReadOnlyUnitOfWork`
- [ ] R25 — `_fetch_chunks()` calls S6 through `ChunkSearchPort` (no direct infra import)
- [ ] R12 — No new `print()` or `import logging` statements

#### Break Impact
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/pipeline/test_retrieval_orchestrator.py` | `_fetch_chunks()` now passes `tenant_id` | Update mock assertions to include `tenant_id` in `ChunkSearchRequest` |
| `services/nlp-pipeline/tests/unit/infrastructure/test_chunk_repository.py` | `ann_search()` signature changed | Update call sites with `tenant_id=None` |

#### Regression Guardrails
- **HR-053**: Every code path that retrieves chunks MUST apply the `(tenant_id IS NULL OR tenant_id = :tid)` filter. If `tenant_id=None` is passed, use `WHERE tenant_id IS NULL` (not no filter). Dropping the filter entirely is a data leak.

---

##### T-C-1-05: S6 API Pydantic ChunkSearchRequest + route handler — tenant_id pass-through (NEW — R-001 fix)

**Type**: impl
**depends_on**: T-C-1-03
**blocks**: T-C-1-04
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (add `tenant_id` field to Pydantic `ChunkSearchRequest`)
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/search.py` (pass `tenant_id` from HTTP request body to `ann_search()`/`lexical_search()`)

**Why this task exists**: The `ChunkSearchPort` ABC and `ChunkANNRepository` were updated in T-C-1-03 to accept `tenant_id`. However, S6 exposes chunk search via an HTTP API. The Pydantic request schema (`api/schemas.py:ChunkSearchRequest`, a `BaseModel`) and the route handler (`api/routes/search.py:search_chunks`) sit between the HTTP layer and the port — if `tenant_id` is not added to both, it is silently dropped at the HTTP boundary. **A missing `tenant_id` here is a data leak.**

**What to build**:

1. In `api/schemas.py`, add to the Pydantic `ChunkSearchRequest`:
```python
tenant_id: str | None = None  # None = public chunks only (tenant-unscoped callers)
```

2. In `api/routes/search.py` `search_chunks()` handler, pass `tenant_id` from `body.tenant_id` when calling `ann_search()` or `lexical_search()` on the use case or port.

**Acceptance criteria**:
- [ ] `tenant_id: str | None = None` present on S6 Pydantic `ChunkSearchRequest`
- [ ] Route handler passes `tenant_id` through to the chunk search call
- [ ] Unit test: `POST /api/v1/search/chunks` with `tenant_id` in body → verify filter reaches the repository mock
- [ ] Existing tests (no `tenant_id` in body) continue to pass (backward-compatible default `None`)

---

## Sub-Plan D — Tenant Upload Domain & Infrastructure

### Wave D-1: S4 Domain Entities, Port Interfaces, Domain Errors

**Goal**: Define the pure domain layer for tenant document uploads — entities, enums, port ABCs, and domain errors. No infrastructure code in this wave. All downstream waves (D-2, E-1, E-2) depend on these definitions.
**Depends on**: A-1 (ContentSourceType.TENANT_UPLOAD)
**Estimated effort**: 45–60 min
**Architecture layer**: domain

#### Tasks

##### T-D-1-01: TenantDocumentUpload entity + UploadStatus enum (NEW)

**Type**: impl
**depends_on**: T-A-1-06
**blocks**: T-D-2-02, T-E-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/domain/tenant_upload.py` *(NEW)*

**What to build**:

```python
# UploadStatus enum
class UploadStatus(str, Enum):
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"
    DELETED    = "deleted"

# TenantDocumentUpload frozen dataclass
@dataclass(frozen=True)
class TenantDocumentUpload:
    id:                   UUID         # UUIDv7
    tenant_id:            UUID
    uploaded_by_user_id:  UUID
    filename:             str          # 1–512 chars
    title:                str          # 1–512 chars
    content_type:         str          # "application/pdf" | "text/plain"
    content_hash:         str          # SHA-256 hex, 64 chars
    byte_size:            int          # > 0
    minio_bronze_key:     str
    status:               UploadStatus
    uploaded_at:          datetime     # UTC-aware

    # Optional — populated as pipeline progresses
    word_count:           int | None = None
    chunk_count:          int | None = None
    minio_silver_key:     str | None = None
    error_message:        str | None = None
    ready_at:             datetime | None = None
    deleted_at:           datetime | None = None

    def __post_init__(self) -> None:
        if self.byte_size <= 0:
            raise ValueError("byte_size must be > 0")
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be 64-char hex string")
        if self.uploaded_at.tzinfo is None:
            raise ValueError("uploaded_at must be UTC-aware")

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        title: str,
        content_type: str,
        content_hash: str,
        byte_size: int,
        minio_bronze_key: str,
    ) -> "TenantDocumentUpload":
        from common.ids import new_uuid7
        from common.time import utc_now
        return cls(
            id=new_uuid7(),
            tenant_id=tenant_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            title=title,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=byte_size,
            minio_bronze_key=minio_bronze_key,
            status=UploadStatus.PROCESSING,
            uploaded_at=utc_now(),
        )
```

**Invariants** (enforced in `__post_init__`):
- `byte_size > 0`
- `content_hash` is exactly 64 hex characters
- `uploaded_at` is UTC-aware (tzinfo is not None)

**Acceptance criteria**:
- [ ] `TenantDocumentUpload.create()` produces `status=PROCESSING`, `id` is UUIDv7
- [ ] `__post_init__` raises `ValueError` for invalid byte_size, invalid hash length, naive datetime
- [ ] `ruff` + `mypy` pass on new file
- [ ] Unit tests: 4 invariant tests + 1 factory test

---

##### T-D-1-02: S4 Port Interfaces for upload domain (NEW)

**Type**: impl
**depends_on**: T-D-1-01
**blocks**: T-D-2-03, T-E-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/ports/tenant_upload.py` *(NEW)*

**What to build**: Three ABC port interfaces (R25 — use cases must depend on ports, not concrete infra).

```python
class TenantDocumentUploadRepositoryPort(ABC):
    @abstractmethod
    async def create(self, doc: TenantDocumentUpload) -> None: ...

    @abstractmethod
    async def get(self, doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None: ...

    @abstractmethod
    async def get_for_update(
        self, doc_id: UUID, tenant_id: UUID
    ) -> TenantDocumentUpload | None:
        """SELECT ... FOR UPDATE. Used by DeleteTenantDocumentUseCase to prevent race conditions."""
        ...

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: UUID,
        status: UploadStatus | None,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> tuple[list[TenantDocumentUpload], int]: ...

    @abstractmethod
    async def set_deleted(self, doc_id: UUID, tenant_id: UUID) -> None: ...

    @abstractmethod
    async def set_ready(
        self, doc_id: UUID, tenant_id: UUID, chunk_count: int, word_count: int
    ) -> None: ...


class TenantDedupHashRepositoryPort(ABC):
    """Per-tenant dedup check — scoped to (tenant_id, hash_type, hash_value)."""
    @abstractmethod
    async def check_exists(
        self, hash_type: str, hash_value: str, tenant_id: UUID
    ) -> UUID | None: ...

    @abstractmethod
    async def insert(
        self, doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID
    ) -> None: ...


class UploadRateLimitPort(ABC):
    """Valkey sliding-window rate limit for uploads."""
    @abstractmethod
    async def check_and_increment(
        self, tenant_id: UUID, window_seconds: int, limit: int
    ) -> bool:
        """Return True if upload is allowed; False if rate limit exceeded."""
        ...

    @abstractmethod
    async def get_reset_at(self, tenant_id: UUID) -> datetime | None: ...
```

**Acceptance criteria**:
- [ ] Three ABCs in `application/ports/tenant_upload.py`
- [ ] All methods are `abstractmethod` with correct signatures
- [ ] No infrastructure imports (R12 domain purity — ports are application layer)

---

##### T-D-1-03: S4 Domain Errors for upload (NEW)

**Type**: impl
**depends_on**: T-D-1-01
**blocks**: T-E-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/domain/exceptions.py` (extend existing file — `DomainError` base is already defined here)

**What to build**: Domain error classes for the upload flow. Each maps to a specific HTTP status in the router.

```python
class UnsupportedFileTypeError(DomainError):
    """File MIME type is not in the allowed set (PDF, plain text)."""

class FileTooLargeError(DomainError):
    """File exceeds the 50 MB size limit."""
    def __init__(self, byte_size: int, limit: int) -> None: ...

class TextExtractionError(DomainError):
    """Text extraction yielded empty or whitespace-only content."""

class DuplicateDocumentError(DomainError):
    """Same content (tenant_id, content_hash) already exists."""
    def __init__(self, existing_doc_id: UUID) -> None: ...
    existing_doc_id: UUID

class UploadRateLimitError(DomainError):
    """Tenant has exceeded the daily upload rate limit."""
    def __init__(self, resets_at: datetime) -> None: ...
    resets_at: datetime
```

All must inherit from the existing `DomainError` base class defined in `content_ingestion.domain.exceptions.DomainError` (confirmed — file is `domain/exceptions.py`, NOT `domain/errors.py`).

**Acceptance criteria**:
- [ ] All 5 error classes defined
- [ ] All inherit from `DomainError` base
- [ ] `DuplicateDocumentError.existing_doc_id` is accessible attribute
- [ ] `UploadRateLimitError.resets_at` is accessible attribute

#### Pre-read (agent must read before starting)
- `services/content-ingestion/src/content_ingestion/domain/entities.py`
- `services/content-ingestion/src/content_ingestion/domain/` (list files to find existing errors.py)
- `services/content-ingestion/src/content_ingestion/application/ports/` (list existing ports)

#### Validation Gate
- [ ] `ruff check services/content-ingestion/src/content_ingestion/domain/` passes
- [ ] `mypy services/content-ingestion/src/content_ingestion/domain/` passes
- [ ] `python -m pytest services/content-ingestion/tests/ -m unit -k "tenant_upload or upload_status" -v` — new unit tests pass

#### Architecture Compliance
- [ ] R12 — `tenant_upload.py` domain entity has ZERO infrastructure imports
- [ ] R10 — `create()` uses `new_uuid7()` (not `uuid4()`)
- [ ] R11 — `create()` uses `utc_now()` (not `datetime.now()`)

#### Regression Guardrails
- **R12 (domain purity)**: The domain layer must not import from `infrastructure/`, `messaging/`, `storage/`, or any external library except standard types. If you find yourself importing `sqlalchemy` or `pdfminer` in this wave, you are in the wrong layer.

---

### Wave D-2: S4 Infrastructure — Migration, ORM, Repositories

**Goal**: Create the `tenant_document_uploads` table; implement the concrete repository and rate-limit adapter that back the ports defined in D-1.
**Depends on**: D-1
**Estimated effort**: 60–75 min
**Architecture layer**: infrastructure

#### Tasks

##### T-D-2-01: S4 Alembic Migration 0007 — tenant_document_uploads table

**Type**: schema
**depends_on**: T-D-1-01
**blocks**: T-D-2-02
**Target files**:
- `services/content-ingestion/alembic/versions/0007_add_tenant_document_uploads.py` *(NEW)*

**What to build**: Migration `0007` with `down_revision = "0006_source_dedup_config_hash"`.

**Upgrade DDL**:
```sql
CREATE TABLE tenant_document_uploads (
    id                  UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    uploaded_by_user_id UUID NOT NULL,
    filename            VARCHAR(512) NOT NULL,
    title               VARCHAR(512) NOT NULL,
    content_type        VARCHAR(128) NOT NULL,
    content_hash        VARCHAR(64) NOT NULL,
    byte_size           BIGINT NOT NULL,
    word_count          INTEGER,
    chunk_count         INTEGER,
    status              VARCHAR(32) NOT NULL DEFAULT 'processing'
                        CONSTRAINT chk_tdu_status CHECK (
                            status IN ('processing', 'ready', 'failed', 'deleted')
                        ),
    minio_bronze_key    VARCHAR(1024) NOT NULL,
    minio_silver_key    VARCHAR(1024),
    error_message       TEXT,
    uploaded_at         TIMESTAMPTZ NOT NULL,
    ready_at            TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_tdu_tenant_status   ON tenant_document_uploads(tenant_id, status);
CREATE INDEX idx_tdu_tenant_hash     ON tenant_document_uploads(tenant_id, content_hash);
CREATE INDEX idx_tdu_uploaded_at     ON tenant_document_uploads(tenant_id, uploaded_at DESC);
```

**Downgrade DDL**: `DROP TABLE IF EXISTS tenant_document_uploads CASCADE;`

**Acceptance criteria**:
- [ ] Migration runs and reverses cleanly
- [ ] CHECK constraint on `status` values enforced (verify with invalid INSERT)
- [ ] All three indexes created

---

##### T-D-2-02: S4 ORM Model TenantDocumentUploadModel (NEW)

**Type**: impl
**depends_on**: T-D-2-01
**blocks**: T-D-2-03
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/db/models.py` (add new model class)

**What to build**: SQLAlchemy mapped class `TenantDocumentUploadModel` mirroring the migration DDL exactly. Column names and types must match 1-to-1 with the migration.

Key SQLAlchemy types: `PG_UUID(as_uuid=True)` for UUID columns, `BIGINT` for byte_size, `String(32)` for status, `TIMESTAMPTZ` → `DateTime(timezone=True)`.

No `unique=True` on `content_hash` — uniqueness is enforced per-tenant by the `idx_tdu_tenant_hash` index (but this index is not UNIQUE — duplicate prevention is done at the application layer via `check_exists()` before insert).

**Acceptance criteria**:
- [ ] All columns in migration DDL have corresponding `mapped_column()` in ORM model
- [ ] `mypy` passes with strict column type annotations

---

##### T-D-2-03: S4 TenantDocumentUploadRepository (NEW)

**Type**: impl
**depends_on**: T-D-2-02, T-D-1-02
**blocks**: T-E-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/db/repositories/tenant_upload.py` *(NEW)*

**What to build**: Concrete implementation of `TenantDocumentUploadRepositoryPort`.

- `create()`: INSERT, mapping domain entity → ORM model. Use `session.add()` + `await session.flush()`.
- `get(doc_id, tenant_id)`: `SELECT WHERE id = :id AND tenant_id = :tid`. Return None if not found (avoids tenant enumeration).
- `get_for_update(doc_id, tenant_id)`: `SELECT WHERE id = :id AND tenant_id = :tid FOR UPDATE`. Used by `DeleteTenantDocumentUseCase` to prevent double-delete races.
- `list_by_tenant()`: Keyset pagination via `WHERE tenant_id = :tid AND (uploaded_at, id) < cursor ORDER BY uploaded_at DESC, id DESC LIMIT :limit+1`. Second query for total count: `SELECT COUNT(*) WHERE tenant_id = :tid`.
- `set_deleted()`: `UPDATE SET status = 'deleted', deleted_at = :now WHERE id = :id AND tenant_id = :tid`.
- `set_ready()`: `UPDATE SET status = 'ready', ready_at = :now, chunk_count = :cc, word_count = :wc WHERE id = :id AND tenant_id = :tid`.

**Read/Write**: `list_by_tenant` is read-only (uses `ReadOnlyUnitOfWork`); all other methods use the write session.

**Acceptance criteria**:
- [ ] Implements all 6 methods of `TenantDocumentUploadRepositoryPort`
- [ ] `get()` and `get_for_update()` both return `None` for wrong tenant (not raises)
- [ ] `list_by_tenant()` returns correct cursor for next page
- [ ] Unit tests: 7 tests (one per method + pagination boundary)

---

##### T-D-2-04: S4 UploadRateLimitAdapter (NEW)

**Type**: impl
**depends_on**: T-D-1-02
**blocks**: T-E-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/valkey/upload_rate_limit.py` *(NEW)*

**What to build**: Concrete implementation of `UploadRateLimitPort` using Valkey sliding-window counter.

Key: `upload:v1:tenant:{tenant_id}` (INCR + EXPIRE pattern).

```python
async def check_and_increment(self, tenant_id: UUID, window_seconds: int, limit: int) -> bool:
    try:
        key = f"upload:v1:tenant:{tenant_id}"
        count = await self._valkey.incr(key)
        if count == 1:
            await self._valkey.expire(key, window_seconds)
        return count <= limit
    except Exception:
        log.warning("upload_rate_limit_valkey_unavailable", tenant_id=str(tenant_id))
        upload_ratelimit_bypass_total.inc()
        return True  # fail-open
```

Prometheus counter `upload_ratelimit_bypass_total` must be defined in S4's metrics module.

**Acceptance criteria**:
- [ ] `check_and_increment()` returns `True` when count ≤ limit
- [ ] Returns `False` when count > limit
- [ ] Fail-open when Valkey raises exception
- [ ] `upload_ratelimit_bypass_total` counter incremented on Valkey failure
- [ ] Unit tests with mocked Valkey: allow path, block path, fail-open path

#### Validation Gate (Wave D-2)
- [ ] `python -m pytest services/content-ingestion/tests/ -m unit -v` passes
- [ ] Migration upgrade + downgrade clean
- [ ] `mypy services/content-ingestion/src/` passes

#### Regression Guardrails
- **BP-019**: ORM model column types must match migration DDL exactly. `byte_size` is `BIGINT` in SQL → `BigInteger` in SQLAlchemy (not `Integer`).
- **R24**: Repository methods must not hold DB session during Valkey calls. Rate limit check happens before session acquisition in the upload use case.

---

## Sub-Plan E — Tenant Upload Application & API

### Wave E-1: S4 Use Cases

**Goal**: Implement the four use cases orchestrating the upload flow. The upload use case is the most complex — it must enforce R24 (no session during MinIO I/O), run PDF extraction in `asyncio.to_thread()`, and implement compensating GC if the DB write fails after MinIO write.
**Depends on**: D-1, D-2
**Estimated effort**: 75–90 min
**Architecture layer**: application

#### Tasks

##### T-E-1-01: UploadTenantDocumentUseCase (NEW)

**Type**: impl
**depends_on**: T-D-1-01, T-D-1-02, T-D-1-03, T-D-2-03, T-D-2-04
**blocks**: T-E-2-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/upload_tenant_document.py` *(NEW)*

**What to build**: Async use case following the exact step order from PRD §6.5 with R24 and HR-019 compliance.

**Full step sequence** (step order is CRITICAL — enforces R24):

```
1. Validate content_type ∈ {"application/pdf", "text/plain"}
   → raise UnsupportedFileTypeError

2. Validate len(file_bytes) ≤ 50_000_000
   → raise FileTooLargeError(byte_size, 50_000_000)

3. Check rate limit (Valkey — no DB session open yet)
   → raise UploadRateLimitError(resets_at) if exceeded

4. Extract text (NO DB session open — R24 compliance):
   - PDF: await asyncio.to_thread(_extract_pdf_text, file_bytes)
     where _extract_pdf_text is a sync function using pdfminer.six
   - Plain text: file_bytes.decode("utf-8", errors="replace").strip()
   → raise TextExtractionError if result is empty or len > 500_000 chars

5. Compute content_hash = hashlib.sha256(text.encode()).hexdigest()
   Compute word_count = len(text.split())

6. [NO DB session open during steps 1-5]
   Acquire write UoW session:

7. Per-tenant dedup check (with session):
   existing_id = await dedup_repo.check_exists("sha256", content_hash, tenant_id)
   → raise DuplicateDocumentError(existing_id) if found

8. Generate doc_id = new_uuid7()
   Build minio_bronze_key = f"tenant-uploads/{tenant_id}/{doc_id}/bronze/{filename}"

9. [RELEASE session before MinIO I/O — R24]
   Commit/close the read check UoW.

10. PUT MinIO bronze object (NO DB session):
    await storage.put_object(minio_bronze_key, file_bytes, content_type)
    pending_bronze_key = minio_bronze_key  # for compensating GC

11. Re-acquire write UoW session:

12. Create TenantDocumentUpload entity (status=PROCESSING)
    await upload_repo.create(doc)
    await dedup_repo.insert("sha256", content_hash, tenant_id, doc_id)
    [append to outbox: topic=content.article.raw.v1, tenant_id=str(tenant_id), ...]
    → If DB write fails:
        try: await storage.delete_object(pending_bronze_key)
        except: log.warning("compensating_gc_failed", key=pending_bronze_key)
        raise original exception

13. Return UploadResult(doc_id=doc.id, status="processing", title=title, filename=filename)
```

**Pydantic input model**:
```python
@dataclass(frozen=True)
class UploadTenantDocumentInput:
    file_bytes: bytes
    filename: str
    content_type: str
    tenant_id: UUID
    user_id: UUID
    title: str | None  # None → use filename stem
```

**Port dependencies** (R25 — all injected via DI):
- `TenantDocumentUploadRepositoryPort`
- `TenantDedupHashRepositoryPort`
- `UploadRateLimitPort`
- `StoragePort` (existing — from `libs/storage`)

**Read/Write**: Write. Uses `UnitOfWork` (write session acquired at step 6 and step 11).

**Acceptance criteria**:
- [ ] UnsupportedFileTypeError raised for wrong MIME
- [ ] FileTooLargeError raised for > 50 MB
- [ ] TextExtractionError raised for empty extraction result
- [ ] DuplicateDocumentError raised for existing (tenant_id, content_hash)
- [ ] UploadRateLimitError raised when limit exceeded
- [ ] MinIO write happens BEFORE DB insert (R24: no session held during MinIO call)
- [ ] Compensating GC deletes MinIO object if DB write fails
- [ ] PDF extraction uses `asyncio.to_thread()` (verified in unit test by asserting loop is not blocked)
- [ ] Return value has `doc_id` (UUIDv7), `status = "processing"`
- [ ] 8+ unit tests covering all error paths and happy path

---

##### T-E-1-02: GetTenantDocumentUseCase + ListTenantDocumentsUseCase (NEW)

**Type**: impl
**depends_on**: T-D-1-02, T-D-2-03
**blocks**: T-E-2-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/get_tenant_document.py` *(NEW)*
- `services/content-ingestion/src/content_ingestion/application/use_cases/list_tenant_documents.py` *(NEW)*

**GetTenantDocumentUseCase**:
- Input: `doc_id: UUID, tenant_id: UUID`
- Output: `TenantDocumentUpload | None`
- Logic: `await repo.get(doc_id, tenant_id)` — returns None for wrong tenant (no info leak)
- **Read/Write**: Read-only. Uses `ReadOnlyUnitOfWork`.

**ListTenantDocumentsUseCase**:
- Input: `tenant_id: UUID, status: UploadStatus | None, limit: int, cursor: str | None`
- Output: `ListResult(items: list[TenantDocumentUpload], next_cursor: str | None, total: int)`
- Cursor encoding: base64-encode `f"{uploaded_at.isoformat()}|{doc_id}"` for keyset pagination
- Cursor decoding: split on `|`, parse datetime and UUID
- **Read/Write**: Read-only. Uses `ReadOnlyUnitOfWork`.

**Acceptance criteria**:
- [ ] `Get` returns None for non-existent doc or wrong tenant
- [ ] `List` returns correct paginated results with next_cursor
- [ ] Cursor decoding/encoding is symmetric (encode → decode → same values)

---

##### T-E-1-03: DeleteTenantDocumentUseCase (NEW)

**Type**: impl
**depends_on**: T-D-1-02, T-D-1-03, T-D-2-03
**blocks**: T-E-2-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/application/use_cases/delete_tenant_document.py` *(NEW)*

**What to build**:

Steps:
1. `await repo.get_for_update(doc_id, tenant_id)` — returns None if wrong tenant → raise `NotFoundError`.
2. If `status == DELETED` → raise `AlreadyDeletedError` (409).
3. `await repo.set_deleted(doc_id, tenant_id)`.
4. Append outbox event: `content.document.deleted.v1` with `doc_id`, `tenant_id`, `event_id=new_uuid7()`, `occurred_at=utc_now()`.

**Read/Write**: Write. Uses `UnitOfWork`. Dual write (DB + Kafka) via outbox (R8).

**Acceptance criteria**:
- [ ] NotFoundError for wrong tenant (not 403)
- [ ] AlreadyDeletedError for already-deleted doc
- [ ] Outbox event appended atomically within same UoW
- [ ] Unit tests: happy path, wrong tenant, already deleted

#### Validation Gate (Wave E-1)
- [ ] `python -m pytest services/content-ingestion/tests/ -m unit -v` — all pass, ≥ 20 new tests
- [ ] `ruff + mypy` on S4 pass
- [ ] Architecture tests pass

#### Architecture Compliance
- [ ] R24 — `UploadTenantDocumentUseCase` step order: validate → rate limit check → extract (thread) → MinIO → DB (no session during MinIO)
- [ ] R25 — All 4 use cases depend only on port ABCs (no concrete infra imports)
- [ ] R27 — Get and List use cases use `ReadOnlyUnitOfWork`
- [ ] R8 — Delete use case uses outbox pattern for content.document.deleted.v1

#### Regression Guardrails
- **HR-019 (blocking I/O in async)**: `pdfminer.six` is synchronous. The unit test for `UploadTenantDocumentUseCase` should mock `asyncio.to_thread` to verify it's called with the sync extraction function. Direct `pdfminer.extract_text()` call in an async function blocks the event loop.
- **R24**: Never open a DB session before the MinIO write in the upload use case. The session MUST be acquired only after the MinIO PUT succeeds (or compensating delete runs on failure).

---

### Wave E-2: S4 API Endpoints, Dispatcher Update, S9 Routing

**Goal**: Wire the use cases to HTTP endpoints, register new Kafka topics in the dispatcher, and add proxy routes in S9.
**Depends on**: E-1, A-1 (Avro schemas)
**Estimated effort**: 60–75 min
**Architecture layer**: API

#### Tasks

##### T-E-2-01: S4 documents router (NEW)

**Type**: impl
**depends_on**: T-E-1-01, T-E-1-02, T-E-1-03
**blocks**: T-E-2-03
**Target files**:
- `services/content-ingestion/src/content_ingestion/api/routes/documents.py` *(NEW)*
- `services/content-ingestion/src/content_ingestion/api/main.py` (register new router)
- `services/content-ingestion/src/content_ingestion/api/schemas/tenant_upload.py` *(NEW)*

**What to build**:

Four endpoints following the PRD §6.2 spec:

```python
router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# POST /api/v1/documents/upload
@router.post("/upload", status_code=202, response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
    title: str | None = Form(None),
    tenant_id: UUID = Depends(tenant_id_dep),
    user_id: UUID = Depends(user_id_dep),
    uow: UoWDep = ...,
    ...
) -> UploadResponse: ...

# GET /api/v1/documents/{doc_id}
@router.get("/{doc_id}", response_model=DocumentStatusResponse)
async def get_document(doc_id: UUID, tenant_id: UUID = Depends(...), read_uow: ReadUoWDep = ...) -> ...: ...

# GET /api/v1/documents
@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status: UploadStatus | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    tenant_id: UUID = Depends(...),
    read_uow: ReadUoWDep = ...,
) -> ...: ...

# DELETE /api/v1/documents/{doc_id}
@router.delete("/{doc_id}", status_code=200, response_model=DeleteResponse)
async def delete_document(doc_id: UUID, tenant_id: UUID = Depends(...), uow: UoWDep = ...) -> ...: ...
```

**Auth pattern**: The S4 service uses `InternalJWTMiddleware` (PRD-0025). Tenant and user IDs come from `X-Tenant-ID` and `X-User-ID` headers forwarded by S9. Create FastAPI `Depends()` extractors for these headers — verify the exact header names and extraction pattern by reading how the portfolio service does it.

**Error mapping** (domain error → HTTP):
- `UnsupportedFileTypeError` → 400
- `FileTooLargeError` → 413
- `TextExtractionError` → 422
- `DuplicateDocumentError(existing_doc_id)` → 409 with body `{"existing_doc_id": "..."}`
- `UploadRateLimitError(resets_at)` → 429 with body `{"resets_at": "..."}`
- `NotFoundError` → 404
- `AlreadyDeletedError` → 409

**Pydantic response schemas** (in `schemas/tenant_upload.py`):
```python
class UploadResponse(BaseModel):
    doc_id: UUID
    status: str  # always "processing"
    title: str
    filename: str

class DocumentStatusResponse(BaseModel):
    doc_id: UUID
    title: str
    filename: str
    status: str
    word_count: int | None
    chunk_count: int | None
    uploaded_at: datetime
    ready_at: datetime | None
    error_message: str | None

class DeleteResponse(BaseModel):
    doc_id: UUID
    status: str  # always "deleted"
```

**Acceptance criteria**:
- [ ] `POST /upload` returns 202 with doc_id
- [ ] `POST /upload` with wrong MIME returns 400
- [ ] `GET /{doc_id}` returns 404 for wrong tenant (not 403)
- [ ] `DELETE /{doc_id}` returns 200 with `{"doc_id": "...", "status": "deleted"}`
- [ ] Router registered in `main.py`

---

##### T-E-2-02: S4 OutboxDispatcher — register new topics

**Type**: impl
**depends_on**: T-A-1-04
**blocks**: T-F-1-01
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/messaging/outbox/dispatcher.py`

**What to build**: Register `content.document.deleted.v1` serializer in `_get_value_serializer()`.

```python
# Add to the serializers dict:
"content.document.deleted.v1": self._build_avro_serializer("content.document.deleted.v1.avsc"),
```

Verify the exact helper method name used for building serializers (from the explore output it's inferred as a helper — read the file to confirm).

**Acceptance criteria**:
- [ ] `content.document.deleted.v1` topic has a registered serializer
- [ ] `KeyError` on first deletion event is impossible (BP-147 avoided)
- [ ] Unit test: dispatcher serializes a `content.document.deleted.v1` payload without error

---

##### T-E-2-03: S9 api-gateway — add 3 proxy routes for document endpoints

**Type**: impl
**depends_on**: T-E-2-01
**blocks**: G-1
**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py` (add 4 new route functions to the existing large proxy file; a `routers/` directory does NOT exist in S9)

**What to build**: Four proxy routes forwarding to S4.

Pattern: S9 has no separate routers/ directory — all proxy routes live in `routes/proxy.py`. A `content_ingestion` httpx client is already initialized in `app.py` (line 158). Read how other routes in `proxy.py` use their service clients (e.g., the nlp-pipeline routes), and follow the same pattern (httpx async client, X-Internal-JWT, X-Tenant-ID/X-User-ID header forwarding, timeout).

Routes to add:
- `POST /api/v1/documents/upload` → S4 `POST /api/v1/documents/upload` (multipart pass-through)
- `GET /api/v1/documents/{doc_id}` → S4 `GET /api/v1/documents/{doc_id}`
- `GET /api/v1/documents` → S4 `GET /api/v1/documents` (forward query params)
- `DELETE /api/v1/documents/{doc_id}` → S4 `DELETE /api/v1/documents/{doc_id}`

**Acceptance criteria**:
- [ ] All 4 routes added to S9
- [ ] multipart/form-data forwarded correctly for upload route
- [ ] X-Tenant-ID and X-User-ID headers forwarded from JWT claims to S4
- [ ] Unit tests for each route (mock S4 response)

#### Validation Gate (Wave E-2)
- [ ] `python -m pytest services/content-ingestion/tests/ -m unit -v` passes
- [ ] `python -m pytest services/api-gateway/tests/ -m unit -v` passes
- [ ] `ruff + mypy` on S4 and S9 pass

#### Regression Guardrails
- **BP-064**: `DELETE` endpoint returns `200` with response body, NOT `204 No Content`. Using `status_code=204` with a response model raises a FastAPI validation error.
- **BP-147**: New Kafka topic `content.document.deleted.v1` MUST be registered in S4's dispatcher BEFORE any deletion event is published. A missing serializer raises `KeyError` which sends events to DLQ.

---

## Sub-Plan F — Event Consumers & Status Feedback

### Wave F-1: DocumentDeletionConsumer (S6) + DocumentReadyConsumer (S4) + S6 Ready Event Emission

**Goal**: Close the loop on async processing: S6 emits `nlp.document.ready.v1` after enrichment, S4 updates `status → READY`; S6 also consumes deletion events to purge chunks/sections/entity_mentions.
**Depends on**: A-1 (schemas), B-2 (S6 migration), E-2 (deletion events)
**Estimated effort**: 75–90 min
**Architecture layer**: infrastructure (Kafka consumers)

#### Tasks

##### T-F-1-01: S6 DocumentDeletionConsumer (NEW)

**Type**: impl
**depends_on**: T-A-1-04, T-B-2-01
**blocks**: G-1
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/document_deletion_consumer.py` *(NEW)*
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/_consumer_main.py` (add new consumer entrypoint)
- `services/nlp-pipeline/docker-compose.yml` / process config (add new worker process)

**What to build**: Kafka consumer conforming to `BaseKafkaConsumer` + `ValkeyDedupMixin` (R9, architecture test `CONSUMER-DEDUP-001` enforces this).

```python
class DocumentDeletionConsumer(ValkeyDedupMixin, BaseKafkaConsumer):
    _dedup_prefix = "nlp:dd:dedup"  # "dd" = document deletion
    _topic = "content.document.deleted.v1"
    _consumer_group = "s6-document-deletion"

    async def process_message(self, key, value, headers) -> None:
        doc_id = UUID(value["doc_id"])
        tenant_id = UUID(value["tenant_id"])
        async with self._uow_factory() as uow:
            await uow.session.execute(
                text("DELETE FROM entity_mentions WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
            await uow.session.execute(
                text("DELETE FROM sections WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
            # chunk_embeddings cascade via FK on chunk_id
            await uow.session.execute(
                text("DELETE FROM chunks WHERE doc_id = :doc_id AND tenant_id = :tid"),
                {"doc_id": doc_id, "tid": tenant_id},
            )
```

**Idempotency**: `DELETE WHERE doc_id AND tenant_id` is naturally idempotent — if rows are already gone, DELETE is a no-op. ValkeyDedupMixin provides additional dedup at the Kafka layer.

**Acceptance criteria**:
- [ ] Extends `ValkeyDedupMixin, BaseKafkaConsumer` (architecture test passes)
- [ ] `_dedup_prefix`, `_topic`, `_consumer_group` set
- [ ] Re-delivery of same event is a no-op (idempotency test)
- [ ] Worker process wired into service startup (R22: independent process)

---

##### T-F-1-02: S4 DocumentReadyConsumer (NEW)

**Type**: impl
**depends_on**: T-A-1-05, T-D-2-03
**blocks**: G-1
**Target files**:
- `services/content-ingestion/src/content_ingestion/infrastructure/messaging/consumers/document_ready_consumer.py` *(NEW)*

**What to build**: S4 consumes `nlp.document.ready.v1` to transition document status → READY.

```python
class DocumentReadyConsumer(ValkeyDedupMixin, BaseKafkaConsumer):
    _dedup_prefix = "ci:dr:dedup"
    _topic = "nlp.document.ready.v1"
    _consumer_group = "s4-document-ready"

    async def process_message(self, key, value, headers) -> None:
        doc_id = UUID(value["doc_id"])
        tenant_id = UUID(value["tenant_id"])
        chunk_count = int(value["chunk_count"])
        word_count = int(value["word_count"])
        async with self._uow_factory() as uow:
            await self._upload_repo.set_ready(doc_id, tenant_id, chunk_count, word_count)
```

**Acceptance criteria**:
- [ ] `set_ready()` called with correct values from event payload
- [ ] Re-delivery of same event → idempotent (set_ready is an UPDATE, safe to re-run)
- [ ] Unit test: mock event payload → verify set_ready called with correct args

---

##### T-F-1-03: S6 ArticleProcessingConsumer — emit nlp.document.ready.v1 after processing tenant docs

**Type**: impl
**depends_on**: T-A-1-05, T-B-2-01, T-C-1-02
**blocks**: G-1
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/outbox/dispatcher.py` (register nlp.document.ready.v1 serializer)

**What to build**:

At the end of `process_message()` in `ArticleProcessingConsumer`, after all pipeline blocks complete: if `tenant_id is not None` (i.e., this is a tenant-uploaded document, not public news), publish `nlp.document.ready.v1` via outbox.

```python
if tenant_id is not None:
    await self._outbox.append(
        aggregate_type="nlp_document",
        aggregate_id=str(doc_id),
        event_type="nlp.document.ready",
        topic="nlp.document.ready.v1",
        payload={
            "event_id": str(new_uuid7()),
            "event_type": "nlp.document.ready",
            "schema_version": 1,
            "occurred_at": utc_now().isoformat(),
            "doc_id": str(doc_id),
            "tenant_id": str(tenant_id),
            "chunk_count": chunk_count,
            "word_count": word_count,
        },
    )
```

Also register `nlp.document.ready.v1` in S6's OutboxDispatcher serializers dict.

**Condition**: Only emit for tenant documents (`tenant_id is not None`). Public news enrichment does NOT emit this event (no S4 row to update).

**Acceptance criteria**:
- [ ] `nlp.document.ready.v1` emitted after successful enrichment of tenant document
- [ ] NOT emitted for public news (tenant_id is None)
- [ ] `nlp.document.ready.v1` serializer registered in S6 dispatcher
- [ ] Unit tests: tenant doc → event emitted; public news → no event

#### Validation Gate (Wave F-1)
- [ ] `python -m pytest services/nlp-pipeline/tests/ -m unit -v` passes
- [ ] `python -m pytest services/content-ingestion/tests/ -m unit -v` passes
- [ ] Architecture tests pass (`tests/architecture/ -v`) — ValkeyDedupMixin enforcement
- [ ] `ruff + mypy` on S4 and S6 pass

#### Architecture Compliance
- [ ] R9 — Both new consumers extend `ValkeyDedupMixin, BaseKafkaConsumer`
- [ ] R8 — `nlp.document.ready.v1` published via outbox (not direct Kafka producer call)
- [ ] R22 — `DocumentDeletionConsumer` runs as independent process

#### Regression Guardrails
- **R9 + CONSUMER-DEDUP-001**: Architecture test verifies all `BaseKafkaConsumer` subclasses either have `ValkeyDedupMixin` or are in the explicit allowlist. New consumers MUST inherit the mixin or the architecture test will fail.
- **BP-147**: Serializer for `nlp.document.ready.v1` must be registered in S6's dispatcher before the first enrichment event for a tenant document is processed.

---

## Sub-Plan G — Integration Tests & Contract Coverage

### Wave G-1: Integration Tests + Contract Tests

**Goal**: End-to-end integration coverage for the new tenant isolation and upload paths. Contract tests ensure Avro schema alignment is maintained.
**Depends on**: C-1, E-2, F-1
**Estimated effort**: 75–90 min
**Architecture layer**: integration + contract

#### Tasks

##### T-G-1-01: Avro contract tests for 5 schema changes

**Type**: test
**depends_on**: T-A-1-01 through T-A-1-05
**Target files**:
- `libs/contracts/tests/contract/test_avro_schemas.py` (update for 3 updated schemas + add 2 new)

Tests to add:
```python
# Verify tenant_id field presence and default in updated schemas
def test_content_article_raw_has_tenant_id_field(): ...
def test_content_article_stored_has_tenant_id_field(): ...
def test_nlp_article_enriched_has_tenant_id_field(): ...
# Verify new schemas parse correctly
def test_content_document_deleted_schema_valid(): ...
def test_nlp_document_ready_schema_valid(): ...
# Forward compat: old event (no tenant_id field) still deserializes
def test_content_article_raw_old_event_tenant_id_defaults_to_null(): ...
# R28: canonical models exist and mirror schema fields
def test_content_document_deleted_canonical_model_fields_match_avro(): ...
def test_nlp_document_ready_canonical_model_fields_match_avro(): ...
```

---

##### T-G-1-02: S5 integration tests — migration + tenant dedup isolation

**Type**: test
**depends_on**: T-B-1-01, T-C-1-01
**Target files**:
- `services/content-store/tests/integration/test_tenant_dedup.py` *(NEW)*

Key test scenarios:
- `test_global_dedup_still_works`: same public news hash → duplicate detected (global dedup unchanged)
- `test_per_tenant_dedup_same_content`: tenant A uploads doc X; tenant A uploads same doc → 409
- `test_per_tenant_dedup_different_tenants`: tenant A and B upload same content → both succeed (independent dedup)
- `test_migration_0005_existing_rows_null`: after upgrade, all existing documents have `tenant_id = NULL`

---

##### T-G-1-03: S6 integration tests — chunk filter + deletion consumer

**Type**: test
**depends_on**: T-B-2-01, T-C-1-03, T-F-1-01
**Target files**:
- `services/nlp-pipeline/tests/integration/test_chunk_tenant_filter.py` *(NEW)*

Key scenarios:
- `test_chunk_search_excludes_other_tenant_chunks`: chunks from tenant B not in tenant A's search results
- `test_chunk_search_includes_public_and_private`: public (NULL) + tenant's private chunks both returned
- `test_document_deletion_consumer_removes_chunks`: consume deletion event → chunks/sections/entity_mentions gone
- `test_document_deletion_consumer_idempotent`: second consumption → no error

---

##### T-G-1-04: S4 integration tests — upload + polling + deletion

**Type**: test
**depends_on**: T-E-2-01, T-F-1-02
**Target files**:
- `services/content-ingestion/tests/integration/test_tenant_upload_api.py` *(NEW)*

Key scenarios:
- `test_upload_pdf_returns_202`: POST PDF → 202 + doc_id
- `test_upload_wrong_mime_returns_400`: DOCX → 400
- `test_upload_duplicate_returns_409_with_existing_doc_id`: same content hash → 409
- `test_upload_different_tenants_same_content_ok`: two tenants same file → both 202
- `test_get_document_wrong_tenant_returns_404`: cross-tenant GET → 404
- `test_delete_sets_status_and_publishes_event`: DELETE → status=deleted + outbox event

---

##### T-G-1-05: S8 integration test — tenant-filtered RAG chunk retrieval

**Type**: test
**depends_on**: T-C-1-04
**Target files**:
- `services/rag-chat/tests/integration/test_tenant_chunk_retrieval.py` *(NEW)*

Key scenario:
- `test_rag_retrieval_excludes_other_tenant_private_chunks`: insert private chunk for tenant B; tenant A's chat request does not receive it
- `test_rag_retrieval_includes_public_chunks`: public (NULL tenant_id) chunks returned for all tenants

#### Validation Gate (Wave G-1)
- [ ] `python -m pytest services/content-store/tests/ -m integration -v` passes (requires test infra)
- [ ] `python -m pytest services/nlp-pipeline/tests/ -m integration -v` passes
- [ ] `python -m pytest services/content-ingestion/tests/ -m integration -v` passes
- [ ] `python -m pytest services/rag-chat/tests/ -m integration -v` passes
- [ ] `python -m pytest libs/contracts/tests/ -m contract -v` passes

---

## Risk Assessment

**Critical path**: A-1 → B-1/B-2 (parallel) → C-1 → E-1 → E-2 → F-1 → G-1

**Highest risk waves**:
1. **E-1** (`UploadTenantDocumentUseCase`) — R24 session sequencing + compensating GC + asyncio.to_thread correctness
2. **C-1** (HNSW filter) — `tenant_id IS NULL` vs no filter: a subtle difference. Getting the filter wrong causes a data leak (HR-053).
3. **B-1** (S5 migration) — dropping `unique=True` on `documents.content_hash` must be handled in both migration DDL AND ORM model, otherwise SQLAlchemy re-creates the constraint.

**Rollback strategy**: All schema migrations are reversible via `alembic downgrade -1`. New tables/columns are nullable or additive. The `documents.content_hash` unique constraint change in B-1 is the most delicate rollback — the migration's downgrade path must recreate the original `unique=True` constraint.

**Testing gaps**: Integration tests (G-1) require real Postgres + Kafka infra. If infra is unavailable, unit tests provide 80% coverage. The deletion cascade (F-1-01) is high-risk to test in unit tests — integration test is required to confirm cascade correctness.
