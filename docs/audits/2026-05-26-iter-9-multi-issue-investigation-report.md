# ITER-9 Multi-Issue Investigation Report — 2026-05-26

Six parallel investigations covering all open issues surfaced by ITER-8 chat-eval (verdicts: 7 USEFUL / 0 USELESS / 0 HARMFUL; only failure: p99 91.9s > 60s gate). No code modified.

Branch: `feat/plan-0093-remediation`. Reference run: `tests/validation/chat_eval/runs/20260526T030829Z/`.

---

## §1 Fundamentals data corruption (task #89, FIX-LIVE-MM)

**Root cause**: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:83-86` queries `INCOME_STATEMENT` records without filtering `period_type`. The ingestion consumer at `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:451-478` stores **both QUARTERLY and ANNUAL** income-statement rows under the same section enum but distinct `period_type` values. The use case then joins them by `period_end` date alone (`get_fundamentals_history.py:95-98`), so when an annual row shares its `period_end` with a quarterly row the dict overwrite returns annual revenue/EPS in a quarterly slot.

**Why earnings looked fine**: `fundamentals_consumer.py:514` keeps `earnings_history` as QUARTERLY-only, so the join's earnings side is clean — but the income side is mixed, which is why quarterly EPS lines up next to annual revenue.

**Evidence**:
- AMD Q1 FY2026 returned **$34.6B** (annual ~$25-26B; quarterly ~$7-8B)
- NVDA Q1 FY2026 returned **$130.5B** — *exactly* NVDA's FY2025 annual revenue
- AMD Q2 / NVDA Q2 values were correct → mixing only when annual `period_end` happens to fall in the requested quarterly window
- FIX-LIVE-P (commit `6b61eaa6`, task #56) addressed labeling (`fiscal_year_end_month`) but did NOT add a periodicity filter to income queries

**Minimal fix**:
```python
# services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:83
income_records = await self._uow.fundamentals_read.find_by_section(
    iid_str,
    FundamentalsSection.INCOME_STATEMENT,
    period_type=PeriodType.QUARTERLY,  # ← NEW
)

# services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:107
async def query_fundamentals(
    session: AsyncSession, security_id: str, section: FundamentalsSection,
    period_type: PeriodType | None = None,  # ← NEW
) -> list[FundamentalsRecord]:
    ...
    if period_type is not None:
        stmt = stmt.where(model_class.period_type == str(period_type))
```

**Regression test**: seed QUARTERLY ($50B) + ANNUAL ($200B) income rows at the same `period_end`; assert returned revenue == $50B and EPS matches the quarterly earnings row.

---

## §2 Fundamentals slow path (task #85, FIX-LIVE-KK)

**Query path**: `services/market-data/src/market_data/api/routers/fundamentals.py:69-116` → `get_fundamentals_history.py:77-92` (three sequential `find_by_section` calls for earnings, income, highlights) → `services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_query.py:107-154`.

**Bottleneck**: schema (`services/market-data/alembic/versions/001_initial_schema.py:43-62`, `_base.py:26-31`) creates only a **single-column index on `instrument_id`**. The query is `WHERE instrument_id = :id ORDER BY period_end_date ASC` — so Postgres index-seeks by `instrument_id`, fetches every matching row, then sorts in memory. With ~50k-row section tables this is the 10–22 s tail.

**Fix**: replace single-column index with composite `(instrument_id, period_end_date ASC)` on all 14 fundamentals section tables introduced in migration 019. Enables an index-only range scan and eliminates the sort.

```sql
CREATE INDEX ix_earnings_history_instrument_period
  ON earnings_history(instrument_id, period_end_date ASC);
-- repeat for income_statements, balance_sheets, cash_flow_statements,
-- highlights, valuation, technicals, splits_dividends, esg_scores,
-- analyst_ratings, insider_transactions, institutional_holders,
-- earnings_estimates, earnings_trend
```

**Expected speedup**: 15–22 s → 50–300 ms (30–100×). Migration is forward-compatible (additive index); rollback drops the new indexes.

---

## §3 Latency p99 + tool fan-out batching

**Decomposition of `agg_q6` (95.2 s, 10 tool calls)**:
- Classifier (`validate_input`, fail-open at 10 s): 5–8 s
- First-turn LLM decision: 2–3 s
- Tool fan-out (parallel via `asyncio.gather` at `chat_orchestrator.py:765`): ~1.2 s wall-clock for 7 concurrent
- Second-turn LLM + retry of missing tickers: 2–3 s + 1 s
- Streaming + grounding validation: 1.5–2 s
- **Baseline ~15–17 s. Remaining ~78 s** = DeepInfra inference variance + multi-turn cascade (model needs 3 LLM turns because it iterates: screener → fundamentals fan-out → retries).

**Parallelism is fine** within a turn (already `asyncio.gather`). The real cost is **multi-turn sequential LLM latency** — the model takes 3 turns where 1 would do if it could batch.

**Batch API proposal** — `get_fundamentals_history_batch(tickers: list[str], periods: int)`:
- New rag-chat tool in `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py` (sketch ~30 lines)
- New market-data route `POST /v1/fundamentals/batch` that does `await asyncio.gather(*[uc.execute(...) for ticker in tickers], return_exceptions=True)` so per-ticker failures don't fail the batch
- Response shape: `{results: {ticker: {status: "ok"|"error", periods?: [...], reason?: str}}}`
- Collapses screener → fundamentals from 3 LLM turns to 1

**Classifier reordering** — `chat_pipeline.py:457` currently runs `validate_input()` before `check_cache()`. Swapping the order means the 15 % cache-hit traffic skips 5–8 s of classifier work. Security argument: a poisoned cache entry was classified on its *first* write; re-classifying every read is defensive duplication, not a gate.

**Estimated combined improvement**: p99 **91.9 s → ~45 s (51 %)**, meeting the 60 s gate with margin. Cache-first saves another 3–5 s on non-tail traffic.

---

## §4 Tool selection misses & documentation

**Overlapping tools** (all in `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py`):

| Tool | Line | Today's wording leaks ambiguity because… |
|---|---|---|
| `get_entity_graph` | 205-216 | Lists "who does X compete with" as an example, encouraging use for category queries it can't answer when KG has sparse `competitor_of` edges |
| `traverse_graph` | 250-287 | Says "any question involving TWO named entities" — model uses for one-entity peer questions too |
| `get_entity_paths` | 503-533 | Pre-ranked S7 paths — wording overlaps `traverse_graph` |
| `get_entity_intelligence` | 565-590 | Bundles narrative + paths + relations + health — but the description gates use on phrases like "tell me everything", so model avoids it for short questions |
| `compare_entities` | 618-639 | Financial-only comparison; model doesn't realise it's NOT a relationship tool |

**Per-question diagnosis**:
- **Q1** ("Apple competitors") → picked `get_entity_graph` with `relation_types=['competitor_of']`; KG is sparse so it returns empty and the model falls back to training knowledge. Should have picked `get_entity_intelligence` (bundles `relations_summary`) or `compare_entities`.
- **Q3** ("Tim Cook before Apple") → picked `get_entity_graph + search_documents`; no tool description mentions biographical / employment-history queries. `get_entity_intelligence` (narrative) would cover it.
- **Q8** isolated (0 tools, 0.9 s) → **cache hit** confirmed in events (`"event": "cache_hit"`). Correct behavior — the grader's required-tool list is over-prescriptive for cache-served answers.

**Description rewrites** (verbatim before/after in the agent's report). Key additions: explicit "DO NOT use for…" clauses on `get_entity_graph` and `traverse_graph`; "(2) biographical/timeline questions about people/executives" added to `get_entity_intelligence`.

**Intent-classifier gaps** (`services/rag-chat/src/rag_chat/application/services/intent_inference.py:45-54`):
- Missing entries: `get_entity_intelligence`, `search_entity_relations`, `get_entity_narrative`. These map to `GENERAL` today, losing the chance to switch to a relationship-specialised second-turn prompt.

**Grader note**: `tests/validation/chat_eval/test_q8_openai_msft_paths.py` should accept cache-hit as valid when grader expects a tool — either skip the tool requirement on `cache_hit` events or set `RAG_COMPLETION_CACHE_DISABLED=true` for the grading session.

---

## §5 Cache poisoning (iter3_top5_market_cap persistence)

**All caches in rag-chat**:

| File:Line | Cache | Key shape | TTL |
|---|---|---|---|
| `application/caching/completion_cache.py:32` | `CompletionCache` | `rag:v3:completion:sha256(message:thread_id)` | 24 h |
| `infrastructure/clients/s1_client.py:32` | Portfolio context (S1) | `s1:v1:portfolio_ctx:{user_id}` | 5 min |
| `infrastructure/cache/valkey_chunk_cache.py:18-20` | Retrieval chunks | `s8:ctx:chunks:{thread_id}:{turn_num}` | 4 h |
| `infrastructure/cache/valkey_chunk_cache.py:18-20` | Turn summaries | `s8:ctx:summary:{thread_id}:{turn_num}` | 24 h |

**Culprit**: `CompletionCache` with the test-harness sending no `thread_id`. In `tests/validation/chat_eval/harness.py:216` the payload is `{"message": question, "entity_ids": ...}` — no thread_id → cache key becomes `sha256(message:None)`. The conftest at lines 19-23 even warns: *"Use a fresh `thread_id` per test, OR set `RAG_COMPLETION_CACHE_DISABLED=true`. A module-scoped `thread_id` will serve a cached answer from an earlier run, masking regressions."* — but the harness doesn't enforce it.

The iter3_top5 artifact shows `screen_universe` returned correct mega-caps (NVDA/AAPL/MSFT/CRM/MSTR) yet the final answer talks about "Unity Software Inc (U)". That string was injected somewhere outside the tool result — either a v2-era leftover served from a non-flushed Valkey replica, or a same-session collision with a thread_id=None entry from an earlier test in the suite.

**Fix recommendation** (in priority order):
1. **Harness**: generate `thread_id=str(uuid4())` per `ask()` call in `tests/validation/chat_eval/harness.py`. Promotes the conftest invariant from advisory to enforced.
2. **Grader signal**: emit `completion_cache_coherence_error` when a cache-hit answer mentions an entity not in the tool result.
3. **Eval-time bypass**: set `RAG_COMPLETION_CACHE_DISABLED=true` (env var read in `chat_pipeline.py`) for chat-eval runs. Cache is a production optimisation; eval should measure cold-path behavior.

---

## §6 Worker tuning (tasks #82 + #80)

### Path-insight (HH2)

`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_explanation_batch_worker.py`

- Current: batch 200, concurrency 5, cycle 20 min → ~400 rows/h
- Backlog (audit 2026-05-25): 4,710 stale rows → 11.8 h drain
- **Proposed**: batch 300, concurrency 7, cycle 12 min → **1,260 rows/h, 3.7 h drain**

```
KNOWLEDGE_GRAPH_PATH_EXPLANATION_BATCH_SIZE=300
KNOWLEDGE_GRAPH_PATH_EXPLANATION_CONCURRENCY=7
KNOWLEDGE_GRAPH_PATH_EXPLANATION_CYCLE_MINUTES=12
```

### 6 starving workers (INV-GG, audit `docs/audits/2026-05-25-iter-5-results-and-closeout.md:197-224`)

Cluster 1 — external-dep blocked:
1. `PriceImpactLabellingWorker` (nlp-pipeline) — JWT mint races api-gateway readiness. Needs 3-retry exponential backoff or deferred client creation on first `run_once()`.
2. `ArticleRelevanceScoringWorker` (nlp-pipeline) — `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` empty → falls back to Ollama → Ollama down. Wire the same DeepInfra key used by other workers.

Cluster 2 — long intervals + small batches inside one asyncio loop:
3. `SummaryWorker` — 7 % coverage; interval 3600→600 s, batch 20→50.
4. `EmbeddingRefreshWorker` — 10 % NULL definitions; interval already 300 s (committed), raise `batch_limit` 50→200.
5. `DefinitionRefreshWorker` — 59.5 % NULL company descriptions; `KNOWLEDGE_GRAPH_GEMINI_API_KEY` missing, no DeepInfra fallback. Add the fallback chain used elsewhere.
6. `FundamentalsRefreshWorker` — 0/2,405 OHLCV embeddings; S7 migration 0003 unconfirmed live; verify S2 OHLCV ingestion is producing events.

**Architectural note**: Cluster 2 runs five LLM-bound workers in a single asyncio loop with no true CPU parallelism. Long-term, follow the nlp-pipeline pattern and extract each into its own container; short-term, the interval/batch tuning above is enough to clear the visible backlog.

**Already committed** (commit `9ad96dc5`, 2026-05-25): docker-compose `depends_on` fixes for relevance-scoring worker; DefinitionRefresh interval 3600→300 s.

---

## Cross-cutting recommendations

1. **Highest leverage**: §1 (fundamentals periodicity filter) — kills the only HARMFUL-shaped failure mode left, single-file fix + one repo signature change.
2. **Second**: §2 (composite index) — turns the dominant tool-call cost from 22 s to <300 ms.
3. **Third**: §3 batch API + classifier reorder — gets aggregate gate green (p99 < 60 s).
4. **Cleanup**: §5 harness `thread_id` and §4 tool-description tightening are small, no-deploy-needed, and remove false-positive noise from the chat-eval gate.
5. **Background**: §6 worker tuning improves SLOs but doesn't gate ITER-8.

A natural PLAN-0095 wave: **W1 = §1 + §2 (market-data data fixes)**, **W2 = §3 batch API + classifier reorder**, **W3 = §4 + §5 (tooling + eval hygiene)**, **W4 = §6 worker tuning**.

---

*Report compiled from 6 parallel Explore-subagent investigations dispatched during ITER-9 multi-issue triage. All file:line citations were verified by each agent against the live tree on `feat/plan-0093-remediation` at HEAD `461d030b`.*
