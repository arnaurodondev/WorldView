---
id: PRD-0089-W2-CORNERS
title: Wave 2 / F4 — Portfolio Overview — Corners & Edges Audit
status: pending-user-review
created: 2026-05-20
parent: docs/designs/0089/03-portfolio-overview.md
locked_by: _DECISIONS.md (F1 + F2 shipped; W1 in flight)
---

# Wave 2 (Portfolio Overview) — design clarity assessment + corners audit

## §A — Design clarity verdict

**Yes, the design is clear, with one of the strongest wireframes in the
corpus.** The doc has:

| Required | Present in `03-portfolio-overview.md` |
|----------|----------------------------------------|
| ASCII wireframe at 1440×900 | ✅ §4.1 — full top-to-bottom render: header strip → KPI 8-cell strip → exposure/currency strip → concentration strip → 120px performance panel → sector bar → table chrome → holdings table with example tickers AAPL/MSFT/NVDA/etc. → pinned TOTAL row → bottom contributors+activity strips |
| Grid description with px dimensions | ✅ §4.2 — every region with height + flex behaviour |
| Density target (counted cells) | ✅ §4.3 — 281 cells above the fold computed |
| Component breakdown with file paths + status (NEW/EXTEND/KEEP) + LOC budget | ✅ §5 — 13-component table |
| Visual spec (per-strip pixel spec + column widths + colour usage + hover + animation) | ✅ §6 (1300+ words) |
| Hotkeys + hover + click + loading + error + empty states | ✅ §7 (6 sub-sections, exhaustive) |
| Data fetching + network budget | ✅ §8 |
| Tradeoffs (Anchored Table vs Split Table — explicit rejection rationale) | ✅ §9 |
| Open questions | ✅ §10 (9 listed) |
| **Appendix A — column ordering rationale** | ✅ explicit five-cluster reading-order analysis |
| **Appendix B — five-second scan test** | ✅ acceptance criterion as a user-narrative |

This is the **most thoroughly specified page** in the design corpus.
No additional sketch needed.

The doc was written before F1 + F2 + W1 locked. Below are the corners
that need updating, plus genuinely new edges.

---

## §B — Coverage map (what the design doc already addresses)

| Concern | Covered by |
|---------|------------|
| 281-cell density target above fold | §4.3 |
| Holdings table 14 columns, exact widths summing to 1336px | §6.2 |
| ROOT-aware behaviour (overview applies to active portfolio whether ROOT or single) | §2 + §5 §5.1 hooks |
| Bloomberg PORT / IBKR / Schwab competitor distillation | §1 |
| Empty state — no brokerage + no portfolios | §7.6 |
| Sector "OTHER" bucket for cash/crypto | §10 OQ4 (locked answer) |
| Currency exposure top-2 inline + `+N more` popover | §10 OQ3 |
| Benchmark = SPY only v1 (matches DISCUSS-10 lock) | §10 OQ5 |
| AG Grid sparkline perf mitigation (single `path`) | §10 OQ7 |
| Sparkline batch endpoint hook | §5.2 |
| Top-movers client-side derivation v1, backend endpoint v1.1 | §10 OQ1 |
| Move-off list: HoldingLotsPanel, DayPnLDistribution, RealizedPnLSparkline, DividendYTDStrip, PositionBarHeat, PortfolioAnalyticsSection migrate to Holdings sub-tab | §5 |
| Hotkeys: `B/T/A/W/R/?/1-5/0/c/Esc` scoped to portfolio page | §7.1 |
| Five-second scan test pass criterion | Appendix B |

---

## §C — Corners missed / contradictions with locked decisions

Severity: **🔴 BLOCKING** (must fix before executor dispatch) ·
**🟡 IMPORTANT** (call out in plan) · **🟢 NICE** (defer if needed)

### Conflicts with F1 design system (already shipped)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-01 | **Row height 22px vs F1 lock 20px**. Wireframe + grid description both specify `[22]` for every row in the holdings table. F1 locked `--row-h: 20px` for `data-table-grid`. AG Grid's `rowHeight` config doesn't read CSS vars, so we pass `rowHeight={20}` explicitly. | 🔴 | Update §4 + §6 to 20px; pass `rowHeight={20}` to AgGridBase config |
| C-02 | **Sparkline 60×16 vs F1 primitive 40×16**. §5 + §6 specify 60px wide SPARK column. F1 `<Sparkline>` primitive uses 40×16 (set in `01-global-shell.md` watchlist + F1 §3.2). Reconcile: keep 60×16 in the holdings table (more horizontal space than the sidebar) OR cut to 40×16 for consistency. | 🟡 | Recommend: bump F1 `<Sparkline>` to accept `width` prop; portfolio uses `width=60`, watchlist uses `width=40`. Both 3-state trend-tinted per FU-5.6 |
| C-03 | **Sparkline 2-state stroke vs F1 3-state lock (FU-5.6)**. §6.3 colour usage says "stroke-positive (green) when 14-day return > 0; stroke-negative (red) when < 0". Flat case unspecified. F1 mandates 3-state (pos/neg/flat → muted-foreground). | 🔴 | Update §6.3 — add flat case (muted-foreground); use F1 primitive's `trend="auto"` mode |
| C-04 | **Row hover style** — §6.4 says `bg-muted/40 transition-colors duration-100`. F1 introduced a `.row-hover` utility (per FU-5 design system doc). Confirm utility exists and use it instead of inline classes. | 🟡 | Replace inline `bg-muted/40 transition-colors` with `<TableRow interactive>` or the `.row-hover` utility from F1 |
| C-05 | **Border-radius on KPI cells / strip dividers** — design doesn't explicitly call out radius, but existing `PortfolioKPIStrip` likely has `rounded-[2px]` somewhere. F1 banned all rounded. | 🟡 | Grep `components/portfolio/PortfolioKPIStrip.tsx` for `rounded-*` — strip; add to file ledger |
| C-06 | **Animation on equity curve** — §6.5 says "no animation". Good — matches F1 Tier-0. But `EquityCurveChart.tsx` is an existing component (lightweight-charts probably) — verify it doesn't animate on data update. | 🟡 | Plan §X: audit `PerformanceChartPanel.tsx` (new) — pass `animationsEnabled: false` to lightweight-charts options |
| C-07 | **Skeleton vs em-dash for cells** — §7.4 loading states say "skeleton rows" for the table. F1 lock: cell-level loading is "—" em-dash; table-level is skeleton. Both can coexist (skeleton row while count unknown, em-dash cell once row exists). | 🟢 | Document in §7.4 that "skeleton row" matches F1 `<LoadingSkeleton variant="table-row">` primitive |
| C-08 | **AssetTypeCellRenderer single-letter chip** — §5 specifies "E/F/B/C" (Equity/Fund/Bond/Crypto). F1 introduced `<SeverityCharBadge>` primitive (used for alerts). The asset-type chip is a similar single-char rendering — could reuse or fork. Decide whether to reuse the primitive or write a new `AssetTypeBadge` component. | 🟢 | Plan §X: reuse `<SeverityCharBadge>` API pattern (single-char + colour mapping) but ship a separate `<AssetTypeBadge>` component since semantics differ |

### Conflicts with F2 entity-id unification (shipped)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-09 | **Holdings row click target** — current `holdings-columns.tsx` likely uses `entity_id` for navigation. Post-F2 must use `ticker`. §7.3 click handlers don't specify URL form. | 🔴 | Update §7.3 — click on ticker cell → `router.push(\`/instruments/\${row.ticker}\`)` (NOT entity_id or instrument_id) |
| C-10 | **TICKER column already exists** — design doesn't note that the existing AG Grid has TICKER as pinned-left. F2 made the ticker the canonical URL component. Confirm `holdingsAgColumns` exports TICKER with `cellRendererSelector` or a custom renderer that wraps the ticker in a Link to `/instruments/{TICKER}`. | 🔴 | Plan task: refactor `ag-holdings-columns.tsx` TICKER column to render a `<TickerLink>` cell rendering `<Link href={\`/instruments/\${ticker}\`}>` |
| C-11 | **Sector clicking** — the SECTOR column shows "TECH/FIN/HC/CONS/ENG" abbreviations. Should clicking a sector cell filter the table by sector? Or navigate to a sector page? Design doesn't address. | 🟢 | Add to §7.3: clicking sector cell filters the table inline (no navigation). v1.1 may add a `/sectors/{name}` page |

### Conflicts with W1 (in flight) global shell

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-12 | **PortfolioSwitcher ownership** — W1 puts the PortfolioSwitcher chip in the TopBar (always visible, ROOT default). The design doc's §4.1 wireframe shows `[36] PORTFOLIO ▼ Main Book (USD)` as a separate header strip on the page itself. **Duplication**: do we have the switcher in BOTH TopBar AND page header? Reconcile. | 🔴 | Drop the inline portfolio dropdown from `PortfolioPageHeader`. Page just shows the static title "Portfolio" + secondary line ("14 positions · 1 owner · 1 broker"). Active portfolio is sourced from the W1 TopBar switcher via shared context |
| C-13 | **`▼ Main Book (USD)` selector in the page** — same issue: design predates W1 lock. The selector is removed (W1 owns it). The `(USD)` currency badge can stay as a static label next to the page title. | 🟡 | Update §4.1 wireframe and §5 PortfolioPageHeader to drop the dropdown |
| C-14 | **scope sub-line "1 owner · 1 broker"** — what backend field drives this? Possibly aggregated from `/v1/portfolios/{id}/details`. Verify endpoint surface. | 🟡 | Plan §X: confirm S1 returns owner_count + broker_count in some response (likely `summary` or a new `scope` field). If not, derive from existing data |
| C-15 | **+ ADD POSITION button** — §4.1 shows it in the page header. Already exists in current page.tsx. Where does it live post-redesign? Inside the new `PortfolioPageHeader` (right-aligned). Confirm. | 🟢 | Document in §5 PortfolioPageHeader description |
| C-16 | **DemoBadge** — W1 renders the DemoBadge in TopBar when active portfolio kind is "demo". Page header doesn't need to repeat. Confirm. | 🟢 | Add note in §4.1 wireframe |

### Conflicts with cluster decisions outside F1/F2/W1

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-17 | **Existing 4-tab page becomes overview-only** — current `app/(app)/portfolio/page.tsx` has 4 tabs: Holdings / Transactions / Watchlist / Brokerages. The new overview design is a single stacked column (no tabs). Where do the other 3 tabs go? Cluster 04 (Portfolio Detail) splits them across pages. Wave 2 must explicitly redirect / move. | 🔴 | Plan §X: Wave 2 makes `/portfolio` = overview (no tabs). The W1 stub `/watchlists` already exists. Transactions move to `/portfolio/transactions` (NEW page stub in Wave 2). Brokerages stays at `/portfolio/brokerage` (already exists). nuqs `?tab=` URL state retires |
| C-18 | **Cash row in holdings table** — current `CashRow.tsx` renders cash as a row in the holdings table. New design has CASH as a KPI cell. Does the holdings table still show cash as a row? Bloomberg PORT does. Per Appendix A column rationale, cash IS a position. Recommend: keep `CashRow` in the table AND show aggregated CASH in the KPI strip. | 🟡 | Add to §5: `CashRow` stays as a pinned-top row in the holdings table; KPI CASH cell is the same value, shown for at-a-glance scan |
| C-19 | **Existing components to delete** — design §5 lists 6 components that "move off the overview to the Holdings sub-tab" (HoldingLotsPanel, DayPnLDistribution, RealizedPnLSparkline, DividendYTDStrip, PositionBarHeat, PortfolioAnalyticsSection). Until cluster 04 (Portfolio Detail) ships, these belong on `/portfolio/analytics` or similar — but that page doesn't exist yet. Either Wave 2 ships a stub OR keeps them rendered on a "Holdings details" expandable below the table. | 🔴 | Plan §X: Wave 2 ships `/portfolio/analytics` route stub (similar to W1 `/watchlists` stub) so the move-off doesn't lose user data |
| C-20 | **`top-movers` computed client-side v1** — §10 OQ1 + §5.1 confirm. But the hook `useTopMovers` needs `holdings × quotes` joined. Current `usePortfolioData` already loads both. Verify joined data is accessible without a re-fetch. | 🟢 | Plan task: implement `useTopMovers` consuming `usePortfolioData().enrichedHoldings` |
| C-21 | **Risk metrics deferred to Holdings sub-tab** — §10 OQ2. But `PortfolioAnalyticsSection.tsx` is on the move-off list (C-19). Where does it live in Wave 2? On `/portfolio/analytics` stub. Confirm sub-tab won't 404 in v1. | 🟡 | Plan §X: `/portfolio/analytics` stub renders the existing `PortfolioAnalyticsSection` as-is (visual unchanged from current state) |

### Genuinely new edges (not yet identified anywhere)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-22 | **ROOT vs single-portfolio behaviour differences** — design implicitly assumes the page works for both. But: ROOT view aggregates across multiple portfolios; single-portfolio view shows one. Two specific differences: (1) `scope: 1 owner · 1 broker` becomes `scope: N owners · N brokers` for ROOT; (2) `+ ADD POSITION` is meaningless on ROOT (which portfolio to add to?). Design doc doesn't address. | 🔴 | Plan §X: when `activeIsRoot`, hide `+ ADD POSITION` button (or open a portfolio-picker modal). Update scope sub-line copy. Show `KIND: aggregated` indicator chip |
| C-23 | **Holdings duplicates across portfolios** — when ROOT aggregates, two portfolios may both hold AAPL. The aggregation logic in S1 already merges (per `list_by_portfolio_ids_aggregated_enriched`). But: the `lots` view (current `HoldingLotsPanel`) shows per-lot detail — across portfolios this becomes ambiguous (lot-1 in Portfolio A vs lot-1 in Portfolio B). Drill-down design for ROOT lot view is undefined. | 🟡 | Plan §X (acceptable v1 stance): when ROOT, drill-down shows per-portfolio split rather than per-lot. Lot detail only on single-portfolio drill-down |
| C-24 | **6-character ticker overflow** — `ANTHRO` in wireframe is fictional and 6 chars. Real example: `GOOG.L` (London listing) — also 6 chars. F1 / W1 watchlist allots 44px for ticker. Holdings table allots TBD — verify §6.2 column widths. Multi-class shares: `BRK.B` (5 chars) fits; `RDS.A` fits. 6+ chars: truncate with ellipsis OR widen column. | 🟢 | Plan §X: TICKER column 56px (vs W1's 44px) to fit 6 chars at mono 11px; document in §6.2 |
| C-25 | **`USDT` / `ANTHRO` token-style tickers** — design wireframe includes a fictional "ANTHRO" token. For crypto / private securities, what's the data source for sparkline + sector? Out of v1 scope per cluster decisions. | 🟢 | Plan §X: limit holdings table to instruments with `kind="financial_instrument"`; cash + private/crypto rows render with em-dashes for sparkline + sector |
| C-26 | **TOTAL row in AG Grid pinned-bottom** — current SemanticHoldingsTable already uses `pinnedBottomRowData`. Design specifies `+0.72%` total return on the TOTAL row. Verify the TOTAL row stays sorted-aware (pinned, not affected by user sort). | 🟢 | Document in §6 — TOTAL row honours `lockPinned` on the columns |
| C-27 | **Filter via "/" hotkey** — §4.1 wireframe shows `⎵ filter (press /)`. The W1 chord registry reserves `/` for global search (`shell.search.focus`). Conflict. | 🔴 | Update §7.1 — use `Ctrl+F` or `Cmd+F` for table filter; OR scope `/` to the portfolio table when focus is within it (requires explicit `<HotkeyScope scope="table" page="/portfolio">`) |
| C-28 | **Sort persistence** — current code persists sort + column state to localStorage per `HOLDINGS_COLS_KEY`. New design adds 2 columns (SPARK, ASSET). The localStorage schema is brittle: if existing key is read and has fewer columns than the new schema, AG Grid may break. Need a versioning strategy. | 🟡 | Plan §X: bump `HOLDINGS_COLS_KEY` to `holdings.col-state.v2`; gracefully fall back to default state when v1 key is read |
| C-29 | **Multi-tab localStorage sync** — Wave 1 added `storage` event listener for sidebar collapse. Holdings column state should also sync across tabs (same pattern). | 🟢 | Plan §X: extend the storage-event listener to also watch `holdings.col-state.v2` |
| C-30 | **PerformanceChartPanel benchmark line** — design shows SPY overlay. SPY is hardcoded per DISCUSS-10. The chart panel needs a hook that fetches the benchmark series (`/v1/instruments/SPY/ohlcv?range=...`). Confirm data source. | 🟡 | Plan §X: new `useBenchmarkSeries(period)` hook fetching SPY OHLCV; cache 30s. Verify endpoint shape against `00-backend-data-inventory.md` |
| C-31 | **Period selector on chart `[1W][1M][3M●][6M][1Y][All]`** — the active state `●` notation needs a clear visual treatment. Active = `text-primary border-b-2 border-primary` (matches InstrumentTabs from PLAN-0090). | 🟢 | Document in §6 |
| C-32 | **Refresh button on the page** — §7.1 lists `R = Refresh` hotkey. W1 added a global RefreshAllButton in the TopBar. Conflict? No — page-level `R` refreshes just the portfolio queries; global is in the TopBar. Document the distinction. | 🟢 | Add to §7.1: `R` is page-scoped; calls `queryClient.invalidateQueries({queryKey: qk.portfolios.all})`, not the global invalidate-all |
| C-33 | **Empty contributors / detractors** — when the portfolio has fewer than 4 holdings, the strip shows 4 slots. Design doesn't address. | 🟢 | Plan §X: `<ContributorsStrip>` renders only as many slots as there are positions; show "—" placeholder for empty slots if fewer than 4 |
| C-34 | **Recent Activity Feed source** — §4.1 shows transactions like "12:18 BUY AAPL 20 $214.30" and "09:30 SYNC Schwab ok". The SYNC event isn't a transaction — it's a brokerage-sync log. Two different sources. Design conflates them. | 🟡 | Plan §X: `<RecentActivityStrip>` shows transactions ONLY (no sync logs); sync status moves to a small badge in the page header or `/portfolio/brokerage` |
| C-35 | **Date format in recent activity** — design uses `12:18` for today, `Yest` for yesterday, no date for older. Bloomberg uses `T-1`, `T-2` for dates. Pick one convention. | 🟢 | Plan §X: use `12:18` (today), `Yest 09:30` (yesterday), `5d ago` (≤7d), then `Jan 12` (older) |
| C-36 | **Sparkline 14-day basis** — design specifies "14 daily closes". With `POST /v1/ohlcv/batch` (W1 sparkline endpoint) timeframe=`5m, limit=78` (intraday). For Holdings sparkline, design wants daily (`timeframe=1d, limit=14`). Confirm batch endpoint supports `1d` or use a separate query. | 🔴 | Plan §X: verify `POST /v1/ohlcv/batch` supports `timeframe=1d` (likely yes per inventory). Use `qk.instruments.ohlcvBatch(tickers, "1d", 14)` for holdings; differs from watchlist's `5m, 78` |
| C-37 | **AG Grid v35 cell-renderer perf budget** — §10 OQ7 mentions 420 DOM nodes (30 rows × 14 points). For ROOT view with 100+ positions: 1400 nodes. Performance test needed. | 🟡 | Plan §X: Playwright perf spec — load `/portfolio` with 100-row fixture; assert scroll is 60fps. If fail, fall back to canvas-rendered sparkline (single canvas per cell, not SVG) |
| C-38 | **Brokerage status banner** — current portfolio page has a brokerage-connection-status banner ("Last sync 3 min ago" / "Sync failed"). Design doesn't include it. | 🟡 | Add to §5: keep `BrokerageStatusBanner` (existing) above the KPI strip when active portfolio has a connected brokerage; collapses to nothing when no brokerage |
| C-39 | **Sticky behaviour at scroll** — header + KPI + exposure strips should stay sticky when the user scrolls the holdings table. Design §4.2 says "KPI strip + exposure + concentration always visible (no scroll inside)". But the page is `flex flex-col h-full overflow-hidden` — the holdings table scrolls inside its own pane (AG Grid manages this). Sticky is automatic. Confirm. | 🟢 | Document in §4.2 — sticky comes from the parent flex container; no `sticky top-0` needed on individual strips |

---

## §D — Cross-wave implications

1. **W1 must complete before Wave 2 dispatches**. The page consumes the TopBar PortfolioSwitcher — page mustn't ship its own duplicate selector.
2. **`/portfolio/transactions` stub route** must ship in Wave 2 OR cluster 04 (Portfolio Detail) wave. Without it, the existing nuqs `?tab=transactions` URL state has no destination.
3. **`/portfolio/analytics` stub route** must ship in Wave 2 OR cluster 04 wave. Houses the 6 moved-off components.
4. **F1 `<Sparkline>` primitive may need a `width` prop** so portfolio (60px) and watchlist (40px) can both use it. If F1 shipped 40px-only, this is a small F1.1 amendment.
5. **`HOLDINGS_COLS_KEY` localStorage version bump** is breaking for existing users. Pre-prod: no concern. Document for v1.1+.
6. **AG Grid 100-row perf canary** — if it fails, the sparkline column must move to canvas rendering. Decide v1 or v1.1.

---

## §E — Recommended Wave 2 plan structure

Mirroring F1 / F2 / W1 plan templates:

1. **Mission** — one sentence
2. **Bloomberg-grade resemblance checklist** — extends W1's: 14-column holdings, pinned TOTAL, sparkline column, KPI 8 cells, ROOT-aware UX
3. **Pre-flight checks** — F1 + F2 + W1 landed; F1 `<Sparkline>` has `width` prop (may require F1.1 amendment); existing `HoldingLotsPanel` etc. preserved
4. **Visual contract reference** — point to §4-§6 of design doc; list deltas (this audit)
5. **File-by-file change set**:
   - 5.1 EXTEND `PortfolioPageHeader.tsx` — drop dropdown (W1 owns it); scope sub-line ROOT-aware
   - 5.2 EXTEND `PortfolioKPIStrip.tsx` — 7→8 tiles (add CASH + BUYING PWR); drop any rounded
   - 5.3 NEW `ExposureCurrencyStrip.tsx` — single 22px row
   - 5.4 NEW `ConcentrationSectorTeaseStrip.tsx`
   - 5.5 NEW `PerformanceChartPanel.tsx` — 120px collapsible with SPY overlay; v1 `useBenchmarkSeries(period)` hook
   - 5.6 NEW `SectorAllocationBar.tsx` — single stacked-bar row
   - 5.7 NEW `HoldingsTableChrome.tsx`
   - 5.8 EXTEND `SemanticHoldingsTable.tsx` — add SPARK + ASSET cols; rowHeight 20; TICKER cell renders `<Link to ticker URL>`
   - 5.9 NEW `cells/SparklineCellRenderer.tsx` — consumes F1 `<Sparkline>` primitive with width=60, trend="auto"
   - 5.10 NEW `cells/AssetTypeBadge.tsx` — single-char chip (E/F/B/C)
   - 5.11 NEW `cells/TickerLink.tsx` — `<Link href={\`/instruments/\${row.ticker}\`}>` (F2 lock)
   - 5.12 NEW `ContributorsStrip.tsx`
   - 5.13 NEW `RecentActivityStrip.tsx`
   - 5.14 NEW `BrokerageEmptyState.tsx`
   - 5.15 NEW hook `useTopMovers.ts`
   - 5.16 NEW hook `useHoldingsSeries.ts` (uses `qk.instruments.ohlcvBatch(tickers, "1d", 14)`)
   - 5.17 NEW hook `useBenchmarkSeries.ts`
   - 5.18 EDIT `app/(app)/portfolio/page.tsx` — strip tab logic; nuqs key cleanup; ROOT-aware empty / no-brokerage state
   - 5.19 NEW stub route `app/(app)/portfolio/transactions/page.tsx` (TransactionsTable already exists; just route to it)
   - 5.20 NEW stub route `app/(app)/portfolio/analytics/page.tsx` (renders existing PortfolioAnalyticsSection)
   - 5.21 EDIT `ag-holdings-columns.tsx` — TICKER cell renders `<TickerLink>`; bump `HOLDINGS_COLS_KEY → v2`; add SPARK + ASSET cols
6. **Hotkey contract** — `B/T/A/W/R/1-5/0/c/Esc/Ctrl+F` (replace `/` per C-27); scope: page=`/portfolio`
7. **Tests** — unit per new component; Playwright for scroll perf + 5-second scan + ROOT-aware UX
8. **Acceptance criteria** — including: ROOT view renders aggregated rows; non-ROOT view shows `+ ADD POSITION`; 281-cell density verified
9. **Risk register** — AG Grid sparkline perf, multi-tab localStorage version bump, ROOT lot-drilldown ambiguity
10. **Estimation**: 5-7 engineer-days (was 4-5 in §D wave plan — adjusted for ROOT-aware corners + 2 new stub routes)

---

## §F — Final verdict

**Design is clear and unusually well-specified.** Wireframe + visual spec
+ column rationale + five-second-scan acceptance test are the strongest
in the design corpus. 39 corners identified, 9 BLOCKING — most are
mechanical alignments with F1 + F2 + W1 locks that postdate the original
design doc.

**Recommended next step**: write the Wave 2 plan with all corners baked
in, mirroring F1 / F2 / W1 plan structure. Then dispatch executor with
the matching prompt (container rebuild + deploy + short summary
included, per the convention established at W1).

Reply with `option B` (skip patching the design doc; jump to plan + prompt)
and I'll write both.
