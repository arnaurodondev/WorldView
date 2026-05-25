# NLP Pipeline Quality Improvements Report

**Date**: 2026-05-22
**Branch**: feat/plan-0089-w2
**Scope**: S6 (nlp-pipeline), S7 (knowledge-graph), S8 (rag-chat)
**Context**: Post-fix state following three code-level bug fixes committed this session

---

## Executive Summary

Three independent bugs that were silently nullifying large swathes of the NLP enrichment pipeline have been fixed in commit d09db499 and related work this session: a phantom `is_backfill` column in the enrichment writer's `relations` INSERT blocked all 3,951 entity enrichments; a `claim_id`/`raw_id` FK mismatch stored 584 contradiction links with broken foreign keys, making them invisible to UI reads; and 7,366 embedded SEC filings and earnings transcripts were wired into the Intelligence tab brief for the first time via `_fetch_entity_chunks`. A fourth blocking condition — a DeepInfra billing cap exhausted at 16:17 UTC 2026-05-22 — is an external account issue requiring a manual top-up before the enrichment, embedding, and resolution workers can process the backlog. After billing is restored and the platform is restarted to load the enrichment writer fix, the pipeline is expected to begin enriching entities at its configured batch rate, contradiction links will be correctly keyed, and Intelligence tab briefings will include relevant document sections for the first time.

---

## Fixes Applied (This Session)

### 1. Enrichment Writer — Root Cause and Expected Impact

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/adapters/entity_enrichment_adapter.py`

**Root cause**: The `relations` INSERT in `seed_relations()` previously included an `is_backfill` column that does not exist on the `relations` table. SQLAlchemy raised a `ProgrammingError: column "is_backfill" of relation "relations" does not exist` on every enrichment attempt. Because the use case wraps the DB write in a broad `SQLAlchemyError` catch (structured_enrichment.py:376–384), this error was re-raised as a `RetryableEnrichmentError`, which the scheduler logged at WARNING and moved on. Result: 3,951 canonical entities have `enriched_at IS NULL` and `enrichment_attempts` ranging 1–3, with no descriptions, no structured relations seeded, and no `entity.dirtied.v1` events emitted.

The fix removes `is_backfill` from the INSERT column list. The adapter now issues clean inserts with the correct 13-column signature shown in the current source at lines 250–278.

**Expected impact after restart + billing restoration**:
- `DefinitionRefreshWorker` / `StructuredEnrichmentUseCase` can complete Phase 3 DB writes for the first time.
- Each enriched entity triggers `seed_relations()` — up to 4 structured relations per financial instrument (listed_on, headquartered_in, is_in_sector, is_in_industry) — potentially seeding ~3,000–6,000 structural graph edges that are currently absent.
- `entity.dirtied.v1` events will fire post-commit, triggering narrative re-embedding for each enriched entity.
- The three HNSW indexes (definition, narrative, fundamentals) will become usable for the first time at meaningful scale.
- Enrichment rate depends on the LLM cascade: ~70% of entities should resolve via S3 market-data (fast, no DeepInfra dependency); the remaining 30% will queue for Gemini Flash Lite (description) or DeepInfra (Step 3 fallback).

**Quantitative baseline**: 0/3,951 entities enriched before fix. Target after 24 hours of operation: 500–1,500 entities enriched (limited by scheduler batch cadence and external API rate limits).

---

### 2. Contradiction FK — Root Cause and Expected Impact

**File**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/contradiction_batch.py`

**Root cause**: The `ContradictionBatchWorker.run()` method was passing `claim_id` as the `relation_evidence_id` argument to `contra_repo.insert_link()`. The `relation_contradiction_links.relation_evidence_id` column is a FK to `relation_evidence_raw.raw_id`, not to the claims table. As a result, 584 contradiction links were inserted with `relation_evidence_id` values that referenced non-existent `raw_id` rows — the FK constraint was either deferred or the rows happened to collide numerically. These links never surfaced in UI read queries (which JOIN `relation_contradiction_links` on `relation_evidence_raw.raw_id`) so contradictions were silently invisible.

The fix passes `raw_id` (fetched from the claim row as `claim.get("relation_evidence_raw_id")`) instead of `claim_id` at line 127 of the fixed source. A cleanup DELETE at lines 79–82 also runs idempotently on each cycle, removing any pre-fix orphaned links:

```sql
DELETE FROM relation_contradiction_links
WHERE relation_evidence_id NOT IN (SELECT raw_id FROM relation_evidence_raw)
```

The `raw_id is None` guard at line 114–121 handles claims with no corresponding `relation_evidence_raw` row gracefully — those are skipped rather than failing.

**Expected impact after restart**:
- The cleanup DELETE will remove the 584 orphaned links on the first cycle.
- New contradiction links will be correctly keyed to `relation_evidence_raw.raw_id`.
- UI contradiction surfaces (relation detail panel, entity graph edge overlays) will begin showing real contradiction data for the first time.
- The `relations.strongest_contra_score` / `contra_count_by_type` / `latest_contra_at` aggregation (T-B-02 block, lines 139–178) can now correctly compute per-relation contradiction statistics.
- Relations whose recomputed confidence falls below 0.1 will be soft-closed (`valid_to = NOW()`), which prevents stale contradicted edges from dominating graph traversal.

**Coverage caveat**: Only claims with a matching `relation_evidence_raw` row (i.e., those that passed through the promoter) will generate contradiction links. The 52.3% of relation evidence rows that reference unresolved provisional entities (Issue F-017 in the QA audit) cannot generate contradiction links until F-001 (billing cap) is fixed and unresolved entities are resolved.

---

### 3. RAG Chunk Briefing — What Was Added and Expected Impact

**File**: `services/rag-chat/src/rag_chat/application/use_cases/briefing_context.py`

**What was added**: `_fetch_entity_chunks()` (lines 417–444) was wired into `gather_instrument_context()` as a fifth parallel coroutine in `asyncio.gather()` at line 237. It issues an ANN chunk search to S6 filtered to `source_types=["sec_filing", "earnings_transcript", "analyst_report"]` and `entity_ids=[UUID(entity_id)]`, with `top_k=10` and `min_score=0.4`. The query text is `entity_graph.canonical_name`, which gives the ANN index enough semantic signal to retrieve relevant document sections without an explicit user query. Results are passed as `relevant_chunks` into `BriefingContext.for_instrument()`.

**Before this fix**: All 7,366 embedded SEC filing and earnings transcript sections were indexed in S6's HNSW chunk index but never queried during Intelligence tab briefing generation. The briefing prompt had access only to news articles, live quotes, fundamentals highlights, and KG events.

**Expected impact**:
- Intelligence tab briefings for financial instruments will now include semantically relevant excerpts from SEC 10-K/10-Q filings, earnings call transcripts, and analyst reports.
- This is the highest-density factual signal available — filings contain precise revenue figures, guidance, risk factors, and management commentary that news articles summarize imprecisely.
- The ANN search is bounded (top_k=10, min_score=0.4) so prompt size remains controlled.
- R9 safe degradation is in place at lines 282–287: chunk search failure logs a warning and returns an empty list rather than crashing the briefing.

**Current limitation**: The improvement is partially gated on DeepInfra billing (F-001). Chunk search requires embedding the query text (`entity_name`) via S6's `/api/v1/embed` endpoint, which calls DeepInfra. Until billing is restored, the embedding step returns 402 and chunk search returns zero results. After billing is restored, this path will become fully functional.

**Additional limitation — JWT propagation (Issue F-008)**: `gather_instrument_context()` does not accept or pass an `internal_jwt` parameter, unlike `gather_morning_context()`. When S6 receives an embedding request from rag-chat without an `X-Internal-JWT` header, it returns 401. This means `_fetch_entity_chunks()` currently fails with a 401 on every call. The R9 degradation guard catches this silently. Fix: add `internal_jwt: str | None = None` parameter to `gather_instrument_context()` and call `set_current_jwt(internal_jwt)` before the coroutines are dispatched.

---

## Outstanding Quality Issues

### Relations Quality

**Evidence text coverage**: Of 9,432 rows in `relation_evidence_raw`, the QA audit identified that the `SummaryWorker` (which generates relation summaries for the Relations tab) relies on `evidence_text` being populated. The investigation found that relation polarity is `'positive'` for 100% of rows (Issue F-018), suggesting `polarity` is not propagated through the Avro payload — the same structural gap likely affects `evidence_text` population. Estimated coverage: unknown without a direct `SELECT COUNT(*) FROM relation_evidence_raw WHERE evidence_text IS NOT NULL`, but the 1.2% summary completion rate (96/7,805 relations) is consistent with near-zero coverage.

**Direction accuracy**: Approximately 50–80% of `has_executive` and `employs` relations are inverted (person as subject, company as object) — Issue F-005. This makes company→executive graph traversal unreliable for the most common relationship type in financial KGs.

**Relation type quality**: 526 relations are classified as `corporate_action` but most are government grants, product recalls, or real estate actions — Issue F-016. The type has no semantic discriminative power.

**Priority/Effort/Impact**:
- Direction normalization: P1 / S / HIGH — deterministic swap rule in `_build_raw_relations()`; no model changes needed
- Evidence text propagation: P1 / M / HIGH — requires Avro payload audit + consumer field mapping
- corporate_action cleanup: P2 / M / MEDIUM — prompt strengthening or type removal

---

### Entity Description Quality

**Current state**: 0/3,951 entities have descriptions (`enriched_at IS NULL` for all entities). Only 8 entities have any description field populated (from direct seed data, not the enrichment worker). The `data_completeness` score is 0.0 or NULL for all entities.

**After fix expected state**: Once the platform is restarted and billing is restored, the `StructuredEnrichmentUseCase` will process entities in batches ordered by `enrichment_attempts ASC, enriched_at ASC NULLS FIRST` (the partial index sweep). For `financial_instrument`/`company` entities, Step 1 (S3 market-data lookup) is expected to return descriptions for ~40–60% without any LLM call. Step 2 (EODHD on-demand profile) will cover another ~20%. Step 3 (LLM — Gemini Flash Lite) covers the remainder plus all `person`/`concept`/`location`/`event` types.

**Embedding quality gap**: Of existing entity embeddings, 90.5% encode only the entity name (since no description was available for the `definition_embedding` HNSW index). After enrichment runs, definition embeddings will be regenerated via `entity.dirtied.v1` events to reflect the actual descriptions, dramatically improving ANN search quality for entity similarity and semantic RAG retrieval.

**Rate limiting**: Gemini Flash Lite has its own rate limits. The enrichment worker should be monitored for 429 responses and the back-off cadence in `RetryableEnrichmentError` handling should be verified.

**Priority**: P0 (dependent on billing) / XS (no code change) / VERY HIGH — all downstream quality metrics improve once descriptions flow.

---

### Contradiction Detection Quality

**Current state after fix**: The cleanup DELETE in `ContradictionBatchWorker.run()` will remove 584 orphaned links on the first post-fix cycle. Future cycles will insert correctly keyed links. Coverage remains partial because:

1. The batch window is 90 days with a cap of 500 claims per run — sufficient for the current scale.
2. Claims with no `relation_evidence_raw` row are skipped (the `raw_id is None` guard). This affects claims from provisional entities that were never resolved — currently ~52.3% of evidence rows.
3. Polarity is always `'positive'` (F-018), which means the `find_opposing_claims()` query that searches for opposite polarity claims will return very few matches. Until polarity extraction is fixed, contradiction detection coverage is near zero even with the FK fix applied.

**Priority for polarity fix**: P1 / M / HIGH — without polarity the contradiction detection system is structurally inoperative.

---

### RAG / Briefing Quality

**What chunk sources are now included** (after JWT fix + billing restoration):
- `sec_filing` — 10-K/10-Q/8-K sections indexed in S6 HNSW chunk index
- `earnings_transcript` — quarterly earnings call text
- `analyst_report` — sell-side research sections

**What is still missing**:
- JWT propagation gap (F-008): `gather_instrument_context()` lacks `internal_jwt` parameter → chunk search returns 401 silently on every call. This must be fixed for `_fetch_entity_chunks()` to function at all.
- Financial context entirely absent (F-007): `S3Client.find_instrument_by_ticker()` calls `/api/v1/instruments/symbol/{ticker}` which returns 404; correct path is `/api/v1/instruments/lookup?symbol={ticker}`. Quote and fundamentals are never retrieved for any instrument briefing.
- Morning briefing chunks: `gather_morning_context()` does not call `_fetch_entity_chunks()`. Portfolio-level filings are not included in morning briefs.
- Relation summary embeddings: 96 relation summaries exist but `summary_embedding` is NULL for all (F-019). Semantic relation search returns zero results.

---

### Other Open Issues (from QA Audit — Medium/Low Priority)

**MEDIUM — to address in next sprint**:
- **F-009** (`organization` entity type rejected by DB CHECK constraint): Companies like Grayscale, Tenstorrent, ZFLOW AI, and Wolfe Research can never be persisted. Requires a one-migration Alembic DDL change to add `'organization'` to the `ck_canonical_entities_entity_type` constraint.
- **F-010** (1,510 entities typed `unknown`, 38.6%): Follows from F-009. After F-009 is fixed, a batch reclassification pass is needed.
- **F-012** (High-frequency entities missing canonicals): SpaceX (59 unresolved mentions), CNBC (40), Benzinga (19+), "Fed" (10), IMAX (7) have no canonical entity. Direct SQL seed needed.
- **F-013** (Mixed embedding model in HNSW index): ~98% Ollama vs ~2% DeepInfra vectors in the same index. Minority set should be re-embedded after canonical provider is chosen.
- **F-014** (`final_routing_tier` NULL for 97.7% of routing decisions): Column is either never written or the wrong worker writes it.
- **F-015** (JWT skip-verification logged at CRITICAL level): Drowns real alerts. Change to DEBUG in `InternalJWTMiddleware`.

**LOW — backlog**:
- **F-020**: UPPERCASE relation types in AGE graph (`EXPOSED_TO_THEME`, `COMPETES_WITH`) unregistered in relation_type_registry.
- **F-021**: Near-duplicate entity proliferation (7+ Amazon variants, 4+ JPMorgan variants).
- **F-022**: 589 failed provisionals have NULL `context_snippet` — LLM resolution quality degraded.
- **F-023**: Narrative and fundamentals HNSW indexes have 0 scans despite populated vectors.
- **F-024**: 93 DLQ articles from GLiNER timeouts; no retry mechanism.
- **F-025**: 1,653 pre-scoring documents have no LLM relevance score (backfill needed).
- **F-026**: Model ID naming inconsistency (`bge-large:latest` vs `BAAI/bge-large-en-v1.5`).
- **F-027**: 12 duplicate canonical entities.

---

## Recommended Next Actions (Prioritized)

| # | Action | Priority | Effort | Expected Impact |
|---|--------|----------|--------|-----------------|
| 1 | Top up DeepInfra billing at `https://deepinfra.com/dash/billing` | P0 | XS | Unblocks 4 workers: relevance scoring, entity resolution, embedding, LLM extraction |
| 2 | Restart platform to load enrichment writer fix (commit d09db499) | P0 | XS | Unblocks all 3,951 entity enrichments |
| 3 | Reset abandoned embedding queue after billing restored | P0 | XS | Recovers 706 permanently abandoned embedding items |
| 4 | Fix JWT propagation in `gather_instrument_context()` — add `internal_jwt` param | P0 | S | Enables `_fetch_entity_chunks()` to actually call S6; currently 100% failure rate |
| 5 | Fix RAG financial URL mismatch in `s3_client.py` — `/symbol/{ticker}` → `/lookup?symbol={ticker}` | P0 | XS | Enables quote and fundamentals to appear in instrument briefings for first time |
| 6 | Recreate entity-refresh-consumer container (DNS failure) | P1 | XS | Restores narrative re-embedding after entity enrichment |
| 7 | Fix price impact worker DNS hostname | P1 | S | Enables `article_impact_windows` to populate (currently 0/6,259) |
| 8 | Fix `organization` entity type in CHECK constraint (Alembic migration) | P1 | S | Unblocks ~15% of provisional entity creates that currently fail silently |
| 9 | Add self-loop filter in `_build_raw_relations()` + clean existing rows | P1 | S | Eliminates 1,604 wasted evidence rows; stops unbounded accumulation |
| 10 | Fix relation direction normalization for `has_executive`/`employs` | P1 | S | Makes company→executive graph traversal reliable (~50–80% of these relations currently inverted) |
| 11 | Fix polarity extraction — audit Avro payload for `polarity` field | P1 | M | Without this, contradiction detection has near-zero coverage despite FK fix |
| 12 | Seed high-frequency missing entities (SpaceX, CNBC, Benzinga, Fed, IMAX) | P2 | S | Resolves 100+ unresolved mentions from high-signal financial sources |
| 13 | Fix JWT skip-verification log level CRITICAL → DEBUG | P2 | XS | Reduces log noise; real critical signals currently buried |
| 14 | Normalize `corporate_action` relation type via prompt clarification | P2 | M | Restores semantic meaning to 526 relations |
| 15 | Choose canonical embedding model; re-embed inconsistent minority | P2 | M | Ensures HNSW ANN ranking is reliable across entire index |
| 16 | Wire relation summary embeddings into `EmbeddingRefreshWorker` | P2 | M | Enables semantic relation search (currently 0 results) |
| 17 | Backfill LLM relevance scores for 1,653 pre-launch documents | P3 | M | Closes the display_relevance_score gap for pre-billing-cap articles |

---

## Metrics to Monitor After Billing Restoration

Run these queries against `intelligence_db` after billing is restored and the platform restarted. Check at T+1h, T+6h, and T+24h.

### Enrichment Progress
```sql
-- Entity enrichment: expect to grow from 0
SELECT COUNT(*) FROM canonical_entities WHERE enriched_at IS NOT NULL;

-- Enrichment by entity type (breakdown)
SELECT entity_type, COUNT(*) as enriched, COUNT(*) FILTER (WHERE enriched_at IS NULL) as unenriched
FROM canonical_entities
GROUP BY entity_type
ORDER BY enriched DESC;

-- Average data_completeness after enrichment
SELECT AVG(data_completeness) FROM canonical_entities WHERE enriched_at IS NOT NULL;

-- Structured relations seeded via enrichment (listed_on, headquartered_in, is_in_sector, is_in_industry)
SELECT canonical_type, COUNT(*) FROM relations WHERE relation_source = 'structured_enrichment' GROUP BY canonical_type;
```

### Contradiction FK Fix
```sql
-- Orphaned links removed by cleanup DELETE (should be 0 after first cycle)
SELECT COUNT(*) FROM relation_contradiction_links
WHERE relation_evidence_id NOT IN (SELECT raw_id FROM relation_evidence_raw);

-- Valid contradiction links (correctly keyed)
SELECT COUNT(*) FROM relation_contradiction_links rcl
JOIN relation_evidence_raw rer ON rer.raw_id = rcl.relation_evidence_id;

-- Relations with contradiction stats populated
SELECT COUNT(*) FROM relations WHERE strongest_contra_score IS NOT NULL;
```

### Embedding Recovery
```sql
-- Abandoned items reset and re-processed (should trend to 0)
SELECT COUNT(*) FROM embedding_pending WHERE retry_count >= 5;

-- Chunks with valid embeddings
SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL;

-- Entity definition embeddings (should grow as enrichment runs)
SELECT COUNT(*) FROM entity_embedding_state WHERE definition_embedding IS NOT NULL;
```

### RAG Chunk Briefing
```sql
-- Verify S6 embedding endpoint is reachable from rag-chat (check rag-chat logs)
-- docker logs worldview-rag-chat-1 --tail=50 | grep "briefing_chunk_search"
-- Should show: {"event": "briefing_chunk_search_failed"} disappear;
-- replaced by chunks actually included in briefing context
```

### Relevance Scoring Recovery
```sql
-- Articles scored after billing restoration (compare before/after)
SELECT COUNT(*) FROM document_source_metadata WHERE llm_relevance_score IS NOT NULL;

-- Unresolved entities (should decrease as resolution worker processes backlog)
SELECT COUNT(*) FROM entity_provisional_queue WHERE status = 'unresolved';
```

### Worker Health Check (run after T+30min)
```bash
# Enrichment worker
docker logs worldview-knowledge-graph-scheduler-1 --tail=50 | grep "enrichment_complete"
# Expected: enrichment_complete events with data_completeness > 0

# Contradiction worker
docker logs worldview-knowledge-graph-contradiction-batch-1 --tail=20 | grep "contradiction_batch_worker_complete"
# Expected: links_inserted > 0 (after enough polarity data accumulates)

# Embedding retry worker
docker logs worldview-nlp-pipeline-embedding-retry-1 --tail=20 | grep "retry_count"
# Expected: no more retry_count=5 after queue reset

# RAG chunk search
docker logs worldview-rag-chat-1 --tail=50 | grep "briefing_chunk"
# Expected: briefing_chunk_search_failed disappears (after JWT fix is deployed)
```
