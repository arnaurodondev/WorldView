# Investigation Report: Retrieval, Graph Generation & Graph Traversal Architecture Audit

> **⚠ SUPERSEDED 2026-04-30** — by `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md`. Several material claims in this document are factually wrong or out-of-date as of 2026-04-30:
> - Embedding model is now `BAAI/bge-large-en-v1.5` via DeepInfra, not nomic-embed-text (changed 2026-04-27)
> - Deep-extraction LLM is `meta-llama/Meta-Llama-3.1-8B-Instruct`, not Qwen2.5-7B (changed 2026-04-27)
> - Intent classifier is DeepInfra Llama-3.1-8B, not Qwen2.5:3b
> - Reranker is Cohere `rerank-english-v3.0` primary + BGE fallback, not BGE primary
> - The "production-grade entity resolution" framing is **wrong**: 7 of 11 GLiNER classes have zero canonical seeds; 66% of documents have zero resolved entities; the `entity_id_by_ref`/`_build_raw_relations` boundary silently drops ~100% of LLM extractions for those documents (F-CRIT-07 in 04-29 deep-dive); `mention_resolutions` and `llm_usage_log` audit tables are empty.
> - The "evidence-backed graph materialization" framing is **wrong**: production rows in `relations` = 18 (all hand-seeded 2026-04-24); `relation_evidence`, `relation_summaries`, AGE shadow graph all have 0 rows.
>
> The architectural roadmap (BM25 + RRF, knowledge compilation, eval framework, Cypher activation, ontology) is still directionally correct and feeds PLAN-0057 (Phase 1) + PLAN-0058 (Phase 2 + 3). Read the revised audit for the current picture.

**Date**: 2026-04-23
**Investigator**: Claude (investigation skill)
**Severity**: MEDIUM (no production outage — architectural gap analysis)
**Status**: SUPERSEDED 2026-04-30 — see header
**External References**: Karpathy LLM Wiki Gist, Elastic IR Reference

---

## 1. Executive Summary

### Top Strengths

1. **Sophisticated multi-stage RAG pipeline** — 13-step pipeline with intent classification (Qwen2.5:3b), HyDE expansion, 9 parallel retrieval sources, cross-encoder reranking (BGE), fusion scoring with trust weights and recency decay. This is considerably more advanced than a naive RAG implementation.

2. **Production-grade entity resolution** — 4-stage cascade (exact alias → ticker/ISIN → fuzzy trigram → ANN HNSW) with auditable resolution trail, provisional entity queue, and the critical invariant that unresolved mentions are never discarded.

3. **Evidence-backed graph materialization** — Append-only relation evidence, advisory locking for concurrent upserts, contradiction detection, and provenance tracking from source document through extraction to graph edge.

4. **Intent-driven retrieval routing** — 8 query intents map to different source combinations, avoiding wasteful retrieval for focused queries (e.g., FINANCIAL_DATA skips chunks, RELATIONSHIP activates Cypher).

5. **Graceful degradation throughout** — Circuit breakers on retrieval sources, 5s timeouts per source, fusion-score fallback when reranker fails, keyword heuristic fallback when Qwen is unreachable.

### Top Critical Weaknesses

1. **Zero lexical/BM25 search** — The entire retrieval stack is purely semantic (vector ANN). No keyword search, no hybrid retrieval. Queries with exact terms ("SEC Form 10-K filing #12345") rely entirely on embedding similarity, which is fundamentally wrong for precision lookups.

2. **No knowledge compilation layer** — Following Karpathy's framework, the system re-discovers answers from raw chunks on every query. There is no materialized knowledge layer (entity summaries, synthesized fact sheets, compiled Q&A pairs) that would allow "query the compiled wiki" instead of "re-search raw documents every time."

3. **Graph traversal is disabled by default and primitive** — Cypher (Apache AGE) is feature-flagged off. When enabled, it offers only 1-3 hop BFS and shortest-path with confidence-product scoring. No path ranking, no weighted traversal, no temporal graph queries.

4. **No retrieval quality evaluation** — Zero offline metrics (NDCG, MRR, precision@k). No retrieval quality benchmarks. No regression gates. The system cannot objectively measure whether changes improve or degrade retrieval quality.

5. **Single market data provider** — 3 of 4 market data adapters are stubs. EODHD is a single point of failure for all financial data.

### Overall Maturity Rating: **3.0 / 5.0 — Advanced Prototype**

The system has strong architectural bones (hexagonal architecture, event-driven pipelines, multi-stage retrieval) but critical gaps in retrieval completeness (no lexical search, no knowledge compilation), graph reasoning (disabled Cypher, no multi-hop intelligence), and operational confidence (no quality metrics, no evaluation framework).

---

## 2. External Reference Synthesis

### 2.1 Karpathy LLM Wiki Pattern

**Core idea**: Three-layer knowledge architecture:
```
Raw Sources (immutable) → Wiki Layer (LLM-maintained) → Schema (configuration)
```

**Key principle**: "Compile knowledge once at ingest time, query the compiled wiki forever, rather than re-discovering from raw documents on every query."

**What is directly applicable to worldview:**

| Karpathy Concept | Worldview Mapping | Gap |
|---|---|---|
| **Ingest-time compilation** | Routing score, entity extraction, claim extraction exist | No entity summaries, no compiled fact sheets, no synthesized Q&A |
| **Wiki layer (materialized knowledge)** | `relation_summaries` table exists but is underutilized | Not queryable as standalone knowledge; only used as RAG enrichment |
| **Index.md (navigable catalog)** | `canonical_entities` + aliases provide entity navigation | No topic-level index, no cross-entity thematic grouping |
| **Log.md (append-only timeline)** | `relation_evidence` is append-only with timestamps | Not surfaced for temporal reasoning or change tracking |
| **Lint (contradiction detection)** | `Block 12b` contradiction detection exists | Only polarity-based; no semantic consistency checking across the knowledge base |
| **Schema (structural conventions)** | `relation_type_registry` canonicalizes relation types | No ontology enforcement; invalid triples (e.g., "person purchases commodity") not filtered |

**What is NOT applicable**:
- Karpathy's pattern assumes ~200 pages navigable via a single index. Worldview's knowledge graph has thousands of entities and unbounded documents — embedding-based retrieval is necessary, not optional.
- The "single-agent maintaining a wiki" model doesn't scale to real-time financial data. Worldview's event-driven pipeline is the correct architecture for high-throughput ingest.

**Critical takeaway**: The biggest gap is the **missing knowledge compilation layer**. The system extracts entities, relations, and claims at ingest time (good) but does NOT compile them into queryable entity summaries or synthesized fact sheets. Every RAG query re-discovers from raw chunks. Adding a materialized entity knowledge layer would be the single highest-impact improvement.

### 2.2 Elastic IR Reference

**Core concepts mapped to worldview:**

| IR Concept | Worldview Status | Impact |
|---|---|---|
| **BM25 lexical search** | ABSENT — zero `tsvector`/`ts_rank` usage in any service | Critical gap for precision queries |
| **Hybrid retrieval (lexical + semantic)** | ABSENT — purely semantic (vector ANN only) | Missing entire retrieval modality |
| **Vector Space Model** | IMPLEMENTED — pgvector HNSW with cosine distance | Solid foundation |
| **Relevance feedback** | ABSENT — no click-through or user feedback loop | Cannot learn from user behavior |
| **Query understanding** | PARTIAL — intent classification + HyDE, no spell-check or synonym expansion | Good foundation, missing completeness |
| **Evaluation metrics (NDCG, MRR, P@k)** | ABSENT — no offline or online metrics | Cannot measure quality |
| **Faceted search** | PARTIAL — entity_id, source_type, date_range filtering; no user-facing facets | Backend filters exist but not exposed as facets |
| **Latent Semantic Indexing** | N/A — embedding models supersede LSI | Correctly using modern approach |

**What is NOT applicable**:
- Boolean model (AND/OR/NOT) is too rigid for financial intelligence queries where partial relevance matters.
- Elasticsearch-specific features (ELSER) are vendor-locked; pgvector + PostgreSQL full-text search provides equivalent capability within the existing stack.

**Critical takeaway**: PostgreSQL already has `tsvector`, `ts_rank`, `plainto_tsquery`, and GIN indexes for full-text search. Adding BM25-style lexical search requires zero new infrastructure — only SQL additions to existing chunk/document queries.

---

## 3. Current-State Architecture Map

### 3.1 Retrieval Pipeline Map

```
User Query
    │
    ├─── Step 1-3: Validation, cache check, rate limit
    │
    ├─── Step 4: Thread history load (last 6 messages)
    │
    ├─── Step 5: Entity resolution (S6 NLP pipeline)
    │    └─── resolve_entities(query_text) → ResolvedEntity[]
    │
    ├─── Step 6: Intent classification (Qwen2.5:3b or keyword fallback)
    │    └─── Output: intent, sub_questions[], rephrased_query
    │    └─── Intent → RetrievalPlan (_INTENT_TO_FLAGS matrix)
    │
    ├─── Step 7: HyDE expansion (for SIGNAL_INTEL/FACTUAL/RELATIONSHIP/REASONING)
    │    └─── Generate 80-120 word hypothesis → embed → cache 30min
    │
    ├─── Step 8: Parallel retrieval (9 sources, 5s timeout each)
    │    ├─── 5A: Chunk ANN search (S6, top-20, cosine on 1024-dim nomic-embed-text)
    │    ├─── 5B: Relation summary search (S7, top-15, min_conf=0.30)
    │    ├─── 5C: Egocentric graph (S7, 1-hop, max 3 entities, min_conf=0.40)
    │    ├─── 5D: Claims search (S7, top-15, 90-day window, min_conf=0.50)
    │    ├─── 5E: Events search (S7, top-10, 180-day window)
    │    ├─── 5F: Contradictions (S7, top-3 per entity, max 3 entities)
    │    ├─── 5G: Financial data (S3, fundamentals + earnings + quote)
    │    ├─── 5H: Portfolio context (S1, holdings + watchlist)
    │    └─── 5I: Cypher traversal (S7, DISABLED by default, 1-3 hop)
    │
    ├─── Step 9: Fusion + dedup (by doc_id, keep max fusion_score, top-30)
    │    └─── fusion_score = ANN_score × recency_score × trust_weight
    │    └─── recency_score = exp(-0.005 × days_old), 0.5 if no date
    │    └─── trust_weight: SEC=0.95, earnings=0.95, news=0.60-0.70
    │
    ├─── Step 10: Graph enrichment (top-3 relations per entity attached to chunks)
    │
    ├─── Step 11: BGE reranker (cross-encoder, top-12, 10s timeout)
    │    └─── Fallback: fusion_score if reranker fails
    │
    ├─── Step 12: Context assembly + contradiction injection + prompt construction
    │
    └─── Step 13: LLM streaming (DeepSeek R1 Distill 32B) + citation injection
```

**Key files:**
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` — parallel retrieval (9 sources)
- `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` — Qwen2.5:3b intent classification
- `services/rag-chat/src/rag_chat/application/pipeline/hyde_expander.py` — HyDE hypothesis generation
- `services/rag-chat/src/rag_chat/application/pipeline/reranker.py` — BGE cross-encoder reranking
- `services/rag-chat/src/rag_chat/application/pipeline/fusion.py` — score fusion + graph enrichment
- `services/rag-chat/src/rag_chat/domain/entities/chat.py:18-27` — recency decay formula

### 3.2 Graph Generation Pipeline Map

```
Document Stored (S5)
    │
    ├─── content.article.stored.v1 (Kafka)
    │
    └─── S6 NLP Pipeline (Article Processing Consumer)
         │
         ├─── Block 3: Sectioning (sentence-aware, 450-word sections)
         ├─── Block 4: GLiNER NER (11 entity classes, threshold 0.35, NMS IoU>0.5)
         ├─── Block 5: Routing score (8 signals → SUPPRESS/LIGHT/MEDIUM/DEEP tier)
         ├─── Block 6: Suppression gate (SUPPRESS→halt, LIGHT→section-embeddings-only)
         ├─── Block 7: Embeddings (nomic-embed-text, 1024-dim, 512-token chunks, 64-overlap)
         ├─── Block 8: Novelty gate (similarity check vs existing entity embeddings)
         ├─── Block 9: Entity resolution (4-stage cascade, audit trail)
         │    ├─── Stage 1: Exact alias (confidence=1.0)
         │    ├─── Stage 2: Ticker/ISIN (confidence=0.95)
         │    ├─── Stage 3: Fuzzy trigram >0.75 (confidence=sim×0.90)
         │    └─── Stage 4: ANN HNSW definition embeddings (distance<0.35, margin>0.10)
         ├─── Block 10: Deep LLM extraction (Qwen2.5-7B, 6K windows, 500 overlap)
         │    └─── Output: events, claims, relations (signal threshold ≥0.80)
         │
         └─── Emit: nlp.article.enriched.v1 → S7

S7 Knowledge Graph (Enriched Article Consumer)
    │
    ├─── Block 11: Relation type canonicalization (3-step: exact → ANN → proposal)
    ├─── Block 12a: Graph materialization
    │    ├─── Upsert relations (advisory lock, increment evidence_count)
    │    ├─── Insert relation_evidence (append-only, provenance tracking)
    │    ├─── Insert events + event_entities
    │    └─── Insert claims
    ├─── Block 12b: Contradiction detection (opposite polarity on same subject+claim_type)
    │
    └─── Post-commit: entity.dirtied.v1 → triggers confidence/summary/embedding refresh
```

**Key files:**
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/ner.py` — GLiNER NER
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` — 4-stage cascade
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/embeddings.py` — chunking + embedding
- `services/knowledge-graph/src/knowledge_graph/application/blocks/canonicalization.py` — relation type canonicalization
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py` — graph materialization
- `infra/gliner/server.py` — GLiNER HTTP server

### 3.3 Graph Traversal / Query Map

```
Query Entry Points:
    │
    ├─── GET /api/v1/entities/{id}/graph         → 1-hop SQL (relation.py:302-353)
    ├─── POST /api/v1/graph/cypher/neighborhood   → Multi-hop AGE BFS (1-3 hops, 5s timeout)
    ├─── POST /api/v1/graph/cypher/path           → AGE Dijkstra shortest path (1-5 hops)
    ├─── POST /api/v1/search/relations            → ANN on relation_summaries (pgvector)
    ├─── POST /api/v1/entities/similar            → ANN on fundamentals_ohlcv + competes_with boost
    ├─── POST /api/v1/claims/search               → SQL temporal (date range, entity, claim_type)
    ├─── GET /api/v1/temporal-events              → SQL temporal (lifecycle phase computation)
    └─── GET /api/v1/entities/{id}/contradictions → SQL contradiction links

Data Layer:
    ├─── canonical_entities (entity_id, canonical_name, entity_type, ticker, ISIN)
    ├─── entity_aliases (normalized_alias_text, pg_trgm for fuzzy)
    ├─── entity_embedding_state (1024-dim, 3 view types, HNSW partial indexes)
    ├─── relations (subject→object, canonical_type, decay_class, confidence, evidence_count)
    │    └─── HASH-partitioned into 8 partitions
    ├─── relation_evidence (append-only, provenance: doc_id, chunk_id, evidence_text)
    ├─── relation_summaries (summary_embedding for ANN, is_current flag)
    ├─── claims (claim_type, polarity, confidence, entity_id)
    ├─── temporal_events (event_type, scope, region, lifecycle phase)
    └─── entity_mentions (mention_text, confidence, resolution outcome)

Frontend Visualization:
    ├─── EntityGraph.tsx — sigma.js WebGL (ForceAtlas2, multi-hop depth=2)
    └─── EntityGraphPanel.tsx — SVG radial (compact sidebar, depth=1)
```

---

## 4. Hard Gap Analysis

### 4.1 Retrieval: Current vs Ideal

| Dimension | Current State | Ideal State | Gap Severity |
|---|---|---|---|
| **Lexical search** | ABSENT — zero BM25/tsvector usage | Hybrid (BM25 + ANN) with RRF fusion | **CRITICAL** |
| **Knowledge compilation** | Raw chunk retrieval only | Materialized entity summaries + compiled fact sheets | **CRITICAL** |
| **Query expansion** | HyDE for 4 intents, no synonyms/spell-check | HyDE + synonym expansion + spell-correct + entity linking in query | **HIGH** |
| **Evaluation framework** | Zero metrics | Offline (NDCG@10, MRR, P@5) + online (click-through, dwell time) | **CRITICAL** |
| **Hybrid scoring** | Fusion = ANN × recency × trust | RRF(BM25_rank, ANN_rank) × recency × trust × source_quality | **HIGH** |
| **display_relevance_score** | IMPLEMENTED in news_query.py (0.5×market + 0.4×llm + 0.1×routing) | Already solid | LOW |
| **Freshness handling** | Single decay rate (-0.005) for all sources | Source-specific decay (fast for news, slow for filings) | **MEDIUM** |
| **Reranking** | BGE cross-encoder, top-12 | Correct approach; needs evaluation to tune thresholds | **LOW** |
| **Caching** | HyDE cached 30min; no query embedding cache | Tiered caching: query embeddings, popular entity contexts, hot chunks | **MEDIUM** |
| **User feedback** | ABSENT | Implicit (click-through, copy) + explicit (thumbs up/down) | **MEDIUM** |

### 4.2 Graph Generation: Current vs Ideal

| Dimension | Current State | Ideal State | Gap Severity |
|---|---|---|---|
| **Entity extraction** | GLiNER v2.1, 11 classes, NMS dedup | Good foundation; needs confidence calibration per class | **LOW** |
| **Entity resolution** | 4-stage cascade with audit trail | Strong; needs temporal alias weighting and cross-EODHD linking | **LOW** |
| **Relation extraction** | Qwen2.5-7B windowed extraction | Good; needs triple validation (ontology enforcement) | **MEDIUM** |
| **Relation canonicalization** | 3-step (exact → ANN → proposal) | Solid; needs feedback loop from proposed → registry | **MEDIUM** |
| **Knowledge synthesis** | ABSENT | Entity-level compiled summaries, auto-maintained fact sheets | **CRITICAL** |
| **Ontology enforcement** | ABSENT — no triple validation | Subject/predicate/object type constraints (e.g., person can't "manufactures") | **MEDIUM** |
| **Temporal validity** | Decay classes (PERMANENT→EPHEMERAL) but no start/end dates | Explicit validity windows on relations | **MEDIUM** |
| **Provenance quality** | Evidence trail with doc_id, chunk_id, text | Good foundation; needs source credibility feedback | **LOW** |

### 4.3 Graph Traversal / Reasoning: Current vs Ideal

| Dimension | Current State | Ideal State | Gap Severity |
|---|---|---|---|
| **Multi-hop queries** | AGE Cypher 1-3 hops, DISABLED by default | Enabled, with path relevance ranking and weighted edges | **HIGH** |
| **Path ranking** | Confidence product only (naive) | Weighted by edge type importance, evidence density, recency | **HIGH** |
| **Temporal traversal** | ABSENT | Graph snapshots at time T, temporal path constraints | **MEDIUM** |
| **Community detection** | ABSENT | Sector/theme clustering for contextual graph reasoning | **MEDIUM** |
| **Subgraph extraction** | Egocentric 1-hop only | Multi-entity subgraph with configurable depth/filters | **MEDIUM** |
| **Query expressiveness** | Fixed patterns (neighborhood, shortest path) | User-composable graph queries via structured API | **LOW** |
| **Graph-RAG integration** | 200-char relation summary appended to chunks | Full subgraph context injection with traversal-based expansion | **HIGH** |

---

## 5. Limitation Catalog

### 5.1 Technical Limitations

| ID | Limitation | Evidence | Impact |
|---|---|---|---|
| **T-1** | No lexical search: zero `tsvector`/`ts_rank` in any service SQL | `grep -r "tsvector\|ts_rank\|BM25" services/` returns only SEC EDGAR adapter (metadata, not search) | Exact-term queries (ticker lookup, filing numbers, proper nouns) degrade to semantic approximation |
| **T-2** | No knowledge compilation: raw chunks re-searched on every query | No "entity_summary" or "compiled_knowledge" table in any migration | Every query pays full retrieval cost; no accumulated intelligence |
| **T-3** | Cypher disabled by default: `KNOWLEDGE_GRAPH_CYPHER_ENABLED=false` | `retrieval_plan_builder.py` gates `use_cypher` with feature flag | Multi-hop reasoning not available in production |
| **T-4** | Single embedding model: nomic-embed-text for all content | `enhanced_chunk_search.py:290` hardcoded | No domain-specific financial embeddings; general-purpose model may miss financial nuance |
| **T-5** | Fixed recency decay for all source types | `chat.py:26` uses uniform -0.005 coefficient | SEC filings (valid for years) penalized same as breaking news (stale in hours) |
| **T-6** | No query embedding cache | HyDE cached, but direct query embeddings recomputed every time | Repeated/similar queries pay full embedding cost |
| **T-7** | Graph enrichment limited to 200-char summary | `context_assembler.py:83` truncates to 200 chars | Graph context severely compressed; multi-hop context lost |
| **T-8** | No implicit relation inference | "A founded B" does NOT infer "B founded_by A" | Graph queries return asymmetric results depending on traversal direction |

### 5.2 Data Limitations

| ID | Limitation | Evidence | Impact |
|---|---|---|---|
| **D-1** | 3/4 market data providers are stubs | `alpha_vantage.py:27`, `polygon.py:27` raise `ProviderUnavailable` | Single provider dependency; no failover for financial data |
| **D-2** | Non-financial entities lack fundamentals embeddings | Only `financial_instrument` gets `fundamentals_ohlcv` embedding | Macro indicators, commodities, people have reduced retrieval quality |
| **D-3** | No entity disambiguation for ambiguous names | "Apple" = company vs other meanings; all treated equally | False entity resolution possible |
| **D-4** | No cross-entity thematic grouping | No sector/industry/theme tags on entities | Cannot query "all semiconductor companies" without individual entity lookup |
| **D-5** | Asset class coverage is equity/bond-centric | No crypto, derivatives, commodities, or FX native adapters | Coverage gaps for multi-asset intelligence |

### 5.3 Operational Limitations

| ID | Limitation | Evidence | Impact |
|---|---|---|---|
| **O-1** | Zero retrieval quality metrics | No NDCG, MRR, P@k in codebase | Cannot measure or gate quality changes |
| **O-2** | No embedding quality monitoring | No NULL rate, drift detection, or staleness metrics | Silent degradation when embeddings go stale |
| **O-3** | No provider quota tracking in Prometheus | EODHD demo-tier usage not surfaced | Quota exhaustion causes silent failures |
| **O-4** | NLP pipeline mostly unobservable | No GLiNER mention counts, extraction failure rates, or entity resolution latency | Blind to extraction quality regressions |
| **O-5** | NewsAPI quota depends on Valkey being up | `config.py:134` — cache miss = no quota enforcement | Over-fetching risk when cache is down |

### 5.4 Product/UX Limitations Caused by Backend Constraints

| ID | Limitation | Root Cause | User Impact |
|---|---|---|---|
| **P-1** | No search-as-you-type for entity names | No prefix-tree or trigram index exposed to frontend | User must type full entity name |
| **P-2** | Graph view limited to 1-hop in sidebar | Backend only serves egocentric 1-hop to sidebar component | Users can't explore relationship chains |
| **P-3** | No "why" explanation for RAG answers | Graph enrichment is 200 chars; no provenance surfaced | Users can't trace reasoning path |
| **P-4** | No filtering by source type in chat | Source types used internally but not exposed as user controls | Users can't say "only use SEC filings" |
| **P-5** | Stale answers for fast-moving topics | Uniform recency decay, no real-time freshness boost | Breaking news equally weighted to week-old articles |

---

## 6. Improvement Portfolio

### 6.1 Short-Term Fixes (High ROI, Low Complexity)

| # | Improvement | Effort | Impact | Evidence |
|---|---|---|---|---|
| **S-1** | Add PostgreSQL full-text search (BM25-style) to chunk search | 2-3 days | **CRITICAL** — enables hybrid retrieval | Add `tsvector` column to `chunks` table, GIN index, `ts_rank` in `chunk_search.py` SQL, RRF fusion with ANN score |
| **S-2** | Enable Cypher traversal by default | 1 day | **HIGH** — unlocks multi-hop graph context in RAG | Flip `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`, add monitoring, tune 5s timeout |
| **S-3** | Source-specific recency decay | 1 day | **MEDIUM** — SEC filings stop being penalized | Add `source_decay_rate` lookup in `compute_recency_score()`: SEC=0.0005, news=0.02, earnings=0.001 |
| **S-4** | Expand graph context injection beyond 200 chars | 1 day | **MEDIUM** — richer graph context in RAG answers | Increase context_assembler limit to 500-800 chars, include relation type and evidence count |
| **S-5** | Add query embedding cache (Valkey, 1h TTL) | 1 day | **LOW** — reduces embedding latency for repeat queries | Cache key: `rag:v1:qemb:{sha256(text)}`, same pattern as HyDE cache |
| **S-6** | Add basic retrieval quality metrics | 2 days | **HIGH** — enables measurement | Log `retrieval_score_distribution`, `reranker_position_changes`, `source_contribution_ratio` to Prometheus |

### 6.2 Medium-Term Architecture Upgrades (1-3 Weeks Each)

| # | Improvement | Effort | Impact | Description |
|---|---|---|---|---|
| **M-1** | Materialized entity knowledge layer (Karpathy Wiki) | 2 weeks | **CRITICAL** | New `entity_summaries` table, `EntitySummaryCompilationWorker` triggered by `entity.dirtied.v1`. Compiles all evidence, relations, claims, and financials into a structured entity fact sheet. RAG queries this first before chunk search. |
| **M-2** | Hybrid retrieval with RRF fusion | 1 week | **HIGH** | After S-1 (full-text search), implement Reciprocal Rank Fusion: `RRF(d) = 1/(k + rank_bm25(d)) + 1/(k + rank_ann(d))` with k=60. Replace pure ANN with hybrid in `chunk_search.py`. |
| **M-3** | Offline evaluation framework | 2 weeks | **CRITICAL** | Build golden query set (50-100 queries with annotated relevant documents). Script to compute NDCG@10, MRR, P@5. Run as CI gate on retrieval pipeline changes. |
| **M-4** | Path relevance scoring for Cypher | 1 week | **HIGH** | Replace confidence-product with weighted score: `path_score = Σ(edge_conf × edge_type_weight × recency × log1p(evidence_count)) / path_length`. Add edge-type importance weights. |
| **M-5** | Ontology enforcement for relation triples | 1 week | **MEDIUM** | Add `valid_subject_types` and `valid_object_types` columns to `relation_type_registry`. Filter invalid triples in Block 12a before materialization. |
| **M-6** | Entity-level observability dashboard | 1 week | **MEDIUM** | Prometheus metrics: embedding NULL rates, resolution confidence distribution, extraction yield by source, provider quota utilization. Grafana dashboard. |

### 6.3 Long-Term Strategic Redesign (1-3 Months Each)

| # | Improvement | Effort | Impact | Description |
|---|---|---|---|---|
| **L-1** | Knowledge graph reasoning engine | 2 months | **HIGH** | Replace ad-hoc Cypher queries with a structured reasoning engine: subgraph extraction → path enumeration → evidence aggregation → confidence-weighted answer synthesis. Supports multi-hop questions like "which companies in my portfolio have supply chain exposure to TSMC through their semiconductor suppliers?" |
| **L-2** | Financial domain embedding model | 1 month | **MEDIUM** | Fine-tune or adopt a domain-specific embedding model (e.g., FinBERT-based) for financial text. Evaluate against nomic-embed-text on financial similarity benchmarks. Run dual-embedding migration. |
| **L-3** | Relevance feedback loop | 1 month | **MEDIUM** | Implicit signals (click-through, copy, dwell time) and explicit signals (thumbs up/down) feed into a lightweight learning-to-rank model that personalizes retrieval over time. |
| **L-4** | Multi-provider data fusion | 2 months | **HIGH** | Implement Alpha Vantage and Polygon adapters. Build provider health monitoring with automatic failover. Add cross-provider data reconciliation for price/fundamental data. |
| **L-5** | Temporal knowledge graph | 2 months | **MEDIUM** | Add explicit validity windows (`valid_from`, `valid_to`) to relations. Support temporal graph queries ("who was CEO of X in 2024?"). Enable graph snapshots for point-in-time reasoning. |

---

## 7. Prioritized Implementation Roadmap

### P0 — Must Do (blocks quality claims) — Weeks 1-3

| Task | Description | Dependency | Complexity |
|---|---|---|---|
| **S-1: Add BM25/full-text search** | `tsvector` column + GIN index on `chunks`, hybrid SQL in `chunk_search.py` | Alembic migration (S6 nlp_db) | 2-3 days |
| **M-3: Offline evaluation framework** | Golden query set + NDCG@10/MRR/P@5 scoring script | None | 2 weeks |
| **S-6: Retrieval quality metrics** | Prometheus metrics for score distributions, source contributions | None | 2 days |
| **S-2: Enable Cypher by default** | Flip feature flag, add timeout monitoring | Validate AGE stability | 1 day |

**Expected impact**: Hybrid retrieval alone should improve precision on exact-term queries by 30-50%. Evaluation framework gates all subsequent changes. Cypher enables graph-aware RAG for relationship queries.

### P1 — Should Do (high user impact) — Weeks 4-8

| Task | Description | Dependency | Complexity |
|---|---|---|---|
| **M-1: Entity knowledge compilation layer** | `entity_summaries` table + compilation worker + RAG integration | P0 complete (needs eval to measure) | 2 weeks |
| **M-2: Hybrid RRF fusion** | Replace pure ANN with `RRF(BM25, ANN)` in chunk search | S-1 complete | 1 week |
| **M-4: Path relevance scoring** | Weighted path score in Cypher queries | S-2 complete | 1 week |
| **S-3: Source-specific recency decay** | Per-source decay rates | None | 1 day |
| **S-4: Expand graph context injection** | Larger context window in context_assembler | S-2 complete | 1 day |

**Expected impact**: Entity summaries eliminate redundant chunk retrieval for known entities. RRF hybrid search balances precision and recall. Path scoring makes multi-hop results meaningful.

### P2 — Nice to Have (strategic value) — Weeks 9-16+

| Task | Description | Dependency | Complexity |
|---|---|---|---|
| **M-5: Ontology enforcement** | Valid type constraints on relation triples | None | 1 week |
| **M-6: Observability dashboard** | Entity-level metrics + Grafana | None | 1 week |
| **L-1: Graph reasoning engine** | Structured multi-hop reasoning | M-4 complete | 2 months |
| **L-4: Multi-provider data fusion** | Alpha Vantage + Polygon implementation | None | 2 months |
| **L-2: Financial embedding model** | Domain-specific embeddings | M-3 complete (needs eval) | 1 month |
| **L-3: Relevance feedback loop** | User signal collection + learning-to-rank | M-3 complete | 1 month |
| **L-5: Temporal knowledge graph** | Validity windows + temporal queries | M-5 complete | 2 months |

---

## 8. Evaluation Framework

### 8.1 Offline Metrics

| Metric | Definition | Target | Measurement Method |
|---|---|---|---|
| **NDCG@10** | Normalized Discounted Cumulative Gain at rank 10 | ≥ 0.65 | Golden query set with graded relevance labels (0-3) |
| **MRR** | Mean Reciprocal Rank of first relevant result | ≥ 0.75 | Binary relevance labels on golden set |
| **P@5** | Precision at rank 5 | ≥ 0.60 | Binary relevance on golden set |
| **Recall@20** | Fraction of relevant docs in top-20 candidates (pre-reranking) | ≥ 0.80 | Pooled relevance judgments |
| **Entity Resolution Accuracy** | Fraction of mentions correctly linked to canonical entities | ≥ 0.85 | Annotated entity mention evaluation set (100+ mentions) |
| **Relation Extraction F1** | Precision × Recall of extracted relation triples | ≥ 0.70 | Annotated document set with gold-standard triples |

### 8.2 Online / Product Metrics

| Metric | Definition | Target | Collection Method |
|---|---|---|---|
| **Answer satisfaction rate** | % of RAG answers rated helpful (if feedback UI exists) | ≥ 0.70 | Thumbs up/down on chat responses |
| **Citation accuracy** | % of citations that point to genuinely relevant sources | ≥ 0.85 | Periodic manual audit (sample 50 responses/week) |
| **Retrieval latency p95** | 95th percentile end-to-end retrieval time | ≤ 3.0s | Prometheus histogram (`rag_retrieval_duration_seconds`) |
| **Reranker improvement ratio** | % of queries where reranker improves top-1 vs fusion-only | ≥ 0.40 | Log pre/post reranker top-1 identity |
| **Source diversity** | Mean unique source types per response | ≥ 2.5 | Log source_type distribution per response |

### 8.3 Regression Gates

| Gate | Trigger | Threshold |
|---|---|---|
| **NDCG regression** | Any change to retrieval SQL, embedding model, or ranking code | NDCG@10 must not drop > 0.03 from baseline |
| **Latency regression** | Any change to retrieval pipeline | p95 must not increase > 500ms |
| **Entity resolution regression** | Any change to resolution cascade or thresholds | Accuracy must not drop > 0.02 |
| **Reranker bypass** | BGE reranker failure rate | Alert if fallback rate > 10% for 5 minutes |

### 8.4 Quality Benchmarks for Graph

| Benchmark | Method | Target |
|---|---|---|
| **Graph coverage** | % of entities with ≥1 non-stale relation | ≥ 0.70 |
| **Relation freshness** | % of relations with evidence < 30 days old | ≥ 0.50 |
| **Contradiction detection rate** | % of known contradictions caught by Block 12b | ≥ 0.80 |
| **Path connectivity** | % of entity pairs within 3 hops that have ≥1 path | Log and trend (no fixed target yet) |
| **Canonicalization coverage** | % of relation types resolved (not proposed) | ≥ 0.85 |

---

## 9. Final Recommendation

### What Must Be Done to Truly Level Up

The three highest-impact improvements, in order:

1. **Add BM25/full-text search and hybrid retrieval** (S-1 + M-2). This is non-negotiable. Purely semantic retrieval is a known failure mode for precision queries. PostgreSQL already supports this — it's a SQL + migration change, not an infrastructure change. Do this first.

2. **Build an offline evaluation framework** (M-3). Without measurement, every subsequent improvement is faith-based. A 50-100 query golden set with graded relevance labels takes 1-2 weeks to build and gates all future changes with objective quality metrics.

3. **Implement the entity knowledge compilation layer** (M-1). This is the Karpathy insight applied correctly: compile entity intelligence at ingest time so RAG can query compiled summaries instead of re-searching raw chunks. An `entity_summaries` table populated by a worker that triggers on `entity.dirtied.v1` would be the single largest improvement to answer quality and latency.

### What Should Be Deferred

- **Financial domain embedding model** (L-2) — The general-purpose nomic-embed-text is likely adequate for the current scale. Measure first (via M-3), then decide if domain-specific embeddings provide lift.
- **Relevance feedback loop** (L-3) — Requires significant frontend instrumentation and enough traffic to learn from. Premature for a thesis project.
- **Temporal knowledge graph** (L-5) — Architecturally elegant but complex. Decay classes provide adequate approximation for now.

### Explicit Go/No-Go Criteria for Claiming Major Improvement

| Criterion | Threshold | Status Required |
|---|---|---|
| Hybrid retrieval deployed | BM25 + ANN with RRF fusion live in production | S-1 + M-2 complete |
| Evaluation framework running | NDCG@10, MRR, P@5 computed on golden set | M-3 complete |
| NDCG@10 ≥ 0.65 on golden set | Measured, not estimated | Pass |
| Entity summaries queryable | `entity_summaries` table populated for ≥80% of entities with relations | M-1 complete |
| Cypher enabled in production | Multi-hop queries returning scored paths | S-2 + M-4 complete |
| Retrieval latency p95 ≤ 3.0s | Measured via Prometheus | Pass |

Until **all six criteria** are met, the retrieval and graph system should be described as "advanced prototype" rather than "production-ready intelligence platform."

---

## Appendix: Contributing Factors & Prevention

### Why These Gaps Exist

1. **Build-forward bias** — The development trajectory prioritized breadth (10 services, 6 libs, 5 content adapters) over depth in any single pipeline. Retrieval "works" (ANN search returns results) so it was never revisited critically.

2. **No retrieval quality measurement** — Without NDCG/MRR, there was no objective signal that pure semantic search is insufficient. The absence of metrics created the illusion of adequacy.

3. **Cypher complexity aversion** — Apache AGE adds operational complexity (sync worker, timeouts, separate graph engine). The feature flag was a reasonable safety measure but became permanent avoidance.

4. **Thesis-project resource constraints** — Building a knowledge compilation layer requires background workers, summary generation prompts, and cache invalidation logic. It was rationally deferred in favor of more visible features.

### Prevention Recommendations

1. **Add retrieval eval to CI** — Every PR touching retrieval code must pass NDCG regression gate.
2. **Log retrieval quality signals from day one** — Even before a golden set exists, log score distributions, source diversity, and reranker position changes.
3. **Design for measurement** — Every new retrieval feature should include a hypothesis about what metric it improves and how to verify.

---

**Compounding check**: The following documents should be updated based on this investigation:
- `docs/BUG_PATTERNS.md` — No new bug patterns (this is an architectural gap analysis, not a bug)
- `RULES.md` — Consider adding R28: "Retrieval changes must pass NDCG regression gate" once M-3 is built
- `.claude/agents/rag-knowledge-graph-engineer.md` — Already references NDCG/MRR; no update needed
- Service `.claude-context.md` files — No endpoint/schema changes
- `docs/MASTER_PLAN.md` — Consider updating retrieval architecture section once P0/P1 are implemented

**No updates applied** — this investigation is diagnostic, not prescriptive. Updates should accompany the implementation work.
