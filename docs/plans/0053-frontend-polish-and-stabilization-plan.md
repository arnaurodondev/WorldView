---
id: PLAN-0053
title: Frontend Polish & Platform Stabilization (Phase 5)
prd: docs/audits/2026-04-29-qa-frontend-deep-audit-and-roadmap.md
status: in-progress
created: 2026-04-29
updated: 2026-04-30
---

# PLAN-0053 — Frontend Polish & Platform Stabilization

> **Source**: `docs/audits/2026-04-29-qa-frontend-deep-audit-and-roadmap.md` (deep frontend QA, 36 findings, 6 parallel investigations) + 5 root-cause investigations performed on 2026-04-29.
>
> **Goal**: Close the gap between "what was planned in PLAN-0049/0050/0051/0052" and "what users actually need". Eliminate 4 CRITICAL bugs, 11 MAJOR gaps, and ship the missing user-feedback frontend so the platform reaches a Bloomberg-grade bar.

---

## Executive Summary

PLANs 0049–0052 shipped 47 of 47 roadmap items, but **8 regressions/scope-leaks** remain visible to users:

| # | User-visible defect | Root cause (verified) | Wave |
|---|---------------------|------------------------|------|
| 1 | Instrument chart infinite past-scroll loop | `placeholderData` object recreated each render → unstable `data` reference → `useEffect([data?.bars])` fires repeatedly | A |
| 2 | Holdings page "black widget" overlay at top | `ExposureBreakdown` loading skeleton uses `h-full` inside `min-h-[200px]` parent → expands to fill the 200px black panel | A |
| 3 | Watchlist add fails for "apple"; AAPL works | S3 instrument search uses `symbol.ilike()` + `exchange.ilike()` only — `name` field NOT searched | A (frontend tier-1) + B (backend tier-2) |
| 4 | Alert title "Graph Change alert" | Backend `_compose_alert_title()` has no template for `GRAPH_CHANGE` / `CONTRADICTION` types — falls back to humanize(alert_type) | A |
| 5 | ACK/snooze state divergence multi-device | Frontend optimistic update has no rollback on backend 5xx; localStorage left dirty | A |
| 6 | Fundamentals "—" pervasive | EODHD returns NULL for some fields; backfill has no per-field logging; no fallback provider | C |
| 7 | Predictions filter "doesn't work" | Polymarket Gamma API exposes ~300 markets total; first-tag fallback yields tiny per-category buckets | C |
| 8 | Top-bar tickers compress on <1024px | `IndexTicker` has no responsive breakpoints | A |

Plus 21 polish items (alerts/chat/screener/settings/workspace/instrument/auth) and the user-feedback frontend (PLAN-0052 Wave E was never started — 14 components missing).

This plan delivers all of these in **8 waves over ~104h** (≈3 weeks). Waves are **independently committable** — Wave A is gating, B–H can run in parallel worktrees once A lands.

---

## Plan Decomposition

| Wave | Theme | Effort | Depends on |
|------|-------|--------|------------|
| A | Critical bug fixes (8 user-visible CRITICAL/MAJOR) | 18h | none — gates Phase 5 |
| B | Watchlist CRUD backend + Holdings widget swap | 12h | A |
| C | Backend data gaps (fundamentals + predictions) | 18h | none |
| D | Portfolio enhancements (news, transactions, realized P&L, etc.) | 16h | A |
| E | Instrument page polish (right sidebar, fundamentals, intelligence) | 14h | A |
| F | Secondary pages polish (alerts, settings, workspace, auth) | 10h | none |
| G | User Feedback frontend (PLAN-0052 Wave E completion) | 16h | none |
| H | Responsive + A11y + performance | 20h | A, B, C, D, E |

**Total**: ~104h. Waves marked "none" can start immediately in parallel.

**Wave A is BLOCKING** — must land before B, D, E, H. C, F, G can run alongside A.

---

# Wave A — Critical Bug Fixes ✅

**Status**: **DONE** — 2026-04-30 · 417 alert unit tests pass · 815 frontend Vitest pass · TypeScript clean · ruff clean

**Goal**: Close every CRITICAL user-visible defect before any polish work. After Wave A, the instrument page works, watchlists are usable, alerts have meaningful titles, and the top bar doesn't break on common viewports.
**Depends on**: none
**Estimated effort**: 18h
**Architecture layer**: API + frontend + backend (alert use case)

## Tasks

### T-A-1-01 — Fix OHLCVChart infinite past-scroll loop

**Type**: impl
**depends_on**: none
**blocks**: T-A-1-04 (chart-toolbar polish in Wave E)
**Target files**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:295-304`
**PRD reference**: `2026-04-29-qa-frontend-deep-audit-and-roadmap.md` §3 I-03 + chart-loop root-cause investigation 2026-04-29

**What to build**:
The `useQuery` for OHLCV bars constructs a fresh `placeholderData` object literal on every render (lines 301-303). React Query treats each render's `placeholderData` as a new value, so `data` returned from the hook has a different reference each render. The downstream effect at line 711 (`useEffect(() => { ... }, [data?.bars])`) re-fires on every render, calling `setVolumeProfileBuckets` (line 706) which triggers another re-render — an infinite loop. Wrap `placeholderData` in `useMemo` keyed on `[initialBars, timeframe, instrumentId]` so the reference is stable across renders.

**Logic & Behavior**:
- Add `useMemo` import to OHLCVChart.tsx (it may already exist).
- Extract the placeholder construction into a `memoizedPlaceholder` const computed via `useMemo`.
- Pass `memoizedPlaceholder` to `useQuery` instead of the inline ternary.

**Tests to write**:
| Test | What it verifies | Type |
|------|------------------|------|
| `test_ohlcv_chart_query_does_not_refetch_on_rerender` | Mount chart with initialBars, force 5 parent re-renders, assert `gateway.getOHLCV` was called exactly once | unit (Vitest + RTL) |
| `test_ohlcv_chart_volume_profile_stable_across_rerenders` | Mount chart, assert `setVolumeProfileBuckets` invoked exactly once for a given bar set | unit |

**Downstream test impact**:
- `apps/worldview-web/__tests__/instrument/OHLCVChart.test.tsx` — must pass
- Playwright `apps/worldview-web/tests/e2e/instrument-page.spec.ts` — must not regress

**Acceptance criteria**:
- [ ] Loading instrument page triggers exactly ONE `/v1/ohlcv/{id}` request on mount (verify via Network tab in dev)
- [ ] Chart renders without visual flashing or auto-scrolling
- [ ] Switching timeframes (1D → 1W → 1M) triggers exactly one new request per switch
- [ ] No console warnings about "Maximum update depth exceeded"

---

### T-A-1-02 — Fix Holdings "black widget" loading overlay

**Type**: impl
**depends_on**: none
**blocks**: T-A-1-03
**Target files**: `apps/worldview-web/components/portfolio/ExposureBreakdown.tsx:60-67`
**PRD reference**: §3 P-01 + z-index root-cause investigation 2026-04-29

**What to build**:
The investigation revealed this is NOT a z-index bug. The parent grid cell (`PortfolioAnalyticsSection.tsx:171`) reserves `min-h-[200px] bg-card` to keep layout stable. Inside it, `ExposureBreakdown`'s loading skeleton wrapper uses `flex flex-col gap-2 h-full` — the `h-full` stretches the skeleton container to fill the parent's 200px, leaving ~160px of empty black space. Removing `h-full` from the loading skeleton lets the skeleton items stack to their natural height (~40px), with the parent's 200px wrapper rendering only border + minor padding.

**Logic & Behavior**:
- Edit `ExposureBreakdown.tsx:62` — change `<div className="flex flex-col gap-2 h-full">` to `<div className="flex flex-col gap-2">`.
- Verify the loaded state still fills correctly (it does — the loaded state uses internal sizing, not `h-full`).
- Audit other portfolio loading skeletons for the same pattern (`SectorAllocationPanel`, `RiskMetricsStrip`).

**Tests to write**:
| Test | What it verifies | Type |
|------|------------------|------|
| `test_exposure_breakdown_loading_does_not_stretch_parent` | Render with `isLoading=true`, assert wrapper is no taller than 60px | unit |

**Acceptance criteria**:
- [ ] At scroll position 0 on Holdings tab during initial load, no black panel exceeds the height of its content + standard card padding
- [ ] Loaded state renders identically to before
- [ ] Skeleton items remain visible during loading

---

### T-A-1-03 — Audit other loading skeletons for `h-full` anti-pattern (BP candidate)

**Type**: refactor
**depends_on**: T-A-1-02
**blocks**: none
**Target files**: `apps/worldview-web/components/**/*.tsx` (audit), `docs/BUG_PATTERNS.md` (new entry)

**What to build**:
The pattern `<div className="... h-full">` inside a parent with `min-h-[X] bg-card` produces a "black widget" effect during loading. Audit all loading-state branches in portfolio + dashboard + instrument components and convert any that use `h-full` to natural-height stacking. Add new bug pattern `BP-291 — h-full loading skeleton in min-h parent produces black overlay`.

**Tests to write**: per-component visual snapshot tests (Playwright @ scroll-top during loading).

**Acceptance criteria**:
- [ ] No remaining `h-full` on loading-state divs inside `min-h-*` parents
- [ ] BP-291 added to docs/BUG_PATTERNS.md with code example + fix

---

### T-A-1-04 — Watchlist add: tier-1 fix (frontend-only)

**Type**: impl
**depends_on**: none
**blocks**: none (T-B-2-01 will do tier-2 backend)
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:359-386`, `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:446-449`
**PRD reference**: §3 P-04c + watchlist root-cause investigation 2026-04-29

**What to build**:
Backend-side, S3 instrument search only queries `symbol.ilike(pattern)` and `exchange.ilike(pattern)` — never `name`. Result: "apple" returns 0; "AAPL" works. Tier-2 backend fix is in Wave B. **Tier-1 ships now**:

1. **Auto-uppercase the input** in `handleInputChange` so users typing "apple" automatically search for "APPLE" (which still won't match name, but at least matches ticker prefixes more reliably).
2. **Update placeholder** from "Add ticker or company…" to "Add ticker (e.g. AAPL)…" to set expectations.
3. **Differentiate error messages** — replace the single "Failed to add — check if already in watchlist" with specific messages keyed off `GatewayError.status`:
   - `409` → "Already in this watchlist"
   - `404` → "Symbol not found — try the full ticker (e.g. AAPL)"
   - `5xx` → "Server error — try again"
4. **Empty-state hint** when search returns zero — render: "No results. Try the ticker symbol (e.g. AAPL for Apple)."

**Logic & Behavior**:
- In `handleInputChange`, uppercase the value before setting state.
- Add `onError` callback to `addMutation` that inspects `GatewayError.status` and sets a typed error message in component state.
- Render the typed error message (replacing the generic line at 446-449).

**Tests to write**:
| Test | What it verifies | Type |
|------|------------------|------|
| `test_input_auto_uppercases` | Type "apple" → state holds "APPLE" | unit |
| `test_409_renders_already_in_watchlist` | Mock 409 response, assert specific message | unit |
| `test_empty_search_renders_help` | Search returns [] → empty-state hint visible | unit |

**Acceptance criteria**:
- [ ] Typing "apple" results in input value "APPLE"
- [ ] 409 / 404 / 5xx all render distinct messages
- [ ] Help text in placeholder visible
- [ ] Empty-state hint renders with example

---

### T-A-1-05 — Watchlist delete button discoverability

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:184-208`

**What to build**:
The delete button exists and is hooked up to `onDelete(member.entity_id)` which calls `removeWatchlistMember()`. It's hidden behind `opacity-0 group-hover/row:opacity-100`. Users miss it. Change default opacity to `30` (subtle but discoverable), `100` on hover. Add tooltip: "Remove from watchlist".

**Acceptance criteria**:
- [ ] Delete button visible at low opacity by default
- [ ] Hover raises to full opacity
- [ ] Tooltip on hover

---

### T-A-1-06 — Alert title backend templates (per-type)

**Type**: impl
**depends_on**: none
**blocks**: T-A-1-07
**Target files**: `services/alert/src/alert/application/use_cases/alert_fanout.py:128-161`, `services/alert/tests/unit/test_alert_fanout.py`
**PRD reference**: §1 D-05 + alert root-cause investigation 2026-04-29

**What to build**:
The current `_compose_alert_title()` falls back to `f"{alert_type.title()} alert"` for `GRAPH_CHANGE` and `CONTRADICTION` because those events have no `claim_type`/`polarity` payload (those are NLP-only fields). Replace the function with explicit per-type templates:

```python
def _compose_alert_title(
    *,
    signal_label: str,
    entity_name: str | None,
    ticker: str | None,
    alert_type: AlertType,
    is_signal_label_fallback: bool,
) -> str:
    """PLAN-0053 T-A-1-06: per-type templates ensure no 'X Alert' fallbacks."""
    subject = ticker or entity_name

    if alert_type == AlertType.SIGNAL:
        if not is_signal_label_fallback and subject:
            return f"{subject}: {signal_label}"
        if not is_signal_label_fallback:
            return signal_label
        return f"{subject}: Signal" if subject else "Signal detected"

    if alert_type == AlertType.GRAPH_CHANGE:
        template = "Graph pattern change"
        return f"{subject}: {template}" if subject else template

    if alert_type == AlertType.CONTRADICTION:
        template = "Conflicting signals"
        return f"{subject}: {template}" if subject else template

    return f"{subject}: Alert" if subject else "Alert"
```

**Tests to write** (replace `f"{alert_type.title()} alert"` assertions):
| Test | What it verifies | Type |
|------|------------------|------|
| `test_graph_change_with_ticker` | `GRAPH_CHANGE` + ticker=SPY → "SPY: Graph pattern change" | unit |
| `test_graph_change_no_subject` | No ticker/name → "Graph pattern change" | unit |
| `test_contradiction_with_entity` | `CONTRADICTION` + entity_name=Apple → "Apple: Conflicting signals" | unit |
| `test_signal_fallback_with_subject` | SIGNAL + fallback signal_label + ticker=AAPL → "AAPL: Signal" | unit |

**Downstream test impact**:
- `services/alert/tests/unit/test_alert_fanout.py` — assertions like `"GRAPH_CHANGE Alert"` must update
- `services/alert/tests/integration/test_alert_publish_flow.py` — DB assertions on `alerts.title`

**Acceptance criteria**:
- [ ] No alert created after deploy has title "Graph Change Alert" or "Contradiction Alert" (verify via DB query)
- [ ] All existing tests updated to new template strings
- [ ] No `is_signal_label_fallback` path produces the bare humanize fallback

---

### T-A-1-07 — Backfill existing NULL/generic alert titles

**Type**: schema
**depends_on**: T-A-1-06
**blocks**: none
**Target files**: `services/alert/alembic/versions/0008_backfill_alert_titles.py` (new), `services/alert/scripts/backfill_alert_titles.py` (new)

**What to build**:
Existing rows in `alerts` table have `title = NULL` or `title = 'Graph Change Alert'`. Write an Alembic migration (data migration, not DDL) that updates rows in batches using the same composition logic as T-A-1-06. Run it as part of deploy.

**SQL approach**:
```sql
UPDATE alerts SET title = (
  CASE
    WHEN alert_type = 'SIGNAL' AND signal_label IS NOT NULL AND COALESCE(ticker, entity_name) IS NOT NULL
      THEN COALESCE(ticker, entity_name) || ': ' || signal_label
    WHEN alert_type = 'GRAPH_CHANGE' AND COALESCE(ticker, entity_name) IS NOT NULL
      THEN COALESCE(ticker, entity_name) || ': Graph pattern change'
    WHEN alert_type = 'GRAPH_CHANGE' THEN 'Graph pattern change'
    WHEN alert_type = 'CONTRADICTION' AND COALESCE(ticker, entity_name) IS NOT NULL
      THEN COALESCE(ticker, entity_name) || ': Conflicting signals'
    WHEN alert_type = 'CONTRADICTION' THEN 'Conflicting signals'
    ELSE COALESCE(title, 'Alert')
  END
) WHERE title IS NULL OR title IN ('Graph Change Alert', 'Contradiction Alert', 'Signal Alert');
```

**Acceptance criteria**:
- [ ] Post-migration, zero rows in `alerts` have title matching `^[A-Z][a-z]+ [A-Z][a-z]+ alert$` (the humanize pattern)
- [ ] Migration is idempotent (re-running is a no-op)
- [ ] Migration tested in `services/alert/tests/integration/test_migrations.py`

---

### T-A-1-08 — ACK/snooze rollback on backend error

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/alerts/AlertsList.tsx:215-301`, `apps/worldview-web/hooks/useAlertActions.ts`

**What to build**:
Currently, `handleAck()` writes to localStorage immediately (optimistic), fires the gateway call, and ignores failures. On 5xx the localStorage stays acked while DB still shows pending → multi-device divergence. Add error rollback + user-facing toast:

```typescript
const handleAck = useCallback((alertId: string) => {
  // Optimistic
  setAcknowledged(prev => new Set(prev).add(alertId));
  saveLS(LS_ACK_KEY, ...);

  void alertActions.ack(alertId).then(res => {
    if (!res.ok) {
      // Rollback
      setAcknowledged(prev => { const n = new Set(prev); n.delete(alertId); saveLS(LS_ACK_KEY, ...); return n; });
      toast.error(res.error || "Failed to acknowledge alert");
    }
  });
}, [alertActions]);
```

Same pattern for `handleSnooze`.

**Tests to write**:
- `test_ack_rollback_on_500` — mock 500 response, assert state reverts and toast fires
- `test_ack_persists_on_2xx` — mock 200, assert state persists

**Acceptance criteria**:
- [ ] On backend 5xx, ACK state reverts within 1 frame
- [ ] Toast appears with error message
- [ ] No localStorage divergence between ack state and backend

---

### T-A-1-09 — Top-bar ticker collapse-to-dropdown on <1024px

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/shell/IndexTicker.tsx`, `apps/worldview-web/components/shell/TopBar.tsx:145-187`

**What to build**:
At viewport widths below `lg:` (1024px), pin only SPY inline; render the rest in a Popover triggered by a "+3" badge. Visible flow:
- `≥1024px` — full strip (current behavior)
- `<1024px` — `[SPY 580.21 ▲0.5%] [+3 ▾]` → popover lists VIX / QQQ / BTC

Also fix typography: ticker symbol bold-white (`font-bold text-foreground`); price+change colored only by daily return.

**Acceptance criteria**:
- [ ] Snapshot test @ 1280px: 4 tickers visible
- [ ] Snapshot test @ 768px: 1 ticker + dropdown trigger visible
- [ ] Click dropdown → popover with 3 tickers
- [ ] Symbol weight `font-bold`, color `text-foreground`; change color `[hsl(var(--positive))]` / `[hsl(var(--negative))]`

---

## Wave A — Pre-read

- `apps/worldview-web/components/instrument/OHLCVChart.tsx`
- `apps/worldview-web/components/portfolio/ExposureBreakdown.tsx`
- `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx`
- `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx`
- `apps/worldview-web/components/alerts/AlertsList.tsx`
- `apps/worldview-web/lib/alerts/format.ts`
- `services/alert/src/alert/application/use_cases/alert_fanout.py`
- `services/alert/src/alert/domain/enums.py`

## Wave A — Validation Gate

- [ ] ruff check passes on changed Python files
- [ ] mypy passes on `services/alert`
- [ ] Vitest passes for `apps/worldview-web` (added 9 new tests)
- [ ] `services/alert` unit tests pass (4 alert_fanout tests updated)
- [ ] Alembic migration 0008 runs cleanly forward + rollback
- [ ] Manual: instrument page chart loads without loop (Network tab shows 1 request)
- [ ] Manual: scroll to top of Holdings tab during initial load — no full-width black panel

## Wave A — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `services/alert/tests/unit/test_alert_fanout.py` | Title format strings change | Update assertions to new templates |
| `apps/worldview-web/__tests__/dashboard/RecentAlerts.test.tsx` | Default mock alerts assert on bare alert_type names | Update mocks to use new templates |
| `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx` (error message JSX) | Single-message renderer replaced | Use new typed error state |

## Wave A — Regression Guardrails

- **BP-291 (NEW)** — `h-full` loading skeleton in `min-h-*` parent produces black overlay. Documented in T-A-1-03.
- **BP-024** — Kafka consumer idempotency. T-A-1-07 backfill must be idempotent (`WHERE title IS NULL OR title IN (...)`).
- **BP-127 (forward-compat schema)** — T-A-1-06 changes only template strings, not the alert payload schema. No producer/consumer impact.
- **BP-235 (httpx asyncio timeout)** — N/A this wave.

---

# Wave B — Watchlist Backend + Holdings Widget Catalog

**Goal**: Complete the watchlist add-flow fix at the backend layer (search by name) + replace the under-utilized WatchlistMovers widget with HoldingsMovers + ship 3 high-value Holdings widgets.
**Depends on**: A
**Estimated effort**: 12h
**Architecture layer**: backend (S3) + frontend

## Tasks

### T-B-2-01 — S3 instrument search by `name` field

**Type**: impl + schema
**depends_on**: T-A-1-04
**blocks**: T-B-2-02
**Target files**:
- `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py:90-94`
- `services/market-data/alembic/versions/0010_add_instruments_name_trgm_idx.py` (new)
- `services/market-data/tests/integration/test_instrument_search.py`

**What to build**:
Extend the search SQL `or_()` clause to include `InstrumentModel.name.ilike(pattern, escape="\\")`. Add a Postgres `pg_trgm` GIN index on `instruments.name` for performance. Verify CREATE EXTENSION exists.

**Migration sketch**:
```python
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX CONCURRENTLY ix_instruments_name_trgm ON instruments USING gin(name gin_trgm_ops)")

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_instruments_name_trgm")
```

**Tests**:
- `test_search_by_company_name_apple` — query "apple" returns AAPL row
- `test_search_by_company_name_partial` — "micro" returns MSFT
- `test_search_case_insensitive` — "APPLE" / "Apple" / "apple" all match

**Acceptance criteria**:
- [ ] `GET /v1/search/instruments?q=apple` returns at least 1 row containing AAPL
- [ ] Index exists in DB (`\d ix_instruments_name_trgm` shows GIN trgm)
- [ ] Search latency p95 < 100ms with index (verify with explain analyze)

---

### T-B-2-02 — Frontend: remove uppercase normalization (name search now works)

**Type**: impl
**depends_on**: T-B-2-01
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx`

**What to build**:
Once name-search is live, remove the auto-uppercase from T-A-1-04. Users typing "apple" now match Apple Inc. Update the placeholder back to "Add ticker or company…". Keep the differentiated error messages.

**Acceptance criteria**:
- [ ] Typing "apple" returns Apple Inc.
- [ ] Typing "AAPL" still works
- [ ] Placeholder reads "Add ticker or company name…"

---

### T-B-2-03 — Holdings Movers widget (replace WatchlistMovers data source)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/dashboard/HoldingsMoversWidget.tsx` (new, can copy from WatchlistMoversWidget.tsx)
- `apps/worldview-web/lib/gateway.ts` (add `getHoldingsMovers` if backend endpoint missing)
- `services/api-gateway/src/api_gateway/routes/portfolio.py` (extend if needed)

**What to build**:
Reuse the WatchlistMovers UI but source data from the user's portfolio holdings instead of their watchlist. The composite `getWatchlistInsights` endpoint already exists; build a parallel `getHoldingsMovers` (or reuse with a `source=portfolio` query param). Default dashboard slot for the existing WatchlistMovers swap.

Top-5 gainers + top-5 losers from holdings · 1D / 1W / 1M period toggle · sector filter · alert dot + news count badges.

**Tests**:
- Unit: with 10 holdings (5 up, 5 down), top-5 each render correctly
- Unit: empty portfolio → empty state with CTA "Connect a brokerage"

**Acceptance criteria**:
- [ ] Replaces WatchlistMovers as the default dashboard widget
- [ ] WatchlistMovers remains accessible (e.g., as second tab) so users with hand-curated watchlists keep it
- [ ] All previous WatchlistMovers polish (sector pills, period toggle, badges) preserved

---

### T-B-2-04 — Cash Management mini-card

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/CashManagementCard.tsx` (new)

**What to build**:
Compact card on Holdings page showing: cash balance · % of total portfolio · sweep APY (if available from broker, else "—") · "Drag" indicator (if cash > 5% of portfolio for >30d, badge "Cash drag").

Data: `exposure.cash` field from `getPortfolioExposure()` (already exists).

**Acceptance criteria**:
- [ ] Card renders below KPI strip
- [ ] Cash %, value, sweep APY render correctly
- [ ] If APY null → "—" with tooltip "Sweep yield not available"

---

### T-B-2-05 — Recent Activity Feed widget

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/RecentActivityFeed.tsx` (new)

**What to build**:
Virtualized list of last 20 transactions + last 5 broker-sync events, merged + sorted by timestamp. Each row: icon (BUY ↑ / SELL ↓ / DIV $ / SYNC ⚙) · ticker · qty · price · timestamp.

Reuses `getTransactions()` + `getSyncStatus()`.

**Acceptance criteria**:
- [ ] List virtualizes (no DOM lag at 100+ rows)
- [ ] Sync events visually distinct from transactions
- [ ] Empty state: "No recent activity"

---

### T-B-2-06 — Dividend Income Timeline widget

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/DividendIncomeTimeline.tsx` (new)

**What to build**:
YTD dividend income, grouped by quarter, with bar chart. Per-ticker breakdown table below (sortable by total received). Reuses `getTransactions({ type: "DIVIDEND" })`.

**Acceptance criteria**:
- [ ] Quarterly bars render with tooltip showing $ amount
- [ ] Per-ticker table shows ticker · YTD total · annualized yield estimate
- [ ] Empty state: "No dividends received yet"

## Wave B — Validation Gate

- [ ] All Wave A criteria still pass
- [ ] `services/market-data` unit + integration tests pass
- [ ] New search-by-name integration test passes
- [ ] Vitest passes for 4 new components
- [ ] Manual: search "apple" in watchlist add → Apple Inc. visible

## Wave B — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `services/market-data/tests/integration/test_instrument_search.py` | New search field | Add new test cases (already in T-B-2-01 scope) |
| Frontend snapshot of dashboard | New widget swap | Update snapshot |

## Wave B — Regression Guardrails

- **BP-180** (asyncpg parameter casting) — N/A; trgm uses standard ILIKE.
- **BP-019** (migration server_default) — Migration is index-only, no NOT NULL columns added.
- **CREATE INDEX CONCURRENTLY** — required to avoid table lock on `instruments` (~4M rows).

---

# Wave C — Backend Data Gaps

**Goal**: Make Fundamentals and Predictions widgets actually display data on most tickers / categories. Surface coverage gaps to operators so they can be addressed proactively.
**Depends on**: none
**Estimated effort**: 18h

## Tasks

### T-C-3-01 — Per-field NULL logging in fundamentals backfill

**Type**: impl
**depends_on**: none
**blocks**: T-C-3-02
**Target files**: `services/market-ingestion/scripts/backfill_fundamentals.py`

**What to build**:
Currently the script logs aggregate counts only (ok / skipped / errors). Add structured per-field logging: for each ticker processed, emit a `structlog` event with the populated/null status of all 10 frontend-displayed fields (eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda, credit_rating). Add `--export-coverage=<path.csv>` flag that writes a per-ticker × per-field matrix.

**Acceptance criteria**:
- [ ] Running with `--export-coverage` produces CSV with rows = tickers, columns = fields, cells = "populated"/"null"/"error"
- [ ] Aggregate `field_population_pct` logged per field at end of run
- [ ] No change to actual snapshot data (logging only)

---

### T-C-3-02 — Fundamentals fallback provider (Alpha Vantage for eps_ttm + beta)

**Type**: impl
**depends_on**: T-C-3-01
**blocks**: T-C-3-03
**Target files**:
- `services/market-ingestion/src/market_ingestion/infrastructure/external/alpha_vantage_adapter.py` (new)
- `services/market-ingestion/scripts/backfill_fundamentals.py` (extend with fallback chain)

**What to build**:
Add a minimal Alpha Vantage adapter targeting only the 2 most-impactful fields (`EarningsShare` → eps_ttm, `Beta` → beta). When EODHD returns NULL for these fields, query Alpha Vantage. Track source per field in the snapshot row (`eps_ttm_source`, `beta_source` enum: `eodhd | alpha_vantage | none`).

**Schema change**: Alembic migration adds two TEXT columns (nullable, default 'eodhd') to `fundamentals_snapshots`. No NOT NULL.

**Tests**:
- Mock EODHD returns null + Alpha Vantage returns value → snapshot has value + source='alpha_vantage'
- Mock both return null → snapshot has null + source=NULL

**Acceptance criteria**:
- [ ] Coverage of `eps_ttm` improves (verified via T-C-3-01 export before/after)
- [ ] Source tracked in DB

---

### T-C-3-03 — Frontend: coverage-aware "—" rendering

**Type**: impl
**depends_on**: T-C-3-02
**blocks**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**:
For genuinely unavailable fields (e.g., credit_rating, which EODHD doesn't expose at all), render "n/a" with tooltip "Limited coverage — credit ratings not available from current data provider" instead of bare "—". For tickers with poor coverage, show a one-time banner at top: "Coverage for this ticker is limited (EODHD did not return X fields)."

**Acceptance criteria**:
- [ ] Fields known to be globally unavailable render as "n/a" with explainer tooltip
- [ ] Fields per-ticker null render as "—" (current behavior)
- [ ] Banner shows when >30% of fields are null for a ticker

---

### T-C-3-04 — Predictions: dynamic limit + improved categorization

**Type**: impl
**depends_on**: none
**blocks**: T-C-3-05
**Target files**:
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx:216`
- `services/content-ingestion/src/content_ingestion/domain/entities.py:378-399` (categorization)

**What to build**:

**Frontend**: Increase default `limit` from 8 → 25. When a category filter is active, pass `limit=50` to the backend so the per-category bucket is full.

**Backend**: Improve `category` extraction from Polymarket Gamma API:
- If `category` field is present → use it (current behavior)
- Else, walk the entire `tags` array (not just first), apply normalization:
  - "Politics" / "politics" / "POL" → "politics"
  - "Crypto" / "Cryptocurrency" / "DeFi" → "crypto"
  - "Sports" / "NBA" / "NFL" / "NHL" → "sports"
  - "Macroeconomics" / "Economy" / "Fed" / "Inflation" → "macro"
- Else, fall back to title-keyword heuristic (existing in `categorize` function on frontend — port to backend).

**Acceptance criteria**:
- [ ] Frontend filter "Macro" returns >5 markets when 30+ exist with macro keywords/tags
- [ ] "Other" bucket reduced from ~60% → <20% in DB (verify post-deploy with COUNT GROUP BY category)

---

### T-C-3-05 — Predictions: empty-state messaging + category counts

**Type**: impl
**depends_on**: T-C-3-04
**blocks**: none
**Target files**:
- `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx`
- `services/market-data/src/market_data/api/routers/prediction_markets.py` (new endpoint)

**What to build**:
Backend: Add `GET /v1/prediction-markets/categories` returning `[{category, count}, ...]` — counts per category for currently-open markets.

Frontend:
1. Display category counts on the filter pills: `[All 87] [Macro 12] [Politics 8] [Sports 5] [Crypto 41]`
2. When filter returns 0 results, render: "No markets in this category right now (only 2 macro markets available). Try 'All' or another filter."
3. Wrap "View all (N)" footer in a real `<Link href="/prediction-markets">` (create stub page).

**Acceptance criteria**:
- [ ] Pills show counts
- [ ] Empty state explains the universe size
- [ ] "View all" link navigates

## Wave C — Validation Gate

- [ ] EODHD adapter unit tests pass (no regression)
- [ ] Alpha Vantage adapter unit tests pass (new)
- [ ] `backfill_fundamentals.py --export-coverage` produces valid CSV
- [ ] `services/content-ingestion` tests pass
- [ ] `services/market-data` tests pass (new categories endpoint)
- [ ] Manual: filter Predictions by "Macro" → ≥5 markets show

## Wave C — Break Impact

| Broken file | Why | Fix |
|-------------|-----|-----|
| `services/content-ingestion/tests/unit/test_polymarket_categorization.py` | New category logic | Update fixtures to assert normalized output |
| `services/market-data/tests/integration/test_prediction_markets_api.py` | New /categories endpoint | Add tests |
| Frontend `PredictionMarketsWidget.test.tsx` | Counts on pills | Update mocks |

## Wave C — Regression Guardrails

- **BP-019** — Alembic migration adding `*_source` columns must have `server_default='eodhd'` on backfill, then drop default.
- **BP-235** — Alpha Vantage adapter must use `httpx.Timeout(...)` not just `asyncio.wait_for`.
- **R5 forward-compat** — adding nullable columns is forward-compatible.

---

# Wave D — Portfolio Enhancements

**Goal**: Close the remaining MAJOR portfolio findings: news widget filter/sort, transactions asset-type column, realized P&L history, plus polish.
**Depends on**: A
**Estimated effort**: 16h

## Tasks

### T-D-4-01 — Portfolio News widget filter + sort header

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/dashboard/PortfolioNewsWidget.tsx`

**What to build**:
Add a header strip with three controls:
- **Ticker filter** dropdown (All / specific holdings) — populated from portfolio
- **Sort** segmented buttons: `Impact ↓` (default) | `Date ↓` (toggle ascending/descending on click)
- **Tier filter** pills: `All · Light · Medium · High · Deep` (multi-select)

All filtering client-side (no extra API). Bump default `limit` from 4 → 20 so the buckets are full.

**Tests**:
- Filter by ticker AAPL → only AAPL articles render
- Sort Date ↓ → newest article first
- Toggle Date ↓ to Date ↑ → oldest first
- Multi-select tiers Light + Deep → only those tiers visible

**Acceptance criteria**:
- [ ] All controls wired to client-side filter/sort
- [ ] No additional API calls per filter change
- [ ] Empty state when filters yield 0: "No articles match these filters."

---

### T-D-4-02 — Transactions: asset_type column (backend + frontend)

**Type**: schema + impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/portfolio/src/portfolio/domain/entities/instrument.py` (add `asset_class` field)
- `services/portfolio/alembic/versions/0016_add_instruments_asset_class.py` (new)
- `services/portfolio/src/portfolio/infrastructure/external/snaptrade_adapter.py` (populate from sync)
- `apps/worldview-web/components/portfolio/TransactionsTable.tsx` (new column)

**What to build**:
Add `asset_class` enum column to `instruments` table (`equity | etf | option | future | bond | crypto | unknown`, default `unknown`). SnapTrade adapter populates from the broker response. Transaction-list endpoint joins instruments and includes asset_class. Frontend renders a small uppercase badge between Type and Ticker columns.

**Migration**:
```python
op.execute("CREATE TYPE asset_class AS ENUM ('equity','etf','option','future','bond','crypto','unknown')")
op.add_column('instruments', sa.Column('asset_class', sa.Enum(name='asset_class'), nullable=False, server_default='unknown'))
```

**Tests**:
- Adapter test: SnapTrade response with `instrument_type='ETF'` → asset_class='etf'
- API test: GET /v1/transactions returns asset_class per row
- Frontend snapshot: badge renders for each asset_class

**Acceptance criteria**:
- [ ] All instruments backfilled from SnapTrade have non-`unknown` asset_class for ≥90%
- [ ] Frontend badges render with distinct colors per class

---

### T-D-4-03 — Realized P&L historical chart

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/RealizedPnLChart.tsx` (new)

**What to build**:
PLAN-0051 Wave A shipped `getRealizedPnL` endpoint (FIFO accounting, full history). Build a chart on Holdings page below KPI strip showing cumulative realized P&L over time, with period toggle (1M / 3M / 6M / 1Y / All) and a per-ticker breakdown panel.

**Acceptance criteria**:
- [ ] Chart renders cumulative line across selected period
- [ ] Per-ticker breakdown table (top contributors / detractors)
- [ ] Empty state for new accounts

---

### T-D-4-04 — Sector treemap (replace 2-col list)

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: `apps/worldview-web/components/portfolio/SectorAllocationPanel.tsx`

**What to build**:
Current panel is a 2-column list. Replace with a treemap visualization (e.g., D3 treemap or `recharts` `Treemap`). Each tile sized by % of portfolio, colored by daily return (green/red gradient). Click → drill down to holdings in that sector.

**Acceptance criteria**:
- [ ] Treemap renders with proportional tiles
- [ ] Click drills down to filtered holdings table
- [ ] Empty state for no holdings

## Wave D — Validation Gate / Break Impact / Guardrails

- Wave A still passes
- Migration 0016 forward + rollback tested
- Frontend Vitest + Playwright pass
- BP-019 — server_default on new column required (set above)

---

# Wave E — Instrument Page Polish

**Goal**: Fix the secondary issues on the instrument page (overview black spaces, sidebar redesign, fundamentals enhancements, intelligence UI density, AI brief alignment).
**Depends on**: A
**Estimated effort**: 14h

## Tasks

### T-E-5-01 — Overview tab loading skeletons + empty states

**Type**: impl
**depends_on**: T-A-1-03
**Target files**: `apps/worldview-web/components/instrument/OverviewLayout.tsx`, `InstrumentKeyMetrics.tsx`, sparkline panels

**What to build**: Add explicit loading skeleton + empty-state cards to each sidebar zone. Ensure overflow-y-auto active. Apply BP-291 fix throughout.

---

### T-E-5-02 — Right sidebar 5-zone redesign (Overview / Competitors / News / Metrics / Sparklines)

**Type**: impl
**depends_on**: T-E-5-01
**Target files**: `apps/worldview-web/components/instrument/OverviewSidebar.tsx` (refactor)

**What to build**:
- Zone 1 (90px): Overview summary card — current price, 52W range bar, 3 badges (Mkt cap, P/E, Yield)
- Zone 2 (120px collapsible): Competitors — 3-5 peer tickers with relative valuations heatmap
- Zone 3 (140px collapsible): News — top 3-5 with sentiment pill + timestamp + "More news →" link
- Zone 4 (existing): Key Metrics scrollable
- Zone 5 (existing): 2 Sparkline panels

Backend: requires existing `getCompanyOverview` + `getInstrumentTopNews` (already wired). Add `getCompetitors(instrumentId)` if not present (likely exists via S7 KG).

**Acceptance criteria**:
- [ ] All 5 zones render with proper loading states
- [ ] Collapse/expand animates smoothly
- [ ] Right column never exceeds viewport (overflow-y-auto)

---

### T-E-5-03 — Fundamentals trend sparklines per metric

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/instrument/FundamentalsTab.tsx`

**What to build**: Add 10px-tall sparkline next to each major metric showing 5y trend (when historical data exists). Use existing `recharts` Sparkline.

---

### T-E-5-04 — Intelligence tab UI density redesign

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/instrument/IntelligenceTab.tsx`

**What to build**:
- Replace shadcn buttons with terminal-weight controls (`text-[10px] uppercase tracking-wider font-semibold`)
- Change `MarkdownContent size="comfortable"` → `size="compact"` (line 45) — fixes I-09
- Tighten card padding around the graph
- Contradiction cards: collapsed = single-line badge + headline, expanded card opens a side modal not in-place

---

### T-E-5-05 — News tab polish (source badges + narrative tags)

**Type**: impl
**depends_on**: none
**Target files**: `apps/worldview-web/components/instrument/NewsTab.tsx`

**What to build**:
- Source badge (2-letter monogram, e.g., "BB" / "ZK" / "MO") left of sentiment pill
- Narrative topic chips (Earnings / M&A / Regulation / Product / Macro) — tagged client-side from title keywords
- Filter persistence to sessionStorage

---

# Wave F — Secondary Pages Polish

**Goal**: Close the 21 polish findings from /alerts /chat /screener /settings /workspace /auth.
**Depends on**: none
**Estimated effort**: 10h

## Tasks (one per finding)

| Task | File | What to build |
|------|------|---------------|
| T-F-6-01 | `components/alerts/AlertsList.tsx` | Snooze duration Popover (15min / 1h / 4h / EOD) |
| T-F-6-02 | `app/(app)/alerts/page.tsx` | News-feed category filter localStorage persistence |
| T-F-6-03 | `components/alerts/AlertsList.tsx` | Bulk action toolbar (multi-select + ACK-all) |
| T-F-6-04 | `app/(app)/chat/page.tsx` | Slash command usage hint inline (`Usage: /quote {ticker}`) |
| T-F-6-05 | `app/(app)/chat/page.tsx` | Thread sidebar scroll position preservation |
| T-F-6-06 | `app/(app)/screener/page.tsx` | "Saved" toast on column preference save |
| T-F-6-07 | `app/(app)/screener/page.tsx` | Sparkline disabled tooltip explainer |
| T-F-6-08 | `app/(app)/settings/page.tsx` | "Coming soon" banner on uncontrolled notification toggles |
| T-F-6-09 | `app/(app)/settings/page.tsx` | Click-to-copy color palette swatches |
| T-F-6-10 | `components/workspace/WorkspaceTabs.tsx` | Fade-gradient on tab strip overflow |
| T-F-6-11 | `app/(app)/workspace/page.tsx` | `router.replace` instead of `window.location.reload` after import |
| T-F-6-12 | `app/login/page.tsx` | Tighten Dev Login probe (require both 502 AND missing env var) |
| T-F-6-13 | `app/callback/page.tsx` | Specific callback error messages (CSRF / network / token expiry) |

Each task is small (S/15-30min). Estimated 10h total with tests.

---

# Wave G — User Feedback Frontend (PLAN-0052 Wave E completion)

**Goal**: Ship the user-feedback frontend that PLAN-0052 backend (14 endpoints, 6 tables) is awaiting. Deliver a finance-pro feedback experience: floating widget + cmd+K + NPS + screenshot capture + public feature board + admin dashboard.
**Depends on**: none
**Estimated effort**: 16h
**Architecture layer**: frontend only (backend already shipped)

## Tasks

### T-G-7-01 — Extend gateway.ts with 8 feedback methods

**Type**: impl
**depends_on**: none
**blocks**: T-G-7-02..06
**Target files**: `apps/worldview-web/lib/gateway.ts`

**Methods to add**:
```typescript
postFeedbackSubmission(payload): Promise<FeedbackSubmission>
getFeedbackSubmissions(filters): Promise<FeedbackSubmission[]>
patchFeedbackSubmission(id, fields): Promise<FeedbackSubmission>
postNPS(payload): Promise<NPSScore>
getNPSAggregate(): Promise<NPSAggregate>
getFeatureRequests(filters): Promise<FeatureRequest[]>
postFeatureRequest(payload): Promise<FeatureRequest>
voteFeature(id): Promise<void>
postMicroSurvey(payload): Promise<void>
```

---

### T-G-7-02 — Feedback hooks (5 hooks in parallel)

**Type**: impl
**depends_on**: T-G-7-01
**blocks**: T-G-7-04..06
**Target files**: `apps/worldview-web/hooks/{useFeedbackSubmit,useNPSEligibility,useConsoleCapture,useFeatureRequests,useFeedbackSubmissions}.ts`

Each hook ~50-100 LOC. Standard TanStack Query patterns + validation. `useNPSEligibility` checks: auth + ≥3 sessions + no submission in 30d + per-quarter flag in localStorage.

---

### T-G-7-03 — Leaf components (4 components in parallel)

**Type**: impl
**depends_on**: T-G-7-02
**blocks**: T-G-7-04
**Target files**:
- `components/feedback/ScreenshotCapture.tsx` (html2canvas + blur tool + S3 upload)
- `components/feedback/ConsoleLogCapture.tsx`
- `components/feedback/NPSPrompt.tsx` (full-screen 0-10 number pad)
- `components/feedback/MicroSurvey.tsx` (inline 👍 👎 🤷)

Add npm dep: `html2canvas` (pinned exact version).

---

### T-G-7-04 — FeedbackModal (multi-tab form)

**Type**: impl
**depends_on**: T-G-7-03
**blocks**: T-G-7-05
**Target files**: `components/feedback/FeedbackModal.tsx`

shadcn Sheet + Tabs. Type selector (Bug / Feature / UX / Contact) → dynamic form per type. Wires into FB-09 hook.

---

### T-G-7-05 — FeedbackButton (floating widget) + entry points

**Type**: impl
**depends_on**: T-G-7-04
**blocks**: none
**Target files**: `components/feedback/FeedbackButton.tsx`, `app/(app)/layout.tsx` (mount), `components/shell/GlobalSearch.tsx` (cmd+K command)

Floating bottom-right 56px circle, mounts in app layout. Adds "Feedback" command to GlobalSearch cmd+K palette.

---

### T-G-7-06 — `/feedback` public board page

**Type**: impl
**depends_on**: T-G-7-02
**blocks**: none
**Target files**: `app/(app)/feedback/page.tsx`

Public-facing list of `is_public=true` feature requests. Sortable by votes / status / category. Vote button (idempotent). "Suggest a feature" CTA opens modal.

---

### T-G-7-07 — `/admin/feedback` dashboard page

**Type**: impl
**depends_on**: T-G-7-02
**blocks**: none
**Target files**: `app/admin/feedback/page.tsx`

Admin-only (route-guard via `useUserRole() === 'admin'`). Filterable virtualized table + bulk actions (assign, status, tags) + CSV export + NPS aggregate strip.

---

### T-G-7-08 — NPS triggers wired

**Type**: impl
**depends_on**: T-G-7-03
**blocks**: none
**Target files**: `hooks/useNPSEligibility.ts`, post-portfolio-sync handler, post-first-alert-trigger handler

Wire `NPSPrompt` to fire when:
- Eligibility check passes
- A "milestone" event occurs (e.g., portfolio sync success, first alert created)

Trigger surface tagged in `nps_score.surface` field for analytics.

## Wave G — Validation Gate

- 14 components/hooks tested (Vitest)
- E2E: open modal → submit bug → verify backend received it (mock)
- Manual: NPS only fires once per quarter

---

# Wave H — Responsive + A11y + Performance

**Goal**: Mobile/tablet support (deferred from Phase 4 per audit decision D-6), full WCAG 2.1 AA, and adoption of batch endpoints / cache-control headers across the codebase.
**Depends on**: A, B, C, D, E
**Estimated effort**: 20h

## Tasks

| Task | Theme | Files | Effort |
|------|-------|-------|--------|
| T-H-8-01 | Dashboard responsive (tablet stack @ 768px, mobile @ 480px) | `app/(app)/dashboard/page.tsx` + dashboard widgets | L |
| T-H-8-02 | Instruments responsive (sidebar collapse, metrics → tabs) | `app/(app)/instruments/[entityId]/` | L |
| T-H-8-03 | Screener responsive (table → card layout <768px) | `app/(app)/screener/page.tsx` | L |
| T-H-8-04 | Portfolio responsive (tabs → accordion, virtualized table) | `app/(app)/portfolio/` | L |
| T-H-8-05 | Workspace responsive (touch panel resize, drag-disable on mobile) | `app/(app)/workspace/page.tsx` + workspace components | M |
| T-H-8-06 | Playwright snapshot tests at 768px / 480px across all pages | `tests/e2e/responsive.spec.ts` | S |
| T-H-8-07 | WCAG contrast audit + fixes | tailwind classes, design tokens | M |
| T-H-8-08 | Keyboard navigation (tabindex, arrow keys on tables, Esc closes modals) | all interactive components | M |
| T-H-8-09 | ARIA labels sweep (img alt, button labels, live regions) | all components | M |
| T-H-8-10 | Batch endpoint adoption — replace per-row `getQuote` calls with `POST /v1/quotes/bars/batch` | dashboard, screener, watchlist | M |
| T-H-8-11 | Cache-Control headers verified on all GET endpoints | all S9 routers | S |
| T-H-8-12 | localStorage persistence sweep (filter/category state across pages) | alerts, screener, news, workspace | M |
| T-H-8-13 | Loading state sweep (Load More, copy hex, async actions) | all async UI | M |

## Wave H — Validation Gate

- Playwright snapshots @ 768/480 pass for all major pages
- axe-core accessibility scan reports 0 violations on dashboard / portfolio / instrument
- Lighthouse Performance score ≥ 85 on dashboard
- All WCAG contrast checks pass

---

## Plan-Level Risk Assessment

**Critical path**: Wave A. Without it, all chart/portfolio/alert pages remain broken; Waves B–E + H all depend on A.

**Highest risk**: T-A-1-06/07 (alert templates + backfill). Backfill SQL must be idempotent and not corrupt rows where backend already composed a good title (`WHERE title IS NULL OR title IN ('Graph Change Alert', ...)` is the safety guard).

**Rollback strategy per wave**: Each wave is a single squashed commit. `git revert <commit>` restores prior state. Migration 0008 (alert title backfill) and 0010 (instrument name index) are reversible.

**Testing gaps**:
- Chart loop is hard to write a deterministic unit test for — verify primarily via Playwright snapshot of one mount cycle + Network tab.
- Predictions universe expansion depends on Polymarket API behavior; can't fully unit-test categorization improvements without integration test against staging API.

---

## Cross-Cutting Concerns

**Contract changes**: None to Avro schemas. Only schema additions: `instruments.asset_class`, `instruments.name` index, `fundamentals_snapshots.{eps_ttm,beta}_source`, alert title backfill.

**Migration order**:
1. `services/alert/0008_backfill_alert_titles.py` (Wave A)
2. `services/market-data/0010_add_instruments_name_trgm_idx.py` (Wave B)
3. `services/portfolio/0016_add_instruments_asset_class.py` (Wave D)
4. `services/market-ingestion/00XX_add_fundamentals_source_columns.py` (Wave C)

**Event flow**: No new Kafka topics or schema changes.

**Configuration**: Wave C requires `ALPHA_VANTAGE_API_KEY` env var. Add to `services/market-ingestion/configs/dev.local.env.example`. Sync to worldview-gitops.

**Documentation**:
- `docs/services/alert.md` — title composition rules updated
- `docs/services/market-data.md` — instrument search now by name
- `docs/services/portfolio.md` — asset_class column documented
- `docs/services/market-ingestion.md` — Alpha Vantage fallback chain
- `docs/apps/worldview-web.md` — feedback widget + cmd+K command
- `services/*/.claude-context.md` — updates per service
- `docs/MASTER_PLAN.md` — note Phase 5 polish complete (after H lands)

---

## Suggested Execution Order

```
Day 1-2:  Wave A (gating)  ← all hands
Day 3:    Wave B starts (parallel: B + C)
          Wave C starts in separate worktree
Day 4-5:  Wave D + Wave E in parallel (depend on A)
Day 6:    Wave F (parallel; small tasks)
Day 7-8:  Wave G (parallel; feedback frontend)
Day 9-12: Wave H (depends on A,B,C,D,E)
```

Total: ~12 working days assuming 2 engineers.

---

## Open Questions for User

1. **Wave G open questions** (from feedback-system design) — needs user decision before Wave G can land:
   - Public vs private feature board? (recommend public)
   - Anonymous submissions allowed? (recommend yes, with email)
   - Auto-capture screenshot/console vs opt-in? (recommend opt-in for both)
   - NPS frequency? (recommend 1/quarter/user)
   - Slack/Discord webhook? (recommend defer)

2. **Wave C open questions**:
   - Add Alpha Vantage as fallback (free tier sufficient for ~25 calls/min)? Or pay for higher-volume provider?
   - Hide credit_rating field entirely (since no provider) or keep "n/a — not available"?

3. **Wave D**:
   - Asset_class enum: ship 7 values now (equity/etf/option/future/bond/crypto/unknown) or only 3 (equity/etf/unknown)? Backend SnapTrade can populate all.

4. **Wave H**:
   - Mobile = "fully usable" or "view-only with a 'desktop required for advanced features' banner"? (Audit recommendation D-6 was banner-only for thesis demo; this plan assumes full responsive.)

---

## Validation Sign-off (per wave)

Each wave must clear before merge:
- [ ] ruff + mypy clean
- [ ] Vitest passes (frontend) + pytest passes (backend)
- [ ] Architecture tests pass (`tests/architecture`)
- [ ] No new BUG_PATTERNS introduced (or new BP-XXX documented)
- [ ] Documentation updated per affected services/libs
- [ ] TRACKING.md row incremented (`Waves Done/Total`)

---

**Ready for `/implement PLAN-0053 Wave A`** once user confirms Open Questions answers.
