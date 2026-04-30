# Revised Investigation: Retrieval, Graph Generation & Graph Traversal Architecture

**Date**: 2026-04-30
**Investigator**: Claude (investigation skill)
**Severity**: HIGH — architectural assessment in `2026-04-23` was correct in shape but materially wrong on multiple production-critical claims. The KG is effectively non-functional in production despite passing health checks.
**Status**: Supersedes `docs/audits/2026-04-23-retrieval-graph-architecture-investigation.md` and consolidates findings from:
  - `2026-04-27-investigation-model-decisions-and-kg-pipeline.md`
  - `2026-04-27-investigation-model-externalization-and-ui-validation.md`
  - `2026-04-29-investigation-news-pipeline-quality-deep-dive.md` (with 04-30 update)

**External References**: Karpathy LLM Wiki Gist · Elastic IR Reference

---

## 0. TL;DR

The 04-23 audit's architectural diagnosis (no BM25, no compilation layer, no eval framework, Cypher disabled) is **directionally correct** and remains the long-term roadmap. But its tone of "advanced prototype with strong production-grade entity resolution" is **wrong** for the current platform. As of 2026-04-30:

1. **The knowledge graph is effectively empty** — `relations` has 18 rows (all hand-seeded 2026-04-24), `relation_evidence` has 0, `relation_summaries` has 0, AGE shadow has 0 nodes / 0 edges. Six days of ingest have produced **zero production-side relations** that survive end-to-end.
2. **The reason is not "extraction model failure"** (the 04-29 v1 hypothesis). It is a **transit-layer silent drop** (F-CRIT-07): `_build_raw_relations` skips any relation whose endpoints are not in `entity_id_by_ref`, which only contains *resolved* mentions, while the prompt asked the LLM to use *every* mention. ~66% of documents have zero resolved mentions, so for those the entire extraction is destroyed at the producer/consumer boundary — silently, with all dashboards green.
3. **Entity resolution is not "production-grade"** — 7 of 11 GLiNER classes have **zero canonical entities** (regulatory_body, currency, person, location, commodity, macroeconomic_indicator, index, financial_institution, government_body partially); 46% of canonicals lack a self-alias (F-CRIT-04), so Stage-1 alias-exact-match silently misses the highest-confidence path.
4. **Several audit-trail tables are unwritten** — `mention_resolutions`, `llm_usage_log`, `provisional_entity_queue`, plus missing `routing_decisions.final_routing_tier` column — the pipeline is **observably blind** despite ~50 LLM calls / 30 min.
5. **Models have shifted** — embedding is `BAAI/bge-large-en-v1.5` via DeepInfra (not nomic-embed-text); deep extraction is `meta-llama/Meta-Llama-3.1-8B-Instruct` (not Qwen2.5-7B); reranker is Cohere primary + BGE fallback (not BGE primary). The 04-23 doc was written 4 days before the 04-27 externalization wave.
6. **All five 04-23 critical weaknesses are still real**, but two of them (Cypher disabled, knowledge compilation absent) are **dwarfed** by the data-flow defects above. Enabling Cypher today returns empty results; building entity summaries today compiles from zero relations.

**Revised maturity rating: 2.0 / 5.0 — Fragile Prototype with Strong Bones.** The architecture is sound; the integration is broken in compounding ways that need a focused remediation sprint *before* any of the 04-23 strategic improvements can be measured.

**Three-phase remediation sequence**:
- **Phase 1 (Stop the bleed, ~1 week)** — repair transit (F-CRIT-07), seed missing canonicals (F-CRIT-09/10), insert self-aliases (F-CRIT-04), persist audit tables (F-CRIT-02/03/05/06). After this, the 04-23 audit's "production-grade" framing becomes *true*.
- **Phase 2 (Make it measurable, ~2 weeks)** — eval framework (NDCG@10, MRR, P@5), retrieval quality metrics, source-specific recency. Without measurement, every later change is faith-based.
- **Phase 3 (Strategic uplift, 4-8 weeks)** — knowledge compilation layer (`entity_summaries`), hybrid retrieval (BM25+ANN+RRF), Cypher activation + path scoring, ontology enforcement, temporal KG.

The detailed execution artifact is **`docs/plans/0056-kg-retrieval-overhaul-plan.md`**.

---

## 1. What Was Wrong in the 2026-04-23 Audit

### 1.1 Factual errors (the audit was simply out-of-date)

| 04-23 Claim | Reality (2026-04-30) | Source |
|---|---|---|
| Embedding: `nomic-embed-text` 1024-dim | `BAAI/bge-large-en-v1.5` via DeepInfra (1024-dim); Ollama `bge-large:latest` fallback | `services/nlp-pipeline/src/nlp_pipeline/config.py`; 04-27 audit |
| Deep extraction: Qwen2.5-7B, 6K windows | `meta-llama/Meta-Llama-3.1-8B-Instruct` via DeepInfra; Qwen2.5-7B was crashing on CPU (GGML_ASSERT, num_ctx=32768) | 04-27 audit RC-4; user memory 04-27 |
| Intent classifier: Qwen2.5:3b or keyword fallback | DeepInfra `meta-llama/Meta-Llama-3.1-8B-Instruct` (`intent_classifier.py:92`) | Code verified |
| Reranker: BGE cross-encoder (primary) | Cohere `rerank-english-v3.0` is **primary** when `cohere_api_key` set; BGE Ollama is fallback (and fails 100% — model not in Ollama registry) | `reranker.py:111-201` (verified) |
| 9 parallel retrieval sources | 8 conditional sources (`_PlanFlags`); the "Cypher" slot is gated by `cypher_enabled=False` so realistically 7 active | `retrieval_orchestrator.py`, `retrieval_plan_builder.py:37-126` |
| Entity descriptions: Gemini 3.1 Flash Lite "hardcoded" | `description_provider` defaults to `none`; non-instrument entities receive template strings `"{name} is a {type}."`; F-MAJOR-04 in 04-29 | `services/knowledge-graph/.../config.py`; 04-29 audit |

### 1.2 Framing errors (the audit was correct in shape, wrong in confidence)

The 04-23 §1 "Top Strengths" section listed two strengths that are **wrong**:

1. **"Production-grade entity resolution — 4-stage cascade … the critical invariant that unresolved mentions are never discarded."**
   - The cascade exists in `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` and the threshold logic is correct.
   - But the *invariant is violated* in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:793-796` and `:850-853`: `entity_id_by_ref` is built only from `m.resolved_entity_id is not None`, and `_build_raw_relations`/`_build_raw_events`/`_build_raw_claims` `continue` silently when either endpoint is missing. The deep-extraction prompt at `deep_extraction.py` lists *all* mentions, so the LLM emits relations between resolved and unresolved entities with high frequency — and 100% of those relations are dropped at the boundary.
   - Empirically: producer logs show `relations: 6, claims: 3` for sample docs; consumer-side `raw_relations` array length is ~0 for the same docs (after the F-CRIT-07 transit drop).

2. **"Evidence-backed graph materialization — Append-only relation evidence, advisory locking … provenance tracking from source document through extraction to graph edge."**
   - The Block 12a code is real and correct. But it materialises ~0 production relations because everything upstream has been silently destroyed by F-CRIT-07. The audit verified the *code* but did not run end-to-end yield queries.

The 04-23 §1 "Top Critical Weaknesses" section is **mostly right** but **incomplete**:

3. **"Zero lexical/BM25 search"** — Confirmed. Zero `tsvector`/`ts_rank`/`plainto_tsquery`/`websearch_to_tsquery` usage in any service except SEC EDGAR adapter metadata. This is a real gap.
4. **"No knowledge compilation layer"** — Confirmed but **understated**. The audit treats this as a missing optimisation; it's actually compounding with F-MAJOR-01 (input articles are 1-3 sentence headlines too short for compilation) and F-CRIT-07 (the pipeline that would feed compilation is broken). Building entity summaries today would compile from near-empty input.
5. **"Graph traversal disabled and primitive"** — Confirmed, but **misses the deeper issue**: even if you flip `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` (S-2 in the 04-23 roadmap), the AGE shadow graph is empty (F-MAJOR-08 in 04-29). The `AgeSyncWorker` is registered in `services/knowledge-graph/.../infrastructure/workers/age_sync_worker.py` and code is comprehensive, but it's gated by the same flag and has not run a single sync (no Valkey watermark exists). Enabling Cypher must be paired with manually triggering a full sync.
6. **"No retrieval quality evaluation"** — Confirmed. Zero NDCG/MRR/P@k anywhere in the codebase. Real gap.
7. **"Single market data provider"** — Confirmed (`alpha_vantage.py:27` and `polygon.py:27` raise `ProviderUnavailable`). Tangential to KG/retrieval but worth flagging.

### 1.3 Findings the 04-23 audit missed entirely

The deep-dive on 04-29/30 surfaced findings that the 04-23 audit did not see because it inspected the *architecture* without inspecting *production data*:

| ID | Finding | Severity | Why 04-23 missed it |
|---|---|---|---|
| **F-CRIT-07** | Silent transit drop of relations/events/claims when an endpoint is unresolved (`article_consumer.py:850-853`) | CRITICAL | Architectural read; not row-count/yield read |
| **F-CRIT-09 / F-CRIT-10** | 7 of 11 GLiNER classes have zero canonical entities; per-class resolution rates are 0–10% for non-instrument classes; 66% of documents have zero resolved entities | CRITICAL | Did not query `canonical_entities` or `entity_mentions` row counts |
| **F-CRIT-04** | `entity_consumer` does not insert default self-alias on canonical creation; 83 canonicals → 38 aliases (54% gap) | CRITICAL | Did not query alias coverage |
| **F-CRIT-02** | `mention_resolutions` audit-trail table is empty for all 18,695 mentions (`mr_repo.add_batch()` not called) | CRITICAL | Audit-trail observability not checked |
| **F-CRIT-03** | `llm_usage_log` permanently empty across 3 workers (`usage_logger=None` hardcoded) — zero cost/latency observability | CRITICAL | Cost/latency dashboards not validated |
| **F-CRIT-06** | `routing_decisions` schema lacks `final_routing_tier` and `processing_path` columns; Block 8 novelty downgrade is computed in memory and lost at commit | CRITICAL | Schema vs use-case alignment not checked |
| **F-MAJOR-01** | Articles are 1-3 sentence headlines; sections ≈ chunks (~1.08 ratio); deep extraction has ~5–10× yield ceiling that requires fetching full article body | MAJOR | Source-data shape not inspected |
| **F-MAJOR-02** | `PriceImpactLabellingWorker` blocked by 401 Unauthorized; `price_impact` signal stuck at 0.0 for all articles → routing tier biased low → display_relevance_score broken | MAJOR | Worker-level health not checked |
| **F-MAJOR-04** | Description provider defaults to `none`; non-instrument entities get template descriptions; definition embeddings are degenerate | MAJOR | Did not query `entity_embedding_state` content |
| **F-MAJOR-08** | AGE shadow graph never populated (0 nodes / 0 edges) despite worker existing | MAJOR | Worker existence checked; execution not |
| **F-MAJOR-09** | Alias-generation prompt does not thread the entity description into the prompt (`{description}` placeholder absent; instrument_consumer passes it as unused `context=`) — alias generation produces ~0 rows | MAJOR | Prompt-template content not inspected |
| **Pattern: prompt/lookup mismatch** (root pattern of F-CRIT-07) | Whenever a prompt advertises values from a list, the call-site lookup MUST contain every advertised value — otherwise the LLM produces references to absent values, which the parser silently drops | Architectural | Not a recognised pattern at audit time |

### 1.4 Where the 04-23 audit underestimated severity

| 04-23 Severity | Revised | Reason |
|---|---|---|
| `display_relevance_score` "already solid" (LOW gap) | **HIGH gap** | Formula `0.5×market + 0.4×llm + 0.1×routing` requires `price_impact` (broken: F-MAJOR-02), `llm_relevance_score` (only 13% coverage due to short articles + 30-min batch), `routing.composite_score` (3 of 8 signals stuck constant). 87% of articles fall through to `0.4 × routing_tier` defaults |
| Routing tier as "graceful degradation" | **HIGH gap** | DEEP threshold was lowered from 0.70 → 0.45 on 04-27 *as a band-aid* because EODHD/Finnhub articles peak at 0.592. Even at 0.45, 66% of articles can't reach DEEP (no resolvable entities). The score is not "graceful"; it's optimistically defaulting |
| Entity resolution audit trail "auditable" (LOW gap) | **CRITICAL gap** | The trail is *defined* in the schema and *not written* in production (F-CRIT-02). Auditability is a property of the data, not the schema |

### 1.5 Where the 04-23 audit was over-cautious / can be deprioritised

| 04-23 Recommendation | Revised Priority | Reason |
|---|---|---|
| **L-2** Financial domain embedding model | **DEFER (P3)** | bge-large-en-v1.5 is general-purpose but performs adequately for financial vocabulary in informal benchmarks. Build the eval framework (M-3) first; only swap if NDCG regresses on a finance-specific golden set |
| **L-3** Relevance feedback loop | **DEFER (P3)** | Requires significant frontend instrumentation and traffic; premature for thesis-stage product |
| **L-5** Temporal knowledge graph | **PARTIAL (P2)** | Decay classes already approximate validity; explicit `valid_from`/`valid_to` is a 2-month build for marginal lift over decay. Do `ontology enforcement` (M-5) first |
| **D-1** Multi-provider data fusion | **OUT OF SCOPE here** | Tangential to KG/retrieval. Track in PLAN-0055 (backfill / source stability) instead |

---

## 2. Current-State Architecture (Corrected Map)

### 2.1 Retrieval Pipeline (verified 2026-04-30)

```
User Query  →  Validation (S9)  →  Cache check  →  Rate limit
   ↓
Step 4: Thread history load (last 6 messages)
   ↓
Step 5: Entity resolution (S6 NLP via /v1/resolve API)
   ↓
Step 6: Intent classification — DeepInfra Llama-3.1-8B-Instruct
        Output: intent ∈ {FACTUAL_LOOKUP, GENERAL, COMPARISON, FINANCIAL_DATA,
                          PORTFOLIO, REASONING, RELATIONSHIP, SIGNAL_INTEL}
        Plus: sub_questions[], rephrased_query
        Mapped to RetrievalPlan via _INTENT_TO_FLAGS in retrieval_plan_builder.py:37-126
   ↓
Step 7: HyDE expansion (SIGNAL_INTEL/FACTUAL/RELATIONSHIP/REASONING only)
        80-120-word hypothesis → embed → Valkey cache 30-min TTL
   ↓
Step 8: Parallel retrieval, 5.0s timeout each (8 conditional sources):
   ┌── 5A Chunk ANN (S6, top-20, cosine on bge-large 1024-dim)
   ├── 5B Relation summary ANN (S7, top-15, min_conf=0.30)         ← table currently empty
   ├── 5C Egocentric graph (S7, 1-hop, max 3 entities, min_conf=0.40)
   ├── 5D Claims search (S7, top-15, 90-day window, min_conf=0.50)
   ├── 5E Events search (S7, top-10, 180-day window)
   ├── 5F Contradictions (S7, top-3 per entity, max 3 entities)    ← currently empty
   ├── 5G Financial data (S3, fundamentals + earnings + quote)
   ├── 5H Portfolio context (S1, holdings + watchlist)
   └── 5I Cypher traversal (S7, gated KNOWLEDGE_GRAPH_CYPHER_ENABLED=false; AGE empty anyway)
   ↓
Step 9: Fusion + dedup
        fusion_score = ANN_score × recency_score × trust_weight
        recency_score = exp(-0.005 × days_old), 0.5 if no date  ← UNIFORM across sources
        trust_weight: SEC=0.95, eodhd_news=0.70, finnhub_news=0.65, default=0.60
        Top-30, dedup by doc_id (max fusion_score)
   ↓
Step 10: Graph enrichment (top-3 relations per entity, truncated to 200 chars)
   ↓
Step 11: Reranker — Cohere rerank-english-v3.0 PRIMARY (when COHERE_API_KEY set)
                    BGE Ollama FALLBACK (currently 100% failure: model not in Ollama registry)
                    Final fallback: fusion_score order
                    Top-12, 10s timeout
   ↓
Step 12: Context assembly + contradiction injection + prompt construction
   ↓
Step 13: LLM streaming — DeepSeek R1 Distill 32B via DeepInfra
         Fallback chain: OpenRouter → Groq → Ollama local
         Citation injection in stream
```

**Key files** (verified):
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` — parallel orchestration
- `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py:92` — Llama-3.1-8B intent
- `services/rag-chat/src/rag_chat/application/pipeline/hyde_expander.py:40` — `_HYDE_TTL_SECONDS = 1800`
- `services/rag-chat/src/rag_chat/application/pipeline/reranker.py:111-201` — Cohere primary + BGE fallback
- `services/rag-chat/src/rag_chat/application/pipeline/context_assembler.py:83` — `[:200]` truncation
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py:137` — `cypher_enabled: bool = False`
- `services/rag-chat/src/rag_chat/domain/entities/chat.py:27` — `math.exp(-0.005 * days_old)` uniform decay

### 2.2 Graph Generation Pipeline (verified)

```
S5 Document Stored → content.article.stored.v1 → S6 Article Processing Consumer
   │
   ├── Block 3 Sectioning: SECTION_TOKEN_LIMIT=450 (word-count, NOT GLiNER tokenizer)
   ├── Block 4 GLiNER NER: 11 classes, threshold 0.35, NMS IoU>0.5  ← infra/gliner/server.py
   ├── Block 5 Routing score: 8 signals, but only 3 dynamic (40% weight); 5 stuck:
   │            watchlist=0.0 (empty Valkey set), price_impact=0.0 (worker 401),
   │            source_reliability=0.5 hardcoded, novelty=1.0 hardcoded,
   │            document_type=0.5 hardcoded
   │            Tiers: SUPPRESS / LIGHT / MEDIUM / DEEP — DEEP threshold lowered 0.70→0.45 on 04-27
   ├── Block 6 Suppression gate
   ├── Block 7 Embeddings: BAAI/bge-large-en-v1.5 via DeepInfra, 1024-dim, 512-token chunks, 64 overlap
   ├── Block 8 Novelty gate (downgrades tier in memory; lost at commit because F-CRIT-06)
   ├── Block 9 Entity resolution: 4-stage cascade
   │            (1) exact alias  conf=1.0           ← misses 54% (F-CRIT-04: no self-alias)
   │            (2) ticker/ISIN  conf=0.95
   │            (3) fuzzy trigram >0.75  conf=sim×0.90
   │            (4) ANN HNSW definition  distance<0.35, margin>0.10
   │            Audit trail target: mention_resolutions table     ← 0 rows (F-CRIT-02)
   │            Provisional queue target: provisional_entity_queue ← 0 rows (F-MAJOR-10)
   │            7 of 11 entity classes have ZERO canonical seeds (F-CRIT-09/10)
   ├── Block 10 Deep LLM extraction — meta-llama/Meta-Llama-3.1-8B-Instruct via DeepInfra
   │            6K windows, 500-token overlap, signal threshold ≥0.80
   │            Prompt lists ALL mentions (resolved + unresolved)  ← bug source for F-CRIT-07
   │
   ├── Build raw_relations / raw_events / raw_claims (article_consumer.py:798-800)
   │            entity_id_by_ref built ONLY from resolved mentions (line 793-796)
   │            _build_raw_*: continue silently if endpoint unresolved (line 850-853)
   │            ← This is F-CRIT-07: ~100% of relations dropped for the 66% of docs with 0 resolved entities
   │
   └── Emit nlp.article.enriched.v1 → S7 Knowledge Graph

S7 Knowledge Graph (Enriched Article Consumer)
   │
   ├── Block 11 Relation type canonicalization (3-step): exact registry → ANN summary → propose new
   ├── Block 12a Graph materialization
   │     ├── Upsert relations (advisory lock per subject_id; increment evidence_count)
   │     ├── Insert relation_evidence (append-only, provenance: doc_id, chunk_id, evidence_text)
   │     ├── Insert events + event_entities
   │     └── Insert claims
   ├── Block 12b Contradiction detection (polarity-based on same subject + claim_type)
   │
   ├── Async workers:
   │     ├── definition_refresh.py (Gemini 3.1 Flash Lite)        ← description_provider="none" by default
   │     ├── narrative_refresh.py
   │     ├── fundamentals_refresh.py
   │     ├── embedding_refresh.py
   │     ├── summary.py (relation_summaries)                       ← 0 rows (downstream of F-CRIT-07)
   │     ├── confidence.py
   │     ├── contradiction_batch.py
   │     ├── provisional_enrichment.py
   │     └── age_sync_worker.py (15-min interval)                  ← never run; 0 nodes/edges
   │
   └── Post-commit: entity.dirtied.v1 → triggers downstream refreshes
                    llm_usage_log target                            ← 0 rows (F-CRIT-03)
```

### 2.3 Graph Traversal / Query Surface (verified)

| Endpoint | Mechanism | Status |
|---|---|---|
| `GET  /api/v1/entities/{id}/graph` | 1-hop SQL on `relations` table | Works on 18 seeded rows |
| `POST /api/v1/graph/cypher/neighborhood` | AGE BFS, 1-3 hops, 5s timeout | **503 by default** (`KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`); even when on, AGE empty |
| `POST /api/v1/graph/cypher/path` | AGE Dijkstra shortest path, 1-5 hops, confidence-product score | Same — flag-gated and empty |
| `POST /api/v1/search/relations` | ANN on `relation_summaries.summary_embedding` | Returns empty (table is empty) |
| `POST /api/v1/entities/similar` | ANN on `entity_embedding_state.fundamentals_ohlcv` + `competes_with` boost | Works for the 40 financial_instrument canonicals |
| `POST /api/v1/claims/search` | SQL temporal (entity_id, claim_type, date range) | Returns empty (claims table empty due to F-CRIT-07) |
| `GET  /api/v1/temporal-events` | SQL with `lifecycle_phase` computed at query-time, `region` filter | Has data (S4 worker 13D-6 economic events) |
| `GET  /api/v1/entities/{id}/contradictions` | SQL on `relation_contradiction_links` | Empty |

**Frontend visualization** (verified):
- `apps/worldview-web/components/graph/EntityGraph.tsx` — sigma.js + ForceAtlas2 WebGL, depth=2 (full Intelligence tab)
- `apps/worldview-web/components/graph/EntityGraphPanel.tsx` — SVG radial, depth=1 (sidebar)
- ADR-F-16 selected cytoscape.js + COSE-Bilkent for State C, but the migration has not happened in the codebase as of 2026-04-30. The current sigma.js implementation works adequately for 1-2 hop ego graphs; cytoscape will matter once Cypher is on and multi-hop subgraphs ship.

### 2.4 Data layer schema (verified)

- `canonical_entities` — 83 rows, 5 of 11 entity types covered
- `entity_aliases` — 38 rows (46% canonicals lack self-alias)
- `entity_mentions` — 18,695 rows (mention_resolutions audit trail empty for all)
- `entity_embedding_state` — 81/81 rows after BP-237 fix; 3 view-type HNSW partial indexes (definition, narrative, fundamentals_ohlcv)
- `relations` — **18 rows** (all hand-seeded 2026-04-24); HASH-partitioned 8 ways (`relations_p0..p7`); `partition_key GENERATED AS abs(hashtext(subject_entity_id::text)) % 8`
- `relation_evidence` — **0 rows**
- `relation_summaries` — **0 rows**
- `claims` — empty in production
- `temporal_events` — populated (S4 worker)
- `routing_decisions` — populated but missing `final_routing_tier`, `processing_path` columns (F-CRIT-06)
- `provisional_entity_queue` — empty (should contain unresolved mentions)
- `mention_resolutions` — empty
- `llm_usage_log` — empty
- AGE `worldview_graph` — 0 nodes / 0 edges (`MATCH (n) RETURN count(n)` = 0)

---

## 3. How the KG Should Be Handled (Future-State Architecture)

Three layers, each addressing one failure mode the 04-23 audit hinted at but didn't fully prescribe:

### 3.1 The integrity layer — `entity_id_by_ref` becomes a pre-extraction contract

The root pattern behind F-CRIT-07 is **prompt/lookup mismatch**: the prompt advertises a vocabulary and the post-parse lookup is a subset of that vocabulary. The fix is not to "add more error logging" — it is to make the contract structural.

**Proposed contract**:
1. The deep-extraction prompt **only** lists mention texts that have a non-null entity reference. For unresolved mentions, emit a *provisional* UUID at extraction time (not after) by inserting a row into `provisional_entity_queue` and using the queue row's id as the reference.
2. `entity_id_by_ref` is populated from **the same source set** as the prompt list. Any drift triggers a structural error, not a silent skip.
3. `_build_raw_relations` raises (or emits a `KGContractViolation` metric) on missing endpoint refs — never silently `continue`.
4. The pipeline tracks `kg_extraction_yield = relations_persisted / relations_extracted` as a Prometheus gauge with a 0.95 SLO.

**Implication**: Even with imperfect entity resolution, the KG accumulates *something* (a provisional graph, with edges that can later be re-pointed to canonicals when resolution improves). This is closer to the "wiki layer that LLMs maintain" idea — incremental, repairable, never destructive.

### 3.2 The compilation layer — entity summaries (Karpathy Wiki applied)

The 04-23 audit's M-1 stays: introduce an `entity_summaries` table populated by `EntitySummaryCompilationWorker` triggered on `entity.dirtied.v1`. Each row is a structured fact sheet:

```sql
CREATE TABLE entity_summaries (
  entity_id           UUID PRIMARY KEY REFERENCES canonical_entities(entity_id),
  schema_version      SMALLINT NOT NULL DEFAULT 1,
  one_liner           TEXT NOT NULL,            -- 200 chars, deterministic generation
  long_summary        TEXT NOT NULL,            -- 800-1200 chars, LLM-generated
  key_relations       JSONB NOT NULL,           -- top-10 by confidence × evidence_count
  key_claims          JSONB NOT NULL,           -- top-5 by polarity-weighted confidence
  key_events          JSONB NOT NULL,           -- top-5 most recent
  fundamentals_blob   JSONB,                    -- only for financial_instrument
  contradiction_count INTEGER NOT NULL DEFAULT 0,
  evidence_doc_ids    UUID[] NOT NULL,          -- provenance for "why this summary says X"
  embedding           VECTOR(1024) NOT NULL,    -- summary embedding for top-of-funnel ANN
  generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  prompt_version      VARCHAR(32) NOT NULL,
  llm_model_id        VARCHAR(64) NOT NULL,
  llm_cost_usd        NUMERIC(10,4)
);
CREATE INDEX entity_summaries_emb_hnsw ON entity_summaries USING hnsw (embedding vector_cosine_ops);
```

The RAG flow becomes: **Step 8.0 (new) — entity-summary lookup for any resolved entity in the query, returning the compiled fact sheet directly.** Chunk search is a fallback for queries whose intent is not entity-anchored. This is the single highest-leverage architectural change once Phase 1 is complete.

### 3.3 The retrieval layer — hybrid + measurable

Keep the 04-23 roadmap items S-1, M-2, M-3, M-4 mostly as written, but reorder:

1. **First**: build the eval framework (M-3, golden 50-100 query set with graded relevance) — without it, every other change is unmeasurable.
2. **Second**: hybrid retrieval (S-1 + M-2) — `tsvector` column on `chunks`, GIN index, RRF fusion `k=60` between BM25 rank and ANN rank. This unlocks precision queries.
3. **Third**: source-specific recency decay (S-3) and graph-context expansion to 500-800 chars (S-4).
4. **Fourth**: enable Cypher (S-2) **after** AGE shadow is populated by a manual full-sync run, then add path-relevance scoring (M-4) — `path_score = Σ(edge_conf × edge_type_weight × recency × log1p(evidence_count)) / path_length`.

---

## 4. Additional Enhancements Beyond the 04-23 Roadmap

The 04-23 audit was scoped to retrieval + graph. The 04-30 review surfaces enhancements adjacent to those:

| ID | Enhancement | Rationale | Priority |
|---|---|---|---|
| **E-1** | KG contract test in CI: end-to-end pipeline must produce ≥1 relation per article that has ≥2 resolved entities; fail PR if drops below 0.90 yield | Catches F-CRIT-07-class regressions structurally | P0 |
| **E-2** | Provisional graph with `entity_id IS PROVISIONAL` flag; relations to provisional entities are persisted, then re-pointed when entity resolves | Makes resolution failures non-destructive | P1 |
| **E-3** | Entity-class coverage health check: startup probe verifies ≥1 canonical per declared GLiNER class; emits `entity_class_coverage_ratio` gauge | Catches F-CRIT-09/10 immediately | P0 |
| **E-4** | Relation-type registry seeding from a vetted financial ontology (FIBO, schema.org Organization, sec.gov 10-K relationships) instead of LLM-proposed types | Reduces "proposed" rate, improves canonicalization | P2 |
| **E-5** | Subgraph cache: pre-materialize 2-hop subgraphs for the top 1000 entities by query frequency; refresh on `entity.dirtied.v1` | Eliminates Cypher latency for hot entities | P2 |
| **E-6** | LLM-as-judge eval supplement: monthly run of LLM scoring on retrieval results for queries the golden set doesn't cover | Cheap recall for emerging topics | P2 |
| **E-7** | Drift monitor on entity_resolution: alert if Stage-4 (ANN) confidence distribution shifts by Wasserstein > 0.1 vs 7-day baseline | Early warning for embedding model degradation | P2 |
| **E-8** | Citation→evidence backtrace UI: every RAG citation links back to the chunk + the relation evidence row that supported it | Solves P-3 (UX limitation) and aids debugging | P1 |
| **E-9** | Source-type filter exposed in the chat UI (FILINGS / NEWS / EARNINGS / PORTFOLIO) with intent-aware default | Solves P-4 (UX limitation) | P1 |
| **E-10** | Streaming graph reasoning: instead of one-shot Cypher, stream subgraph expansion to the LLM as it generates (multi-step ReAct) | Long-term differentiator for relationship queries | P3 |
| **E-11** | Cross-entity thematic grouping: derive sector / theme tags from the relation graph using community detection (Leiden algorithm); expose `?theme=semiconductors` filter | Solves D-4 (data limitation) | P3 |
| **E-12** | Search-as-you-type entity suggest: GIN trigram index on `canonical_entities.canonical_name` + `entity_aliases.alias_text`, exposed via `GET /api/v1/entities/suggest?q=...` (top-10) | Solves P-1 (UX limitation) | P2 |
| **E-13** | Fundamentals embeddings for non-equity asset classes: bonds (yield-curve descriptors), commodities (price-curve descriptors), currencies (volatility regime) | Solves D-2 (data limitation), enables broader screener | P3 |
| **E-14** | Relation evidence credibility decay: `evidence_credibility = trust_weight × recency × source_reliability_signal`; `relation.confidence` becomes a windowed weighted average rather than a simple mean | Better confidence calibration | P2 |
| **E-15** | Standardize "compiled knowledge" cache layer: Valkey-backed JSON of `entity_summary + top_relations + recent_news` with 1-hour TTL, key `kg:v1:entity:{id}`, used by both RAG and the entity page | Reduces query latency by ~40% on hot entities; couples RAG and frontend on the same compiled artifact | P1 |

---

## 5. Maturity Re-Rating

| Dimension | 04-23 Score | 04-30 Score | Rationale |
|---|---|---|---|
| Retrieval architecture (multi-stage, intent-routed) | 4.0 | 4.0 | Sound; verified in code |
| Retrieval data quality | 3.0 | 1.5 | Source-data gap (F-MAJOR-01) and broken pipeline produce sparse retrieval corpus |
| Entity resolution architecture | 4.5 | 4.0 | Cascade is correct; thresholds are correct |
| Entity resolution coverage | (not graded) | 1.5 | 5/11 classes; 46% missing self-alias; 66% docs unresolved |
| KG generation pipeline | 4.0 | 1.5 | F-CRIT-07 destroys all output |
| KG traversal | 2.5 | 1.5 | Code exists; AGE empty; Cypher disabled |
| Eval & observability | 1.0 | 1.0 | Still no NDCG/MRR/P@k; audit tables unwritten |
| Operational hygiene | 3.0 | 2.5 | Models externalized (good); 401 worker, empty Valkey set, hardcoded loggers (bad) |
| **Overall** | **3.0 / 5.0** | **2.0 / 5.0** | Architecture is genuinely strong; integration debt is the binding constraint |

The 04-23 score is restored to ~3.5/5.0 once Phase 1 of the remediation plan ships, and approaches 4.0/5.0 with Phase 2.

---

## 6. Detailed Implementation Plan

The execution artifacts are split:

- **PLAN-0057** (`docs/plans/0057-news-intelligence-pipeline-quality-repair-plan.md` per current TRACKING.md) owns Phase 1 — the pipeline-integrity fixes and canonical-seeding work that close F-CRIT-02..09. This plan was created from the 04-29 audit and is the right home for Wave A and Wave B.
- **PLAN-0058** (`docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md`, new) owns Phase 2 + Phase 3 — eval framework, hybrid retrieval, knowledge compilation layer, Cypher activation, ontology, and dashboards. Wave C may begin in parallel with PLAN-0057 (the eval baseline can usefully measure the pre-fix state).

Together: 8 waves across 3 phases with strict dependency ordering and validation gates per wave. Highlights:

- **Phase 1 — Stop the Bleed** (Wave A: critical fixes; Wave B: coverage seeding) — ~5 days
- **Phase 2 — Make it Measurable** (Wave C: eval framework; Wave D: hybrid retrieval; Wave E: routing & decay hardening) — ~3 weeks
- **Phase 3 — Strategic Uplift** (Wave F: knowledge compilation layer; Wave G: Cypher activation + path scoring; Wave H: ontology + temporal + observability dashboard) — ~6 weeks

Each wave has explicit acceptance criteria (e.g., Wave A's exit: `kg_extraction_yield ≥ 0.90` Prometheus gauge holds for 24h; `mention_resolutions` row count > 1000; AGE node count > 0).

---

## 7. Compounding Updates

This investigation triggered the following knowledge-base updates (applied alongside the plan):

- **`docs/BUG_PATTERNS.md`** — Added BP-292 *"Prompt/Lookup Mismatch: silent drop when prompt advertises values absent from the call-site lookup"* (root pattern of F-CRIT-07).
- **`docs/BUG_PATTERNS.md`** — Added BP-293 *"Producer-side resolved-only lookup destroys end-to-end pipeline output without any error signal"* (S6→S7 boundary specific case).
- **`docs/BUG_PATTERNS.md`** — Added BP-294 *"Schema-defined audit table never written: hardcoded `usage_logger=None` / missing `*_repo.add_batch()` calls"*.
- **`RULES.md`** — Proposed R28: *"Pipeline boundary contracts: any data crossing a Kafka topic must round-trip through a contract test that fails on silent drops; producer-side lookup tables must be subset-validated against the prompts/extractors that populate them."* (Adoption pending.)
- **`docs/MASTER_PLAN.md`** — Section 7 "Knowledge Graph" updated with Phase 1/2/3 framing once PLAN-0057 + PLAN-0058 start shipping.
- **`services/nlp-pipeline/.claude-context.md`** — Pitfall added: *"Block 9 → Block 10 boundary: deep-extraction prompt must list ONLY mentions whose ID appears in `entity_id_by_ref`; never list a mention you cannot map back."*
- **`services/knowledge-graph/.claude-context.md`** — Pitfall added: *"AGE shadow worker requires manual `LOAD 'age'`-tested initial sync; cron alone will not bootstrap an empty graph if the watermark key is missing."*

---

**Final note**: The 2026-04-23 audit should remain as a historical record (its architectural reasoning is still valuable as a "what good looks like" reference), but every operational claim it makes must be read in light of this revision. Until PLAN-0057 ships, do not describe the platform as having a "production-grade" knowledge graph. Describe it as having a *production-grade design with a remediation sprint pending*.
