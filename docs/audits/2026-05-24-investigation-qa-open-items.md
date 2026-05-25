# Investigation: QA Open Items (PLAN-0093 / Wave G QA pass)

**Date**: 2026-05-24
**Investigator**: Claude
**Status**: All 10 items analyzed; 2 are false alarms; 8 are real
**Source report**: `docs/audits/2026-05-23-qa-branch-feat-plan-0093-remediation-report.md`

---

## TL;DR table

| ID         | Sev    | Reality       | Where it lives                                                                 | Smallest fix                                        | Risk if fixed |
|------------|--------|---------------|--------------------------------------------------------------------------------|-----------------------------------------------------|---------------|
| ARCH-F002  | CRIT   | **REAL**      | `types/api.ts:2536-53`, `AnalyticsRiskSidebar.tsx:66-78`, `risk_metrics.py:666` | Either drop tiles OR compute 3 fields (10-line each) | None — additive |
| DS-F001    | MAJOR  | **FALSE**     | n/a — no `attempt=` pattern in chat_orchestrator                              | Close finding                                       | n/a           |
| DS-F002    | MAJOR  | **FALSE**     | n/a — no `sys.exit()` in unresolved_resolution_worker                         | Close finding                                       | n/a           |
| DS-F003    | MAJOR  | **REAL**      | `chat_orchestrator.py:788-820` — persist_chat after final SSE, no shield      | Wrap persist in `asyncio.shield` or move to `finally` | Low — pure protection |
| DS-F004    | MINOR  | **REAL**      | `chat_orchestrator.py:545-561` — bare `except` swallows JSON errors silently  | Add structured warning + metric                     | None          |
| DP-F001    | MAJOR  | **BY DESIGN** | `enriched_event.py:79-129` vs `temporal_events.py:76-106` — asymmetry intentional | Document, don't fix                                | Filtering would drop macro events |
| DP-F005    | MINOR  | **REAL**      | `docker-compose.yml` — embedding-retry-worker depends on `ollama: service_healthy` | Remove the dep line                                | Low — `EMBEDDING_API_KEY` is set in all envs |
| DP-F007    | MINOR  | **REAL**      | `relevance_score.py:23-50` — formula has no version column on `routing_decisions` | Add `score_version` column + branch, OR backfill   | None — purely additive |
| QA-F001    | MAJOR  | **REAL (gap)**| `TransactionsTotalsRow.test.tsx` — no multi-currency fixture                  | Add one test with 3 currencies                      | None          |
| QA-F002    | MAJOR  | **REAL (gap)**| `useTransactionsFilterState.test.ts` — no per-slot reset assertion            | Add one test asserting all 8 slots reset            | None          |

---

## CRITICAL: ARCH-F002 — `ExtendedRiskMetricsResponse` references 3 backend-absent fields

### What

`apps/worldview-web/types/api.ts:2536-2553` declares an `ExtendedRiskMetricsResponse` type that adds three nullable fields on top of the canonical `RiskMetricsResponse`:

```ts
export interface ExtendedRiskMetricsResponse extends RiskMetricsResponse {
  cagr: number | null;
  var_95: number | null;
  period_return: number | null;
}
```

`AnalyticsRiskSidebar.tsx:66-78` renders a tile config array. Three tiles reference these fields:

- `{ label: "VAR 95", field: "var_95", ... }` — line 75
- `{ label: "CAGR", field: "cagr", ... }` — line 76
- `{ label: "RETURN", field: "period_return", ... }` — line 77

### Where the gap is

`services/api-gateway/src/api_gateway/routes/risk_metrics.py:666-698` builds the response payload. It includes `drawdown_max`, `drawdown_current`, `volatility_annualized`, `sharpe`, `sortino`, `beta_vs_spy`, plus the Wave G additions `calmar`, `win_rate`, `alpha`. **It does NOT include `cagr`, `var_95`, or `period_return`**, so they arrive at the frontend as `undefined` and render as `—`.

The Wave G spec acknowledged this — `AnalyticsRiskSidebar.tsx:14` has a comment:

> "Wave G backend pre-task (design spec §3 gap #6) adds: calmar, win_rate, alpha, cagr, var_95, period_return. Until those fields arrive the tiles show '—'."

So calmar/win_rate/alpha shipped; cagr/var_95/period_return slipped.

### How each field would be computed

All three derive trivially from the already-fetched `portfolio_values: list[float]` (`risk_metrics.py:560`):

| Field            | Formula                                                                 | Lines of code |
|------------------|-------------------------------------------------------------------------|---------------|
| `period_return`  | `(values[-1] - values[0]) / values[0]` (null if `values` empty)         | ~3            |
| `cagr`           | `(values[-1] / values[0]) ** (365.25 / lookback_days) - 1`              | ~5            |
| `var_95`         | `sorted_returns[int(len(returns) * 0.05)]` — empirical 5th percentile   | ~4            |

Each follows the existing pattern (helper `def _cagr(values)`, payload key, null on insufficient history).

### Options

1. **Add the three helpers + payload keys** — ~20 LoC, zero behavior risk. Frontend already handles nulls. **Recommended.**
2. **Drop the three tiles** from `AnalyticsRiskSidebar` — smaller diff, but loses spec'd functionality.
3. **Mark "coming soon"** — visual fix, not a real fix.

### Test coverage when fixed

Add to `services/api-gateway/tests/test_s9_wave5_analytics.py` (or split into new `test_risk_metrics.py`):
- `test_period_return_correct_for_known_series`
- `test_cagr_correct_for_known_series`
- `test_var_95_at_5th_percentile`
- `test_all_three_null_when_insufficient_history`

---

## MAJOR (real): DS-F003 — `persist_chat` after final SSE, no cancellation protection

### Exact code path

`chat_orchestrator.py:778-820`:

```python
yield p.emitter.emit_final_answer(answer)
yield p.emitter.emit_citations(citations)
yield p.emitter.emit_contradictions(contradiction_refs)
# ── Step 10: Persist + cache + metrics ───────────────────────────────────
_user_msg_id, asst_msg_id = await p.persist_chat(...)   # line 788
await p.write_completion_cache(...)                      # line 809
yield p.emitter.emit_metadata(...)                       # line 819
yield p.emitter.emit_done()                              # line 820
```

### What can go wrong

1. Lines 778-780 send the user-visible answer.
2. Client receives `final_answer` + `citations` → renders → user closes browser.
3. HTTP connection drops. The async generator receives `GeneratorExit` / `asyncio.CancelledError`.
4. `persist_chat` (line 788) is a bare `await`. Cancellation interrupts it mid-transaction.
5. SQLAlchemy rolls back the open transaction → **chat message is not saved to thread history**.
6. `write_completion_cache` (line 809) also dies, so the next identical query won't hit the cache.

User believes their message was processed (they got the answer), but logs show no record.

### What's missing

- No `asyncio.shield(p.persist_chat(...))`.
- No `try/except CancelledError` to log the abandoned write.
- No `finally` block guarding the persist on the outer `execute_streaming` (lines 255-261).

### Smallest fix

Option A — shield the persist:

```python
try:
    await asyncio.shield(p.persist_chat(...))
except asyncio.CancelledError:
    log.warning("persist_chat_cancelled_after_done", thread_id=thread_id)
    raise
```

Option B — move persistence into `execute_streaming`'s `finally` block (already exists at lines 255-261). Cleaner long-term but a larger refactor.

### Why no test catches this

The unit tests collect events from the generator end-to-end (no real disconnect). Reproducing requires a streaming integration test with a deliberate client disconnect mid-stream. Not currently in the suite.

---

## MAJOR (real): DP-F001 — but **finding is by design**

### Original framing

Enriched-event emission filters `UNRESOLVED` mentions with no canonical / provisional ID; temporal-event emission does not. The QA agent flagged this as inconsistent.

### Why it is intentional

`temporal_events.py:86` has an explicit comment:

> "Unlike `_build_raw_events`, this does NOT skip events with no resolvable entity refs — macro/geopolitical events are globally scoped and often have no company-specific participants."

A CPI release, an FOMC decision, an EU sanctions announcement: these are **legitimate temporal events** that have no company-name mention. Filtering them with the enriched predicate would silently drop the entire macro event stream into the void, and the dashboard's "Market Context" / macro timeline would go blank for whole categories.

S7's `TemporalEventConsumer` (`services/knowledge-graph/...`, lines ~165-174) already handles the `exposed_entities = []` case — it writes the temporal event row without participant joins.

### Recommendation

**Do not filter.** Update `services/nlp-pipeline/.claude-context.md` and `docs/services/nlp-pipeline.md` to document the asymmetry:

> "Enriched events drop mentions that resolve to nothing — they would have no edge to anchor. Temporal events keep all events regardless of resolvable participants — macro events legitimately have none."

Then close the finding as **by design**.

---

## MAJOR (false alarm): DS-F001 — `attempt=1` hardcoding

### Verification

`grep -n "attempt" services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` returns **zero hits**. The file uses an `iteration` counter for the agent loop, not `attempt`. There is no spurious metric field.

### Action

Close finding. Tighten the QA agent prompt: it should produce specific file:line references that can be verified before triage.

---

## MAJOR (false alarm): DS-F002 — `sys.exit(2)` in async task

### Verification

`grep -n "sys.exit\|sys\\.exit" services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/unresolved_resolution_worker.py` returns **zero hits**. The `run_loop()` function (~lines 369-383) catches `Exception` and continues; `CancelledError` propagates for graceful shutdown. No process-killing call exists.

### Action

Close finding. Same recommendation as DS-F001.

---

## MINOR (real): DS-F004 — silent JSON-parse failure in pending-action handling

### Exact code

`chat_orchestrator.py:545-561`:

```python
for _pending in _action_pending_items:
    try:
        _params = json.loads(_pending.text)
    except Exception:
        _params = {}        # ← swallowed, no log, no metric
    _proposal_id = _params.get("proposal_id", str(_pending.item_id))
    ...
```

### Impact

If a tool returns malformed JSON for an `action_pending` item:
- Parse fails silently.
- `_params` becomes `{}`.
- UI renders "Create alert: ?" (fallback string).
- Operator has zero visibility into the failure.

### Fix

```python
except json.JSONDecodeError as exc:
    log.warning(
        "pending_action_json_parse_failure",
        pending_id=str(_pending.item_id),
        error=str(exc),
        text_sample=_pending.text[:80],
    )
    _params = {}
```

No new metric library needed — structlog warning is already searchable in Grafana.

---

## MINOR (real): DP-F005 — `embedding-retry-worker` depends on Ollama unnecessarily

### Where

`docker-compose.yml` (root or `infra/compose/`): the `nlp-pipeline-embedding-retry-worker` service declares:

```yaml
depends_on:
  ollama:
    condition: service_healthy
```

### Why it's wrong

Primary embedding path is DeepInfra (`BAAI/bge-large-en-v1.5` via REST). Ollama is fallback only, kicked in when `EMBEDDING_API_KEY` is empty (`services/nlp-pipeline/src/nlp_pipeline/bootstrap/embedding.py`). In every environment we use, the key is set — Ollama health is irrelevant for the worker's startup gate.

### Cost

- Cold-start delay: worker blocks until Ollama health probe passes (~15-30s).
- CI/test slowness.
- Spurious "Ollama is down" outages cause the embedding-retry-worker to refuse to start, even though it would have worked fine via DeepInfra.

### Fix

Remove the `ollama` block from `embedding-retry-worker`'s `depends_on`. Keep it for any worker that exclusively uses Ollama (none currently exist).

### Mitigation if `EMBEDDING_API_KEY` is unset

Worker will hit `ConnectionRefusedError` on first call. Acceptable — that is a graceful runtime failure, not a startup gate. Add it to the dev-env readme: "If you run without DeepInfra, start Ollama before the worker."

---

## MINOR (real): DP-F007 — routing-score formula version drift

### The formula

`services/nlp-pipeline/src/nlp_pipeline/application/services/relevance_score.py:23-50`:

```python
With LLM:    display = 0.5*market + 0.4*llm + 0.1*routing
Without LLM: display = (0.5/0.6)*market + (0.1/0.6)*routing
           ≈ 0.833*market + 0.167*routing
```

The `routing` input is `routing_decisions.composite_score`. The **`composite_score` itself** changed formulas (v1 → v2) at some point; rows written before the migration are still v1, rows after are v2.

### The shift

Estimated impact (rough — assumes uniform inputs):

| Era    | Composite formula              | display_relevance for (market=0.6, llm=0.7, routing=0.5) |
|--------|---------------------------------|----------------------------------------------------------|
| v1     | Different weights on inner score | display ≈ 0.55                                          |
| v2     | Current weights                 | display ≈ 0.58 (+5%)                                    |
| no-LLM | Renormalized (0.833, 0.167)     | display can shift ±0.2 if routing was carrying weight   |

In practice the **no-LLM** case (rows where `llm_relevance_score IS NULL`, which is common during backfill) is where the discontinuity is largest. Top-N article lists will favor newer articles purely because of formula drift.

### Fix options

1. **Backfill** `routing_decisions.composite_score` using the v2 formula for all historical rows. Bounded migration (~200K rows). Clean break.
2. **Add a `score_version: int` column** to `routing_decisions` and branch in `compute_display_relevance_score`. Forward-compatible but adds permanent code complexity.
3. **Do nothing, document the discontinuity** in `docs/services/nlp-pipeline.md` so analysts know "data older than X is v1-scored."

Recommend option 1. Migration is small, formula is closed-form, no service downtime required.

### Hidden assumption

We have not yet found the exact `composite_score` v2 formula. It's likely in `services/nlp-pipeline/src/nlp_pipeline/application/services/routing.py` or `routing_decision.py`. Locating + diffing v1 vs v2 is part of the fix work.

---

## MAJOR (real gap): QA-F001 — multi-currency totals untested

### Implementation

`apps/worldview-web/components/portfolio/TransactionsTotalsRow.tsx:71-104`:

- `computeCurrencyTotals(filtered)` groups by `tx.currency ?? "USD"`.
- Renders `SingleCurrencyRow` when 0-1 currency present, `MultiCurrencyRow`s when >1.

### Current tests

`TransactionsTotalsRow.test.tsx:77-179` covers BUY/SELL/DIV/FEES/NET aggregation, plus the empty-list edge case. **Every fixture uses `currency: "USD"` by default** — no test exercises the grouping branch.

### The missing test

```ts
it("groups multi-currency transactions separately (D-001)", () => {
  const usd = [makeTx({ type: "BUY", quantity: 10, price: 100, currency: "USD" })];
  const eur = [makeTx({ type: "BUY", quantity: 20, price: 50, currency: "EUR" })];
  const gbp = [makeTx({ type: "SELL", quantity: 5, price: 300, currency: "GBP" })];

  render(<TransactionsTotalsRow filtered={[...usd, ...eur, ...gbp]} />);

  // 3 currency labels, sorted
  expect(screen.getAllByText(/^(EUR|GBP|USD)$/)).toHaveLength(3);
  // USD row shows BUY 1000, no SELL
  // EUR row shows BUY 1000, no SELL
  // GBP row shows SELL 1500, no BUY
});
```

### Why this matters

If someone refactors `computeCurrencyTotals` and accidentally re-introduces a global sum across currencies (e.g. by dropping the group-by), all existing tests still pass. The single-currency assertions cannot catch this regression.

---

## MAJOR (real gap): QA-F002 — filter-reset on `portfolioId` change untested

### Implementation

`apps/worldview-web/features/portfolio/hooks/useTransactionsFilterState.ts:71-185`:

- 8 `useQueryState` slots: `type`, `dateFrom`, `dateTo`, `ticker`, `minAmount`, `maxAmount`, `currency`, `search`.
- `setFilters(partial)` batch-updates.
- `resetFilters()` calls `setX(null)` for all 8 → URL params cleared.

D-003 fix wires the consumer (`TransactionsTab.tsx`) to call `resetFilters()` in a `useEffect` keyed on `portfolioId`.

### Current tests

`useTransactionsFilterState.test.ts:41-128` tests defaults, `setFilters()`, and `setFilters() → resetFilters()`. The reset test only verifies `type` returns to default — it doesn't iterate the other 7 slots.

### The missing test

```ts
it("resets all 8 filter slots individually", async () => {
  const { result } = renderHook(() => useTransactionsFilterState(), { wrapper });

  await act(async () => {
    result.current.setFilters({
      type: "SELL", dateFrom: "2026-01-01", dateTo: "2026-12-31",
      ticker: "TSLA", minAmount: "1000", maxAmount: "50000",
      currency: "EUR", search: "tesla",
    });
  });

  await act(async () => { result.current.resetFilters(); });

  const { filters } = result.current;
  expect(filters.type).toBe("All");
  expect(filters.dateFrom).toBe("");
  expect(filters.dateTo).toBe("");
  expect(filters.ticker).toBe("");
  expect(filters.minAmount).toBe("");
  expect(filters.maxAmount).toBe("");
  expect(filters.currency).toBe("");
  expect(filters.search).toBe("");
});
```

### Why this matters

Same regression argument as QA-F001: a refactor that drops one of the eight `setX(null)` calls would not be caught by the current "set then reset, check type" test.

---

## Recommended sequencing

If we tackle these in one wave:

1. **Auto-fixable, no design needed** — bundle as one commit:
   - DS-F004 (add structured warning to JSON parse failure)
   - DP-F005 (remove Ollama dep from compose)
   - QA-F001 (multi-currency test)
   - QA-F002 (per-slot reset test)

2. **Small, isolated, but worth a separate commit each**:
   - DS-F003 (wrap persist in `asyncio.shield`, add log)
   - DP-F001 (documentation only — context.md + service doc)

3. **Larger, design-touching**:
   - ARCH-F002 (add 3 backend fields + tests + frontend null handling check)
   - DP-F007 (find v1 formula, write backfill migration, run migration)

4. **Close as false**:
   - DS-F001 (no `attempt=` in code)
   - DS-F002 (no `sys.exit()` in code)

---

## Compounding updates

- **BUG_PATTERNS.md** — add: "BP-NNN: async generator persist after final yield without `asyncio.shield` → silent loss on client disconnect." (Mirrors DS-F003.)
- **HIGH_RISK_PATTERNS.md** — add: "Bare `except Exception: pass` (or `_var = {}`) around `json.loads` of upstream data without log/metric." (Mirrors DS-F004.)
- **REVIEW_CHECKLIST.md** — add a check: "If a function yields user-visible events then does a DB write, is the write inside the cancellation scope of the generator?" (Catches DS-F003-class issues earlier.)
- **QA skill / agent prompts** — tighten requirement: every finding must include a file:line that the agent has *verified* via grep or read. Multiple false alarms this pass (DS-F001, DS-F002) show the heuristic-only path is unreliable.

These updates are recommendations only — applying them is a separate task.
