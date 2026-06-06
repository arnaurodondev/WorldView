# Investigation Report: Intelligence Generation Quality — Deep Dive

**Date**: 2026-05-23
**Investigator**: Claude — investigation skill (4 parallel specialist agents)
**Severity**: HIGH
**Status**: Root causes identified across 8 quality dimensions

---

## 1. Issue Summary

A comprehensive audit of the end-to-end intelligence generation pipeline was conducted, covering article ingestion, NLP extraction, entity resolution, knowledge graph construction, narrative generation, path insights, and the API output layer. The investigation found that the **instrument brief (RAG layer) is genuinely excellent**, but significant structural gaps exist at the narrative embedding, entity enrichment, and path explanation layers that degrade the Intelligence tab experience for most entities.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| Article volume/recency (13,485 articles, 7-day histogram) | content_store_db.documents | Ingestion health |
| Source stub epidemic measurement (37% articles <50 words) | content_store_db word_count stats | NLP input quality |
| Entity mention extraction (51,678 mentions, 11 types) | nlp_db.entity_mentions | NLP breadth |
| Resolution rate (59% resolved, 24% provisional) | nlp_db mention_resolutions | Entity matching quality |
| Relation evidence samples (10,238 rows, top-20 types) | intelligence_db.relation_evidence_raw | KG edge quality |
| Description coverage (4,016 entities, per-type) | intelligence_db.canonical_entities | Description quality |
| Narrative embedding length distribution | intelligence_db.entity_embedding_state | Narrative quality |
| NarrativeRefreshWorker source code | knowledge-graph/workers/narrative_generation_worker.py | Root cause analysis |
| entity_narrative_versions vs entity_embedding_state cross-check | intelligence_db | Write-back gap confirmation |
| Live API responses AAPL/NVDA/MSFT | S9 localhost:8000 | Output quality |
| Path insight samples (12,689 paths) | intelligence_db.path_insights | Path quality |
| Confidence/summary stale flags | intelligence_db.relations | Worker health |

---

## 3. Quality Assessment by Layer

### 3.1 Article Ingestion — GOOD

- **13,485 total articles**; latest as of 2026-05-23 17:33 UTC; ~600 articles/weekday
- 5 source providers: finnhub (46%), eodhd (34%), sec_edgar (18%), newsapi (2%), tenant_upload (<1%)
- Deduplication working: only 3 semantic near-duplicates across 13,485 articles

**CRITICAL gap**: **37% of articles have <50 words** (5,006 articles)

| Source | Stub % |
|--------|--------|
| finnhub | 61% (3,781 / 6,195) |
| sec_edgar | 52% (1,224 / 2,372) |
| eodhd | 0.02% |
| newsapi | 0% |

Finnhub and SEC Edgar deliver headlines/stubs without full body text. These generate sparse or zero NLP signal. The 6,412 documents that have been chunked (avg 1,632 chars, 76% with embedded mentions) come overwhelmingly from the non-stub sources.

### 3.2 NLP Entity Extraction — GOOD, with gaps

- **51,678 entity mentions** across 5,546 documents, 11 entity types
- Dominant type: organization (53%) — expected for financial news
- Resolution: **59% resolved** (auto_resolved + entity_created), 24% stuck as `provisional`, 17% noise

The 24% provisional mentions (~12,225) are stuck in the queue and never being upgraded by the second-pass LLM resolution worker. If that worker is stalled, these remain invisible to the KG.

Resolution confidence is high: "Jensen Huang" (0.97), "Apple" (1.00), "Nasdaq" (0.98). Low-confidence mentions (0.40) do resolve — the floor logic is working.

### 3.3 Relation Evidence Quality — GOOD text, structural gaps

- **10,238 evidence rows** across 20+ canonical types
- Top types: is_in_sector (1,392), listed_on (934), competes_with (896), partner_of (757)
- 85% of evidence at confidence ≥0.9
- Evidence text is contextually grounded: *"When Chase does something, Citi reacts. Or when Amex amps up an offer, Bank of America antes up"*

**Gaps**:
- 269 rows (2.6%) have NULL `canonical_type` — unclassified extractions that won't route to KG
- Multi-label over-firing: a single sentence about Musk/OpenAI drives 5 simultaneous relation types (sentiment_signal, competes_with, board_member_of, owns_stake_in, corporate_action)

### 3.4 Entity Descriptions — MISLEADING coverage numbers

After the BP-541 write-back fix (2026-05-23), `canonical_entities.description` shows 3,440/4,016 (85.7%) populated. However, the **quality distribution is very skewed**:

| Entity type | Coverage | Avg desc length | Real prose % |
|-------------|----------|-----------------|--------------|
| sector/currency/index | 100% | 200–500 chars | **~100%** |
| financial_instrument | 62.6% | 57 chars avg | ~10% |
| person | 100% | 23 chars avg | ~3% |
| unknown | 100% | 71 chars avg | ~4% |

The "100% coverage" for person/unknown means the DB column is filled with the entity name itself (e.g. `"The Washington Post"`, `"Kevin O'Leary"`) — not real descriptions. This is because `DefinitionRefreshWorker` falls back to `_fallback_description()` which returns `"{name} is a {entity_type}."` when Gemini API fails or when `source_text` was never set. The write-back correctly propagates whatever was in `source_text`, but for most person/unknown entities, that content was already minimal.

**Bright spot**: S&P 500 scale `financial_instrument` entities have excellent EODHD descriptions (Caterpillar: 1,997 chars; Pfizer: 1,993 chars; Berkshire Hathaway: 1,958 chars).

### 3.5 Narrative Embeddings — CRITICAL structural bug

**91.8% of all 4,016 narrative embeddings are name stubs** (<60 chars):

| Length category | Count | % |
|-----------------|-------|---|
| <30 chars (e.g. "Himax (financial_instrument)") | 2,193 | 54.6% |
| 30–60 chars | 1,494 | 37.2% |
| 60–500 chars | 256 | 6.4% |
| 500+ chars (rich) | 73 | 1.8% |

**Root cause confirmed**: There are two workers writing to this space that are siloed from each other:

1. **`NarrativeRefreshWorker` (hourly polling)**: Rebuilds `entity_embedding_state.source_text` from `claims` table. For entities with no claims (85%+ of entities), produces `"{name} ({type})"` — a pure name stub. **This worker has zero awareness of `entity_narrative_versions`.**

2. **`NarrativeGenerationWorker` / `GenerateNarrativeUseCase` (LLM-based)**: Produces real prose (~65 words) and writes it to `entity_narrative_versions`. This text IS of acceptable quality for entities with graph relations. But this text **never flows into `entity_embedding_state.source_text`**.

The Kafka hot-path consumer (`NarrativeRefreshKafkaConsumer`) was designed to bridge this gap — it listens for `entity.narrative.generated.v1` events and embeds the new narrative. However, the hourly `NarrativeRefreshWorker` **overwrites the rich embedding with the stub template** on the next cycle, because it rebuilds `source_text` from claims unconditionally.

Additionally, the LLM narratives themselves hallucinate for entities with no article context: the `entity_narrative_versions` entry for "Himax" says it was "acquired by Eigen AI" — fabricated.

### 3.6 Instrument Brief (RAG) — EXCELLENT

The strongest output layer. RAG-based brief generation is working correctly:

- **NVDA brief**: Correct FY2027 Q1 figures (Revenue $44.1B, beat by $4.5B), 50 citations, 73.2% revenue growth YoY, accurate P/E of 43.8
- **AAPL brief**: Correctly covers Fortnite/App Store litigation, Supreme Court petition, citations from 2026-05-22

This layer is genuinely production-quality.

### 3.7 Path Insights — Scored but unexplained, hub-collapsed

- **12,689 path insights** (7,305 hop-2, 5,384 hop-3); avg composite score 0.625
- **0/12,689 have `llm_explanation`** — explanation pipeline never triggered
- **AI theme hub collapse**: "Artificial Intelligence" entity is so densely connected that all AAPL/NVDA/MSFT paths route through it with identical scores (0.482), destroying path diversity
- Top entities: NVIDIA (134 edges), Intel (133), AMD (110), Anthropic (101), OpenAI (98)

### 3.8 Seeded Entity Blindspot — CRITICAL for AAPL/NVDA/MSFT

The 10 seeded entities (AAPL, NVDA, MSFT, etc.) were inserted directly into `canonical_entities` before the enrichment pipeline existed. They never flowed through the provisional enrichment queue:

| Field | Value for seeded entities |
|-------|--------------------------|
| `key_metrics` | `{}` (empty) |
| `data_completeness` | 0.1 (1/10 metadata fields) |
| Definition embedding | None |
| Claims linked | 0 (AAPL: 0 claims) |
| Metadata fields present | Only: country, gics_sector, instrument_id |

Pipeline-discovered entities (Intel, Anthropic, AMD) have rich data. Seeded entities are starved.

---

## 4. Root Cause Summary

| # | Issue | Root Cause | File |
|---|-------|-----------|------|
| RC-1 | 37% of articles are stubs | Finnhub/SEC Edgar deliver headlines without full-text retrieval | content_ingestion adapters |
| RC-2 | 91.8% narrative stubs | `NarrativeRefreshWorker` rebuilds `source_text` from claims unconditionally, overwriting LLM narrative; claims coverage is 14.7% for financial_instrument | `narrative_generation_worker.py` |
| RC-3 | Seeded entities have no enrichment data | Seeded entities bypass provisional enrichment queue; never processed by EODHD fundamentals worker | `canonical_entities` seed migrations |
| RC-4 | 0/12,689 path explanations | LLM explanation job queue exists but no worker runs it | `path_insight_jobs` table |
| RC-5 | Path hub collapse | "Artificial Intelligence" hub entity over-connected; path ranker doesn't penalize over-traversed hubs | path scoring algorithm |
| RC-6 | Confidence always 1.0 | Confidence scorer not differentiating; 6,349/7,911 (80%) relations have `confidence_stale=true` | confidence decay worker |
| RC-7 | 24% provisional mentions never resolved | Second-pass LLM resolution worker not processing provisional queue | nlp-pipeline unresolved_resolution_worker |
| RC-8 | Description stubs for person/unknown | `_fallback_description()` produces "{name} is a {type}" when Gemini fails; most non-financial entities have no Gemini-generated content | `definition_refresh.py:_fallback_description` |

---

## 5. Enhancement Recommendations

### P0 — Immediate fixes (high impact, low effort)

**P0-1: Fix NarrativeRefreshWorker to use LLM narrative** (XS–S effort, HIGHEST LEVERAGE)

In `NarrativeRefreshWorker._build_narrative_text()`, before building the claims template, check `canonical_entities.current_narrative_version_id`. If a version exists, fetch `narrative_text` from `entity_narrative_versions` and use it as `source_text` (truncated). Fall back to the claims template only when no LLM narrative exists. This single join collapses the two-pipeline gap and immediately upgrades 91.8% of stub embeddings.

**P0-2: Fix uppercase canonical_type normalization** (XS effort)

```sql
UPDATE relations SET canonical_type = LOWER(canonical_type)
WHERE canonical_type != LOWER(canonical_type) AND canonical_type IS NOT NULL;
UPDATE relation_evidence_raw SET canonical_type = LOWER(canonical_type)
WHERE canonical_type != LOWER(canonical_type) AND canonical_type IS NOT NULL;
```

**P0-3: Enqueue seeded entities into the enrichment pipeline** (S effort)

The 10 seeded entities (AAPL, NVDA, MSFT, GOOGL, AMZN, META, TSLA, BRK.B, NFLX, JPM) need to be manually inserted into the `enrichment_queue` / `provisional_enrichment_queue` so they receive EODHD fundamentals, definition embeddings, and claims linkage. Until this happens, the most prominent stocks on the platform have degraded intelligence output.

### P1 — Complete broken pipelines (M effort)

**P1-1: Run LLM path explanation worker** — `path_insight_jobs` table exists; a worker needs to run the explanation job for each unprocessed path. 12,689 paths with scores but no prose are not useful in UX.

**P1-2: Fix provisional mention resolution backlog** — 12,225 provisional mentions need the LLM resolution worker to process them. Check `UnresolvedResolutionWorker` logs and queue state.

**P1-3: Wire article context into narrative generation** — `GenerateNarrativeUseCase` has `articles=[]` hardcoded (agent 4 confirmed). Connecting recent article snippets (top-3 by relevance score for the entity) would eliminate hallucination and produce news-aware narratives instead of generic KG-topology summaries.

**P1-4: Implement stub article filter** — Add a `min_word_count ≥ 50` filter before NLP pipeline submission. This would eliminate 5,006 stub articles (37%) from consuming NLP capacity.

### P2 — Quality improvements

**P2-1: Tighten multi-label extraction confidence threshold** — A single evidence sentence producing 5 simultaneous relation types indicates the extraction confidence threshold is too permissive. Raise from current level or add a per-sentence relation-count cap (max 2 relations per sentence).

**P2-2: Penalize over-traversed path hubs** — Add a hub-penalty term to the path scoring formula: `hub_penalty = log(edge_count) / max_log_degree`. Divide composite_score by `(1 + hub_penalty)` so "Artificial Intelligence" (127 edges) is scored down relative to specific company-to-company paths.

**P2-3: Grow claims coverage** — Only 226/1,542 (14.7%) financial_instrument entities have claims. Claims are the fallback when no LLM narrative exists. Improving claim extraction precision and recall would benefit 85%+ of entities.

---

## 6. Contributing Factors

- **Architectural silo**: `NarrativeRefreshWorker` and `NarrativeGenerationWorker` write to different tables with no shared state — the hourly worker never checks what the LLM worker wrote
- **Seeding workflow gap**: No mechanism exists to retroactively enrich manually-seeded entities through the standard pipeline
- **Missing article context in LLM calls**: `GenerateNarrativeUseCase` builds narratives from KG relations only — no article text fed in despite article corpus being available
- **Explanation worker exists but never deployed**: `path_insight_jobs` table has the right schema but no consuming worker is running in production

---

## 7. Open Questions

1. Why is the `UnresolvedResolutionWorker` not processing the 12,225 provisional mentions? Is it failing silently?
2. Does the path explanation worker exist in code but lack a scheduler entry, or is it entirely unimplemented?
3. Is `NarrativeGenerationWorker` running for all entity types or only financial_instrument? (agent 4 saw it producing output but the entity_type scope is unclear)
4. Why does `_fallback_description()` get called for so many entities — is Gemini failing frequently or are those entity types excluded from the Gemini call?
