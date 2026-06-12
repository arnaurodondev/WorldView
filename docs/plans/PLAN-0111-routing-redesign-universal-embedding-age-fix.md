# PLAN-0111 — News Routing Redesign + Universal Embedding + AGE Anchor-Index Fix

> **Status:** in-progress (2026-06-12)
> **Branch:** `feat/frontend-enhancement-sprint` (consider a dedicated `feat/routing-redesign` branch for Sub-Plan C)
> **Origin:** NLP/news-pipeline throughput investigation. Routing is the upstream linchpin
> that relieves both downstream bottlenecks (GLiNER NER saturation + 235B extraction latency tail).
> **Research backing:** `docs/thesis/references-routing-and-infra.md` (RouteLLM, FrugalGPT, SetFit,
> learning-to-defer, calibration, EmbeddingGemma/MRL — all primary-source verified).

---

## Design decisions (settled with the user, 2026-06-12)

1. **Two embedders, disjoint jobs — no vector-space conflict.**
   - **Router:** `EmbeddingGemma-300m(title + subtitle)` → calibrated classifier → tier.
     Cheap ($0.002/1M, ~30–60 tokens/doc). The router vector is consumed *only* by the
     classifier — it is never ANN-compared against retrieval vectors, so there is no
     space-mismatch. EmbeddingGemma's native `task: classification` prompt + `title:/text:`
     document format fit exactly; MRL lets us truncate to 256d for a light classifier head.
   - **Retrieval:** `BGE-large-en-v1.5` unchanged (1024d). **No corpus migration, no HNSW
     re-tune, no retrieval-regression risk.**
2. **Embedding becomes universal for retrieval.** Every non-SUPPRESS doc (incl. **LIGHT**) gets
   BGE chunk embeddings → every ingested article is semantically searchable. Routing then
   decides only the **expensive** thing (KG/LLM extraction), not whether a doc *exists* in search.
3. **AGE anchor-index fix is independent and ships first** (hardening; unblocks graph panels).
4. **Pipeline order already fits:** Gemma router embed runs on title+subtitle *before* chunking/BGE.

---

## Sub-Plan A — AGE anchor-index + timeout fix (independent, ship first)

**Root cause (diagnosed 2026-06-12):** migration `0049` is marked applied but
`worldview_graph.entity_entity_id_idx` **does not exist** — its inner `create_property_index`
call is wrapped in `EXCEPTION WHEN OTHERS THEN RAISE NOTICE` (0049 line 140-142), which swallowed
the real failure while the migration reported success. Every `{entity_id: …}` anchor is therefore
a **seq-scan of ~15,555 vertices** (EXPLAIN nested-loop cost ~72M); live 2-hop = 22s, 3-hop > 35s.
Compounded by a **timeout inversion**: `_STATEMENT_TIMEOUT_MS = "60000"` (60s) vs each query's
`asyncio.wait_for(_DISCOVERY_TIMEOUT_SECONDS / 2)` = **30s** → client cancels first, orphans the
query → "could not send data to client: Broken pipe" / "connection to client lost". The
`PathInsightWorker` fires up to 10 concurrent such queries per batch → **1,172 failed jobs**.

| Wave | Task | Files | Status |
|------|------|-------|--------|
| A-1 | Live-diagnose the *real* `SQLERRM` from `create_property_index` (run it manually w/ short statement_timeout) | running intelligence_db | **done** |
| A-2 | Migration **0050**: create the index correctly + **fail loud** when AGE present but creation fails (no blanket swallow); assert index exists post-create | `services/intelligence-migrations/alembic/versions/0050_age_entity_properties_gin_index.py` | **done** |
| A-3 | Fix timeout inversion: `_STATEMENT_TIMEOUT_MS` 60000 → **25000** (DB cancels before the 30s `wait_for`, never orphans) | `services/knowledge-graph/.../age/path_discovery.py` | **done** |
| A-4 | Reset/re-run the failed `path_insight_jobs`; validate broken-pipe stops + queue drains | `path_insight_jobs` table | **done** |
| A-5 | Reduce worker batch concurrency 10 → **3** (Postgres still saturated after the index — 10-way × 2 queries/job breached timeout) | `path_insight_worker.py` | **done** |

**Validation (2026-06-12):**
- **A-1 SQLERRM:** `function create_property_index(unknown, unknown, unknown) does not exist` — **AGE 1.5.0 has no `create_property_index` function at all**; 0049's inner `WHEN OTHERS → RAISE NOTICE` swallowed it (BP-688).
- **A-2:** AGE 1.5 compiles `{entity_id: …}` anchors to `properties @> '{"entity_id":"…"}'::agtype` (containment), so a btree expression index is never chosen — the planner-correct index is a **GIN index on `properties`**. 0050 creates it + asserts `pg_class` presence (FAIL LOUD). Confirmed: `alembic_version=0050`, `entity_properties_gin_idx` present.
- **Latency:** anchor lookup 24ms-seqscan → **0.15ms** Bitmap Index Scan on `entity_properties_gin_idx` (after `ANALYZE`). NOTE: the GIN index fixes the *anchor*; the full 2-hop is still ~13s because the dominant cost is **edge-table expansion** (no `start_id/end_id` index on per-label edge tables) — out of Sub-Plan A scope (edge indexes are a separate follow-up).
- **A-3/A-4/A-5:** steady-state "could not send data to client: Broken pipe" / "connection to client lost" = **0**; slow jobs now log the clean `canceling statement due to statement timeout` at 25s instead. Queue drains; remaining timeouts are pathological hub entities (edge-expansion bound, see above).

---

## Sub-Plan B — Universal chunk embedding (LIGHT gets BGE)

**Gap:** LIGHT = ~21% of corpus (3,862 docs / 6,925 chunks); only 13 have chunk embeddings →
invisible to semantic ANN retrieval (reachable only via the BM25/tsvector leg). Section embeddings
exist for LIGHT but chat queries chunk-granularity, so they're dead weight.

| Wave | Task | Files | Status |
|------|------|-------|--------|
| B-1 | `should_generate_chunk_embeddings` → include `SECTION_EMBEDDINGS_ONLY` (LIGHT); SUPPRESS stays HALT | `.../blocks/suppression.py` | ✅ done 2026-06-12 |
| B-2 | Stop emitting now-redundant LIGHT **section** embeddings (cleanup) — new `should_generate_section_embeddings` gate + `generate_section_embeddings` flag | `.../blocks/suppression.py`, `.../blocks/embeddings.py`, `.../article_consumer.py` | ✅ done |
| B-3 | Backfill the missing LIGHT chunk embeddings — dedicated one-shot script (NOT the retry worker; chunks were never enqueued in `embedding_pending`) | `.../workers/backfill_light_chunk_embeddings.py`, nlp_db | ✅ done |
| B-4 | Retrieval-noise guard: conservative `min_score=0.20` floor on the **pure-ANN** chunk leg only (NOT hybrid — would erase the FTS leg); `TrustScorer` already source-weights stubs | `.../retrieval_orchestrator.py` | ✅ done |
| B-5 | Deploy (rebuild article-consumer `--no-cache`) + validate retrieval | docker | ✅ |
| B-6 | Docs: update routing/embedding tier table | `docs/services/nlp-pipeline.md` | ✅ done |

**Cost:** ~$0.005 one-time + pennies/month. **Effort/risk:** low/low (1-line gate + backfill; no schema/contract change).

---

## Sub-Plan C — EmbeddingGemma cascade router (the core; thesis contribution)

Incremental: ship the learned classifier first, extend to the cascade. Built against
`docs/thesis/references-routing-and-infra.md`.

| Wave | Task | Status |
|------|------|--------|
| C-1 | EmbeddingGemma adapter in `libs/ml-clients` (DeepInfra; `task: classification` + `title:/text:` prompt; MRL truncation; 768d/256d) | ✅ done (`EmbeddingGemmaRouterAdapter`, 18 tests, live-verified `google/embeddinggemma-300m`) |
| C-2 | Compute + persist router embedding on `title + subtitle` at routing time (new column/table for training + inference) | pending |
| C-3 | Build labeled dataset: retroactive **extraction-yield** label per historical doc (≥1 relation/claim/event) JOINed to `routing_decisions`. Labels are now clean post the silent-except fix (timeouts no longer masquerade as "0 yield") |
| C-4 | Train baseline **logistic + LightGBM** on Gemma embeddings → P(yield); **calibrate** (Platt / isotonic) for a meaningful decision threshold |
| C-5 | **Ablation eval** (the thesis result): 5-hand-feature GBM (baseline-to-beat) vs embedding-classifier vs cascade, on a held-out labeled set; cost/accuracy table mirroring RouteLLM/FrugalGPT methodology |
| C-6 | Wire classifier into routing (replace the static weighted-sum; keep the 5 hand-features as a logged baseline + fallback). **Shadow mode first** — log proposed vs actual tier before flipping |
| C-7 | **Cascade**: escalate the uncertain band (P near threshold) to the existing **Llama-8B** relevance call for a tiebreak (FrugalGPT / learning-to-defer). No LLM on the confident majority |
| C-8 | Go-live + monitor: route distribution, extraction yield, downstream GLiNER + 235B load relief |

**Dependencies:** A and B are independent. C-3 depends on the already-shipped silent-except fix (clean
yield labels). The model A/B (235B vs alternatives — harness ready, judge = Claude Opus 4.8) runs
**after** the routing baseline lands, so models are measured against a non-overloaded pipeline.

**Why this beats the static weighted-sum:** the current `compute_routing_score` uses 5 shallow
proxies (entity_density, source_reliability, recency, document_type, extraction_yield) with hardcoded
weights and dead signals (`novelty/watchlist/price_impact`). The embedding router reads the article's
actual semantic content; the ablation proves the lift empirically.

---

## Tracking

Tasks: #27 (A), #28 (B), #29 (C). Research deliverable committed `f58e2db97`.
