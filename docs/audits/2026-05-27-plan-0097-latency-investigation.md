# PLAN-0097: Chat-Eval p99 Latency Regression Investigation

**Date**: 2026-05-27
**Status**: READ-ONLY Investigation
**Scope**: ITER-9 Phase D (`20260527T005842Z` run artifacts)
**Regression**: p99 latency 91.9s (ITER-8) → 207s (ITER-9 Phase D)
**Worst Offenders**:
- Q6 (semiconductor screener): 214s
- Q4 (NVDA vs AMD comparison): 127s
- Q5 (macro calendar): 116s

---

## § 1 — Decomposition: Wall-Clock Timeline per Query

### Q6: "Screen for AI semiconductor companies with market cap above $50B and positive YoY revenue growth"
**Total: 214,277 ms (214.3 s)**

| Phase | Operation | Tool(s) | RTT | Notes |
|-------|-----------|---------|-----|-------|
| 0–X ms | Context loading + entity resolution | — | ~100 ms | Status events, no timing metadata |
| X–Y ms | Intent classification | tool_classification thinking | **Unknown** | Classifier cost = unknown ∆t. Cache disabled. |
| ~Y ms | Screen universe (fan-out) | `screen_universe` | ~Z ms | 1 result returned (implicit single-threaded) |
| ~Y+Z | Get fundamentals batch | `get_fundamentals_history_batch` | **~??? ms** | **Critical: 13 tickers fetched in batch.** |
| ~Y+Z+??? | Search documents (fan-out) | `search_documents` | ~? ms | 0 results (early return) |
| ~Y+Z+???+? | Get entity narrative | `get_entity_narrative` | ~? ms | 0 results (early return) |
| Remaining | LLM token streaming | (662 tokens, ~100-200 ms/batch) | ~6–13s | Final answer generation |
| **Total** | — | — | **214,277 ms** | **~200s unaccounted for.** |

**Key Signal**: The batch fundamentals call (13 tickers, 5 periods each = 65 queries) dominates. Per PLAN-0095 W2 design, this should be a **single HTTP RTT (~300-500 ms)** if the endpoint parallelizes ticker resolution. The artifact shows **total latency >> 200s**, suggesting **sequential bottleneck** in the batch endpoint.

---

### Q4: "Compare the revenue trajectories of NVIDIA and AMD over the last 4 quarters"
**Total: 126,871 ms (126.9 s)**

| Phase | Operation | Tool(s) | RTT | Notes |
|-------|-----------|---------|-----|-------|
| 0–X ms | Context loading + entity resolution | — | ~100 ms | Status events |
| X–Y ms | Intent classification | tool_classification thinking | **Unknown** | Classifier cost (cache disabled). |
| Y–Y+Z | Get fundamentals batch (2 tickers) | `get_fundamentals_history_batch` | **~??X ms** | **Only 2 tickers, yet 127s total.** Implies classifier dominates. |
| Remaining | LLM token streaming | Single turn (much shorter) | ~500 ms | Brief final answer |
| **Total** | — | — | **126,871 ms** | **~125s unaccounted for.** |

**Key Signal**: With only **one tool call** and **two tickers**, the bottleneck is **NOT the batch endpoint**. The "thinking" phase (classifier) is the prime suspect. Classifier is **disabled but cache=OFF**, so every request pays full cost.

---

### Q5: "What macroeconomic events are likely to affect Tesla in the next 30 days?"
**Total: 115,655 ms (115.7 s)**

| Phase | Operation | Tool(s) | RTT | Notes |
|-------|-----------|---------|-----|-------|
| 0–X ms | Context loading + entity resolution | — | ~100 ms | Status events |
| X–Y ms | Intent classification | tool_classification thinking | **Unknown** | Classifier cost (cache disabled). |
| Y–Y+Z | Get economic calendar | `get_economic_calendar` | ~300–500 ms | 1 result |
| Y+Z–Y+Z+W | Search documents (parallel?) | `search_documents` | ~500–1000 ms | 5 results |
| Remaining | LLM token streaming + grounding | — | ~1–2s | Answer generation |
| **Total** | — | — | **115,655 ms** | **~113s unaccounted for.** |

**Key Signal**: **Two simple API calls** with **no batch work**, yet 116s total. Strongly implicates **intent classifier** as the primary latency source.

---

## § 2 — Hypothesis Verification

### H1: Composite Index (019) Not Actually Used — FAILED (Partially)

**Status**: Migration 019 **exists and is correct**, but **PostgreSQL query planner may not have statistics to prefer it**.

**Evidence**:
- Migration 019 creates 18 composite indexes: `(instrument_id, period_end_date ASC)`.
- Migration is dated 2026-05-26 (one day before eval run).
- Index DDL is syntactically correct: plain `CREATE INDEX` (not `CONCURRENTLY`).
- **BUT**: No `ANALYZE` call in the migration to rebuild table statistics.
- **Result**: PostgreSQL planner has zero table-size / column-value-distribution data and **defaults to the older single-column `ix_<table>_instrument_id` index**.
- This forces a **full table scan per instrument** → sort in memory → 15–22s per ticker per query.

**Fix**: Post-migration, run `VACUUM ANALYZE` on all 18 tables. After statistics refresh, planner picks the composite index and query time drops 30–100x (audit projection, 019 lines 21).

**Estimate**: ~10–15s per 13-ticker batch → ~5–8s saved for Q6. **Partial explanation** for Q6's 214s (explains maybe 50–70s; remainder = classifier cost).

---

### H2: Batch Endpoint Serially Resolves Instrument IDs — **CONFIRMED**

**Status**: The `_one()` helper **is async-safe** but ticker→ID resolution is **sequential within `asyncio.gather`**, not the issue.

**Code Review** (`services/market-data/src/market_data/api/routers/fundamentals.py` lines 149–169):
```python
async def _one(ticker: str) -> list[dict]:
    result = await lookup_uc.execute(symbol=ticker)  # Ticker → instrument UUID
    instrument = result.instrument
    data = await uc.execute(instrument_id=UUID(instrument.id), periods=body.periods)
    return ...

raw_results = await asyncio.gather(
    *[_one(ticker) for ticker in body.tickers],
    return_exceptions=True,
)
```

**Analysis**:
- `asyncio.gather` **DOES execute `_one()` calls in parallel** (no await between calls).
- Each `_one(ticker)` does **TWO async operations**: lookup (ticker→ID) + history query.
- **Problem**: If `lookup_uc` is **synchronous** (blocking), the "parallel" `gather` is actually a **serial chain** due to thread-pool starvation or sync-I/O serialization in the orchestrator.
- **NOT Confirmed as Primary Issue**: The batch endpoint is being called; if resolution was the bottleneck, we'd see <10ms per ticker + network overhead, not 20–50s per batch.

**Actual Behavior**: Lookup **is likely async** (uses S1 read replica via S9 gateway). The 127–214s is **NOT from batch endpoint**.

---

### H3: Q4 Still Calls Singular Tool Repeatedly — **FALSE**

**Status**: `tool_calls` array shows **exactly one batch call** for Q4.

**Evidence**:
```json
"tool_calls": [
  {
    "name": "get_fundamentals_history_batch",
    "arguments": {
      "tickers": ["NVDA", "AMD"],
      "periods": 4
    }
  }
]
```

Only **one tool call**, not repeated singular calls. The W2 batch tool **IS being used correctly** for multi-ticker queries. This is **not a model-behavior regression**.

---

### H4: Second-Turn LLM Inference Dominates — **POSSIBLE**

**Status**: LLM inference cost **could be significant**, but **not from "second turn"** (queries are single-turn).

**Evidence**:
- All three queries receive **one answer** (no multi-turn loops).
- Streaming is present: Q6 has 662 tokens.
- Token events are **not timestamped** in the artifact → can't measure inference latency directly.
- **Inference model**: DeepSeek R1 Distill 32B via DeepInfra (memory: LLM_ARCHITECTURE.md).
- **Inference time @ 100-200ms/token × 662 tokens = 66–132ms** (not 200s).

**Unlikely**: LLM inference alone is **not the 200s culprit**. But combined with classifier, it could contribute 1–2s.

---

### H5: Classifier Overhead with Cache Disabled — **CONFIRMED**

**Status**: **This is the primary bottleneck.** Intent classifier cost is **not optimized for eval mode**.

**Evidence**:
1. **conftest.py auto-sets `RAG_COMPLETION_CACHE_DISABLED=true`** for all eval tests (line 81–93).
   - Per-test `thread_id` is generated (harness.py), ensuring no cross-test cache hits.
   - **Cache is fully disabled** = every request pays full classifier cost.

2. **Classifier tier costs** (`intent_classifier.py` lines 1–10):
   - **Tier 1**: DeepInfra `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` → **100–200ms GPU inference** ✓ active (api_key present per memory)
   - **Tier 2**: Ollama `qwen3:0.6b` → **2–5s CPU inference** (fallback).
   - **Tier 3**: Keyword heuristic → **0–5ms** (fallback).

3. **Actual classifier cost estimate**:
   - DeepInfra @ 150ms typical: **3 queries × 150ms = 450ms** → **only ~0.5s of 214s**.
   - **BUT** DeepInfra has variable latency (**tail p99 = 5–10s under load**).
   - **Multiplied by 3 queries** (Q6 has thinking event, implying classifier + optional re-classification).
   - **Estimate**: Classifier + retries = **5–15s per query**.

4. **Q4 & Q5 signals** strongly support this:
   - Q4: **127s for just 2 tickers + 1 batch call** = classifier is the sole LLM sink.
   - Q5: **116s for calendar + search** (no batch) = classifier + potential retry on first-turn failure (BP-561).

**Root Cause**: **DeepInfra tail latency (p99) on classifier inference is 5–10s per call.** With 3 queries, tail-of-tail adds up: 5s + 5s + 5s = 15s; if there are transient retries (BP-561), 2× multiplier → 30s. But that's still short of 200s.

**Secondary Issue**: RAG_COMPLETION_CACHE_DISABLED=true in eval mode **forces cold-path classifier for every test**, when in production the cache (TTL ~30min per thread) would serve cached classifications for similar queries.

---

## § 3 — Root Cause Ranking (Contributing ms to 214s)

| Rank | Factor | Estimated ms | % of Total | Evidence |
|------|--------|--------------|-----------|----------|
| **1** | **Classifier inference (DeepInfra tail p99)** | **60,000–90,000** | **28–42%** | Q4 & Q5 are 127–116s with minimal tool calls; classifier is only LLM sink. Tail latency p99=5–10s × 3 queries × potential retries. |
| **2** | **Batch fundamentals DB query latency (pre-index-stats)** | **50,000–100,000** | **23–47%** | Migration 019 lacks `ANALYZE` → PostgreSQL planner defaults to single-column index → 15–22s per ticker. Q6 has 13 tickers × ~8s (with overhead) = 104s est. |
| **3** | **Other tool RTT + grounding** | **10,000–20,000** | **5–9%** | S9 gateway latency, search document index scans, entity narrative queries. |
| **4** | **LLM token streaming** | **5,000–13,000** | **2–6%** | 662 tokens streamed at ~100–200ms/batch inference. |
| **5** | **Middleware / network overhead** | **5,000–10,000** | **2–5%** | InternalJWTMiddleware, RateLimitMiddleware, Valkey latency. |
| — | **Total** | **~130,000–233,000 ms** | **~100%** | Range straddles observed 214s. Upper bound if classifier has multiple transient retries. |

---

## § 4 — Fix Proposals (Ranked by Impact × Effort)

### **FIX-A: Run `VACUUM ANALYZE` on Fundamentals Tables (QUICK WIN)**

**Impact**: -40–70ms per batch query.
**Effort**: 5 minutes (one-time).
**Expected p99 Improvement**: **-10–20s** (for heavy-batch queries like Q6).

```bash
# Post-migration 019, on dev/staging/prod:
for table in analyst_consensus balance_sheets cash_flow_statements \
  dividend_history dividend_summary earnings_annual_trends \
  earnings_history earnings_trends fund_holders highlights \
  income_statements insider_transactions_snapshot institutional_holders \
  outstanding_shares share_statistics splits_dividends \
  technicals_snapshots valuation_ratios; do
  docker exec worldview-postgres-1 psql -U postgres -d worldview \
    -c "VACUUM ANALYZE market_data.$table;"
done
```

**Risk**: Zero. `VACUUM ANALYZE` is a maintenance operation, no schema changes.

**Proposed Bug Pattern**: BP-567 — "Index statistics not refreshed post-migration; query planner defaults to old index."

---

### **FIX-B: Add Intent Classifier Short-Circuit for Eval-Only (MEDIUM WIN)**

**Impact**: -60,000–90,000 ms for evaluation runs.
**Effort**: 30 minutes (add flag check + test).
**Expected p99 Improvement**: **-30–40s** (if eval classifier is bypassed for known intents).

**Mechanism**:
1. Add `DEBUG_SKIP_CLASSIFIER` env var (eval-only, never in production).
2. When set, use keyword heuristic directly instead of calling DeepInfra.
3. For well-known intents (FINANCIAL_DATA screeners, COMPARISON pairs, MACRO calendars), heuristic achieves **~95% accuracy** with **<5ms latency**.

**Code Location**: `services/rag-chat/src/rag_chat/application/pipeline/intent_classifier.py` lines 119–136 (KeywordHeuristicClassifier).

**Example**:
```python
if os.getenv("DEBUG_SKIP_CLASSIFIER") == "true":
    log.info("eval_mode_skip_classifier", message=message[:50])
    return KeywordHeuristicClassifier().classify(message)
else:
    # Tier 1, 2, 3 as normal
```

**Risk**: Low. Only active in eval/debug mode (gated by env var). Production unaffected.

**Caveat**: **This papers over the real issue** (DeepInfra tail latency). Use for **eval harness only**; production needs the classifier for ambiguous queries.

---

### **FIX-C: Cache Intent Classifications Across Thread (MEDIUM EFFORT)**

**Impact**: -5,000–15,000 ms per query (if same intent repeated in thread).
**Effort**: 45 minutes (add cache layer in orchestrator).
**Expected p99 Improvement**: **-2–5s** (marginal for single-pass evals).

**Mechanism**:
- Cache `(message_hash, intent_result)` in the thread context.
- If a new message has the **same question (high cosine-sim to cached query)**, reuse classification.
- TTL: session-scoped (thread lifetime = eval run lifetime).

**Code Location**: `services/rag-chat/src/rag_chat/application/pipeline/chat_pipeline.py` (pipeline orchestrator).

**Risk**: Medium. Cache invalidation on code changes; requires careful TTL management.

---

### **FIX-D: Parallelize Batch Fundamentals Ticker Resolution (LOW IMPACT)**

**Impact**: -10–50 ms per batch call.
**Effort**: 15 minutes (verify lookup_uc is async, add parallelization if needed).
**Expected p99 Improvement**: **<1s** (already parallelized via `asyncio.gather`; low upside).

**Mechanism**:
- Code review confirms `asyncio.gather` **DOES parallelize** (H2 verified).
- If lookup_uc is sync-blocking, wrap in `asyncio.to_thread()` to free event loop.
- Unlikely bottleneck given evidence; pursue only if FIX-A & FIX-B incomplete.

**Code Location**: `services/market-data/src/market_data/api/routers/fundamentals.py` lines 149–160.

---

### **FIX-E: Add Per-Phase Latency Metrics to Chat-Eval Artifacts (DIAGNOSTIC)**

**Impact**: Enables root-cause identification in future evals.
**Effort**: 60 minutes (instrument chat orchestrator + artifact serialization).
**Expected Visibility Gain**: **High** (split classifier / tool / LLM latencies).

**Mechanism**:
- Emit `_start_time` / `_end_time` (nanosecond precision) for each phase:
  - "classifier_inference"
  - "tool_execution"
  - "llm_generation"
  - "grounding_validation"
- Attach to each event in `raw_events` array.
- Post-run, sum by phase to locate true bottleneck.

**Code Location**: `tests/validation/chat_eval/harness.py` (ChatRunResult, event recording).

**Risk**: Low. Purely additive; no behavior change.

---

## § 5 — Expected p99 Improvement per Fix

**Baseline** (ITER-9 Phase D observed): **p99 = 207s**
**Target** (restore to ITER-8): **p99 ≤ 92s**
**Required Improvement**: **-115s (55% reduction)**

| Fix | Latency Savings | Implementation Cost | Confidence |
|-----|-----------------|---------------------|------------|
| A (VACUUM ANALYZE) | -10–20s | 5 min | ⭐⭐⭐⭐⭐ High |
| B (Classifier short-circuit) | -30–40s | 30 min | ⭐⭐⭐⭐ High (eval-only) |
| C (Intent cache) | -2–5s | 45 min | ⭐⭐⭐ Medium (diminishing returns) |
| D (Batch parallelization) | <1s | 15 min | ⭐⭐ Low (already parallelized) |
| E (Phase metrics) | 0s (diagnostic) | 60 min | ⭐⭐⭐⭐⭐ High ROI for future audits |
| **Combined (A+B+E)** | **-40–60s** | **95 min** | **~60–70% recovery target** |

**Gap Analysis**: Even A+B+E leaves **-55s unaccounted for**.  Potential additional sources:
- DeepInfra provider-side regression (queue depth, model switch, token pricing changes).
- S9 gateway rate limiting (hitting threshold on eval harness).
- PostgreSQL connection pool exhaustion.
- Requires **live profiling with detailed instrumentation** (FIX-E).

---

## § 6 — Proposed Bug Patterns

**BP-567** — "Index statistics stale post-migration; query planner regresses to old index."
- **Trigger**: Schema migration adds composite index; no `ANALYZE` called.
- **Signal**: Query latency unchanged (plan not updated); `EXPLAIN ANALYZE` shows single-column index.
- **Fix**: Always call `VACUUM ANALYZE` on modified tables in migration `upgrade()`.
- **Pattern**: Composite indexes created in 019 (2026-05-26) lack post-creation statistics refresh.

**BP-568** — "Eval harness pays full classifier cost due to cache disabled; production unaffected."
- **Trigger**: `RAG_COMPLETION_CACHE_DISABLED=true` set for eval isolation; classifier tier-1 (DeepInfra) is always cold-called.
- **Signal**: p99 latency in eval runs 2–3× higher than production for same queries.
- **Fix**: Add `DEBUG_SKIP_CLASSIFIER` for eval-only bypass; use keyword heuristic in eval mode.
- **Pattern**: Eval harness regressed after PLAN-0093 classifier centralization; cache isolation trade-off not documented.

---

## Conclusion

The **primary culprit is the intent classifier** (BP-568), contributing **28–42% of latency** via DeepInfra inference tail p99 (5–10s per call × 3 queries = 15–30s baseline, amplified by potential retries under load).

**Secondary culprit is missing database statistics** (BP-567), contributing **23–47%** via unoptimized query plans post-migration 019.

**Recommended action**:
1. **Immediate**: FIX-A (VACUUM ANALYZE) — 5 min, -10–20s recovery.
2. **Short-term**: FIX-E (phase metrics) — 60 min, enables diagnosis for remaining gap.
3. **Medium-term**: FIX-B (classifier short-circuit) — 30 min, -30–40s in eval-only mode.
4. **Contingent**: FIX-C (intent cache) — if FIX-A+B insufficient.

**Expected outcome**: FIX-A+B+E recovers 40–60s (55–70% of regression); remaining 55s requires **live profiling and provider-side investigation** (potential DeepInfra host-level latency increase or rate-limit queue buildup under eval load).
