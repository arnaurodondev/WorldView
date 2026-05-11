# PLAN-0078 — Chunk Entity-Filter + GLiNER Mention Storage

> **PRD**: derived from `/investigate` 2026-05-07 — long-term consistency review (issue C-2)
> **Status**: complete (4/4 waves done 2026-05-07)
> **Created**: 2026-05-07
> **Owner**: TBD
> **Estimated effort**: ~2 dev-days (4 waves, ~12 tasks)
> **Critical path**: Wave A → Wave B → Wave C → Wave D
> **Hard dependencies**: none (additive S6 storage + port extension)
> **Blocks**: PLAN-0067 W11-2 (`search_documents` tool), PLAN-0074 Wave F (entity-context chat)

---

## §0 Why this plan exists

Both PLAN-0067 (`search_documents` tool spec accepts `entity_tickers`) and PLAN-0074 (entity-context chat scopes retrieval by `entity_id`) presuppose `ChunkSearchRequest` supports filtering chunks by entity. **It does not.** The current port (services/rag-chat/src/rag_chat/application/ports/upstream_clients.py — `ChunkSearchRequest` dataclass at line 18) has only `query_text`, `query_embedding`, `top_k`, `min_score`, `granularity`, `include_entities`, `date_from`, `date_to`, `source_types`, `search_type`. Neither plan creates the filter; both depend on it.

S6 already extracts GLiNER mentions on every chunk (the `include_entities=True` flag in the port hints at this) but they are returned in the response, not used as a query-time filter. The mentions are not persisted in a queryable form on the chunk row — they live downstream in the entity-resolution pipeline as a separate `entity_mentions` table. This plan adds a denormalised JSONB copy on the chunk row for efficient GIN-indexed query-time filtering.

> **BP-405 Name Verification** (run before implementing each wave):
> - `ChunkANNRepository` — confirmed exists at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py`; concrete class, NOT an ABC. Wave C must depend on an ABC port (see §3 R25 note).
> - `ChunkSearchRequest` — **two distinct classes** with the same name; both must be extended in Wave C and Wave D respectively:
>   1. S6 Pydantic schema: `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (`ChunkSearchRequest(BaseModel)`)
>   2. S8 dataclass port: `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (`ChunkSearchRequest` dataclass)
> - `entity_mentions` — already a table name in nlp_db (`entity_mentions` stores GLiNER mention resolutions). The new column on the `chunks` table is `chunks.entity_mentions JSONB` — same name, different object. Implementer must be aware of this naming overlap; the migration description must be unambiguous.
> - `EnhancedChunkSearchUseCase` — confirmed exists at `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/enhanced_chunk_search.py`; this is the use case that Wave C extends.
> - `ChunkRepository` — confirmed exists at `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk.py`; this is the write-side repo that Wave B extends.
> - Next nlp-pipeline migration slot: **0018** (current head is `0017_add_chunks_tsv_english_gin.py` — pre-flight verified 2026-05-07).

This plan ships the missing piece end-to-end:

1. **S6 storage**: persist GLiNER mention metadata (entity_id, entity_type, char_offset, gliner_score) on the chunk row in a queryable JSONB column with a GIN index (migration `0018`).
2. **S6 endpoint**: extend the S6 Pydantic `ChunkSearchRequest` and `EnhancedChunkSearchUseCase` to accept `entity_ids: list[UUID]` and `entity_types: list[str]` filters that narrow results via the GIN index.
3. **S8 port extension**: extend the rag-chat dataclass `ChunkSearchRequest` with the new fields so callers can pass entity filters across the wire.
4. **Backfill**: re-extract GLiNER mentions for existing chunks via a one-shot script (must run before Wave C is wired in Wave D).

---

## 1. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Schema: `chunks.entity_mentions JSONB NOT NULL DEFAULT '[]'` + GIN index in S6 nlp-pipeline (migration `0018`) | DB migration | 2 hours |
| B | Worker: persist GLiNER mentions on every chunk write (extend `ChunkRepository.add`); backfill script for historical chunks | application + infra | 6 hours |
| C | Endpoint: extend S6 Pydantic `ChunkSearchRequest` with `entity_ids` + `entity_types`; extend `EnhancedChunkSearchUseCase` via `ChunkSearchPort` ABC; SQL builder in `ChunkANNRepository` uses GIN index | API + use case + infra | 6 hours |
| D | Port: extend rag-chat dataclass `ChunkSearchRequest` with new fields; integration tests; update `s6_client.py` to pass fields through | port + client | 4 hours |

## 2. Schema Sketch

```sql
-- Migration 0018 (next after 0017_add_chunks_tsv_english_gin.py)
ALTER TABLE chunks ADD COLUMN entity_mentions JSONB NOT NULL DEFAULT '[]';
CREATE INDEX ix_chunks_entity_mentions_gin ON chunks USING GIN (entity_mentions jsonb_path_ops);

-- Each entity_mentions element:
-- {"entity_id": "...", "entity_type": "company|person|location|...", "char_start": 0, "char_end": 5, "gliner_score": 0.92, "raw_text": "Apple"}
```

Filter via:
```sql
WHERE entity_mentions @> :entity_filter_json
-- where entity_filter_json = [{"entity_id": "<uuid>"}]
```

## 3. Hard Constraints

- **Backfill before port wires through** (§0 captures this): Wave B backfill script must complete on the dev DB before Wave D wires the filter into the S8 port — otherwise the new filter returns empty for older chunks. Merge sequence: Wave A migration → Wave B backfill + chunk write → Wave C S6 endpoint → Wave D S8 port.
- **Filter semantics — OR within field, AND across fields**: `entity_ids=[A, B]` matches chunks mentioning A *or* B; `entity_ids=[A] entity_types=["company"]` matches chunks mentioning A *and* tagged as company.
- **GLiNER score floor**: `entity_mentions` only stores mentions with `gliner_score >= GLINER_MENTION_FLOOR` (default 0.6) to avoid index bloat from low-confidence noise. See §4 env var.
- **Forward-compatible JSONB shape** (R11): new fields can be added to mention objects without breaking existing readers; never remove or rename existing JSONB keys.
- **R25 — ABC port required for Wave C**: `ChunkANNRepository` is a concrete infrastructure class. The extended search method must be exposed via a new ABC port interface in `application/ports/repositories.py` (e.g. `ChunkSearchPort`) so `EnhancedChunkSearchUseCase` depends on the ABC, not the concrete class. The concrete `ChunkANNRepository` implements `ChunkSearchPort`; DI in `api/dependencies.py` wires it.
- **R27 — ReadOnlyUoW for Wave C**: `EnhancedChunkSearchUseCase` is read-only (no mutations). Its dependency must be `ReadOnlyUnitOfWork` (not `UnitOfWork`), and the route handler must use `ReadUoWDep`. This routes chunk search queries to the read replica.
- **R10 — UUIDv7 for all IDs**: any new entity IDs generated during backfill or write path must use `common.ids.new_uuid7()`, never `uuid.uuid4()`.
- **R11 — UTC timestamps**: any `created_at` / `extracted_at` timestamps in the JSONB mention objects must be UTC-aware (`common.time.utc_now()`), never naive datetimes.
- **structlog only** (R14): all new workers, use cases, and backfill scripts must use `observability.get_logger(__name__)` — never stdlib `logging` or bare `print`.
- **R22 — standalone backfill process**: the backfill script runs as an independent one-shot process (`python -m nlp_pipeline.workers.backfill_entity_mentions`), not a background thread in the API server.
- **Forward-compatible schema extension** (R6): the S6 `ChunkSearchRequest` Pydantic schema extension (`entity_ids`, `entity_types`) adds optional fields with defaults — existing callers that omit them receive full unfiltered results (zero breaking change).
- **Migration number pre-flight** (R32): migration `0018` reserved by this plan after verifying that `0017_add_chunks_tsv_english_gin.py` is the current head. Implementer MUST re-verify head before coding: `ls services/nlp-pipeline/alembic/versions/ | sort -V | tail -3`.

## 4. Cross-cutting

- New env var: `NLP_PIPELINE_GLINER_MENTION_FLOOR` (S6, default `"0.6"`). Must be added to `RagChatSettings` and `docker-compose*.yml`.
- Update `docs/services/nlp-pipeline.md` with new column + endpoint params + env var.
- Update `services/nlp-pipeline/.claude-context.md` Databases section with `entity_mentions JSONB` column on `chunks` table and the GIN index.
- Tests required per R1:
  - **Unit**: `ChunkSearchPort` ABC contract test; `ChunkANNRepository.ann_search_filtered` with mocked session.
  - **Integration**: create chunk with known mentions → query `entity_ids=[that_id]` → assert only that chunk returned; query `entity_ids=[other_id]` → assert empty.
  - **Wave D unit test**: rag-chat `s6_client.py` passes `entity_ids` + `entity_types` through wire correctly (mock httpx).

## 5. Out of scope

- Sentiment per mention (can be added to JSONB later without breaking existing readers — R11 forward-compat).
- Rank ordering by mention prominence (future).
- Cross-service entity-resolution rebuild (already in S6 entity-resolution pipeline; this plan does not touch it).

---

*Stub generated 2026-05-07 by `/investigate`. Architecture compliance pass applied 2026-05-07 (BP-405 name verification, R25/R27/R10/R11/R22/R32 guardrails added).*
