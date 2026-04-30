# QA Report — Frontend Deep Audit & PLAN-0053 Roadmap

**Date**: 2026-04-29
**Skill**: qa
**Scope**: PLANS 0049 / 0050 / 0051 / 0052 + full frontend surface
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: **FAIL — 4 CRITICAL + 11 MAJOR + 21 MINOR** outstanding live-UI issues despite TRACKING.md showing all four plans SHIP'd
**Report file**: `docs/audits/2026-04-29-qa-frontend-deep-audit-and-roadmap.md`

---

## Executive Summary

The user reported that despite PLANS 0049–0052 having been QA'd to SHIP verdicts, the live UI still has many gaps and several flat-out broken behaviors. To validate this claim, we dispatched **6 parallel investigation agents** across the frontend surface (dashboard widgets, portfolio pages, instrument page, secondary pages, feedback system design, and a cross-check against the original `2026-04-28-qa-frontend-design-roadmap` audit).

**Key finding**: All 47 items in the original roadmap audit were fully scoped into PLANs 0049–0052 and shipped. **The user-reported gaps are real and break the world-class UX bar — but they are not omissions from those plans**. They fall into five categories:

1. **Task scope creep at the wave level** — e.g., "fix watchlist black widget" was scoped only as an empty-state guard, not as full watchlist CRUD. The delete button and add-to-watchlist flow were never in scope.
2. **Pre-existing bugs not in the original roadmap** — e.g., the instrument chart infinite-scroll loop, the holdings z-index bug, and ACK/snooze multi-device divergence are bugs not previously documented.
3. **Downstream data-quality gaps** — fundamentals are still `—` on many tickers because the EODHD adapter has gaps; Predictions filter is "broken" because the universe of markets is too small (~80) for any category to fill 3 slots.
4. **Misclassified work** — Portfolio News widget filters were assumed to belong on the instrument-page News tab; they were never planned for the dashboard widget.
5. **Deferred work explicitly punted to Phase 5** — mobile responsive, institutional analytics, drawing-tool persistence.

This report consolidates 36 distinct findings, proposes specific fixes, designs the user-feedback system that PLAN-0052 backend is awaiting, and outlines a 7-wave PLAN-0053 to close all gaps and deliver a Bloomberg-grade experience.

**Most user-impacting items requiring immediate attention** (Wave A of PLAN-0053):

1. Watchlist add/delete flow broken (`P-04`) — blocks core portfolio workflow
2. Instrument chart infinite past-scroll loop (`I-03`) — instrument page unusable
3. Alerts with title "Graph Change alert" (`D-05`) — no fallback templating
4. Holdings z-index bug (`P-01`) — visual defect on every load
5. Top-bar tickers compress on narrow screens (`D-01`) — desktop-mid breakpoint broken

---

## Multi-Agent Coverage

| Agent | Focus | Findings | CRIT | MAJOR | MINOR |
|-------|-------|----------|------|-------|-------|
| Dashboard & Top-Bar | top bar, movers, predictions, news, alerts | 5 | 1 | 2 | 2 |
| Portfolio Section | holdings, transactions, watchlists, widget catalog | 7 (incl. 12-widget catalog) | 0 | 3 | 4 |
| Instrument Page | routing, chart, overview, fundamentals, news, intelligence, AI brief | 9 | 1 | 4 | 4 |
| Other Pages Sweep | alerts, chat, news redirect, screener, settings, workspace, auth | 21 | 1 | 4 | 16 |
| Feedback System Design | inventory + design + 14 frontend tasks | — | — | — | — |
| Roadmap Cross-Check | 47 roadmap items vs shipped status | 47 verified + 8 regressions | — | 8 regressions | — |

---

## Section 1 — Dashboard & Top-Bar Findings

### D-01 — Top-bar ticker compression (MAJOR)

**Files**: `apps/worldview-web/components/shell/TopBar.tsx:145-187`, `apps/worldview-web/components/shell/IndexTicker.tsx:42-175`

**Current**: SPY/QQQ/VIX/BTC render in a fixed flex row with `gap-2`, `text-xs`, `max-w-[640px]`. No responsive breakpoints — narrow viewports (<1024px) compress text without graceful collapse.

**User proposal**: Marquee/rotation animation (left→right cycling).

**Options**:
- **A. Marquee scroll** — full-width animation, 1 ticker visible at a time. Pros: novel, no clipping. Cons: bad mental model for fast trading; animation distracts during decisions.
- **B. Horizontal scroll with arrow buttons** — page through tickers manually. Pros: user controls; all visible eventually. Cons: extra ~28px vertical space.
- **C. Collapse to dropdown** — pin SPY inline + popover for VIX/QQQ/BTC. Pros: Bloomberg convention; smallest code; respects priority order. Cons: hides 3 of 4.

**Recommendation**: **Option C** for v1. SPY is most-watched; collapse the rest. If feedback shows the dropdown is hidden, graduate to B.

**Also**: User wants ticker symbol bold-white + price+change in red/green. Current code uses muted-foreground for label and color only on change. Fix at `IndexTicker.tsx:134-154` — make price `font-bold text-foreground`, change in `text-[hsl(var(--positive))]` / `text-[hsl(var(--negative))]`.

**Effort**: M

---

### D-02 — Watchlists Movers replacement (MINOR — design decision)

**File**: `apps/worldview-web/components/dashboard/WatchlistMoversWidget.tsx`

**Current**: Top 5 gainers + losers from your *first* watchlist, filtered by sector/period. Shows ticker · name · price · %change with optional alert dot + news count badge.

**User issue**: "Not very useful". On a watchlist of 10–20 names with low movers, half the widget is empty.

**Proposed alternatives** (in priority order — implement #2 first):

| # | Concept | Data available? | Trader value | Effort |
|---|---------|-----------------|--------------|--------|
| 1 | Sector Leaders (3-5 movers per sector) | YES (existing enrichment) | Macro view of sector health | M |
| 2 | **Holdings Movers** (top gainers/losers from *portfolio*, not watchlist) | YES (reuse logic, swap source) | "Which positions are moving today?" — answers the highest-value question | L |
| 3 | Relative Strength (holdings vs SPY today) | YES (need SPY quote) | "Am I beating the market?" | M |
| 4 | Volume/Volatility Spike (holdings with abnormal volume or ATR breakout) | NO (need 50d OHLCV/ATR) | Pre-move signal | H |
| 5 | Earnings & Events upcoming (your holdings) | YES (existing earnings calendar) | Reduce surprise gap risk | M |

**Recommendation**: Replace WatchlistMovers with **Holdings Movers** (#2) v1; add Sector Leaders (#1) as a tab v2.

---

### D-03 — Prediction Markets filter broken / insufficient entries (MAJOR)

**File**: `apps/worldview-web/components/dashboard/PredictionMarketsWidget.tsx:202-312`

**Investigation**:
- Filter logic itself works correctly (`filteredMarkets = allMarkets.filter(categorize(m.title) === categoryFilter)` at line 229).
- **Real bug**: `limit=8` markets fetched (line 216). When user filters to "Macro", and only 2 of the 8 markets are macro, only 2 rows display. User sees an empty widget half.
- "View all (N)" footer at line 530-538 is **static text** — not wrapped in a `<Link>`. Clicking does nothing.
- Universe data gap (PLAN-0053 Wave C territory): even at `limit=30`, if Polymarket only has ~80 active markets and 70% are sports, "Macro" filter still empties.

**Fixes**:
1. **S** — Increase `limit: 8 → 25`.
2. **S** — Wrap "View all" in `<Link href="/prediction-markets">`. (Note: that route may not exist; create stub or link to `/instruments?category=prediction`.)
3. **M** — Dynamic limit: when a filter is active, refetch with `limit=50`.
4. **L** (PLAN-0053 Wave C) — Universe expansion via PLAN-0056 Polymarket Phase 2 ingestion.

---

### D-04 — Portfolio News widget missing filter/sort (MINOR — feature)

**File**: `apps/worldview-web/components/dashboard/PortfolioNewsWidget.tsx:1-243`

**Current**: Top 20 articles from `getTopNews()`, ranked by S6 `market_impact_score`. **Zero filter/sort controls**.

**User wants**: Ticker filter (All / specific ticker from holdings), sort (Impact ↓ / Date ↓ asc/desc), tier filter (LIGHT / MED / HIGH / DEEP).

**Proposed header layout**:
```
PORTFOLIO NEWS · [All ▾] [Impact ↓ | Date ↓] · [All · Light · Med · High · Deep]
```

All filtering can be **client-side** (no extra API). Use `useState` for ticker/sort/tier, derive filtered+sorted array.

**Effort**: M.

---

### D-05 — Alert title quality + click-to-detail (CRITICAL)

**Files**:
- `apps/worldview-web/components/dashboard/RecentAlerts.tsx:34-198`
- `apps/worldview-web/lib/alerts/format.ts:1-75`
- `apps/worldview-web/components/alerts/AlertDetailSheet.tsx:1-80+`

**Current**: `formatAlertTitle()` has a 7-step fallback ladder ending in "humanize alert_type" — this is what produces the user's complaint **"Graph Change alert"**.

**Click-to-detail**: Already works. `RecentAlerts.tsx:143-145` navigates to `/alerts?selected={alert.id}` which opens `AlertDetailSheet`. **No bug here.**

**Fix — title template engine**: Replace the type-humanization fallback with a per-`alert_type` template that interpolates `payload` fields:

| Alert Type | Template | Example |
|---|---|---|
| `PRICE_DROP` | `{ticker}: Price down {pct}% in {period}` | "SPY: Price down 3.2% in last hour" |
| `PRICE_RISE` | `{ticker}: Price up {pct}% in {period}` | "AAPL: Price up 2.1% in 30min" |
| `GRAPH_CHANGE` | `{ticker}: Technical breakout ({direction})` | "QQQ: Technical breakout (upside)" |
| `SENTIMENT_SHIFT` | `{ticker}: Sentiment shift ({direction})` | "TSLA: Sentiment shift (negative)" |
| `NARRATIVE_SHIFT` | `Market narrative shift: {detail}` | "Market narrative shift: Fed policy change" |
| `EARNINGS` | `{ticker}: Earnings {beats_misses}` | "MSFT: Earnings beat EPS estimate" |
| `DIVIDEND` | `{ticker}: Ex-dividend {date}, ${amount}` | "KO: Ex-dividend tomorrow, $0.42" |

**Where**: extend `lib/alerts/format.ts`. Add `formatAlertTitleWithTemplate(alert)` that runs templates **before** the humanize fallback. If the template needs a payload field that's null, fall through to a less specific template, only landing on humanize as last resort.

**Effort**: M.

---

## Section 2 — Portfolio Section Findings

### P-01 — Holdings page "black widget" overlay (CRITICAL)

**Files**:
- `apps/worldview-web/components/portfolio/PortfolioAnalyticsSection.tsx:103-184`
- `apps/worldview-web/components/portfolio/EquityCurveChart.tsx:313-323`

**Root cause**: The equity-curve chart wrapper applies `min-h-[200px] bg-card` *unconditionally* during loading. While the data is loading, the dark panel renders at full 200px height behind a Skeleton — appearing as a black panel that consumes half the viewport at the top of the page.

**Fix**: Make the min-height conditional on loaded data:

```tsx
{equityLoading ? (
  <div className="col-span-12 lg:col-span-8 h-auto">
    <Skeleton className="h-[200px] w-full rounded-[2px]" />
  </div>
) : equityIsEmpty ? (
  /* existing empty state */
) : (
  <div className="col-span-12 lg:col-span-8 min-h-[200px] bg-card">
    {/* chart */}
  </div>
)}
```

**Effort**: S.

---

### P-02 — Holdings page widget enhancement catalog (MINOR — design decision)

**Current widgets**: Holdings table (12 cols) · KPI strip · equity curve · exposure breakdown · risk metrics · sector allocation panel.

**Industry research** (Bloomberg PORT, Schwab, Fidelity ATP, Robinhood, Public, Wealthfront, TradingView):

**Proposed widget catalog — 12 items, prioritized**:

| # | Widget | Data ready? | Trader value | Effort |
|---|--------|-------------|--------------|--------|
| 1 | Realized P&L breakdown (YTD/period) | ✅ YES (PLAN-0051 Wave A `getRealizedPnL`) | Tax planning, wash-sale tracking | S |
| 2 | Dividend Income Timeline (YTD) | ✅ YES (transactions filterable by DIV) | Passive income view + per-symbol yield | M |
| 3 | Sector/Industry tree map | ⚠️ PARTIAL (sector yes, industry no) | Concentration risk visualization | M |
| 4 | Asset-type breakdown (Equity/ETF/Bond/Crypto/Options) | ❌ NO (S1 has no asset_class field) | Multi-asset visibility | L |
| 5 | Performance attribution by sector | ⚠️ PARTIAL (need new S9 endpoint) | "Which sectors drove return?" | L |
| 6 | Options Greeks summary | ❌ NO (no options support) | Risk hedging visibility | L |
| 7 | Cash management (% cash, sweep APY) | ✅ YES (`exposure.cash`) | Cash drag visibility | S |
| 8 | Correlation matrix (pairwise) | ✅ YES (price history) | Identify redundant positions | M |
| 9 | Rebalance alerts (drift > 5% from target) | ✅ YES (weight already computed) | Strategic-allocation discipline | M |
| 10 | Recent activity feed (transactions + sync events) | ✅ YES | Audit trail | S |
| 11 | Risk heat map (per-position 30d volatility) | ⚠️ PARTIAL (need rolling std-dev compute) | Visual scan of which positions are most volatile | M |
| 12 | Tax-loss harvesting opportunities | ⚠️ PARTIAL (need wash-sale history) | Year-end tax planning | L |

**Recommendation**: Ship #1, #2, #7, #10 in PLAN-0053 Wave D (all small effort, all data ready). Defer #4 and #6 to a separate brokerage-multi-asset PRD.

---

### P-03 — Transactions: dividend qty + asset type column

**P-03a — Dividend qty**: ✅ **Already correct**. `TransactionsTable.tsx:449-451` renders `"—"` for DIVIDEND rows. The `amount` field carries the cash payment. **No fix needed.**

**P-03b — Asset type column**: ⚠️ Backend gap. S1 `Transaction` schema only has `transaction_type` (TRADE/DIVIDEND/FEE) and `direction` (BUY/SELL/INFLOW/OUTFLOW). The `Instrument` model has no `asset_class` field. To distinguish equity vs ETF vs option vs future:
1. (Backend) Add `asset_class` enum to `Instrument` ORM in S1 + Alembic migration. Source from broker sync (SnapTrade exposes it).
2. (Backend) Join on transaction fetch — return `asset_class` per row.
3. (Frontend) Add column to `TransactionsTable.tsx`. Style as small uppercase badge (`bg-primary/10 text-primary` for EQUITY; `bg-blue-500/10 text-blue-500` for ETF; etc.).

**Effort**: L (backend schema change). Add to PLAN-0053 Wave D.

---

### P-04 — Watchlists: black widget + delete + broken add flow (CRITICAL)

**P-04a — "Big black widget"**: The `/watchlists` route is a redirect stub (`app/(app)/watchlists/page.tsx` → `/workspace`). The user's "black widget" is on the **dashboard `WatchlistMoversWidget`** or **workspace `WorkspaceWatchlistWidget`** — same z-index bug as P-01. Apply the same conditional min-height fix.

**P-04b — Delete button**: ✅ **Already implemented**. `WatchlistsTabPanel.tsx:184-208` renders a hover-revealed `Trash2` button that calls `removeWatchlistMember(watchlistId, entityId)` (gateway.ts:1658-1665, `DELETE /v1/watchlists/{wid}/members/{entityId}`). User may have missed the hover reveal (opacity-0 default). **Suggest**: keep the button at opacity-30 by default (still subtle, more discoverable).

**P-04c — Broken add flow** ("Failed to add", "No instruments found for 'apple'"): **CRITICAL**.

Root cause is in `searchFundamentals()` (gateway.ts:2378-2407):
1. Stage 1 calls `searchInstruments(trimmed)` — S3 only indexes by **ticker** (uppercase), not by company name.
2. Query "apple" (lowercase, name) → S3 returns 0 candidates → Stage 2 (entity enrichment) is skipped → `searchFundamentals` returns `{results: []}`.

**Three-tier fix**:
- **Quick (S)**: Auto-uppercase the input in `WatchlistsTabPanel.tsx:359` (`const val = e.target.value.toUpperCase()`). Add help text: "Enter ticker (e.g., AAPL for Apple)". Add empty-state hint: "No results — try the ticker symbol (e.g., AAPL for Apple)".
- **Better (L)**: Add company-name index in S3. The S7 KG already has company names; mirror them into S3's instrument search. Then "apple" matches both ticker=AAPL and name="Apple Inc."
- **Best (XL)**: Full-text search via Postgres `pg_trgm` or OpenSearch — matches misspellings, partial names, ticker prefixes.

**Recommendation**: Ship the Quick fix in PLAN-0053 Wave A (immediate user value). Schedule the Better fix for a separate S3-search PRD (cross-cuts S3+S7).

---

## Section 3 — Instrument Page Findings

### I-01 — Sidebar `/instruments` → screener routing (LOW — design clarity)

**Status**: Design intent is correct. `/instruments` and `/screener` are separate pages by design (Bloomberg analogy: SECF vs EQUITY SCREEN). User mental-model issue, not a code bug.

**Fix**: Rename sidebar label "Instruments" → "**Browse Instruments**" or add a tooltip. Effort: S.

---

### I-02 — Screener row click → instrument page broken (HIGH — needs repro)

**File**: `components/screener/ScreenerTable.tsx:398`

**Current**: `onClick={() => router.push(`/instruments/${row.entity_id}`)}` — code looks correct. `entity_id` is the right key per ADR-F-12.

**Hypotheses if user reports navigation fails**:
1. Click region not activating — check `cursor-pointer` and that no overlay z-index blocks it.
2. `row.entity_id` is null/undefined — add defensive check + error toast.
3. Route param decode error on `[entityId]/page.tsx:58` if entity_id contains special chars.

**Action**: Add console logging + Playwright test in PLAN-0053 Wave A. Reproduce live before designing fix.

---

### I-03 — Chart infinite past-scroll loop (CRITICAL)

**File**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:213-650`

**Investigation**: No `subscribeVisibleTimeRangeChange` callback found via grep. So the loop must come from one of:
1. **State→fetch→re-render→state** loop (e.g., a `useEffect` that depends on a value it also sets).
2. **Stale `useQuery` deps** — query refetches on every render.
3. **External toolbar component** (`ChartToolbar`?) that fires timeframe changes spuriously.

**Action plan** (PLAN-0053 Wave A `/fix-bug`):
1. Add `console.warn` at the start of `queryFn` to detect rapid refetches.
2. Audit `useEffect` dependency arrays in OHLCVChart + ChartToolbar.
3. If query is re-firing on every render, fix the `queryKey` stability.
4. If it's a panning callback, debounce + check that the callback dependency is stable.

**Severity**: CRITICAL — instrument page is unusable.

---

### I-04 — Overview tab "black big spaces" (HIGH)

**File**: `components/instrument/OverviewLayout.tsx:85-210`

**Investigation**: Layout grid `[1fr_280px]` is structurally sound. Black spaces likely come from:
1. `OverviewSidebarMetrics` (line 148) renders empty when fundamentals null — no skeleton, no fallback card.
2. `SparklinePanel` instances (lines 156-171) collapse to 0 height when their data is loading/missing.
3. `overflow-y-auto` may not be active on the sidebar column (line 145).

**Fix**: Add proper loading skeletons + empty-state cards for each sidebar zone. Ensure parent column has explicit `min-h` or `flex-grow` so empty state still occupies expected space.

**Effort**: M.

---

### I-05 — Right-sidebar redesign: overview/competitors/news (MAJOR — design)

**Current sidebar zones**: Key Metrics + 2 Sparkline panels.

**User wants**: Overview summary + Competitors + News (in addition to existing).

**Proposed 5-zone sidebar layout** (280px wide, scrollable):
```
1. Overview Summary (h-90px)
   - Current price + 52W range bar
   - Market cap, P/E, Div yield as compact badges

2. Competitors (h-120px, collapsible)
   - 3-5 peer tickers + relative valuations (mini heatmap)

3. News (h-140px, collapsible)
   - 3-5 headlines with sentiment pill + timestamp
   - "More news →" link to NewsTab

4. Key Metrics (existing, scrollable, ~12 rows)

5. Sparklines (existing, 2 panels)
```

**Effort**: H (3 new components + sidebar rework).

---

### I-06 — Fundamentals tab enhancements (MEDIUM — polish)

**Current**: 9 sections in 2-3 col grid + 280px sidebar (Market Position, Peer Comparison, Ownership, News).

**5 enhancements (priority order)**:
1. **(S) Trend sparklines per metric** — add 10px-tall sparkline next to each metric value showing 5y trend.
2. **(M) Peer comparison column in-grid** — for Valuation / Profitability / Growth grids, add "Sector avg | Industry median" columns.
3. **(M) Multi-period tabs** — "1Y / 3Y / 5Y" tabs on each section to compare YoY trends.
4. **(L) Income-statement waterfall** — Revenue → COGS → GP → OpEx → EBITDA → Net Income flow.
5. **(M) Forecast/guidance section** — analyst consensus FY+1 estimates vs actuals.

---

### I-07 — News tab polish (LOW)

**Current**: relevance gradient, sentiment pill, impact pill, entity chips, time-grouping, source filter, sort. Already good.

**5 polish items**:
1. **Source badges** (2-letter monogram: BB / ZK / MO) left of sentiment pill.
2. **Narrative tags** — Earnings/M&A/Regulation/Product/Macro chips per article.
3. **Timeline view toggle** — vertical timeline alternative to flat list.
4. **Filter persistence** to sessionStorage.
5. **Read-on-source CTA** — explicit secondary button at row end.

---

### I-08 — Intelligence/KG UI redesign ("toy not Bloomberg") (MEDIUM — design)

**File**: `components/instrument/IntelligenceTab.tsx`

**Critique points**:
- Buttons use default shadcn weight, look "clumsy" — should be terminal-weight (`text-[10px] uppercase tracking-wider`).
- MarkdownContent uses `size="comfortable"` (12px) — too loose for dense intelligence data.
- Card padding around the graph wastes space.
- Contradiction cards lack hierarchy between severity badge and text.
- Depth slider possibly broken (no telemetry).

**Refined design**:
```
Zone 1: Graph Controls (h-9, edge-to-edge)
   [Depth: ① ② ③] [Refresh ↻] [Export SVG]   font-semibold for active depth
Zone 2: Graph Container (flex-1, padding 0)
Zone 3: Brief — collapsible 9-row banner OR full
   MarkdownContent size="compact" (11px)
Zone 4: Contradictions — header with count, expanded card opens modal not in-place
```

---

### I-09 — AI brief format alignment (LOW — 1-line fix)

**File**: `components/instrument/IntelligenceTab.tsx:45`

**Bug**: Uses `MarkdownContent size="comfortable"` while dashboard `MorningBriefCard` and `InstrumentAISubheader` use `size="compact"`. Per the existing comment, "compact" is canonical.

**Fix**: Change `comfortable` → `compact`. Effort: trivial.

---

## Section 4 — Other Pages Sweep

### /alerts (4 findings)

- **O-AL-01 (M)** — Snooze button has no duration picker. Add Popover submenu: 15min / 1h / 4h / EOD.
- **O-AL-02 (L)** — News-feed category filter doesn't persist across reloads. Add localStorage.
- **O-AL-03 (L)** — AlertDetailSheet doesn't show "viewed at" timestamp.
- **O-AL-04 (M)** — No bulk action toolbar (select-all, ACK-all-visible). Power users with 50+ alerts need this.

### /chat (3 findings)

- **O-CH-01 (L)** — CitationBar doesn't update during streaming.
- **O-CH-02 (L)** — Thread sidebar scroll position resets on new message.
- **O-CH-03 (M)** — Slash command autocomplete shows no usage hint (e.g., "Usage: /quote {ticker}").

### /news (1 finding)

- **O-NW-01 (L)** — Page is now a redirect stub to `/alerts?tab=news`. Audit internal links to avoid redirect overhead.

### /screener (3 findings)

- **O-SC-01 (L)** — "Load N more" button label doesn't update during fetch.
- **O-SC-02 (M)** — Column customization saves to localStorage silently — no "Saved" toast.
- **O-SC-03 (L)** — Sparklines disabled silently for >200 rows; no explanation tooltip.

### /settings (2 findings)

- **O-ST-01 (M)** — Notification toggles are uncontrolled (`defaultChecked`); never sync to server. Add "(Coming soon)" banner.
- **O-ST-02 (L)** — Color palette swatches don't copy hex on click. Add click-to-copy.

### /workspace (2 findings)

- **O-WS-01 (L)** — Tab strip overflow has no fade-gradient indicator that more tabs exist off-screen.
- **O-WS-02 (L)** — `?config=token` import calls `window.location.reload()`, clearing the param. Use `router.replace('/workspace')` instead.

### Auth pages (2 findings)

- **O-AU-01 (CRITICAL)** — Dev Login button can appear in prod if Zitadel probe returns 502. Tighten probe: require **both** 502 **and** missing `NEXT_PUBLIC_ZITADEL_URL`.
- **O-AU-02 (M)** — Callback error messages are generic — users can't distinguish CSRF from network error.

### Cross-cutting themes

- **T-01** — Multiple uncontrolled `defaultChecked` MVP scaffolds without "Coming Soon" indicators.
- **T-02** — Inconsistent localStorage persistence for filter/category state.
- **T-03** — Missing loading states during async mutations.
- **T-04** — Inconsistent aria-label coverage.
- **T-05** — Email/form validation absent on register/login.
- **T-06** — Boilerplate empty-state messaging.

---

## Section 5 — User Feedback System Design

PLAN-0052 Wave D shipped the backend (14 endpoints, 6 tables, PII redaction). **No frontend exists yet.** This section designs the frontend Wave E.

### 5.1 Backend inventory (already shipped)

**Endpoints**: feedback submissions (CRUD + admin patch), NPS scores + admin aggregate, feature requests + idempotent voting, micro-survey, beta-program enrollment.

**Tables**: `feedback_submissions` (PII-redacted, 7-day TTL on logs, 90-day TTL on screenshots), `nps_scores` (30-day-per-user rate limit at use-case layer), `feature_requests` + `feature_votes`, `micro_survey_responses`, `beta_enrollments`.

**Auth**: Owners see own + admins see all. Anonymous submissions land in a separate platform-support tenant.

### 5.2 Recommended frontend design

**Combine 5 patterns** (finance-pro audience = quality > quantity):

1. **Floating widget** (bottom-right, always-on) — entry to feedback modal.
2. **Cmd+K command** "Feedback" — power-user entry.
3. **NPS prompt** — full-screen modal, rate-limited (30-day server + per-quarter app flag), surfaces tied to milestones (post-portfolio-sync, post-first-alert).
4. **Screenshot capture** — html2canvas + blur tool, opt-in toggle in form.
5. **Feature-request public board** at `/feedback` — list/vote/suggest.

### 5.3 Modal flow

```
TYPE SELECTOR → DYNAMIC FORM → CONFIRMATION
  ├─ Bug Report (severity, description, screenshot toggle, console logs toggle, email if anon)
  ├─ Feature Request (title, description, category, email if anon)
  ├─ UX/Design (description)
  ├─ General (description)
  └─ Contact Us (subject, message, email required)
```

**Auto-collected metadata** (page URL, viewport, user_agent, build_hash, user_role, timestamp, theme).

### 5.4 14 frontend tasks

| ID | Component | Effort | Notes |
|----|-----------|--------|-------|
| FB-01 | FeedbackButton (floating 56px) | S | bottom-right fixed, auth-only |
| FB-02 | FeedbackModal (multi-tab) | M | shadcn Sheet + Tabs |
| FB-03 | ScreenshotCapture | M | html2canvas + blur overlay + S3 presigned-URL upload |
| FB-04 | ConsoleLogCapture | S | window.console monkey-patch hook |
| FB-05 | NPSPrompt (full-screen) | M | 0-10 number pad + comment |
| FB-06 | MicroSurvey (inline 👍👎🤷) | S | reusable for docs etc. |
| FB-07 | FeatureRequestBoard (`/feedback` page) | M | public, sortable, idempotent voting |
| FB-08 | FeedbackAdminDashboard (`/admin/feedback`) | M | filterable virtualized table + bulk actions + CSV |
| FB-09 | useFeedbackSubmit hook | S | gateway wrapper + validation |
| FB-10 | useNPSEligibility hook | S | sessions ≥3, 30-day check, per-quarter flag |
| FB-11 | useConsoleCapture hook | S | wraps window.console |
| FB-12 | useFeatureRequests hook | S | TanStack Query + filters |
| FB-13 | useFeedbackSubmissions hook (admin) | S | TanStack Query + status sort |
| FB-14 | Extend gateway.ts | S | 8 new methods |

**Total**: ~16h.

### 5.5 Open questions (need user decision)

1. Public vs private feature board? **Recommend public.**
2. Anon submissions allowed? Backend allows it. Recommend yes (with email).
3. Email follow-up enabled? **Recommend not in MVP.**
4. Auto-capture console logs vs opt-in? **Recommend opt-in.**
5. Auto-capture screenshot vs opt-in? **Recommend opt-in.**
6. Slack/Discord webhook? **Defer post-MVP.**
7. NPS frequency? **Recommend 1/quarter/user.**
8. Feature categories — admin-managed or hardcoded? **Recommend hardcoded enum** (Performance / Usability / Data / Integrations / Documentation / Other).

---

## Section 6 — Roadmap Cross-Check Summary

**47 of 47 roadmap items shipped** across PLANs 0049–0052. Zero items skipped.

**8 regressions/scope-leaks identified** (where the user reports a gap that wasn't caught by prior QA):

| # | Regression | Plan/Wave that should have caught it | Severity |
|---|------------|---------------------------------------|----------|
| 1 | Watchlist delete button unhooked / add flow broken | PLAN-0049 Wave B (T-B-2-05 was empty-state-only scope) | CRITICAL |
| 2 | Holdings z-index bug | PLAN-0049 Wave B (T-B-2-04 fixed empty state, not z-index) | CRITICAL |
| 3 | Chart infinite-loop | Pre-existing, not in roadmap | CRITICAL |
| 4 | ACK/snooze multi-device divergence | PLAN-0051 Wave D (T-D-4-03 lacks retry-on-fail) | CRITICAL |
| 5 | Fundamentals "—" on many tickers | PLAN-0050 Wave D (EODHD adapter has gaps) | MAJOR |
| 6 | Predictions data insufficiency | PLAN-0050 Wave F (filter shipped but universe too small) | MAJOR |
| 7 | Portfolio news widget no sort/filter | Misclassified as instrument-page work; not scoped | MAJOR |
| 8 | Top-bar ticker compression | PLAN-0050 Wave F (responsive deferred) | MAJOR |

**Items explicitly deferred to Phase 5**: chart drawing-tool persistence, institutional analytics, universe expansion 600+, mobile responsive overhaul, feedback Phase 3 (Linear webhook + sentiment), workspace panel completeness, Polymarket Phase 2.

---

## Section 7 — Suggested PLAN-0053 Outline

**Theme**: "Polish & Advanced Features" (Phase 5)
**Total effort**: ~104h ≈ 2.5–3 weeks

### Wave A — Critical Bug Fixes & Watchlist CRUD (~16h) — **gates Phase 5**

- A-1 (S) — Watchlist delete UI polish (raise opacity, verify hook)
- A-2 (M) — Watchlist add-flow fix (auto-uppercase + better empty state + help text)
- A-3 (S) — Holdings z-index bug (conditional min-h on equity curve panel)
- A-4 (M) — Alert ACK/snooze sync hardening (retry-on-fail, fall back to localStorage with retry queue)
- A-5 (M) — Chart infinite-loop diagnosis + fix (useEffect dep audit, queryKey stability)
- A-6 (S) — Screener→instrument routing E2E test (Playwright)
- A-7 (S) — Alert title template engine (per-alert_type templates with payload interpolation)
- A-8 (S) — Top-bar ticker dropdown collapse on <1024px

### Wave B — Fundamentals Data Backfill Completion (~12h)

- B-1 (M) — EODHD adapter quality audit (auth, rate-limits, per-field logging)
- B-2 (M) — Extend `backfill_fundamentals.py` (% populated per ticker, top 50 gaps)
- B-3 (L) — Add fallback provider (Alpha Vantage / Polygon) for EODHD-missing tickers
- B-4 (S) — Verify all 10 fields wired end-to-end on AAPL/MSFT/NVDA live

### Wave C — Universe Expansion + Prediction Markets (~18h)

- C-1 (L) — Universe expansion to S&P 500 + NDX-100 + sector ETFs + 20 crypto
- C-2 (M) — Coordinate Polymarket Phase 2 ingestion (PLAN-0056)
- C-3 (M) — Seed 50+ markets across categories if Phase 2 delayed
- C-4 (S) — Universe-coverage admin dashboard widget
- C-5 (S) — Prediction widget: increase limit to 25 + dynamic limit on filter + wire "View all" link

### Wave D — Portfolio Enhancements (~14h)

- D-1 (M) — Portfolio news widget filter + sort (ticker/date/impact/tier)
- D-2 (L) — Transaction asset_type column + S1 schema migration
- D-3 (M) — Realized P&L historical chart (PLAN-0051 Wave A endpoint, period toggle)
- D-4 (S) — Allocation widget responsiveness <768px
- D-5 (S) — Holdings Movers widget (replace WatchlistMovers data source with portfolio)
- D-6 (S) — Cash management mini-card (cash % + APY if sweep enabled)
- D-7 (M) — Dividend Income Timeline widget (group transactions by quarter, mini sparkline)
- D-8 (S) — Recent Activity Feed widget (transactions + sync events virtualized list)

### Wave E — Responsive Design Overhaul (~20h) — deferred from Phase 4

- E-1 (L) — Dashboard responsive
- E-2 (L) — Instruments responsive (sidebar collapse, metrics → tabs)
- E-3 (L) — Screener responsive (table → cards <768px)
- E-4 (L) — Portfolio responsive (tabs → accordion)
- E-5 (M) — Workspace responsive (touch panel resize)
- E-6 (S) — Playwright snapshots @ 768px / 480px

### Wave F — Accessibility, Performance & Cross-Cutting Polish (~14h)

- F-1 (L) — WCAG 2.1 AA contrast + keyboard nav + ARIA audit
- F-2 (M) — Batch endpoint adoption (`POST /v1/quotes/bars/batch`)
- F-3 (M) — localStorage persistence sweep (filter/category state across pages)
- F-4 (M) — Loading state sweep (Load-more buttons, copy-hex, async actions)
- F-5 (S) — Auth page error message specificity (CSRF vs network vs token expiry)
- F-6 (S) — Settings notifications "Coming soon" banner
- F-7 (S) — Bulk actions on /alerts (multi-select + ACK-all)
- F-8 (S) — Alert snooze duration picker

### Wave G — User Feedback System Frontend (~16h)

- G-1 (S) — FB-14 Extend gateway.ts (8 methods)
- G-2 (S) — FB-09..13 hooks in parallel
- G-3 (S) — FB-03/04/05/06 leaf components
- G-4 (M) — FB-02 FeedbackModal
- G-5 (S) — FB-01 FeedbackButton
- G-6 (M) — FB-07 FeatureRequestBoard page
- G-7 (M) — FB-08 FeedbackAdminDashboard page
- G-8 (S) — Wire NPS triggers (post-portfolio-sync, post-first-alert)

### Wave H — Instrument Page Polish (~12h)

- H-1 (S) — I-09 AI brief size alignment (`comfortable` → `compact`)
- H-2 (M) — I-04 Overview tab loading skeletons + empty states
- H-3 (H) — I-05 Right-sidebar 5-zone redesign (Overview / Competitors / News / Metrics / Sparklines)
- H-4 (S) — I-06 Trend sparklines per fundamentals metric
- H-5 (M) — I-08 Intelligence UI weight + density polish
- H-6 (S) — I-07 News tab source badges + narrative tags

---

## Recommendations

**Immediate next steps** (in order):

1. **Approve PLAN-0053 outline** (or refine waves) — user decision on scope.
2. **Run `/plan` skill** with this audit as input to generate full task-level plan with PRD references and dependency graph.
3. **Start Wave A immediately** — these are user-blocking. Don't bundle with Wave B+ (different concerns, different verification gates).
4. **Resolve feedback-system open questions** (Section 5.5) before starting Wave G.
5. **Schedule live-stack repro session** for I-03 (chart loop) and I-02 (screener routing) — these need user-side telemetry to diagnose.

**Process improvements** (compounding value):

1. **Add "scope creep guard" to `/implement`** — at task start, agent must read the task description AND the underlying user-reported issue. If the task description is narrower than the issue, flag it before coding.
2. **Add "regression sweep" to `/qa`** — after fixing issue X, search for related-but-out-of-scope problems (e.g., fix-watchlist-empty-state should also surface "are delete/add flows working?").
3. **Add `BP-XXX` for "z-index loading state bug"** — `min-h` + `bg-card` on a panel during data load causes a black panel. Pattern repeated 3+ times in this codebase.

---

## Verdict

**FAIL** — 4 CRITICAL findings remain unresolved (P-01, P-04c, I-03, O-AU-01) plus 11 MAJOR. None of the 4 plans should be re-opened (they shipped what was scoped); instead, **launch PLAN-0053** to close the gap between "what was planned" and "what users need".

The original roadmap audit was complete; the plans were faithful to it. The miss was at the task-scope-definition level — too narrow on issues like watchlist CRUD and chart stability. PLAN-0053 corrects this with explicit scope on the user-reported gaps.
