# PRD-0075: Multi-Tenant Content Pipeline Isolation & Tenant Document Ingestion

**Version**: 1.0
**Date**: 2026-05-08
**Status**: Draft
**Owner**: Arnau Rodon
**Depends on**: PRD-0025 (Auth — Zitadel internal JWT), PRD-0001 (Intelligence Pipeline)
**Supersedes**: PRD-0002 §FR-06 (tenant_id on KG tables — replaced by shared-reference-layer model below)

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Users & Personas](#2-users--personas)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Out of Scope](#5-out-of-scope)
6. [Technical Design](#6-technical-design)
7. [Architecture Decisions](#7-architecture-decisions)
8. [Security Design](#8-security-design)
9. [Failure Modes & Recovery](#9-failure-modes--recovery)
10. [Scalability & Performance](#10-scalability--performance)
11. [Test Strategy](#11-test-strategy)
12. [Migration Strategy](#12-migration-strategy)
13. [Observability](#13-observability)
14. [Open Questions](#14-open-questions)
15. [Estimation](#15-estimation)

---

## 1. Problem Statement

### 1.1 Current State

The worldview platform supports multiple tenants at the auth layer (PRD-0025: Zitadel JWT with `tenant_id` claim) and at the portfolio/alert domain (S1, S10: all tables have `tenant_id`, all queries filter by it). However, the content intelligence pipeline — content ingestion (S4), content store (S5), NLP processing (S6), and RAG retrieval (S8) — was built as a shared utility processing public news. It has no tenant awareness:

- `documents` table (S5) has no `tenant_id` — all ingested articles are globally shared.
- `chunks`, `sections`, `chunk_embeddings` tables (S6) have no `tenant_id` — HNSW vector similarity search in RAG-chat returns results from all tenants' content indiscriminately.
- Three core Avro schemas (`content.article.raw.v1`, `content.article.stored.v1`, `nlp.article.enriched.v1`) carry no `tenant_id` field — Kafka consumers have no routing context.
- `entity_mentions.tenant_id` (S6 migration 0010, F-009) is the only completed isolation work.

This creates **two compounding problems**:

**Problem A — Missing isolation infrastructure**: There is no mechanism to distinguish public content from tenant-private content in the pipeline or in RAG retrieval. The moment a private document is introduced, there is no wall preventing its chunks from surfacing in other tenants' RAG responses.

**Problem B — No tenant document ingestion**: Tenants cannot upload their own research reports, proprietary analysis, earnings call transcripts, or internal filings. This is a significant capability gap — financial analysts routinely annotate and reference internal documents alongside public news.

Problem A must be solved before Problem B can be safely deployed. This PRD addresses both.

### 1.2 Relationship to PRD-0002

PRD-0002 (Multi-Tenant SaaS Foundation, Draft) proposed adding `tenant_id` to all KG tables (`canonical_entities`, `relations`, `claims`, `events`). This PRD supersedes that proposal for the KG layer. The architectural decision in §7.1 establishes the KG as a **shared reference layer** — entities and relations are public facts. Tenant isolation is enforced at the `entity_mentions` level (already implemented, migration 0010). PRD-0002's auth section was already superseded by PRD-0025.

### 1.3 Content Ownership Model

Public news (S4 sources: EODHD, NewsAPI, Finnhub, SEC EDGAR): `tenant_id = NULL`. All tenants see all public news. This is intentional — news about Apple Inc. is not owned by any one tenant.

Tenant-uploaded documents: `tenant_id = <owning_tenant_uuid>`. Only the owning tenant sees these in RAG retrieval.

RAG chunk filter: `WHERE (tenant_id IS NULL OR tenant_id = :requesting_tenant_id)`.

This model is called the **Global + Private content model**: public content is shared, private content is isolated, isolation infrastructure is unified.

---

## 2. Users & Personas

### 2.1 Financial Analyst (Primary)
- Works at an investment firm (one Worldview tenant).
- Wants to upload internal research reports, proprietary sector analyses, and earnings call transcripts.
- Expects RAG-chat responses to cite both public news AND their firm's private documents.
- Needs to see which documents have been processed and are "ready" for querying.

### 2.2 Platform Administrator
- Manages the Worldview deployment.
- Needs to audit which tenants have uploaded documents and how many.
- Needs to monitor pipeline processing status across all tenant uploads.

### 2.3 Existing Tenant (No Uploads)
- Uses RAG-chat today for public news intelligence.
- Must see **no behaviour change** after this PRD is deployed — all existing queries return the same results (public chunks have `tenant_id = NULL`, still returned by the updated filter).

---

## 3. Functional Requirements

### Phase 1 — Pipeline Isolation (prerequisite)

| ID | Requirement | Priority |
|----|-------------|----------|
| F-001 | `documents` table gains nullable `tenant_id` UUID column. `NULL` = public news visible to all tenants. | MUST |
| F-002 | `dedup_hashes` table gains nullable `tenant_id`. Per-tenant dedup: a tenant uploading the same document twice receives a 409 referencing the existing `doc_id`. Global dedup (public news) remains `tenant_id = NULL`. | MUST |
| F-003 | `chunks` and `sections` tables gain nullable `tenant_id` UUID column. All existing rows remain `NULL` (public). | MUST |
| F-004 | `content.article.raw.v1`, `content.article.stored.v1`, and `nlp.article.enriched.v1` Avro schemas gain a nullable `tenant_id` string field with `"default": null`. | MUST |
| F-005 | S6 chunk search (HNSW + hybrid) filters results: `WHERE (chunks.tenant_id IS NULL OR chunks.tenant_id = :requesting_tenant_id)`. This is applied as a post-filter after ANN retrieval. | MUST |
| F-006 | S8 `_fetch_chunks()` passes `tenant_id` from the chat request into `ChunkSearchRequest`. When `tenant_id` is `None` (unauthenticated or system calls), only public chunks (`tenant_id IS NULL`) are returned. | MUST |
| F-007 | S5 `ArticleStorageConsumer` and S6 `ArticleProcessingConsumer` propagate `tenant_id` from the Avro event payload to all rows they write. For public news events (`tenant_id = null` in event), rows are written with `tenant_id = NULL`. | MUST |

### Phase 2 — Tenant Document Ingestion

| ID | Requirement | Priority |
|----|-------------|----------|
| F-010 | Tenants can upload PDF (`.pdf`) or plain text (`.txt`) documents up to 50 MB via `POST /api/v1/documents/upload`. | MUST |
| F-011 | Upload is **asynchronous**: endpoint returns HTTP 202 with `doc_id` and `status: "processing"` immediately after accepting the file. Processing continues in the pipeline. | MUST |
| F-012 | Tenants can poll document processing status via `GET /api/v1/documents/{doc_id}` returning the current `status` (`processing` \| `ready` \| `failed`). | MUST |
| F-013 | Tenants can list all their uploaded documents via `GET /api/v1/documents` with optional `status` filter and cursor-based pagination. | MUST |
| F-014 | Tenants can delete an uploaded document via `DELETE /api/v1/documents/{doc_id}`. Deletion is soft (status → `deleted`) immediately; physical cleanup (MinIO objects, chunks, entity_mentions) is handled asynchronously by a background job. | MUST |
| F-015 | Uploaded documents are processed through the **full NLP pipeline** (Level 2): text extraction → sectioning → chunking → embeddings → NER → entity resolution → KG contribution (entity_mentions tagged with `tenant_id`). | MUST |
| F-016 | S4 enforces per-tenant dedup before MinIO write: if `(tenant_id, SHA-256(extracted_text))` already exists, the endpoint returns HTTP 409 with the existing `doc_id`. | MUST |
| F-017 | Per-tenant upload rate limit: 20 uploads per rolling 24-hour window per tenant. Configurable via `TENANT_UPLOAD_DAILY_LIMIT` env var. Enforced via Valkey sliding window (fail-open if Valkey is unavailable). | MUST |
| F-018 | Upload file is stored in MinIO under `tenant-uploads/{tenant_id}/{doc_id}/bronze/{filename}`. Cleaned text is stored under `tenant-uploads/{tenant_id}/{doc_id}/silver/clean.txt`. | MUST |
| F-019 | Documents are **tenant-owned** (not user-owned). Any user within the tenant can see and query all tenant documents. The `uploaded_by_user_id` is stored for audit purposes only. | MUST |
| F-020 | When a tenant document is deleted, S6 consumes the `content.document.deleted.v1` event and removes all associated chunks, sections, and entity_mentions for `(doc_id, tenant_id)`. | MUST |
| F-021 | RAG-chat responses citing a tenant's private document include the document title and source attribution so the analyst knows the citation origin. | MUST |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | Upload API response time (202 acceptance, before processing) | ≤ 5 seconds for files up to 50 MB |
| NFR-02 | Document processing time (upload → `ready` status) | ≤ 5 minutes for typical 50-page PDF |
| NFR-03 | HNSW query latency with tenant filter (post-filter) | ≤ 200 ms at p99 for up to 500k public + 50k private chunks |
| NFR-04 | Zero regression for existing tenants | Existing RAG-chat queries return identical results (public chunks still returned, unchanged) |
| NFR-05 | Forward-compatible Avro schema changes | Adding `tenant_id` field with `"default": null` must not break existing consumers |
| NFR-06 | Per-tenant dedup consistency | Two concurrent uploads of the same document by the same tenant must not produce two rows |
| NFR-07 | Soft-delete atomicity | `DELETE /documents/{doc_id}` must atomically set `status = deleted` before returning 200; no partial state |
| NFR-08 | Upload rate limit accuracy | Rate limit counter must not undercount by more than 1 in case of Valkey unavailability (fail-open) |

---

## 5. Out of Scope

- **Private canonical entities in the KG** — deferred to PRD-0076. Provisional entities are created for unrecognized mentions in tenant documents; promotion to private canonicals is a future workflow.
- **User-level document visibility** — documents are tenant-owned. Per-user document permissions are PRD-0077+.
- **Non-PDF/text formats in v1** — DOCX, Markdown, HTML, URL ingestion are deferred. v1 supports PDF and plain text only.
- **Tenant-to-tenant document sharing** — a tenant cannot share a private document with another tenant.
- **External storage integration** — tenants cannot point to their own S3 bucket or Google Drive. Documents must be uploaded via the API.
- **Document versioning** — uploading a new version of an existing document requires deleting and re-uploading.
- **MinIO object key restructuring for public news** — public news keys are unchanged. Only new tenant-upload keys follow the new prefix convention.
- **KG table tenant_id** (PRD-0002 §FR-06) — explicitly rejected. See §7.1.
- **Market data Avro schemas** — `market.*` schemas remain without `tenant_id` (global reference data).

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Changes |
|---------|---------|
| S4 content-ingestion | New source type `tenant_upload`; new `tenant_document_uploads` table; **4 new use cases** (Upload, Get, List, Delete + UpdateDocumentStatus); 3 new endpoints; **1 new consumer** (`DocumentReadyConsumer` on `nlp.document.ready.v1`) |
| S5 content-store | Migration **0005**: `tenant_id` on `documents` + `dedup_hashes`; dedup logic updated |
| S6 nlp-pipeline | Migration **0019**: `tenant_id` + `document_title` on `chunks`; `tenant_id` on `sections`; chunk search filter updated; new deletion consumer; `nlp.document.ready.v1` outbox emission |
| S7 knowledge-graph | None |
| S8 rag-chat | `ChunkSearchRequest` gains `tenant_id`; `_fetch_chunks()` passes it through |
| S9 api-gateway | 3 new routes proxied to S4; rate limit key updated |
| intelligence-migrations | None |

---

### 6.2 API Changes

#### POST /api/v1/documents/upload
- **Purpose**: Accept a tenant document for async ingestion through the NLP pipeline.
- **Auth**: JWT required; `tenant_id` extracted from token by S9; forwarded as `X-Tenant-ID` header to S4.
- **Request**: `multipart/form-data`

| Field | Type | Required | Validation | Description |
|-------|------|----------|------------|-------------|
| `file` | binary | yes | MIME: `application/pdf` or `text/plain`; ≤ 50 MB | Document file |
| `title` | string | no | ≤ 512 chars; sanitized (no HTML) | Display title; defaults to filename without extension |

- **Response (202)**:

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | string (UUID) | UUIDv7; stable identifier for polling and deletion |
| `status` | string | Always `"processing"` on 202 |
| `title` | string | Resolved display title |
| `filename` | string | Original uploaded filename |

- **Error responses**:
  - `400` — unsupported MIME type or missing file
  - `401` — missing or invalid JWT
  - `409` — duplicate: same content already uploaded by this tenant; body includes `{"existing_doc_id": "..."}`
  - `413` — file exceeds 50 MB limit
  - `422` — file accepted but text extraction failed (corrupt PDF, empty document)
  - `429` — daily upload rate limit exceeded; body includes `{"resets_at": "<ISO-8601>"}`

---

#### GET /api/v1/documents/{doc_id}
- **Purpose**: Poll processing status for a single uploaded document.
- **Auth**: JWT required; verifies `doc_id` belongs to requesting tenant.

- **Response (200)**:

| Field | Type | Description |
|-------|------|-------------|
| `doc_id` | string | UUIDv7 |
| `title` | string | Display title |
| `filename` | string | Original filename |
| `status` | string | `processing` \| `ready` \| `failed` \| `deleted` |
| `word_count` | int \| null | Populated after text extraction; null while processing |
| `chunk_count` | int \| null | Populated after S6 processing |
| `uploaded_at` | string | ISO-8601 UTC |
| `ready_at` | string \| null | ISO-8601 UTC; null until status=ready |
| `error_message` | string \| null | Human-readable error; populated if status=failed |

- **Error responses**: `401`, `403` (tenant mismatch), `404`

---

#### GET /api/v1/documents
- **Purpose**: List all uploaded documents for the requesting tenant.
- **Auth**: JWT required.
- **Query params**:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | (all) | Filter: `processing` \| `ready` \| `failed` |
| `limit` | int | 20 | Max 100 |
| `cursor` | string | (start) | Opaque pagination cursor |

- **Response (200)**:

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | Array of document summaries (same shape as GET by ID) |
| `next_cursor` | string \| null | Null when no more pages |
| `total` | int | Total count across all pages for this tenant |

- **Error responses**: `400` (invalid status filter), `401`

---

#### DELETE /api/v1/documents/{doc_id}
- **Purpose**: Soft-delete a tenant document; physical cleanup is async.
- **Auth**: JWT required; verifies `doc_id` belongs to requesting tenant.
- **Response**: `200 OK` with `{"doc_id": "<uuid>", "status": "deleted"}` (see BP-064: FastAPI ≤0.111 raises a validation error on `status_code=204` with a non-None response body; use 200 with a minimal response body to avoid this pattern)
- **Error responses**: `401`, `403` (tenant mismatch), `404`, `409` (deletion already in progress)

---

#### S8 — ChunkSearchRequest port update (internal, not a user-facing endpoint)

```python
@dataclass
class ChunkSearchRequest:
    query_embedding: list[float] | None
    query_text: str | None
    search_type: Literal["ann", "hybrid", "lexical"]
    top_k: int
    date_from: datetime | None = None
    date_to: datetime | None = None
    tenant_id: str | None = None  # NEW — None = public chunks only
```

---

### 6.3 Event Changes

#### content.article.raw.v1 — updated
New field added to existing schema (forward-compatible):
```json
{
  "name": "tenant_id",
  "type": ["null", "string"],
  "default": null,
  "doc": "Owning tenant UUID string. null = public news visible to all tenants. Set only for tenant-uploaded documents."
}
```
- **Producer**: S4 (existing + new upload path)
- **Consumer**: S5

#### content.article.stored.v1 — updated
Same field addition as above. Pass-through from S4 event.
- **Producer**: S5
- **Consumer**: S6

#### nlp.article.enriched.v1 — updated
Same field addition as above. Pass-through from S5 event.
- **Producer**: S6
- **Consumer**: S7 (knowledge-graph consumers)

#### content.document.deleted.v1 — NEW
- **Topic**: `content.document.deleted.v1`
- **Partition key**: `tenant_id`
- **Retention**: 7 days
- **Cleanup policy**: delete
- **Producers**: S4
- **Consumers**: S6 (deletes chunks, sections, entity_mentions for the document)

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| `event_id` | string | — | no | UUIDv7 |
| `event_type` | string | `"content.document.deleted"` | no | |
| `schema_version` | int | 1 | no | |
| `occurred_at` | string | — | no | ISO-8601 UTC |
| `doc_id` | string | — | no | UUIDv7 of deleted document |
| `tenant_id` | string | — | no | Non-nullable — all deletions are tenant-scoped |

#### nlp.document.ready.v1 — NEW (OQ-001 resolution)
- **Topic**: `nlp.document.ready.v1`
- **Partition key**: `tenant_id`
- **Retention**: 7 days
- **Cleanup policy**: delete
- **Producers**: S6 (via nlp_db outbox, only when `tenant_id IS NOT NULL`)
- **Consumers**: S4 (DocumentReadyConsumer, consumer group `s4-document-ready`)

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| `event_id` | string | — | no | UUIDv7 |
| `event_type` | string | `"nlp.document.ready"` | no | |
| `schema_version` | int | 1 | no | |
| `occurred_at` | string | — | no | ISO-8601 UTC |
| `doc_id` | string | — | no | UUIDv7 of processed document |
| `tenant_id` | string | — | no | Non-nullable — only emitted for tenant-uploaded documents |
| `chunk_count` | int | — | no | Total chunks produced for this document |
| `word_count` | int | — | no | Total word count of the processed document |

---

**Note on source_type Avro enum**: The `source_type` field in `content.article.raw.v1` must accept the new `tenant_upload` value. If `source_type` is currently an Avro `enum` type, the implementation plan must: (a) verify the Avro type, (b) if enum, add `"tenant_upload"` symbol to the enum definition and set a `"default"` value on the field so old consumers encountering the new symbol fall back gracefully per the Avro specification. If `source_type` is already a `string` type, no schema change is needed beyond documenting the new value.

---

### 6.4 Database Changes

#### S5 content-store — Migration 0005

> **Note**: Current Alembic head for content-store is `0004_rename_dedup_hashes_constraint.py`. This migration must be numbered **0005**.

```sql
-- documents: tag private uploads with owning tenant; NULL = global public news
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

CREATE INDEX IF NOT EXISTS idx_documents_tenant_id
    ON documents(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- dedup_hashes: was globally unique on (hash_type, hash_value).
-- Split into two partial unique constraints:
--   - global dedup (NULL tenant) unchanged in semantics
--   - per-tenant dedup (non-NULL tenant) scoped to (tenant_id, hash_type, hash_value)
ALTER TABLE dedup_hashes
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

-- Drop old unique constraint (name may vary; implementation must check against
-- the constraint name introduced in migration 0004_rename_dedup_hashes_constraint.py)
DROP INDEX IF EXISTS uq_dedup_hashes;

CREATE UNIQUE INDEX IF NOT EXISTS uq_dedup_hashes_global
    ON dedup_hashes(hash_type, hash_value)
    WHERE tenant_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_dedup_hashes_tenant
    ON dedup_hashes(tenant_id, hash_type, hash_value)
    WHERE tenant_id IS NOT NULL;
```

**Current Alembic head**: 0004. New head: 0005.
**Backfill**: All existing rows keep `tenant_id = NULL` — correct. No server_default needed (nullable column).
**Downgrade**: Remove the new columns and recreate original unique index.
**Note on migration 0004**: Migration 0004 renamed the dedup_hashes unique constraint. The `DROP INDEX IF EXISTS uq_dedup_hashes` in this migration must match the constraint name as it exists after 0004. The implementation must `grep` the 0004 migration for the final constraint name before writing the DROP statement.

---

#### S6 nlp-pipeline — Migration 0019

> **Note**: Current Alembic head for nlp-pipeline is `0018_add_entity_mentions_jsonb_to_chunks.py`. This migration must be numbered **0019**.

```sql
-- sections: propagate tenant ownership from document
ALTER TABLE sections
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

CREATE INDEX IF NOT EXISTS idx_sections_tenant_id
    ON sections(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- chunks: the primary table for HNSW tenant filtering and citation metadata
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS tenant_id UUID;

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_id
    ON chunks(tenant_id)
    WHERE tenant_id IS NOT NULL;

-- document_title: denormalized for RAG citation (OQ-002 resolution).
-- NULL for public news chunks; populated from content.article.stored.v1 title field
-- for tenant-uploaded document chunks by ArticleProcessingConsumer.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS document_title VARCHAR(512);

-- chunk_embeddings: no direct tenant_id column needed.
-- HNSW filtering is applied via JOIN on chunks.tenant_id.
-- The existing HNSW indexes on chunk_embeddings.embedding are unchanged.
```

**Current Alembic head**: 0018. New head: 0019.
**Backfill**: All existing rows keep `tenant_id = NULL` and `document_title = NULL` (public news). Correct — existing queries still work.
**Domain entity**: The `Chunk` domain entity in S6 must gain a `document_title: str | None = None` field.

---

#### S4 content-ingestion — New table (Migration 0001 for content_ingestion_db or next available)

> **Note**: The `tenant_document_uploads` table lives in S4's own database (`content_ingestion_db`), not in `content_store_db`. Check the current Alembic head in `services/content-ingestion/alembic/versions/` before numbering this migration.

```sql
CREATE TABLE tenant_document_uploads (
    id              UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL,
    uploaded_by_user_id UUID NOT NULL,
    filename        VARCHAR(512) NOT NULL,
    title           VARCHAR(512) NOT NULL,
    content_type    VARCHAR(128) NOT NULL,   -- 'application/pdf' | 'text/plain'
    content_hash    VARCHAR(64) NOT NULL,    -- SHA-256 of extracted text (hex)
    byte_size       BIGINT NOT NULL,
    word_count      INTEGER,                 -- NULL until extraction complete
    chunk_count     INTEGER,                 -- NULL until S6 processing complete
    status          VARCHAR(32) NOT NULL DEFAULT 'processing',
    CONSTRAINT chk_tenant_doc_upload_status
        CHECK (status IN ('processing', 'ready', 'failed', 'deleted')),
    minio_bronze_key VARCHAR(1024) NOT NULL,
    minio_silver_key VARCHAR(1024),          -- NULL until S5 processing complete
    error_message   TEXT,
    uploaded_at     TIMESTAMPTZ NOT NULL,
    ready_at        TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_tenant_doc_uploads_tenant_status
    ON tenant_document_uploads(tenant_id, status);
CREATE INDEX idx_tenant_doc_uploads_tenant_hash
    ON tenant_document_uploads(tenant_id, content_hash);
CREATE INDEX idx_tenant_doc_uploads_uploaded_at
    ON tenant_document_uploads(tenant_id, uploaded_at DESC);
```

**Estimated rows**: ≤ 10k per tenant at thesis scale. No partitioning needed.
**Constraints**: `status` values enforced via CHECK constraint (inline in DDL above).
**UUIDv7 PK**: `id` is always set by the application using `common.ids.new_uuid7()`. The DDL intentionally has no `gen_random_uuid()` default — enforced by the S4 `.claude-context.md` pitfall note.

---

### 6.5 Domain Model Changes

#### S4 — SourceType enum

Add `tenant_upload` to the existing `SourceType` enum used throughout S4, S5, S6.

---

#### S4 — New entity: TenantDocumentUpload

```
TenantDocumentUpload (frozen dataclass)

Attributes:
  id                   : UUID        # UUIDv7; PK
  tenant_id            : UUID        # owning tenant; non-nullable
  uploaded_by_user_id  : UUID        # audit trail; non-nullable
  filename             : str         # original filename; 1-512 chars
  title                : str         # display title; 1-512 chars
  content_type         : str         # "application/pdf" | "text/plain"
  content_hash         : str         # SHA-256 hex of extracted text; 64 chars
  byte_size            : int         # raw file bytes; > 0
  word_count           : int | None  # None until text extraction complete
  chunk_count          : int | None  # None until S6 processing complete
  status               : UploadStatus
  minio_bronze_key     : str         # tenant-uploads/{tenant_id}/{doc_id}/bronze/{filename}
  minio_silver_key     : str | None  # tenant-uploads/{tenant_id}/{doc_id}/silver/clean.txt
  error_message        : str | None
  uploaded_at          : datetime    # UTC-aware
  ready_at             : datetime | None
  deleted_at           : datetime | None

Invariants:
  - byte_size > 0
  - content_hash is a 64-char hex string
  - uploaded_at is UTC-aware (tzinfo is not None)
  - ready_at is not None iff status == UploadStatus.READY
  - deleted_at is not None iff status == UploadStatus.DELETED

Factory:
  TenantDocumentUpload.create(
    tenant_id, uploaded_by_user_id, filename, title,
    content_type, content_hash, byte_size, minio_bronze_key
  ) -> TenantDocumentUpload
  # Sets id=new_uuid7(), status=PROCESSING, uploaded_at=utc_now()
```

---

#### S4 — UploadStatus enum

```
UploadStatus:
  PROCESSING  # accepted; pipeline has not yet produced chunks
  READY       # S6 processing complete; document is queryable in RAG
  FAILED      # unrecoverable processing error
  DELETED     # soft-deleted; excluded from queries and RAG retrieval
```

---

#### S4 — New use case: UploadTenantDocumentUseCase

**Input**:
```
file_bytes     : bytes
filename       : str
content_type   : str
tenant_id      : UUID
user_id        : UUID
title          : str | None  (None → use filename stem)
```

**Output**:
```
UploadResult:
  doc_id  : UUID
  status  : str   # always "processing"
  title   : str
  filename: str
```

**Steps**:
1. Validate `content_type` ∈ `{"application/pdf", "text/plain"}`. Raise `UnsupportedFileTypeError` otherwise.
2. Validate `len(file_bytes) <= 50_000_000`. Raise `FileTooLargeError` otherwise.
3. Extract text (MUST run in `asyncio.to_thread()` — blocking sync I/O on the async event loop freezes the entire service; see HR-019 and §8.2):
   - PDF: `extracted_text = await asyncio.to_thread(pdfminer_extract, file_bytes)` where `pdfminer_extract` is a thin sync wrapper around `pdfminer.six`. Raise `TextExtractionError` if result is empty.
   - Plain text: `decoded = await asyncio.to_thread(file_bytes.decode, "utf-8")`. Raise `TextExtractionError` if empty after strip.
4. Compute `content_hash = hashlib.sha256(extracted_text.encode()).hexdigest()`.
5. Check per-tenant dedup: `DedupHashRepositoryPort.check_exists(tenant_id, "sha256", content_hash)`. If exists, raise `DuplicateDocumentError(existing_doc_id=...)`.
6. Generate `doc_id = new_uuid7()`. Build MinIO key: `tenant-uploads/{tenant_id}/{doc_id}/bronze/{filename}`.
7. Write bronze object to MinIO (S3 PUT). Track the key as `pending_bronze_key`. Raise `StorageError` on failure — do NOT proceed.
8. Write `TenantDocumentUpload` row (status=PROCESSING) and `dedup_hashes` row within a single UoW transaction.
   - On DB commit failure: catch exception, attempt `bronze_storage.delete_object(pending_bronze_key)` (compensating GC, best-effort); log WARNING if delete fails, DO NOT mask original exception; re-raise original exception. This mirrors the MinIO compensating GC pattern used in S4 `FetchAndWriteUseCase` and S5 `ArticleConsumer`.
9. Append outbox event: topic=`content.article.raw.v1`, `tenant_id` set, `source_type=tenant_upload`.
10. Return `UploadResult`.

**R24 compliance (session not held across external I/O)**:
The use case must NOT hold an open DB session during steps 3 (text extraction) or 7 (MinIO write). The correct call sequence is:
1. Enter UoW ONLY for step 5 (dedup check) — read-only query; exit UoW immediately after.
2. Perform step 7 (MinIO PUT) outside any UoW context.
3. Enter write UoW for step 8 (DB row + outbox INSERT) — commit — exit.
This matches the R24 pattern: "read → release → I/O → acquire → write" described in STANDARDS.md §16.

**Errors raised** (domain errors, mapped to HTTP in router):
- `UnsupportedFileTypeError` → 400
- `FileTooLargeError` → 413
- `TextExtractionError` → 422
- `DuplicateDocumentError` → 409
- `StorageError` → 503

---

#### S4 — New port interfaces (R25 — application/ports/)

All new use cases depend on port abstractions, never infrastructure directly:

```
TenantDocumentUploadRepositoryPort (Protocol):
  create(doc: TenantDocumentUpload) -> None
  get(doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None
    # Returns None for wrong tenant (no information leak)
  get_for_update(doc_id: UUID, tenant_id: UUID) -> TenantDocumentUpload | None
    # SELECT ... FOR UPDATE; used by DeleteTenantDocumentUseCase to prevent race
  list_by_tenant(tenant_id: UUID, status: UploadStatus | None,
                 limit: int, cursor: tuple[datetime, UUID] | None) -> tuple[list[TenantDocumentUpload], int]
  set_deleted(doc_id: UUID, tenant_id: UUID) -> None
  set_ready(doc_id: UUID, tenant_id: UUID, chunk_count: int, word_count: int) -> None

TenantDedupHashRepositoryPort (Protocol):  # per-tenant scoped; always requires tenant_id
  check_exists(hash_type: str, hash_value: str, tenant_id: UUID) -> UUID | None
    # Returns existing doc_id if found, None otherwise
  insert(doc_id: UUID, hash_type: str, hash_value: str, tenant_id: UUID) -> None

UploadRateLimitPort (Protocol):
  check_and_increment(tenant_id: UUID, window_seconds: int, limit: int) -> bool
    # Returns True if upload is allowed; False if rate limit exceeded.
    # Fail-open: returns True if Valkey is unavailable (bypass logged via counter).
  get_reset_at(tenant_id: UUID) -> datetime | None
    # Returns approximate reset time for 429 response body; None if key not found
```

The `UnitOfWork` for S4's new upload path must expose `tenant_uploads` and `dedup_hashes` repository properties. The `ReadOnlyUnitOfWork` must expose `tenant_uploads` (read-only).

---

#### S4 — New use case: GetTenantDocumentUseCase (read-only)

**Input**: `doc_id: UUID, tenant_id: UUID`
**Output**: `TenantDocumentUpload | None`
**Logic**: Fetch by `(doc_id, tenant_id)`. Return `None` if not found or tenant mismatch (router returns 404 for both — no information leak).
**UoW type**: `ReadOnlyUnitOfWork`.

---

#### S4 — New use case: ListTenantDocumentsUseCase (read-only)

**Input**: `tenant_id: UUID, status: UploadStatus | None, limit: int, cursor: str | None`
**Output**: `ListResult(items: list[TenantDocumentUpload], next_cursor: str | None, total: int)`
**UoW type**: `ReadOnlyUnitOfWork`.
**Cursor**: opaque base64-encoded `(uploaded_at, doc_id)` pair for keyset pagination.

---

#### S4 — New use case: DeleteTenantDocumentUseCase

**Input**: `doc_id: UUID, tenant_id: UUID`
**Steps**:
1. Fetch document by `(doc_id, tenant_id)` with `SELECT ... FOR UPDATE`.
2. Raise `NotFoundError` if not found or tenant mismatch (404).
3. Raise `AlreadyDeletedError` if `status == DELETED` (409).
4. Set `status = DELETED`, `deleted_at = utc_now()` within UoW transaction.
5. Append outbox event: topic=`content.document.deleted.v1`, `doc_id`, `tenant_id`.

---

#### S6 — New consumer: DocumentDeletionConsumer

**Consumer group**: `s6-document-deletion`
**Topic**: `content.document.deleted.v1`
**Extends**: `ValkeyDedupMixin, BaseKafkaConsumer` (R9 + R20 + CONSUMER-DEDUP-001 enforcement)
**Dedup prefix**: `nlp:dedup:document_deletion`
**Idempotency**: Inherits ValkeyDedupMixin for at-least-once safety. Natural idempotency also applies via `DELETE WHERE doc_id = :doc_id AND tenant_id = :tid` — re-delivery is a no-op if rows already deleted. Both layers are required: Valkey dedup prevents unnecessary DB round-trips; SQL DELETE idempotency provides the safety net when Valkey is unavailable.

> **Note**: The `is_duplicate` / `mark_processed` contract MUST be satisfied via `ValkeyDedupMixin`. A hand-rolled stub (`return False`) is forbidden — the architecture test `CONSUMER-DEDUP-001` will fail. The consumer must be added to `tests/architecture/_consumer_dedup_allowlist.yaml` ONLY if there is a justified reason to use natural-key idempotency instead (there is not here). Default: use the mixin.

**Steps**:
1. Parse event; extract `doc_id` and `tenant_id`.
2. Within a single UoW transaction:
   - `DELETE FROM entity_mentions WHERE doc_id = :doc_id AND tenant_id = :tid`
   - `DELETE FROM chunks WHERE doc_id = :doc_id AND tenant_id = :tid` (cascades to chunk_embeddings via FK)
   - `DELETE FROM sections WHERE doc_id = :doc_id AND tenant_id = :tid`

---

#### S8 — ChunkSearchRequest update

Add `tenant_id: str | None = None` to the existing frozen dataclass. Default `None` is backward-compatible — callers that don't set it continue to receive public chunks only (unchanged behaviour).

---

### 6.6 Frontend Changes

None for this PRD. Document management UI is deferred to PRD-0076 (Terminal UI v3 follow-on). The API endpoints are available to external API clients and the existing chat interface (which automatically benefits from private chunk retrieval once Phase 1 is deployed).

---

### 6.7 Data Flows

#### 6.7.1 Upload Flow (end-to-end)

```
User
  → POST /api/v1/documents/upload (multipart, JWT)
  → S9: validate JWT, extract tenant_id + user_id, forward to S4
  → S4 UploadTenantDocumentUseCase:
      1. Validate file type + size
      2. Extract text (pdfminer.six / UTF-8 decode)
      3. Compute SHA-256(text) = content_hash
      4. Per-tenant dedup check → 409 if duplicate
      5. PUT MinIO bronze key
      6. INSERT tenant_document_uploads (status=PROCESSING)
         INSERT dedup_hashes (tenant_id=:tid, hash_value=content_hash)
         INSERT outbox_events (topic=content.article.raw.v1, tenant_id set)
         [all in one UoW transaction]
      7. Return 202 {doc_id, status:"processing"}

  → S4 OutboxDispatcher publishes content.article.raw.v1 (tenant_id = :tid)

  → S5 ArticleStorageConsumer:
      1. Per-tenant dedup check on content_hash
      2. Clean and normalize text
      3. PUT MinIO silver key: tenant-uploads/{tid}/{doc_id}/silver/clean.txt
      4. INSERT documents (tenant_id = :tid, source_type = tenant_upload)
      5. Publish content.article.stored.v1 (tenant_id propagated)

  → S6 ArticleProcessingConsumer:
      1. Section document
      2. Chunk sections → INSERT sections, chunks (tenant_id = :tid, document_title = :title)
      3. Compute BGE-1024 embeddings → INSERT chunk_embeddings
      4. GLiNER NER → entity_mentions (tenant_id = :tid)
      5. Entity resolution (global KG lookup only; provisional if unknown)
      6. Routing decision → LLM extraction if tier ≥ medium
      7. Publish nlp.article.enriched.v1 (tenant_id propagated)
      8. If tenant_id is NOT NULL: publish nlp.document.ready.v1 (doc_id, tenant_id, chunk_count)
         via nlp_db outbox (same transaction as step 7 commit — R8 compliance)

  → S4 DocumentReadyConsumer (consumer group s4-document-ready):
      1. Parse nlp.document.ready.v1 event
      2. UpdateDocumentStatusUseCase: SET status=READY, chunk_count=:chunk_count, ready_at=utc_now()
         WHERE id = :doc_id AND tenant_id = :tenant_id AND status = 'processing'
         (status guard prevents overwriting DELETED status on race conditions)
```

#### 6.7.2 Poll Flow

```
User
  → GET /api/v1/documents/{doc_id} (JWT)
  → S9 → S4 GetTenantDocumentUseCase
  → SELECT from tenant_document_uploads WHERE id = :doc_id AND tenant_id = :tid
  → Return {status, word_count, chunk_count, ...}
```

Recommended polling interval: 10 seconds. Typical latency for a 20-page PDF: 60–120 seconds.

#### 6.7.3 RAG Query Flow (updated)

```
User → POST /api/v1/chat (S9) → S8 pipeline
  Step 5A _fetch_chunks():
    ChunkSearchRequest(
      query_embedding=...,
      query_text=...,
      search_type="hybrid",
      top_k=20,
      tenant_id=request.tenant_id   ← NEW
    )
  → S6 ChunkSearchUseCase SQL:
      SELECT ce.chunk_id, ce.embedding <=> :q AS distance,
             c.text, c.doc_id, c.tenant_id, c.document_title   ← NEW
      FROM chunk_embeddings ce
      JOIN chunks c ON c.chunk_id = ce.chunk_id
      WHERE (c.tenant_id IS NULL OR c.tenant_id = :tenant_id)
      ORDER BY ce.embedding <=> :q
      LIMIT :top_k
  → Public news chunks (tenant_id IS NULL) + tenant's private chunks returned
  → Fusion, reranking, LLM generation treat all chunks equally
  → Citation: private chunks labeled with c.document_title (no cross-service lookup needed; OQ-002 resolved)
```

#### 6.7.4 Deletion Flow

```
User → DELETE /api/v1/documents/{doc_id} (JWT)
  → S4 DeleteTenantDocumentUseCase:
      SELECT FOR UPDATE → SET status=DELETED, deleted_at=utc_now()
      INSERT outbox_events (topic=content.document.deleted.v1)
  → 200 response {doc_id, status: "deleted"}

  [Async] S4 OutboxDispatcher publishes content.document.deleted.v1

  [Async] S6 DocumentDeletionConsumer:
      DELETE entity_mentions WHERE doc_id=:id AND tenant_id=:tid
      DELETE chunks WHERE doc_id=:id AND tenant_id=:tid
      DELETE sections WHERE doc_id=:id AND tenant_id=:tid
      (chunk_embeddings cascade via FK on chunk_id)
```

---

## 7. Architecture Decisions

### ADR-0075-01: Knowledge Graph as Shared Reference Layer

**Decision**: `canonical_entities`, `relations`, `relation_evidence_raw`, `claims`, `events` in `intelligence_db` do NOT receive `tenant_id` columns.

**Rationale**: Entities and relations represent public facts — "Apple Inc.", "Elon Musk is CEO of Tesla". Duplicating these per tenant wastes storage and makes cross-tenant entity deduplication impossible. A tenant's proprietary connection to an entity is expressed as an `entity_mention` (already tenant_id-scoped since migration 0010) pointing to the global canonical entity. This provides full RAG context with zero KG duplication.

**Rejected alternative**: Per-tenant KG (PRD-0002 §FR-06). Rejected due to HNSW scaling impossibility at 100k tenants (see §10.2) and storage duplication.

**Private canonical entities**: Deferred. When a tenant's uploaded document mentions an unknown entity (e.g., an internal project name), the NLP pipeline creates a provisional entity and records an entity_mention with the tenant's `tenant_id`. The provisional entity is visible in the KG graph for that tenant's egocentric traversals (since they start from their entity_mentions). Explicit promotion of provisionals to private canonicals is PRD-0076.

### ADR-0075-02: Global + Private Content Model

**Decision**: Public news articles have `tenant_id = NULL` and are visible to all tenants. Tenant-uploaded documents have `tenant_id = <uuid>` and are visible only to the owning tenant. The RAG chunk filter is `WHERE (tenant_id IS NULL OR tenant_id = :tid)`.

**Rationale**: News is public information — NVDA's earnings report is the same fact regardless of which tenant reads it. Per-tenant news copies would make deduplication impossible. Private content (tenant uploads) is isolated by design. NULL as the "public" sentinel is idiomatic in this codebase (see entity_mentions migration 0010) and allows zero-migration backward compatibility.

### ADR-0075-03: HNSW Post-Filter Strategy

**Decision**: Tenant isolation in HNSW chunk search is applied as a post-filter (after ANN retrieval, before returning results), not as a pre-filter on the index.

**Rationale**: pgvector's HNSW does not support predicate pushdown during index traversal. Pre-filtering would require per-tenant HNSW indexes (infeasible at scale). Post-filtering over a shared index is acceptable because: (a) at thesis scale, private chunks are a tiny fraction of total chunks, so top-K recall degradation is < 1%; (b) for production scale, the correct solution is an external vector DB (Qdrant namespaces) — deferred.

### ADR-0075-04: Async Upload with Polling

**Decision**: `POST /documents/upload` returns HTTP 202 immediately after accepting the file. Status is polled via `GET /documents/{doc_id}`.

**Rationale**: PDF processing (pdfminer.six extraction + chunking + embeddings + NER) takes 30–120 seconds for a 50-page document. Holding an HTTP connection open for this duration is not viable. The 202 + polling pattern is consistent with other async operations in the platform (e.g., intelligence task queue).

### ADR-0075-05: Per-Tenant Deduplication

**Decision**: Deduplication for tenant-uploaded documents is scoped to `(tenant_id, content_hash)`. Two different tenants uploading the same PDF produce independent `doc_id` values and independent chunks.

**Rationale**: Documents are tenant-owned. If tenant A deletes a document, tenant B's copy must not be affected. Shared `doc_id` would require reference counting on deletion — complex and error-prone. The storage overhead is acceptable at thesis scale.

---

## 8. Security Design

### 8.1 Tenant Isolation Enforcement

Every database query that touches user-attributable data in the pipeline MUST include a `tenant_id` filter. The RAG chunk filter `WHERE (tenant_id IS NULL OR tenant_id = :tid)` is the critical path — this must be present in every chunk retrieval query. Any code path that retrieves chunks without this filter is a **data leak** (HR-053 in HIGH_RISK_PATTERNS.md).

Document access endpoints (`GET /documents/{doc_id}`, `DELETE /documents/{doc_id}`) verify `tenant_id` at the use-case layer — not only at the API layer. If the use case receives a `doc_id` that belongs to a different tenant, it returns `None` (not an authorization error message, to avoid information leakage about the existence of documents).

### 8.2 File Upload Validation

- MIME type validated against an allowlist (`{"application/pdf", "text/plain"}`). The HTTP `Content-Type` header is NOT trusted alone — the actual file bytes are inspected using `python-magic` (libmagic bindings) to confirm the file signature matches the declared type.
- File size validated before reading entire file into memory (`Content-Length` header checked; body streamed with max-read enforcement).
- PDF text extraction is sandboxed: `pdfminer.six` runs without network access; no JavaScript execution.
- Extracted text length limit: 500,000 characters (prevents degenerate PDFs with enormous text content).
- No execution of uploaded file content — extracted text is treated as untrusted plain text.

### 8.3 Input Validation

All upload endpoint inputs pass through Pydantic schemas at the S4 API boundary. `title` field is sanitized with `bleach.clean()` to strip any HTML before storage.

### 8.4 Rate Limiting

Upload rate limit key in Valkey: `upload:v1:tenant:{tenant_id}`. Sliding window of 20 uploads per 24 hours. The key is intentionally NOT scoped to `user_id` — the limit is per tenant, not per user within a tenant.

General API rate limit key updated (GAP-6 from investigation report): `rl:v1:user:{tenant_id}:{user_id}` (was `rl:v1:user:{user_id}`). This ensures rate limits are scoped per (tenant, user) combination.

### 8.5 MinIO Access Control

Tenant-uploaded objects are stored under `tenant-uploads/{tenant_id}/...`. No pre-signed URL generation is implemented in v1 — all file access goes through the API which enforces tenant_id checks. Direct MinIO access must remain restricted to internal services only (enforced by Docker network isolation and MinIO bucket policies).

### 8.6 Secrets and Logging

No file content or extracted text is logged. Log statements include only `doc_id`, `tenant_id`, `word_count`, and `status` transitions. Filenames and titles are logged at DEBUG level only.

---

## 9. Failure Modes & Recovery

| Failure | System State | Recovery Strategy |
|---------|-------------|-------------------|
| MinIO write fails during upload (step 7 of use case) | Text extracted, content_hash computed, but object not stored; DB row NOT yet written (step 7 precedes step 8) | Return 503 to client. Client can retry the full upload. Idempotent: dedup check prevents duplicate row on retry. |
| S4 crash after MinIO write but before outbox INSERT | Orphaned MinIO object; no DB row | Background orphan-cleanup scheduled job (runs daily) scans MinIO keys without matching `tenant_document_uploads` rows and deletes them. Client receives 503 and retries. |
| S5 crash mid-processing | `content.article.stored.v1` not published; document stuck in PROCESSING | S4 outbox lease expires → OutboxDispatcher re-emits `content.article.raw.v1`. S5 reprocesses idempotently (upsert on `content_hash`). |
| S6 NLP pipeline unavailable (Ollama/GLiNER down) | Chunks not created; document status stays PROCESSING | S6 consumer retries via Kafka offset commit strategy (offset not committed until processing complete). Auto-recovers when pipeline is healthy. Circuit breaker (rag-chat) does not apply here — S6 is a consumer, not a retrieval source. |
| `content.document.deleted.v1` consumed out of order (delete before processing completes) | S6 deletes entity_mentions/chunks; then `ArticleProcessingConsumer` tries to write for same doc_id | `ArticleProcessingConsumer` checks `documents.status != 'deleted'` before writing. If deleted, skips all writes and commits offset. |
| Valkey unavailable during upload rate limit check | Cannot enforce daily upload limit | Fail-open: upload is permitted. Log warning with counter `tenant_upload_ratelimit_bypass_total`. Valkey key is reconciled on next upload attempt. |
| PDF text extraction produces only whitespace | Empty or near-empty `content_hash` | Return 422: "Could not extract meaningful text from this file." MinIO bronze object is written before extraction (for debugging); a cleanup job removes orphaned bronze objects after 7 days if no corresponding DB row. |
| DELETE called while S6 processing in-flight | Race: S6 writes chunks AFTER soft-delete is set | `ArticleProcessingConsumer` checks document status before writing chunks. If status=DELETED, it skips writes and commits offset. A background cleanup job handles any chunks written before the check. |
| Dedup check race (two concurrent uploads of same content) | Both pass `check_exists` before either inserts | Unique partial index on `dedup_hashes` prevents double-insert. Second INSERT raises `IntegrityError` → mapped to `DuplicateDocumentError` → 409. |

---

## 10. Scalability & Performance

### 10.1 Current Scale Targets

- Tenants: ≤ 100 (thesis deployment)
- Uploaded documents per tenant: ≤ 1,000
- Public news chunks: ~500k (existing)
- Private chunks per tenant: ~50k (based on 1,000 docs × 50 chunks/doc average)
- Total chunks in HNSW at target scale: ~5.5M

### 10.2 HNSW Post-Filter Recall

At thesis scale: private chunks ≈ 50k / 5.5M total ≈ 0.9% of corpus. For a top-K=20 ANN search:
- Expected hits from private corpus in top-K if no filtering: ~0.18 (effectively zero false negatives).
- Post-filtering is safe. Recall degradation from private content is negligible.

At 100k tenant scale with 1k private docs/tenant: total private chunks ≈ 5B. HNSW post-filter is no longer viable — migration to Qdrant namespaces required. This is a future infrastructure decision (PRD-0076+).

### 10.3 Upload Processing Throughput

The NLP pipeline (S6) is the bottleneck. A single 50-page PDF produces approximately:
- 200 chunks (average 250 words/chunk)
- 200 BGE-1024 embedding calls (batched, ~5 seconds total via DeepInfra)
- ~40 entity mention candidates (GLiNER, ~2 seconds local CPU)
- 1 routing decision + optional LLM extraction (~10 seconds if deep tier)

Total estimated processing time: 60–120 seconds per document. With concurrent document uploads by different tenants, the S6 consumer processes sequentially per partition. If throughput becomes a bottleneck, S6 partition count can be increased (operational change, no code change).

### 10.4 Dedup Index Performance

Two partial unique indexes on `dedup_hashes` (one for NULL tenant, one for non-NULL). Writes hit one index only. At 1M documents total, both indexes remain fast (B-tree on UUID + hash string). No partitioning needed.

---

## 11. Test Strategy

### Unit Tests

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_upload_use_case_validates_mime_type` | `UnsupportedFileTypeError` raised for non-PDF/text MIME | HIGH |
| `test_upload_use_case_validates_file_size` | `FileTooLargeError` raised for > 50 MB | HIGH |
| `test_upload_use_case_pdf_extraction_empty` | `TextExtractionError` raised when pdfminer returns empty string | HIGH |
| `test_upload_use_case_dedup_returns_409` | `DuplicateDocumentError` raised when content_hash + tenant_id exists | HIGH |
| `test_upload_use_case_minio_failure_does_not_write_db` | StorageError prevents DB insert (step order enforced) | HIGH |
| `test_upload_use_case_pdf_extraction_in_thread` | pdfminer.six called via `asyncio.to_thread`, not directly on event loop | HIGH |
| `test_upload_use_case_happy_path_returns_doc_id` | Returns UploadResult with UUIDv7 doc_id, status=processing | HIGH |
| `test_tenant_document_upload_entity_invariants` | `byte_size > 0`, `content_hash` is 64-char hex, `uploaded_at` is UTC-aware | HIGH |
| `test_tenant_document_upload_factory_sets_processing_status` | `TenantDocumentUpload.create()` always produces status=PROCESSING | MEDIUM |
| `test_delete_use_case_sets_deleted_status` | Status → DELETED, deleted_at set | HIGH |
| `test_delete_use_case_tenant_mismatch_returns_none` | Not-found returned for wrong tenant (no information leak) | HIGH |
| `test_delete_use_case_already_deleted_raises_conflict` | `AlreadyDeletedError` if status is already DELETED | MEDIUM |
| `test_chunk_search_request_defaults_tenant_id_none` | `ChunkSearchRequest` backward-compatible default `tenant_id=None` | HIGH |
| `test_chunk_search_filters_null_tenant_when_none` | When `tenant_id=None`, filter is `WHERE tenant_id IS NULL` | HIGH |
| `test_chunk_search_filters_tenant_and_null` | When `tenant_id=:tid`, filter is `WHERE tenant_id IS NULL OR tenant_id = :tid` | HIGH |
| `test_document_deletion_consumer_idempotent` | Second consumption of same deletion event is no-op (no error on empty DELETE) | HIGH |
| `test_avro_tenant_id_field_default_null` | All three updated Avro schemas have `tenant_id` with `"default": null` | HIGH |
| `test_upload_rate_limit_valkey_fail_open` | Upload proceeds when Valkey is unavailable; counter incremented | MEDIUM |
| `test_upload_dedup_race_integrity_error_mapped_to_409` | `IntegrityError` from unique index → `DuplicateDocumentError` → 409 | HIGH |
| `test_upload_use_case_minio_failure_triggers_compensating_gc_and_reraises` | DB write fails after MinIO write; compensating delete called; original exception re-raised | HIGH |
| `test_document_deletion_consumer_uses_valkey_dedup_mixin` | `DocumentDeletionConsumer` inherits `ValkeyDedupMixin`; architecture test CONSUMER-DEDUP-001 passes | HIGH |
| `test_document_ready_consumer_sets_status_ready` | S4 `DocumentReadyConsumer` sets status=READY and chunk_count on matching doc | HIGH |
| `test_document_ready_consumer_skips_deleted_documents` | Status guard: if doc is DELETED when READY event arrives, no status update | HIGH |
| `test_chunk_search_returns_document_title` | `EnrichedChunkResult` includes `document_title` for tenant upload chunks | HIGH |

### Integration Tests

| Test | Infrastructure | What It Verifies |
|------|---------------|------------------|
| `test_upload_endpoint_pdf_full_flow` | Postgres, MinIO | POST upload → 202; document row in DB; bronze object in MinIO |
| `test_upload_endpoint_duplicate_returns_409` | Postgres | Second upload of same PDF by same tenant → 409 with existing doc_id |
| `test_upload_endpoint_different_tenants_same_content_ok` | Postgres | Two tenants uploading same PDF → both get 202 (per-tenant dedup) |
| `test_get_document_tenant_isolation` | Postgres | Tenant B cannot retrieve tenant A's document (404 not 403) |
| `test_list_documents_pagination` | Postgres | Cursor pagination returns correct pages |
| `test_delete_document_sets_status` | Postgres, Kafka | DELETE → status=deleted → outbox event published |
| `test_s5_migration_0005_existing_rows_null` | Postgres | All pre-migration document rows have tenant_id=NULL after migration |
| `test_s6_migration_chunks_null` | Postgres | All pre-migration chunk rows have tenant_id=NULL after migration |
| `test_dedup_hashes_global_unique_constraint` | Postgres | Two NULL-tenant rows with same hash type+value rejected |
| `test_dedup_hashes_per_tenant_unique_constraint` | Postgres | Same tenant, same hash → rejected; different tenant, same hash → allowed |
| `test_chunk_search_excludes_other_tenant_chunks` | Postgres, pgvector | Chunks from tenant B not returned in tenant A's search |
| `test_chunk_search_includes_public_and_private` | Postgres, pgvector | Public (NULL) chunks + tenant's private chunks both returned |
| `test_document_deletion_consumer_removes_chunks` | Postgres, Kafka | After `content.document.deleted.v1`, all chunks for doc_id+tenant_id removed |
| `test_s4_outbox_propagates_tenant_id` | Postgres, Kafka | Outbox event for tenant_upload source has tenant_id set in Avro payload |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_avro_content_article_raw_v1_tenant_id_field` | Schema has `tenant_id` as `["null", "string"]` with `"default": null` |
| `test_avro_content_article_stored_v1_tenant_id_field` | Same check for stored schema |
| `test_avro_nlp_article_enriched_v1_tenant_id_field` | Same check for enriched schema |
| `test_avro_content_document_deleted_v1_shape` | New schema has all required envelope fields + doc_id + tenant_id |
| `test_canonical_model_alignment_content_article_raw` | `libs/contracts` canonical model matches Avro schema field for field |
| `test_avro_nlp_document_ready_v1_shape` | New schema has all required envelope fields + doc_id + tenant_id + chunk_count |
| `test_avro_content_document_deleted_v1_source_type_not_enum` | `source_type` in `content.article.raw.v1` is Avro `string` type (not `enum`) — confirms no enum-extension migration needed |

---

## 12. Migration Strategy

### Phase 1 — Schema + Pipeline Isolation (prerequisite; zero user impact)

All migrations are additive (nullable columns, new indexes). No downtime required.

1. Deploy S5 migration 0002: adds `tenant_id` to `documents` and `dedup_hashes`. Existing rows remain `NULL`. All existing S5 code still works (queries don't filter by tenant_id yet).
2. Deploy S6 migration: adds `tenant_id` to `chunks` and `sections`. Existing rows remain `NULL`. All existing HNSW queries still work (no filter added yet).
3. Deploy updated Avro schemas to Schema Registry. Old consumers see `tenant_id = null` in all existing events (backward-compatible via `"default": null`).
4. Deploy updated S5 `ArticleStorageConsumer` and S6 `ArticleProcessingConsumer` to propagate `tenant_id` from event payloads. For public news events (tenant_id=null in event), behavior is unchanged.
5. Deploy updated S8 `_fetch_chunks()` with `tenant_id` pass-through. With `tenant_id` set, the filter `WHERE tenant_id IS NULL OR tenant_id = :tid` returns all existing public chunks (tenant_id IS NULL) — **zero regression for existing tenants**.
6. Deploy updated S6 `ChunkSearchUseCase` with tenant filter.

### Phase 2 — Tenant Document Ingestion

1. Deploy new Kafka topics: `content.document.deleted.v1` and `nlp.document.ready.v1`. Topics must exist before services that produce or consume them are deployed.
2. Register new Avro schemas for both topics in Schema Registry (run `register-schemas.py`).
3. Deploy S4 migration: creates `tenant_document_uploads` table.
4. Deploy S4: new use cases (Upload, Get, List, Delete, UpdateDocumentStatus), new routes, `DocumentReadyConsumer`.
5. Deploy S6 `DocumentDeletionConsumer` (new consumer group `s6-document-deletion`).
6. Update S9 routing: add 3 new proxy routes.

### Rollback

- Phase 1 schema changes: rollback migrations (drop columns + indexes). Safe because new columns are nullable and existing code ignores them.
- Phase 2: new `tenant_document_uploads` table can be dropped without affecting any existing table. New topic can be deleted. S4 rollback removes new endpoints.

---

## 13. Observability

### New Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tenant_upload_total` | Counter | `tenant_id`, `status` (accepted\|rejected\|duplicate) | Upload attempts |
| `tenant_upload_processing_seconds` | Histogram | `source_type` | End-to-end processing time (upload → READY) |
| `tenant_upload_ratelimit_bypass_total` | Counter | — | Rate limit checks bypassed due to Valkey unavailability |
| `chunk_search_tenant_filter_active` | Gauge | — | 1 when tenant_id filter is applied in chunk search |
| `document_deletion_consumer_lag` | Gauge | — | Consumer lag on `content.document.deleted.v1` topic |
| `document_ready_consumer_lag` | Gauge | — | Consumer lag on `nlp.document.ready.v1` topic (S4 consumer) |
| `tenant_upload_status_update_total` | Counter | `status` (ready\|failed) | Status transitions applied by S4 `DocumentReadyConsumer` |

### Status Monitoring

`GET /api/v1/documents` provides per-tenant visibility into processing status. Documents stuck in `PROCESSING` for > 10 minutes indicate pipeline failures and should trigger an alert (future monitoring rule).

### Structured Logs

All upload events log at INFO: `doc_id`, `tenant_id`, `word_count`, `status`, elapsed seconds. No file content logged.

---

## 14. Open Questions

| ID | Question | Classification | Resolution |
|----|----------|---------------|------------|
| OQ-001 | How does `tenant_document_uploads.status` transition to READY? S6 `ArticleProcessingConsumer` finishes processing but has no direct connection to S4's DB. Options: (A) S6 publishes a `nlp.document.ready.v1` event that S4 consumes to update status; (B) S4 polls a dedicated S6 endpoint; (C) RAG-chat determines readiness by detecting chunks exist. | **RESOLVED — Option A** | **Decision**: Implement a new lightweight `nlp.document.ready.v1` Avro event (fields: `event_id`, `event_type`, `schema_version`, `occurred_at`, `doc_id`, `tenant_id`, `chunk_count`, `word_count`) emitted by S6 after successful enrichment via the nlp_db outbox. S4 deploys a new `DocumentReadyConsumer` (consumer group `s4-document-ready`) that calls `UpdateDocumentStatusUseCase` to set status=READY and chunk_count. This is the only option consistent with R7 (no cross-service DB) and R8 (no dual-write). Options B and C are rejected: B requires polling and introduces an S4→S6 REST dependency; C is undefined and leaves status permanently in PROCESSING for failures. **This OQ must be resolved before Phase 2 Wave 1 implementation begins.** New topic `nlp.document.ready.v1` must be added to §6.3 and a new Avro schema must be created. The plan must include a wave for this event + S4 consumer. |
| OQ-002 | When RAG citation references a private document, what metadata is available? Specifically: does `ChunkSearchUseCase` return `doc_id`, and can S8 look up the document title from S4? Or should title be denormalized onto the chunk row? | **RESOLVED** | **Decision**: Denormalize `document_title` onto `chunks` table as a nullable `VARCHAR(512)` column (NULL for public news chunks, populated during S6 processing for tenant uploads). S6's `ArticleProcessingConsumer` receives `title` from the `content.article.stored.v1` event and writes it to each chunk row at INSERT time. This avoids a cross-service REST call from S8→S4 at query time (R7 compliance) and avoids the complexity of S8 caching S4 titles. The `chunks` migration (0019) must include this column. The S6 chunk search query must return `document_title` in results; `ChunkSearchRequest`/`EnrichedChunkResult` must expose it. **Implement in Phase 1 Wave 1 alongside other migration columns.** |
| OQ-003 | Should `source_type` in `content.article.raw.v1.avsc` be verified as Avro `enum` or `string` type before implementation? | **RESOLVED — no schema change needed** | Verified in PRD revision: `content.article.raw.v1.avsc` field `source_type` is `"type": "string"` with doc `"eodhd \| sec_edgar \| finnhub \| newsapi \| manual"`. Adding `tenant_upload` as a new string value requires **no Avro schema change** — string values are open by convention. The doc comment on the field should be updated to include `tenant_upload` during Wave 1 implementation. |

---

## 15. Estimation

| Phase | Waves | Services | Complexity |
|-------|-------|---------|------------|
| Phase 1 — Schema + Isolation | 2 | S5, S6, S8 + Avro schemas | Medium (migrations + filter wiring) |
| Phase 2 — Document Ingestion | 4 | S4 (domain entity + use cases + DocumentReadyConsumer) + S6 (deletion consumer + nlp.document.ready.v1 outbox) + S9 routing + Kafka topic provisioning | High (new domain entity + async pipeline + two-direction event flow) |
| **Total** | **6 waves** | 5 services | |

**Implementation order**:
1. Phase 1 Wave 1: S5 migration 0005 + S6 migration 0019 (including `document_title` column) + Avro schema updates for `content.article.raw/stored/enriched.v1`
2. Phase 1 Wave 2: S8 `ChunkSearchRequest.tenant_id` + S5/S6 consumer `tenant_id` propagation + S6 `ChunkSearchUseCase` tenant filter + `EnrichedChunkResult.document_title`
3. Phase 2 Wave 1: New Kafka topics + Avro schemas for `content.document.deleted.v1` + `nlp.document.ready.v1`
4. Phase 2 Wave 2: S4 domain entity + 4 use cases + `UploadTenantDocumentUseCase` migration + `DocumentReadyConsumer`
5. Phase 2 Wave 3: S4 endpoints + S9 routing (3 proxy routes)
6. Phase 2 Wave 4: S6 `DocumentDeletionConsumer` + `nlp.document.ready.v1` outbox emission in `ArticleProcessingConsumer`
