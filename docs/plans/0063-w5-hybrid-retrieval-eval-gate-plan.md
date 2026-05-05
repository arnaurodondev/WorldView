---
id: PLAN-0063
prd: docs/specs/0034-mvp-launch-readiness-program.md
prd_section: "§3 Tier 1 — FR-T1-2; §6 Workstream W5; §7 Sprint Calendar Week 3"
title: "W5 — Hybrid Retrieval (BM25 + ANN + RRF) + Golden Eval CI Gate"
status: draft
created: 2026-05-03
updated: 2026-05-03
plans: 1
waves: 5
tasks: 16
critical_path: "W5-1 → W5-2 → W5-3 → W5-4 → W5-5"
---

# PLAN-0063 — W5: Hybrid Retrieval + Golden Eval CI Gate

## 0. Pre-Flight Summary

**Source workstream**: PRD-0034 §6 Workstream W5 (Hybrid Retrieval + Eval Gate, Tier 1, FR-T1-2). The PRD §6 row points at PLAN-0058 Waves C+D as the implementation target ("already detailed"). PLAN-0060 Sub-Plan B subsequently absorbed those waves with an architecture correction (server-side RRF in S6, not client-side fusion in S8) and has them in `pending` state (B-1, B-2, B-3 — three waves, ~9 tasks at PLAN-0060's level of detail).

**Why this plan exists rather than continuing PLAN-0060 Sub-Plan B**:
1. **PLAN-0060 confused two scopes** — it bundles PLAN-0057 follow-up residuals (Sub-Plan A) with W5 work (Sub-Plan B). PRD-0034 is now the canonical driver and W5 deserves its own plan ID for tracking, QA, and revertability.
2. **The golden set is a stub, not a labeled set.** `tests/eval/golden/queries.jsonl` exists with 50 query rows but every row has `relevant_doc_ids: []` and `entity_ids: []`. The eval cannot compute NDCG@10 against an empty ground-truth. PLAN-0060 T-B1-01 advertised this as "to be hand-labeled" but the labeling work itself was never sized; this plan promotes labeling to a first-class wave with its own validation gate.
3. **Per-intent NDCG breakdown is missing from PLAN-0060.** The CI gate as drafted compares one global NDCG@10 number — but PRD-0034 §3 FR-T1-2 explicitly asks for hybrid behaviour to be intent-aware (SIGNAL_INTEL stays ANN-only). Without per-intent metrics the gate cannot detect regressions confined to a single intent class.
4. **PLAN-0058 Wave E (routing/recency hardening) is part of W5's exit gate** because `display_relevance_score` feeds the news ranking that downstream eval queries rely on. PLAN-0060 B-3 covers it but sits behind Sub-Plan A in the same plan; surfacing it here keeps the W5 scope cohesive.
5. **W5 needs its own QA story** — the LLM-as-judge citation-accuracy audit (PLAN-0058 Wave C-5) is missing from PLAN-0060 entirely. Folding it in here closes that gap before we ship.

**Migration path**: On commit of PLAN-0063 Wave W5-1, PLAN-0060 Sub-Plan B will be marked `superseded by PLAN-0063` in TRACKING.md (Sub-Plan A residuals stay under PLAN-0060). PLAN-0058 stays as the historical strategic-uplift document but its Waves C/D/E are likewise marked superseded.

**Coordination boundaries with parallel workstreams**:
- **W4 (Structured AI Brief, PLAN-0062-W4 owner separately)** — W5 owns the runtime LLM-judge citation-accuracy gate (T-W5-5-02 weekly cron emits `rag_citation_accuracy` gauge). W4 narrows to a schema/shape contract test only (no runtime accuracy gate, no LLM-judge). W5-1 and W5-2 must finish before W4 wires its schema/shape contract test. Otherwise no shared files.
- **W6 (Full-Text Search, PLAN-0064 owner separately)** — W6 introduces a search route over articles + filings + transcripts. **W5 owns the `chunks` lexical substrate; W5-2 advertises the following outputs that W6 references**:
  - **Table**: `chunks` (in `nlp_db`)
  - **Generated column**: `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(chunk_text_key, ''))) STORED`
  - **GIN index name**: `ix_chunks_tsv_gin` (SQLAlchemy `ix_` convention; see §0 cross-plan decision below)
  - **tsquery parser**: `websearch_to_tsquery('english', :q)` for both lookup and ranking (see §0 cross-plan decision below)
  - **Migration file**: `services/nlp-pipeline/alembic/versions/0017_add_chunks_tsv_gin.py`
- **W9 (Stability + Observability)** — W5 emits four new Prometheus metrics; W9 adds them to the existing Grafana board for retrieval. No code overlap.
- **W8 (RLS, downstream)** — W5 introduces no cross-tenant aggregation paths (the originally-drafted T-W5-4-02 cross-tenant watchlist endpoint was dropped after audit confirmed the existing event-driven entity-id watchlist already exists; see §0 cross-plan decision below). Therefore W5 does not collide with W8's tenant-isolation work.
- **W1 (KG Remediation, PLAN-0057 closed) and W2 (Universe Expansion, PLAN-0055)** — already shipped; W5 inherits the higher relation/canonical/chunk volumes those waves produced. The eval baseline is measured against the post-W1/W2 state.

---

### Cross-Plan Decisions (locked 2026-05-03 — DO NOT re-litigate during /implement)

These decisions resolve audit findings B-3, B-1, B-2, and the W4↔W5 citation-gate ownership question. They are reflected in every relevant section below.

1. **GIN index name** = `ix_chunks_tsv_gin` (SQLAlchemy `ix_` convention). PLAN-0064 (W6) updates its EXPLAIN ANALYZE assertion to match.
2. **tsquery parser** = `websearch_to_tsquery('english', :q)` for both index lookup and `ts_rank_cd` ranking. PLAN-0064 (W6) standardises on the same helper. Rationale: `websearch_to_tsquery` auto-escapes user input (matching `plainto_tsquery`'s injection-safety property) AND supports operator syntax (`-Android`, quoted phrases) needed by W5-2 test cases.
3. **W4 ↔ W5 citation gate ownership** = W5 owns the runtime LLM-judge accuracy gate (T-W5-5-02 weekly cron). W4 owns only a schema/shape contract test (every claim-bearing unit — every `lead` sentence containing `[cN]`, every bullet — has at least one resolvable citation; citation resolves to a non-empty snippet; no relevance scoring). W4 does not duplicate the LLM-judge. **Revised 2026-05-03 to acknowledge PRD-0034 §3 FR-T1-1 `lead` field**: claim-bearing units now include the lead-paragraph sentences that contain `[cN]` markers, not bullets only. T-W5-5-02 below extracts per-marker claim spans from both `lead` and `bullets` rather than scoring whole-message text.
4. **Watchlist signal in S6 routing** = the existing event-driven path is canonical and already wired:
   - Valkey key: `nlp:v1:watched_entities` (overridable via `Settings.valkey_watchlist_key`)
   - Set members: **entity UUIDs** (NOT tickers)
   - Population mechanism: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/watchlist_consumer.py:107` consumes `portfolio.watchlist.updated.v1` Avro events and calls `await self._cache.add_entity(entity_id)`.
   - Routing block: `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py:79` accepts `watched_entity_ids: frozenset[UUID]` and matches against `m.resolved_entity_id`.
   - Hydration: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:319` calls `await self._watchlist.get_all_watched()` per article.
   - **The originally-drafted T-W5-4-02 (5-min cron + flat-ticker endpoint) was based on a stale model and is DROPPED.** If empirical observation later shows the watchlist signal is 0 in production, the diagnosis path is: (a) is the watchlist consumer running? (b) is `portfolio.watchlist.updated.v1` Kafka topic receiving events? (c) is `resolved_entity_id` populated on enriched mentions? — none of which a polling cron would address.
5. **Routing source_reliability + document_type signals** = both are already externalised:
   - `source_reliability` is supplied via the `source_trust_weight: float` parameter on `compute_routing_score()` (`services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py:156`), sourced from the `intelligence_db.source_trust_weights` table.
   - `document_type` lives in the `DOCUMENT_TYPE_SIGNAL` dict at `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py:43` with per-source-type values.
   - **The originally-drafted T-W5-4-03 (replace "hardcoded 0.5" with new in-code dicts) was based on a stale model and is DROPPED.** Promotion of these in-code values to a config file or DB-driven seeding is deferred to §15 Follow-ups; revisit only if routing-tuning empirical evidence requires it.
6. **Baseline-first NDCG target** = the +0.05 NDCG@10 absolute-lift target advertised in PRD-0034 §3 FR-T1-2 was set before any baseline existed. **W5-1's first sub-task (T-W5-1-00) establishes the baseline number against the labelled golden set**; the +0.05 lift target is then expressed as **relative to that recorded baseline number** (i.e. `post_hybrid_ndcg ≥ recorded_baseline_ndcg + 0.05`). The CI gate (T-W5-1-04) reads the baseline file and **fails the build if the baseline file is missing or unreadable**. This avoids "+0.05 lift over an empty set" gate semantics.

---

## 1. Pre-Flight Gate

| Check | Result | Note |
|-------|--------|------|
| No unresolved BLOCKING OQs | **PASS** | PRD-0034 §14 BLOCKING items (OQ-1..OQ-4) concern lane/pricing/users/cull. None gate W5 — retrieval and eval are internal capabilities. The DEFERRED OQs (OQ-5..OQ-12) likewise do not block W5. |
| No unverified external API fields | **PASS** | W5 is internal-only. No EODHD/Alpaca/Stripe surfaces touched. |
| No active cross-plan conflicts | **PASS (with supersession)** | PLAN-0060 Sub-Plan B and PLAN-0058 Waves C/D/E describe the same work but at lower fidelity. Both are explicitly marked `superseded by PLAN-0063` on Wave W5-1 commit. PLAN-0060 Sub-Plan A (PLAN-0057 residuals, A-1, A-2 — already DONE) is unaffected. |
| PRD recency | **PASS** | PRD-0034 created 2026-05-02; today is 2026-05-03 (1 day). |
| Architecture compliance | **PASS** | Server-side RRF in S6 honours R7 (no cross-service DB; S8 stays a pure HTTP consumer). Alembic migration for `chunks.tsv` is forward-compatible (additive `GENERATED ALWAYS AS … STORED` column with non-blocking default population for existing rows; on the dev stack `chunks` ≈ 5K rows, backfill is instant). R5/R28 do not apply (no Avro change). R8 untouched (no new dual-write). R9 untouched (no new consumer). R12 (domain isolation) preserved — fusion logic lives in `application/use_cases`, repo in `infrastructure/`. |

---

## 2. Codebase State Verification (Read From Source, 2026-05-03)

| PRD Reference | Type | Service | Actual State (from code) | Target State | Delta |
|---------------|------|---------|--------------------------|--------------|-------|
| `chunks.tsv` | DB column | nlp-pipeline `nlp_db` | does **not** exist (verified `services/nlp-pipeline/alembic/versions/0016_add_last_attempted_at_to_embedding_pending.py` is current head) | `tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(chunk_text_key,''))) STORED` | new migration `0017_add_chunks_tsv_gin.py` |
| `ix_chunks_tsv_gin` | DB index | nlp-pipeline `nlp_db` | does not exist | GIN index on `chunks.tsv` | created in `0017` |
| `ChunkSearchRequest.search_type` | Pydantic field | nlp-pipeline `api/schemas.py:135` | not present (8 fields; current shape verified) | `search_type: Literal["ann","lexical","hybrid"] = "ann"` (default preserves backward compat) | additive schema extension |
| `ChunkSearchRequest` (rag-chat port) | dataclass | rag-chat `application/ports/upstream_clients.py:18` | not present | mirror the new field with same default | additive port extension |
| `ChunkANNRepository.lexical_search()` | repo method | nlp-pipeline `infrastructure/nlp_db/repositories/chunk_search.py:25` | does **not** exist; class has only `ann_search` (line 31), `_search_chunks` (line 80), `_search_sections` (line 156), `fetch_entity_mentions` (line 225) | new `lexical_search()` method | additive |
| `ChunkSearchUseCaseImpl.execute()` routing | use case | nlp-pipeline `application/use_cases/chunk_search.py` | calls `ann_search` directly (verified file present) | dispatch on `req.search_type`: ann / lexical / hybrid (with server-side RRF) | branch + RRF helper |
| `_PlanFlags.use_hybrid_chunks` | dataclass | rag-chat `application/pipeline/retrieval_plan_builder.py:22` | not present (`_PlanFlags` has 9 fields including `use_chunks`, `use_cypher`) | new flag, ANDed with intent (True for FACTUAL_LOOKUP/COMPARISON/REASONING/RELATIONSHIP/FINANCIAL_DATA/GENERAL; False for SIGNAL_INTEL/PORTFOLIO) | additive |
| `_fetch_chunks` `search_type` plumbing | orchestrator | rag-chat `application/pipeline/retrieval_orchestrator.py:174-194` | `ChunkSearchRequest` constructed without `search_type` | pass `search_type="hybrid"` when `plan.flags.use_hybrid_chunks` else `"ann"` | one-line addition |
| `tests/eval/golden/queries.jsonl` | test fixture | repo root | exists, **50 queries, all 50 have `relevant_doc_ids: []`** (verified by `grep -c '"relevant_doc_ids": \[\]'` → 50) — labels are stubs | 50 queries with ≥5 graded candidates each; ≥1 grade=3 per query; per-intent proportions per §W5-1 | **labelling work + schema extension** |
| `scripts/eval_retrieval.py` | script | repo root | does **not** exist | new script computing NDCG@10/MRR/P@5/Recall@20 + per-intent breakdown + baseline diff | create |
| `results/baseline_pre_hybrid.json` | data file | repo root | does not exist | committed baseline NDCG snapshot | create |
| CI eval workflow | config | `.github/workflows/` | does not exist (verified `ls .github/workflows/ \| grep -i eval` returns nothing) | new `retrieval-eval.yml` triggered on touched paths | create |
| `compute_recency_score` | function | rag-chat `domain/entities/chat.py:18` | uniform `exp(-0.005 * days_old)` — single hard-coded rate | source-aware lookup with per-source rates (sec=0.0005, earnings=0.001, news=0.02, default=0.005) | rewrite |
| `nlp:v1:watched_entities` Valkey set | runtime | nlp-pipeline | **already populated event-driven** via `watchlist_consumer.py:107` consuming `portfolio.watchlist.updated.v1`; key is overridable via `Settings.valkey_watchlist_key`; members are entity UUIDs (not tickers) | no change | **no work** — see §0 cross-plan decision #4. The originally-drafted "tickers cron" task was based on a stale codebase model and is dropped. |
| `source_reliability` signal | application code | nlp-pipeline `application/blocks/routing.py:156` | **already externalised** via `source_trust_weight: float` parameter on `compute_routing_score()` (sourced from `intelligence_db.source_trust_weights` table) | no change | **no work** — see §0 cross-plan decision #5. The originally-drafted "replace hardcoded 0.5" task was based on a stale model and is dropped. |
| `DOCUMENT_TYPE_SIGNAL` dict | application code | nlp-pipeline `application/blocks/routing.py:43` | **already externalised** as in-module dict with per-source-type values | no change | **no work** — see §0 cross-plan decision #5. |
| `routing_decisions.final_routing_tier` | DB column | nlp-pipeline `nlp_db` | exists (verified `0015_add_processing_path_to_routing_decisions.py`) but write path may not populate post-novelty values | confirm repo writes both `final_routing_tier` and `processing_path` post-novelty | code audit + fix if missing |
| `news_display_score_path_total` | Prometheus counter | nlp-pipeline | does not exist | new counter labels `{full_formula, no_price_impact, routing_only}` | new metric |
| `rag_retrieval_score_distribution` | Prometheus histogram | rag-chat | does not exist | new histogram labelled by `source` | new metric |
| `rag_citation_accuracy` gauge | Prometheus gauge | rag-chat | does not exist | weekly cron job emits gauge from LLM-as-judge | new cron + metric |

**Tasks gated by deltas above**:
- Every row with Delta ≠ "none" maps to a specific task in W5-1..W5-5 below. The task IDs are listed in the table-of-tasks at the end of each wave so a reviewer can trace each delta to its task.

---

## 3. Plan Dependency Graph

```
W5-1 (Eval Foundation: /v1/internal/retrieve endpoint + golden labels + script + recorded baseline + CI gate)
   ↓ recorded baseline NDCG@10 committed to results/baseline_pre_hybrid.json (T-W5-1-03)
W5-2 (Hybrid Retrieval Schema + Repo)
   ↓ tsvector + GIN index `ix_chunks_tsv_gin` live in nlp_db; lexical_search method ready (using websearch_to_tsquery)
W5-3 (Hybrid Use-Case + S8 Plumbing + RRF)
   ↓ search_type="hybrid" path live; eval gate must show NDCG@10 lift ≥ recorded_baseline + 0.05
W5-4 (Recency Hardening + Routing-Tier Audit)
   ↓ recency now source-aware; routing_decisions.final_routing_tier write path verified
W5-5 (Observability + Citation-Accuracy Cron + Doc Updates)

Strict ordering:
- W5-1 must finish before W5-3 (cannot evaluate hybrid without recorded baseline + script + endpoint)
- W5-2 must finish before W5-3 (lexical_search method needed for hybrid path)
- W5-4 can run in parallel with W5-2/W5-3 (different files; only collides on
  the eval re-run, which W5-4 must pass without regression)
- W5-5 follows all four (depends on metrics + cron infrastructure they create)

Critical path: W5-1 → W5-2 → W5-3 → W5-4 → W5-5
```


---

## 4. Wave W5-1: Eval Foundation — Golden Labels, NDCG Script, CI Gate

**Goal**: Build the measurement substrate before changing retrieval. The 50-query golden set must be properly labelled, `scripts/eval_retrieval.py` must compute NDCG@10/MRR/P@5/Recall@20 with per-intent breakdown, the rag-chat service must expose a read-only `/v1/internal/retrieve` endpoint for the eval script to call over HTTP, the baseline NDCG@10 number must be captured into a committed JSON file (so the +0.05 lift target in PRD-0034 §3 FR-T1-2 becomes a number-relative-to-recorded-baseline rather than an absolute floor), and a CI workflow must fail PRs that regress NDCG@10 by ≥3% (absolute) on any retrieval-touching path. The CI gate also fails if `results/baseline_pre_hybrid.json` is missing or unreadable.

**Depends on**: none (parallel-safe entry point)
**Blocks**: W5-3 (cannot run hybrid eval gate without this)
**Estimated effort**: 7–9 hours (labelling is the long pole; +1h for `/v1/internal/retrieve` endpoint)
**Architecture layer**: test infrastructure + CI + rag-chat read-only API

---

### T-W5-1-00: Add `POST /v1/internal/retrieve` endpoint to rag-chat (read-only, no LLM call)

**Type**: impl
**depends_on**: none
**blocks**: T-W5-1-02 (script consumes this endpoint), T-W5-1-03 (baseline capture uses it)
**Target files**:
- `services/rag-chat/src/rag_chat/api/routers/chat.py` (or new `routers/internal.py`) — new endpoint
- `services/rag-chat/src/rag_chat/api/schemas.py` — request/response Pydantic models
- `services/rag-chat/tests/integration/test_internal_retrieve.py` (new — endpoint smoke + JWT enforcement)

**PRD reference**: §3 FR-T1-2 (eval gate is gated on a callable retrieval endpoint)

**What to build**:

A read-only endpoint that runs the existing `ParallelRetrievalOrchestrator` end-to-end **without** invoking the chat LLM, returning the ranked candidate list (top-20 chunks + relevant entity-keyed metadata) so the eval script can call it via HTTP rather than importing the orchestrator with full DI in-process.

**Endpoint surface**:
- Path: `POST /v1/internal/retrieve`
- Auth: `InternalJWTMiddleware` (already wired); requires `role=system` or any user JWT
- Request body:
  ```json
  {
    "query_text": "What is Apple's iPhone Q4 guidance?",
    "top_k": 20
  }
  ```
- Response body:
  ```json
  {
    "query_text": "...",
    "intent": "FACTUAL_LOOKUP",
    "candidates": [
      {"doc_id": "<uuid>", "chunk_id": "<uuid>", "rank": 1, "score": 0.87, "source_type": "sec_filing", "snippet": "..."}
    ],
    "n_candidates": 20
  }
  ```
- Implementation: thin wrapper around the existing orchestrator's `retrieve()` method. **Skips the LLM render path entirely** — no `chat_use_case` invocation, no token counting, no streaming.

**Tests**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_internal_retrieve_returns_200_with_candidates` | valid query → 200 + ≥1 candidate | integration |
| `test_internal_retrieve_requires_internal_jwt` | no JWT → 401 | integration |
| `test_internal_retrieve_respects_top_k` | top_k=5 → ≤5 candidates | integration |
| `test_internal_retrieve_returns_empty_for_unparseable_query` | empty `query_text` → 422 (validation) | integration |
| `test_internal_retrieve_does_not_call_chat_llm` | mock chat client → assert it is never invoked | unit (mock) |

**Acceptance criteria**:
- [ ] 5 new tests pass; ruff + mypy clean
- [ ] Endpoint responds in <2s p95 on dev stack (no LLM call → fast)
- [ ] Endpoint reuses existing `ParallelRetrievalOrchestrator` DI graph (no new wiring)
- [ ] Documented in `docs/services/rag-chat.md` API surface section
- [ ] Eval script (T-W5-1-02) defaults to this endpoint when `--rag-url` flag is set; in-process orchestrator import is **removed** from the script's design (the audit-recommended path)

**Logic & Behavior**:
- This endpoint is `internal` (S9 does NOT proxy it to the public surface); it is reachable only by other internal services with system JWT.
- Returns `intent` so the eval script can sanity-check the intent classifier alongside retrieval (debug-aid, not gate criteria).
- No caching, no rate limiting on the internal route — eval script is the only consumer and runs once per CI pass.

**Downstream test impact**: none (additive endpoint; existing routes unchanged).

---

### T-W5-1-01: Label the 50-query golden set

**Type**: test
**depends_on**: none
**blocks**: T-W5-1-02
**Target files**:
- `tests/eval/golden/queries.jsonl` (rewrite — currently 50 stub rows, all with empty `relevant_doc_ids`/`entity_ids`)
- `tests/eval/golden/README.md` (new — describes JSONL schema, intent proportions, labelling rationale)

**PRD reference**: §3 FR-T1-2 ("50-query golden eval set with NDCG@10 / MRR / P@5 metrics")

**What to build**:
The current file has 50 query rows but no graded labels. This task replaces it with a fully-labelled set following the schema below, with intent proportions matching the rag-chat intent classifier's distribution (audited from `services/rag-chat/src/rag_chat/domain/enums.py:QueryIntent`).

**Schema** (one JSON object per line, all fields required):
```json
{
  "query_id": "q001",
  "query_text": "What is Apple's current iPhone revenue guidance for the next quarter?",
  "intent": "FACTUAL_LOOKUP",
  "entity_ids": ["<canonical_uuid_1>", "<canonical_uuid_2>"],
  "relevant_doc_ids": [
    {"doc_id": "<uuid>", "relevance": 3, "rationale": "Apple Q4 guidance press release; direct hit"},
    {"doc_id": "<uuid>", "relevance": 2, "rationale": "earnings call transcript with guidance discussion"},
    {"doc_id": "<uuid>", "relevance": 1, "rationale": "analyst note referencing guidance"}
  ],
  "notes": "Should surface earnings calls and most recent guidance documents."
}
```

**Relevance scale**:
- `0` — irrelevant (not a candidate; only used implicitly via "any non-listed doc has relevance 0")
- `1` — marginally relevant (mentions topic but not direct answer)
- `2` — relevant (substantive content on the asked entity/topic)
- `3` — highly relevant (direct answer; primary source)

**Intent proportions** (50 queries total — revised 2026-05-03 per Sam-alignment audit). PRD-0034 §2 persona "Sam the Analyst" pain is *finding the relevant claim across sources* — i.e. FACTUAL_LOOKUP / COMPARISON / REASONING dominate his real workload. The original mix sent 24% of queries (RELATIONSHIP + SIGNAL_INTEL + PORTFOLIO) to intents that bypass the hybrid path (per `application/blocks/intent_routing.py` SIGNAL_INTEL stays ANN-only, RELATIONSHIP/PORTFOLIO bypass chunks entirely), so the gate measured hybrid behaviour against a workload where 12/50 queries never used hybrid. Rebalanced so 38/50 queries (76%) actually exercise the hybrid path:
- 16 × `FACTUAL_LOOKUP` (specific company facts) — was 12
- 10 × `COMPARISON` (compare two companies/sectors) — was 8
- 10 × `REASONING` (causal — "why did X happen") — was 8
- 6 × `FINANCIAL_DATA` (earnings, ratios, price-history queries) — was 10 (still hybrid-eligible; trimmed because Sam's financial-data queries route to S7 batch endpoints, not chat retrieval)
- 4 × `RELATIONSHIP` (graph-anchored — "who supplies Apple?") — was 6
- 2 × `SIGNAL_INTEL` (sentiment / market-impact reads) — was 4
- 2 × `PORTFOLIO` (portfolio-context queries) — unchanged

**Phrasing requirement** (added 2026-05-03 per Sam-alignment audit): ≥80% of the 50 queries MUST be phrased as analyst-research questions per PRD-0034 §2 (e.g. "What's the latest on AAPL guidance?", "How have NVDA gross margins evolved?"); ≤2 queries reference intraday or tick-level information (out-of-persona for Sam — those are L2 day-trader queries). The labelling procedure below adds a `phrasing_audit` checkbox to each row.

**Labelling procedure**:
1. For each query, run the live retrieval pipeline (rag-chat `ParallelRetrievalOrchestrator.retrieve(query, top_k=20)`) on the dev stack populated with W1+W2 data.
2. Inspect each of the top-20 candidates' `(doc_id, title, source_type, snippet)`.
3. Hand-grade each candidate `0/1/2/3`. Record `rationale` (≤120 chars) for every row with `relevance ≥ 1`. (Rationale is required so a reviewer can audit the label without re-running retrieval.)
4. **Each query must have at least 5 graded candidates and at least one row with `relevance = 3`.** Queries that cannot meet this bar are dropped and replaced from a backlog of 80 candidate queries (see step 6).
5. Resolve `entity_ids` for every query that names entities (look up canonical UUID via `SELECT id FROM canonical_entities WHERE label ILIKE '<name>'` on intelligence_db). Empty list is allowed for non-entity queries.
6. **Backlog of replacement queries**: maintain `tests/eval/golden/_backlog.jsonl` with up to 30 unlabelled queries. When a primary query is dropped (step 4), promote one from backlog. Backlog file is checked in but not used by the eval script.

**Acceptance criteria**:
- [ ] `tests/eval/golden/queries.jsonl` has exactly 50 rows; each parses as valid JSON
- [ ] `query_id` is unique across rows (regex `^q[0-9]{3}$`)
- [ ] Per-intent counts exactly match the proportions above (assert in T-W5-1-02 script)
- [ ] Every row has ≥5 entries in `relevant_doc_ids` with at least one `relevance == 3`
- [ ] Every `relevant_doc_ids[].rationale` is ≤120 chars
- [ ] `tests/eval/golden/README.md` documents the schema, the relevance scale, the intent proportions, and the labelling procedure
- [ ] `entity_ids` UUIDs all resolve to existing rows in `canonical_entities` (verify with a one-shot SQL spot-check)

**Downstream test impact**: none (new file content, no consumers yet — T-W5-1-02 is the first consumer).

---

### T-W5-1-02: `scripts/eval_retrieval.py` — NDCG/MRR/P@5/Recall + per-intent breakdown

**Type**: impl
**depends_on**: T-W5-1-00, T-W5-1-01
**blocks**: T-W5-1-03
**Target files**:
- `scripts/eval_retrieval.py` (new)
- `tests/scripts/test_eval_retrieval.py` (new — unit tests for the metric functions)

**PRD reference**: §3 FR-T1-2 + §4 NFR ("Golden-eval NDCG@10 ≥ +0.05 absolute over ANN-only; CI-gated")

**What to build**:
A standalone Python script that:
1. Loads the labelled golden set from `tests/eval/golden/queries.jsonl`.
2. For each query, calls the rag-chat read-only retrieval endpoint over HTTP at `${RAG_CHAT_URL}/v1/internal/retrieve` (the endpoint built in T-W5-1-00). The HTTP path is the **only** supported execution path — there is no in-process orchestrator import fallback (this was an audit-deferred design decision; `--rag-url` is required, and the script exits 2 with a clear error message if the URL is unreachable).
3. Receives top-20 ranked `doc_id` list per query.
4. Computes per-query: NDCG@10, MRR, P@5, Recall@20.
5. Aggregates: mean ± std + per-intent breakdown + per-source-type contribution counts.
6. Optional baseline-diff: when `--baseline <path>` provided, compares each metric to baseline; exits 1 if NDCG@10 drops by `--fail-on-regression` (default 0.03) — and additionally exits 1 if any individual intent's NDCG@10 drops by ≥0.05 (intent-level guardrail).
7. Writes `results/eval_<UTC-ISO8601-timestamp>.{csv,json}` with full per-query rows; prints summary block to stdout.

**Metric definitions (canonical, from IR literature)**:
```python
def dcg(relevances: list[float], k: int) -> float:
    """DCG@k using gain = (2^rel - 1) / log2(rank + 1) for rank in 1..k."""
    return sum((2 ** r - 1) / math.log2(rank + 1) for rank, r in enumerate(relevances[:k], start=1))

def ndcg_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 10) -> float:
    """Normalised DCG@k. retrieved is ranked doc_id list; relevant maps doc_id -> grade (0..3)."""
    gains = [float(relevant.get(doc_id, 0)) for doc_id in retrieved[:k]]
    ideal = sorted(relevant.values(), reverse=True)[:k]
    actual_dcg = dcg(gains, k)
    ideal_dcg = dcg([float(g) for g in ideal], k)
    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0

def mean_reciprocal_rank(retrieved: list[str], relevant: dict[str, int]) -> float:
    """First rank where relevance >= 1; 0.0 if no relevant doc retrieved."""
    for rank, doc_id in enumerate(retrieved, start=1):
        if relevant.get(doc_id, 0) >= 1:
            return 1.0 / rank
    return 0.0

def precision_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 5) -> float:
    """Fraction of top-k with relevance >= 1."""
    if not retrieved or k == 0:
        return 0.0
    hits = sum(1 for doc_id in retrieved[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / k

def recall_at_k(retrieved: list[str], relevant: dict[str, int], k: int = 20) -> float:
    """Fraction of all relevant docs that appear in top-k."""
    total_relevant = sum(1 for v in relevant.values() if v >= 1)
    if total_relevant == 0:
        return 0.0
    hits = sum(1 for doc_id in retrieved[:k] if relevant.get(doc_id, 0) >= 1)
    return hits / total_relevant
```

**CLI surface**:
```
python scripts/eval_retrieval.py \
  [--golden tests/eval/golden/queries.jsonl] \
  [--baseline results/baseline_pre_hybrid.json] \
  [--fail-on-regression 0.03] \
  [--output-dir results/] \
  [--rag-url http://localhost:8003] \
  [--top-k 20] \
  [--verbose]
```

**Output schema** (`results/eval_<ts>.json`):
```json
{
  "timestamp": "2026-05-03T14:00:00Z",
  "git_sha": "abc123",
  "golden_set_path": "tests/eval/golden/queries.jsonl",
  "n_queries": 50,
  "summary": {
    "ndcg_at_10": {"mean": 0.523, "std": 0.084},
    "mrr": {"mean": 0.612, "std": 0.131},
    "p_at_5": {"mean": 0.44, "std": 0.18},
    "recall_at_20": {"mean": 0.71, "std": 0.14}
  },
  "by_intent": {
    "FACTUAL_LOOKUP": {"n": 12, "ndcg_at_10": 0.61, "mrr": 0.70, "p_at_5": 0.52, "recall_at_20": 0.78},
    "FINANCIAL_DATA": {"n": 10, "ndcg_at_10": 0.55, ...},
    "...": {}
  },
  "per_query": [
    {"query_id": "q001", "intent": "FACTUAL_LOOKUP", "ndcg_at_10": 0.66, "mrr": 1.0, "p_at_5": 0.6, "recall_at_20": 0.83, "retrieved_top_5": ["doc1", "doc2", "doc3", "doc4", "doc5"]}
  ],
  "source_contribution": {"sec_filing": 47, "earnings_transcript": 32, "eodhd_news": 121, "...": 0}
}
```

**Unit tests for the metric functions** (`tests/scripts/test_eval_retrieval.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_ndcg_perfect_ranking_returns_1` | retrieved order = ideal order → NDCG = 1.0 | unit |
| `test_ndcg_inverted_ranking` | reversed ideal → NDCG < 1.0 with expected value | unit |
| `test_ndcg_no_relevant_docs_returns_0` | empty `relevant` dict → NDCG = 0.0 | unit |
| `test_mrr_first_hit_at_rank_3` | first relevant at rank 3 → MRR = 1/3 | unit |
| `test_mrr_no_relevant_returns_0` | no rank has relevance ≥ 1 → MRR = 0.0 | unit |
| `test_precision_at_5_three_hits` | 3 of top-5 are relevant → P@5 = 0.6 | unit |
| `test_recall_at_20_with_2_of_5_relevant_in_top_20` | 2 of 5 relevant docs found → Recall@20 = 0.4 | unit |
| `test_load_golden_set_validates_intent_proportions` | mismatched intent counts in JSONL → raises | unit |
| `test_load_golden_set_rejects_query_without_grade_3` | a query with no relevance=3 row → raises | unit |
| `test_baseline_regression_triggers_exit_1` | NDCG@10 drops 0.05 from baseline → script exits 1 | integration (script invoked via subprocess with mocked retrieval) |

**Acceptance criteria**:
- [ ] Script runs end-to-end on dev stack in <5 minutes (50 queries × ~5s each)
- [ ] Produces both `.csv` (one row per query) and `.json` (full structured output) under `results/`
- [ ] Stdout prints a 4-line summary: `NDCG@10: 0.523 ± 0.084 | MRR: 0.612 | P@5: 0.44 | Recall@20: 0.71` then a per-intent table
- [ ] `--fail-on-regression 0.03` exits 1 when global NDCG@10 drops ≥0.03 from baseline
- [ ] Per-intent regression guardrail exits 1 when any intent's NDCG@10 drops ≥0.05
- [ ] All 10 unit tests pass
- [ ] ruff + mypy clean
- [ ] Script does **not** require Docker — works against an already-running dev stack

**Logic & Behavior**:
- If `--baseline` is omitted: produce report only, exit 0.
- If `--baseline` points at a file that does not exist: warn (`baseline_missing`) but exit 0 — first run is by definition the baseline.
- Use `httpx.AsyncClient(timeout=httpx.Timeout(30.0))` per **BP-235** to avoid silent 5s timeouts.
- Retrieval errors per-query (HTTP 5xx, timeout) are recorded with `metric_value=NaN` for that query and excluded from the mean — but counted in stdout warning. If >5 queries fail, exit 1 (retrieval is broken, not a regression).
- When extracting `doc_id` from rag-chat response, normalise to lowercase UUID string for stable comparison with golden set (golden labels carry lowercase UUIDs).

**Downstream test impact**: none (script is a new tool; no consumers).

---

### T-W5-1-03: Capture baseline + commit `results/baseline_pre_hybrid.json` (ANCHORS the +0.05 lift target)

**Type**: test
**depends_on**: T-W5-1-02
**blocks**: T-W5-1-04, W5-3
**Target files**:
- `results/baseline_pre_hybrid.json` (new — generated artifact, **must** be committed)
- `tests/eval/golden/README.md` (append a "Baseline as of <date>" section)
- `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md` (this file — fill in the baseline number in the §11 tracking table once measured)

**Why this is gated by W5-2/W5-3**: this baseline is captured on the **current ANN-only retrieval path** before the hybrid changes ship. The `+0.05 NDCG@10` lift target advertised in PRD-0034 §3 FR-T1-2 is interpreted as `post_hybrid_ndcg ≥ recorded_baseline_ndcg + 0.05` (relative to the number written here). Before this task ran, the target was an absolute floor against an unknown number — see §0 cross-plan decision #6.

**What to build**:
1. On a clean dev stack with W1+W2 data flowing for ≥24h and the labelled golden set committed (T-W5-1-01) and the rag-chat `/v1/internal/retrieve` endpoint live (T-W5-1-00), run:
   ```bash
   python scripts/eval_retrieval.py --rag-url http://localhost:8003 --output-dir results/
   ```
2. Rename the resulting `results/eval_<ts>.json` to `results/baseline_pre_hybrid.json` and commit it.
3. Append the baseline summary block (from stdout) to `tests/eval/golden/README.md` under a new section `## Baseline (ANN-only, pre-hybrid, captured <date>)` so the numbers are also reviewable in markdown.
4. **Update §11 tracking table** in this plan to record the captured baseline NDCG@10 value (replace the `*baseline TBD*` placeholder).
5. **Sanity check the +0.05 target against the captured baseline**: if recorded baseline NDCG@10 is ≥0.85 (ceiling effect risk per Spärck Jones-Cormack), or ≤0.20 (the +0.05 lift would be trivial), pause and re-validate the FR-T1-2 lift target with PM/founder before W5-3 begins. Document the outcome in this plan's §12 Open Questions (resolution of OQ-W5-4).

**Acceptance criteria**:
- [ ] `results/baseline_pre_hybrid.json` committed and parseable
- [ ] `summary.ndcg_at_10.mean` is finite and >0.0 (sanity check that retrieval works at all)
- [ ] `tests/eval/golden/README.md` contains the captured baseline numbers
- [ ] `git_sha` field in the baseline JSON matches the HEAD at capture time
- [ ] §11 tracking table in this plan has the baseline NDCG@10 number filled in
- [ ] OQ-W5-4 in §12 is resolved (target re-validated against captured baseline; if baseline outside [0.20, 0.85] range, decision documented)

**Logic & Behavior**:
- This task is **gated by the dev stack having stable W1+W2 data** — verify with a quick SQL: `SELECT count(*) FROM nlp_db.chunks` should be ≥10K. If not, halt and ask the user before proceeding.

**Downstream test impact**: T-W5-1-04 reads this file; T-W5-3-04 (hybrid eval gate) reads this file.

---

### T-W5-1-04: CI workflow — fail PR on retrieval-touching paths regression

**Type**: config
**depends_on**: T-W5-1-03
**blocks**: nothing (but every later wave's PR runs through this gate)
**Target files**:
- `.github/workflows/retrieval-eval.yml` (new)

**PRD reference**: §3 FR-T1-2 + §4 NFR + §11 Test Strategy ("Golden-eval NDCG@10 — PR touching rag-chat or ml-clients — CI fails if NDCG@10 regresses ≥3%")

**What to build**:
GitHub Actions workflow that triggers on PRs touching any of:
- `services/rag-chat/**`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/**`
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/chunk_search.py`
- `libs/ml-clients/**`
- `tests/eval/golden/**`
- `scripts/eval_retrieval.py`

**Job steps**:
1. `actions/checkout@v4` with `fetch-depth: 2` (need parent for diff).
2. Set up Python 3.12 + install repo via Hatch.
3. **Pre-flight check (fails the build if missing)**: assert `results/baseline_pre_hybrid.json` exists and is valid JSON with finite `summary.ndcg_at_10.mean`. Without a baseline file, the +0.05 lift target (and the regression gate) is meaningless. The CI step is a one-liner: `python -c "import json,sys; d=json.load(open('results/baseline_pre_hybrid.json')); v=d['summary']['ndcg_at_10']['mean']; assert v>0, 'baseline NDCG missing or zero'"`.
4. Boot a minimal dev stack subset via `docker-compose -f docker-compose.test.yml --profile retrieval-eval up -d` (a new compose profile to be added in this task — postgres + nlp-pipeline + rag-chat + valkey only; ~90s boot).
5. Wait for `/health` 200 on both services (timeout 120s).
6. Apply alembic upgrade head against nlp_db (so the PR's own migrations are present).
7. Run `python scripts/eval_retrieval.py --rag-url http://localhost:8003 --baseline results/baseline_pre_hybrid.json --fail-on-regression 0.03`.
8. Upload `results/eval_*.json` as a CI artifact (always, even on failure).
9. Tear down compose.

**Bypass mechanism**: commit messages containing `[skip-eval]` short-circuit the job (sets `if:` condition on the run-eval step). Document this in `.github/workflows/retrieval-eval.yml` top-of-file comment.

**Acceptance criteria**:
- [ ] Workflow file lints cleanly (`actionlint` if installed, otherwise `gh workflow view`)
- [ ] Workflow definition committed
- [ ] Manually triggered run on a feature branch finishes in <10 minutes
- [ ] A synthetic regression branch (set `top_k=0` in the orchestrator) triggers a CI failure
- [ ] **Workflow fails the build when `results/baseline_pre_hybrid.json` is missing or has zero NDCG@10** (verified by manually deleting the file on a test branch and confirming red CI)
- [ ] `[skip-eval]` keyword bypass verified
- [ ] `docker-compose.test.yml` has the new `retrieval-eval` profile with only the four services listed above

**Logic & Behavior**:
- Job uses `services:` block in GHA only for postgres (faster than compose-up); the application services come up via compose because they need ML-client config.
- Use Postgres image matching prod (`pgvector/pgvector:pg16`) so tsvector behaviour is consistent.
- The baseline JSON is reread from the PR branch (not main) so a PR that legitimately re-baselines (e.g. a model swap) is not blocked — but the task description in the PR must reference the re-baselining and the baseline diff must be human-reviewed.

**Downstream test impact**:
- `docker-compose.test.yml` gains a new profile; existing profiles (`all`, etc.) untouched. Verify no service-name collisions.
- Existing CI workflows (lint.yml, test.yml) untouched.

---

### Pre-read for Wave W5-1
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (full retrieval flow — to wrap in `/v1/internal/retrieve`)
- `services/rag-chat/src/rag_chat/domain/enums.py` (QueryIntent enum — verify intent names match golden set)
- `services/rag-chat/src/rag_chat/api/routers/chat.py` (existing route shape — for the new `/v1/internal/retrieve` endpoint)
- `services/rag-chat/src/rag_chat/middleware/internal_jwt.py` (or wherever `InternalJWTMiddleware` is wired — confirm new endpoint is covered)
- `tests/eval/golden/queries.jsonl` (current 50 stub rows — preserve `query_id` values where possible)
- `docker-compose.test.yml` (existing profiles for the new `retrieval-eval` profile pattern)
- `.github/workflows/test.yml` (existing CI patterns for the new workflow)

### Validation Gate for Wave W5-1
- [ ] `POST /v1/internal/retrieve` endpoint live; 5 endpoint tests pass (T-W5-1-00)
- [ ] `tests/eval/golden/queries.jsonl` validates per T-W5-1-01 acceptance
- [ ] `python scripts/eval_retrieval.py --rag-url http://localhost:8003 --golden tests/eval/golden/queries.jsonl --output-dir results/` succeeds on dev stack
- [ ] `results/baseline_pre_hybrid.json` committed and contains a finite NDCG@10
- [ ] §11 tracking table updated with captured baseline number; OQ-W5-4 resolved
- [ ] CI workflow definition lints clean and fails the build when baseline file is missing
- [ ] All 10 metric unit tests pass
- [ ] ruff + mypy clean on `scripts/eval_retrieval.py` and the new endpoint files
- [ ] `tests/eval/golden/README.md` documents schema + baseline

### Break Impact for Wave W5-1
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `tests/eval/golden/queries.jsonl` | Schema extends from stub to graded; some test fixtures may load it as a list | Verify (`grep -rn "tests/eval/golden" services/`) — currently no consumers. If any fixture loads it, update to handle the new schema. |
| `docker-compose.test.yml` | New `retrieval-eval` profile added | None — additive. Run `docker compose config --profile retrieval-eval` to validate. |
| `.github/workflows/` | New workflow file | None — additive. |

### Regression Guardrails for Wave W5-1
- **BP-235** (httpx asyncio timeout shadowing): Script's HTTP calls to rag-chat use `httpx.AsyncClient(timeout=httpx.Timeout(30.0))` — explicit, not the default 5s.
- **BP-180** (asyncpg AmbiguousParameterError): not applicable here (script reads JSONL only).
- **BP-127** (pre-commit ruff version mismatch): When committing the script, run `git diff --name-only --cached | grep ".py$" | xargs uvx ruff format --check` first to avoid the phantom-reformat loop.
- **R19** (never delete tests): The 50 stub queries are replaced, not deleted — `query_id` values preserved where possible; the file is rewritten in-place with the same row count and ID continuity.
- **PRD §10 Failure Mode** ("Golden set labels are subjective"): Mitigated by `rationale` field on every relevance ≥1 row (T-W5-1-01) — auditable post-hoc.


---

## 5. Wave W5-2: Hybrid Retrieval — Schema Migration + Lexical Repository

**Goal**: Add the `tsvector` column + GIN index to `nlp_db.chunks` and implement `ChunkANNRepository.lexical_search()` so the hybrid use-case (W5-3) has a working lexical path. No client-facing API surface changes ship in this wave; W5-2 is the storage + repo substrate only.

**Depends on**: none (the alembic migration is independent of W5-1; can run in parallel with W5-1's labelling)
**Blocks**: W5-3
**Estimated effort**: 4–5 hours
**Architecture layer**: infrastructure (migration) + infrastructure (repo)

---

### T-W5-2-01: Alembic migration `0017_add_chunks_tsv_gin.py`

**Type**: schema
**depends_on**: none
**blocks**: T-W5-2-02
**Target files**:
- `services/nlp-pipeline/alembic/versions/0017_add_chunks_tsv_gin.py` (new)

**PRD reference**: §3 FR-T1-2 ("Postgres `tsvector` GIN index for lexical")

**What to build**:
Forward-compatible additive migration. The new `tsv` column is `GENERATED ALWAYS AS … STORED`, which Postgres populates atomically when the column is added — no separate backfill step is needed for existing rows. The dev stack has roughly 5–15K chunk rows (verified pattern from PLAN-0057 audit), so the backfill completes in milliseconds; production-scale planning is out of scope for MVP (R26 does not apply since this is a single-node Postgres instance during MVP launch).

**Migration body**:
```python
"""Add tsvector column + GIN index to nlp_db.chunks for hybrid lexical search.

PLAN-0063 W5-2-01. Forward-compatible additive change.
- New column `tsv` is GENERATED ALWAYS AS STORED (read-only from ORM perspective).
- Postgres populates the column for existing rows during the ALTER TABLE.
- GIN index supports websearch_to_tsquery('english', :q) lookups in <50ms p95.
"""
from __future__ import annotations

from alembic import op

revision = "0017_add_chunks_tsv_gin"
down_revision = "0016_add_last_attempted_at_to_embedding_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN IF NOT EXISTS tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(chunk_text_key, ''))
        ) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chunks_tsv_gin
        ON chunks USING GIN (tsv)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_gin")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv")
```

**Critical constraint — ORM model must NOT declare `tsv`**: The `tsv` column is server-generated (Postgres computes it from `chunk_text_key`). If SQLAlchemy declares it as a regular `Column(TSVECTOR)`, INSERTs via the ORM will fail because Postgres rejects writes to GENERATED columns. The repository's lexical query references the column via raw SQL only — `chunks.tsv` is never read or written through `ChunkModel`. Confirm this constraint with a comment in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` near the existing `ChunkModel` class:

```python
class ChunkModel(Base):
    # ... existing columns ...
    # NOTE: a server-generated column `tsv tsvector GENERATED ALWAYS AS ... STORED`
    # exists on this table from migration 0017_add_chunks_tsv_gin. It is
    # intentionally NOT declared here — declaring it would cause INSERTs to
    # fail because Postgres rejects writes to GENERATED columns.
```

**Acceptance criteria**:
- [ ] `alembic upgrade head` applies cleanly on a freshly-seeded dev nlp_db
- [ ] `alembic downgrade -1` then `alembic upgrade head` round-trip clean (idempotent)
- [ ] `\d chunks` in psql shows the new column with `GENERATED ALWAYS AS ... STORED`
- [ ] `\d chunks` shows the new GIN index named `ix_chunks_tsv_gin` (per §0 cross-plan decision #1; PLAN-0064 W6 will reference this exact name)
- [ ] Smoke SQL: `SELECT count(*) FROM chunks WHERE tsv @@ websearch_to_tsquery('english', 'Apple')` returns >0 on a seeded stack (and finite, not NULL)
- [ ] Comment-block added to `ChunkModel` per above
- [ ] **ORM-no-tsv guard test** added at `services/nlp-pipeline/tests/unit/test_chunk_model_no_tsv.py`: asserts `"tsv" not in {c.name for c in ChunkModel.__mapper__.columns}` with a docstring referencing BP-NEW1. One-line test; prevents future `sqlacodegen`-style regressions from silently re-introducing the column declaration. Audit finding I-5.
- [ ] ruff + mypy clean on the migration file (note: mypy historically does not type-check Alembic migrations — confirm `pyproject.toml` excludes them; if it does not, add `# type: ignore` on the `op.execute` lines)

**Logic & Behavior**:
- **Idempotency**: `IF NOT EXISTS` on both the column add and the index create lets the migration be re-applied without error (matches PLAN-0057 patterns).
- **GIN vs GiST**: GIN is correct for tsvector column queries (faster lookup, slower updates — fine for our write-once-then-read workload).
- **`coalesce(chunk_text_key, '')`**: defends against NULL `chunk_text_key` (rare but possible per existing schema). Without coalesce the GENERATED expression would be NULL and queries would silently miss those chunks.

**Downstream test impact**:
| Broken Test | Why | Fix |
|-------------|-----|-----|
| `services/nlp-pipeline/tests/integration/test_alembic_migrations.py` (if asserts head revision) | head changed from `0016` to `0017` | Update expected head string |
| `services/nlp-pipeline/tests/unit/test_chunk_model.py` (if asserts column count) | `chunks` table gains a column server-side; ORM does not declare it | Verify ORM column count assertion (if any) — should still pass since ORM doesn't see `tsv` |
| Architecture invariant tests | Migrations add new files | None — additive |

---

### T-W5-2-02: `ChunkANNRepository.lexical_search()` method

**Type**: impl
**depends_on**: T-W5-2-01
**blocks**: T-W5-3-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` (extend the existing `ChunkANNRepository` class — line 25)
- `services/nlp-pipeline/tests/integration/test_chunk_lexical_search.py` (new — integration test against test postgres)

**PRD reference**: §3 FR-T1-2

**What to build**:

A new method on the existing `ChunkANNRepository` class that mirrors `ann_search`'s shape (so the use-case can dispatch transparently). Key differences:
- Takes a `query_text: str` argument (not an embedding).
- Uses `ts_rank_cd(tsv, websearch_to_tsquery('english', :q))` for ranking.
- Returns the same row shape as `_search_chunks`: a `(rows, total_searched)` tuple where each row is the same dict with `chunk_id`, `doc_id`, `section_id`, `heading_path`, `chunk_text_key`, `section_type`, and `score`.

**Method signature**:
```python
async def lexical_search(
    self,
    query_text: str,
    granularity: str = "chunk",  # only "chunk" supported initially; "section"/"both" raise
    top_k: int = 20,
    min_score: float = 0.0,
    date_from: Any | None = None,
    date_to: Any | None = None,
    source_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
```

**SQL** (parameterised; same metadata join shape as `_search_chunks` for downstream parity):
```sql
SELECT
    c.chunk_id,
    c.doc_id,
    c.section_id,
    c.heading_path,
    c.chunk_text_key,
    s.section_type,
    ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) AS score
FROM chunks c
JOIN sections s ON s.section_id = c.section_id
LEFT JOIN document_source_metadata dsm ON dsm.doc_id = c.doc_id
WHERE c.tsv @@ websearch_to_tsquery('english', :q)
  AND ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) >= :min_score
  AND (CAST(:date_from AS TIMESTAMPTZ) IS NULL OR dsm.published_at >= CAST(:date_from AS TIMESTAMPTZ))
  AND (CAST(:date_to   AS TIMESTAMPTZ) IS NULL OR dsm.published_at <= CAST(:date_to   AS TIMESTAMPTZ))
  AND (CAST(:source_types AS text[]) IS NULL OR dsm.source_type = ANY(CAST(:source_types AS text[])))
ORDER BY score DESC
LIMIT :top_k
```

**Critical SQL pattern** — **BP-180** (asyncpg `AmbiguousParameterError` for nullable params): every nullable parameter must be wrapped in `CAST(:param AS TYPE) IS NULL`. The above SQL follows this pattern for `date_from`, `date_to`, and `source_types`. **Do not** use `:param IS NULL` without the CAST.

**Score normalisation**: `ts_rank_cd` returns floats typically in [0, 1] but can exceed 1.0 for very dense matches. The use-case layer (W5-3) is responsible for normalising before RRF — the repo returns the raw score so RRF has full ordering information.

**Granularity argument**: For the MVP only `granularity="chunk"` is supported. Calling with `"section"` or `"both"` raises `ValueError("lexical_search supports granularity='chunk' only in W5; section-level lexical is deferred")`. This is a deliberate scope limit — sections in nlp_db do not have a comparable text field for lexical ranking and out-of-scope per PRD-0034 §5.

**Tests to write** (in `tests/integration/test_chunk_lexical_search.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_lexical_search_returns_chunks_matching_query` | Insert known chunk with text "Apple iPhone Q4 guidance"; query "Apple iPhone" → row in results | integration (real postgres) |
| `test_lexical_search_orders_by_ts_rank_cd_desc` | 3 chunks with varying term frequency → returns most-frequent first | integration |
| `test_lexical_search_respects_top_k` | 5 matching chunks, top_k=2 → returns 2 | integration |
| `test_lexical_search_respects_date_range_filter` | chunks at different `published_at`, filter narrows result | integration |
| `test_lexical_search_respects_source_types_filter` | mix of `sec_filing` and `eodhd_news` chunks; filter narrows result | integration |
| `test_lexical_search_returns_empty_for_unknown_token` | query "asdfqwerzxcv" → empty list, total=0 | integration |
| `test_lexical_search_section_granularity_raises` | granularity="section" → `ValueError` | unit |
| `test_lexical_search_handles_websearch_operators` | query `'iPhone -Android'` → returns iPhone-only matches | integration (validates `websearch_to_tsquery` semantics) |
| `test_lexical_search_with_min_score_filters_low_rank_results` | min_score=0.05 drops weak matches | integration |

**Acceptance criteria**:
- [ ] 9 new tests pass; ruff + mypy clean
- [ ] No regressions in existing `tests/integration/test_chunk_search.py` (run full file)
- [ ] Method signature matches spec exactly (including kwarg names — the use-case dispatches by kwarg)
- [ ] Comment block above the method explains the BP-180 CAST pattern so future maintainers do not "simplify" it

**Logic & Behavior**:
- The repo class stays focused: it does not know about RRF or hybrid logic. That belongs to the use-case (W5-3).
- The session is the same `AsyncSession` already injected via `__init__` — no new DI wiring.
- `ts_rank_cd` (cumulative, density-aware) is preferred over `ts_rank` (length-normalised) for finance content because longer relevant chunks should not be penalised relative to short noise-snippets.

**Downstream test impact**:
- `services/nlp-pipeline/tests/integration/test_chunk_search.py` — existing ANN tests untouched; verify they still pass after the new column is present (they will — ANN query never references `tsv`).

---

### Pre-read for Wave W5-2
- `services/nlp-pipeline/alembic/versions/0016_add_last_attempted_at_to_embedding_pending.py` (current head; reference for migration shape)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/chunk_search.py` lines 25–155 (existing `_search_chunks` for SQL shape parity)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` (ChunkModel — to add the comment block)
- `docs/BUG_PATTERNS.md` BP-180 (asyncpg CAST IS NULL pattern)
- Postgres docs on `websearch_to_tsquery` and `ts_rank_cd` (built-in to pg16)

### Validation Gate for Wave W5-2
- [ ] `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` round-trips clean
- [ ] 9 new lexical-search tests + 1 ORM-no-tsv guard test pass (10 total — see T-W5-2-01 acceptance for the BP-NEW1 guard rationale)
- [ ] Existing nlp-pipeline test suite passes (`pytest services/nlp-pipeline/tests/ -v`)
- [ ] ruff + mypy clean on changed files
- [ ] `\d chunks` in psql shows new column + GIN index named `ix_chunks_tsv_gin`

### Break Impact for Wave W5-2
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/nlp-pipeline/tests/integration/test_alembic_migrations.py` (if it asserts head revision) | head moves to `0017_add_chunks_tsv_gin` | Update expected head |
| `services/nlp-pipeline/tests/unit/test_chunk_search.py` (if any) | new method added to repo class | None — additive method, existing tests unchanged |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` | comment-only edit; no behaviour change | None |

### Regression Guardrails for Wave W5-2
- **BP-180** (asyncpg AmbiguousParameterError): Lexical SQL uses `CAST(:param AS TYPE) IS NULL` for every nullable parameter — see SQL in T-W5-2-02. Do not "simplify" to `:param IS NULL`.
- **BP-126** (Alembic NOT NULL column missing server_default): Not applicable — `tsv` is GENERATED, has no default-needed semantic. But verify by reading the migration.
- **R5/R28** (Avro forward compatibility, no JSON on Kafka): not applicable — no Kafka surface in W5-2.
- **R7** (no cross-service DB): preserved — repo is in nlp-pipeline service only.
- **PRD §10 Failure Mode** ("`GENERATED ALWAYS AS` tsvector backfill locks chunks table during migration"): on dev stack ~5–15K rows, backfill is sub-second. For production scale this would warrant CONCURRENTLY-style index creation but MVP-launch nlp_db is a single-node instance with no concurrent writers during the migration window.


---

## 6. Wave W5-3: Hybrid Use-Case + S8 Plumbing + Eval Gate

**Goal**: Wire the lexical path into `ChunkSearchUseCaseImpl` with server-side Reciprocal Rank Fusion, expose the new `search_type` field on the API and on the rag-chat port, set `search_type="hybrid"` for eligible intents in the orchestrator, and run the eval gate. **Wave W5-3 does not ship until eval shows ≥0.05 NDCG@10 lift over the recorded baseline from `results/baseline_pre_hybrid.json` (T-W5-1-03)** — or the re-validated target if the recorded baseline fell outside [0.20, 0.85] per OQ-W5-4 resolution.

**Depends on**: W5-1 (baseline must exist), W5-2 (lexical_search method must exist)
**Blocks**: W5-4 (which re-runs the eval after recency hardening)
**Estimated effort**: 5–7 hours
**Architecture layer**: application (use case) + API (schemas) + application (orchestrator)

---

### T-W5-3-01: Extend `ChunkSearchRequest` schema (S6 API + rag-chat port)

**Type**: schema (Pydantic) + impl (port mirror)
**depends_on**: T-W5-2-02
**blocks**: T-W5-3-02
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (extend `ChunkSearchRequest` line 135)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` (extend `ChunkSearchRequest` dataclass line 18)
- `services/nlp-pipeline/tests/unit/test_chunk_search_schema.py` (new — schema validation tests)

**PRD reference**: §3 FR-T1-2

**What to build**:

S6 Pydantic schema gains a new optional field with a backward-compatible default:
```python
from typing import Literal

class ChunkSearchRequest(BaseModel):
    # ... existing 8 fields unchanged ...
    search_type: Literal["ann", "lexical", "hybrid"] = "ann"
```

The `Literal` type ensures Pydantic rejects unknown values with a 422 (constraint enforced before the use case is reached).

`exactly_one_query` model-validator (already present at the bottom of `ChunkSearchRequest`) gains a follow-up rule:
```python
@model_validator(mode="after")
def search_type_lexical_requires_query_text(self) -> ChunkSearchRequest:
    if self.search_type == "lexical" and self.query_text is None:
        raise ValueError("search_type='lexical' requires query_text")
    if self.search_type == "hybrid" and self.query_text is None:
        raise ValueError("search_type='hybrid' requires query_text (and optionally query_embedding)")
    return self
```

The rag-chat port dataclass at `application/ports/upstream_clients.py:18` gains the same field with the same default:
```python
@dataclass
class ChunkSearchRequest:
    # ... existing fields unchanged ...
    search_type: str = "ann"  # "ann" | "lexical" | "hybrid"
```

The port uses `str` (not `Literal`) because the rag-chat side does not enforce the constraint — that's S6's job; the port stays loose to avoid duplicating validation. A comment above the field documents this.

**Tests to write** (`tests/unit/test_chunk_search_schema.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_default_search_type_is_ann` | Construction without `search_type` → field == "ann" | unit |
| `test_search_type_hybrid_accepted` | Construction with "hybrid" → ok | unit |
| `test_search_type_unknown_value_rejected` | Construction with "fts5" → ValidationError | unit |
| `test_lexical_requires_query_text` | search_type="lexical", query_text=None → ValidationError | unit |
| `test_hybrid_requires_query_text` | search_type="hybrid", query_text=None → ValidationError | unit |
| `test_hybrid_with_both_text_and_embedding_ok` | hybrid + query_text + query_embedding → ok | unit |

**Acceptance criteria**:
- [ ] All 6 new schema tests pass
- [ ] Existing schema tests pass (backward-compatible)
- [ ] ruff + mypy clean on both files
- [ ] Field defaults preserve backward compat — any caller not setting `search_type` still gets ANN behaviour

**Downstream test impact**:
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/test_retrieval_orchestrator.py` (mock that asserts `ChunkSearchRequest` exact field set) | new field added | Update mock construction call to include `search_type=...` or rely on default |
| `services/nlp-pipeline/tests/integration/test_search_routes.py` | API contract changed (additive) | None — additive default-having field, existing tests unchanged |

---

### T-W5-3-02: Hybrid use-case routing + server-side RRF

**Type**: impl
**depends_on**: T-W5-3-01
**blocks**: T-W5-3-03
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/chunk_search.py` (extend `ChunkSearchUseCaseImpl.execute`)
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/_rrf.py` (new — pure function module for RRF)
- `services/nlp-pipeline/tests/unit/test_rrf_fusion.py` (new — pure unit tests for RRF)
- `services/nlp-pipeline/tests/unit/test_chunk_search_use_case.py` (extend with hybrid branch tests)

**PRD reference**: §3 FR-T1-2 ("Reciprocal Rank Fusion for combination")

**What to build**:

**Pure RRF helper** (`_rrf.py`) — kept domain-pure (no DB, no HTTP, just rank math) so it is trivially unit-testable:
```python
"""Reciprocal Rank Fusion — pure function for combining ranked lists.

Reference: Cormack, Clarke, Buettcher 2009 ("Reciprocal Rank Fusion outperforms
Condorcet and individual rank learning methods").

Score for each candidate d: sum over input rankings of 1 / (k + rank(d)).
k=60 is the canonical default from the original paper; tuning is permitted in
W5-3-04 (eval gate) but the default ships at 60.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

DEFAULT_K = 60


def reciprocal_rank_fuse(
    rankings: Sequence[Sequence[Any]],
    *,
    k: int = DEFAULT_K,
    key: callable = lambda x: x,  # extract identity from each item; default is item itself
) -> list[tuple[Any, float]]:
    """Fuse N ranked lists; return [(item, fused_score), ...] sorted DESC by score.

    Items appearing in multiple lists are deduplicated by `key(item)` and their
    fused score sums across lists. The original item from the FIRST list it
    appears in is preserved in the output (so metadata from list[0] takes
    precedence when present in multiple lists).
    """
    scores: dict[Any, float] = {}
    representatives: dict[Any, Any] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            ident = key(item)
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + rank)
            if ident not in representatives:
                representatives[ident] = item
    return sorted(
        ((representatives[ident], score) for ident, score in scores.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )
```

**Use-case dispatch** (in `chunk_search.py`):
```python
async def execute(self, req: ChunkSearchRequest) -> list[EnrichedChunkResult]:
    if req.search_type == "ann":
        return await self._execute_ann(req)
    if req.search_type == "lexical":
        return await self._execute_lexical(req)
    if req.search_type == "hybrid":
        return await self._execute_hybrid(req)
    # Pydantic Literal already rejects unknown; this is defensive.
    raise ValueError(f"unknown search_type: {req.search_type!r}")


async def _execute_hybrid(self, req: ChunkSearchRequest) -> list[EnrichedChunkResult]:
    # Short-query fallback: BM25 on 1–2 tokens is noisy. Fall through to ANN.
    if req.query_text and len(req.query_text.split()) < 3:
        log.info("hybrid_short_query_fallback_to_ann", token_count=len(req.query_text.split()))
        return await self._execute_ann(req)

    # Run both paths in parallel. Important: each leg has its OWN explicit timeout
    # because asyncio.wait_for around asyncio.gather doesn't propagate per-leg
    # timeouts cleanly, and httpx's default 5s will fire first (BP-235).
    ann_task = asyncio.create_task(self._execute_ann(req))
    lex_task = asyncio.create_task(self._execute_lexical(req))
    ann_results, lex_results = await asyncio.gather(ann_task, lex_task, return_exceptions=False)

    # Server-side RRF
    fused = reciprocal_rank_fuse(
        [ann_results, lex_results],
        k=DEFAULT_K,
        key=lambda r: r.chunk_id,  # dedup on chunk_id
    )
    # Take top_k after fusion
    return [item for item, _score in fused[: req.top_k]]
```

**RRF unit tests** (`tests/unit/test_rrf_fusion.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_rrf_single_list_preserves_order` | one input list → output identical order | unit |
| `test_rrf_dedups_items_in_both_lists` | item in both list[0] and list[1] → appears once with summed score | unit |
| `test_rrf_boosts_items_in_both_lists_above_one_only` | item ranked top-3 in both vs. top-1 in one only → both-list item wins | unit |
| `test_rrf_with_disjoint_lists_returns_all` | no overlap → all items appear, ordered by 1/(k+rank) | unit |
| `test_rrf_k_parameter_controls_decay` | k=10 produces steeper decay than k=100 | unit |
| `test_rrf_keeps_first_list_representative` | item in both lists; output retains the list[0] copy (metadata precedence) | unit |
| `test_rrf_empty_inputs_return_empty` | all empty lists → [] | unit |
| `test_rrf_handles_unhashable_with_key_func` | items are dataclasses; `key=lambda r: r.chunk_id` works | unit |

**Hybrid-branch use-case tests** (extend `tests/unit/test_chunk_search_use_case.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_search_type_ann_skips_lexical_repo_call` | mock both repos; search_type="ann" → only ann_search called | unit (mock) |
| `test_search_type_lexical_skips_ann_repo_call` | search_type="lexical" → only lexical_search called | unit |
| `test_search_type_hybrid_calls_both_repos` | search_type="hybrid" → both repos called | unit |
| `test_hybrid_short_query_falls_back_to_ann_only` | search_type="hybrid", query_text="Apple" (1 token) → only ann_search called | unit |
| `test_hybrid_dedupes_chunk_ids_via_rrf` | overlapping chunk_id in both repo results → exactly one in output | unit |
| `test_hybrid_respects_top_k` | both repos return 20 results; top_k=10 → output ≤10 | unit |
| `test_hybrid_propagates_repo_exception` | if either repo raises, hybrid execute raises (no silent swallow) | unit |

**Acceptance criteria**:
- [ ] `_rrf.py` is pure (no I/O, no logging, no DI)
- [ ] 8 RRF unit tests + 7 hybrid-branch tests pass
- [ ] Existing ANN tests pass unchanged
- [ ] ruff + mypy clean
- [ ] Hybrid path has explicit per-leg timeout handling commented inline (BP-235 reference)

**Logic & Behavior**:
- Both legs run in parallel (`asyncio.gather`) — total latency is `max(ann, lex)` not `ann + lex`. ANN typically dominates (~80–150ms); lexical with GIN should be <50ms.
- The short-query fallback (`< 3 tokens`) is a heuristic from PLAN-0058 Wave D — confirmed in code; eval may show a different threshold is better. Threshold is a private constant `_HYBRID_MIN_TOKENS = 3` so it can be tuned without API change.
- RRF default `k=60` is the canonical paper choice. The eval gate (T-W5-3-04) measures NDCG with `k=60`; if the gate fails, T-W5-3-04 explicitly authorises trying `k=30` and `k=80` before declaring the wave failed.

---

### T-W5-3-03: Plumb `search_type="hybrid"` into rag-chat orchestrator

**Type**: impl
**depends_on**: T-W5-3-02
**blocks**: T-W5-3-04
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py` (extend `_PlanFlags` + `_INTENT_TO_FLAGS`)
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (`_fetch_chunks` lines 174–194)
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` (extend `RetrievalPlan` if needed for the new flag — verify shape)
- `services/rag-chat/tests/unit/test_retrieval_plan_builder.py` (extend)
- `services/rag-chat/tests/unit/test_retrieval_orchestrator.py` (extend `_fetch_chunks` tests)

**PRD reference**: §3 FR-T1-2 (intent-aware hybrid)

**What to build**:

**`_PlanFlags` extension** (line 22 of `retrieval_plan_builder.py`):
```python
@dataclass(frozen=True)
class _PlanFlags:
    use_chunks: bool
    use_relations: bool
    use_graph: bool
    use_claims: bool
    use_events: bool
    use_contradictions: bool
    use_financial: bool
    use_portfolio: bool
    use_cypher: bool
    use_hybrid_chunks: bool  # NEW: when True and use_chunks, S6 receives search_type="hybrid"
```

**Intent map updates** (`_INTENT_TO_FLAGS`). Hybrid is enabled for intents where lexical adds signal (entity-token recall) without diluting semantic similarity. Per PRD §3 FR-T1-2 + PLAN-0058 reasoning:
- **SIGNAL_INTEL** stays ANN-only because BM25 over short news titles is noisy for sentiment intent.
- **PORTFOLIO** is also ANN-only because portfolio retrieval is dominated by the portfolio_client path, not chunks.
- **FINANCIAL_DATA** has `use_chunks=False` in current code (`retrieval_plan_builder.py:71-81` — verified 2026-05-03 via audit). This is intentional: financial-data queries are served from the `financial_client`/`portfolio_client` paths, not from chunk text. Therefore `use_hybrid_chunks` for FINANCIAL_DATA is moot (the flag is only consulted when `use_chunks=True` — see the `_fetch_chunks` plumbing below). We **do not** change `use_chunks` for FINANCIAL_DATA in W5; that would be a semantic retrieval change orthogonal to hybrid.
- **RELATIONSHIP** has `use_chunks=False` in current code (graph-anchored intents are served from KG/Cypher paths). Same logic applies — `use_hybrid_chunks` is moot.

| Intent | use_chunks (current) | use_hybrid_chunks (W5 sets) | Effective hybrid? |
|--------|----------------------|------------------------------|-------------------|
| `FACTUAL_LOOKUP` | True | **True** | yes |
| `FINANCIAL_DATA` | **False** (unchanged) | True (set anyway, but moot) | no — chunks not used |
| `COMPARISON` | True | **True** | yes |
| `REASONING` | True | **True** | yes |
| `RELATIONSHIP` | **False** (unchanged) | False | no — chunks not used |
| `SIGNAL_INTEL` | True | **False** (ANN-only) | no — explicit opt-out |
| `PORTFOLIO` | True | **False** (ANN-only) | no — explicit opt-out |
| `GENERAL` | True | **True** | yes |

**Net effective hybrid coverage**: 4 of 8 intents (FACTUAL_LOOKUP, COMPARISON, REASONING, GENERAL) actually run hybrid. FINANCIAL_DATA and RELATIONSHIP never reach the chunk path; SIGNAL_INTEL and PORTFOLIO are explicitly ANN-only.

**Orchestrator change** (`retrieval_orchestrator.py:174-194`):
```python
req = ChunkSearchRequest(
    query_embedding=query_embedding,
    query_text=resolved_query.rephrased_query if not query_embedding else None,
    top_k=20,
    include_entities=True,
    date_from=_date_to_dt(plan.date_filter.start) if plan.date_filter else None,
    date_to=_date_to_dt(plan.date_filter.end) if plan.date_filter else None,
    search_type="hybrid" if plan.flags.use_hybrid_chunks and resolved_query.rephrased_query else "ann",
)
```

The `and resolved_query.rephrased_query` guard ensures we don't request hybrid when only an embedding is available (hybrid requires query_text).

**Tests** (extend existing):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_plan_builder_factual_lookup_uses_hybrid` | intent=FACTUAL_LOOKUP → flags.use_hybrid_chunks True | unit |
| `test_plan_builder_signal_intel_does_not_use_hybrid` | intent=SIGNAL_INTEL → flags.use_hybrid_chunks False | unit |
| `test_plan_builder_portfolio_does_not_use_hybrid` | intent=PORTFOLIO → flags.use_hybrid_chunks False | unit |
| `test_plan_builder_financial_data_use_chunks_remains_false` | intent=FINANCIAL_DATA → flags.use_chunks False (unchanged from baseline; W5 must NOT regress this) | unit |
| `test_orchestrator_passes_search_type_hybrid` | plan.flags.use_hybrid_chunks=True + query_text → req.search_type="hybrid" | unit (mock S6Client) |
| `test_orchestrator_passes_search_type_ann_when_no_query_text` | use_hybrid_chunks=True but only embedding → req.search_type="ann" | unit |
| `test_orchestrator_passes_search_type_ann_when_intent_signal` | SIGNAL_INTEL → req.search_type="ann" | unit |

**Acceptance criteria**:
- [ ] 7 new tests pass (6 hybrid wiring + 1 FINANCIAL_DATA-no-regression guard)
- [ ] Existing rag-chat tests pass (backward-compatible default)
- [ ] ruff + mypy clean
- [ ] No change to `ChunkSearchRequest` field default ("ann") — backward compat preserved if rag-chat is rolled back
- [ ] FINANCIAL_DATA `use_chunks=False` is preserved (test asserts the existing-baseline value to prevent silent regression during W5)

**Logic & Behavior**:
- The plan-builder change is data-only (a bigger `_PlanFlags` dataclass + a new column in `_INTENT_TO_FLAGS`). All construction sites are inside `_INTENT_TO_FLAGS` — no callers construct `_PlanFlags` directly.
- The orchestrator change is one ternary. No timeout changes; `_with_cb` circuit-breaker logic is unchanged because it wraps the whole `_fetch_chunks` call.

---

### T-W5-3-04: Eval gate — hybrid must lift NDCG@10 by ≥0.05 vs **recorded** baseline

**Type**: test (enforcing acceptance, but produces an artifact)
**depends_on**: T-W5-3-01, T-W5-3-02, T-W5-3-03 (and the recorded baseline from T-W5-1-03)
**blocks**: wave completion
**Target files**:
- `results/eval_post_hybrid.json` (new — committed artifact)

**PRD reference**: §3 FR-T1-2 ("NDCG@10 ≥0.05 absolute lift over ANN-only baseline") and §4 NFR

**Target semantics (per §0 cross-plan decision #6)**: the lift is measured **relative to the number recorded in `results/baseline_pre_hybrid.json` at T-W5-1-03**, not against a hypothetical absolute floor. If that file does not exist, this task fails fast (the script's `--baseline` reads the file; missing file is a hard error). If the recorded baseline was outside [0.20, 0.85], a re-validated target from OQ-W5-4 resolution is used instead of `+0.05` (e.g. if baseline is 0.86, the re-validated target may be `+0.02` to acknowledge ceiling effects; if baseline is 0.18, the re-validated target may be `+0.10`).

**What to build**:

After T-W5-3-01..03 land in the dev stack, run the eval script with the hybrid path active and the W5-1 baseline as the reference:

```bash
python scripts/eval_retrieval.py \
  --golden tests/eval/golden/queries.jsonl \
  --baseline results/baseline_pre_hybrid.json \
  --fail-on-regression -0.05 \
  --output-dir results/
mv results/eval_<latest-ts>.json results/eval_post_hybrid.json
git add results/eval_post_hybrid.json
```

(Note: `--fail-on-regression -0.05` is treated as a require-improvement floor; the script's existing `--fail-on-regression 0.03` behaviour is symmetric, so a *negative* regression threshold is interpreted as the *minimum required improvement*. The script must support this — confirm in T-W5-1-02 spec; if not, extend the script in this task to accept a separate `--require-improvement` flag.)

**Per-intent gates**:
- Global NDCG@10 must improve by ≥0.05 absolute (FR-T1-2).
- No individual intent's NDCG@10 may regress by ≥0.05 (intent-level guardrail from T-W5-1-02).
- SIGNAL_INTEL and PORTFOLIO intents should be **identical** to baseline within ±0.005 (because they don't switch to hybrid). If they drift outside this range, investigate before shipping (likely indicates a non-deterministic test fixture or unrelated retrieval drift).

**Tuning fallback**: if the global lift is <0.05 on first run, in this same task try:
1. `k=30` (steeper decay favouring top results)
2. `k=80` (gentler decay)
3. Asymmetric weighting: multiply lexical scores by 0.7 before fusion (down-weights lexical)
4. Asymmetric weighting: multiply lexical scores by 1.3 (up-weights lexical)

If none of the four reach ≥0.05 lift on the global metric, the wave is **blocked**. Pause and investigate (likely insufficient labelled data for hybrid to differentiate, or label noise on COMPARISON queries — known PLAN-0058 risk).

**Acceptance criteria**:
- [ ] `results/eval_post_hybrid.json` committed
- [ ] `summary.ndcg_at_10.mean` is ≥ **recorded** baseline + 0.05 (or re-validated target if OQ-W5-4 set a different number)
- [ ] No intent regresses ≥0.05
- [ ] If RRF k value differs from default 60: update `_rrf.py` `DEFAULT_K` constant and add a comment citing the eval result that justified the tuning, then re-run eval and use that as the committed `eval_post_hybrid.json`

---

### Pre-read for Wave W5-3
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/chunk_search.py` (full file — current ANN-only execute)
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` lines 130–185 (ChunkSearchRequest)
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py` (full file)
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` lines 170–230 (`_fetch_chunks`)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` lines 1–60 (port + DTOs)
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` (RetrievalPlan and any shape that includes `_PlanFlags`)
- `docs/BUG_PATTERNS.md` BP-235 (httpx asyncio timeout) — referenced in the hybrid path

### Validation Gate for Wave W5-3
- [ ] All 6 schema tests + 8 RRF tests + 7 use-case branch tests + 7 plan-builder/orchestrator tests pass (28 new tests)
- [ ] Existing nlp-pipeline + rag-chat suites pass
- [ ] ruff + mypy clean
- [ ] CI workflow from T-W5-1-04 passes on a synthetic branch with hybrid active
- [ ] `results/eval_post_hybrid.json` committed showing ≥0.05 NDCG@10 lift
- [ ] `services/nlp-pipeline/.claude-context.md` updated with one-line note "search_type=hybrid uses tsvector + RRF, see T-W5-3-02"
- [ ] `services/rag-chat/.claude-context.md` updated with one-line note "_fetch_chunks passes search_type='hybrid' for FACTUAL/FINANCIAL/COMPARISON/REASONING/GENERAL"

### Break Impact for Wave W5-3
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/test_retrieval_orchestrator.py` | mock construction may need new field | Add `search_type=...` parameter to mock or use `.match` partials |
| `services/nlp-pipeline/tests/integration/test_search_routes.py` | endpoint contract gains optional field | None — additive default; existing tests pass |
| `services/rag-chat/tests/unit/test_retrieval_plan_builder.py` | `_PlanFlags` count of fields changed | Existing tests construct via `_INTENT_TO_FLAGS` lookup, not direct construction; safe |
| `libs/contracts/` | port `ChunkSearchRequest` is local to rag-chat, not in libs/contracts (verify by grep) | None — local |

### Regression Guardrails for Wave W5-3
- **BP-235** (httpx asyncio timeout): The `_execute_hybrid` use-case explicitly notes per-leg timeouts in the inline comment; both legs are repo-level (not HTTP-level) so this is informational, but the orchestrator's `asyncio.wait_for(self._s6.search_chunks(req), timeout=self._timeout)` wrap stays in place — confirmed unchanged.
- **BP-180** (asyncpg AmbiguousParameterError): Lexical SQL inside the use-case path uses CAST patterns from W5-2.
- **BP-127** (pre-commit ruff version mismatch): Run `git diff --name-only --cached | grep ".py$" | xargs uvx ruff format --check` before commit.
- **R7** (no cross-service DB): Hybrid fusion happens in S6 (where the data lives), not in S8. Confirmed.
- **R12** (domain layer independent of infrastructure): `_rrf.py` is in `application/use_cases/` (allowed) and is pure (no DB/HTTP). Domain entities (`chat.py`) only gain a flag, no infrastructure imports.


---

## 7. Wave W5-4: Recency Hardening + Routing-Tier Audit

**Goal**: Replace uniform recency decay with source-specific rates (the only routing/recency signal not already externalised), audit `routing_decisions.final_routing_tier` write path post-novelty, and re-run the eval to confirm no NDCG@10 regression. The originally-drafted "5 Stuck Signals" framing was based on a stale codebase model — the audit (2026-05-03) confirmed that:

- Watchlist signal — already populated event-driven via `watchlist_consumer` consuming `portfolio.watchlist.updated.v1` (entity-UUID set at `nlp:v1:watched_entities`). See §0 cross-plan decision #4. **No work in W5.**
- `source_reliability` signal — already externalised via `source_trust_weight` parameter sourced from `intelligence_db.source_trust_weights`. See §0 cross-plan decision #5. **No work in W5.**
- `document_type` signal — already externalised in `DOCUMENT_TYPE_SIGNAL` dict at `routing.py:43`. See §0 cross-plan decision #5. **No work in W5.**

What remains in W5-4 is genuinely missing: source-specific recency decay (currently a uniform `exp(-0.005*days_old)` constant), and a code audit on the routing-tier write path.

**Depends on**: none (touches different files than W5-2/W5-3) — can run in parallel with them, but the eval re-run lands after W5-3 to ensure no regression
**Blocks**: W5-5 (which adds observability for these signals)
**Estimated effort**: 2–3 hours (down from 4–5h after T-W5-4-02 and T-W5-4-03 were dropped)
**Architecture layer**: rag-chat domain (recency) + nlp-pipeline infrastructure (routing-decision audit)

---

### T-W5-4-01: Source-specific recency decay in rag-chat

**Type**: impl
**depends_on**: none
**blocks**: T-W5-4-02
**Target files**:
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` (rewrite `compute_recency_score` line 18)
- `services/rag-chat/tests/unit/test_recency_score.py` (new — and update any existing test that asserts the old uniform formula)

**PRD reference**: §3 FR-T1-2 ("source-specific recency decay") — pulled forward from PLAN-0058 Wave E-5

**What to build**:

Replace the single-constant decay (`exp(-0.005 * days_old)`) with a source-aware lookup:

```python
import math
from datetime import datetime, timezone

# Decay rate is dimensionless: score = exp(-rate * days_old)
# Higher rate = faster decay. Calibrated so:
#   - SEC filings retain >0.83 score after 365 days
#   - news articles drop below 0.55 after 30 days
_RECENCY_DECAY_RATES: dict[str, float] = {
    "sec_filing": 0.0005,        # 10-K/10-Q stay relevant for years
    "earnings_transcript": 0.001,
    "press_release": 0.01,
    "eodhd_news": 0.02,
    "finnhub_news": 0.02,
    "newsapi": 0.025,
    "default": 0.005,            # unchanged from current uniform constant
}

# Source-quality floor (added 2026-05-03 per Sam-alignment audit).
# WHY: news-class items decay 40-50× faster than filings/transcripts, so a
# 14-day-old earnings transcript ranks near zero against a 1-day-old newsapi
# blurb. For Sam (research analyst persona) the OPPOSITE is desired in the
# snippet popover — primary sources should dominate even when older. This
# floor multiplier is applied AFTER recency decay to lift filings/transcripts
# above transient news on tied lexical relevance.
_SOURCE_QUALITY_FLOOR: dict[str, float] = {
    "sec_filing": 1.4,           # primary regulatory disclosure — analyst trust source
    "earnings_transcript": 1.3,  # management voice — high signal
    "press_release": 1.0,        # neutral baseline
    "eodhd_news": 0.9,
    "finnhub_news": 0.9,
    "newsapi": 0.85,             # blog/aggregator — least authoritative
    "default": 1.0,
}
# Final score: ts_rank * recency_score(source_type, age) * _SOURCE_QUALITY_FLOOR[source_type]
# Documented in F-W5-9 follow-up: revisit weights after 30d of telemetry on Sam's
# actual click-through ratios per source_type.


def compute_recency_score(
    published_at: datetime | None,
    source_type: str | None = None,
) -> float:
    """Temporal decay weight for a retrieved item, source-aware.

    Returns exp(-rate * days_old) where rate is looked up from
    _RECENCY_DECAY_RATES by source_type (default 0.005 if unknown).
    Returns 0.5 when published_at is None (matches current behaviour).
    """
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    days_old = max(0, (datetime.now(timezone.utc) - published_at).days)
    rate = _RECENCY_DECAY_RATES.get(source_type or "default", _RECENCY_DECAY_RATES["default"])
    return math.exp(-rate * days_old)
```

**All callers must be updated** to pass `source_type` where the value is available. Audit by grep:
```
grep -rn "compute_recency_score" services/rag-chat/src/
```
Expected callers: `RetrievedItem.create()` (factory at line ~138 of `chat.py`). The factory has access to `source_type` via the citation_meta or item construction context — pass it through. If a caller does not have `source_type`, `None` is the safe default (gives the current uniform 0.005 rate).

**Tests** (`tests/unit/test_recency_score.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_sec_filing_1_year_old_above_0_83` | SEC filing 365 days old → recency_score ≥ 0.83 | unit |
| `test_news_30_days_old_below_0_55` | eodhd_news 30 days old → recency_score < 0.55 | unit |
| `test_unknown_source_uses_default_rate` | source_type=None or "wat" → default 0.005 rate | unit |
| `test_zero_days_old_returns_1` | freshly-published doc → 1.0 | unit |
| `test_published_at_none_returns_half` | None published_at → 0.5 | unit |
| `test_naive_datetime_treated_as_utc` | datetime without tzinfo → treated as UTC, no exception | unit |
| `test_future_dated_doc_clamped_to_zero_days` | published_at in the future → days_old clamped to 0 → score 1.0 | unit |
| `test_earnings_transcript_decays_faster_than_sec_filing` | same age, transcript < sec score | unit |

**Acceptance criteria**:
- [ ] 8 new tests pass
- [ ] Existing test in `test_chat_entity.py` (or wherever `compute_recency_score` was tested previously) updated to use `pytest.approx` or new source_type argument
- [ ] All callers pass `source_type` where available; grep confirms no caller ignores it without comment
- [ ] ruff + mypy clean

---

### T-W5-4-02: Confirm `routing_decisions.final_routing_tier` is being written + eval re-run

**Type**: impl + test
**depends_on**: T-W5-4-01
**blocks**: wave completion
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision_repo.py` (audit; fix if needed)
- `services/nlp-pipeline/tests/integration/test_routing_decision_persistence.py` (extend)
- `results/eval_post_routing.json` (new — committed artifact)

**What to build**:

**Code audit step**: PLAN-0057 A-1 added `final_routing_tier` and `processing_path` columns to `routing_decisions` (migration `0015_add_processing_path_to_routing_decisions.py`). Verify the repo's `upsert` writes both fields with the post-novelty values. If `processing_path` or `final_routing_tier` is `None` after a routing decision in a fresh dev-stack run, **this task includes the fix** (track the value through novelty stage in the routing pipeline and pass to the upsert).

Verification SQL (run in psql after 1h ingest):
```sql
SELECT count(*) FILTER (WHERE final_routing_tier IS NOT NULL) AS populated,
       count(*) AS total
FROM routing_decisions
WHERE created_at > now() - interval '1 hour';
```
Acceptance: `populated / total ≥ 0.95` (allow 5% legacy rows).

**Eval re-run**:
After T-W5-4-01 is merged into the dev stack, run:
```bash
python scripts/eval_retrieval.py \
  --golden tests/eval/golden/queries.jsonl \
  --baseline results/eval_post_hybrid.json \
  --fail-on-regression 0.03 \
  --output-dir results/
mv results/eval_<latest-ts>.json results/eval_post_routing.json
```

The expectation is that NDCG@10 is **unchanged or improved** (recency signal feeds reranking, not retrieval — so the impact may be small but should be non-negative). Strict fail-condition: NDCG@10 must not regress >0.03 from the post-hybrid baseline.

**Tests** (extend `test_routing_decision_persistence.py`):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_routing_decision_writes_final_routing_tier` | After a full pipeline run, `final_routing_tier` is non-NULL on the new row | integration |
| `test_routing_decision_writes_processing_path` | `processing_path` is non-NULL | integration |

**Acceptance criteria**:
- [ ] If the audit reveals `final_routing_tier` is being written: pass through with no code change, only test addition
- [ ] If not being written: fix in this task (add the value to the upsert call)
- [ ] 2 new integration tests pass
- [ ] `results/eval_post_routing.json` committed showing NDCG@10 unchanged or improved vs `results/eval_post_hybrid.json`
- [ ] `routing_decisions.composite_score` stddev SQL query returns >0.10
- [ ] ruff + mypy clean

---

### Pre-read for Wave W5-4
- `services/rag-chat/src/rag_chat/domain/entities/chat.py` (full `compute_recency_score` and `RetrievedItem.create` factory)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/routing_decision_repo.py` (audit `upsert`)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` (verify which signals are externalised — for §0 cross-plan decision #5 sanity check)

### Validation Gate for Wave W5-4
- [ ] All 10 new tests pass (8 recency + 2 routing decision)
- [ ] Existing test suites pass
- [ ] ruff + mypy clean across rag-chat + nlp-pipeline
- [ ] `results/eval_post_routing.json` shows no regression
- [ ] CI workflow from T-W5-1-04 passes on this wave's PR

### Break Impact for Wave W5-4
| Broken File | Why | Fix |
|-------------|-----|-----|
| `services/rag-chat/tests/unit/test_chat_entity.py` (or wherever `compute_recency_score` was previously tested) | Signature gains optional `source_type` param; old callers still work | Update assertions that asserted exact value of `exp(-0.005 * N)`; use `pytest.approx` with the source-aware rate |

### Regression Guardrails for Wave W5-4
- **BP-179** (`Optional[SecretStr]` empty-string env vars): not applicable here (no new SecretStr settings).
- **BP-201** (ws_token sub preference): not applicable (no WebSocket).
- **BP-235** (httpx asyncio timeout): not applicable here (no new httpx clients introduced; the dropped T-W5-4-02 cron worker would have needed this guard, but the cron is dropped).
- **R7** (no cross-service DB): preserved — recency is computed in rag-chat domain layer with data already in hand.

---

## 8. Wave W5-5: Observability + Citation-Accuracy Cron + Doc Updates

**Goal**: Close the W5 loop with observable metrics on retrieval quality, ship the citation-accuracy weekly cron (LLM-as-judge), and update all relevant docs and `.claude-context.md` files. This wave is intentionally light: the heavy lifting is done; W5-5 is what makes the work visible and durable.

**Depends on**: W5-1, W5-2, W5-3, W5-4 (all four)
**Blocks**: nothing (final wave)
**Estimated effort**: 3–4 hours
**Architecture layer**: observability + docs + cron

---

### T-W5-5-01: Prometheus metrics for retrieval quality

**Type**: impl
**depends_on**: T-W5-3-03, T-W5-4-02
**blocks**: T-W5-5-02 (informational dependency for W9)
**Target files**:
- `services/rag-chat/src/rag_chat/observability/metrics.py` (or wherever existing rag-chat metrics live; create if missing)
- `services/nlp-pipeline/src/nlp_pipeline/observability/metrics.py` (or equivalent)
- `services/rag-chat/tests/unit/test_metrics_emission.py` (new — verifies metrics are emitted under the right conditions)

**PRD reference**: §3 FR-T1-2 + §4 NFR observability + §11 Test Strategy

**What to build**:

Four new Prometheus metrics, registered at module import (existing pattern):

1. **`rag_retrieval_score_distribution` (Histogram, labels: `source`)** — recorded for every chunk that survives fusion. Buckets `[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]`. Emitted in `retrieval_orchestrator._fetch_chunks` after results return.

2. **`rag_reranker_position_change` (Gauge)** — fraction of queries where the reranker's top-1 differs from fusion's top-1. Emitted at the end of each chat turn in `chat_use_case.py` (find the right hook point during pre-read). Window: rolling 100-query average; updated as a gauge after each query.

3. **`rag_source_contribution_total` (Counter, labels: `source`)** — incremented once per source per query, where source is the `source_type` of any chunk that made it into final fusion top-30.

4. **`news_display_score_path_total` (Counter, labels: `path` ∈ `{"full_formula", "no_price_impact", "no_llm_score", "routing_only"}`)** — incremented in nlp-pipeline wherever `display_relevance_score` is computed. Tracks which fallback path is hit; "full_formula" should grow over time as W5-4 + W1 + W2 mature.

**Important**: Each metric is registered exactly once (module-level constant) per BP-272 / structlog pattern. Tests verify the expected metric is present in the registry but should NOT call `.observe()` / `.inc()` themselves (that creates flaky tests on order-dependent counters).

**Tests**:
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_retrieval_score_distribution_metric_registered` | metric appears in `REGISTRY.collect()` | unit |
| `test_retrieval_score_distribution_emits_on_fetch` | mock _fetch_chunks → metric observed | unit (mock) |
| `test_source_contribution_increments_per_query` | 1 query, 3 distinct sources → 3 increments | unit |
| `test_display_score_path_full_formula_emitted` | all three components present → path="full_formula" | unit |
| `test_display_score_path_no_price_impact_emitted` | price impact null → path="no_price_impact" | unit |

**Acceptance criteria**:
- [ ] 5 new metric tests pass
- [ ] All 4 metrics visible in `/metrics` endpoint of rag-chat + nlp-pipeline
- [ ] ruff + mypy clean

**Logic & Behavior**:
- Metrics are read by W9's Grafana board updates — coordinate with W9 owner so the panels exist by launch.
- The `rag_reranker_position_change` gauge requires storing recent results; use a fixed-size deque (`collections.deque(maxlen=100)`) at module scope. This is simple and adequate for MVP — proper aggregation belongs in Prometheus, not in-memory.

---

### T-W5-5-02: Weekly citation-accuracy cron (LLM-as-judge)

**Type**: impl
**depends_on**: T-W5-5-01
**blocks**: nothing
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/jobs/citation_accuracy_cron.py` (new)
- `services/rag-chat/src/rag_chat/application/use_cases/score_citation_accuracy.py` (new)
- `services/rag-chat/tests/unit/test_score_citation_accuracy.py` (new)

**PRD reference**: §11 Test Strategy ("Citation accuracy — PR touching brief or chat endpoints — 50-claim fixture set; CI fails if any citation 404s or has empty `snippet`") and §13 evaluation of citation-accuracy audit job

**What to build**:

A weekly cron job that samples 50 recent chat responses (from `chat_messages` with role=assistant, joined to citations), uses the existing chat LLM (DeepSeek R1 Distill 32B via DeepInfra) as judge to score each citation→snippet relevance on a 0–3 scale, and emits the mean score as `rag_citation_accuracy` gauge.

**Cron registration**: register inside the existing rag-chat cron infrastructure (verify location during pre-read; likely `app.py:lifespan` startup hook with `asyncio.create_task(_run_periodically(...))`). Schedule: every Sunday 03:00 UTC. First run on next service start (don't wait a week for the first reading).

**Use-case** (`score_citation_accuracy.py`):
```python
class ScoreCitationAccuracyUseCase:
    """Sample 50 recent assistant messages, judge each citation, emit mean score."""

    async def execute(self) -> float:
        samples = await self._chat_history_repo.sample_recent_with_citations(n=50)
        if len(samples) < 10:
            log.warning("citation_accuracy_insufficient_samples", n=len(samples))
            return 0.0
        scores: list[float] = []
        # Revised 2026-05-03 (Sam-alignment audit) — score per [cN] claim-span,
        # not per whole-message text. PLAN-0062 introduced a `lead` paragraph
        # whose sentences carry inline [cN] markers; "claim = msg.text" would
        # score the entire chat message against each citation, which deflates
        # the gauge for synthesis-style leads (lead paraphrases multiple
        # sources but only some words map to any one cite). The per-span
        # extractor returns (claim_text, citation_id) tuples where claim_text
        # is the lead sentence containing the marker, OR the enclosing bullet
        # text, depending on which surface the [cN] sits in.
        for msg in samples:
            for claim_text, citation_id in iter_cited_claims(msg):
                cite = msg.citation_by_id(citation_id)
                if cite is None:  # marker references a citation_id not in the message — should not happen post-T-W4-B-02 invariant
                    continue
                judge_score = await self._llm_judge.score(
                    claim=claim_text,
                    snippet=cite.snippet,
                    rubric=_CITATION_RUBRIC,  # 0=irrelevant, 1=tangential, 2=supports, 3=directly-answers (synthesis-paraphrase counts as ≥2)
                )
                scores.append(judge_score / 3.0)  # normalise to [0, 1]
        mean = sum(scores) / len(scores) if scores else 0.0
        rag_citation_accuracy.set(mean)
        log.info("citation_accuracy_scored", n_samples=len(samples), n_claims=len(scores), mean=mean)
        return mean


def iter_cited_claims(msg: Message) -> Iterator[tuple[str, str]]:
    """Yield (claim_text, citation_id) for each [cN] marker in a brief-shaped message.

    Extracts per-marker claim spans from both the `lead` paragraph (if present)
    and bullets within sections. For lead markers, claim_text is the sentence
    containing the marker (split on `.!?`). For bullet markers, claim_text is
    the bullet's full text (markers stripped per T-W4-B-02). For chat-only
    messages without lead/sections, falls back to msg.text per-citation
    (legacy behaviour, scored once not N times).
    """
```

**Sampling repo method**: `ChatHistoryRepo.sample_recent_with_citations(n: int) -> list[Message]` — `ORDER BY random() LIMIT n` filtered by `role='assistant' AND created_at > now() - interval '7 days' AND citations IS NOT NULL AND jsonb_array_length(citations) > 0`. (Verify schema during pre-read.)

**Judge prompt** (in module constant `_CITATION_JUDGE_PROMPT`) — **revised 2026-05-03 to accept synthesis paraphrasing** so PLAN-0062 lead-style claims (e.g. "Three Fed signals point to a hawkish pivot [c1, c3, c5]") are not unfairly penalised when no single snippet contains the synthesis verbatim:
```
You are evaluating whether a snippet supports a chat assistant's claim.
The claim may be a direct quote OR a synthesis/paraphrase of multiple sources.

CLAIM: {claim}
SNIPPET: {snippet}

Score the snippet's support of the claim on this 0-3 scale:
- 0: Snippet is irrelevant to the claim
- 1: Snippet is tangentially related but does not support the specific claim
- 2: Snippet supports the claim — EITHER directly OR by supporting a paraphrase
     or synthesis of which this claim is a faithful summary. A snippet about
     "Fed hints at slower rate cuts" supporting a claim like "Three signals
     point to a hawkish pivot" qualifies as 2 (it is one of the supporting
     signals).
- 3: Snippet directly answers/contains the claim verbatim or near-verbatim.

Respond with ONLY a single digit 0, 1, 2, or 3.
```

**Tests** (mock LLM client, mock repo):
| Test | What It Verifies | Type |
|------|-----------------|------|
| `test_score_citation_accuracy_with_50_samples` | mock returns score 2 for all → mean = 2/3 ≈ 0.67 | unit |
| `test_score_citation_accuracy_insufficient_samples_logs_warning` | only 5 samples → returns 0.0 + WARNING log | unit |
| `test_score_citation_accuracy_no_samples_returns_zero` | 0 samples → 0.0, no exception | unit |
| `test_score_citation_accuracy_emits_gauge` | mock LLM → `rag_citation_accuracy` gauge has the expected value | unit |
| `test_judge_returns_invalid_response_skipped` | LLM returns "banana" → that score skipped, not crashed | unit |
| `test_iter_cited_claims_extracts_lead_sentence` | (Sam-fit) `lead="Foo [c1] bar."` + `bullets=[]` → yields `("Foo [c1] bar.", "c1")` (sentence, not whole msg) | unit |
| `test_iter_cited_claims_extracts_per_bullet` | (Sam-fit) bullet `text="X happened"` with `citations=[c1, c2]` → yields `("X happened", "c1")` and `("X happened", "c2")` | unit |
| `test_iter_cited_claims_handles_multi_marker_lead_sentence` | (Sam-fit) `lead="Foo [c1] and bar [c3]."` → yields 2 tuples sharing the same sentence span | unit |
| `test_iter_cited_claims_falls_back_to_msg_text_for_non_brief` | (Sam-fit) chat msg without lead/sections → legacy single-claim-per-citation behaviour preserved | unit |
| `test_judge_synthesis_claim_scored_at_least_2` | (Sam-fit) judge mock for synthesis claim ("3 signals point to hawkish pivot") + supporting snippet returns score ≥2 — guards rubric revision | unit |

**Acceptance criteria**:
- [ ] 5 new tests pass
- [ ] First cron run logs `citation_accuracy_scored` on dev stack with non-NaN mean
- [ ] Gauge visible at `/metrics`
- [ ] ruff + mypy clean

**Logic & Behavior**:
- Cron runs in the rag-chat process (no separate worker container). Failure to score does not crash the service; the gauge simply does not update that week.
- The judge LLM call is rate-limited to 50 calls/week (50 samples × ~3 citations avg = ~150 calls). Cost: ~$0.05/week at DeepInfra prices — negligible.
- **Prompt injection mitigation**: the snippet content is wrapped in `<<<SNIPPET START>>> {snippet} <<<SNIPPET END>>>` delimiters and the judge prompt explicitly tells the model to score only — same defence-in-depth pattern as PLAN-0060 T-A2-01.

---

### T-W5-5-03: Documentation updates

**Type**: docs
**depends_on**: T-W5-5-01, T-W5-5-02
**blocks**: nothing
**Target files**:
- `services/nlp-pipeline/.claude-context.md` (note hybrid path + tsv column)
- `services/rag-chat/.claude-context.md` (note hybrid wiring + recency change)
- `docs/services/nlp-pipeline.md` (document `search_type` API, `tsv` column, lexical_search method)
- `docs/services/rag-chat.md` (document hybrid orchestration, source-specific recency, citation-accuracy cron)
- `docs/MASTER_PLAN.md` (retrieval section: hybrid is now the default for entity-anchored intents)
- `docs/BUG_PATTERNS.md` (new BP for: "tsvector GENERATED column must NOT be declared in ORM model" — call it BP-NEW1, will be assigned a number on commit)
- `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` §5 (update maturity rating: retrieval lifts from ~3.5/5 to ~4.5/5)

**What to build**:
Standard doc updates: each `.md` file gets a section (or extension of an existing section) describing the new behaviour, the new API surface where applicable, and links to the test files. Length targets: each `.claude-context.md` update ≤80 lines; each service doc update ≤120 lines.

**Acceptance criteria**:
- [ ] All 7 doc files updated
- [ ] Cross-links verified (no 404 markdown links)
- [ ] BP-NEW1 added to BUG_PATTERNS.md with a code example
- [ ] Maturity rating in 2026-04-30 audit reflects W5 outcome

---

### Pre-read for Wave W5-5
- Existing rag-chat metrics module (locate via `find services/rag-chat/src -name "metrics.py"`)
- Existing nlp-pipeline metrics module
- `services/rag-chat/src/rag_chat/app.py:lifespan` (where to register the citation cron)
- Recent doc updates in `docs/services/rag-chat.md` for style consistency

### Validation Gate for Wave W5-5
- [ ] 10 new tests pass (5 metrics + 5 citation accuracy)
- [ ] All 4 metrics visible at `/metrics`
- [ ] Citation-accuracy cron logs first scoring run
- [ ] All 7 docs updated
- [ ] BP-NEW1 added with code example
- [ ] ruff + mypy clean

### Break Impact for Wave W5-5
| Broken File | Why | Fix |
|-------------|-----|-----|
| Existing rag-chat metrics test (if it asserts metric count) | new metrics added | update count |
| Service docs index | new sections referenced | none — additive |

### Regression Guardrails for Wave W5-5
- **BP-235** (httpx asyncio timeout): citation-accuracy cron uses LLM-clients abstraction which already enforces timeouts. Verify in pre-read.
- **BP-272** (`llm_usage_log` wiring): the citation-accuracy cron's LLM calls must wire `LLMUsageLogger` so cost is tracked. Acceptance: each cron run produces N rows in `llm_usage_log` matching N judge calls.
- **BP-127** (pre-commit ruff version mismatch): standard guard.
- **R3** (must update docs): T-W5-5-03 covers this comprehensively.


---

## 9. Cross-Cutting Concerns

### 9.1 Contract Changes
- `ChunkSearchRequest` Pydantic schema (S6) gains `search_type: Literal["ann","lexical","hybrid"] = "ann"` — additive, default-having, backward compatible. No version bump on `/api/v1/search/chunks` route required (R6).
- The rag-chat-side `ChunkSearchRequest` dataclass mirrors the field. This dataclass is **not** in `libs/contracts` (verified by grep) — it is a service-local DTO, so no shared contract test triggers.
- No Avro schema changes (R5/R28 unaffected).

### 9.2 Migrations
- `services/nlp-pipeline/alembic/versions/0017_add_chunks_tsv_gin.py` — new head. Forward-compatible; the column is GENERATED, so no application code changes needed for existing rows. Backfill is instant on dev stack.
- No intelligence-migrations changes (R24 preserved).
- No portfolio-service migration; T-W5-4-02's new endpoint reads existing tables only.

### 9.3 Event-Flow Changes
- None. No Kafka topic changes, no consumer changes, no schema-registry interactions.

### 9.4 Configuration Changes
| Setting | Service | Default | Purpose |
|---------|---------|---------|---------|
| `CITATION_ACCURACY_CRON_DOW` | rag-chat | `6` (Sunday) | T-W5-5-02 schedule day-of-week |
| `CITATION_ACCURACY_CRON_HOUR_UTC` | rag-chat | `3` | T-W5-5-02 schedule hour |
| `CITATION_ACCURACY_SAMPLE_SIZE` | rag-chat | `50` | T-W5-5-02 sample size |
| `RRF_K` | nlp-pipeline | `60` | T-W5-3-02 RRF tuning constant; default = paper canon |
| `RAG_CHAT_URL` | (script env) | `http://localhost:8003` | T-W5-1-02 eval script HTTP target for `/v1/internal/retrieve` |

All settings get added to `services/<svc>/src/<svc>/config.py` Settings class with the listed defaults and to `dev.local.env.example` with the same values.

### 9.5 Documentation Updates
Covered exhaustively in T-W5-5-03. Summary of touched files:
- 2 × `.claude-context.md`
- 2 × `docs/services/<svc>.md`
- 1 × `docs/MASTER_PLAN.md`
- 1 × `docs/BUG_PATTERNS.md` (new BP for tsvector ORM warning)
- 1 × `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` §5 (maturity rating)

---

## 10. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Golden-set labels are subjective and noisy | Medium | Medium | Every label has a `rationale` field (T-W5-1-01); 2-person review prior to merge; per-intent breakdown isolates noisy intents |
| Hybrid lift <0.05 on first run | Medium | High (blocks wave) | T-W5-3-04 explicitly authorises k tuning + asymmetric weighting before declaring failure; if all 4 attempts fail, halt for investigation rather than ship a degraded gate |
| Hybrid regresses SIGNAL_INTEL or PORTFOLIO | Low | Low | Plan builder explicitly excludes these intents from hybrid; per-intent guardrail in eval script catches any drift |
| `tsvector GENERATED` migration locks `chunks` during backfill | Low | Low (dev), Medium (prod, deferred) | Dev: ~5–15K rows, sub-second; production: out of MVP scope |
| ORM accidentally declares `tsv` column → INSERT fails | Medium | High (silent prod bug) | Comment block in `ChunkModel`; new BP-NEW1 in BUG_PATTERNS.md; grep guard in T-W5-2-01 acceptance |
| LLM-as-judge gives noisy citation scores | Medium | Low | Cron is informational, not gating; gauge trend over weeks is the signal, not a single value |
| Per-leg timeouts in hybrid path race incorrectly | Low | Medium | T-W5-3-02 explicitly uses `asyncio.gather(return_exceptions=False)` so a slow leg blocks but does not silently swallow; outer `wait_for` (in `_with_cb`) caps total time |
| CI workflow times out on slow runner | Low | Medium | `retrieval-eval` profile boots only 4 services; total budget 10 minutes; if it consistently times out, switch to job-level concurrency cap |
| `entity_ids` UUIDs in golden set go stale (canonicals deleted) | Low | Low | T-W5-1-01 acceptance includes UUID resolution check; future maintenance needs a periodic spot-check (added to docs; F-2 in §15) |
| W5-4 source-specific recency rates are wrong empirically | Medium | Low | Eval re-run in T-W5-4-02 catches regression; if NDCG regresses, rates can be tuned without schema change |
| Recorded baseline (T-W5-1-03) ends up outside [0.20, 0.85] band → +0.05 lift target is trivial or unreachable | Medium | Medium | T-W5-1-03 acceptance forces re-validation of the FR-T1-2 lift target with PM/founder before W5-3 begins; OQ-W5-4 documents the resolution |

---

## 11. Tracking Table (Local — mirror of TRACKING.md row for this plan)

| Wave | Tasks | Status | NDCG@10 (post) | Tests | QA | Date |
|------|-------|--------|----------------|-------|-----|------|
| W5-1 (Eval Foundation: endpoint + golden labels + script + baseline + CI gate) | 5 (T-W5-1-00..04) | pending | *baseline TBD — fill in after T-W5-1-03* | 5 endpoint + 10 metric + 50 golden labels | — | — |
| W5-2 (Hybrid Schema + Repo) | 2 (T-W5-2-01..02) | pending | (no eval) | 9 lexical + 1 ORM-no-tsv guard (BP-NEW1) | — | — |
| W5-3 (Hybrid Use-Case + Plumbing + Gate) | 4 (T-W5-3-01..04) | pending | *post-hybrid TBD; ≥recorded_baseline+0.05* | 28 (6 schema + 8 RRF + 7 use-case + 7 plan/orch) | — | — |
| W5-4 (Recency + Routing-Tier Audit) | 2 (T-W5-4-01..02) | pending | *post-routing TBD; no regression* | 10 (8 recency + 2 routing decision) | — | — |
| W5-5 (Observability + Cron + Docs) | 3 (T-W5-5-01..03) | pending | (no eval) | 10 (5 metrics + 5 citation) | — | — |
| **Totals** | **16 tasks** | — | — | **73 new tests + 50 labels** | — | — |

**Recorded baseline NDCG@10**: _TBD — to be filled in by T-W5-1-03 once measured against the labelled golden set_.

---

## 12. Critical Path & Open Questions

### Critical Path
```
W5-1 (eval baseline)  ───►  W5-3 (hybrid + gate)  ───►  W5-4 (routing/recency)  ───►  W5-5 (observability + docs)
                            ▲
W5-2 (tsv + lexical)  ──────┘
```

W5-1 and W5-2 are parallelisable (different files). W5-3 needs both. W5-4 can begin in parallel with W5-3 but its eval re-run lands after W5-3 ships. W5-5 is strictly final.

**Total sequential time**: ~22–28 hours (single agent).
**Parallelised time** (W5-1 + W5-2 in parallel; W5-3 + W5-4 partially overlapped): ~16–20 hours.

### Open Questions (W5-Local — not blocking PRD-0034 BLOCKING list)

- **OQ-W5-1** [RESOLVED 2026-05-03]: Does rag-chat expose a read-only `/retrieve` endpoint? **No** — confirmed by audit. **Resolution**: T-W5-1-00 adds `POST /v1/internal/retrieve` (read-only, no LLM call). Eval script uses HTTP only; no in-process orchestrator import.
- **OQ-W5-2** [RESOLVED 2026-05-03]: Should `tests/eval/golden/_backlog.jsonl` replacement queries also be hand-labelled, or raw only? **Resolution**: raw only — backlog is for promotion-on-failure, not measurement. T-W5-1-01 reflects this.
- **OQ-W5-3** [DROPPED — moot 2026-05-03]: Cross-tenant aggregation in T-W5-4-02 (originally proposed flat-ticker endpoint). **Resolution**: T-W5-4-02 was dropped entirely after audit confirmed the watchlist signal is already populated event-driven (entity-UUID set). No cross-tenant endpoint is being added; W5/W8 RLS collision is moot.
- **OQ-W5-4** [TO BE RESOLVED IN T-W5-1-03]: RRF default `k=60` and the +0.05 NDCG@10 lift target. **Resolution path**: after T-W5-1-03 captures the recorded baseline NDCG@10, re-validate the +0.05 target. If baseline ≥0.85 (ceiling effects per Spärck Jones-Cormack), or ≤0.20 (target trivial), document a re-validated target with PM/founder signoff before T-W5-3-04 runs. The eval gate (T-W5-3-04) honours whichever target ends up in this plan.
- **OQ-W5-5**: Should W5 include a frontend change to surface the new `news_display_score_path_total` in any UI? Out of scope for W5; W9 owns observability surfacing.

---

## 13. Compounding Updates Required on Each Wave Commit

Per CLAUDE.md mandatory compounding step:
- `docs/plans/TRACKING.md` — update PLAN-0063 row's `Waves Done/Total` and `QA` and `Updated` columns
- `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md` — local tracking table at §11
- `docs/audits/2026-04-30-retrieval-graph-architecture-revised.md` §5 — maturity re-rating after W5-3 and W5-4
- `services/nlp-pipeline/.claude-context.md` — pitfalls discovered during W5-2/W5-3 implementation
- `services/rag-chat/.claude-context.md` — pitfalls discovered during W5-3/W5-4
- `docs/BUG_PATTERNS.md` — at least one new BP from W5-2 (tsvector ORM declaration warning); more as discovered
- `docs/MASTER_PLAN.md` — retrieval section after W5-3 ships

**Compounding check at /plan time**: this plan introduces one new pattern worth codifying — "Generated column must not be declared in ORM model" (BP-NEW1, assigned in T-W5-5-03). No other RULES/STANDARDS/skill updates are required at this point. Reconfirm after each wave's QA pass.

---

## 14. Migration / Supersession Note

On commit of Wave W5-1 to `main`:

### 14.1 PLAN-0060 Sub-Plan B (chunks.tsv migration + RRF + routing) → moved to PLAN-0063

1. Update `docs/plans/TRACKING.md` PLAN-0060 row to:
   - Title: `KG + Retrieval MVP Activation — PLAN-0057 residuals (Sub-Plan A only; Sub-Plan B SUPERSEDED by PLAN-0063)`
   - Waves: `2/2 (Sub-Plan A complete; Sub-Plan B moved to PLAN-0063)`
2. In `docs/plans/0060-kg-retrieval-mvp-activation-plan.md`, add a top-of-file note:
   ```
   > **Sub-Plan B SUPERSEDED 2026-05-03 by PLAN-0063** (W5 hybrid retrieval + eval gate).
   > The `chunks.tsv` GIN index migration originally drafted as PLAN-0060 Wave B-2
   > is now PLAN-0063 Wave W5-2-01. Downstream plans (PLAN-0064 W6 FTS) updated to
   > reference the new owner (W5-2-01) and the new index name `ix_chunks_tsv_gin`
   > with `websearch_to_tsquery` parser (see PLAN-0063 §0 cross-plan decisions
   > #1 and #2). See `docs/plans/0063-w5-hybrid-retrieval-eval-gate-plan.md`.
   > This file remains as historical record of Sub-Plan A (PLAN-0057 residuals
   > — already shipped).
   ```
3. **Downstream consumer notification**: PLAN-0064 (W6 FTS) was authored against the original PLAN-0060 Wave B-2 ownership. The W6 plan owner must update PLAN-0064 §1, §2, §3, §4, §6, §10, §11 to reference `PLAN-0063 Wave W5-2-01` as the upstream dependency, and to use the index name `ix_chunks_tsv_gin` and tsquery parser `websearch_to_tsquery` per PLAN-0063 §0 cross-plan decisions #1 and #2. **A parallel revision pass on PLAN-0064 is in flight (2026-05-03).** This is W6's responsibility to apply; W5 advertises its outputs (table name, column name, index name, parser choice) clearly in §0 and §5 so W6 can reference them.

### 14.2 PLAN-0058 Waves C/D/E (offline eval + BM25+RRF + routing/recency) → absorbed into PLAN-0063

In `docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md`, add a top-of-file note that Waves C/D/E are absorbed into PLAN-0063.

### 14.3 PLAN-0058 Waves F/G/H (entity_summaries hot cache + AGE shadow + ontology enforcement) → DEFERRED to a separate post-MVP plan

The audit (2026-05-03) flagged that PLAN-0058 Waves F/G/H were silently orphaned by the §0 supersession note ("absorbs C/D/E"). These waves are about KG retrieval quality (entity_summaries + Cypher/AGE + temporal ontology) and are **not** in W5 scope. They are scheduled for a separate post-MVP plan:

- **Disposition**: defer to a new plan (suggested ID **PLAN-0066** — KG Retrieval Quality Uplift, post-MVP).
- **Why not now**: PRD-0034 §3 FR-T1-2 acceptance criterion is "+0.05 NDCG@10 lift on a 50-query hand-labelled set" which is dominated by chunk retrieval (W5 scope) rather than KG path retrieval (F/G/H scope). The MVP launch can ship without F/G/H even if RELATIONSHIP/REASONING intents are slightly weaker than ideal. Capturing the recorded baseline at T-W5-1-03 will measure the **current** KG state (which is impoverished per the 2026-04-30 audit), and any subsequent F/G/H work will measure against that baseline in its own future plan.
- **Tracking action on commit of W5-1**: in `docs/plans/TRACKING.md`, add a TODO row referencing PLAN-0058 Waves F/G/H deferral and link to "PLAN-0066 (TBD)". In `docs/plans/0058-retrieval-and-kg-strategic-uplift-plan.md`, the supersession note explicitly says "Waves F/G/H deferred to PLAN-0066 (TBD); not in MVP launch scope".

### 14.4 Net effect on the plan archive

After W5-1 commits:
- PLAN-0058: Waves A/B (done) preserved as history; Waves C/D/E absorbed into PLAN-0063 (note in plan); Waves F/G/H deferred to PLAN-0066 TBD (note in plan + TRACKING TODO).
- PLAN-0060: Sub-Plan A (done) preserved; Sub-Plan B moved to PLAN-0063 (note in plan).
- PLAN-0063: this plan, single source of truth for W5 work (16 tasks across 5 waves).
- PLAN-0064 (W6 FTS): updated by parallel revision to reference PLAN-0063 W5-2-01 outputs.

This avoids duplicate "the same work is described in three places" confusion for any future agent reading the plan archive.

---

## 15. Follow-ups (Deferred from Audit; Revisit Post-MVP)

These items were raised during the 2026-05-03 audit (`docs/audits/2026-05-03-revise-plan-0063-w5.md`) but explicitly deferred out of W5 scope. Each carries a "revisit when…" trigger so it does not silently rot.

| # | Item | Source finding | Trigger to revisit | Owner |
|---|------|----------------|--------------------|-------|
| F-1 | Promote in-code routing dicts (`source_trust_weights` consumers + `DOCUMENT_TYPE_SIGNAL`) to a config file or admin-editable DB table | B-2 / §0 cross-plan decision #5 | If empirical routing tuning post-launch shows per-source-type tuning is needed more than once per quarter, externalise. Until then, in-code is fine. | platform |
| F-2 | Periodic spot-check that golden-set `entity_ids` UUIDs still resolve (canonicals can be deleted/merged) | N-1-style guardrail | Quarterly; first run 30 days post-launch. Cron or manual SQL. | data |
| F-3 | RRF k-value ablation (k ∈ {30, 60, 100, 150}) baked into the eval script as a `--ablate-k` flag | N-1 / OQ-W5-4 | If T-W5-3-04 needs to try multiple k values and the manual workflow becomes painful. Otherwise W5 ships with k=60 default. | retrieval |
| F-4 | Per-leg explicit timeout in `_execute_hybrid` (current code uses `asyncio.gather` and outer `_with_cb` cap only; a slow leg blocks but doesn't error early) | N-3 | If hybrid p99 latency exceeds 1.5s sustained for 1 week post-launch. | retrieval |
| F-5 | PRD-0034 §6 W5 row update — add a single-line pointer to PLAN-0063 (currently still says "PLAN-0058 Wave C+D") | N-4 | At T-W5-1-04 commit time (cheap; do then). Strictly a doc nit, no code impact. | docs |
| F-6 | Citation-accuracy cron schedule semantics — "first run on next service start" + "every Sunday 03:00 UTC" interaction (potential drift if computed naively) | I-7 | At T-W5-5-02 implementation; pick "compute next-aligned Sunday at process start; emit a single immediate run only on first-ever boot identified by absent gauge value". Documented in T-W5-5-02 `Logic & Behavior`; revisit if drift observed. | retrieval |
| F-7 | `chunks.chunk_id` uses `default=uuid.uuid4` (R10 violation; pre-existing, not introduced by W5) | I-6 | When a broader R10 sweep happens or when the model is rewritten for any other reason. W5 lexical-search integration tests construct chunk_id with `common.ids.new_uuid7()` to avoid entrenching the violation in test fixtures. | platform |
| F-8 | PLAN-0058 Waves F/G/H (entity_summaries hot cache + AGE shadow + ontology) | I-4 / §14.3 | After MVP launch; bundle into PLAN-0066 (TBD). | retrieval |
