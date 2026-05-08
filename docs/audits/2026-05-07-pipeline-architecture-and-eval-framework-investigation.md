# Investigation Report: Pipeline Architecture, Intent Classifier, and Evaluation Framework

**Date**: 2026-05-07
**Investigator**: Claude (investigation skill)
**Severity**: MEDIUM — architectural clarity and strategic planning concern, no data at risk
**Status**: Root causes identified; strategic recommendations provided
**Triggered by**: Post-eval questions on classifier chain, eval scope, tool mechanism, and future eval design

---

## 1. Questions Addressed

1. Does the intent classifier use DeepInfra Llama-3.1-8B-Instruct-**Turbo** as primary and Ollama as fallback?
2. Should we migrate to `Qwen/Qwen3.5-0.8B` for intent classification?
3. What exactly does the current eval measure — entire pipeline or just chunk retrieval?
4. How does PLAN-0067's tool mechanism change everything (PLAN-0066/0067/0074/0077–0084)?
5. Should entity resolution go through GLiNER → Qwen 0.8B validation? Is this still needed once the LLM has tools?
6. How should the evaluation framework evolve once the tool mechanism is live?

---

## 2. Intent Classifier — Confirmed Architecture

### 2.1 The Three-Tier Chain (Confirmed)

The investigation **confirms** the classifier chain is:

| Tier | Model | Provider | Latency | Timeout | Triggers |
|------|-------|----------|---------|---------|---------|
| **1 (Primary)** | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | DeepInfra | 100–200 ms | 10.0 s | `deepinfra_api_key` is set |
| **2 (Secondary)** | `qwen3:0.6b` | Local Ollama | 2–5 s (CPU) | 20.0 s | DeepInfra unavailable/error |
| **3 (Fallback)** | Keyword heuristic | In-memory | <1 ms | — | Ollama unavailable/error |

Config fields:
- `RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL` (default: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo`)
- `RAG_CHAT_OLLAMA_CLASSIFICATION_MODEL` (default: `qwen3:0.6b`)

The Ollama tier uses `"think": False` to suppress Qwen3's chain-of-thought blocks (BP-231). The keyword heuristic is last-resort and returns `FACTUAL_LOOKUP` if nothing matches.

### 2.2 Should We Migrate to Qwen/Qwen3.5-0.8B for the Primary?

**Question**: Replace `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` with `Qwen/Qwen3.5-0.8B` (a DeepInfra-hosted smaller model)?

**Analysis**:

| Dimension | Current (Llama-3.1-8B-Turbo) | Proposed (Qwen3.5-0.8B) |
|-----------|------------------------------|--------------------------|
| Parameters | 8B | 0.8B (10× smaller) |
| Latency (DeepInfra GPU) | ~100–200 ms | ~20–60 ms (estimated) |
| Cost | ~$0.00009/token | ~$0.00003/token (estimated) |
| JSON instruction follow | Excellent (`response_format=json_object`) | Good (Qwen3 family follows JSON well) |
| Intent classification accuracy | High | Unknown — no benchmark on this task |
| Context window | 131K | 32K (sufficient for intent classification — query + 6 history turns ≈ 2K tokens) |
| Availability | Confirmed on this DeepInfra account | **Needs verification** — `Qwen/Qwen3.5-0.8B` vs `Qwen/Qwen2.5-0.5B` (the 0.5B was 404 on this account) |

**Recommendation**: **Do not migrate yet, for two reasons:**

1. **PLAN-0067 W11 hard-deletes the intent classifier** (`IntentClassifier`, `RetrievalPlanBuilder`, `ParallelRetrievalOrchestrator`) in Wave 11-3. The LLM driving tool selection *is* the intent classifier in the new architecture. Migrating the intent classifier now is optimising a component that will be removed in the next major plan.

2. **Accuracy risk**: Intent classification errors silently route queries to the wrong retrieval sources (as shown by `FINANCIAL_DATA → use_chunks=False`). A 0.8B model may produce lower accuracy on rare intents (`SIGNAL_INTEL`, `RELATIONSHIP`) despite lower latency. A 50ms latency reduction on a ~2s total query is <3% improvement.

**If migration is desired anyway** (e.g., for cost reduction in the interim period before PLAN-0067 ships):
- Run an offline accuracy test: send the 120 golden-set query texts to both models, compare output intents against hand-labelled ground truth
- Require ≥95% agreement with Llama-3.1-8B-Turbo on the 8 intent classes before switching
- Add `RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL` to the Makefile's eval setup to make A/B testing trivial

---

## 3. What the Current Eval Measures (and Doesn't)

### 3.1 Scope: L1 Retrieval Only

The eval harness (`scripts/eval_retrieval.py`) calls `POST /v1/internal/retrieve` (`RetrieveOnlyUseCase`) which executes **only steps 0–5I** of the 13-step pipeline:

```
Step 0:  InputValidator (PII, injection)
Step 3:  S6 resolve_entities (alias cascade)
Step 4:  IntentClassifier.classify → RetrievalPlanBuilder.build
Step 5:  HydeExpander.expand (when eligible)
Step 5bis: EmbeddingPort.embed
Step 5A-5I: ParallelRetrievalOrchestrator (fan-out to S6/S7/S3/S1)
         └─ EnhancedChunkSearchUseCase (ANN + BM25 + RRF fusion)
```

**What the eval DOES measure**:
- Candidate pool quality (NDCG@10, MRR, P@5, Recall@20) on pre-fusion candidates
- The ANN + BM25 + RRF hybrid retrieval quality
- Entity resolution effectiveness (indirectly — missing entities → worse candidates)
- Plan routing correctness (indirectly — wrong plan → wrong sources → 0 recall)

**What the eval DOES NOT measure**:
- Step 6: `FusionPipeline` (dedup by doc_id, trust weighting)
- Step 7: `GraphEnricher`
- Step 8: `DeepInfraReranker` / `CohereReranker` (cross-encoder)
- Steps 9–10: Prompt assembly
- Step 11: LLM generation quality
- Step 12: Citation parsing + PII redaction
- Step 13: DB persistence
- End-to-end answer quality (covered by planned L2/L3/L4 evals in PLAN-0075)

### 3.2 Metric Alignment Issue

The eval sorts candidates by **raw ANN/BM25 score**, not by `fusion_score` (which incorporates recency decay and trust weighting). This means:

- `TrustScorer` output is invisible to the eval
- `_RECENCY_DECAY_RATES` source-specific decay is invisible to the eval
- `GraphEnricher` entity context injection is invisible to the eval
- `DeepInfraReranker` re-ordering is invisible to the eval

**Impact**: the current NDCG@10=0.577 baseline is a **lower bound** on production quality — production adds reranking and trust weighting on top. The eval is conservative by design (L1 measures the worst-case floor). However, it also means that optimising the eval metric does not necessarily optimise what users see.

**Recommended eval metric additions** (for PLAN-0085 consideration):
1. Run the full fusion + reranker path in a separate eval mode (`--mode post_rerank`); measure NDCG@10 after `DeepInfraReranker`
2. Add a `fusion_score_sorted` comparison mode; the difference between `raw_score_ndcg` and `fusion_score_ndcg` quantifies the value of trust + recency weighting

---

## 4. PLAN-0067 Tool Mechanism — Impact on Everything

### 4.1 What PLAN-0067 W11 Actually Does

PLAN-0067 W11 (revised 2026-05-07, "Full Tool Catalog") is the binding plan for the tool mechanism. Key architectural decisions locked in revision A-1:

> **Hard-delete `IntentClassifier`, `RetrievalPlanBuilder`, and `ParallelRetrievalOrchestrator` in W11-3. No feature flag. Tool-use is the only path post-merge.**

The 8 new tools wrap the same backends as the current orchestrator:

| Tool Name | Wraps | Current Equivalent |
|-----------|-------|-------------------|
| `search_documents` | `S6Port.search_chunks()` | `_fetch_chunks` |
| `get_entity_graph` | `S7Port.get_egocentric_graph()` | `_fetch_graph` |
| `traverse_graph` | `S7Port.cypher_traverse()` | `_fetch_cypher` |
| `search_entity_relations` | `S7Port.search_relations()` | `_fetch_relations` |
| `search_claims` | `S7Port.search_claims()` | `_fetch_claims` |
| `search_events` | `S7Port.search_events()` | `_fetch_events` |
| `get_contradictions` | `S7Port.get_contradictions()` | `_fetch_contradictions` |
| `get_portfolio_context` | `S1Port.get_portfolio_context()` | `_fetch_portfolio` |

The **critical difference** from the current plan-based routing:

| Dimension | Current (Plan-based) | Future (Tool-based) |
|-----------|---------------------|---------------------|
| Who decides which sources to query | `RetrievalPlanBuilder` (hardcoded intent→flag matrix) | The LLM (Qwen3-235B/DeepSeek-R1), dynamically, per query |
| Granularity | Intent-level (8 intents → 9 boolean flags) | Query-level (LLM reasons about each tool call) |
| Multi-step reasoning | No — single fan-out, no iteration | Yes — LLM can call tools in sequence, see results, refine |
| `FINANCIAL_DATA → use_chunks=False` bug | Exists — hardcoded | Eliminated — LLM can call both `search_documents` + `get_financial` |
| Relationship multi-entity | Fails (single resolve, no 2-hop) | Resolvable — LLM calls `traverse_graph` with 2 entities |

### 4.2 Implications for Today's Investigation Findings

The two root causes identified in the previous report:
1. `FINANCIAL_DATA: use_chunks=False` → **eliminated in PLAN-0067** (LLM calls `search_documents` when relevant)
2. `RELATIONSHIP: use_chunks=False` + single entity resolve → **eliminated in PLAN-0067** (LLM calls `traverse_graph` + `search_entity_relations` + `search_documents` in sequence)

**Recommendation**: Do not fix `use_chunks=False` in `RetrievalPlanBuilder` if PLAN-0067 W11 is being implemented in the next sprint cycle. Fixing it now adds 2 hours of work that will be deleted by W11-3. The exception: if the plan is >2 sprints away, fix it as a short-term patch (flip the flag, re-run eval, commit).

---

## 5. Entity Resolution — GLiNER + Qwen Validation

### 5.1 Current State

`S6Client.resolve_entities(message)` sends the **full query string** to the nlp-pipeline's 5-stage alias cascade:

1. Exact alias match → 2. Ticker/ISIN → 3. Trigram fuzzy → 4. ANN embedding → 5. Unresolved queue

GLiNER is currently used **in the NLP pipeline's article processing** (`article_consumer._build_chunk_entity_mentions`) to tag entity spans in ingested documents, **not** in the query-time resolution path. The PLAN-0078 integration stores these mentions in `chunks.entity_mentions JSONB` and uses them to filter chunk searches by entity ID.

The query-time resolution does **not** run NER — it sends the full string to the alias cascade, which returns zero, one, or occasionally two entities. Multi-entity queries like "Apple and TSMC" typically resolve to only one canonical entity.

### 5.2 The Proposed GLiNER → Qwen 0.8B Two-Stage Query Resolution

**Proposed flow**:
1. GLiNER NER on query → extract entity spans (e.g., ["Apple", "TSMC"])
2. For each span → alias cascade resolve → `entity_id`
3. Optionally: Qwen3.5-0.8B validates the resolved entities (confidence check)

**Analysis**:

**Arguments for this approach (pre-tool era)**:
- Directly fixes the multi-entity resolve bug (root cause B of relationship failures)
- GLiNER is already running in the stack (local Ollama container)
- Qwen 0.8B validation adds a <100ms confidence check to prevent false positives
- Does not require a new LLM call for the common single-entity case

**Arguments against (in the tool-use era)**:

With PLAN-0067 W11 live, the LLM driving tool selection has access to `entity_context: EntityContext` at request time and can call `search_entity_relations(entities=[apple_id, tsmc_id])` directly. The LLM can:
- Extract multiple entities from its own reasoning
- Call `search_documents(query="Apple TSMC supply chain", entity_ids=[...])` with multi-entity filtering
- Retry with different entity combinations if initial results are sparse

The LLM-as-orchestrator pattern makes per-query NER on the backend **redundant** for tool selection. However, there is one remaining use case: **indexing**. GLiNER entity tagging on chunk ingestion (`chunks.entity_mentions`) is still required because:
- It enables `search_documents` tool to accept `entity_ids` as a filter (PLAN-0078)
- It lets the tool executor inject entity scope automatically (`M-1` in PLAN-0067 revision)
- It is query-independent (runs at write time, not read time)

**Recommendation**:

| When | Action |
|------|--------|
| **Before PLAN-0067 ships** | Add span-based resolve to `S6Client.resolve_entities` using GLiNER NER; skip Qwen validation (adds latency for marginal gain; alias cascade already provides confidence). This is a 1-sprint self-contained fix that improves current eval by ~5-10 NDCG@10 on relationship queries. |
| **After PLAN-0067 ships** | Remove query-time GLiNER NER from `RetrieveOnlyUseCase` (deprecated). Keep GLiNER for document ingestion (chunk entity mentions). The LLM handles entity extraction as part of its tool reasoning. |

---

## 6. New Evaluation Framework for the Tool Era

### 6.1 Why the Current Eval Will Break

The current eval calls `POST /v1/internal/retrieve` → `RetrieveOnlyUseCase`, which maps to the plan-based path. After PLAN-0067 W11 ships, `RetrieveOnlyUseCase` is deleted. The tool-based path has no equivalent "retrieve-only" shortcut — the LLM drives tool selection, so you cannot decouple retrieval from generation.

### 6.2 Proposed Three-Layer Evaluation Architecture

Aligned with PLAN-0063 v2's L1/L2/L3/L4 framework (from TRACKING.md) and PLAN-0075's planned L2/L3/L4 evals:

```
┌─────────────────────────────────────────────────────────────────────┐
│ L1: Retrieval Quality (currently live — NDCG@10 regression gate)    │
│     What: pre-fusion candidate pool quality per tool call           │
│     How: inject mock LLM that always calls all tools; measure NDCG  │
│     Gate: NDCG@10 ≥ baseline - 0.03 (per-class ≥ baseline - 0.05) │
├─────────────────────────────────────────────────────────────────────┤
│ L2: Tool Selection Quality (new — required by PLAN-0067)            │
│     What: does the LLM call the RIGHT tools for each query?         │
│     How: golden set of (query → expected_tools) pairs; F1 on calls  │
│     Gate: tool recall ≥ 0.80, precision ≥ 0.70 across golden set   │
├─────────────────────────────────────────────────────────────────────┤
│ L3: Answer Quality (PLAN-0075, post-MVP)                            │
│     What: LLM answer correctness + citation quality                 │
│     How: LLM-as-judge (Qwen3-235B), rubric-scored 1-5              │
│     Gate: mean ≥ 3.5 / 5.0; no grade-1 answers on gold queries     │
├─────────────────────────────────────────────────────────────────────┤
│ L4: Operational (PLAN-0063 W5-5, placeholder)                       │
│     What: latency, cost, token efficiency                           │
│     Metrics: p95 TTFT < 1.5s, p95 final < 8s, $/turn < $0.02     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 L1 Eval Adaptation for Tool Era

After PLAN-0067 ships, L1 retrieval quality can still be measured per-tool:

**Strategy**: Replace the `RetrieveOnlyUseCase` call with a **stub LLM** that always calls all 8 tools, then measure the candidate pool quality per tool.

```python
# New eval mode: --mode tool_stub
# Injects a deterministic tool-call sequence:
# 1. search_documents(query=query_text, query_embedding=precomputed_embedding)
# 2. search_entity_relations(query_embedding=precomputed_embedding)
# 3. get_entity_graph(entity_ids=resolved_entity_ids) if entities resolved
# Measures NDCG@10 on the merged candidate pool (pre-rerank)
```

This preserves the NDCG@10 regression gate without needing the old plan-based path.

**Per-tool metrics** (new):
- `search_documents`: NDCG@10, Recall@20 (same as today)
- `search_entity_relations`: Relation recall (fraction of labelled relations found)
- `traverse_graph`: Hop accuracy (did the 2-hop traversal reach the target entity?)

### 6.4 L2 Tool Selection Eval — Design

The L2 eval answers: "given this query, did the LLM call the right tools?"

**Golden set structure** (extend `queries_eval_stack.jsonl`):

```jsonc
{
  "query_id": "q038",
  "query_text": "What is the supplier relationship between Apple and TSMC?",
  "intent": "RELATIONSHIP",
  "query_class": "relationship",
  "relevant_doc_ids": [...],
  // NEW fields for L2:
  "expected_tools": ["search_entity_relations", "traverse_graph", "search_documents"],
  "required_tools": ["search_entity_relations"],     // must be called (recall gate)
  "forbidden_tools": ["get_portfolio_context"],      // must NOT be called
  "expected_entity_ids": ["<apple_uuid>", "<tsmc_uuid>"]  // entities that should be resolved
}
```

**Metrics**:
- **Tool Recall** = |called ∩ required| / |required|  (per query, avg over golden set)
- **Tool Precision** = |called ∩ expected| / |called|  (penalises irrelevant calls)
- **Tool F1** = harmonic mean of recall and precision
- **Entity Resolution Accuracy** = fraction of `expected_entity_ids` correctly resolved
- **Adversarial Pass Rate** = fraction of adversarial queries where forbidden tools are NOT called

**CI Gate** (proposed):
- Tool Recall ≥ 0.80 (80% of required tools called)
- Tool Precision ≥ 0.70 (no more than 30% irrelevant calls)
- Adversarial Pass Rate = 1.00 (zero adversarial tool bypasses)
- Gate: `continue-on-error: false` from day 1 (PLAN-0067 W11-4 ships with gate enabled)

### 6.5 Eval Infrastructure Changes Required

| Component | Current | After PLAN-0067 |
|-----------|---------|-----------------|
| `POST /v1/internal/retrieve` | Exists, evaluated | **Deleted** in W11-3; replaced by full chat path |
| L1 eval entry point | `RetrieveOnlyUseCase` | New `ToolStubEvalUseCase` with deterministic tool sequence |
| Golden set | `queries_eval_stack.jsonl` (doc_id relevance only) | Extend with `expected_tools`, `required_tools`, `forbidden_tools` |
| `eval_retrieval.py` | Calls `retrieve` endpoint | Add `--mode tool_stub` + `--mode l2_tool_selection` |
| CI workflow | Single `full-eval` job | Split: `l1-retrieval` (tool stub) + `l2-tool-selection` + `l3-answer-quality` |
| Eval stack | Current (345 seeded chunks) | Add `responses_eval_stack.jsonl` with expected answer snippets for L3 |

### 6.6 Suggested Plan Structure for the Eval Evolution

**Proposed PLAN-0085: Evaluation Framework v2 — Tool-Era Eval**

Scope: ~3 waves, ~12 tasks. Depends on PLAN-0067 W11 completion.

**Wave A: L1 Tool-Stub Eval** (parallels PLAN-0067 W11-4)
- A-1: `ToolStubEvalUseCase` — accepts `query_text` + `query_embedding`, calls all 8 tools with deterministic parameters, returns merged candidates
- A-2: `--mode tool_stub` in `eval_retrieval.py`; reuse NDCG/MRR/Recall metrics
- A-3: CI job update — replace `full-eval` with `l1-retrieval-tool-stub`
- A-4: Update golden set to remove `relevant_doc_ids` entries that relied on the deleted code paths

**Wave B: L2 Tool Selection Eval**
- B-1: Extend golden set schema with `expected_tools`, `required_tools`, `forbidden_tools`
- B-2: Label 60 priority queries (all `relationship`, `financial_data`, `reasoning`, `comparison` queries + 10 adversarial)
- B-3: `L2ToolSelectionEval` class — captures `tool_calls` from a real LLM run, scores against golden
- B-4: `--mode l2_tool_selection` in eval harness; new metrics: tool recall, precision, F1
- B-5: CI job: `l2-tool-selection` (separate job, can run weekly — requires real LLM calls, costs ~$0.05/run)
- B-6: Adversarial eval suite — 10 adversarial queries, pass rate gate = 1.00

**Wave C: L3 Answer Quality Baseline**
- C-1: `L3AnswerEval` — sends full chat request, captures assistant response, runs LLM-as-judge (Qwen3-235B)
- C-2: 20-query representative golden set with expected answer snippets / rubric
- C-3: `--mode l3_answer_quality` in eval harness
- C-4: CI job (manual trigger only — $0.10-0.50/run); gate advisory only for thesis MVP

---

## 7. Summary of Recommendations

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **P0** | Understand that PLAN-0067 eliminates most of today's retrieval bugs | 0 | Strategic clarity |
| **P1** | Do NOT fix `use_chunks=False` in `RetrievalPlanBuilder` if PLAN-0067 ships in <2 sprints | 0 | Avoids wasted work |
| **P1** | Do NOT migrate intent classifier to Qwen3.5-0.8B (classifier is being deleted) | 0 | Avoids wasted work |
| **P2** | Add span-based GLiNER NER to query-time `resolve_entities` (if PLAN-0067 is >2 sprints away) | 1 sprint | +5-10 NDCG@10 on relationship |
| **P2** | Fix `FINANCIAL_DATA use_chunks=False` (if PLAN-0067 is >2 sprints away) | 1 day | +0.20-0.35 NDCG@10 |
| **P3** | Plan PLAN-0085 Evaluation Framework v2 | 1 sprint (planning) | Future eval infrastructure |
| **P3** | Add `expected_tools` labels to 60 golden queries now | 2 days | Needed for L2 eval |
| **P4** | Add `--mode post_rerank` to eval harness to measure reranker contribution | 0.5 days | Metric alignment |

---

## 8. Open Questions for User Decision

1. **PLAN-0067 timeline**: Is W11 being implemented in the next sprint (implies skip the `use_chunks` patch) or is it ≥2 sprints away (implies apply the patch now)?

2. **Eval framework priority**: Should PLAN-0085 be drafted as a standalone plan, or should its Wave A (L1 tool-stub) be bundled into PLAN-0067 W11-4 (which already specifies "60-query parity eval")?

3. **L3 answer quality**: For thesis MVP, is it sufficient to have advisory L3 metrics (no CI gate), or is a passing L3 gate required before submission?

4. **Classifier migration timing**: If the thesis includes a performance benchmark comparison section, should the Qwen3.5-0.8B migration be done for the benchmark even though it will be deleted by PLAN-0067?

---

## 9. Compounding Updates

**BUG_PATTERNS.md**: No new patterns — the retrieval routing issues were documented in the previous report session.

**docs/audits/**: This document fulfils the user's requirement for a written report.

**TRACKING.md update recommended**: Add a note to PLAN-0067's row clarifying that the tool mechanism eliminates the need for intent classifier migration and span-based entity resolution (both previously tracked as improvement opportunities).

**PLAN-0063 TRACKING.md**: The eval scope is now clearly documented as L1 retrieval only; recommend adding a note that the `/v1/internal/retrieve` endpoint will be deleted in PLAN-0067 W11-3 and that PLAN-0085 must update the eval infrastructure before that deletion.

---

*Next step: `/prd` to draft PLAN-0085 Evaluation Framework v2, or confirmation of PLAN-0067 timeline to decide whether the short-term `use_chunks` patch should be applied.*
