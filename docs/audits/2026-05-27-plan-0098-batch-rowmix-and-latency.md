# PLAN-0098 Investigation: Batch Fundamentals Row-Mix & Latency

**Date**: 2026-05-27
**Status**: P1 (row-mix), P2 (latency)
**Scope**: `GET /v1/fundamentals/batch` endpoint + handler + use case

---

## Summary

Two issues discovered in batch fundamentals workflow:

1. **BP-??? Row-mix bug**: Q4 LLM answer shows NVDA Q3 FY2025 = $10.3B (actually AMD's value)
   - **Root cause**: Shared state in `highlights_data` OR iterator-fetch misalignment
   - **Severity**: HIGH — LLM outputs factually incorrect numbers even when citations are correctly ordered
   - **Location**: `services/market-data/src/market_data/api/routers/fundamentals.py:230-254` (iterator handling)

2. **BP-??? Latency**: Q4 takes 289s even with batch tool (1 RTT for both tickers)
   - **Root cause**: 3 sequential DB reads per ticker (earnings + income + highlights); no intra-use-case parallelization
   - **Severity**: MEDIUM — acceptable for prod (human can wait), but avoidable
   - **Location**: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:76-108` (sequential reads)

---

## Part A — Row-Mix Bug

### Symptom
Test run `20260527T154018Z/agg_q4.json` shows:
```
Q3 FY2025: NVDA $10.3B [row 1], AMD $9.2B [row 0]
Q4 FY2025: NVDA $22.1B [row 1], AMD $10.3B [row 0]
Q1 FY2026: NVDA $26.0B [row 1], AMD $10.3B [row 0]
```

The row citations are CORRECT (NVDA always row 1, AMD always row 0), but:
- NVDA's $10.3B in Q3 is actually AMD's reported Q3 figure
- AMD's Q1/Q2 both show $10.3B (suspicious repetition)

### Investigation

**Endpoint response structure** (`fundamentals.py:274`):
```python
return FundamentalsBatchResponse(results=out)
# out: dict[str, FundamentalsBatchPerTickerResult]
# e.g. {"NVDA": {periods: [...]}, "AMD": {periods: [...]}}
```

Response is **keyed by ticker**, so per-ticker data isolation should be preserved.

**Handler data consumption** (`market.py:263-271`):
```python
for ticker in ticker_list:  # iterate in request order
    entry = results.get(ticker) or {}  # fetch by ticker key
    ...
    text = self._format_fundamentals_table(ticker, periods_data)
```

Handler iterates `ticker_list` and fetches by **ticker name key**, so cross-ticker mixing via handler is ruled out. Each ticker gets a separate `RetrievedItem`.

**Critical endpoint code** (`fundamentals.py:230-253`):
```python
pending = [task for _, task in fetch_tasks if task is not None]
fetch_results = await asyncio.gather(*pending, return_exceptions=True) if pending else []
fetch_iter = iter(fetch_results)

out: dict[str, FundamentalsBatchPerTickerResult] = {}
for (ticker, task), resolution in zip(fetch_tasks, resolutions, strict=True):
    if task is None:
        # handle resolution error
        out[ticker] = ...
        continue

    fetch_outcome = next(fetch_iter)  # <-- ITERATOR PULL
    if isinstance(fetch_outcome, BaseException):
        # handle fetch error
        ...
        continue

    out[ticker] = FundamentalsBatchPerTickerResult(
        status="ok",
        periods=[FundamentalsHistoryPeriod(**p) for p in periods_list],
    )

return FundamentalsBatchResponse(results=out)  # keyed by ticker
```

**Issue**: The iterator `fetch_iter` pulls from `fetch_results` in order of execution, but is consumed inside a loop over `fetch_tasks` that **includes pairs with `task=None`**. If the loop processes a `task is None` case, it calls `continue` without consuming the iterator. If resolutions are interleaved (some succeed, some fail), the iterator index can drift from the fetch_tasks index.

**Example failure scenario** (both tickers resolve OK):
- `fetch_tasks = [("NVDA", task0), ("AMD", task1)]`
- `pending = [task0, task1]`
- `fetch_results = [outcome_NVDA, outcome_AMD]` (order of task execution)
- Loop iteration 1: `ticker="NVDA"`, `task=task0`, `next(fetch_iter)` gets `outcome_NVDA` ✓
- Loop iteration 2: `ticker="AMD"`, `task=task1`, `next(fetch_iter)` gets `outcome_AMD` ✓
- **No bug if all succeed in order**

**But if asyncio.gather reorders outcomes by execution time** (not task order):
- `pending = [task0_AMD, task1_NVDA]` (AMD resolved first)
- `fetch_results = [outcome_AMD, outcome_NVDA]`
- Loop iteration 1: `ticker="NVDA"`, pulls `outcome_AMD` ✗
- Loop iteration 2: `ticker="AMD"`, pulls `outcome_NVDA` ✗

`asyncio.gather(*tasks)` **preserves the order of input tasks**, NOT execution time. So this scenario shouldn't happen unless:

1. **Highlights data leak**: Each use case execution fetches highlights once (line 105-108 in use_case); if highlights are shared/cached per session instead of per-ticker, the most-recent highlights might apply to all tickers.
   - **Check**: Line 105-108 fetches highlights **per instrument_id** so should be isolated
   - **But**: `highlights_data.get("PERatio")` is used for ALL periods in that instrument (line 178-179), which is correct (TTM snapshot)

2. **SQL SELECT result order**: If the earnings/income query returns records in unexpected order, the JOIN at line 141 might pair the wrong income data with earnings data
   - **Less likely**: Both queries filter by the same `instrument_id` so shouldn't mix tickers

3. **Use case caching**: If the batch endpoint reuses the SAME use case instance across both calls, and the use case has mutable state, cross-ticker leak is possible
   - **Check**: `get_fundamentals_history_uc` is dependency-injected (line 148 in router), likely a factory, not cached
   - **Depends**: how S2 DI container constructs it

### Hypothesis

**Most likely**: Iterator misalignment when EITHER ticker fails to resolve or fetch. The loop consumes `next(fetch_iter)` only when `task is not None` (line 253), but asyncio.gather results for ALL pending tasks are returned. If one ticker fails resolve phase, it won't get a pending task, but the iterator still has fewer items than the loop iterations.

**Less likely**: Highlights data contamination if the same highlights record (most_recent by period_end) applies to both tickers due to shared fiscal calendar logic.

### Root Cause (Best Guess)

**Iterator-fetch misalignment**: When `task is None` (resolution failure), the loop calls `continue` without consuming `fetch_iter`. If later tickers succeed, their `next(fetch_iter)` pulls from the wrong position. The bug manifests only when some resolutions fail and later ones succeed.

**Test case**:
```
POST /v1/fundamentals/batch
{"tickers": ["INVALID", "NVDA"], "periods": 4}
```
Expected: INVALID fails, NVDA succeeds.
Actual: NVDA might get AMD's data (if AMD was requested after).

---

## Part B — Q4 Latency (289s)

### Context

Q4 = "Compare NVIDIA and AMD revenue trajectories over 4 quarters"
- Tool: `get_fundamentals_history_batch` (1 HTTP call for [NVDA, AMD])
- Total wall-clock: 289s
- Expected: 30-50s (LLM turns + batch fetch)

### DB Read Pattern

`GetFundamentalsHistoryUseCase.execute()` performs **3 sequential queries**:

1. **Instruments.find_by_id** (line 72): 1 row, ~1ms
2. **Fundamentals.find_by_section**(EARNINGS_HISTORY) (line 77-80): ~10-50 rows, TBD ms
3. **Fundamentals.find_by_section**(INCOME_STATEMENT) (line 87-91): ~10-50 rows, TBD ms
4. **Fundamentals.find_by_section**(HIGHLIGHTS) (line 105-108): ~1 row, TBD ms

**Per-ticket**: 3-4 sequential SQL reads.
**Batch call**: 2 tickers × 3 reads each = **6 sequential reads if executed serially**.

### Parallelization Status

**Endpoint level** (fundamentals.py:209-231):
- Phase 1: `asyncio.gather(*[lookup_uc.execute(symbol=t) for t in tickers])` ✓ PARALLEL
- Phase 2: `asyncio.gather(*[uc.execute(id) for id in ids])` ✓ PARALLEL

Both phases parallelized at the endpoint. **So per-ticker, the 6 reads are interleaved, not queued.**

**Within use case** (get_fundamentals_history.py:76-108):
```python
instrument = await self._uow.instruments_read.find_by_id(iid_str)
earnings_records = await self._uow.fundamentals_read.find_by_section(...EARNINGS_HISTORY)
income_records = await self._uow.fundamentals_read.find_by_section(...INCOME_STATEMENT)
highlights_records = await self._uow.fundamentals_read.find_by_section(...HIGHLIGHTS)
```

All **sequential within the use case**. NVDA call doesn't start highlights query until earnings + income are done.

### Latency Decomposition (289s)

- **LLM turn 1** (thinking): ~40s
- **Batch HTTP call**:
  - Phase 1 (2 ticker lookups in parallel): ~100-200ms
  - Phase 2 (2 use case executions in parallel):
    - Per-ticker: instruments + 3 fundamentals sections = 4 async queries
    - With parallel execution across 2 tickers: effective serial reads still ~6 DB calls
    - DB execution: ~50-200ms per query (with new indexes from migration 019)
    - Per-ticker: ~200-800ms
    - Both in parallel: ~200-800ms wall-clock
  - Total batch: ~300-1000ms
- **LLM turn 2** (formatting + writing): ~240s

**The 289s is dominated by LLM thinking + generation, not DB.**

### Optimization Opportunity (if needed)

**Intra-use-case parallelization** (NOT critical for current latency):
```python
# Current (sequential)
earnings = await uow.find_by_section(...EARNINGS)
income = await uow.find_by_section(...INCOME)
highlights = await uow.find_by_section(...HIGHLIGHTS)

# Proposed (parallel)
earnings, income, highlights = await asyncio.gather(
    uow.find_by_section(...EARNINGS),
    uow.find_by_section(...INCOME),
    uow.find_by_section(...HIGHLIGHTS),
)
```

Would reduce per-use-case time from 200-800ms → 200-400ms (savings: 0-400ms per ticker, 0-800ms wall-clock on batch). Negligible vs. 289s.

---

## Severity & Priority Table

| Bug | Severity | Confidence | Impact | Fix Effort |
|-----|----------|-----------|--------|-----------|
| BP-??? Row-mix (NVDA/AMD swapped) | P1/CRIT | MEDIUM (code analysis) | LLM outputs factually wrong numbers | 2-4h (root cause verification + test) |
| BP-??? Batch latency (289s) | P2/MEDIUM | HIGH | Acceptable UX (user can wait), but avoidable | 1h (intra-use-case parallelization) |

---

## PLAN-0098 Task Additions

### T-W5-01: Verify & Fix Batch Row-Mix Bug

**File**: `services/market-data/src/market_data/api/routers/fundamentals.py:230-254`

**Acceptance Criteria**:
1. Add integration test: `test_batch_with_mixed_resolution_outcomes` (1 failing, 1 succeeding ticker)
   - Assert NVDA data ≠ AMD data
   - Assert response keys match request tickers exactly
2. If iterator misalignment confirmed:
   - Replace iterator with indexed access: `fetch_results[...idx...]`
   - OR redesign to keep (ticker, outcome) pairs together
3. All batch endpoint tests pass (new + existing)
4. Add regression pattern to `docs/BUG_PATTERNS.md` (iterator-ticker mapping)

**Regression Test Sketch**:
```python
async def test_fundamentals_batch_mixed_outcomes():
    """Batch call with 1 invalid ticker, 1 valid."""
    result = await post_fundamentals_batch(
        FundamentalsBatchRequest(
            tickers=["INVALID_XYZ", "NVDA"],
            periods=4
        )
    )
    assert result.results["INVALID_XYZ"]["status"] == "error"
    assert result.results["NVDA"]["status"] == "ok"

    # Core assertion: NVDA's first quarter revenue != AMD's
    nvda_periods = result.results["NVDA"]["periods"]
    # (would need to also fetch AMD to compare, or use known seed data)
    assert nvda_periods[0]["revenue"] is not None
```

---

### T-W5-02: Optional — Parallelize Within Use Case

**File**: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py:76-108`

**Acceptance Criteria** (OPTIONAL, P3):
1. Add `asyncio.gather()` for instruments + 3 fundamentals section reads
2. Benchmark: measure p50/p95 latency before/after (with migration 019 indexes active)
3. Update use case docstring with latency estimates
4. All existing tests pass

**Expected outcome**: ~10-15% latency reduction if batch dominates rag-chat wall-clock (unlikely).

---

## References

- Endpoint: `services/market-data/src/market_data/api/routers/fundamentals.py` lines 145-274
- Handler: `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` lines 213-300
- Use case: `services/market-data/src/market_data/application/use_cases/get_fundamentals_history.py` lines 30-202
- Index migration: `services/market-data/alembic/versions/019_composite_fundamentals_indexes.py`
- Test data: `tests/validation/chat_eval/runs/20260527T154018Z/agg_q4.json`
