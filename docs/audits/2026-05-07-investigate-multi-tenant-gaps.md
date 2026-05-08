# Investigation Report: Multi-Tenant Architecture Gap Analysis

**Date**: 2026-05-07
**Skill**: investigate
**Severity**: HIGH (data-leak risk in multi-tenant deployment)
**Status**: Root cause identified — architectural scope decision needed before implementation
**Branch**: feat/content-ingestion-wave-a1

---

## 1. Issue Summary

The platform was originally scoped as single-tenant for thesis purposes. Multi-tenancy was
planned ("logical: shared DB, tenant_id filter" per PRODUCT_CONTEXT.md) but incompletely
implemented. The portfolio and alert domains are fully tenant-aware; the content ingestion,
NLP, knowledge graph, and RAG retrieval pipeline is either partially or completely unaware of
tenancy. If multiple tenants are active simultaneously, the RAG retrieval layer would serve
cross-tenant content to all users, the Avro event stream carries no tenant routing header, and
vector similarity searches return chunks from all tenants indiscriminately.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `content-store/alembic/0001` — `documents` table has no `tenant_id` column | Migration file | BLOCKING — all ingested articles globally shared |
| `nlp-pipeline/alembic/0001` — `sections`, `chunks`, `chunk_embeddings` have no `tenant_id` | Migration file | BLOCKING — HNSW vector search crosses tenant boundary |
| `nlp-pipeline/alembic/0010` — `entity_mentions` has nullable `tenant_id` (migration exists) | Migration file | PARTIAL — partial work already done for F-009 |
| `intelligence-migrations/alembic/*` — `canonical_entities`, `relations`, `claims`, `events` have no `tenant_id` | All migration files | ARCHITECTURAL — KG is shared reference data by design |
| `infra/kafka/schemas/*.avsc` — 18/22 schemas missing `tenant_id` field | Avro schema files | BLOCKING — consumers cannot route events by tenant |
| `portfolio.events.v1.avsc`, `alert.email.sent.v1.avsc` — have `tenant_id` | Schema files | Confirms portfolio domain is correctly multi-tenant |
| `nlp-pipeline/src/nlp_db/repositories/news_query.py:136` — `entity_mentions` filtered by `IS NULL OR = :tenant_id` | Source code | Partial implementation of F-009 is already shipped |
| `ValkeyDedupMixin` docstring S-002 — explicit warning: dedup keys not tenant-scoped | `libs/messaging` | Known footgun, now needs to be addressed |
| `api-gateway/src/api_gateway/jwt_utils.py:52` — JWT includes `tenant_id` claim | Source code | Auth layer is correct |
| `api-gateway/src/api_gateway/middleware.py:266` — `tenant_id` forwarded in downstream JWT | Source code | Auth propagation is correct |
| `rag-chat/alembic/0001` — `threads` has `tenant_id`; `messages` does not | Migration file | Messages rely on thread join for tenant context |
| `libs/storage/src/storage/key_builder.py` — key format has no tenant segment | Source code | MinIO objects not namespaced per tenant |
| `api-gateway/middleware.py:404-420` — rate limit key is `f"rl:v1:user:{user_id}"` | Source code | Rate limits not scoped per (tenant, user) |

---

## 3. Execution Path Analysis

### 3.1 Current Data Flow (single-tenant design)

```
[External Source] → content-ingestion → content.article.raw (Avro, no tenant_id)
    → content-store (documents table, no tenant_id)
    → nlp-pipeline → sections/chunks/embeddings (no tenant_id)
        → nlp.article.enriched (Avro, no tenant_id)
    → knowledge-graph → canonical_entities/relations (no tenant_id in intelligence_db)
    → rag-chat: vector search on chunks (all tenants) → response

[User] → api-gateway (JWT with tenant_id) → rag-chat
    rag-chat reads threads (tenant_id ✓)
    rag-chat reads chunks (ALL tenants, no filter) ← DATA LEAK
```

### 3.2 Correctly Implemented Tenant Flows (can be used as reference)

```
[User] → api-gateway (tenant_id in JWT) → portfolio-service
    portfolio reads holdings WHERE tenant_id = :tid ✓
    portfolio reads watchlists WHERE tenant_id = :tid ✓
    Kafka events carry tenant_id ✓
```

### 3.3 Architectural Question: Is the KG Shared or Per-Tenant?

The knowledge graph (entities, relations) represents public reference data: "Apple Inc.",
its relations to Tim Cook, its sector. This is conceptually shared across all tenants — it
would be redundant and wasteful to maintain per-tenant copies of globally-known entity graphs.

**Recommendation**: Keep the KG as a shared reference layer. Tenant isolation happens at
the **usage** layer — which documents a tenant has ingested and which entities their content
mentions. This is already the direction of F-009 (entity_mentions.tenant_id added).

The model: `entity` (shared global) ↔ `entity_mention` (per-tenant junction) ↔ `document`
(per-tenant).

---

## 4. Gap Classification

### GAP-1 (BLOCKING): Content-Store — `documents` table has no `tenant_id`

**File**: `services/content-store/alembic/versions/0001_create_content_store_schema.py`
**Tables affected**: `documents`, `minhash_signatures`, `minhash_entity_mentions`, `dedup_hashes`, `duplicate_clusters`
**Impact**: All ingested articles are globally accessible. A cross-tenant query would return any tenant's articles.
**Fix**: Add nullable `tenant_id UUID` column + `CREATE INDEX ON documents(tenant_id)` via new Alembic migration. Populate from the JWT in the content-ingestion writer path. Update all repository queries to filter by tenant_id.
**Downstream**: MinHash dedup hashing should remain tenant-unaware (same article from two tenants should still be deduplicated), but `documents.tenant_id` should track which tenant first ingested the article. Consider a `content.article.stored` event payload update to carry tenant_id.

---

### GAP-2 (BLOCKING): NLP-Pipeline — `sections`, `chunks`, `chunk_embeddings` have no `tenant_id`

**Files**: `services/nlp-pipeline/alembic/versions/0001_create_nlp_schema.py` and related migrations
**Impact**: HNSW vector similarity search in RAG-chat returns top-K chunks from ALL tenants. Cross-tenant content leaks via semantic search — the highest-impact data breach vector.
**Note**: `entity_mentions` already has tenant_id (migration 0010, F-009). Chunks need the same.
**Fix**: New migration adding `tenant_id UUID NULLABLE` to `chunks` (and `sections` for completeness). Add partial HNSW index strategy: either add `tenant_id` to WHERE clause in all chunk queries, or partition HNSW by tenant. The simpler path: `WHERE tenant_id = :tid OR tenant_id IS NULL` with a composite index `(tenant_id, ...)`. Update all chunk retrieval queries in `rag-chat` and `nlp-pipeline` to pass and filter on `tenant_id`.

---

### GAP-3 (ARCHITECTURAL DECISION NEEDED): Knowledge Graph — Shared Reference Layer

**Tables**: `canonical_entities`, `relations`, `relation_evidence_raw`, `relation_summaries`, `claims`, `events`, `entity_embedding_state`
**Current state**: No tenant_id on any intelligence_db table.
**Recommended model**: Keep the KG as a shared reference layer (entities and relations are public facts). Tenant isolation is enforced at:
- `entity_mentions.tenant_id` (already done, F-009)
- `documents.tenant_id` (GAP-1 above)
- Query layer: tenant-specific KG traversals are scoped by starting from the tenant's entity_mentions/watchlist entities, not by filtering the entity/relation tables themselves.
**ADR required**: This design choice must be documented before implementation begins.

---

### GAP-4 (BLOCKING): Avro Schemas — 18/22 Event Schemas Missing `tenant_id`

**Files**: `infra/kafka/schemas/*.avsc`
**Schemas without tenant_id**:
- `content.article.raw.v1.avsc`
- `content.article.stored.v1.avsc`
- `nlp.article.enriched.v1.avsc`
- `entity.canonical.created.v1.avsc`
- `entity.dirtied.v1.avsc`
- `entity.provisional.queued.v1.avsc`
- `graph.state.changed.v1.avsc`
- `intelligence.contradiction.v1.avsc`
- `intelligence.temporal_event.v1.avsc`
- `market.dataset.fetched.avsc` (global market data — acceptable to leave without tenant_id)
- `market.instrument.created.avsc` (global — acceptable)
- `market.instrument.discovered.v1.avsc` (global — acceptable)
- `market.instrument.updated.avsc` (global — acceptable)
- `market.prediction.v1.avsc` (global — acceptable)
- `nlp.signal.detected.v1.avsc`
- `portfolio.watchlist.updated.v1.avsc`
- `relation.type.proposed.v1.avsc`

**Impact**: Kafka consumers processing content/NLP/intelligence events have no routing context. They cannot write tenant_id to destination tables because the event doesn't carry it.
**Fix**: Add `{"name": "tenant_id", "type": ["null", "string"], "default": null}` to all content/NLP/intelligence schemas (nullable for backward compatibility per R5). Market data schemas are global reference data and may remain without tenant_id.
**Rule R5 compliance**: Adding a nullable field with `"default": null` is forward-compatible.

---

### GAP-5 (MEDIUM): Kafka Consumer Dedup Keys — No Tenant Namespace

**File**: `libs/messaging/src/messaging/kafka/consumer/dedup.py:157`
**Key pattern**: `f"{self._dedup_prefix}:{event_id}"`
**Documented**: S-002 in the codebase explicitly flags this footgun.
**Risk**: If the same `event_id` UUID appears in events for two different tenants (vanishingly unlikely in practice due to UUIDv7 randomness), the dedup key would collide. More realistic: in a replay scenario where events are re-ingested for a specific tenant, the old dedup key blocks reprocessing.
**Fix**: Update key pattern to `f"{self._dedup_prefix}:{tenant_id}:{event_id}"`. Requires `tenant_id` to be available in the Kafka consumer context (either from the event payload — requires GAP-4 fix — or from consumer configuration).
**Scope**: All 15+ `_dedup_prefix` declarations across market-data, knowledge-graph, and nlp-pipeline consumers.

---

### GAP-6 (MEDIUM): API Gateway Rate Limiting — Per-User Not Per-(Tenant, User)

**File**: `services/api-gateway/src/api_gateway/middleware.py:404-420`
**Key pattern**: `f"rl:v1:user:{user_id}"` (line ~420)
**Impact**: A user belonging to multiple tenants could consume rate limit quota from one tenant's context while appearing limited in another. In multi-tenant deployments, rate limits should be scoped per (tenant, user).
**Fix**: Change rate limit key to `f"rl:v1:user:{tenant_id}:{user_id}"`. Simple one-line change.

---

### GAP-7 (MEDIUM): MinIO Object Keys — No Tenant Namespace

**File**: `libs/storage/src/storage/key_builder.py`
**Key format**: `{service}/{domain}/{resource_id}/{artifact}/{version}.{ext}`
**Impact**: Two tenants could store an object at the same path (if `resource_id` is globally derived from a non-tenant-scoped ID). Currently unlikely since `resource_id` contains UUIDs, but lacks explicit isolation for auditing/access control.
**Fix option A**: Update `KeyBuilder.build()` to accept an optional `tenant_id` segment prepended: `{tenant_id}/{service}/{domain}/...`. Breaking change — all existing keys would need migration.
**Fix option B**: Rely on tenant_id-scoped `resource_id` values (e.g., always include `doc_id` which is tenant-scoped after GAP-1 fix). No structural change needed.
**Recommendation**: Option B (lower blast radius). Document the convention that `resource_id` must derive from a tenant-scoped entity ID.

---

### GAP-8 (LOW): RAG-Chat `messages` Table — No `tenant_id` Column

**File**: `services/rag-chat/alembic/versions/0001_create_rag_db.py`
**Status**: `threads` table correctly has `tenant_id`; `messages` only has `thread_id` FK.
**Risk**: Queries against `messages` that join through `threads` inherit tenant context correctly. Only a direct message query bypassing the thread join would leak. No such direct API exists currently.
**Fix**: Add `tenant_id UUID` to `messages` table for defense-in-depth. Can be populated by `SELECT tenant_id FROM threads WHERE thread_id = :tid` on insert.
**Severity**: LOW because all current API routes go through thread ownership check first.

---

## 5. Root Cause

The platform has two architecturally distinct domains:

1. **Portfolio/User/Alert domain** (S1, S10, S9): Designed multi-tenant from day one. Every table has `tenant_id`. Every Avro event carries `tenant_id`. Every query filters by `tenant_id`. The JWT propagation is correct.

2. **Content/Intelligence/NLP/RAG domain** (S2, S3, S4, S6, S7, S8): Designed as a shared intelligence pipeline that processes public market information. Multi-tenancy was partially started (F-009 added `entity_mentions.tenant_id`), but the foundational tables — `documents`, `chunks`, `chunk_embeddings` — never received tenant isolation. The Avro event schemas for this pipeline have no tenant routing.

**Root cause**: The content/intelligence pipeline was built as a shared utility and the multi-tenancy retrofit was started but not completed. The absence of `tenant_id` in Avro schemas means that even if tables get the column, consumers have no way to populate it from events.

---

## 6. Impact Analysis

- **Immediate impact**: In a true multi-tenant deployment, the RAG vector search serves results from all tenants. A user at Tenant B asking "What is Tenant A's portfolio thesis?" could receive chunks from Tenant A's ingested documents if both tenants overlap in their content sources.
- **Blast radius**: Content pipeline (S2–S7), RAG-chat (S8), knowledge graph (S7). Portfolio/Alert (S1, S10) are unaffected — already correct.
- **Data integrity**: No data corruption. Existing data remains valid; the gap is one of access control (cross-tenant reads) not correctness.
- **The KG shared layer**: NOT a data leak — entities and relations are public facts. The leak is in the document/chunk layer.

---

## 7. Recommended Implementation Order

### Phase 1: Foundation (must happen first — all other phases depend on these)
1. **Add `tenant_id` to all content-pipeline Avro schemas** (GAP-4) — nullable, with `"default": null`. Without this, Kafka consumers can't populate tenant_id in destination tables.
2. **Add `tenant_id` to `documents` table** (GAP-1) — migration 0002 in content-store. Update content-ingestion writer to carry tenant_id from JWT into the `content.article.raw` event.
3. **Add `tenant_id` to `chunks` and `sections`** (GAP-2) — migration 0019 in nlp-pipeline. Update `ArticleProcessingConsumer` to propagate tenant_id from the incoming enriched event.

### Phase 2: Query Isolation (blocks multi-tenant RAG correctness)
4. **Update chunk retrieval queries** — all NLP and RAG-chat queries that search chunks by vector similarity must add `AND (tenant_id = :tid OR tenant_id IS NULL)` filter.
5. **Update content-store repository layer** — all document queries must accept and propagate `tenant_id`.
6. **Update API Gateway rate limit key** (GAP-6) — one-line change, low risk.

### Phase 3: Event Consumer Wiring (required for ongoing correctness)
7. **Update Kafka consumers** to extract `tenant_id` from event payload and write it to destination tables. Requires Phase 1 (schemas must carry tenant_id).
8. **Update dedup keys** (GAP-5) — add tenant_id to the dedup key format. Requires Phase 1.

### Phase 4: Hardening (defense-in-depth)
9. **Add `tenant_id` to `messages` table** (GAP-8) — low priority, low risk.
10. **Document KG shared-layer ADR** (GAP-3) — write ADR confirming entities/relations are global reference data; isolation is at entity_mentions and document level.

---

## 8. Open Questions Requiring Decisions

| Question | Impact | Recommendation |
|----------|--------|----------------|
| Is the knowledge graph a shared reference layer or per-tenant? | Determines if intelligence_db needs tenant_id on entity/relation tables | **Recommend: shared** — entities are public facts; isolation at entity_mentions level |
| Should market data Avro schemas carry `tenant_id`? | OHLCV/fundamentals are global — should they be tenant-attributed? | **Recommend: NO** — market data is global reference data, same for all tenants |
| Should MinIO object keys be restructured with tenant prefix? | Breaking change to all existing object references | **Recommend: NO for now** — ensure `resource_id` always derives from tenant-scoped IDs |
| What is the content pipeline's tenant attribution model? | Who "owns" an article if multiple tenants ingest the same URL? | **Recommend**: Content-store deduplicates globally; `documents.tenant_id` = first ingester; article is accessible to all tenants who trigger ingestion (shared article model) |

---

## 9. Next Steps

This investigation reveals that multi-tenancy readiness requires a **PRD** to answer the open questions (especially the shared-vs-per-tenant KG question and the content deduplication model) before any implementation begins.

**Suggested path**: `/prd` → `PRD-0032: Multi-Tenant Content Pipeline Isolation` covering Phases 1–3 above.

Then `/plan` → implementation waves starting with schema migrations and Avro schema updates.

---

## 10. Compounding Check

- **PRODUCT_CONTEXT.md**: Multi-tenancy constraint should be strengthened — currently says "Logical (shared DB, tenant_id filter)" which is the correct target, but needs to note which domains are shared reference data vs. per-tenant.
- **docs/BUG_PATTERNS.md**: No new bug pattern from this investigation — the gaps are architectural incompleteness, not bugs.
- **STANDARDS.md**: Should add a rule: "Every Avro schema for user-attributable events MUST include a `tenant_id` field with `default: null` for forward-compatibility."
- **HIGH_RISK_PATTERNS.md**: Add HR pattern: "HNSW/vector search query without tenant_id filter on chunks/embeddings = cross-tenant data leak (analogous to SQL query missing WHERE tenant_id)."
- **REVIEW_CHECKLIST.md**: Add check: "If adding a new Kafka consumer that writes to a shared table, does the Avro event schema carry tenant_id? Does the consumer propagate it?"
