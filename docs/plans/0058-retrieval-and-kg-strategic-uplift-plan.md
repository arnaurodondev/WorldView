# PLAN-0058 — Retrieval & Knowledge-Graph Strategic Uplift

> **Scope split**: Phase 1 of the revised audit (pipeline-integrity fixes + canonical seeding) is owned by **PLAN-0057** (News-Intelligence Pipeline Quality Repair, created from the 04-29 audit). PLAN-0058 owns the *strategic* Phase 2 + Phase 3 work: eval framework, hybrid retrieval, knowledge compilation layer, Cypher activation, ontology, observability.
>
> **Dependency**: PLAN-0058 Wave C (eval framework) can begin in parallel with PLAN-0057 Wave A (so the eval baseline measures the pre-fix state too). Waves D onwards strictly require PLAN-0057 Phase 1 complete.

**Created**: 2026-04-30
**Owner**: Backend (S6, S7, S8) + RAG (S8)
**Source documents**:
- `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` (revised audit)
- `docs/audits/2026-04-29-investigation-news-pipeline-quality-deep-dive.md` (with 04-30 update)
- `docs/audits/2026-04-27-investigation-model-decisions-and-kg-pipeline.md`
- `docs/audits/2026-04-23-retrieval-graph-architecture-investigation.md` (superseded)

**Goal**: After PLAN-0057 restores the pipeline to a working state, lift the retrieval + KG stack from "production-grade design" (~3.5/5) to "production-grade in practice" (~4.5/5) by adding measurement, hybrid retrieval, knowledge compilation, multi-hop reasoning, ontology enforcement, and full observability.

**Status**: draft — pending user approval

---

## Executive Plan

```
PHASE 1 (PLAN-0057, separate plan)        Phase 2 — Make it Measurable (~3 weeks)        Phase 3 — Strategic Uplift (~6 weeks)
─────────────────────────────────────     ─────────────────────────────────────────       ─────────────────────────────────────
Wave A: Pipeline-Integrity Fixes          Wave C: Offline Eval Framework                  Wave F: Knowledge Compilation Layer
Wave B: Canonical Coverage Seeding        Wave D: Hybrid Retrieval (BM25+ANN+RRF)         Wave G: Cypher Activation + Path Scoring
   ↓ (delegated to PLAN-0057)             Wave E: Routing & Recency Hardening             Wave H: Ontology, Temporal, Dashboards
```

> Waves A and B are reproduced below for traceability, but they are owned and tracked under **PLAN-0057**. PLAN-0058's net-new content begins at **Wave C**.

Cross-wave invariants:
- **No wave is "done" until** its acceptance metrics hold for 24h on the dev stack with seed data flowing.
- **No phase moves forward until** Phase N's gates pass on the eval framework (after Wave C).
- **Every PR** in this plan must update `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` Section 5 (maturity re-rating).

---

## Phase 1 — Stop the Bleed *(delegated to PLAN-0057; reproduced for traceability only)*

**Phase exit gate**: `kg_extraction_yield ≥ 0.90` (Prometheus gauge), `mention_resolutions` rows > 5000 (24h), AGE node count > 0, `entity_class_coverage_ratio = 1.0` (all 11 GLiNER classes have ≥1 canonical), `llm_usage_log` rows > 0 (24h).

---

### Wave A — Pipeline-Integrity Fixes

**Wave intent**: Eliminate the silent-drop pathology and unwrite the audit-trail blindness so the pipeline becomes observable end-to-end. No new features — this is restoration.

**Dependencies**: none (these are independent fixes; can run in parallel within the wave).

**Tasks**:

| ID | Task | File(s) | Acceptance |
|---|---|---|---|
| **A-1** | Fix F-CRIT-07: change `_build_raw_relations`/`_events`/`_claims` from silent `continue` to structured handling. Two-step fix: (a) populate `entity_id_by_ref` from the union of resolved IDs and provisional queue UUIDs; (b) the deep-extraction prompt must list ONLY mentions whose ref is in `entity_id_by_ref`; (c) parser raises `KGContractViolation` on unknown ref (Prometheus counter `nlp_kg_contract_violation_total{reason}`). | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:780-870`, `services/nlp-pipeline/src/nlp_pipeline/application/blocks/deep_extraction.py` (prompt construction) | `kg_extraction_yield` gauge ≥ 0.90 over 24h on dev. Unit test feeds a known doc and asserts `len(raw_relations) == len(extraction.relations)` for fully-resolved cases. Contract violation test asserts the counter increments when prompt/lookup drift is induced. |
| **A-2** | Fix F-CRIT-04: insert default self-alias on canonical creation. In `entity_consumer` (S7), wrap `canonical_entities` insert in a transaction that also inserts an `entity_aliases` row with `alias_text=canonical_name`, `normalized_alias_text=lower(canonical_name)`, `source='self'`, `confidence=1.0`. Idempotent (skip if exists). Backfill migration for the 45 missing canonicals. | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py`, new Alembic migration in `services/intelligence-migrations/alembic/versions/` (data-only) | `SELECT count(*) FROM entity_aliases WHERE source='self'` ≥ count of canonical_entities (after backfill). Unit test: creating canonical inserts alias. |
| **A-3** | Fix F-CRIT-02: persist `mention_resolutions` audit trail. In `article_consumer.py` after Block 9, call `mr_repo.add_batch(mention_resolution_rows)` inside the same UoW that writes `entity_mentions`. Include resolution_stage, score, alias_id (if Stage 1), candidate count. | `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:405-430`, `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/mention_resolution_repo.py` | After 24h ingest, `mention_resolutions` row count ≈ `entity_mentions` row count. Unit test: a resolved mention writes one audit row. |
| **A-4** | Fix F-CRIT-03: wire `LLMUsageLogger` into the 3 affected workers (deep extraction, intent classifier shared client where applicable, alias generation). Replace `usage_logger=None` with the real adapter from `libs/ml-clients`. | `services/nlp-pipeline/.../llm_workers/*.py`, `services/knowledge-graph/.../infrastructure/workers/definition_refresh.py`, `services/knowledge-graph/.../infrastructure/workers/summary.py`, `services/knowledge-graph/.../infrastructure/workers/provisional_enrichment.py` | `llm_usage_log` row count > 0 after first deep-extraction run; rows have non-null `tokens_in`, `tokens_out`, `latency_ms`, `cost_usd`. (BP-272 also enforces this.) |
| **A-5** | Fix F-CRIT-05: rewrite `UnresolvedResolutionWorker` prompt to use neutral notability criteria (SEC-registered / publicly listed / exchange-traded / mentioned across ≥2 distinct sources) instead of "has a Wikipedia article". Add 3 few-shot examples. | `services/knowledge-graph/.../infrastructure/workers/provisional_enrichment.py`, prompts directory | Eval set of 50 known-notable entities from provisional queue: ≥35 promoted to canonical (vs current ~5). |
| **A-6** | Fix F-CRIT-06: add `final_routing_tier`, `processing_path` columns to `routing_decisions` via Alembic migration. Update `RoutingDecisionRepo.upsert` to write the post-novelty values. | `services/intelligence-migrations/alembic/versions/`, `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision_repo.py` | Schema change applied; queries `SELECT count(*) FROM routing_decisions WHERE final_routing_tier IS NOT NULL` > 0 after 1h ingest. Migration is forward-compatible (nullable column with default). Apply via `/migrate-db`. |
| **A-7** | Fix F-MAJOR-09: thread `{description}` into alias-generation prompt and update `instrument_consumer` to pass description through actual placeholder (not unused `context=`). Add 5 few-shot examples per entity type. | `services/knowledge-graph/.../infrastructure/workers/instrument_consumer.py:230-250`, alias prompt in `prompts/` | Alias generation produces ≥3 aliases for top-50 financial_instrument entities (currently ~0). |
| **A-8** | Add `entity_class_coverage_ratio` Prometheus gauge: at startup, S7 queries `SELECT entity_type, count(*) FROM canonical_entities GROUP BY entity_type` against the 11 declared GLiNER classes; emits gauge per class and overall ratio. | `services/knowledge-graph/.../infrastructure/metrics/prometheus.py`, S7 startup hook | Gauge emitted; alert rule fires if ratio < 1.0. |
| **A-9** | Add `kg_extraction_yield` Prometheus gauge in `article_consumer`: ratio of (`raw_relations` length / `extraction.relations` length) per article, exported as histogram. | `services/nlp-pipeline/.../article_consumer.py`, prometheus metrics module | Gauge visible in Prometheus; values cluster ≥ 0.90 after A-1. |

**Validation**:
- `python -m pytest services/nlp-pipeline/tests/ -v` (unit + integration: ≥95% pass; new tests for A-1/A-2/A-3/A-7).
- `python -m pytest services/knowledge-graph/tests/ -v`.
- 24h dev-stack soak: `make dev` + seeded ingest, then check `kg_extraction_yield`, `mention_resolutions` count, `llm_usage_log` count.

**Wave A exit gate**: All 9 tasks pass acceptance; phase invariants hold; no new lint/mypy errors; ruff-format clean.

---

### Wave B — Canonical Coverage Seeding

**Wave intent**: Cover the 7 GLiNER entity classes that currently have zero canonicals. Without this, even a perfectly-fixed pipeline (Wave A) cannot resolve mentions for ~66% of documents.

**Dependencies**: Wave A (so the resolution that comes next is observable).

**Tasks**:

| ID | Task | Source | Acceptance |
|---|---|---|---|
| **B-1** | Seed `regulatory_body` canonicals from a curated list (SEC, FDIC, FINRA, OCC, CFTC, FRB, FHFA, ESMA, FCA, BaFin, MAS, JFSA, RBI, SEBI, CSRC; ~25 globally relevant). Include aliases (full name + acronym + common variants). | Hand-curated CSV in `infra/seeds/regulatory_bodies.csv`; one-shot Alembic data migration | Stage-1 alias-exact resolution rate for `regulatory_body` mentions ≥ 70% after 24h ingest. |
| **B-2** | Seed `currency` canonicals from ISO 4217 codes (top 50 by trading volume); aliases include code + name + symbol. | `infra/seeds/currencies.csv` | Stage-1 resolution rate for `currency` ≥ 90%. |
| **B-3** | Seed `government_body` from ~50 most-mentioned-in-finance bodies (US Treasury, ECB, BoJ, PBoC, Fed, BoE, RBA, IMF, World Bank, WTO, etc.). Aliases include acronym + full name. | `infra/seeds/government_bodies.csv` | Stage-1 resolution rate for `government_body` ≥ 60%. |
| **B-4** | Seed `macroeconomic_indicator` (CPI, PPI, GDP, Unemployment, NFP, ISM, PMI, JOLTS, Retail Sales, Housing Starts, Industrial Production, FOMC Rate Decision, etc.; ~30). | `infra/seeds/macro_indicators.csv` | Stage-1 resolution for macro mentions ≥ 75%. |
| **B-5** | Seed `index` canonicals (S&P 500, Dow, Nasdaq Composite, Russell 2000, FTSE 100, DAX, Nikkei 225, Hang Seng, MSCI World, etc.; ~25). Aliases include common shorthand. | `infra/seeds/indices.csv` | Stage-1 resolution for `index` mentions ≥ 80%. |
| **B-6** | Seed `commodity` (WTI Crude, Brent, Gold, Silver, Copper, Natural Gas, Wheat, Corn, Soybeans, etc.; ~20). | `infra/seeds/commodities.csv` | Stage-1 resolution ≥ 80%. |
| **B-7** | `person` and `location` are unbounded; do NOT pre-seed. Instead, increase Stage-3 (fuzzy) and Stage-4 (ANN) tolerance for these classes by 0.05 each, and rely on `UnresolvedResolutionWorker` (post-A-5) to promote. | Resolution config | Person/location resolution ≥ 25% (vs current 0.4% / 0.1%). |
| **B-8** | Seed `financial_institution` from a pre-built list of top 200 globally significant banks/asset managers/exchanges (G-SIBs + top 50 asset managers + major exchanges). | `infra/seeds/financial_institutions.csv` | Stage-1 resolution ≥ 50%. |
| **B-9** | Add seed health-check script: `scripts/check_canonical_coverage.py` that fails CI if any of the 11 classes has < 5 canonicals. | `scripts/`, CI workflow | Script runs in CI; passes after B-1..B-8. |

**Validation**:
- 24h dev-stack soak post-seed; check resolution rate per entity class via SQL or Grafana.
- `entity_class_coverage_ratio` gauge (from A-8) = 1.0.
- Sample 50 articles randomly; verify ≥80% have at least 2 resolved entities.

**Wave B exit gate**: All seeds applied; document-level resolution rate ≥ 50% (vs 34% baseline); no class with 0 canonicals.

---

## Phase 2 — Make it Measurable

**Phase entry gate**: Phase 1 invariants holding for 7 days continuous.
**Phase exit gate**: Eval framework returns NDCG@10, MRR, P@5 on a golden 50-query set with all three above 0.50; hybrid retrieval is live; source-specific recency in production.

---

### Wave C — Offline Evaluation Framework

**Wave intent**: Build the measurement substrate that gates all subsequent retrieval changes. Without it, every change in Phase 3 is faith-based.

**Dependencies**: none (parallel to Wave D start, but Wave D's changes must be measured by C).

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **C-1** | Create `tests/eval/golden/` golden set: 50 finance-domain queries with graded relevance labels (0=irrelevant, 1=marginal, 2=relevant, 3=highly-relevant) on the top-50 candidates returned by current retrieval. Hand-label with the help of Claude (each label requires brief justification). Cover all 8 query intents proportionally. |  Golden set committed; ≥50 queries, ≥10 graded candidates each. |
| **C-2** | Build `scripts/eval_retrieval.py` that runs the golden set through the live retrieval pipeline and computes NDCG@10, MRR, P@5, Recall@20, source diversity. Output CSV + JSON for trend tracking. | Script runs end-to-end; produces report; takes < 5min. |
| **C-3** | CI gate: PR touching `services/rag-chat/`, `services/nlp-pipeline/.../embeddings.py`, or `services/knowledge-graph/.../search.py` must run `eval_retrieval.py` and fail if NDCG@10 drops > 0.03 from `main` baseline. | GitHub Actions workflow added; baseline committed; gate enforces on test PR. |
| **C-4** | Live retrieval-quality metrics in Prometheus: `rag_retrieval_score_distribution` (histogram by source), `rag_reranker_position_change` (gauge: % of queries where reranker top-1 ≠ fusion top-1), `rag_source_contribution` (counter labeled by source). | Metrics visible; baseline values logged. |
| **C-5** | Citation-accuracy audit job (cron): weekly sample of 50 chat responses; LLM-as-judge scores citation→source relevance; emits `rag_citation_accuracy` gauge. | Cron registered; first run logs baseline. |

**Validation**: NDCG@10 baseline measured on current pipeline; expected ≈ 0.45-0.55 given Phase 1 fixes. Document baseline in plan.

---

### Wave D — Hybrid Retrieval (BM25 + ANN + RRF)

**Wave intent**: Add lexical search and combine with semantic ANN via Reciprocal Rank Fusion. Single highest-leverage retrieval change after Phase 1.

**Dependencies**: Wave C live (so D's improvement is measurable).

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **D-1** | Alembic migration on `nlp_db.chunks`: add `tsv` column `tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`. Backfill via SQL (no application change). Add GIN index `chunks_tsv_gin`. Validate forward-compat. | Migration applied; row count of `tsv IS NOT NULL` = chunk count; index size reported. |
| **D-2** | Update `enhanced_chunk_search.py`: add `lexical_search(query, top_k)` that runs `ts_rank_cd(tsv, websearch_to_tsquery('english', $1)) DESC LIMIT $2`. Returns same shape as `ann_search`. | Unit test: query "SEC 10-K Apple" returns Apple-10K chunks ranked first. |
| **D-3** | Implement RRF fusion in `fusion.py`: `RRF(d) = 1/(k + rank_bm25(d)) + 1/(k + rank_ann(d))` with `k=60`. Replace pure ANN in chunk-source path. Keep ANN-only as fallback for queries with < 3 tokens. | Hybrid path active for FACTUAL/COMPARISON/REASONING intents; ANN-only for SIGNAL_INTEL. |
| **D-4** | Eval gate (via Wave C): NDCG@10 must improve by ≥ 0.05 vs Phase-1 baseline; MRR by ≥ 0.04. | Numbers reported in PR; passes gate. |
| **D-5** | Doc updates: `services/rag-chat/.claude-context.md`, `docs/services/rag-chat.md`, `docs/MASTER_PLAN.md` retrieval section. | Docs reflect hybrid path. |

**Wave D exit gate**: Hybrid live in production retrieval; Wave C metrics show NDCG@10 ≥ 0.55, MRR ≥ 0.65.

---

### Wave E — Routing & Recency Hardening

**Wave intent**: Make `routing_decisions.composite_score` reflect reality (not constants), and stop penalising SEC filings with news-rate decay.

**Dependencies**: Wave A (so signals are persisted post-novelty).

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **E-1** | Fix F-MAJOR-02: `PriceImpactLabellingWorker` 401. Trace the auth header mismatch (likely missing internal JWT for cross-service S6→S2 call); add `X-Internal-JWT` header per BP-258. | Worker successful run rate ≥ 95%; `price_impact` non-zero on ≥30% of articles. |
| **E-2** | Fix `watchlist` signal: hydrate Valkey set `s6:routing:watchlist:tickers` from S1 portfolio data (`PortfolioWatchlistsRepo.list_all_tickers()`) on a 5-minute cron. | Set non-empty; signal contributes to ≥20% of articles. |
| **E-3** | Replace `source_reliability=0.5` hardcode with lookup against trust_weights table (already exists conceptually in `retrieval_orchestrator.DEFAULT_TRUST_WEIGHTS`); externalize to `routing_source_trust` Alembic-managed config table. | Per-source values in DB; signal varies (SEC=0.95, news=0.65, etc.). |
| **E-4** | Replace `document_type=0.5` with rule-based mapping (FILING=0.9, EARNINGS=0.85, NEWS=0.6, BLOG=0.4) on `document_source_metadata.source_type`. | Signal varies by source. |
| **E-5** | Implement source-specific recency decay (S-3 from 04-23 audit): table `recency_decay_rates` (`source_type`, `decay_rate`); SEC=0.0005, earnings=0.001, news=0.02; update `chat.py:compute_recency_score()` to take `source_type`. | Test: SEC chunk older than 1 year still has recency_score > 0.8; news chunk older than 30 days has recency_score < 0.5. |
| **E-6** | Add `display_relevance_score` audit logging: every read logs `(market_score, llm_score, routing_score, fallback_path)` to track which fallback path is hit. | Prometheus counter `news_display_score_path_total{path}` shows distribution; "all-three-present" path increases over time. |

**Wave E exit gate**: ≥6 of 8 routing signals dynamic for ≥90% of articles; SEC chunks no longer drop out of top-30 due to age; display_relevance_score full-formula path ≥ 30% of reads.

---

## Phase 3 — Strategic Uplift

**Phase entry gate**: NDCG@10 ≥ 0.60, MRR ≥ 0.70 on golden set; Phase 2 invariants stable for 7 days.

---

### Wave F — Knowledge Compilation Layer (Karpathy Wiki applied)

**Wave intent**: Compile entity intelligence at ingest time so RAG can query compiled summaries before re-searching raw chunks.

**Dependencies**: Phase 1 + 2 complete (relations and resolutions need to flow into the layer).

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **F-1** | Alembic migration: create `entity_summaries` table per the schema in §3.2 of the revised audit (PRIMARY KEY `entity_id`, fields: one_liner, long_summary, key_relations JSONB, key_claims JSONB, key_events JSONB, fundamentals_blob, contradiction_count, evidence_doc_ids, embedding vector(1024), generated_at, prompt_version, llm_model_id, llm_cost_usd). HNSW index on embedding. | Migration applied; index size confirmed. |
| **F-2** | Implement `EntitySummaryCompilationWorker` (S7) consuming `entity.dirtied.v1`. Pulls entity's relations, top claims, recent events, fundamentals; calls Llama-3.1-8B with structured prompt; writes row + emits embedding. Idempotent on `(entity_id, prompt_version, generated_at_day)`. | Worker registered; 50 sample entities processed; rows visible. |
| **F-3** | Add `EntitySummaryRepo.search_by_query_embedding(emb, top_k=5)` HNSW ANN. | Unit test passes. |
| **F-4** | Wire into RAG: new Step 8.0 in `retrieval_orchestrator.py` — for each resolved entity in the query (from Step 5), fetch its `entity_summaries` row directly; inject as a high-priority context source (`source_type='entity_summary'`, trust_weight=0.92). Skips chunk_search if entity-anchored intent (FACTUAL_LOOKUP, FINANCIAL_DATA) and summary is present. | RAG uses summaries when available; chunk source still used for non-entity-anchored intents. |
| **F-5** | Eval (via Wave C): NDCG@10 ≥ 0.65; latency p95 ≤ 2.5s on entity-anchored queries (faster due to skipping chunk search). | Numbers reported. |
| **F-6** | Add Valkey hot cache (`E-15` from revised audit): `kg:v1:entity:{id}` key with 1-hour TTL caching the compiled summary + top-3 relations + 3 most recent news. Used by both RAG and the entity page. | Cache hit rate ≥ 60% on hot entities. |

---

### Wave G — Cypher Activation + Path Scoring + AGE Population

**Wave intent**: Make multi-hop graph reasoning real.

**Dependencies**: Phase 1 (graph must have data) + Wave F (entity summaries exist for path endpoints).

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **G-1** | Run AGE shadow full sync manually: `kubectl exec` (or local equivalent) into S7, trigger `AgeSyncWorker.run_full_sync()` once with `watermark=epoch`. Verify node and edge counts match SQL. | `MATCH (n) RETURN count(n)` ≥ canonical_entities count; edges ≥ relations row count. |
| **G-2** | Set `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` in dev `docker.env`. Set `cypher_enabled=True` default in `RetrievalPlanBuilder.__init__()` (or read from env). | Flag flipped; Cypher endpoint returns 200, not 503. |
| **G-3** | Implement weighted path scoring in `cypher_path.py:_path_confidence()`: replace `prod(edge.confidence)` with `sum(edge.confidence × edge_type_weight × recency × log1p(evidence_count)) / path_length`. Edge-type weights from new `relation_type_registry.importance_weight` column. | Test: path with 3 high-conf SEC-derived edges scores higher than 3 low-conf news-derived edges. |
| **G-4** | Add Cypher latency monitoring + circuit breaker tightening. Alert if `cypher_query_duration_seconds_p95 > 4s`. | Dashboard panel; alert rule. |
| **G-5** | Expand graph context injection: `context_assembler.py:83` truncation from 200 → 800 chars; include relation type and evidence count alongside summary. | Sample chat showing richer graph context. |
| **G-6** | Eval (Wave C): RELATIONSHIP-intent queries show NDCG@10 ≥ 0.55 (vs Phase-2 ANN-only baseline). | Numbers reported. |

---

### Wave H — Ontology, Temporal, Observability Dashboards

**Wave intent**: The remaining strategic items. Smaller scope, but each closes a specific maturity gap.

**Tasks**:

| ID | Task | Acceptance |
|---|---|---|
| **H-1** | Ontology enforcement (M-5 from 04-23 audit): add `valid_subject_types`, `valid_object_types` to `relation_type_registry`. Block 12a filters invalid triples (e.g., person `manufactures` commodity) before materialization. Emit `kg_ontology_rejection_total{reason}` counter. | Test: a `(person, manufactures, commodity)` triple is filtered. |
| **H-2** | Partial temporal KG (subset of L-5): add `valid_from`, `valid_to` (nullable) to `relations`. Populate from event-window evidence when available. Cypher path query supports optional `as_of=<date>`. | Test: querying CEO of Apple `as_of='2010-01-01'` returns Steve Jobs, `as_of='2024-01-01'` returns Tim Cook. |
| **H-3** | Entity observability dashboard (M-6): Grafana board with embedding NULL rate, resolution confidence distribution, extraction yield by source, provider quota utilization, AGE sync lag, llm_usage cost-per-day. | Dashboard imported; baseline visible. |
| **H-4** | Citation→evidence backtrace UI (E-8): every chat citation links to chunk + relation_evidence row. | UI ships; spot-check 5 citations. |
| **H-5** | Source-type filter in chat (E-9): chat composer exposes FILINGS / NEWS / EARNINGS / PORTFOLIO chips; filter applied at retrieval. | UI ships; e2e test. |
| **H-6** | Entity suggest API (E-12): GIN trigram index + `GET /api/v1/entities/suggest?q=...&limit=10`. | p95 latency < 100ms; integrated into search bar. |
| **H-7** | KG contract test in CI (E-1): ingest 5 fixed test articles with known entities; assert end-to-end relation count > 0 per article. Fails PR if regression. | Test runs in CI; gate enforces. |

---

## Cross-Cutting: Compounding Updates

Each wave commit updates:
- `docs/plans/TRACKING.md` — status row for PLAN-0057
- `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` Section 5 — maturity re-rating
- `docs/MASTER_PLAN.md` — relevant subsection (KG, retrieval, eval framework as they ship)
- `services/<service>/.claude-context.md` — pitfalls discovered during implementation
- `docs/BUG_PATTERNS.md` — new patterns (BP-292/293/294 already added; expect more)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Wave A fix introduces regressions in already-shipped E2E tests | Medium | Medium | Run full S6+S7 test suites + 24h soak before merge |
| Backfill migration in A-2 conflicts with concurrent ingest | Low | High | Migration uses advisory lock matching `entity_consumer`'s lock pattern |
| Wave C golden set is biased toward English/finance and inflates measured NDCG | Medium | Medium | Expand golden set in Wave F; track NDCG by intent class separately |
| Wave F summary generation cost balloons (LLM token usage) | Medium | Medium | Set per-day budget; cache aggressively; only refresh on `entity.dirtied.v1` |
| Wave G AGE sync hangs on first full run with thousands of edges | Medium | Medium | Run with batch_size=500 and progress logging; can re-run safely (MERGE is idempotent) |
| Hybrid retrieval (Wave D) regresses some intent classes | Medium | Low | Per-intent NDCG tracking in Wave C catches; can disable BM25 for SIGNAL_INTEL specifically |

---

## Out of Scope (explicitly deferred)

- L-2 financial domain embedding model — measure first via Wave C, swap only if NDCG plateau
- L-3 relevance feedback loop — premature for thesis-stage product
- L-4 multi-provider data fusion — tracked in PLAN-0055
- E-10 streaming graph reasoning — Phase 4 if pursued
- E-11 community detection / theme grouping — Phase 4
- Frontend cytoscape.js migration (ADR-F-16) — separate frontend plan; sigma.js adequate for current 1-2 hop use cases

---

## Tracking

Update on every wave completion. Use `/implement` for each wave; `/qa` after each phase.

| Phase | Wave | Status | QA | Date |
|---|---|---|---|---|
| 1 | A | pending | — | — |
| 1 | B | pending | — | — |
| 2 | C | pending | — | — |
| 2 | D | pending | — | — |
| 2 | E | pending | — | — |
| 3 | F | pending | — | — |
| 3 | G | pending | — | — |
| 3 | H | pending | — | — |
