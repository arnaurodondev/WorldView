---
id: PRD-0089-W2
title: Wave 2 — Portfolio Overview
prd: PRD-0089
order: W2 (second page wave — runs after F1 + F2 + W1)
status: ready-to-execute
created: 2026-05-20
platform_state: pre-production (no_backfill: true)
parent_design: docs/designs/0089/03-portfolio-overview.md
corners_audit: docs/designs/0089/oq/03-portfolio-overview-CORNERS-AUDIT.md
depends_on:
  - F1 (design system foundation) — `<Sparkline>` primitive, `<TableRow>`, `<EmptyState>`, `<LoadingSkeleton>`, F1.1 if Sparkline lacks `width` prop
  - F2 (entity ID unification) — `/instruments/{ticker}` routing
  - W1 (global shell) — PortfolioSwitcher in TopBar, `data-table-grid` opt-in pattern
unblocks:
  - Page 3 (Portfolio Detail / Holdings drilldown / Transactions ledger / Analytics)
---

# Wave 2 — Portfolio Overview (PRD-0089)

> **One sentence.** Replace the 4-tab portfolio page with a single
> overview view dominated by a 14-column holdings table (with sparkline
> + asset chip + ticker-URL navigation), surrounded by tight chrome
> (KPI 8-cell strip / exposure-currency strip / concentration strip /
> collapsible 120px performance chart with SPY benchmark / single
> stacked sector bar / bottom contributors + activity), all honouring
> F1 tokens (20px rows, no rounded, trend-tinted sparklines), F2
> routing (ticker URLs), and W1 architecture (TopBar
> PortfolioSwitcher owns active portfolio).

## 1. Bloomberg-grade resemblance checklist (acceptance signals)

| # | Test | Verify |
|---|------|--------|
| V1 | Density: 281+ visible data cells above the fold at 1440×900 | Playwright spec counts cells |
| V2 | Single overview (no tabs) on `/portfolio` | URL doesn't carry `?tab=...` |
| V3 | KPI strip 8 cells (TOTAL VALUE / DAY P&L / UNREAL P&L / REAL P&L YTD / CASH / BUYING PWR / TOP GAIN / TOP LOSE) | DOM inspection |
| V4 | Holdings table 14 cols with widths summing to 1336px (no horizontal scroll) | Computed style |
| V5 | Row height 20px (NOT 22px); rowHeight={20} passed to AgGridBase | AG Grid config + inspect |
| V6 | TICKER cell renders `<Link href="/instruments/{TICKER}">`; click navigates per F2 lock | Playwright spec |
| V7 | SPARK column uses F1 `<Sparkline>` primitive at width=60, trend="auto" (3-state per FU-5.6) | Source + DOM check |
| V8 | ASSET column shows single-char chip (E/F/B/C) via `<AssetTypeBadge>` | DOM |
| V9 | TOTAL row pinned at bottom (AG Grid `pinnedBottomRowData`), respects `lockPinned` on TICKER column | AG Grid inspect |
| V10 | Performance chart 120px, SPY overlay always (DISCUSS-10 lock), period selector [1W/1M/3M/6M/1Y/All] | DOM + interaction |
| V11 | PortfolioPageHeader has NO inline portfolio dropdown (W1 TopBar PortfolioSwitcher owns it) | grep + visual |
| V12 | Scope sub-line ROOT-aware: "All Portfolios · N positions · M owners · K brokers" vs "Main Book · ... · 1 owner · 1 broker" | Toggle ROOT in switcher, verify copy |
| V13 | `+ ADD POSITION` button hidden when active portfolio kind=root; shown otherwise | Toggle ROOT, verify |
| V14 | Sparkline data fetched via `qk.instruments.ohlcvBatch(tickers, "1d", 14)` (daily, not 5m) | Network tab |
| V15 | `/portfolio/transactions` stub route exists, renders existing `<TransactionsTable>` | curl 200 |
| V16 | `/portfolio/analytics` stub route exists, renders the 6 moved-off components (HoldingLotsPanel, DayPnLDistribution, RealizedPnLSparkline, DividendYTDStrip, PositionBarHeat, PortfolioAnalyticsSection) | curl 200 |
| V17 | Filter hotkey is `Ctrl+F` (NOT `/`, which is reserved for global search) | Press Ctrl+F on table — focuses filter input |
| V18 | Empty state when no portfolios AND no brokerage: full-page `<BrokerageEmptyState>` CTA | Mock empty state |
| V19 | Zero `rounded-(sm\|md\|lg\|xl\|2xl)` in `components/portfolio/` | grep |
| V20 | Zero `text-(sm\|base\|lg\|xl)` in `components/portfolio/` | grep |
| V21 | `HOLDINGS_COLS_KEY` bumped to `v2`; existing v1 keys gracefully fall back to default | localStorage inspect |
| V22 | `RecentActivityStrip` shows transactions only (no sync logs); sync moves to brokerage status banner | DOM |
| V23 | Brokerage status banner present above KPI strip when active portfolio has a connected broker | Toggle broker, verify |
| V24 | Five-second scan test (design doc Appendix B): a PM can answer 7 questions without scrolling/clicking | Manual eyeball |
| V25 | Container rebuilt and force-recreated; page renders at http://localhost:3001/portfolio | Curl 200 + visual |

## 2. Pre-flight checks (block dispatch if any fail)

1. **F1 + F2 + W1 landed**:
   - `git log --oneline | grep -c "feat(plan-0089-f1"` → 7+
   - `git log --oneline | grep -c "feat(plan-0089-f2"` → 14+
   - `git log --oneline | grep -c "feat(plan-0089-w1"` → 15+
2. **F1 `<Sparkline>` primitive has `width` prop** —
   `grep -E "width.*:.*number" apps/worldview-web/components/primitives/Sparkline.tsx`.
   If absent: F1.1 amendment first (~10 LOC; add `width` prop with default 40,
   verify watchlist call site passes `width={40}` explicitly).
3. **W1 PortfolioSwitcher in TopBar exists and writes active portfolio
   to a shared source** — verify `useActivePortfolio()` hook or
   equivalent. If W1 didn't export it: W2 reads from
   `usePortfolioData()` directly (existing hook).
4. **TanStack `qk.instruments.ohlcvBatch` already exists** (added in W1).
5. **Existing 4-tab page state** — verify `?tab=` URL param consumers
   are limited to `app/(app)/portfolio/page.tsx` (no external consumers).

If any pre-flight fails: report + stop. Do not branch.

## 3. Visual contract reference

See `docs/designs/0089/03-portfolio-overview.md`:
- §4.1 wireframe; §4.2 grid; §4.3 density; §5 component breakdown;
  §6 visual spec; §7 interaction model; Appendix A column ordering;
  Appendix B five-second scan test.

**Deltas from the design doc** (corners audit closes these):

| Design doc says | W2 ships | Reason |
|-----------------|----------|--------|
| Row height `[22]` everywhere | 20px (AG Grid `rowHeight={20}`) | F1 lock (C-01) |
| Sparkline 60×16, 2-state stroke | 60×16, 3-state trend-tinted via F1 `<Sparkline>` | F1 / FU-5.6 (C-02, C-03) |
| `PortfolioPageHeader` with inline `▼ Main Book (USD)` dropdown | Static title "Portfolio" + scope sub-line; W1 TopBar PortfolioSwitcher owns selection | W1 lock (C-12, C-13) |
| `(press /)` filter shortcut | `Ctrl+F` filter shortcut | W1 reserves `/` for global search (C-27) |
| TICKER cell — plain text | TICKER cell renders `<Link href={\`/instruments/\${ticker}\`}>` | F2 lock (C-09, C-10) |
| Sparkline series via `/v1/market/series/batch?...&days=14` | `qk.instruments.ohlcvBatch(tickers, "1d", 14)` via existing W1-introduced endpoint | reuse, no new endpoint (C-36) |
| `+ ADD POSITION` always visible | Hidden when active portfolio `kind === "root"` (ambiguous which portfolio to add to) | C-22 |
| Move-off components vanish | Render on `/portfolio/analytics` stub route (Wave 2 ships the stub) | C-19, C-21 |
| Transactions hidden after tab removal | `/portfolio/transactions` stub route renders existing `<TransactionsTable>` | C-17 |
| `RecentActivityStrip` shows transactions + sync events mixed | Transactions only; sync moves to `BrokerageStatusBanner` | C-34 |

## 4. File-by-file change set (one commit per step)

### 4.1 EXTEND — `features/portfolio/components/PortfolioPageHeader.tsx`
- Drop the inline portfolio selector dropdown (W1 TopBar owns it)
- Keep static title "Portfolio" + secondary line
- Scope sub-line ROOT-aware:
  - non-ROOT: `{portfolio.name} · {position_count} positions · 1 owner · {broker_count} brokers`
  - ROOT: `All Portfolios · {position_count} positions · {owner_count} owners · {broker_count} brokers`
- `+ ADD POSITION` button: hidden when `activeIsRoot === true`
- `⋯` overflow menu unchanged
- **Line budget**: keep ~120 LOC

### 4.2 EXTEND — `components/portfolio/PortfolioKPIStrip.tsx`
- 7 → 8 tiles. Add CASH + BUYING PWR (BUYING PWR = CASH for cash accounts in v1)
- Strip any `rounded-*` classes from cells; tile dividers via `divide-x divide-border-subtle`
- Tile height: `h-7` (28px); inner padding `px-2`
- Use F1 `<MetricCell>` for each tile (label 10px upper / value 11-13px mono)
- **Line budget**: existing ~150 LOC + 60 = ~210 LOC

### 4.3 NEW — `components/portfolio/ExposureCurrencyStrip.tsx`
- Single `h-[22px]` row merging existing `ExposureStrip` data + currency top-2
- Format: `EXPOSURE · INV $X (Y%) · CASH $Z (W%) · LEV 1.00× · β-ADJ 1.12 · CCY USD 92% · EUR 8% [+N more]`
- `+N more` opens 200px popover with full currency breakdown (FU-1.7 forward-compat)
- **Line budget**: 140

### 4.4 NEW — `components/portfolio/ConcentrationSectorTeaseStrip.tsx`
- Single `h-[22px]` row; merges existing `ConcentrationStrip` data + top-3 sector preview
- Format: `CONCENTRATION · HHI X [low/moderate/high] · Top-3 Y% · N names · Sector top: TECH X% · FIN Y% · HC Z%`
- **Line budget**: 130

### 4.5 NEW — `components/portfolio/PerformanceChartPanel.tsx`
- 120px tall (`h-[120px]`), collapsible via state
- Period selector [1W][1M][3M][6M][1Y][All]; active = `text-primary border-b-2 border-primary`
- Portfolio line (solid) + SPY benchmark (dashed) overlay
- `useBenchmarkSeries(period)` hook fetches SPY OHLCV
- lightweight-charts config: `animationsEnabled: false` (F1 Tier-0 lock)
- Collapsed state: row becomes `h-7` "PERFORMANCE ▶" (no chart visible)
- **Line budget**: 220

### 4.6 NEW — `components/portfolio/SectorAllocationBar.tsx`
- Single `h-[22px]` stacked horizontal bar
- Format: `SECTOR  ████████ TECH 38%  ████ FIN 17%  ███ HC 12% ...`
- Replaces existing 240px `SectorAllocationPanel` on the overview
- Cash + crypto bucketed under "OTHER" (locked per OQ4)
- **Line budget**: 110

### 4.7 NEW — `components/portfolio/HoldingsTableChrome.tsx`
- Single `h-[22px]` row: `POSITIONS — N · sort: Value ▼ · hidden: 0 · ⎵ filter (Ctrl+F)`
- Sort indicator reads from AG Grid column state
- Filter shortcut: pressing `Ctrl+F` focuses an inline search input
- **Line budget**: 90

### 4.8 EXTEND — `components/portfolio/SemanticHoldingsTable.tsx`
- Pass `rowHeight={20}` to AgGridBase config (was 22)
- Add 2 new columns: SPARK (60px) + ASSET (28px)
- Update column widths to sum to 1336px (`columnDefs` widths in
  `ag-holdings-columns.tsx`)
- Add `<HoldingsTableChrome>` above the grid
- Remove any `rounded-*` from cell renderers
- **Line budget**: +40 to existing ~600 LOC

### 4.9 EXTEND — `components/portfolio/ag-holdings-columns.tsx`
- Bump `HOLDINGS_COLS_KEY` from current to `holdings.col-state.v2` (C-28)
- v1 key gracefully falls back to default state on first read
- TICKER cell: `cellRenderer: TickerLink` (renders `<Link href={\`/instruments/\${row.ticker}\`}>`); preserve pinning + lockPinned
- Add SPARK column: `cellRenderer: SparklineCellRenderer`, width=60, sortable=false
- Add ASSET column: `cellRenderer: AssetTypeBadge`, width=28, sortable=true
- **Line budget**: existing ~400 LOC + 80 = ~480 LOC

### 4.10 NEW — `components/portfolio/cells/TickerLink.tsx`
- AG Grid cell renderer
- `<Link href={\`/instruments/\${params.value}\`} className="font-mono text-[11px] hover:text-primary">{params.value}</Link>`
- **Line budget**: 30

### 4.11 NEW — `components/portfolio/cells/SparklineCellRenderer.tsx`
- Consumes F1 `<Sparkline data={...} width={60} height={16} trend="auto" />`
- Reads series data from `useHoldingsSeries()` hook keyed by ticker
- Loading: empty SVG placeholder (avoids layout shift)
- Missing data: renders muted-foreground em-dash
- **Line budget**: 70

### 4.12 NEW — `components/portfolio/cells/AssetTypeBadge.tsx`
- Single-character chip: E (equity) / F (fund) / B (bond) / C (crypto) / O (other)
- Colour: muted-foreground default, primary if equity
- 12×16px footprint, font-mono 10px uppercase
- **Line budget**: 30

### 4.13 NEW — `components/portfolio/ContributorsStrip.tsx`
- `h-24` (96px), 3-cell grid: TOP CONTRIBUTORS / TOP DETRACTORS / RECENT ACTIVITY
- Each cell shows top-4 entries at 20px row height
- Empty slot renders "—" placeholder if fewer than 4 holdings (C-33)
- Period toggle (deferred — "today" only v1; period buttons disabled with
  tooltip "1D only — historical mover data coming soon")
- **Line budget**: 130

### 4.14 NEW — `components/portfolio/RecentActivityStrip.tsx`
- Last 8 transactions (no sync events — C-34)
- Format per row: `{time} {kind} {ticker} {qty} {price}` at 18px height
- Date format: `12:18` today / `Yest 09:30` yesterday / `5d ago` ≤7d / `Jan 12` older (C-35)
- **Line budget**: 90

### 4.15 NEW — `components/portfolio/BrokerageEmptyState.tsx`
- Full-page CTA when no portfolios AND no brokerage
- "Connect a brokerage" primary button → `/portfolio/brokerage`
- "Add a manual portfolio" ghost button → opens existing CreatePortfolioDialog
- **Line budget**: 80

### 4.16 NEW — `features/portfolio/hooks/useTopMovers.ts`
- Derives top-4 contributors + bottom-4 detractors from `enrichedHoldings × quotes`
- Pure compute, no extra fetch (uses `usePortfolioData().enrichedHoldings`)
- v1: today only (1D); period buttons disabled per design §10 OQ1
- **Line budget**: 80

### 4.17 NEW — `features/portfolio/hooks/useHoldingsSeries.ts`
- Fetches sparkline series for all holdings in one batch:
  `qk.instruments.ohlcvBatch(tickers, "1d", 14)` (C-36)
- staleTime: 15 min
- Returns `Record<ticker, number[]>` keyed for SparklineCellRenderer
- **Line budget**: 100

### 4.18 NEW — `features/portfolio/hooks/useBenchmarkSeries.ts`
- Fetches SPY OHLCV for the active period: `qk.instruments.ohlcv("SPY", period)`
- staleTime: 30s
- Returns `{data, isLoading, isError}` for `<PerformanceChartPanel>`
- **Line budget**: 60

### 4.19 EDIT — `app/(app)/portfolio/page.tsx`
- Strip ALL tab logic. No more `useQueryState` for `?tab=`
- Stack the components from §4.1-§4.15 in order per wireframe
- ROOT-aware empty state: `<BrokerageEmptyState>` when no portfolios + no brokerage
- Page state: only dialog open/close booleans + period selector (URL-backed via nuqs `?period=`)
- **Line budget**: dramatic reduction from current ~450 LOC to ~200 LOC

### 4.20 NEW STUB — `app/(app)/portfolio/transactions/page.tsx`
- Server component
- Renders existing `<TransactionsTable>` directly (no new UX in W2)
- Page header: "Portfolio · Transactions" with back link to `/portfolio`
- **Line budget**: 60 LOC stub

### 4.21 NEW STUB — `app/(app)/portfolio/analytics/page.tsx`
- Server component
- Renders the 6 moved-off components as-is:
  HoldingLotsPanel, DayPnLDistribution, RealizedPnLSparkline,
  DividendYTDStrip, PositionBarHeat, PortfolioAnalyticsSection
- Page header: "Portfolio · Analytics" with back link
- **Line budget**: 120 LOC stub

### 4.22 EXTEND — `components/portfolio/BrokerageConnectionCard.tsx` or NEW `BrokerageStatusBanner.tsx`
- Render brokerage sync status as a banner above the KPI strip when
  active portfolio has a connected brokerage
- "Last sync 3 min ago · OK" / "Sync failed — retry"
- Collapses to nothing (`h-0`) when no brokerage attached
- **Line budget**: 60 LOC (new component preferable; existing card stays for `/portfolio/brokerage` page)

### 4.23 EDIT — `lib/query/keys.ts`
- Add `qk.instruments.ohlcvBatch(tickers, timeframe, limit)` (if not already
  added by W1 — verify) and `qk.market.benchmarkSeries(ticker, period)`
- Use `QK_VERSION` prefix per F2

### 4.24 EDIT — `__tests__/architecture/no-off-palette-colors.test.ts`
- Add forbidden pattern: `rowHeight\s*[:=]\s*22` (catches 22→20 regression)

## 5. Hotkeys (page-scoped to `/portfolio`)

| Chord | Action |
|-------|--------|
| `B` | Back to dashboard (legacy — preserve) |
| `T` | Navigate to `/portfolio/transactions` |
| `A` | Navigate to `/portfolio/analytics` |
| `W` | Navigate to `/watchlists` |
| `R` | Page-scoped refetch (`queryClient.invalidateQueries({queryKey: qk.portfolios.all})`) |
| `1` `2` `3` `4` `5` | Toggle Performance chart period (1W/1M/3M/6M/1Y); `0` toggles `All` |
| `c` | Toggle Performance chart collapse |
| `Ctrl+F` / `Cmd+F` | Focus HoldingsTableChrome filter input |
| `Esc` | Clear filter; unfocus |
| `?` | Open HotkeyCheatSheet (global) |

Register inside `app/(app)/portfolio/page.tsx` via
`<HotkeyScope scope="page" page="/portfolio">` — auto-pops on unmount.

## 6. Tests

### 6.1 Unit
- `useTopMovers.test.ts` — derivation logic for both winners and losers
- `useHoldingsSeries.test.ts` — batch fetch + null fallback
- `useBenchmarkSeries.test.ts` — SPY-only v1
- `PortfolioKPIStrip.test.tsx` — 8 tiles render; CASH and BUYING PWR present
- `PerformanceChartPanel.test.tsx` — collapsed state; period change
- `TickerLink.test.tsx` — renders `<Link>` to `/instruments/{TICKER}`
- `SparklineCellRenderer.test.tsx` — em-dash fallback; trend-tinted colour
- `AssetTypeBadge.test.tsx` — 5 kinds (E/F/B/C/O)
- `ContributorsStrip.test.tsx` — fewer-than-4 holdings → "—" slots
- `RecentActivityStrip.test.tsx` — sync events filtered out

### 6.2 Playwright e2e
- `portfolio-overview-no-tabs.spec.ts` — visit `/portfolio`; assert no tabs
- `portfolio-overview-ticker-click.spec.ts` — click a holdings row → URL contains `/instruments/AAPL`
- `portfolio-overview-root-aware.spec.ts` — toggle ROOT in TopBar; `+ ADD POSITION` hidden
- `portfolio-overview-density.spec.ts` — count cells ≥ 281
- `portfolio-overview-perf.spec.ts` — 100-row fixture; scroll-fps ≥ 60 (sparkline perf canary, C-37)
- `portfolio-stub-routes.spec.ts` — `/portfolio/transactions` + `/portfolio/analytics` both 200

### 6.3 Architecture-test extensions
- Forbid `rowHeight: 22` regex
- Forbid `rounded-` in `components/portfolio/` (mirrors W1 pattern)

## 7. Acceptance criteria

All 25 V-gates from §1 plus:
| # | Gate | Verification |
|---|------|--------------|
| 26 | `pnpm --filter worldview-web typecheck` | 0 errors |
| 27 | `pnpm --filter worldview-web test --run` | All green |
| 28 | `pnpm --filter worldview-web build` | Succeeds |
| 29 | `pnpm --filter worldview-web lint` | 0 errors |
| 30 | grep -rE "rounded-(sm\|md\|lg\|xl\|2xl)" apps/worldview-web/components/portfolio/ | 0 results |
| 31 | grep -rE "text-(sm\|base\|lg\|xl)" apps/worldview-web/components/portfolio/ | 0 results |
| 32 | grep -rE "useQueryState.*tab" apps/worldview-web/app/\(app\)/portfolio/page.tsx | 0 results (tabs gone) |
| 33 | Architecture test passes with new `rowHeight: 22` forbidden pattern | grep + test |
| 34 | Container rebuilt; `/portfolio` renders the new layout | curl + visual |

## 8. Risk register

| Risk | Mitigation |
|------|------------|
| AG Grid sparkline column blows past 60fps with 100+ rows | Perf canary in §6.2; if fail, fall back to canvas-rendered sparkline (single canvas per cell). Defer to v1.1 if not blocking |
| F1 `<Sparkline>` lacks `width` prop → can't pass 60 | Pre-flight verifies; if absent, ship F1.1 amendment first (~10 LOC) |
| `HOLDINGS_COLS_KEY` v1 → v2 migration breaks existing dev sessions | Graceful fallback to default state on missing v2 key; pre-prod = no concern |
| Move-off components break when rendered on `/portfolio/analytics` stub (different parent context) | Stub passes same props as overview did; visual smoke confirms |
| `RecentActivityStrip` source change loses sync events users may want to see | Sync status moves to `BrokerageStatusBanner` (more prominent); document the migration |
| Performance chart benchmark series fails to load | Hook returns `isError`; chart renders portfolio line only (no overlay); no crash |
| ROOT view edge case: clicking `+ ADD POSITION` while it's hidden via keyboard nav | Defensively: button `disabled={activeIsRoot}` rather than removed from DOM, so keyboard nav skips it |

## 9. Files touched (consolidated)

```
NEW:
  components/portfolio/ExposureCurrencyStrip.tsx              (~140 LOC)
  components/portfolio/ConcentrationSectorTeaseStrip.tsx       (~130)
  components/portfolio/PerformanceChartPanel.tsx               (~220)
  components/portfolio/SectorAllocationBar.tsx                  (~110)
  components/portfolio/HoldingsTableChrome.tsx                  (~90)
  components/portfolio/ContributorsStrip.tsx                    (~130)
  components/portfolio/RecentActivityStrip.tsx                  (~90)
  components/portfolio/BrokerageEmptyState.tsx                  (~80)
  components/portfolio/BrokerageStatusBanner.tsx                (~60)
  components/portfolio/cells/TickerLink.tsx                     (~30)
  components/portfolio/cells/SparklineCellRenderer.tsx          (~70)
  components/portfolio/cells/AssetTypeBadge.tsx                 (~30)
  features/portfolio/hooks/useTopMovers.ts                      (~80)
  features/portfolio/hooks/useHoldingsSeries.ts                 (~100)
  features/portfolio/hooks/useBenchmarkSeries.ts                (~60)
  app/(app)/portfolio/transactions/page.tsx                     (~60 stub)
  app/(app)/portfolio/analytics/page.tsx                        (~120 stub)
  __tests__/portfolio/{many}.test.tsx                            (~10 unit tests)
  tests/e2e/portfolio-overview-{...}.spec.ts                     (6 specs)

EDIT:
  features/portfolio/components/PortfolioPageHeader.tsx          (drop selector; ROOT scope)
  components/portfolio/PortfolioKPIStrip.tsx                     (7→8 tiles; no rounded)
  components/portfolio/SemanticHoldingsTable.tsx                  (rowHeight=20; SPARK+ASSET cols)
  components/portfolio/ag-holdings-columns.tsx                    (TickerLink cell; KEY v2; new cols)
  app/(app)/portfolio/page.tsx                                    (-250 LOC tab logic; stack new components)
  lib/query/keys.ts                                                (ohlcvBatch + benchmarkSeries keys)
  __tests__/architecture/no-off-palette-colors.test.ts             (rowHeight regex)

NET LOC: roughly +1400 new, -250 from page.tsx tab logic. Net ~+1150 LOC.
```

## 10. Estimation

| Phase | Effort |
|-------|-------:|
| EXTEND PortfolioPageHeader + KPI strip | 0.5d |
| NEW ExposureCurrencyStrip + ConcentrationSectorTeaseStrip + SectorAllocationBar + HoldingsTableChrome | 1d |
| NEW PerformanceChartPanel + useBenchmarkSeries | 0.75d |
| EXTEND SemanticHoldingsTable + ag-holdings-columns (TickerLink, SPARK, ASSET) | 1d |
| NEW cell renderers (TickerLink, Sparkline, AssetTypeBadge) | 0.5d |
| NEW hooks (useTopMovers, useHoldingsSeries) | 0.5d |
| NEW ContributorsStrip + RecentActivityStrip + BrokerageEmptyState + BrokerageStatusBanner | 0.5d |
| EDIT page.tsx (strip tabs, stack components, ROOT-aware empty) | 0.5d |
| NEW stub routes `/portfolio/transactions` + `/portfolio/analytics` | 0.25d |
| Unit + Playwright tests (10 unit + 6 e2e) | 1d |
| Architecture-test extensions | 0.1d |
| Container rebuild + visual smoke | 0.25d |
| **Total single-agent serial** | **~6 days** |

## 11. Rollback plan

Per-PR (per §4 step) revert. The riskiest commit is §4.19 (page.tsx
strip-tabs); revert restores the 4-tab layout. Stub routes (§4.20-4.21)
can be deleted without affecting overview behaviour. AG Grid column
state bump is forward-only — revert restores `v1` key but existing v2
data is ignored (defaults applied).

## 12. Out of scope for Wave 2

- Period-aware top movers (1M/YTD) — backend endpoint v1.1 (§10 OQ1)
- Risk metrics (sharpe/vol/drawdown) on overview KPI — moves to Analytics sub-tab (§10 OQ2)
- Tall-mode equity chart (240px) — v1.1 (§10 OQ6)
- Per-firm benchmark selection — v1.1 (locked SPY-only per DISCUSS-10)
- CSV import for holdings — separate PRD
- Mobile responsive — FU-1.6 → v1.1
- Workspace integration (portfolio panel inside workspace) — v2

## 13. Definition of done

- All 34 acceptance gates pass
- Container rebuilt; `/portfolio` renders the new layout
- Page 3 (Portfolio Detail) is unblocked: `/portfolio/transactions` +
  `/portfolio/analytics` stubs hold the move-off components until they get
  proper redesign in the next wave
- Five-second scan test (design Appendix B) passes: PM can answer 7
  questions without scrolling/clicking
