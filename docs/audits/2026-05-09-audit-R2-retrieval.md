# Audit R2 — Retrieval Substrate (VA-4)

**Date**: 2026-05-09
**Agent**: R2 (PLAN-0087 Wave B)
**Plans covered**: PLAN-0063 (hybrid ANN+BM25+RRF), PLAN-0064 (FTS), PLAN-0066 (temporal RAG / brief-seed), PLAN-0084 (W5-5b hardening)
**Eval run**: `results/eval_20260509T171834Z.json` (this audit), prior baseline `results/eval_20260509T161035Z.json`
**Mode**: hybrid, top_k=20, BAAI/bge-large-en-v1.5, n_evaluated=112 / n_queries_total=120 / n_skipped=8 (q103-q110, all `adversarial_or_out_of_scope` — empty `relevant_doc_ids` by design)
**Stack snapshot**: rag-chat healthy at :8008, S6 search healthy via S9 :8000, nlp_db chunks=546 / chunk_embeddings=546 / distinct_docs=523 (avg 1.04 chunks per doc — see D-R2-007).

---

## 1. Eval table

| Bucket | n | NDCG@10 | MRR | Recall@20 | Δ vs prior baseline (NDCG@10) |
|---|---|---|---|---|---|
| factual_lookup | 17 | 0.7287 | 0.873 | 0.676 | −0.018 |
| financial_data | 9 | **0.8950** | 1.000 | 0.748 | +0.004 |
| relationship | 9 | **0.8503** | 1.000 | 0.799 | −0.013 |
| signal_intel | 8 | 0.6684 | 0.813 | 0.735 | +0.081 |
| identifier_lookup | 12 | 0.5537 | 0.692 | 0.703 | −0.029 |
| non_analyst | 10 | 0.5475 | 0.688 | 0.520 | (not in prior) |
| reasoning | 12 | 0.4829 | 0.565 | 0.528 | +0.072 |
| portfolio | 7 | 0.4364 | 0.571 | 0.467 | +0.056 |
| comparison | 12 | 0.3870 | 0.558 | 0.327 | −0.015 |
| ambiguous | 6 | 0.2985 | 0.430 | 0.291 | (not in prior) |
| time_anchored_edge | 4 | **0.1575** | 0.233 | 0.137 | +0.008 |
| general | 6 | **0.0564** | 0.208 | 0.086 | +0.011 |
| **Overall** | **112** | **0.5519** | **0.685** | **0.547** | **+0.012 vs 0.5398** |

Failed query IDs: none. Skipped: q103-q110 (`adversarial_or_out_of_scope`, no labels by design — not a defect).

`general` and `time_anchored_edge` remain critically low. `comparison` and `ambiguous` remain weak (corpus gap + no temporal anchoring).

---

## 2. Per-query traces (5 samples, intent coverage)

All numbers from `results/eval_20260509T171834Z.json` plus a fresh `POST /v1/internal/retrieve` probe for q065 / q111 to capture source mix. JWT minted via `POST /v1/auth/dev-login`.

| Query | qid | Intent (chosen) | Sources hit | Date filter? | Top-5 chunk_ids | NDCG@10 | OK? |
|---|---|---|---|---|---|---|---|
| "What is Apple's interest coverage ratio based on the latest filings?" | q020 | FINANCIAL_DATA | chunks (claims+events also enabled but no entity_ids resolved → claims skipped) | None passed in; relies on `request.context.date_range` (always None in eval) | f7b807f7…, fd1bc2ee…, a41503be…, cd3a0199…, 493c4d5d… | 0.840 | YES — labels are doc_ids, retrieval returns chunk_ids whose `doc_id` field matches labels. |
| "How does Apple's inventory turnover compare to Samsung's most recent year?" | q022 | COMPARISON | chunks, claims, events | None | a61b010c…, 285a1ecf…, bbc9a933…, 3d890f35…, e4b19f80… | 0.664 | PARTIAL — comparison corpus gap (F-M-009) is real; only 2/16 labels recovered. |
| "What is the supplier relationship between Apple and TSMC?" | q038 | RELATIONSHIP | chunks (cypher gated off) | None | 1fc67d9c…, a17e1f94…, 5c98245d…, 776ca0ec…, 285a1ecf… | **0.989** | YES — relationship intent works very well end-to-end. |
| "What's interesting in the market today?" | q065 | GENERAL | chunks ONLY (`use_chunks=True`, all other flags False); 10/10 from `finnhub` source | None | 019df36e…, 019deed1…, 019df40b…, 019dee76…, 019df36d… | **0.000** | NO — see §3 F-C-002 status. Retrieval pulled 10 finnhub chunks, none of the 10 labelled doc_ids' chunks. |
| "What earnings reports are coming today?" | q111 | FACTUAL_LOOKUP (note: `time_anchored_edge` class but classified as FACTUAL_LOOKUP, not as anything temporal) | chunks, claims, events all enabled; in trace probe top-10 came 10/10 from `yahoo_finance` | **None — no anchoring of "today"**. `request.context.date_range` is always None from eval; planner has no extraction stage. | 019dd689…, 019deeaa…, 019dcb13…, 019dee62…, 019de49e… | **0.000** | NO — F-C-003 confirmed below. |

Direct probes captured during this audit (sub-second each):
- q065 mix: 10/10 `finnhub` source, scores 0.7155-0.7191 (very tight band → ANN saturates on short generic query).
- q111 mix: 10/10 `yahoo_finance`, scores 0.7388-0.7514. **No date filter applied.** Top-1 chunk_id `019dd4db-9db4-7ffb-b14c-0eaba86f8040` corresponds to a doc not in golden labels.

---

## 3. F-C-002, F-C-003, F-M-001 status

### F-C-002 — `general` bucket NDCG=0.05 — **NOT FIXED, ROOT CAUSE WAS MISDIAGNOSED**

The 2026-05-09 QA report claims q065-q070 have **empty `query_text`**. Verified directly against `tests/eval/golden/queries.jsonl` — **all six queries have populated `query_text`** (e.g. q065 = "What's interesting in the market today?", q068 = "What are the main themes driving the AI infrastructure trade right now?"). The earlier diagnosis is wrong.

The actual root cause is twofold:
1. **GENERAL plan flags are minimal** — `_INTENT_TO_FLAGS[QueryIntent.GENERAL]` (retrieval_plan_builder.py:115-126) sets `use_chunks=True` and **everything else False**. No graph, no claims, no events, no relations, no contradictions. So the only signal is the chunks ANN+FTS leg — a 10-chunk top-k from one similarity space.
2. **Generic queries saturate the ANN space** — short, generic queries like "What's interesting in the market today?" retrieve a tightly clustered band of finnhub headline chunks (scores 0.7155-0.7191) that lexically resemble each other but are unrelated to the labelled gold set. The labelled gold set was hand-curated to test "general market interest" semantics, and the retriever simply doesn't reach those chunks.

q068 ("AI infrastructure trade") — narrower phrasing — scores 0.110 (the only non-zero in the bucket), confirming the issue is generic phrasing, not a bug.

**Fix path** (recommend PLAN-0087-E):
- Re-grade or re-author q065-q067 with more specific framing OR enrich GENERAL plan flags (e.g. enable `use_events=True` for time-of-day implicit anchoring).
- Audit the gold labels against the actual corpus distribution — the corpus is 90% news headlines; labels written assuming a richer corpus will systematically miss.

### F-C-003 — `time_anchored_edge` NDCG=0.15, date_filter chain — **NOT FIXED, STRUCTURAL GAP**

Tracing the date_filter chain:
- `RetrievalPlanBuilder.build()` (retrieval_plan_builder.py:140) accepts `date_filter` as a parameter; it is plumbed straight through.
- `RetrieveOnlyUseCase.execute()` (retrieve_only.py:85) passes `request.context.date_range` to the builder — **no extraction stage**.
- `ChatPipeline.classify_and_plan()` (chat_pipeline.py:285,306) takes `date_range: Any = None` from its caller — **no extraction stage**.
- `scripts/eval_retrieval.py` — searched (`grep -n "date_range\|date_filter\|temporal"`) returns **zero matches**. The eval never sets `request.context.date_range`.
- The HTTP wrapper `RetrieveRequest` (api/routes/internal.py:25) has **no field for date_range** — the request body cannot carry one.

So for time_anchored_edge queries, `plan.date_filter` is **always None**. `_fetch_chunks` then sends `date_from=None, date_to=None` to S6 (orchestrator lines 268-269). `_fetch_claims`/`_fetch_events` fall back to "last 90/180 days from now" — which works coincidentally for "this past week" but misses "today" and "last quarter" entirely.

**Probe confirmation**: q111 ("What earnings reports are coming today?") classified as FACTUAL_LOOKUP (not RELATIONSHIP/SIGNAL_INTEL), date_filter=None, retrieved 10 yahoo_finance headline chunks none of which are the 3 labelled doc_ids.

**Fix path** (recommend PLAN-0087-D):
- Add a temporal-extraction stage between intent classification and plan building (regex or LLM) that converts "today/this week/last quarter/since X earnings" → `DateRange(start, end)`.
- Add a `date_range` field to `RetrieveRequest` so the eval can pass curated anchors.
- Add a structured-log assertion `log.warning("retrieval_temporal_intent_no_date_filter")` when intent is in {time-anchored-classes} and `plan.date_filter is None`.

### F-M-001 — No deduplication of retrieved items — **PARTIALLY FIXED IN CHAT PATH, NOT FIXED IN EVAL PATH**

- **Eval path (`RetrieveOnlyUseCase.execute()`, line 113)**: sorts raw items by `score` descending and truncates to `top_k`. **No dedup.** Items with the same `item_id` from different sources both survive. (Refer: retrieve_only.py:106-113.)
- **Orchestrator (`ParallelRetrievalOrchestrator.retrieve()`, line 168-199)**: `items.extend(r)` for each task. **No dedup at this layer.** F-M-001 confirmed at the orchestrator boundary.
- **Chat path (`FusionPipeline.process()`, fusion.py:118-144)**: dedups by `doc_id`, keeping highest fusion_score. Items with `doc_id=None` (relations, claims, financial, portfolio, cypher) are routed to `no_doc` and **never deduped against each other** — so a `relation` with `relation_id=X` and another `relation` with the same `relation_id=X` from different sources both survive.
- **Test coverage**: `grep -rn "test_dedup\|dedup_by_doc"` returns zero matches in `services/rag-chat/tests` — no regression test guards the dedup invariant.

**Fix path**:
- Add post-retrieval dedup in the orchestrator (line 177 area) keyed on `(item_type, item_id)` — keeps the highest-score occurrence.
- Add a regression test for fusion dedup.
- The eval path is silently affected because the retrieve_only use case bypasses fusion — either call `fusion.process(raw_items)` from `RetrieveOnlyUseCase` or apply the orchestrator-level dedup.

---

## 4. Additional findings discovered during this audit

### D-R2-005 — Golden set has 0 chunk_id labels, all 888 are doc_ids
`jq -rs 'map(.relevant_doc_ids) | add | map(select(.chunk_id))| length'` → **0**. F-B-002's "prefer chunk_id over doc_id" eval fix is still semantically working only because S6's `chunk_id` field happens to equal the parent `doc_id` for some sec_edgar / earnings_transcript chunks (single-chunk-per-doc case — see q020, q022, q038 where retrieval looks like UUIDv5 doc_ids). For news chunks (q065, q111) where `chunk_id` is UUIDv7 and `doc_id` is UUIDv5, the comparison cannot match and the bucket scores 0.

**This is the structural reason general/time_anchored buckets score so low.** The eval comparison logic in `scripts/eval_retrieval.py:302` does `c.get("chunk_id") or c.get("doc_id")` — chunk_id always wins because it's always populated. To rescue this, line 302 should try BOTH the chunk_id and doc_id and treat either as a hit.

### D-R2-007 — Corpus depth: 1.04 chunks/doc
`SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM chunks;` → 546 chunks across 523 docs. The chunker is producing 1 chunk per doc for ~96% of docs (mostly news headlines + short summaries). For comparison and reasoning queries the retriever has no fine-grained intra-document evidence to surface. F-M-009 (comparison corpus gap) is rooted here.

### D-R2-008 — FTS endpoint returns `published_at: null` despite data being present
`/v1/search?q=Apple+earnings` returned doc_id `5c383e08-...` with `published_at: null`. Direct DB query: `SELECT published_at FROM document_source_metadata WHERE doc_id='5c383e08-...'` returns `2026-05-01 13:32:08+00`. The FTS use case `_hit_from_repo_result` (search_documents.py:262) reads `s5_meta.get("published_at")` — the S5 batch lookup is dropping or not returning published_at, or the local nlp_db copy isn't being read. This breaks UI date display and any downstream temporal sorting on FTS results.

### D-R2-009 — `routing_decisions` table has only 16 rows (vs 523 docs)
`SELECT COUNT(*) FROM routing_decisions` → 16. This is the document-routing-tier decision table from the relevance-scoring path. Most ingested docs were never routed (or rows were never persisted). Not directly a retrieval-quality bug, but it means the `composite_score` JOIN that PRD-0026 / PLAN-0066 expected for `display_relevance_score` is missing for most docs.

### D-R2-010 — Smoke probe in eval_retrieval.py is fragile under JTI
The smoke probe (`scripts/eval_retrieval.py:945`) uses static `EVAL_INTERNAL_JWT`. With InternalJWTMiddleware JTI single-use enforcement, a JWT minted seconds before the run can be invalidated by the smoke probe and the per-query path then 401s. Workaround during this audit: mint two JWTs, set `EVAL_INTERNAL_JWT` for the smoke probe, set `EVAL_JWT_REFRESH_URL` for per-query refresh. Even then the gateway dev-login rate-limits at ~10/min, causing 30+ `429 Too Many Requests` warnings during the run — the eval recovered because each retried JWT mint kept the previous static JWT alive on the rag-chat side, but this is luck-of-the-draw.

---

## 5. Defect rows (YAML)

```yaml
- id: D-R2-001
  va: VA-4
  surface: A6, A7, A8 (chat retrieval); B3 (free-form chat); eval CI gate
  severity: SF-1  # NDCG <0.30 in two buckets — soft fail per PRD §3.2
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    1. EVAL_INTERNAL_JWT=$(curl -s -X POST :8000/v1/auth/dev-login -d '{}' | jq -r .access_token)
    2. EVAL_JWT_REFRESH_URL=http://localhost:8000/v1/auth/dev-login \
       .venv312/bin/python scripts/eval_retrieval.py \
         --rag-url http://localhost:8008 \
         --golden tests/eval/golden/queries.jsonl \
         --query-embeddings tests/eval/golden/query_embeddings.parquet \
         --mode hybrid --top-k 20 --output-dir results
    3. Inspect results: NDCG@10 general=0.0564 / time_anchored_edge=0.1575
  evidence:
    - file: results/eval_20260509T171834Z.json
    - per_query.q065 / q066 / q067 ndcg=0; q068=0.11
    - per_query.q111 ndcg=0; q112=0.27; q113=0.34; q114=0.0
  root_cause: |
    F-C-002 (2026-05-09 QA) misdiagnosed as "empty query_text" — query_text is
    populated for all 6 GENERAL queries. Real cause: GENERAL plan flags use
    chunks-only (no graph/claims/events) AND generic phrasings saturate ANN on
    a tightly clustered band of finnhub headlines that don't intersect labels.
  fix_decision: spawn-subagent  # PLAN-0087-E (golden-set hygiene + GENERAL plan)
  spawned_plan: PLAN-0087-E (when materialised)

- id: D-R2-002
  va: VA-4
  surface: A6 (chat with temporal phrasing); A2 dashboard "today's news"
  severity: SF-1
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    1. POST /v1/internal/retrieve {"query_text":"What earnings reports are coming today?"}
    2. Returns intent=FACTUAL_LOOKUP (not anything temporal)
    3. Top-10 are yahoo_finance headlines spanning weeks; no date_from / date_to
       was ever sent to S6
    4. Direct probe: grep -n "date_range" services/rag-chat/src/rag_chat/api/routes/internal.py
       → no field on RetrieveRequest. grep -n "date_range\|temporal" scripts/eval_retrieval.py
       → 0 hits.
  evidence:
    - retrieval_orchestrator.py:268-269 sends date_from=None when plan.date_filter is None
    - retrieve_only.py:85 plumbs request.context.date_range straight through
    - chat_pipeline.py:285 takes date_range as Any=None from its caller
    - api/routes/internal.py:25 RetrieveRequest has no date_range field
  root_cause: |
    No temporal-extraction stage. The system inherits date_range from
    request.context, which the eval and most chat callers never set. Planner
    therefore plans with date_filter=None for every query, including the four
    time_anchored_edge ones.
  fix_decision: spawn-subagent  # PLAN-0087-D (date-filter chain fix)
  spawned_plan: PLAN-0087-D (when materialised)

- id: D-R2-003
  va: VA-4
  surface: A6 / A8 (chat); eval path
  severity: HF-3  # could surface duplicate citations [N1] [N1] in chat answers
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    1. ParallelRetrievalOrchestrator.retrieve() at line 168: items.extend(r) per
       task — no per-(item_type, item_id) dedup
    2. RetrieveOnlyUseCase.execute() at line 113: sorts by score and truncates,
       no dedup → eval path is fully un-deduped
    3. FusionPipeline.process() at fusion.py:135: items with doc_id=None all go
       to no_doc bucket and are never deduped against each other
    4. grep -rn "test_dedup" services/rag-chat/tests → 0 matches
  evidence:
    - services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py:170-177
    - services/rag-chat/src/rag_chat/application/use_cases/retrieve_only.py:106-113
    - services/rag-chat/src/rag_chat/application/pipeline/fusion.py:118-144
  root_cause: |
    F-M-001 (2026-05-09 QA) recorded fix recommendation but no patch landed.
    Dedup exists only in FusionPipeline (chat path) and only by doc_id, which
    excludes graph/claims/financial/cypher items that all carry doc_id=None.
    The eval path bypasses FusionPipeline entirely.
  fix_decision: fix-now  # ~1h: dict-based dedup at orchestrator line 177 + 1 test

- id: D-R2-004
  va: VA-4
  surface: eval framework correctness; CI gate
  severity: SF-1  # makes per-bucket gates unreliable
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    jq -rs 'map(.relevant_doc_ids)|add|map(select(.chunk_id))|length' \
      tests/eval/golden/queries.jsonl  # → 0
    jq -rs 'map(.relevant_doc_ids)|add|length' tests/eval/golden/queries.jsonl  # → 888
  evidence:
    - 888/888 golden labels are doc_ids (zero chunk_ids)
    - scripts/eval_retrieval.py:302 retrieved_doc_ids = [c.chunk_id or c.doc_id]
      → chunk_id always wins because it is always populated
    - For sec_edgar / earnings_transcript single-chunk-per-doc, chunk_id == doc_id
      coincidentally works (q020, q022, q038 score well)
    - For news (multi-chunk or distinct UUIDs), chunk_id != doc_id → never matches
      labels (q065, q111 score 0)
  root_cause: |
    The "prefer chunk_id over doc_id" change in F-B-002 silently breaks the news
    buckets because the golden set was written when the eval matched on doc_id.
    Not a code bug per se but a labels↔candidates id-space mismatch.
  fix_decision: fix-now  # ~1h: change line 302 to try BOTH ids against relevant
                         # OR add chunk_id field to golden labels

- id: D-R2-005
  va: VA-4
  surface: A2 (dashboard news), A4 (instrument News tab)
  severity: HF-4  # visible "—" / null date on news cards
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    1. JWT=$(curl -s -X POST :8000/v1/auth/dev-login -d '{}' | jq -r .access_token)
    2. curl -fsS ":8000/v1/search?q=Apple+earnings&limit=5" -H "Authorization: Bearer $JWT"
    3. First result has published_at=null
    4. docker exec worldview-postgres-1 psql -U postgres -d nlp_db -c \
         "SELECT published_at FROM document_source_metadata WHERE doc_id='5c383e08-8559-58ed-a911-20dacf715c0a';"
       → 2026-05-01 13:32:08+00 (data IS present)
  evidence:
    - search_documents.py:262 published_at=s5_meta.get("published_at")
    - The S5 batch lookup is dropping the field
  root_cause: |
    FTS use case relies on S5 (content-store) batch metadata; the local nlp_db
    document_source_metadata is ignored. When S5 returns the doc but no
    published_at, the field is silently null in the response.
  fix_decision: fix-now  # ~30min: fall back to nlp_db.document_source_metadata
                         # OR ensure S5 returns published_at

- id: D-R2-006
  va: VA-4
  surface: corpus depth — affects every retrieval bucket
  severity: SF-1
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d nlp_db \
      -c "SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM chunks;"
    → 546, 523  (avg 1.04 chunks/doc)
  evidence: 546 chunks across 523 docs; 96% of docs have a single chunk
  root_cause: |
    Chunker is emitting 1 chunk per doc for short news content. For comparison,
    reasoning, and time_anchored queries the retriever has no intra-document
    evidence to surface. Likely related to the chunking strategy or to many
    headline-only ingested docs.
  fix_decision: defer  # demo can rehearse around shallow corpus; fix is >4h

- id: D-R2-007
  va: VA-4 / VA-7 cross-cutting
  surface: relevance scoring, brief intelligence (PRD-0026 display_relevance)
  severity: SF-3
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    docker exec worldview-postgres-1 psql -U postgres -d nlp_db \
      -c "SELECT COUNT(*) FROM routing_decisions;"
    → 16  (vs 523 docs)
  evidence: only 16 of 523 ingested docs have a routing_tier persisted
  root_cause: |
    Routing classifier is either not running for all docs or rows aren't being
    persisted. PRD-0026 display_relevance_score = 0.5*market + 0.4*llm + 0.1*routing
    falls back to 0 for the routing component on 98% of docs.
  fix_decision: defer

- id: D-R2-008
  va: VA-4
  surface: eval CI gate operability
  severity: SF-2
  status: open
  agent: R2
  found_at: 2026-05-09T17:18Z
  reproduce: |
    EVAL_JWT_REFRESH_URL=http://localhost:8000/v1/auth/dev-login \
      python scripts/eval_retrieval.py …
    → 30+ "429 Too Many Requests" warnings; smoke probe fails with ReadTimeout
      if static JWT alone is used
  evidence:
    - scripts/eval_retrieval.py:566 comment "rate-limited (~10/min)"
    - This audit ran with both static JWT + refresh URL; eval still produced
      ~30 mint failures across 112 queries
  root_cause: |
    JTI single-use enforcement + 10/min dev-login rate limit + per-query JWT
    mint requirement combine to a fragile run mode. The eval succeeded by luck
    (cached prior JWT remained valid past mint failures).
  fix_decision: defer  # not on demo path; CI uses long-lived service-account JWT
```

---

## 6. Severity table for this audit

| Severity | Count |
|---|---|
| HF-3 / HF-4 | 2 (D-R2-003, D-R2-005) |
| SF-1 | 4 (D-R2-001, D-R2-002, D-R2-004, D-R2-006) |
| SF-2 / SF-3 | 2 (D-R2-007, D-R2-008) |
| INFO | 0 |

---

## 7. Evidence inventory (relevant absolute paths)

- Eval result: `results/eval_20260509T171834Z.json`
- Prior baseline: `results/eval_20260509T161035Z.json`
- Golden set: `tests/eval/golden/queries.jsonl`
- Eval harness: `scripts/eval_retrieval.py` (line 302 id-matching, line 945 smoke probe, line 555 timeout)
- Orchestrator: `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (line 168-199 no dedup, line 268-269 date_from)
- Plan builder: `services/rag-chat/src/rag_chat/application/pipeline/retrieval_plan_builder.py` (line 115-126 GENERAL flags)
- Eval use case: `services/rag-chat/src/rag_chat/application/use_cases/retrieve_only.py` (line 85 date_range plumb-through, line 113 no fusion)
- Internal route: `services/rag-chat/src/rag_chat/api/routes/internal.py` (line 25 RetrieveRequest has no date_range)
- Fusion: `services/rag-chat/src/rag_chat/application/pipeline/fusion.py` (line 118-144 dedup by doc_id only)
- FTS use case: `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/search_documents.py` (line 262 published_at via S5 only)

---

**End R2 audit.**
