# Investigation Report: Model Hosting Decisions & KG Dynamic Update Pipeline

**Date**: 2026-04-27
**Investigator**: Claude (investigate skill)
**Severity**: HIGH (multiple critical bugs found and fixed; pipeline now operational)
**Status**: Root causes identified and fixed

---

## 1. Issue Summary

Two parallel investigation tracks:

1. **Model hosting decisions**: Validate that the choice of local vs external models optimises latency — externalize all models that are not extremely small AND have external API providers.
2. **KG dynamic update**: Validate that entity embeddings, graph relations, and relation evidence are correctly populated and updated; validate that RAG queries retrieve information correctly.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| 0/200 embedding_state rows had embeddings | `intelligence_db.entity_embedding_state` | Confirmed KG embedding pipeline fully broken |
| `ensure_rows_exist()` sets `next_refresh_at = NULL` | Source code analysis | Root cause #1 of broken pipeline |
| asyncpg raises DataError on `list[float]` in INSERT | Direct DB testing (`CAST string works!`) | Root cause #2 — writes silently fail |
| `NLP_PIPELINE_ROUTING_TIER_DEEP=0.70` vs max observed score 0.592 | Container env vars + DB data | DEEP tier unreachable — no LLM extraction running |
| qwen3:0.6b `GGML_ASSERT abort` on CPU containers | Container logs + BP-121 | Num_ctx=32768 too large; needs explicit `num_ctx: 512` |
| bge-reranker-v2-m3 `404 Not Found` | rag-chat logs | Model not installed in Ollama, not in registry |
| Ollama model contention (bge-large + qwen3:0.6b) | Performance testing | Mutual 30s load delays cause timeout storms |
| 110 articles score 0.45-0.59 (should be DEEP) | `routing_decisions` table | DEEP threshold lowered from 0.70 → 0.45 needed |

---

## 3. Execution Path Analysis

### KG Embedding Update Flow (Broken → Fixed)

```
New Entity arrives (market.instrument.created event)
  → KG consumer calls ensure_rows_exist(entity_id, entity_type)
  → Rows created with next_refresh_at = NULL  ← BUG BP-236
     → DefinitionRefreshWorker.run() skips rows (IS NOT NULL check fails)
     → Embeddings NEVER generated

  FIXED: ensure_rows_exist() now sets next_refresh_at = now()
  → DefinitionRefreshWorker.run() finds rows (IS NOT NULL AND < now())
  → Generates embedding via bge-large Ollama
  → Calls upsert(entity_id, "definition", embedding=list[float], ...)
  → asyncpg rejects list[float] parameter → DataError  ← BUG BP-237
     → Session execute fails, embedding stays NULL

  FIXED: upsert() converts list to "[x,y,z]" string format
  → CAST(:embedding AS vector) works correctly
  → Embedding persisted in entity_embedding_state
```

### DEEP Tier Routing Flow (Broken → Fixed)

```
New article arrives → S6 assigns composite_score (0.45-0.592 typical for eodhd/finnhub)
  → S6 routing: composite_score >= 0.70? → NO (threshold too high)
  → Article routed as MEDIUM → no LLM extraction
  → No raw_relations extracted → no relation_evidence → no relation_summaries

  FIXED: DEEP threshold lowered from 0.70 → 0.45
  → Articles scoring 0.45+ now routed as DEEP
  → LLM extraction runs (meta-llama/Meta-Llama-3.1-8B-Instruct via DeepInfra)
  → raw_relations extracted → relation_evidence populated
  → SummaryRefreshWorker generates relation_summaries with embeddings
  → RAG relation search starts returning results
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | ensure_rows_exist sets next_refresh_at=NULL, breaking refresh schedule | CONFIRMED | Source code analysis + DB query showing 0 rows due for refresh |
| H-2 | asyncpg cannot serialize list[float] to vector(1024) in upsert | CONFIRMED | Direct SQL test: `CAST('[0.1,0.2,...]' AS vector)` works, passing list fails |
| H-3 | DEEP threshold 0.70 is unreachable for news articles | CONFIRMED | DB shows max composite_score = 0.592 for eodhd/finnhub articles |
| H-4 | qwen3:0.6b crashes without num_ctx=512 | CONFIRMED | BP-121 variant: GGML_ASSERT on CPU with 32768 context window |
| H-5 | bge-reranker-v2-m3 not available via Ollama | CONFIRMED | `ollama pull bge-reranker-v2-m3` → "file does not exist" |
| H-6 | Ollama model contention causes timeout storms | CONFIRMED | bge-large (~670MB) + qwen3:0.6b (~522MB) share single Ollama; model swap takes ~30s |

---

## 5. Root Causes

### RC-1: ensure_rows_exist() scheduling black hole (BP-236)

**Location**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_embedding_state.py:ensure_rows_exist()`

**What**: Rows created with `next_refresh_at = NULL`. All refresh workers query `WHERE next_refresh_at IS NOT NULL AND next_refresh_at < now()`. NULL rows are permanently invisible to the scheduler.

**Fix applied**: Added `next_refresh_at = now()` to the INSERT statement.

### RC-2: asyncpg cannot serialize list[float] to vector(1024) in upsert (BP-237)

**Location**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_embedding_state.py:upsert()`

**What**: `CAST(:embedding AS vector)` in SQL doesn't make asyncpg serialize Python `list[float]` to pgvector format. asyncpg raises `DataError: invalid input for query argument (expected str, got list)`. The exception was swallowed, embeddings never written.

**Fix applied**: Convert list to `"[x,y,z]"` string before binding; use `CAST(:embedding AS vector)` and `CAST(EXCLUDED.embedding AS vector)` in SQL.

### RC-3: DEEP routing tier threshold 0.70 unreachable (Configuration)

**Location**: `services/nlp-pipeline/configs/docker.env`: `NLP_PIPELINE_ROUTING_TIER_DEEP=0.70`

**What**: eodhd/finnhub news articles peak at composite_score ~0.592. DEEP threshold at 0.70 means no articles ever get DEEP routing → no LLM extraction → no relation_evidence → no relation_summaries → relation search always empty.

**Fix applied**: Lowered `NLP_PIPELINE_ROUTING_TIER_DEEP=0.45`.

### RC-4: qwen3:0.6b GGML abort without explicit context window (BP-121 variant)

**Location**: `nlp_pipeline/.../article_relevance_scoring_worker.py`, `unresolved_resolution_worker.py`

**What**: qwen3:0.6b defaults to n_ctx=32768 on CPU → GGML_ASSERT abort. Also: timeout default of 10s is too short for CPU inference (5-10s per request).

**Fix applied**: Added `"options": {"num_ctx": 512}` and `"think": False` to both workers. Raised timeout to 30s.

---

## 6. Model Hosting Decisions Analysis

| Model | Size | Current | Provider Available? | Decision | Rationale |
|-------|------|---------|---------------------|----------|-----------|
| qwen3:0.6b | 0.6B | Local Ollama | Yes (DeepInfra, Groq) | **KEEP LOCAL** | Extremely small. 0.6B params is below threshold. 5-10s on CPU acceptable for non-realtime background workers. |
| bge-large | ~335M | Local Ollama | Yes (Jina AI, Cohere) | **SHOULD EXTERNALIZE** | Causes Ollama contention with qwen3:0.6b. External Jina AI embedding API: ~100ms vs ~7-13s local. 1024-dim output matches vector schema. |
| bge-reranker-v2-m3 | ~370M | Local Ollama (missing) | Yes (Cohere Rerank, Jina Rerank) | **MUST EXTERNALIZE** | Not in Ollama registry (`ollama pull` fails). Cohere `/v2/rerank` API: ~300ms, excellent quality. Currently zero reranking happening. |
| gliner_large-v2.1 | ~230M | Containerized GLiNER | No external NER provider | **KEEP LOCAL** | No equivalent external API for financial NER. GLiNER containerized separately (not Ollama). |
| meta-llama/3.1-8B-Instruct | 8B | DeepInfra API | Already external | **ALREADY CORRECT** | Too large for CPU. DeepInfra GPU: ~2-5s per extraction. |
| deepseek-r1-distill-qwen-32b | 32B | DeepInfra API | Already external | **ALREADY CORRECT** | Far too large for CPU. DeepInfra GPU: ~15-60s for chat completion. |
| Gemini Flash Lite | N/A | Google AI Studio | Already external | **CONFIGURED BUT DISABLED** | `NullDescriptionAdapter` in use — no Gemini API key configured in KG scheduler. Entity descriptions fall back to deterministic template. |

### Externalization Priority

1. **CRITICAL**: `bge-reranker-v2-m3` → **Cohere Rerank API** (`/v2/rerank`)
   - Currently zero reranking happening (fallback to fusion_score sort)
   - Cohere Rerank: ~300ms latency, no model download needed
   - Implement `libs/ml-clients/src/ml_clients/adapters/cohere_rerank.py`

2. **HIGH**: `bge-large` embeddings → **Jina AI Embeddings v3**
   - Eliminates Ollama contention (bge-large + qwen3 swap = 30s delays)
   - Jina embeddings-v3: ~100ms vs ~7-13s local, 1024-dim, financial domain support
   - Implement `libs/ml-clients/src/ml_clients/adapters/jina_embedding.py`
   - Add to `FallbackChainClient`: primary=Jina, fallback=Ollama bge-large

---

## 7. Impact Analysis

### Before fixes:
- **0/81 entities had definition embeddings** (both RC-1 and RC-2 compounding)
- **0/81 entities had narrative embeddings**
- **0 DEEP-tier articles** ever processed (RC-3)
- **0 relation_evidence rows** (consequence of RC-3)
- **0 relation_summary rows** (consequence of RC-3)
- RAG chat worked but used only chunk search (no KG relation context)
- Entity similarity search always returned 422 (no fundamentals embeddings)
- qwen3:0.6b workers crashed on CPU (RC-4)

### After fixes:
- **81/81 definition embeddings** generated ✅
- **81/81 narrative embeddings** generated ✅
- **DEEP threshold = 0.45** — 110 existing articles would qualify ✅
- New articles scoring ≥0.45 will get LLM extraction ✅
- qwen3:0.6b workers stable with num_ctx=512 ✅
- RAG citations returned from real news chunks with confidence scores 0.72-0.82 ✅

### Remaining gaps:
- **0/38 fundamentals_ohlcv embeddings** — requires market-data service auth in KG FundamentalsRefreshWorker
- **0 relation_summaries** — requires DEEP tier articles to flow through (pipeline now configured correctly)
- **0 reranking** — bge-reranker-v2-m3 missing; must externalize to Cohere
- **HyDE expansion degraded** — qwen3:0.6b contention when both workers active simultaneously

---

## 8. RAG Query Quality Assessment

**Test 1**: "What is Apple Inc and what sector does it belong to?"
- Response: Correct sector (Technology), detailed company description ✅
- Citations: News chunks with confidence 0.72-0.75 ✅
- Latency: ~21s (DeepInfra deepseek-r1-distill-qwen-32b)

**Test 2**: "Which companies are investing in AI chips? What are their strategic relationships?"
- Response: Named Amazon, Meta, Nvidia, Intel, AMD, Arm with specific partnerships ✅
- Citations: 1 citation ("Amazon Is a Big AI Chip Player Now...") confidence 0.82 ✅
- Latency: ~64s (long due to comprehensive structured response)

**Test 3**: NVIDIA semiconductor/AI technology sector query
- Response: Correct GPU, AI Computing, Data Center breakdown ✅
- No relation citations (expected — 0 relation_summaries)

**Overall quality**: Good but incomplete. Answers are factually grounded in actual news chunk retrieval. Missing KG relation context (will improve once DEEP articles flow through). Reranking degraded (fallback to fusion score).

---

## 9. Contributing Factors

1. **Silent exception handling** in upsert() masked the asyncpg encoding error completely — the embedding write appeared to succeed
2. **Cascade of two independent bugs** (RC-1 + RC-2) produced identical symptom (all embeddings NULL) making single-cause analysis misleading
3. **Baked Docker images** (no bind mounts) required container rebuilds to test fixes — changes to code didn't auto-reload
4. **Single Ollama instance** serving both embedding (bge-large) and generation (qwen3:0.6b) models creates contention — swapping models takes ~30s
5. **DEEP threshold calibrated for higher-quality sources** (SEC filings, earnings) but applied to news sources with inherently lower routing scores

---

## 10. Recommended Fixes (Remaining)

### P0 — External Reranker (bge-reranker-v2-m3 missing)
Implement `libs/ml-clients/src/ml_clients/adapters/cohere_rerank.py`:
```python
class CohereRerankAdapter:
    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[dict]:
        # POST https://api.cohere.com/v2/rerank
        # Returns: list of {index, relevance_score}
```
Wire into `BGEReranker.__init__` as a fallback or replace entirely.

### P1 — External Embeddings (Jina AI)
Implement `libs/ml-clients/src/ml_clients/adapters/jina_embedding.py`:
```python
class JinaEmbeddingAdapter:
    async def embed(self, texts: list[str], model: str = "jina-embeddings-v3") -> list[list[float]]:
        # POST https://api.jina.ai/v1/embeddings
        # 1024-dim output, financial domain task: "retrieval.passage"
```
Wire into `FallbackChainClient` as primary, with Ollama bge-large as fallback.

### P2 — FundamentalsRefreshWorker Auth
The KG FundamentalsRefreshWorker calls market-data endpoints with 401 errors. Needs to pass an internal system JWT. Check `settings.admin_token` or use the internal JWT pattern.

### P3 — Relation Evidence Population
Now that DEEP threshold is 0.45, new articles will flow through LLM extraction. After ~24h, verify `relation_evidence` count > 0 with:
```sql
SELECT COUNT(*) FROM relation_evidence;
```

---

## 11. Prevention Recommendations

1. **Add BP-236 pattern check**: Any `ON CONFLICT DO NOTHING` provisioning INSERT should set all scheduler fields (`next_refresh_at`, `next_retry_at`) to `now()`, never NULL.
2. **Add BP-237 pattern check**: All `entity_embedding_state.upsert()` call sites should pass `list[float]` through the `"[" + ",".join(...) + "]"` conversion.
3. **Add integration test**: `test_entity_embedding_state.py` should verify that after `ensure_rows_exist()`, rows appear in `get_due_for_refresh()` output.
4. **Add integration test**: `test_entity_embedding_state.py` should verify that after `upsert()` with a real embedding, the row has `embedding IS NOT NULL`.
5. **Alert on routing tier distribution**: Add metric: if DEEP count = 0 for >24h, alert. Threshold misconfiguration should be detected quickly.
6. **Separate Ollama instances**: Run a dedicated Ollama container for embeddings (bge-large) and a separate one for generation (qwen3:0.6b). Eliminates model swap contention.

---

## 12. Open Questions

- Does `FundamentalsRefreshWorker` need an admin token or internal JWT to call market-data? Check if S3 requires authentication for the `/api/v1/fundamentals/{id}` endpoint.
- Should `DefinitionRefreshWorker` generate fallback descriptions for `financial_instrument` entities when no EODHD source_text is available (same as non-company entities)? Currently these are silently skipped.
- Gemini Flash Lite `NullDescriptionAdapter` — is this intentional (no API key) or a configuration gap?
