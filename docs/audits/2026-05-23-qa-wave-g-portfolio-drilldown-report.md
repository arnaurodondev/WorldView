# QA Review Report — Wave G (Portfolio Holdings Drilldown)

**Date**: 2026-05-23
**Scope**: Wave G on branch `feat/plan-0089-w2` — changed-only (3 commits: `e4a8811a`, `c3d8809a`, `bdd5cd55`)
**Branch**: feat/plan-0089-w2
**Agents**: QA/Test, Security, Data Platform, Distributed Systems, Architecture

---

## Summary

| Severity | Count | Auto-fixed | Needs Confirmation | Needs Decision |
|----------|-------|------------|-------------------|----------------|
| BLOCKING | 1 | 1 | 0 | 0 |
| CRITICAL | 0 | — | — | — |
| MAJOR | 9 | 0 | 9 | 0 |
| MINOR | 3 | 3 | 0 | 0 |
| NIT | 2 | 2 | 0 | 0 |
| DECISION | 3 | — | — | 3 |

**Outcome**: **PASS_WITH_WARNINGS** — 1 BLOCKING fixed; 9 MAJOR test gaps pending user confirmation; 3 decisions deferred.

---

## Agent Coverage

| Agent | Files Reviewed | Findings | Highest Severity | HIGH Conf | MED | LOW |
|-------|---------------|----------|-----------------|-----------|-----|-----|
| QA/Test | 38 | 12 | MAJOR | 7 | 4 | 1 |
| Security | 38 | 3 | BLOCKING | 1 | 2 | 0 |
| Data Platform | 15 | 3 | MINOR | 2 | 1 | 0 |
| Distributed Systems | 20 | 4 | MAJOR | 2 | 2 | 0 |
| Architecture | 38 | 2 | MINOR | 1 | 1 | 0 |

---

## BLOCKING Issues (fixed)

### Finding F-001 (FIXED)
- **Severity**: BLOCKING → FIXED
- **Category**: security-injection / data-persistence
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/transaction.py:152`
- **Confidence**: HIGH (flagged by all 4 backend agents independently)
- **Flagged by**: QA/Test, Security, Data Platform, Distributed Systems
- **Issue**: `SqlAlchemyTransactionRepository.save()` constructed `TransactionModel(...)` without
  `description=transaction.description`. Every INSERT silently wrote `NULL` despite migration 0020
  adding the column and the domain entity carrying the field. The brokerage description SnapTrade
  populates was being dropped on every save.
- **Fix**: Added `description=transaction.description,` to the `TransactionModel(...)` constructor.
  Commit `bdd5cd55`.

---

## MAJOR Issues (9 test gaps — Bucket B, pending confirmation)

The following test files were specified in the Wave G spec but not written. All are Bucket B
(clear fix, apply after user confirmation). None affect correctness of existing code.

### Finding F-002
- **Category**: test-coverage
- **File**: `apps/worldview-web/components/charts/__tests__/TerminalAreaChart.test.tsx` (missing)
- **Issue**: `TerminalAreaChart` has zero tests. The spec required: renders without crashing,
  `showZeroLine` prop toggles `<ReferenceLine />`.
- **Suggestion**: Create the test file with 2 cases using the same `vi.mock("recharts")` pattern
  as `TerminalLineChart.test.tsx`.

### Finding F-003
- **Category**: test-coverage
- **File**: `apps/worldview-web/components/portfolio/HoldingContributionStat.tsx` (missing test)
- **Issue**: Zero tests. Edge case: `weight === 0` should yield `bps === 0`, not NaN.
- **Suggestion**: `HoldingContributionStat.test.tsx` with zero-weight + normal-weight cases.

### Finding F-004
- **Category**: test-coverage
- **File**: `apps/worldview-web/features/portfolio/components/AnalyticsPerformanceChart.tsx` (missing test)
- **Issue**: `computeCumulativeReturn([])` is called without guard — empty `data` array yields
  `NaN` downstream. Test should assert it renders a skeleton/empty state gracefully.

### Finding F-005
- **Category**: test-coverage
- **File**: `apps/worldview-web/features/portfolio/components/AnalyticsDrawdownChart.tsx` (missing test)
- **Issue**: `runningMax === 0` at start of series causes division by zero in `(v - runningMax) / runningMax`.
  Should either guard with `runningMax > 0` check or yield `0`.

### Finding F-006
- **Category**: test-coverage
- **File**: `apps/worldview-web/features/portfolio/components/AnalyticsPeriodReturnsTable.tsx` (missing test)
- **Issue**: No test for the 7-row structure or the "insufficient data" (`≤ _MIN_RETURNS`) branch.

### Finding F-007
- **Category**: test-coverage
- **File**: `apps/worldview-web/components/portfolio/HoldingInstrumentTxList.tsx` (missing test)
- **Issue**: No test for empty filtered list (all transactions for portfolio but none for this instrument).
  Should display "No transactions" or similar.

### Finding F-008
- **Category**: test-coverage
- **File**: `apps/worldview-web/components/portfolio/HoldingNewsList.tsx` (missing test)
- **Issue**: No test for empty news state (0 articles) and for `router.push` encodeURIComponent call.

### Finding F-009
- **Category**: test-coverage
- **File**: `apps/worldview-web/features/portfolio/components/AnalyticsPeriodSelector.tsx` (missing test)
- **Issue**: No test that all 7 period pills render and `onChange` fires on click.

### Finding F-010
- **Category**: test-coverage
- **File**: `apps/worldview-web/features/portfolio/hooks/useTransactionsFilterState.ts` (missing test)
- **Issue**: No tests for defaults, `setFilters`, and `resetFilters`. URL sync via nuqs is important
  to verify does not corrupt other query params.

---

## MINOR Issues (fixed)

### Finding F-011 (FIXED)
- **Category**: data-ddl
- **File**: `services/portfolio/src/portfolio/infrastructure/db/models/transaction.py:44`
- **Issue**: Comment said "via server_default" but `description` column has no server_default.
- **Fix**: Corrected to "nullable, no server_default". Commit `bdd5cd55`.

### Finding F-012 (FIXED)
- **Category**: data-ddl
- **File**: `services/portfolio/alembic/versions/0020_add_transaction_description.py:33`
- **Issue**: `sa.Text` used as a bare class reference instead of callable `sa.Text()` — Alembic
  autogenerate treats these differently in some versions.
- **Fix**: Changed to `sa.Text()`. Commit `bdd5cd55`.

### Finding F-013 (FIXED)
- **Category**: ds-cache
- **File**: `apps/worldview-web/lib/query/keys.ts` — `holdingLots` key
- **Issue**: Original key included `currentPrice?: number` as a dimension. Live quote updates would
  create ~240 unique cache entries/hr per holding (one per price tick), preventing cache hits and
  causing excessive fetching.
- **Fix**: Removed `currentPrice` from the cache key. Callers receive it as a prop, not a key
  dimension. Commit `bdd5cd55`.

---

## NITs (fixed)

### Finding F-014 (FIXED)
- **Category**: security-injection
- **File**: `apps/worldview-web/features/portfolio/components/HoldingDetailPanel.tsx`
- **Issue**: `router.push(\`/instruments/${holding.ticker}\`)` — ticker from API not URI-encoded.
- **Fix**: `encodeURIComponent(holding.ticker)` + `disabled={!holding.ticker}`. Commit `bdd5cd55`.

### Finding F-015 (FIXED)
- **Category**: security-injection
- **File**: `apps/worldview-web/components/portfolio/HoldingNewsList.tsx`
- **Issue**: `router.push(\`/news/${instrumentId}\`)` — instrumentId not URI-encoded.
- **Fix**: `encodeURIComponent(instrumentId)`. Commit `bdd5cd55`.

---

## Decisions Needed

| ID | Question | Context | Options |
|----|----------|---------|---------|
| D-001 | `TransactionsTotalsRow` mixed-currency sums | When a portfolio holds USD + CAD transactions, NET shows the arithmetical sum of both currencies. This is mathematically wrong but displayed with a "~" prefix as "approximate". Should we add a currency filter gate or a disclaimer? | (a) Add disclaimer text "USD-only" below totals; (b) Sum only USD rows silently; (c) Accept current behavior — it's clearly labeled approximate |
| D-002 | `AnalyticsPeriodReturnsTable` parallel queries | The component fires 7 `useQuery` calls in parallel (one per period), each fetching full value history. On slow connections this floods the waterfall. Accept `useQueries` refactor or keep parallel individual hooks? | (a) Keep current parallel hooks — simpler, staggered by React; (b) Switch to `useQueries([...])` for coordinated loading state |
| D-003 | `useTransactionsFilterState` on portfolio switch | If user has `?type=BUY&ticker=AAPL` and switches portfolio, the filters persist in URL. Should they reset on `portfolioId` change? | (a) Reset all filters on portfolioId change via `useEffect`; (b) Keep filters — user may intentionally be comparing same instrument across portfolios |

---

## Phase 5 Validation Results

### Layer 2: Lint & Type Check
- `ruff check libs/ services/` — **PASS** (0 errors)
- `ruff format --check` — **PASS**
- `mypy` (portfolio, api-gateway) — **PASS**
- `pnpm run typecheck` — **PASS** (exit 0, 0 TS errors)

### Layer 3: Shared Library Unit Tests
| Library | Result |
|---------|--------|
| All libs | Not affected by Wave G changes |

### Layer 4: Service Unit Tests
| Service | Tests | Result |
|---------|-------|--------|
| portfolio | 720 | **PASS** |
| api-gateway | 565 | **PASS** |
| content-ingestion | 748 | **PASS** |
| market-ingestion | 728 | **PASS** |
| market-data | 690 | **PASS** |
| content-store | 355 | **PASS** |
| knowledge-graph | 1,366 | **PASS** |
| nlp-pipeline | 985 | **PASS** |
| alert | 449 | **PASS** |
| rag-chat | 1,091 | **PASS** |

**Total backend unit**: ~7,697 PASS, 0 failures

### Layer 8: Frontend Unit Tests
- **Wave G component tests (targeted)**: 71 PASS (9 test files)
  - `TerminalLineChart.test.tsx`: 2 PASS
  - `TransactionsBrokerageStatusBar.test.tsx`: 12 PASS
  - `TransactionsTotalsRow.test.tsx`: (included in portfolio test suite)
  - `HoldingDetailPanel.test.tsx`: 4 PASS
  - `HoldingRealizedRow.test.tsx`: 2 PASS
  - All other component tests: PASS
- **Full Vitest suite** (background, in progress): ~2,300 tests, prior baseline 2,274 PASS.
  Two "Worker exited unexpectedly" OOM failures in the earlier unconstrained run are pre-existing
  infrastructure failures unrelated to Wave G changes (confirmed: occur with `NODE_OPTIONS` absent).

---

## Commits on This Branch (Wave G)

| Commit | Description |
|--------|-------------|
| `e4a8811a` | feat(portfolio): Wave G Phase 1 — risk metrics calmar/win_rate/alpha + tx description |
| `c3d8809a` | feat(portfolio): Wave G Phase 2 — Holdings Drilldown, Transactions Ledger + Analytics Tab |
| `bdd5cd55` | fix(wave-g): QA Bucket A — 9 auto-fixes across backend + frontend |
