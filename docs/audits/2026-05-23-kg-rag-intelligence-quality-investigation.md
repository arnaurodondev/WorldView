# Investigation Report: KG-RAG Intelligence Layer Quality

**Date**: 2026-05-23
**Investigator**: Claude — investigation skill (3 parallel specialist agents)
**Severity**: HIGH
**Status**: Root causes identified across 6 quality dimensions

---

## 1. Issue Summary

An investigation into the end-to-end quality of the Knowledge Graph and RAG intelligence layer was requested, covering: relation quality, entity descriptions, edge labels/messages, embedding descriptions, and whether existing reports address the identified enhancements needed.

The platform is functionally live (19,701 DeepInfra extraction calls, 14,325 embeddings generated, briefs cached and readable), but significant data quality gaps exist at 6 layers that degrade the intelligence product — particularly for path traversal, semantic search, and the RAG briefing pipeline.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| Postgres counts across all intelligence_db tables | Direct DB query | Baseline for all quality assessments |
| Relation type distribution (20 types, 7,911 rows) | `relations` table | Topology health |
| Evidence text samples (10 per type) | `relation_evidence_raw` | Edge prose quality |
| Entity embedding coverage by view type | `entity_embedding_state` | Embedding health |
| AGE graph label counts vs Postgres relations | `ag_catalog` + `relations` | Sync gap measurement |
| Live API responses for AAPL, NVDA, MSFT | S9 API gateway localhost:8000 | UX-facing quality |
| Path insight records (12,689) | `path_insights` table | Path quality |
| Relation summaries (101) | `relation_summaries` table | Summary quality |
| All existing audit reports (14+ files) | `docs/audits/` | Prior investigation coverage |

---

## 3. Quality Assessment by Layer

### 3.1 Relations (Postgres) — GOOD

7,911 edges across 20+ distinct `canonical_type` values. Distribution is healthy:
- Top 5 types represent ~40% (no extreme concentration)
- `competes_with` (703), `partner_of` (608) confirm news-derived inference is active
- Confidence scores uniformly high (0.815–0.947 across all types)
- **All rows have evidence_text** (100% coverage after BP-532 fix)

Gaps:
- **269 rows have `canonical_type = NULL`** — orphaned evidence without an edge type (EODHD source 250, Finnhub 14, SEC 4, Newsapi 1)
- **71.7% of consolidated relations have `confidence_stale = true`** (5,670/7,911) — recomputation lagging
- **80.8% have `summary_stale = true`** (6,393/7,911) — SummaryWorker barely started
- **36 UPPERCASE `canonical_type` rows** (`EXPOSED_TO_THEME`, `COMPETES_WITH`, `SUPPLIER_OF`) — legacy seed data inconsistent with lowercase norm

### 3.2 Evidence Text Quality — MODERATE

Event-derived relations (`competes_with`, `partner_of`, `analyst_rating`, etc.) have real, accurate 100–141 char sentences extracted from news articles. These are the backbone of the intelligence product.

Structural relations are stubs:
- `is_in_sector` avg 43 chars: `"EODHD fundamentals: sector classification."` — factually correct, zero informational value for RAG
- `listed_on` avg 61 chars: `"<ticker> listed on <exchange> (EODHD data)"` — same pattern

This is by design for structural facts but limits the RAG retrieval depth for these relation types.

### 3.3 AGE Graph Sync — CRITICAL (74% gap)

The Apache AGE graph powering Cypher path traversal is severely out of sync with the Postgres `relations` table:

| Relation type | AGE count | Postgres count | Missing |
|--------------|-----------|---------------|---------|
| COMPETES_WITH | 278 | 703 | **425** |
| PARTNER_OF | 162 | 608 | **446** |
| LISTED_ON | 108 | 550 | **442** |
| ANALYST_RATING | 52 | 453 | **401** |
| IS_IN_SECTOR | 679 | 713 | 34 |
| Total (est.) | ~2,041 | ~7,911 | **~5,870** |

18 of 35 AGE edge type tables have stale statistics (`-1` approximate counts), suggesting they may be near-empty. The `worldview_graph` has 3,773 vertices vs 4,016 in `canonical_entities` — 243-entity vertex gap.

**All path traversal (`GET /intelligence/{id}/graph`) is operating on ~25% of the true graph.**

Direct 1-hop connections (e.g., Apple ↔ Microsoft `COMPETES_WITH`) are missing from AGE — all 10 Apple→MSFT paths and Apple→NVDA paths route only through "Artificial Intelligence" intermediate node because the direct edges are not in AGE.

### 3.4 Entity Descriptions — GOOD text, broken write-back

Entity description text in `entity_embedding_state.source_text` (definition view) is high quality:
- `person` entities: 3-paragraph Wikipedia-style biographies
- `financial_instrument` (large-caps): Full EODHD business descriptions, 500–1800 chars
- `sector`/`unknown` types: AI-generated synthetic descriptions, reasonable quality
- Avg source_text length: 234 chars

**Critical gap**: `canonical_entities.description` is NULL for 4,008/4,016 entities (99.8%). `enriched_at` is NULL for all 4,016. The `DefinitionRefreshWorker` generates and embeds description text into `entity_embedding_state` but **never writes back to `canonical_entities.description`**. This means:
- All graph node descriptions served via API are `null`
- Frontend shows empty description panels for 99.8% of entities
- The field is populated only for 8 entities apparently seeded manually (AMD, Alphabet, Anthropic, Coinbase, Intel, Netflix, OpenAI, Qualcomm)

### 3.5 Embedding Coverage — MIXED

| View type | Coverage | Quality |
|-----------|----------|---------|
| **definition** | 85.7% (3,440/4,016) | GOOD — real descriptions, avg 234 chars |
| **narrative** | 100% (4,016/4,016) | POOR — 91.8% are stubs under 60 chars |
| **fundamentals_ohlcv** | 49.0% (756/1,542) | BROKEN — all source_text is placeholder |

**Narrative crisis**: Although 100% of narrative rows are "embedded", 91.8% are name-only stubs:
- 54.6% are under 30 chars: `"<Name> (type)"`
- 37.2% are 30–60 chars: `"<Name> (type) — brief sentence"`
- Only 4.9% have 200+ chars of real narrative

Vector similarity in the narrative index effectively differentiates entities only by their type and a few keywords. Semantic search for "companies with strong AI partnerships" will not distinguish Intel from AMD because both have nearly identical stub texts.

**Fundamentals_ohlcv is broken**: Every single one of the 1,542 source_text values (and 756 embeddings built on them) is:
```
<EntityName> (financial_instrument) — Financial State Summary
No financial data available.
```
The entire `fundamentals_ohlcv` ANN index is noise — all entities appear equally "similar" to any financial query.

### 3.6 Relation Summaries — HIGH quality, not embedded

101 LLM-generated relation summaries exist and the prose quality is excellent:
- *"TCI increased its stake in Alphabet to 5%, making it the firm's largest technology position, while Alphabet, Meta, Microsoft, and Amazon plan up to $725 billion in combined spending on AI infrastructure this year."*
- *"Alphabet, Amazon, and Microsoft have invested heavily in AI firms like Anthropic and OpenAI..."*

**Critical gap**: All 101 summaries have `summary_embedding = NULL`. They cannot be retrieved by vector search. The SummaryWorker generates prose but never calls the embedding worker on the result. Coverage is also only 101/7,911 relations (1.3%).

### 3.7 Path Insights — Scored but Unexplained

12,689 path insights exist with computed scores (composite avg 0.625 for 2-hop, 0.574 for 3-hop). However:
- **0/12,689 path insights have `llm_explanation`** — the natural language explanation generation step has never run
- The `PathInsightWorker` LLM narrative step is either misconfigured or silently failing
- `explanation_at` is NULL for every row
- Duplicate paths: 10 consecutive Applied Materials paths with identical scores (0.95/0.5/0.398) indicate the deduplication guard is per-job, not global

### 3.8 API-Facing Quality — PARTIAL

What works well:
- Health scores (AAPL=0.729, NVDA=0.744, MSFT=0.729) — populated and reasonable
- Evidence snippets on graph edges — accurate and readable (60–80% of edges)
- Instrument briefs (NVDA, AAPL) — excellent: real financial data, inline citations, timely content
- Morning brief — coherent, topical, properly cached
- Narrative generation — 80–100 words per entity, factually coherent

Broken/null API fields:
- `relation_type` on graph edges always `"NO_TYPE"` — transform function never sets it
- `description` on graph nodes null for 99.8% of entities
- `data_completeness` null for all 4,016 entities
- `quality_score` on narratives null for all entries
- `key_metrics` always `{}`
- `sentiment_timeseries` always `{"points": []}`
- `contradictions` always `[]`
- Path edge `confidence` always `0.0`
- `risk_summary.sector_breakdown` always `{}`

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | AGE sync worker is not running or severely lagging | CONFIRMED | Direct ag_catalog label counts vs relations table |
| H-2 | fundamentals_ohlcv embedding index is usable for financial semantic search | REFUTED — all source_text is placeholder | Direct DB query of 5 random fundamentals rows |
| H-3 | DefinitionRefreshWorker writes descriptions to canonical_entities | REFUTED — enriched_at null for all 4,016 | DB query + API response inspection |
| H-4 | Relation summaries are integrated into RAG retrieval | REFUTED — summary_embedding null for all 101 | DB query on relation_summaries table |
| H-5 | Path insights have human-readable LLM explanations | REFUTED — explanation_at null for all 12,689 | DB query on path_insights |
| H-6 | Narrative embeddings differentiate entities semantically | REFUTED — 91.8% are name-only stubs | source_text sampling + length distribution |

---

## 5. Root Cause Summary

| Issue | Root Cause | File/Location |
|-------|-----------|---------------|
| AGE sync 74% gap | AGE sync worker has a large backlog; new relations added by NLP pipeline are not being synced fast enough, or the sync is skipping edge types | `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py` |
| fundamentals_ohlcv broken | `FundamentalsRefreshWorker` builds narrative from S3 market-data REST API; if S3 returns no data, it writes the placeholder and embeds it | `fundamentals_refresh.py` + `build_fundamentals_narrative()` |
| Narrative stubs | `NarrativeGenerationWorker` may be running but producing minimal output for most entity types; or many entities haven't been processed yet | `knowledge_graph/infrastructure/workers/narrative_generation_worker.py` |
| Description not written back | `DefinitionRefreshWorker` writes to `entity_embedding_state.source_text` but not to `canonical_entities.description` — this write-back was never implemented | `definition_refresh.py` |
| Relation summaries not embedded | `SummaryWorker` calls LLM and writes `summary_text` to `relation_summaries` but never queues the row for embedding | `summary_worker.py` |
| Path insight LLM explanations | `PathInsightWorker` computes scores but the LLM explanation step is disabled or failing silently | `path_insight_worker.py` |
| `relation_type` always NO_TYPE | `_transform_graph_response()` in intelligence routes populates `label` (snake_case type) but never sets `relation_type` field | `intelligence.py` transform function |

---

## 6. Impact Analysis

- **Semantic search**: Narrative and fundamentals_ohlcv ANN indexes are functionally broken for ~91.8% of entities. Only the definition index provides meaningful semantic differentiation.
- **Path traversal**: All Cypher queries operate on 25% of the true graph — critical connections (direct COMPETES_WITH, PARTNER_OF) are invisible.
- **RAG quality**: Entity descriptions are null in API responses; relation summaries cannot be retrieved by vector search; path insights have no natural language explanations. RAG must fall back to raw evidence snippets only.
- **Entity type accuracy**: 30% of entities (1,208/4,016) have `entity_type = unknown` including top-connected nodes (Anthropic, Amazon Inc, Google LLC, OpenAI) — these miss type-specific enrichment, partial indexes, and sector attribution.
- **Contradiction detection**: Structurally inoperative — relation polarity is `positive` for 100% of rows.
- **Event-entity linkage**: 96% of 74,190 events are unlinked — temporal intelligence layer is sparsely populated.

---

## 7. Enhancement Recommendations

### Priority P0 — Fix silently broken indices

**P0-1: AGE sync catch-up** (Effort: M)
Run a one-time catch-up sync for all `relations` rows not yet in AGE. Check `age_sync_worker.py` for the sync flag/cursor and reset or replay. Without this, all path queries are wrong.

**P0-2: fundamentals_ohlcv placeholder guard** (Effort: S)
In `build_fundamentals_narrative()`, return `None` (not the placeholder string) when market data is unavailable. In `FundamentalsRefreshWorker`, treat `None` narrative as "skip + retry" instead of embedding the placeholder. Backfill: `UPDATE entity_embedding_state SET embedding = NULL, source_text = NULL, source_hash = NULL WHERE view_type = 'fundamentals_ohlcv' AND source_text LIKE '%No financial data available%'`.

**P0-3: Write description back to canonical_entities** (Effort: S)
In `DefinitionRefreshWorker.run()`, after the embedding upsert, add an UPDATE to `canonical_entities.description = source_text` and `enriched_at = now()` for each successfully embedded entity. This immediately unlocks graph node descriptions for 3,440 entities.

### Priority P1 — Complete incomplete pipelines

**P1-1: Embed relation summaries** (Effort: S)
In `SummaryWorker`, after writing `summary_text` to `relation_summaries`, call the embedding client on the summary text and write the result to `summary_embedding`. Alternatively, add relation_summaries to the `EmbeddingRefreshWorker` scheduler queue.

**P1-2: Generate path insight LLM explanations** (Effort: M)
Diagnose `PathInsightWorker` LLM explanation step — check logs for errors. If misconfigured, fix the LLM client wiring. If disabled by config, re-enable. 12,689 paths with scores but no text are useless in a UX context.

**P1-3: Narrative generation for non-financial entities** (Effort: M)
The `NarrativeGenerationWorker` produces 80–100 word narratives for some entities. Audit which entity types are being skipped and why 91.8% of narratives are stubs. Run a targeted catch-up for `sector`, `industry_group`, `country`, `person`, and `company` entity types.

**P1-4: Fix relation_type in graph transform** (Effort: XS)
In `_transform_graph_response()` (intelligence routes), set `edge["relation_type"] = edge["label"]` before returning. One line.

### Priority P2 — Data integrity fixes

**P2-1: Self-loop pre-insert guard** (Effort: S)
In `_build_raw_relations()`, add `if subject_entity_id == object_entity_id: continue` before inserting into `relation_evidence_raw`. Backfill: `DELETE FROM relation_evidence_raw WHERE subject_entity_id = object_entity_id`.

**P2-2: Fix NULL canonical_type rows** (Effort: S)
Investigate 269 `relation_evidence_raw` rows with `canonical_type = NULL`. Either type them via re-extraction or delete them (`DELETE FROM relation_evidence_raw WHERE canonical_type IS NULL`).

**P2-3: Entity type classification for key unknowns** (Effort: M)
Anthropic, Google LLC, Amazon Inc, OpenAI, and ~300 other high-connectivity entities are `unknown` type. A classification pass using the provisional_entity_queue + a targeted GLiNER call or simple rule (if has_executive → company; if has_ticker → financial_instrument) would rescue the most impactful nodes.

**P2-4: Normalize UPPERCASE canonical_type in legacy seed data** (Effort: XS)
`UPDATE relations SET canonical_type = lower(canonical_type) WHERE canonical_type != lower(canonical_type)`. Same for `relation_evidence_raw`.

**P2-5: Event-entity exposure coverage** (Effort: M)
533 entity_event_exposures vs 74,190 events is 0.7% coverage. Diagnose whether `EventExposureWorker` is running, and if temporal events are being linked. Target: at least 10% coverage of recent events.

### Priority P3 — Quality scoring and evaluation

**P3-1: Implement data_completeness scoring** (Effort: M)
The `data_completeness` field exists in the intelligence response schema but is always null. Implement a scoring function: (def_embedding / 1.0) * 0.3 + (narrative_quality / 1.0) * 0.2 + (relation_count / target) * 0.3 + (has_description / 1.0) * 0.2.

**P3-2: Narrative quality_score** (Effort: S)
After generating each narrative, score it: `quality_score = min(1.0, len(narrative.split()) / 100)` as a simple proxy, or use the LLM-judge pattern from PLAN-0075 if implemented.

**P3-3: Implement contradiction detection** (Effort: L)
Polarity is `positive` for 100% of evidence rows. The contradiction pipeline is structurally broken. Fix: add polarity classification in `deep_extraction.py` prompt schema; update `ContradictionBatchWorker` to consume it.

---

## 8. Relationship to Existing Reports

The following 14+ audit reports already exist in `docs/audits/` covering this domain:

| Report | Date | Scope |
|--------|------|-------|
| `2026-05-22-qa-intelligence-layer-report.md` | 2026-05-22 | Full intelligence layer QA pass 1 — 45 findings |
| `2026-05-22-qa-intelligence-layer-report-2.md` | 2026-05-22 | QA pass 2 after fixes — 38 findings, 3 CRITICAL open |
| `2026-05-22-quality-improvements-report.md` | 2026-05-22 | 17 remaining issues with priority/effort/impact matrix |
| `2026-05-22-qa-nlp-pipeline-deep-dive-report.md` | 2026-05-22 | Live-stack NLP/KG deep-dive — FAIL verdict |
| `2026-05-09-audit-R3-intelligence-layer.md` | 2026-05-09 | Intelligence layer end-to-end 500 failures root cause |

**This report adds**: live data quality measurements that the code-only QA passes could not see (actual counts, actual text samples, AGE sync gap measurement, embedding coverage statistics, API field null rates).

**The `2026-05-22-quality-improvements-report.md` is the most relevant prior document**: it maps 17 issues with P0/P1/P2 priority and effort estimates. The recommendations in this report are consistent with and extend that prior work.

---

## 9. Open Questions

1. Why is AGE sync so far behind? Is the sync worker running? What is its current backlog size and throughput? (check `docker logs worldview-knowledge-graph-dispatcher-1`)
2. Why does `FundamentalsRefreshWorker` embed placeholder text? Is S3 returning empty responses for most tickers, or is the narrative builder failing before the API call?
3. Is `PathInsightWorker` LLM explanation generation even configured? What model is it using and what do its logs show?
4. Is `NarrativeGenerationWorker` running on all entity types or only `financial_instrument`?
5. Was the decision made to NOT write descriptions back to `canonical_entities.description`? (No ticket or ADR found.)

---

## 10. Next Steps

The most impactful fixes in order:
1. **P0-1**: AGE sync catch-up → unblocks path traversal for 75% of missing edges
2. **P0-2**: fundamentals_ohlcv placeholder guard → fixes broken ANN index
3. **P0-3**: Write description back → 3,440 entities get descriptions immediately
4. **P1-4**: `relation_type` field (1 line) → unblocks frontend field
5. **P1-1**: Embed relation summaries → 101 quality summaries become searchable

Invoke `/fix-bug` for P0-3 and P1-4 (both are small, clear code changes). Invoke `/prd` for AGE sync and narrative quality (these require design decisions about sync strategy and quality threshold).
