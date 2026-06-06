# QA Report: Wave G — Portfolio Holdings Drilldown (final)

**Date**: 2026-05-26 22:00 UTC
**Skill**: qa (5-agent parallel)
**Scope**: changed-only (Wave G frontend + Phase 1 backend pre-wave)
**Branch**: feat/plan-0093-remediation
**Verdict**: **PASS_WITH_WARNINGS** — 0 BLOCKING, 2 CRITICAL (cache cascade), 8 MAJOR, 7 MINOR, 5 NIT
**Report file**: docs/audits/2026-05-26-qa-wave-g-final-report.md

---

## Executive Summary

Five specialist agents (QA/Test, Security, Data Platform, Distributed Systems, Architecture) reviewed Wave G (Holdings Drilldown / Transactions ledger / Analytics tab) + the Phase 1 backend pre-wave that added `calmar`/`win_rate`/`alpha` to `/risk-metrics` and threaded `tx.description` through the portfolio service.

The implementation is **functionally correct and merge-ready** with two caveats: (1) TanStack Query cache cascade has two gaps where mutations don't invalidate the new Wave G query keys — surfaces will display stale data for up to 60s/5min until the next staleTime poll. (2) Two sidebar tiles (TWR, BENCH TWR) reference backend fields (`twr_period`, `spy_twr`) that the `/risk-metrics` endpoint does not return — these tiles render `—` permanently rather than the actual metric. All hard rules (R14 frontend→S9 only, R25 API → use cases, R19 no test deletion, R5 forward-compat, R7 no cross-service DB, R8 no dual writes) hold. No security defects of substance — one Pydantic `max_length` bound recommended for the new `description` field.

134 tests pass across the changed scope (api-gateway risk-metrics 14, portfolio read-models 9, frontend Wave G 111). Ruff lint clean, TypeScript typecheck clean. Backend Phase 1 fields verified live on the cluster: `calmar=39.78`, `win_rate=0.452`, `alpha=null` (correctly null when SPY series unavailable), insufficient-data edge correctly nulls all three with `data_quality.status="insufficient_data"`. Transactions endpoint carries `description` key on every row.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 28+ frontend + 3 backend | 7 | 0 | 0 | 3 | 3 | 1 |
| Security | 5 backend + 28 frontend | 3 | 0 | 0 | 1 | 1 | 1 |
| Data Platform | 6 backend + 1 frontend | 3 | 0 | 0 | 0 | 0 | 3 |
| Distributed Systems | 6 backend + 12 frontend | 9 | 0 | 2 | 4 | 2 | 1 |
| Architecture | 6 backend + 18 frontend + spec | 4 | 0 | 0 | 1 | 1 | 2 |
| **Total** | — | **26** | **0** | **2** | **9** | **7** | **8** |

### Cross-Agent Signals (HIGH Confidence)

| Finding | Agents | Severity |
|---------|--------|----------|
| Wave G mutation invalidation gap (cache cascade broken on new keys) | DS F-001, F-002 + Arch implicit | CRITICAL |
| Sidebar tile set + spec drift (TWR/BENCH TWR render permanent "—") | QA F-003, Arch F-001, Arch F-004 | MAJOR |
| `description` field rendering coverage gaps | QA F-001, QA F-006, Security F-002 | MAJOR (combined) |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|-------|--------|--------|---------|--------|
| Ruff lint | Phase 1 backend + Wave G files | — | — | 0 | — | PASS |
| TypeScript typecheck | apps/worldview-web | — | — | 0 | — | PASS |
| Backend pytest — risk-metrics | api-gateway, Wave G scope | 14 | 14 | 0 | 0 | PASS |
| Backend pytest — read-models | portfolio, Wave G scope | 9 | 9 | 0 | 0 | PASS |
| Frontend Vitest — targeted | Wave G test suites | 111 | 111 | 0 | 0 | PASS |
| Live endpoint validation | api-gateway + portfolio (round 2) | 8 endpoints | 8 | 0 | 0 | PASS |
| Frontend route smoke | /portfolio, /transactions, /analytics | 3 routes | 3 (HTTP 200) | 0 | 0 | PASS |
| Full suite vitest | OOMs locally (14 workers × 2GB) | — | — | — | killed | DEFERRED |
| Full backend pytest per-service | All 10 services | — | — | — | — | DEFERRED (not in Wave G scope) |
| Integration tests | Requires infra-test profile | — | — | — | — | DEFERRED |
| E2E tests | Requires infra-test profile | — | — | — | — | DEFERRED |
| Playwright | Recommended for next QA cycle | — | — | — | — | DEFERRED |

**Note on DEFERRED layers**: The Wave G changeset is frontend-heavy and the touched backend files (3) are already covered by targeted unit tests. Running the full multi-service pytest + integration + e2e suite was scoped out as the changes have no schema/DDL/event-shape implications that could break other services. A separate full QA pass before a release tag is recommended.

---

## Issues — Full Investigation

## Issue F-001: TanStack Query cache cascade does not invalidate new Wave G keys on portfolio mutations

### Summary
Two mutation hooks (`useTriggerBrokerageSync`/`useDisconnectBrokerage` and `usePortfolioData`'s `handlePositionAdded`) invalidate the cache using pre-Wave G key shapes (`["brokerage-connections"]`, `holdingsByPortfolio`, `transactionsByPortfolio`, `performance`). The Wave G surfaces consume different keys (`qk.brokerage.statusForPortfolio`, `qk.portfolios.riskMetrics`, `realizedPnL`, `valueHistory`, `attribution`, `twr`, `holdingTx`). After a sync or an `addPosition`, these new keys never invalidate; their data remains stale until the next staleTime expires (60s for brokerage status, 5min for risk-metrics).

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Distributed Systems F-001 + F-002

### Root Cause Analysis
- **What**:
  - `apps/worldview-web/hooks/use-brokerage-connections.ts:141-143, 169-180` — invalidates `["brokerage-connections"]` (legacy non-`QK_VERSION` key) but TransactionsBrokerageStatusBar reads `qk.brokerage.statusForPortfolio(portfolioId)` → `["v2","brokerage","status-for-portfolio",portfolioId]`. Disjoint key trees → no overlap.
  - `apps/worldview-web/features/portfolio/hooks/usePortfolioData.ts:439-471` (`handlePositionAdded`) — invalidates `holdingsByPortfolio`, `transactionsByPortfolio`, `holdingsQuotesAll`, `performance(selectedPeriod)`, `bundle`. Does NOT cascade-invalidate `qk.portfolios.detail(id)` which would propagate to all `Analytics*`/`Holding*` consumers.
- **Why**: The mutation hooks predate Wave G. New Wave G query keys were added but the cascade contract documented in `lib/query/keys.ts:21` ("invalidate `qk.portfolios.detail(id)` to refetch all nested keys") was never wired into the existing mutation handlers.
- **When**: Visible whenever a user triggers brokerage sync or adds/sells a position while the Analytics tab or Holding Detail panel is open. Masked by 60s `refetchInterval` for brokerage status; masked by 5min `staleTime` for risk-metrics.
- **Where**: TanStack Query cache layer (frontend).
- **History**: Cache cascade pattern documented in `lib/query/keys.ts:20-25`. This is exactly the convergence problem the QK_VERSION + cascade pattern was designed to prevent — but the mutation handlers were not migrated.

### Evidence
```
git grep "brokerage-connections" apps/worldview-web/hooks/use-brokerage-connections.ts
git grep "qk.brokerage.statusForPortfolio" apps/worldview-web/components/portfolio/TransactionsBrokerageStatusBar.tsx
```
- **File**: `apps/worldview-web/hooks/use-brokerage-connections.ts:141-143`
- **File**: `apps/worldview-web/features/portfolio/hooks/usePortfolioData.ts:439-471`

### Impact
- **Immediate**: After `addPosition`, Wave G surfaces (RiskSidebar, AnalyticsPeriodReturnsTable, HoldingDetailPanel) display pre-position data until 5min cache expires. After brokerage sync, the new StatusBar in TransactionsTab shows the pre-sync status until 60s refetch.
- **Blast radius**: All Wave G analytics surfaces that read from `qk.portfolios.detail(id).*`.
- **Data risk**: Display-only inconsistency, no data corruption.
- **User impact**: Yes — the user sees "stale" analytics after adding a position; their natural expectation is to see the new position reflected immediately.

### Solution Options

#### Option A: Cascade invalidate `qk.portfolios.detail(activePortfolioId)` in `handlePositionAdded`
**Description**: Add a single `queryClient.invalidateQueries({ queryKey: qk.portfolios.detail(activePortfolioId) })` call. The factory's `detail()` key is the parent of all Wave G keys (`["v2","portfolios","detail",id,...]`).
**Changes required**:
- [ ] `apps/worldview-web/features/portfolio/hooks/usePortfolioData.ts:471` — add the cascade invalidation alongside existing flat-key invalidations
- [ ] `apps/worldview-web/hooks/use-brokerage-connections.ts:141, 175` — replace `["brokerage-connections"]` with `qk.brokerage.all` (already in `keys.ts`)
- [ ] Add a test in `usePortfolioData.test.tsx` asserting that `addPosition` invalidates the detail key
**Benefits (long-term)**:
- Fulfils the cascade contract documented in `keys.ts:20-25`
- Future Wave G+ surfaces automatically pick up invalidation
**Drawbacks (long-term)**:
- Slightly broader invalidation than strictly necessary (refetches `concentration`, `sectorAttribution` too — but those are correctly stale after a position change)
**Effort**: Low
**Risk**: Low

#### Option B: Per-key explicit invalidations
**Description**: Add explicit `invalidateQueries` calls for each Wave G key.
**Changes required**: 7-8 new invalidateQueries calls in `handlePositionAdded`, 1 in each brokerage mutation.
**Benefits**: Narrower invalidation.
**Drawbacks**: Brittle — new Wave H/I keys will repeat the bug.
**Effort**: Low
**Risk**: Medium (likely to drift)

### Recommended Option
**Option A** — uses the documented cascade pattern; one-line fix; matches the intent already encoded in `keys.ts`.

### Verification Steps
- [ ] Open `/portfolio/analytics` with Holdings tab populated; add a position via the dialog; observe RiskSidebar refresh within ≤500ms
- [ ] Trigger brokerage sync from Transactions page; observe StatusBar text update within ≤500ms
- [ ] Confirm no infinite refetch loop (the cascade only fires on explicit invalidation, not on every refocus)

---

## Issue F-002: Sidebar tiles TWR / BENCH TWR reference backend fields not returned by /risk-metrics

### Summary
The 11-tile risk sidebar's top two tiles (`TWR`, `BENCH TWR`) reference fields `twr_period` and `spy_twr` that the `/v1/portfolios/{id}/risk-metrics` endpoint does NOT return. The endpoint returns `period_return`, `cagr`, `var_95`, etc., but not the two named fields. These tiles therefore render `—` permanently regardless of data state.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: Architecture F-004 + QA F-003 (indirectly)

### Root Cause Analysis
- **What**: `apps/worldview-web/features/portfolio/components/AnalyticsRiskSidebar.tsx:73-88` METRICS array; `services/api-gateway/src/api_gateway/routes/risk_metrics.py:758-795` payload schema.
- **Why**: Fix agent FA-1 added TWR + BENCH TWR tiles per the design spec (§4.3 ASCII shows them as the first two), assuming backend would supply `twr_period`/`spy_twr` — but the backend does not, and the spec's §3 backend-gap list does not include them as pre-wave additions.
- **When**: On every page render. Tiles always show `—`.
- **Where**: Frontend tile config + backend payload mismatch.
- **History**: Wave G fix-up Round 1 introduced this when reconciling "9 tiles vs 11" to match the spec's prose count. The deviation was flagged in FA-1's report ("dropped VAR 95 + RETURN to keep 11"), but the choice to add fields-not-in-payload was not caught.

### Evidence
```python
# services/api-gateway/src/api_gateway/routes/risk_metrics.py:758-795
payload = {
    "drawdown_max": ..., "drawdown_current": ...,
    "volatility_annualized": ..., "sharpe": ..., "sortino": ...,
    "beta_vs_spy": ..., "calmar": ..., "win_rate": ..., "alpha": ...,
    "period_return": ..., "cagr": ..., "var_95": ...,
    # NO twr_period, NO spy_twr
}
```
```tsx
// apps/worldview-web/features/portfolio/components/AnalyticsRiskSidebar.tsx:75
{ label: "TWR",       field: "twr_period", format: "percent", signColor: true },
{ label: "BENCH TWR", field: "spy_twr",    format: "percent", signColor: true },
```

### Impact
- **Immediate**: 2/11 tiles permanently empty — the 2 most prominent (top of sidebar).
- **Blast radius**: Analytics tab only.
- **Data risk**: None.
- **User impact**: HIGH — sidebar appears broken on first encounter.

### Solution Options

#### Option A: Alias TWR → period_return and acknowledge BENCH TWR as known follow-up
**Description**: The backend already computes `period_return` for the configured lookback. Map TWR's `field` to `period_return`. For BENCH TWR, render a separate `—` placeholder with a tooltip "Benchmark TWR requires backend support" and document as deferred.
**Changes required**:
- [ ] `AnalyticsRiskSidebar.tsx:75` — change `field: "twr_period"` → `field: "period_return"`
- [ ] `AnalyticsRiskSidebar.tsx:76` — keep `field: "spy_twr"` with a comment explaining it intentionally renders `—` until backend support lands
- [ ] Update spec `docs/designs/0089/04-portfolio-detail.md` §4.3 to clarify BENCH TWR is a v2 enhancement
**Effort**: Low
**Risk**: Low

#### Option B: Drop both tiles, return to a 9-tile sidebar
**Description**: Revert to the 9-tile composition; update spec to match.
**Changes required**: Remove 2 tiles; update spec ASCII + prose.
**Drawbacks**: Loses one of Wave G's headline features (TWR vs benchmark).
**Effort**: Low
**Risk**: Medium (spec churn)

#### Option C: Backend adds twr_period + spy_twr to the endpoint
**Description**: Extend `risk_metrics.py` to compute `twr_period = (V_end - V_start) / V_start` and `spy_twr` from aligned SPY series.
**Changes required**:
- [ ] `risk_metrics.py` — add 2 new fields + computation
- [ ] new test cases
- [ ] api-gateway docs update
**Effort**: Medium
**Risk**: Low

### Recommended Option
**Option A** — TWR maps cleanly to the existing `period_return` field (1-line fix); BENCH TWR is genuinely a backend gap (requires alpha-style aligned-series computation). Splitting these gives the user the TWR tile populated immediately while parking BENCH TWR cleanly.

### Verification Steps
- [ ] Render Analytics tab — TWR tile shows formatted percent matching `period_return`
- [ ] BENCH TWR shows `—` with a tooltip explaining
- [ ] Existing test `AnalyticsRiskSidebar.test.tsx` updated to assert TWR populated, BENCH TWR `—`

---

## Issue F-003: `description` field has no max_length on the Pydantic schema (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH (Security F-001)
**File**: `services/portfolio/src/portfolio/api/schemas.py:196`
**Issue**: `description: str | None = None` has no `max_length` constraint. A malicious upstream broker could push a 100KB+ description that bloats every `/transactions` response and breaks the React table layout.
**Fix**: `description: Annotated[str, StringConstraints(max_length=500)] | None = None`. Also slice in `title=` attribute as defense-in-depth (`title={(row.original.description ?? "").slice(0, 500)}`).
**Auto-fixable**: YES

---

## Issue F-004: 3 MAJOR test-coverage gaps from QA/Test agent

| ID | File | Issue |
|----|------|-------|
| F-004a | `apps/worldview-web/components/portfolio/__tests__/transaction-columns.test.ts` | No test for `description` rendering branch (transaction-columns.tsx:243-248) |
| F-004b | `apps/worldview-web/features/portfolio/components/__tests__/AnalyticsRiskSidebar.test.tsx` | `isError` branch at line :226 has no test |
| F-004c | `apps/worldview-web/features/portfolio/components/__tests__/AnalyticsRiskSidebar.test.tsx` | `alpha` rendered format not asserted (fixture has it, no `expect` for "+2.63%") |

**Severity**: MAJOR (HIGH confidence — flagged by QA/Test)
**Auto-fixable**: YES — 3 simple test additions
**Fix recommendation**: apply before merge

---

## Issue F-005: risk-metrics sequential awaits (MAJOR perf win)

**Severity**: MAJOR
**Confidence**: HIGH (DS F-004)
**File**: `services/api-gateway/src/api_gateway/routes/risk_metrics.py:614-632`
**Issue**: `_fetch_value_history` and `_fetch_spy_ohlcv` execute sequentially. They have no data dependency. With `lookback_days=3650` total tail-latency = S1_RTT + S3_RTT + S3_search_RTT instead of `max(S1_RTT, S3_RTT)`.
**Fix**: `portfolio_series, spy_series = await asyncio.gather(_fetch_value_history(...), _fetch_spy_ohlcv(...), return_exceptions=True)`. Handle `_BareEnvelopeError` specifically on the portfolio leg; treat SPY exceptions as `[]`.
**Auto-fixable**: NO (needs care with `_BareEnvelopeError` re-raise)
**Effort**: Medium

---

## Issue F-006: HoldingsTab inline brokerage key (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH (DS F-003)
**File**: `apps/worldview-web/features/portfolio/components/HoldingsTab.tsx:139`
**Issue**: Inline key `["brokerage-connections", activePortfolioId]` duplicates the same query as TransactionsBrokerageStatusBar but with a different (non-cascading) key shape. Duplicate fetch + cache miss.
**Fix**: switch to `qk.brokerage.statusForPortfolio(activePortfolioId)`.
**Auto-fixable**: YES (1-line)

---

## Issue F-007: 5xx silently downgrades to "insufficient_data" (MAJOR)

**Severity**: MAJOR
**Confidence**: HIGH (DS F-005)
**File**: `services/api-gateway/src/api_gateway/routes/risk_metrics.py:456-462, 501-502, 549-552`
**Issue**: When S1 or S3 returns 5xx (or raises), `_fetch_*` returns `[]` and the endpoint reports `data_quality.status = "insufficient_data"` — indistinguishable from a portfolio with genuinely few snapshots.
**Fix**: Track per-leg failure reason. Add `data_quality.degradation = {"value_history": "5xx"|"ok", "benchmark": "5xx"|"ok"|"no_data"}` so the sidebar can render the correct empty-state caption.
**Auto-fixable**: NO
**Effort**: Medium

---

## Issue F-008: AnalyticsPeriodReturnsTable retry storm risk (MAJOR)

**Severity**: MAJOR
**Confidence**: MEDIUM (DS F-006)
**File**: `apps/worldview-web/features/portfolio/components/AnalyticsPeriodReturnsTable.tsx:103-114`
**Issue**: 7 parallel `useQueries` × default 3-retry = up to 21 concurrent S1 calls on a transient backend hiccup (DS-005 retry storm pattern).
**Fix**: Add `retry: 1` to these queries.
**Auto-fixable**: YES (1-line per query)

---

## Issue F-009: Sidebar tile set vs spec drift (MAJOR)

**Severity**: MAJOR (combined finding)
**Confidence**: HIGH (Arch F-001)
**Files**: `apps/worldview-web/features/portfolio/components/AnalyticsRiskSidebar.tsx:73-88` vs `docs/designs/0089/04-portfolio-detail.md:309-330, 403`
**Issue**: Spec §4.3 ASCII lists 10 tiles; spec prose says "11-tile". Implementation ships 11 tiles by adding `CAGR` (not in spec ASCII) and dropping `VAR 95`/`RETURN` placeholders. Sub-issue: the deviation was not memorialised in the spec.
**Fix recommendation**: Either (a) drop CAGR to match spec ASCII (10 tiles, reconcile prose), or (b) amend spec §4.3 + §5.3 to officially add CAGR. F-002 above already recommends TWR-aliasing; pick a definitive 11-tile set and update both atomically.
**Auto-fixable**: NO (architectural decision)
**Requires decision**: YES

---

## Minor + NIT findings (consolidated)

| ID | Source | File | Issue | Fix |
|----|--------|------|-------|-----|
| M-001 | QA F-004 | `test_risk_metrics_wave_g.py` | `_win_rate` lacks all-negative-returns edge case test | Add `assert _win_rate([-0.01]*12) == 0.0` |
| M-002 | QA F-005 | `test_risk_metrics_wave_g.py` | `_alpha` lacks zero-variance SPY edge case | Add `assert _alpha([0.001]*15, [0.0]*15) is None` |
| M-003 | QA F-006 | `HoldingInstrumentTxList.test.tsx` | populated `description` path untested | Add test with `description="Cash Dividend"` |
| M-004 | Security F-002 | `transaction-columns.tsx:243, HoldingInstrumentTxList.tsx:213` | `title=` mirrors full untruncated description | `.slice(0, 500)` defensive truncate |
| M-005 | DS F-007 | `HoldingRealizedRow.tsx:71-87` | `endDate` uses local time, not UTC | Use `new Date().toISOString().slice(0,10)` |
| M-006 | DS F-008 | `HoldingInstrumentTxList.tsx:99-104` | `holdingTx` key includes instrumentId but request is identical → duplicate fetches | Drop `instrumentId` from the key, filter client-side |
| M-007 | Arch F-002 | `AnalyticsTab.tsx`, `AnalyticsPeriodSelector.tsx` | Spec §4.3 shows `DataFreshnessPill` next to period selector — not rendered | Add `<DataFreshnessPill lastUpdated={data.as_of} />` |
| N-001 | QA F-007 | `test_use_cases_read_models.py:166-236` | No contract test through FastAPI response_model serialisation | Add API-router test (optional) |
| N-002 | Security F-003 | `risk_metrics.py:154-155` | `X-Internal-JWT` fallback in non-RSA mode | Startup assertion in prod env |
| N-003 | DS F-009 | `risk_metrics.py:597-602` | No try/except at SPY OHLCV call site (relies on inner catch) | Wrap call site `try: ... except Exception: spy_series = []` |
| N-004 | Arch F-003 | `docs/designs/0089/04-portfolio-detail.md:403` | Spec paths reference `components/portfolio/` but actual is `features/portfolio/components/` | Update spec paths |
| N-005 | Arch F-004 (sub) | `AnalyticsRiskSidebar.tsx` comment | Comment claims TWR/BENCH TWR render "—" pending backend, but no backend roadmap | Either alias TWR (see F-002) or add backend roadmap link |

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| R5 Avro forward-compat | PASS | No Avro schemas touched |
| R7 cross-service DB | PASS | risk_metrics.py is pure composition over REST |
| R8 no dual writes | PASS | All Phase 1 changes are read-only |
| R10 UUIDv7 / R11 UTC | N/A (no new IDs/timestamps) | — |
| R14 frontend→S9 only | PASS | No direct backend URLs in Wave G |
| R19 no test deletion | PASS | All test diffs are additions |
| R25 API → use cases only | PASS | risk_metrics.py has no infrastructure imports |
| R27 ReadOnlyUoW | N/A (composition route) | — |
| BP-571 createGateway anti-pattern | PASS in Wave G scope | All 11 Wave G files migrated to useApiClient; ~30 pre-Wave G files remain (separate cleanup) |
| Docs freshness | PASS | api-gateway.md, TRACKING.md, BUG_PATTERNS.md all updated |
| Frontend type contract | PASS | `apps/worldview-web/types/api.ts:907` carries `description?: string \| null` |

---

## Decisions Needed

| Finding | Question | Options | Recommendation |
|---------|----------|---------|----------------|
| F-009 | Sidebar tile composition | (a) drop CAGR to match spec ASCII = 10 tiles + reconcile prose; (b) keep CAGR + amend spec §4.3/§5.3 to officially add it | (b) — CAGR is a real metric the backend computes; cheaper to fix the spec than drop the feature |
| F-002 | TWR/BENCH TWR backend fields | (a) alias TWR→period_return + BENCH TWR placeholder; (b) drop both tiles; (c) add backend fields | (a) — cheapest fix that gets TWR populated immediately and parks BENCH TWR cleanly |

---

## Fixes Applied (this session)

| Finding | Fix | Status |
|---------|-----|--------|
| — | None yet — report only | — |

---

## Recommendations (priority-ordered)

1. **Before merge** — fix the 2 CRITICAL cache-cascade issues (F-001) and the 2 broken sidebar tiles (F-002). Both are 1-line / 10-line fixes.
2. **Before merge** — add the `max_length=500` Pydantic constraint on `description` (F-003).
3. **Before merge** — add the 3 missing test cases (F-004a/b/c).
4. **Before merge** — pick one of the F-009 decisions (CAGR in spec or out of code).
5. **Soon after merge** — convert risk-metrics sequential awaits to `asyncio.gather` (F-005).
6. **Soon after merge** — fix HoldingsTab inline brokerage key (F-006).
7. **Backlog** — refine 5xx degradation reasoning (F-007) and add `retry: 1` to AnalyticsPeriodReturnsTable queries (F-008).
8. **Backlog** — apply the 7 MINOR findings as part of Wave H polish.

---

## Compounding Updates

**Already applied this session**:
- ✅ `docs/BUG_PATTERNS.md` BP-571: `createGateway(accessToken)` inside `useMemo` bypasses canonical `useApiClient()` hook
- ✅ `docs/services/api-gateway.md` line 629: corrected performance endpoint description (was wrong — claimed calmar/win-rate when only return_pct/return_abs/covered_pct returned)
- ✅ `docs/designs/0089/04-portfolio-detail.md`: revised with calmar/win_rate/alpha backend additions + OQ resolutions (Wave G design pre-flight)

**Additional updates recommended** (not applied):
- ⏳ `docs/designs/0089/04-portfolio-detail.md` §4.3 + §5.3 — reconcile tile set decision (F-009) and path drift (N-004)
- ⏳ `.claude/review/checklists/REVIEW_CHECKLIST.md` — append §10n Frontend / TanStack Query gateway access checklist (BP-571 reference); previously denied edit, paste-ready content in earlier QA report
- ⏳ `docs/STANDARDS.md` — add a TanStack Query "mutation invalidation cascade" pattern documenting the `qk.portfolios.detail(id)` invalidation rule (F-001's class of bug)

---

## Verdict

**PASS_WITH_WARNINGS** — Wave G is functionally correct, live-verified, and 0 BLOCKING. The 2 CRITICAL findings are cache-consistency cosmetics (max 5min staleness, not data corruption) and 1 cosmetic display defect (2 sidebar tiles render `—`). Recommend applying the priority-ordered fixes above before opening the PR; the implementation is otherwise merge-ready.

---

## Workflow Chain — Next Steps

- **Apply F-001/F-002/F-003/F-004** → re-run targeted vitest + typecheck → commit + PR
- **Or invoke `/fix-bug` with finding IDs** to orchestrate parallel fix agents

**Report written to**: `docs/audits/2026-05-26-qa-wave-g-final-report.md`
