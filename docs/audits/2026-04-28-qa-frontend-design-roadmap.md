# QA Report: Frontend Design Audit & Stabilization Roadmap

**Date**: 2026-04-28
**Skill**: `/qa`
**Scope**: Frontend design (all pages) + backend stabilization + new systems (landing, docs, feedback)
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: **FAIL** (1 BLOCKING + 6 CRITICAL frontend/backend defects; 70+ MAJOR enhancements queued)
**Report file**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md`

---

## Executive Summary

Six specialist agents audited the Worldview frontend in parallel: Dashboard, Portfolio, Instruments, Pre-alpha pages (Screener/Workspace/Alerts/Chat), Backend stabilization, and three new systems (Landing/Docs/Feedback). Total findings: **165** discrete issues across visual bugs, layout overflow, missing trader-grade features, broken backend flows, data-coverage gaps, performance bottlenecks, and absent product surface area (no instruments landing, no docs hub, no feedback system).

The product has a **solid Bloomberg/IBKR-grade design foundation** (12-col grid, Midnight Pro palette, IBM Plex typography, terminal density) but execution drift has accumulated: alerts render `"LOW signal"` instead of titles (backend schema lacks `title` column), the SnapTrade callback regressed for v4 portal (frontend rejects valid v4 redirects), holdings page has an empty black `min-h-[200px]` panel from `EquityCurveChart`, sector heatmap tiles overflow grid bounds via flex-basis rounding, instrument sidebar metrics are stubbed `—`, and the entity graph has zero hover affordances. Pre-alpha pages (Screener, Workspace, Alerts, Chat) all need P0 features before they are usable to a trader.

**Top 5 deployment blockers** (must fix this week):
1. **F-B-001 / F-P-009** SnapTrade v4 callback rejected by overly strict frontend guard (BLOCKING)
2. **F-B-002 / F-D-006** Alert schema lacks `title` column → `"LOW signal"` everywhere (CRITICAL)
3. **F-P-001** EquityCurveChart `min-h-[200px]` creates empty black panel mid-page (CRITICAL)
4. **F-D-002** Sector heatmap flex-basis cumulative-overflow on common viewports (CRITICAL)
5. **F-I-002 / F-I-003** Chart toolbar has 4 controls vs TradingView's 25; key-metrics sidebar stubbed (CRITICAL)

**The roadmap below sequences ~14–18 weeks of work into 5 phases**, with Phase 1 (Stabilization, 2 weeks) closing all BLOCKING/CRITICAL items and laying the foundation for the new Landing, Docs, and Feedback systems.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| Dashboard (D) | 17 widgets + TopBar | 30 | 0 | 2 | 4 | 21 | 3 |
| Portfolio (P) | 12 components + 2 pages | 28 | 1 | 3 | 3 | 18 | 3 |
| Instruments (I) | 24 components + 1 page | 35 | 1 | 3 | 16 | 15 | 0 |
| Pre-Alpha (X) | Screener/Workspace/Alerts/Chat | 37 | 0 | 5 | 16 | 14 | 2 |
| Backend (B) | 10 services | 15 | 1 | 1 | 8 | 5 | 0 |
| New systems | Landing/Docs/Feedback | 3 system designs | — | — | — | — | — |
| **Total** | — | **145 findings + 3 systems** | **3** | **14** | **47** | **73** | **8** |

### Cross-Agent Signals (HIGH Confidence — flagged by ≥2 agents)
- **Alert "LOW signal" bug** — flagged by Dashboard (F-D-006), Pre-Alpha (F-X-201), Backend (F-B-002, F-B-006). Root cause: alerts table has no `title` column; payload-derivation falls back to `"{severity} signal"` when claim_type/polarity missing.
- **AI brief format inconsistency** — flagged by Dashboard (F-D-001) and Instruments (F-I-004). Root cause: brief returned as raw markdown string; renderers diverged across surfaces.
- **SnapTrade callback rejected** — flagged by Portfolio (F-P-009) and Backend (F-B-001). Root cause: frontend guard requires 4 params; v4 portal sends 2.
- **Empty data fields** — Dashboard (F-D-006), Instruments (F-I-003/011/012/013/014/015), Backend (F-B-012). Root cause: fundamentals pipeline gaps + hardcoded `—` placeholders.
- **No batch endpoints / N+1 latency** — Dashboard (F-D-026), Backend (F-B-009, F-B-011). Root cause: per-symbol GETs.
- **Universe coverage too small (~80 symbols)** — Pre-Alpha screener (F-007/F-011), Backend (F-B-004). Root cause: static seed, no S&P 500 backfill.

---

## Severity & Effort Summary

| Severity | Count | S (≤2h) | M (2-8h) | L (1-3d) | XL (>3d) |
|----------|-------|---------|----------|----------|----------|
| BLOCKING | 3 | 2 | 1 | 0 | 0 |
| CRITICAL | 14 | 4 | 5 | 4 | 1 |
| MAJOR | 47 | 4 | 22 | 14 | 7 |
| MINOR | 73 | 41 | 25 | 6 | 1 |
| NIT | 8 | 8 | 0 | 0 | 0 |
| **Total effort** | — | **~120h** | **~270h** | **~360h** | **~270h** = **~1020h ≈ 14–18 weeks at 1 dev** |

---

# PART A — Findings by Area

## A.1 Dashboard (30 findings)

### CRITICAL — F-D-002: Sector Heatmap tiles overflow widget bounds
- **File**: `apps/worldview-web/components/dashboard/SectorHeatmapWidget.tsx:294-310`
- **Root cause**: `flex-basis: calc({weight*100}% - {GAP_PX}px)` accumulates float-rounding overflow; with 11 sectors at GAP_PX=4 + p-1, sub-pixel spillover crosses border at 1280px viewport.
- **Fix**: Reduce GAP_PX to 2, change padding to `px-0.5 py-0`, add `overflow: hidden` to container. Test all 11 GICS sectors at 1280/1440/1920px.
- **Effort**: S | **Backend dep**: NO

### CRITICAL — F-D-006: Recent Alerts shows "LOW signal" / "MEDIUM signal" instead of subject
- **File**: `RecentAlerts.tsx:69-85`, `AlarmsPanel.tsx:145-155`, `services/alert/src/alert/application/use_cases/alert_fanout.py:105-125`
- **Root cause**: `_derive_signal_label` falls back to `f"{severity} signal"` when claim_type/polarity missing; alerts table has no `title` column at all (verified in `alembic/versions/0001_create_alert_db.py:39-49`).
- **Fix (composite)**: (1) Add nullable `title VARCHAR`, `ticker VARCHAR(20)`, `entity_name VARCHAR(500)`, `signal_label VARCHAR(200)` columns to `alerts` via new Alembic migration. (2) Populate `alert.title` in `AlertFanoutUseCase.execute()` from signal_label/entity_name (e.g., `"AAPL: Bullish guidance"`). (3) Add `logger.warning("signal_label_fallback", ...)` so we measure the failure rate. (4) Frontend: prefer `alert.title` then `signal_label` then descriptive fallback (drop bare severity).
- **Effort**: M | **Backend dep**: YES (S10)

### MAJOR — F-D-001: AI brief expanded view plain & under-structured
- **File**: `MorningBriefCard.tsx:338-353`
- **Fix**: Wrap ReactMarkdown in styled container; use `[&_h2]:border-t [&_h2]:pt-2 [&_blockquote]:bg-muted/30 [&_blockquote]:pl-2`; cap line-length at 720px; section dividers via left border. Combine with **F-B-010** (return structured JSON `{headline, drivers, implications, citations}` instead of raw markdown).
- **Effort**: M | **Backend dep**: YES (S8 structured response)

### MAJOR — F-D-004: Watchlist Movers widget data-sparse / "useless"
- **File**: `WatchlistMoversWidget.tsx`
- **Fix**: Five enhancements gated on **F-B-007** new endpoint `GET /v1/watchlists/{id}/insights`:
  1. Per-watchlist 1D/1W/1M weighted return summary row
  2. Sector concentration mini-bar (Tech 45% | Finance 30% | Health 25%)
  3. News-of-the-day overlay icon on top movers (S6)
  4. Active-alert dot on members with triggered alerts (S10)
  5. Single-biggest-news callout above the gainers/losers
- **Effort**: L | **Backend dep**: YES (S9 + S6 + S10)

### MAJOR — F-D-008/009: Top bar metrics crammed; missing Ask AI button
- **File**: `TopBar.tsx:155-237`
- **Fix**: Wrap PORT/Day P&L/Total P&L in `<div class="flex items-center gap-1 px-2 rounded-[2px] bg-muted/20 border border-border/30">` for visual cluster. Insert `<AskAiButton>` opening Popover with text input + "Make bigger →" link to `/chat`. Use Server-sent quick-ask endpoint.
- **Effort**: L | **Backend dep**: NO (reuse existing `AskAiPanel.tsx`)

### MAJOR — F-D-026: Top bar P&L not real-time
- **Fix**: Hoist `usePortfolioMetrics()` into layout; reduce TanStack `refetchInterval` from 60s → 15s; (Wave 2) WebSocket portfolio-update stream from S9.
- **Effort**: L | **Backend dep**: Optional WS

### MINOR (sample, all 21 detailed in agent output)
- F-D-003: PortfolioSummary "+1 more → View all" overflow → add `truncate px-2`
- F-D-005: PredictionMarkets needs category filter pills (All / Macro / Politics / Sports / Crypto) — replace `econOnly` boolean with enum
- F-D-007: PortfolioNewsWidget hardcoded `limit:4` → fetch 15-20
- F-D-010: Extract `<PeriodSelector>` shared component (1D/1W/1M)
- F-D-011: Standardize widget inner padding to `px-3 py-2` to match `gap-3`
- F-D-012: WCAG check on positive/negative palette; consider `#3CC8A3` / `#FF6B63` for stronger contrast
- F-D-013: Centralize `<DashboardEmptyState>` component
- F-D-015: Mute flat sectors with `opacity-30` so movers dominate visually
- F-D-016/028: Add custom MDX renderers for table/code/pre
- F-D-017: Tailwind utility `.num-col { @apply font-mono tabular-nums; }`
- F-D-018: Responsive breakpoints below 1024px (currently broken)
- F-D-019: Data-freshness `<DataTimestamp>` component on all widgets
- F-D-022: Sector pill row overflow on col-span-5 → reduce padding/font-size
- F-D-025: Backport deep-link to AlarmsPanel (F-303 fix only landed in RecentAlerts)
- F-D-027: Global "Refresh All" button → `queryClient.invalidateQueries()`

### NIT
- F-D-014/020/021/023/024/029/030: skeleton stagger jitter, "vol" label noise, broken-link guard on entity linkification, sector-pill responsive, single-point sparkline placeholder, popover max-h, header `leading-none`

---

## A.2 Portfolio (28 findings)

### BLOCKING — F-P-009: SnapTrade v4 callback validator rejects valid redirects
- **File**: `apps/worldview-web/app/(app)/portfolio/brokerage/callback/page.tsx:93`
- **Root cause**: Guard requires `connectionId && authorizationId && userId && sessionId`. SnapTrade Connection Portal v4 omits `userId` and `sessionId` (commented in lines 70-78 but the guard wasn't relaxed). Backend (`brokerage_connections.py:152-167`) already handles missing fields correctly.
- **Fix**: Change guard to `if (!connectionId || (!authorizationId && !connection_id_snap))`. Add v4 test case to `__tests__/brokerage-callback.test.tsx` (currently always provides 4 params → false-PASS).
- **Effort**: S | **Backend dep**: NO

### CRITICAL — F-P-001: Black widget mid-page on Holdings tab
- **File**: `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx:81`
- **Root cause**: `min-h-[200px] bg-card` enforced unconditionally; when data is empty/loading the panel reserves 200px of solid bg-card → visually a "black widget".
- **Fix**: Conditional min-h: when data present `min-h-[200px]`, when empty render `<InlineEmptyState>` with `min-h-0 h-auto`; or use loading skeleton matching the chart's eventual aspect.
- **Effort**: S | **Backend dep**: NO

### CRITICAL — F-P-008: Black widget above watchlists tab
- **File**: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:187-190`
- **Root cause**: When `watchlists.length === 0`, the Tabs root renders with no TabsContent → empty void above the tab strip.
- **Fix**: Guard before render: if no watchlists, show `<InlineEmptyState message="No watchlists yet. Create one to start adding symbols.">` with a "Create" CTA. Optional: auto-create default "Watchlist" on first login.
- **Effort**: S | **Backend dep**: NO

### CRITICAL — F-P-010: DIVIDEND transactions show $0 (amount field empty)
- **File**: `TransactionsTable.tsx:191`, S1 SnapTrade adapter
- **Fix**: Verify SnapTrade adapter populates `amount` for DIVIDEND rows; ensure gateway TransactionListItem schema includes it. Add operator log on amount ≤ 0 for DIVIDEND. Possibly compute fallback from raw SnapTrade transaction.
- **Effort**: M | **Backend dep**: YES (S1)

### MAJOR — F-P-007: Transactions tab missing core trader filters
- **Fix**: Add (1) date-range picker, (2) ticker autocomplete filter, (3) market/exchange filter, (4) amount range slider, (5) CSV export, (6) pagination, (7) totals row (sum BUY cost / SELL proceeds / dividends), (8) free-text search.
- **Effort**: L | **Backend dep**: Maybe (export)

### MAJOR — F-P-011: Realized P&L only partial-closes
- **Fix**: Backend should expose `GET /v1/portfolio/realized-pnl` computing FIFO from full transaction history (including fully-closed positions). Frontend currently approximates via `(tx.price - avgCost) * qty` which loses fully-closed P&L.
- **Effort**: L | **Backend dep**: YES (S1)

### MAJOR — F-P-018: Missing institutional analytics
- **Fix list (XL, post-MVP)**: contribution attribution, realized vs unrealized split, drawdown chart, correlation matrix, dividend timeline, currency exposure, tax-lot view, position sizing risk panel.
- **Effort**: XL | **Backend dep**: YES (multiple S1 endpoints)

### Spacing & layout (F-P-002, F-P-005, F-P-006, F-P-015, F-P-019, F-P-026)
- ExposureBreakdown empty state not vertically centered
- Allocation rows `h-[18px]` vs holdings `h-[22px]` rhythm mismatch — pick one
- Equity curve missing 1D button (or document why) **and remove 1S/1W/1M from Holdings page header per user request** (separate from chart toggle)
- Sticky table header padding alignment
- Mobile safe-area `env(safe-area-inset-*)` on portfolio shell
- Cash/Invested segment colors not colorblind-safe

### MINOR/NIT (F-P-003/004/012/013/014/016/017/020/021/022/023/024/025/027/028)
Sort/period state not persisted across tab switches; risk-metrics responsive collapse; P&L tile zero vs null disambiguation; weight-bar flicker on quote refresh; sector bar a11y; empty-state copy guide; KPI tile padding variance; loading skeleton responsive; tooltip contrast; period selector documentation; divider consistency; search debounce; sort persistence; resolution badge timeout; zero-qty/price row de-emphasis.

---

## A.3 Instruments (35 findings)

### BLOCKING — F-I-001: Instruments landing page absent (or sidebar misroutes)
- **Fix**: Build `app/(app)/instruments/page.tsx` proper landing: search + popular-companies grid + sector entry tiles + recently viewed + top market movers + watchlist quick access + "or use Screener →" CTA. Verify Sidebar.tsx:49 routes correctly.
- **Effort**: M | **Backend dep**: NO (reuse existing endpoints)

### CRITICAL — F-I-002: Chart toolbar has only 4 controls; missing TradingView indicators + drawing tools
- **File**: `ChartToolbar.tsx:80-139`
- **Fix**: Add left-side vertical drawing palette (trend line, horizontal level, rectangle, arrow, fib retracement, parallel channel, text annotation). Top dropdown for indicators (RSI, MACD, Bollinger, ATR, Stochastic, OBV, VWAP, Volume MA20, Volume Profile). Use `lightweight-charts` series API for indicators; custom DOM overlay for drawing tools persisted in instrument-context state.
- **Effort**: L | **Backend dep**: NO

### CRITICAL — F-I-003 / F-I-011 / F-I-012 / F-I-013: Sidebar metrics stubbed (EPS/Beta/Volume/etc.)
- **Files**: `InstrumentKeyMetrics.tsx:159-184, 179-184, 216-221`
- **Fix**: Add `eps_ttm`, `beta`, `avg_volume_30d` to S3 Fundamentals schema; backfill via EODHD; wire S9 endpoint; remove hardcoded `—`. Document data-freshness footer (`Data as of 2:15p ET`).
- **Effort**: L | **Backend dep**: YES (S3, EODHD)

### CRITICAL — F-I-014 / F-I-015: Cash Flow + Debt/Credit sections empty
- **Fix**: Add `operating_cash_flow`, `capex`, `free_cash_flow`, `fcf_margin`, `interest_coverage`, `net_debt_to_ebitda`, `credit_rating` to Fundamentals schema and EODHD adapter.
- **Effort**: L | **Backend dep**: YES (S3)

### MAJOR — F-I-004: AI brief format diverges between InstrumentAISubheader and IntelligenceTab
- **Fix**: Replace plain `<p>` rendering at `InstrumentAISubheader.tsx:188` with the same ReactMarkdown configuration used at `IntelligenceTab.tsx:268`. Better: extract shared `<AIBriefRenderer>` and use everywhere (also dashboard MorningBriefCard) — closes F-D-001.
- **Effort**: S | **Backend dep**: NO

### MAJOR — F-I-005: Trend sparkline axes uninformative
- **Fix**: Add slim right YAxis (width=30, fontSize=8) with $X B labels; show year ticks at start/mid/end; tooltip already correct.
- **Effort**: M | **Backend dep**: NO

### MAJOR — F-I-006: News tab too plain
- **Fix**: Add relevance score gradient badge (0-1.0), sentiment pill (requires S6 sentiment field), market-impact pill (display_impact_score), entity chips, time grouping (TODAY / PAST 3 DAYS / PAST WEEK), source filter chips, sort dropdown (Relevance / Time / Impact). Rich `<ArticleCard>` with hover summary.
- **Effort**: L | **Backend dep**: YES (S6 sentiment)

### MAJOR — F-I-007: Entity graph has zero hover affordances
- **File**: `EntityGraphPanel.tsx:236-268`
- **Fix**: Add NodeTooltip + EdgeTooltip rendered at mouse position. Node: name, type, degree, recent news count. Edge: relation_type, weight, source citation. Use `pointer-events-none`. Sigma.js + Cytoscape both expose `tap`/`mouseover` events.
- **Effort**: M | **Backend dep**: NO

### MAJOR — F-I-008: Intelligence tab needs filter controls
- **Fix**: Toolbar above graph (h-9) with: depth slider (1-3 hops), relation-type multi-select chips (subsidiary/competitor/partner/supplier/executive/investment), entity-type filter (company/person/event/topic/geography), time-window filter (All/7d/30d/90d), layout selector (force/hierarchical/radial), confidence threshold slider.
- **Effort**: XL | **Backend dep**: Optional

### MAJOR — F-I-018: "Ask AI" button missing on Overview
- **Fix**: Floating bottom-right button → opens contextual chat panel with system prompt that injects ticker, current price, OHLCV last 30d, fundamentals, brief narrative, recent news. Re-use AskAiPanel.
- **Effort**: L | **Backend dep**: YES (S8 instrument-context)

### MAJOR — F-I-031 / F-I-032: Mobile responsiveness broken
- **Fix**: `grid-cols-[1fr_280px] md:grid-cols-1`; mobile expands header to 3 rows; metrics panel becomes a "Metrics" tab.
- **Effort**: M | **Backend dep**: NO

### MAJOR — F-I-033: No error boundary around dynamic-imported EntityGraph
- **Fix**: Wrap `next/dynamic` import with onError fallback; render `<GraphLoadError>` if WebGL/import fails.
- **Effort**: S | **Backend dep**: NO

### MAJOR — F-I-028: Right sidebar scrolls independently from left column
- **Fix**: Remove `overflow-y-auto` from right sidebar in FundamentalsTab; let entire page scroll together.
- **Effort**: S | **Backend dep**: NO

### MINOR (sample)
- F-I-009: Data freshness "as of" footer in metrics panel
- F-I-010: 52W bar vertical alignment in row 2
- F-I-016: Description expand animation jank
- F-I-017: LiveQuoteBadge invisible on fresh data — add 3px green dot
- F-I-019: Volume dropdown menu (Volume MA20, VWAP, Volume Profile, OBV)
- F-I-020 / F-I-021 / F-I-025: Keyboard nav for entity graph; ARIA labels on chart canvas; news date filter labelling
- F-I-022: Session stats strip cramped on mobile
- F-I-023: FundamentalSparkline `showAxis` prop incomplete
- F-I-024: Skeleton mismatched with 9-section layout
- F-I-026: Search debounce 400ms → 250ms
- F-I-027: OHLCV placeholder data flicker on timeframe switch
- F-I-029: Click-to-copy on ticker badge
- F-I-030: Stale-graph indicator after 24h
- F-I-034: News article opens new tab; offer "same tab" preference or modal preview
- F-I-035: Share/copy-link button on instrument header

---

## A.4 Pre-Alpha Pages (37 findings)

### Screener (12 findings)

#### CRITICAL — F-X-007: No fundamental filters (P/E, dividend yield, ROE, debt/equity, growth)
- **Fix**: Expand ScreenerFilterBar to a collapsible filter panel with sections: Valuation, Profitability, Growth, Leverage. Number range inputs map to S9 filter syntax (likely already supported). Without these, the screener is non-functional for serious users.
- **Effort**: L | **Backend dep**: YES (S9)

#### CRITICAL — F-X-011: Backend data gaps (REVENUE / BETA / PRICE / 52W / VOLUME columns show "—")
- **Fix**: Coordinate with S3/S9: ensure `POST /fundamentals/screen` joins live quote + week-52 range + 30d avg volume. If data unavailable, augment via secondary fetch in api-gateway.
- **Effort**: L | **Backend dep**: YES (S9)

#### MAJOR — F-X-001 / F-X-002 / F-X-003: Export, Saved Screens, Column Customization
- **Fix**:
  - **Export**: `[⬇ Export]` dropdown (CSV/Excel/PDF); papaparse + xlsx
  - **Saved Screens**: Save/Load named filter configs in localStorage (MVP) → S9 sync (Wave 2)
  - **Column Settings**: ⚙ icon → checklist of 12 columns + drag reorder; persist to localStorage
- **Effort**: M each | **Backend dep**: NO (MVP)

#### MAJOR — F-X-008 / F-X-009: Technical + News/Intelligence filters
- **Fix**: Sections "Technical" (above 50d MA, RSI band, volume vs avg, distance from 52W high/low) and "News & Signals" (news velocity 7d, controversy score, recent earnings, insider activity). Map to S9 syntax; client-side fallback if unsupported.
- **Effort**: M each | **Backend dep**: Maybe

#### MINOR — F-X-004: Inline mini-chart per row
- **Fix**: Add 13th CHART column (120px) with `<Sparkline>` of 30d closes; pre-fetch via batch endpoint.
- **Effort**: M | **Backend dep**: YES (batch OHLCV F-B-009)

#### MINOR — F-X-005 / F-X-006 / F-X-010 / F-X-012
Unsaved-changes dot indicator; live-preview count; pagination/load-more; "X of Y match" total-universe count (F-B-007 helps).

### Workspace (8 findings)

#### CRITICAL — F-X-101: Layout persistence not verified
- **Fix**: Confirm `WorkspaceContext.updateWorkspaceLayout()` is wired into `<PanelGroup onLayout>` callback and serializes to localStorage keyed by workspace ID.
- **Effort**: S

#### CRITICAL — F-X-102: Panel types may be stubs
- **Fix**: Audit each entry in PANEL_CATALOGUE: chart, watchlist, screener, alerts, fundamentals, news, graph, portfolio, brief, chat. Either fully implement or remove from catalogue (do not ship "Coming Soon" stubs). **F-X-106** chart widget is the most-likely stub.
- **Effort**: L

#### MAJOR — F-X-103: Symbol linking not functional
- **Fix**: Implement color-group symbol picker in panel header → SymbolLinkingContext.setSymbolForColor(); linked panels read `useSymbolForColor(panel.color)` → re-fetch.
- **Effort**: M

#### MAJOR — F-X-104: No templates
- **Fix**: "New from Template" with 4-5 presets: Day Trader (Chart+Alerts+News+Portfolio), Research (Fundamentals+Graph+Chat+Screener), Swing Trader (Chart+Watchlist+Screener), News Junkie (News+Alerts+Chat).
- **Effort**: M

#### MAJOR — F-X-105: No share-via-URL
- **Fix**: `[📤 Share]` button → base64-encode WorkspaceConfig → URL param. Decode on load.
- **Effort**: M

#### MINOR — F-X-107 / F-X-108: Add-Panel dialog stays open after add; no undo/revert.

### Alerts (8 findings — extends F-D-006 + F-B-002/003/006)

#### CRITICAL — F-X-201: "LOW signal" rendered (see F-D-006/F-B-002)

#### MAJOR — F-X-202: Severity normalization scattered → centralize in `lib/alerts.ts`

#### MAJOR — F-X-203: ACK/Snooze state localStorage-only → multi-device divergence
- **Fix**: S10 PATCH `/alerts/{id}/acknowledge`, schema field `acknowledged_at`, `snooze_until`. Frontend writes both LS + backend.
- **Effort**: M | **Backend dep**: YES (S10)

#### MAJOR — F-X-204: No alert history view
- **Fix**: Tab "History" + S10 `GET /alerts/history?severity&entity&from&to&status` paginated.
- **Effort**: M | **Backend dep**: YES

#### MAJOR — F-X-205: AlertDetailSheet has no suggested actions
- **Fix**: "View Instrument" / "Add to Watchlist" / "Set Alert Rule" / "Open in Chat" buttons.
- **Effort**: M

#### MAJOR — F-X-206: AlertRuleBuilder has no edit/delete (only create)
- **Fix**: Manage Rules dialog with edit/delete actions, wire `[⚙ Rules]` button.
- **Effort**: M

#### MAJOR — F-X-207: No channel preferences (in-app/email/push)

#### MINOR — F-X-208: No quiet hours / mute schedule

### Chat (9 findings)

#### MAJOR — F-X-304: Slash commands not implemented
- **Fix**: Parse `/portfolio`, `/quote SYM`, `/news SECTOR=tech`, `/watchlist NAME`, `/alerts`, `/screener` client-side; render structured cards inline.
- **Effort**: M

#### MAJOR — F-X-305: No markdown rendering (code blocks / tables / lists render as raw text)
- **Fix**: `react-markdown` with shared config (closes F-D-001/F-I-004 too); copy-button on code blocks.
- **Effort**: M

#### MAJOR — F-X-306: No inline charts in responses (XL, post-MVP)
- **Fix**: S8 returns `[CHART type=bar entities=AAPL,MSFT metric=revenue years=2020-2024]` annotation; frontend renders recharts bar chart.

#### MAJOR — F-X-301: No thread search

#### MINOR — F-X-302: Citation score visualization (red/yellow/green bar instead of bare %)

#### MINOR — F-X-303: Context-aware starter questions

#### MINOR — F-X-307 / F-X-308 / F-X-309: Rename threads; conversation export (PDF/MD); refresh entity-context badge

---

## A.5 Backend Stabilization (15 findings)

### BLOCKING — F-B-001: SnapTrade v4 callback regression (see F-P-009)

### CRITICAL — F-B-006: Alert signal_label silent fallback
- **File**: `services/alert/src/alert/application/use_cases/alert_fanout.py:105-125`
- **Fix**: Add structured warning log on fallback; investigate upstream NLP pipeline to fix root cause (claim_type/polarity not always emitted). Synthesize a label via knowledge-graph + entity name when signal claim missing.
- **Effort**: M | **Service**: alert

### MAJOR — F-B-002 / F-B-003: Alert schema lacks `title` + denormalized enrichment fields
- **Fix**: Alembic migration `0002_add_alert_enrichment.py` adds `title VARCHAR`, `ticker VARCHAR(20)`, `entity_name VARCHAR(500)`, `signal_label VARCHAR(200)` + indexes. Populate in AlertFanoutUseCase.
- **Effort**: M | **Service**: alert

### MAJOR — F-B-004: Universe coverage ~80 symbols → expand to S&P 500 + NDX-100 + Russell 1000 + sector ETFs + 20 crypto
- **File**: `services/market-ingestion/alembic/versions/0002_initial_seeds.py`
- **Fix**: New Alembic data migration `0012_expand_to_sp500_nasdaq100_plus.py`. T3 tier polling. Helper `scripts/seed_instruments.py` pulls live constituent CSV.
- **Effort**: M | **Service**: market-ingestion

### MAJOR — F-B-007: New endpoint `GET /v1/watchlists/{id}/insights`
- Returns: `{ members_count, movers:[{entity_id, ticker, 1d_return, 1w_return, 1m_return, is_top}], sectors:[{name, weight}], news:[...], alerts:[...] }`. Composes S1+S3+S6+S7+S10. Powers WatchlistMoversWidget redesign (F-D-004).
- **Effort**: L | **Service**: api-gateway

### MAJOR — F-B-008: Prediction Markets `?category=` filter
- **Fix**: Add `category` Query param + WHERE filter; powers F-D-005.
- **Effort**: S | **Service**: api-gateway + content-ingestion

### MAJOR — F-B-009: OHLCV bars fetched per-symbol → batch endpoint
- **Fix**: `POST /v1/quotes/bars/batch { symbols, interval, from, to }` parallelized fan-out, `Cache-Control: max-age=300`. Powers F-X-004 inline mini-charts and dashboard sparklines.
- **Effort**: M | **Service**: market-data + api-gateway

### MAJOR — F-B-010: AI brief format inconsistent end-to-end
- **Fix**: S8 returns structured JSON `{ headline, sections:[{title, bullets[]}], citations:[{title,url}] }`. Frontend renders deterministically. Closes F-D-001 / F-I-004.
- **Effort**: M | **Service**: rag-chat

### MAJOR — F-B-011: Quote batch may be sequential
- **Fix**: Audit `POST /quotes/batch` — verify parallelization; add `Cache-Control: max-age=60`.
- **Effort**: S–M

### MAJOR — F-B-012: Fundamentals pipeline empty fields
- **Fix**: Audit S2 → S3 fundamentals_loader; verify EODHD auth + rate limits; backfill top 50 symbols. Resolves F-I-003/011/012/013/014/015.
- **Effort**: M | **Service**: market-ingestion + market-data

### MINOR — F-B-005 / F-B-013 / F-B-014 / F-B-015
News default limit (`limit=10`) too low for briefings; brokerage sync error messages opaque; alert_id missing on legacy alerts breaks deep-links; v4 callback test fixture provides 4 params (false-PASS).

---

# PART B — Three New Systems (Strategic Roadmap Inputs)

## B.1 Enhanced Landing Page (System 1)

**Goal**: Compete with Bloomberg / IBKR / TradingView marketing sites.

**Sections (top → bottom)**:
1. Hero — "The intelligence layer for your portfolio" + animated terminal mock + Sign In / Watch Demo CTAs
2. Live data ticker strip — 4-6 mock tickers, pulsing live-dot, sector heatmap miniature
3. Differentiators 3-up — News Intelligence (impact scoring) · Knowledge Graph (entity relations) · Multi-source Aggregation
4. Workflow walk-through — 4 steps Discover → Analyze → Track → Act with screenshots
5. AI ask-anything demo — example question, citation-grounded answer
6. Feature parity table — Worldview vs Bloomberg vs IBKR vs TradingView vs Finviz
7. Trust strip — "Powered by EODHD · Finnhub · Polymarket · SEC EDGAR · Reuters"
8. Pricing — Free / Pro / Enterprise tiers, annual/monthly toggle
9. Testimonials — 2-3 placeholder thesis case studies
10. FAQ accordion — 8-10 Qs
11. Footer — docs link, status, security, legal

**Tech**: Server Component (zero JS), shadcn/ui only, Tailwind, IBM Plex.
**Effort**: 7-10 days (3-phase)

## B.2 Documentation Hub `/docs` (System 2)

**Architecture**: Next.js App Router `app/docs/[[...slug]]/page.tsx` + MDX in `content/docs/` + `next-mdx-remote` + `contentlayer` + `fuse.js` cmd-K search.

**Components**: DocsLayout · DocsSidebar · DocsTableOfContents · MDXContent · Callout · CodeBlock · DocsTabs · Steps · DocsBreadcrumb · DocsSearch · DocsFeedback · DocsFooter.

**Sidebar sections** (~12 top-level, ~50 leaf pages): Getting Started · Dashboard · Instruments · Portfolio · Screener · Alerts · Chat/AI · Workspace · Data Sources · API Reference · FAQ · Changelog.

**Packages**: `next-mdx-remote@^5`, `contentlayer@^0.3.4`, `remark-gfm`, `rehype-pretty-code`, `shiki`, `fuse.js`.

**Effort**: 7-10 days (3-phase)

## B.3 User Feedback Collection System (System 3)

**Multi-channel**:
- (a) Floating feedback button (bottom-right) → modal with type + textarea + screenshot (html2canvas) + console-log capture (PII-redacted)
- (b) NPS prompt (0-10) on triggers (post-action, 30-day check)
- (c) Contextual micro-surveys (👍/👎)
- (d) Beta program enrollment in Settings
- (e) Bug-report deep link `?feedback=bug&page=X`
- (f) Public roadmap `/feedback` with upvotable feature requests
- (g) Admin dashboard `/admin/feedback` with filters + tagging + CSV export + Linear/GitHub webhook

**Postgres tables**: `feedback_submissions`, `nps_scores`, `feature_requests`, `feature_votes`, `micro_survey_responses`, `beta_enrollments`. All tenant-scoped with RLS.

**Endpoints (12)**:
| Method | Path |
|--------|------|
| POST | `/v1/feedback/submissions` |
| GET / PATCH / DELETE | `/v1/feedback/submissions/{id}` (admin) |
| GET | `/v1/feedback/submissions` (admin filters) |
| POST | `/v1/feedback/nps` |
| GET | `/v1/feedback/nps/aggregate` (admin) |
| GET | `/v1/feedback/features` (public) |
| POST | `/v1/feedback/features/{id}/vote` |
| POST | `/v1/feedback/micro-survey` |
| GET / PATCH | `/v1/feedback/beta-program/enrollment` |

**GDPR**: PII regex blacklist, 90d screenshot TTL, 7d console-log TTL, right-to-be-forgotten anonymization.

**Effort**: 6-8 days (3-phase)

---

# PART C — Cross-Cutting Themes & Recommendations

## C.1 Architectural

1. **Centralize markdown rendering** — single `<MarkdownContent>` shared by AI Brief (dashboard, instrument, intelligence), chat responses, docs MDX. Pluggable component overrides (table/code/pre/links).
2. **Centralize empty/loading/error states** — `<DashboardEmptyState>`, `<InlineEmptyState>`, `<DataTimestamp>` components used across all widgets/pages.
3. **Centralize period selector** — `<PeriodSelector periods=['1D','1W','1M']>` shared component.
4. **Centralize alert severity normalization** — `lib/alerts.ts:normalizeAlertSeverity()`.
5. **Backend: alert schema needs `title` and enriched columns** — closes 4 findings (F-D-006, F-X-201, F-B-002, F-B-003) with one migration.
6. **Backend: structured JSON responses** instead of raw markdown for AI surfaces (F-B-010) — closes F-D-001 and F-I-004.

## C.2 Performance

1. Batch endpoints `POST /quotes/bars/batch` and verified `POST /quotes/batch` (F-B-009/011) cut N+1 latency on dashboard, watchlists, screener, holdings.
2. Cache headers (`Cache-Control: max-age=60` on quotes, `300` on bars) reduce gateway load.
3. Universe expansion (F-B-004) gated on T3 polling tier to avoid quota blowout.
4. Dashboard global "Refresh All" (F-D-027) via `queryClient.invalidateQueries()`.

## C.3 Accessibility (currently weak)

- WCAG contrast on positive/negative palette (F-D-012)
- Allocation/exposure bars rely on color alone (F-P-014/026)
- ARIA labels missing on chart canvas (F-I-021), entity graph (F-I-020), news date filter (F-I-025)
- Tabular-nums utility class (F-D-017) for column-shift jitter
- Mobile/responsive breakdowns at <1024px (F-D-018, F-I-031, F-I-032, F-P-019)

## C.4 Data Coverage

- Universe: 80 → 800+ symbols (F-B-004)
- Fundamentals: EPS / Beta / Volume / FCF / Interest Coverage / Credit Rating gaps (F-I-003/011/012/013/014/015 + F-B-012)
- Alert title + denormalized enrichment (F-B-002/003)
- News default limit (F-B-005)
- Sentiment + impact fields on RankedArticle (F-I-006)

---

# PART D — Phased Roadmap (14–18 weeks)

## Phase 1 — Stabilization (Weeks 1-2) — FIX ALL BLOCKING/CRITICAL

**Backend**
- [ ] F-B-001 / F-P-009 — SnapTrade v4 callback guard relaxed (S, 1d)
- [ ] F-B-002 / F-B-003 — Alert table migration + AlertFanoutUseCase title population (M, 2d)
- [ ] F-B-006 — Signal-label fallback logging + synthesis (M, 2d)
- [ ] F-B-009 — `POST /v1/quotes/bars/batch` (M, 2d)
- [ ] F-B-010 — Structured AI brief JSON response (M, 2d)

**Frontend**
- [ ] F-P-001 — Conditional `min-h` on EquityCurveChart (S)
- [ ] F-P-008 — Watchlist tab empty state guard (S)
- [ ] F-D-002 — Sector heatmap overflow fix (S)
- [ ] F-D-006 — Alert title fallback chain (S)
- [ ] F-D-003 — PortfolioSummary truncate (S)
- [ ] Remove 1S/1W/1M buttons from Holdings page header (per user)
- [ ] Centralize `<MarkdownContent>` + `<DashboardEmptyState>` + `<PeriodSelector>` + `<DataTimestamp>` (M, 3d)

**Test/QA**
- [ ] Add v4 callback test case (F-B-015)
- [ ] Verify TRACKING.md update

**Outcome**: Zero BLOCKING, zero CRITICAL. All test layers PASS. Production-deployable baseline.

## Phase 2 — Dashboard & Instruments Polish (Weeks 3-5)

- [ ] F-D-004 / F-B-007 — Watchlist Movers redesign + new insights endpoint (L)
- [ ] F-D-005 / F-B-008 — Prediction Markets category filter
- [ ] F-D-008 / F-D-009 — Top bar redesign + Ask AI button
- [ ] F-D-026 — Real-time portfolio metrics
- [ ] F-I-002 — Chart toolbar (indicators + drawing tools)
- [ ] F-I-003 / F-I-011-15 / F-B-012 — Fundamentals data backfill + sidebar metrics wired
- [ ] F-I-004 — AI brief renderer unified
- [ ] F-I-006 — News tab enhancements (sentiment/impact/filters)
- [ ] F-I-007 / F-I-008 — Entity graph hover tooltips + Intelligence tab filters
- [ ] F-I-018 — Ask AI on Overview
- [ ] All MINOR/NIT in dashboard + instruments (combined ~60h, parallelize)

## Phase 3 — Portfolio + Pre-Alpha Activation (Weeks 6-9)

- [ ] F-P-007 — Transactions filters + export
- [ ] F-P-010 — Dividend amount fix
- [ ] F-P-011 — Realized P&L (full FIFO)
- [ ] F-X-007 — Screener fundamental filters
- [ ] F-X-008 / F-X-009 — Screener technical + news filters
- [ ] F-X-001 / F-X-002 / F-X-003 — Export, Saved Screens, Column Customization
- [ ] F-X-011 — Screener data gaps backfill (depends on F-B-012)
- [ ] F-X-101 / F-X-102 — Workspace persistence + panel completion audit
- [ ] F-X-103 / F-X-104 / F-X-105 — Symbol linking, templates, share-via-URL
- [ ] F-X-203 / F-X-204 / F-X-205 / F-X-206 — Alert ACK sync, history, detail actions, rule manager
- [ ] F-X-304 / F-X-305 — Chat slash commands, markdown
- [ ] F-X-301 — Thread search

## Phase 4 — New Surfaces (Weeks 10-13)

- [ ] **System 1 — Landing page** redesign (3 phases, 7-10 days)
- [ ] **System 2 — Documentation hub** `/docs` (3 phases, 7-10 days; content writing in parallel)
- [ ] **System 3 — Feedback system** MVP (Phase 1 + 2, ~6 days; Phase 3 deferred)

## Phase 5 — Polish & Advanced Features (Weeks 14-18)

- [ ] F-B-004 — Universe expansion to S&P 500 + NDX-100
- [ ] F-P-018 — Institutional analytics (contribution, drawdown, correlation)
- [ ] F-X-306 — Inline charts in chat responses
- [ ] F-I-002 Wave 2 — Drawing tools persistence + custom indicators
- [ ] All remaining MINOR/NIT
- [ ] Accessibility full audit (WCAG 2.1 AA)
- [ ] Mobile responsive overhaul (F-D-018, F-I-031/032, F-P-019)
- [ ] Performance: cache layer audit, batch endpoint adoption
- [ ] Feedback system Phase 3 (Linear webhook, sentiment analysis, public roadmap)

---

# PART E — Test Execution

**Skipped this run** — scope is design audit + roadmap, not code changes. After Phase 1 fixes land, run full layer 1-7 test suite per `/qa` standard:

| Layer | Status |
|-------|--------|
| Architecture | NOT RUN (no architecture changes pending) |
| Lint (ruff) | NOT RUN |
| Type Check (mypy) | NOT RUN |
| Library Unit | NOT RUN |
| Service Unit | NOT RUN |
| Contract | NOT RUN |
| Integration | NOT RUN |
| E2E | NOT RUN |
| Frontend Unit | NOT RUN |
| Frontend E2E | NOT RUN |

**Required after Phase 1 fixes**: full test pass + new tests for SnapTrade v4 callback (F-B-015), alert title population, structured brief schema.

---

# PART F — Decisions Needed (User Input)

Before starting Phase 1, please confirm:

| ID | Question | Recommended | Rationale |
|----|----------|------------|-----------|
| D-1 | AI brief: structured JSON (F-B-010) or keep markdown? | **Structured JSON** | Deterministic rendering, eliminates F-D-001/F-I-004 |
| D-2 | Universe expansion: S&P 500 only or full Russell 1000? | **S&P 500 + NDX-100 + sector ETFs** (~600) | Quota-safe, covers user expectation of "+500 companies" |
| D-3 | Feedback system: new `feedback` service or extend api-gateway? | **Extend api-gateway** | Single tenant, low volume, avoids new service overhead |
| D-4 | Holdings page: delete 1S/1W/1M (user request) or keep 1D/1W/1M only on equity curve? | **Delete from page header; keep on equity curve only** | Matches user request precisely |
| D-5 | Workspace stub panels: ship with "Coming Soon" or remove from catalogue? | **Remove until ready** | Stubs damage product perception |
| D-6 | Mobile support: full redesign or "desktop-only with mobile warning"? | **Desktop-only + warning page** for thesis demo; full redesign in Phase 5 | Trader workflows are desktop-native |

---

# Compounding Updates

After this audit, the following knowledge-base updates are recommended:

- **`docs/BUG_PATTERNS.md`**: Add BP-260 (alert schema lacks `title` causing severity-fallback in UI) and BP-261 (frontend callback guards must mirror backend optionality for OAuth v3/v4 forward-compatibility).
- **`.claude/review/checklists/REVIEW_CHECKLIST.md`**: Add "every alert/event display field has a meaningful fallback that doesn't reveal internal taxonomy (severity/status enums)".
- **`.claude/review/heuristics/HIGH_RISK_PATTERNS.md`**: Add "Hardcoded `—` placeholders in production data fields → must trace to backend schema/data gap and resolve before merge".
- **`docs/ui/DESIGN_SYSTEM.md`**: Add shared component spec for `<DashboardEmptyState>`, `<PeriodSelector>`, `<DataTimestamp>`, `<MarkdownContent>`.
- **`CLAUDE.md`**: Add note "frontend OAuth callback guards must use `||` between mandatory params and `??` between optional params; mirror backend optionality".

---

**End of report.**

Total findings: 145 + 3 system designs.
Recommended next: Begin Phase 1 stabilization. Confirm decisions D-1 through D-6 before kickoff.
