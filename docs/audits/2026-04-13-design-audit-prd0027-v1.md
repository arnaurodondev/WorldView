# Design Audit — worldview-mvp_v1.pen
**Date**: 2026-04-13
**Auditor**: Design QA Pass (multi-agent + visual analysis)
**Verdict**: PASS_WITH_MAJOR_GAPS
**Scope**: All 12 pages + 3 dashboard states in `worldview-mvp_v1.pen`
**Reference**: `apps/frontend/designs/STYLE_GUIDE.md`, `REDESIGN_PLAN.md`, PRD-0027

---

## Executive Summary

The v1 design represents a significant improvement over the baseline. The **dashboard is the standout success** — information-dense, technically credible, and professional enough to present to stakeholders. The landing page hero is strong. However, **6 of 12 pages have critical issues** that would undermine stakeholder confidence, and **2 pages are completely absent** (Workspace/Workstation, Graph sub-tab). The chart visualization across Company Detail is a critical blocker — bar charts instead of candlesticks undermine the professional credibility of the entire platform. Marketing copy in sections 2 and 3 of the landing page targets the wrong emotional register for professional traders. The portfolio page has not been updated from the old design and needs a complete rebuild.

**Highest priority before any stakeholder presentation**:
1. Candlestick chart for Company Detail (currently bar chart)
2. Fix dashboard state placement (outside design column)
3. Replace "Everything a serious analyst needs" and "Finally, a Bloomberg alternative that's actually affordable" copy
4. Complete Portfolio redesign
5. Add Workstation/Workspace page

---

## Page-by-Page Audit

---

### 01 — Landing Page

**Grade: B+**

**What works**:
- Hero headline "Bloomberg-Grade Research. Without the Bloomberg Bill." is strong and positions correctly against a known competitor
- Stats bar (10M+ data points, 18 fundamentals sections, 500K+ graph relations, <5s AI answers) is credible and specific
- Comparison table is clear and visually differentiates Worldview
- Dark aesthetic with product screenshot in hero is professional

**Critical Issues**:

#### F-001 · CRITICAL · Landing Copy — "Everything a serious analyst needs"
- **Location**: Feature section header, ~1/3 down the page
- **Issue**: This phrase is ineffective for professional traders and analysts. It sounds like a consumer pitch claiming to be comprehensive. Professionals evaluate tools on specific capabilities, not on completeness claims. "Serious analyst" is a self-congratulatory framing that feels defensive.
- **Replacement options**:
  - `"Six capabilities no single platform delivers"` — specific, verifiable, creates curiosity
  - `"The research stack your firm isn't providing"` — targets buy-side analysts with budget constraints
  - `"From filing to thesis in minutes"` — workflow-specific, implies speed advantage
- **Recommended**: `"The edge no single platform delivers"` — minimal, confident, professional-register

#### F-002 · CRITICAL · Landing Copy — "Finally, a Bloomberg alternative that's actually affordable"
- **Location**: Comparison table header
- **Issue**: Three problems. (1) "Finally" is cliché. (2) "Actually affordable" positions Worldview as a budget product — professionals do not buy on price; they buy on ROI and edge. Budget positioning destroys credibility with hedge fund PMs and sell-side analysts. (3) "Bloomberg alternative" is redundant after the hero already established the comparison.
- **Replacement options**:
  - `"Bloomberg's data depth. Accessible pricing."` — factual, not "affordable"
  - `"Research-grade intelligence, independent pricing"` — B2B framing, respects the audience
  - `"The institutional stack. Without the institutional lock-in."` — addresses real pain point (Bloomberg's aggressive contract tactics)
- **Recommended**: `"Institutional depth. No lock-in."` — two beats, professional register, addresses a real Bloomberg pain point

#### F-003 · MAJOR · Unstructured Data Capabilities Underrepresented
- **Issue**: The platform's genuine differentiator is its NLP pipeline (entity extraction, claim detection, relationship discovery from SEC filings and news). This is not described anywhere in the feature cards. The feature cards show: "Workspace Terminal", "AI Research Copilot", "Entity Knowledge Graph", "News Intelligence", "18-Section Fundamentals", "Prediction Markets" — but don't communicate the underlying data processing capability.
- **Target audience context**: Research analysts and quant traders specifically value NLP on unstructured data (10-K/10-Q text, earnings call transcripts, SEC filings). This is their actual workflow pain point with Bloomberg — Bloomberg BNT (brief/news search) is expensive and limited.
- **Suggested addition**: Add a "document processing" feature card or spotlight section: "Every filing. Every call. Every relationship." showing that the platform ingests and structures unstructured data — not just structured market data.

#### F-004 · MINOR · Color — Yellow/Amber Contrast on Dark
- **Issue**: The amber CTA button (`#F0C040` or similar) against the near-black background (`#080A0E`) creates a very high contrast that could look harsh. The yellow-black combination is visually striking (Bloomberg-DNA) but needs a subtle gradient or shadow to avoid the "warning sign" aesthetic.
- **Suggestion**: Use amber for primary CTAs but pair with a 1px inner shadow or subtle gradient. Keep amber reserved for CTAs and AI indicators only — not as section backgrounds.

#### F-005 · MINOR · Mobile state annotation only (State C)
- **Issue**: State C: Mobile 375px contains only an annotation text node — no actual mobile design. For a stakeholder demo, this is fine, but should be noted as "design intent annotation only".

---

### 02 — Dashboard

**Grade: A−**

**What works**:
- Morning Brief as the primary hero element — amber border, AI label, instant recognition
- Portfolio summary card with total value, daily P&L, unrealized P&L, sparkline
- Sector heatmap with correct proportional tiles and color scale
- Intelligence stream + alert stream side by side
- Watchlist in sidebar with live prices
- Economic calendar
- Recent alerts at bottom with severity badges
- The overall information density is exactly right — professional without being overwhelming

**Critical Issues**:

#### F-006 · BLOCKING · Dashboard States Outside Design Column
- **Location**: Frames `fBOiy` (State A), `UbwGX` (State B), `NZEgU` (State C) are at x=1540 — outside the main design column (x=0)
- **Issue**: The `02-Dashboard` frame (`vsdgH`) at x=0 appears to be a wrapper only (height=1790) while the actual state designs are placed at x=1540. For any stakeholder presentation or implementation handoff, this is confusing. The states need to be inside the parent frame or the parent frame should clearly contain all three states stacked vertically.
- **Fix**: Either move all three states inside the `vsdgH` frame as children, OR place them at x=0 in a column below the main dashboard header.

#### F-007 · MAJOR · Search Bar Missing from Top Nav
- **Location**: Top navigation bar (`AvCDM` in fBOiy)
- **Issue**: User explicitly requested a global ticker search bar in the top nav (left of notification bell). This is a fundamental navigation pattern — every professional platform (Bloomberg command line, TradingView search) has this. Absence is immediately noticeable.
- **Fix**: Add a search input `[🔍 Search ticker, company, ETF, crypto...]` — 240px wide, between the market strip and the notification bell. Results should navigate to Company/Instrument Detail.

#### F-008 · MAJOR · Color Variants Not Tested
- **Issue**: User requested multiple color scheme variants (yellow-black dominant, sky-blue dominant, red accent variant) side by side for comparison. These don't exist. For a professional design process, testing multiple palettes before implementation is standard practice.
- **Action**: Design 3 color variant strips showing the same morning brief card + sector tile + navigation item in each color scheme.

#### F-009 · MINOR · Status Bar Content Sparse
- **Location**: Bottom status bar (sbar)
- **Current**: "SPX 5,248.32 +0.29% | NDX 18,421.10 +0.51% | VIX 14.82 -0.93% | USD/JPY 154.32"
- **Missing**: DXY (Dollar Index), Oil, Gold, Bonds (10Y yield), Bitcoin. Status bar is the place for macro cross-asset context. Bloomberg's status bar shows: Equities | Bonds | FX | Commodities | Crypto all at once.
- **Suggested**: `SPX +0.29% | NDX +0.51% | VIX 14.82 | US10Y 4.21% | DXY 104.3 | WTI $82.4 | BTC $68,240 | ETH $3,420`

---

### 03 — Company Detail (Instrument Detail)

**Grade: B−**

**Page naming note**: User correctly identified that "Company Detail" is misleading — this page displays any financial instrument (equities, ETFs, crypto, indices). Rename to "Instrument Detail" in both the canvas and implementation.

**What works**:
- Header row 1–4 is comprehensive (NVDA chip, exchange badge, sector, stats row with Vol/Mkt Cap/P/E/EPS/Beta)
- 52-week range bar with current price position
- 5-tab structure (Overview, Fundamentals, Intelligence, News, Chat)
- Fundamentals accordion structure with 5 groups
- Chat tab is clean and functional
- Intelligence tab shows prediction markets and similar companies

**Critical Issues**:

#### F-010 · BLOCKING · Chart is NOT Candlestick / OHLCV
- **Location**: Chart area visible in all tab states
- **Issue**: The current chart shows solid colored bars (green up, red down) without open/high/low/close wicks. This is a volume bar chart or price-change histogram — NOT an OHLCV candlestick chart. Any professional trader will immediately notice this and lose confidence in the platform.
- **Professional standard**: Bloomberg, TradingView, Interactive Brokers all show candlestick charts by default with: body (open→close), upper wick (high), lower wick (low). Volume bars appear in a separate sub-panel below (20% height). Moving averages (MA50, MA200) as overlay lines.
- **Fix required**: Completely redraw the chart as a candlestick chart:
  - Upper section (80% height): OHLCV candlesticks — green body=up, red body=down, thin wicks extending to high/low
  - Lower section (20% height): Volume bars colored by day direction
  - MA50 overlay: dashed line in `$amber`
  - MA200 overlay: dashed line in `$primary`
  - Price line: current price horizontal dotted line with price label on right Y axis
  - Y axis: right-aligned, mono font, price levels
  - X axis: date labels, mono font

#### F-011 · MAJOR · Instrument Brief Not Integrated Into Header
- **Location**: Right side panel in Overview tab (`wE7LT`)
- **Issue**: The instrument brief (AI analysis card with amber border) is currently in a separate right-side panel. User requested it be integrated inline with the header — as a horizontally scrollable or collapsible section directly below the header rows.
- **Proposed solution**: Add a collapsible "AI BRIEF" row immediately below the 52w range bar, expandable by default for new visitors:
  ```
  [◉ AI BRIEF · DeepSeek R1 · 08:45 ET] [▲ collapse]
  "NVIDIA delivered exceptional Q4 results with data center revenue surging..." [cite][cite][cite]
  ```
- **Right panel in Overview** then becomes: Key Metrics 3×3 + Analyst Consensus only

#### F-012 · MAJOR · Intelligence Tab — Entity Graph Too Simplistic
- **Location**: `M1GXQ` Intelligence tab
- **Issue**: The entity graph shows circles arranged in a loose layout — TSMC, AMD, MSFT, NFLX, TSM around NVDA. There is no apparent force-directed physics, no edge labels showing relationship types, no visual differentiation between node types (company vs person vs fund). The graph looks like a placeholder, not a functional tool.
- **Fix**: Redesign the intelligence graph to show:
  - Force-directed layout with visible edge connections (lines between nodes)
  - Edge labels: "competes_with", "CEO of", "supplier of", "holder of"
  - Node type differentiation: company=sky-blue circle, person=green circle, fund=purple circle
  - Node size proportional to relationship confidence
  - Sidebar controls: depth (2-hop/3-hop), confidence threshold slider, node type filter
  - Hover tooltip on nodes with key data

#### F-013 · MAJOR · News Tab State Missing Critical Design
- **Location**: `jZEVF` State D: News Tab
- **Issue**: The news tab state (`jZEVF`) has height=900 but appears positioned at y=3780 within the aTIbj frame, which conflicts with the Chat tab at y=3840. Based on the canvas structure, the news tab state likely overlaps with the chat tab state. Cannot verify visual from current screenshots — needs investigation.
- **Action**: Verify node positions within aTIbj frame. The news tab should show the full article feed with entity filter, relevance scores, tier badges, and impact sparklines.

#### F-014 · MINOR · Graph Tab Should Become Intelligence Sub-Tab
- **Issue**: The standalone Graph page (06-Graph) adds navigation complexity. The entity graph is contextually relevant only when viewing a specific instrument. Moving it to the Intelligence tab within Company Detail makes it the primary view of that tab (full-width at 60% + right panels at 40%).
- **Action**: Deprecate `06-Graph` as standalone page; ensure Intelligence tab has the full-width entity graph as primary content.

---

### 04 — Markets Page

**Grade: C+**

**What works**:
- Treemap heatmap of individual stocks (S&P 500 view) is professional and functional
- Sector performance bar chart at bottom is useful
- Status bar at bottom shows key indices

**Critical Issues**:

#### F-015 · BLOCKING · Missing Top Nav and Sidebar
- **Issue**: The Markets page (`SEWOh`) does not use the same top nav (with market strip, notification bell) or sidebar used by the Dashboard. Every authenticated page MUST use the same nav structure.
- **Fix**: Add the standard `tnav` (44px) + sidebar (200px) + status bar (24px) to the Markets page frame.

#### F-016 · MAJOR · Purpose Ambiguity — Markets vs Intelligence
- **Issue**: Currently there are two separate pages: Markets (heatmap) and Intelligence (news feed). Users need both at the same time — a quant trader scanning sector rotations also wants to see the news driving those rotations. Having them as separate pages creates unnecessary navigation friction.
- **Recommendation**: Merge into a single **"Markets & Intelligence"** page:
  ```
  Left 60%: Treemap heatmap (with S&P 500 / NASDAQ / Russell 2000 / Crypto tabs)
             + Sector performance bars below
  Right 40%: News feed with tier filter (DEEP / MEDIUM / LIGHT)
             + Macro events ticker at top
  ```
- This mirrors how Bloomberg's Market Wrap and TradingView's Market Overview work — price action and news coexist.

#### F-017 · MAJOR · Missing Asset Class Tabs
- **Current**: Only shows S&P 500, NASDAQ, Russell 2000 tabs
- **Missing**: ETFs tab, Crypto tab, Bonds/Rates tab, FX tab, Commodities tab
- For professional traders, cross-asset scanning is critical. A quant needs to see equity rotation AND bond yield movements AND FX moves simultaneously.

#### F-018 · MINOR · No Macro Events Integration
- **Issue**: Economic calendar events (CPI, FOMC, NFP) have major market impact. The Markets page should show upcoming macro events as a strip above or alongside the heatmap, so traders can contextualise sector moves.

---

### 05 — Intelligence Page

**Grade: C+** (may be merged into Markets per F-016)

#### F-019 · BLOCKING · Missing Top Nav and Sidebar
- Same issue as Markets — needs standard nav structure.

#### F-020 · MAJOR · Left Filter Panel Too Wide
- The entity type filter panel on the left takes significant horizontal space. For a page where the content (news feed) is the primary value, this is inefficient.
- **Fix**: Collapse the filter into a horizontal chip strip above the feed, or make it a collapsible overlay panel.

#### F-021 · MINOR · Entity Spotlight Panel Could Be Richer
- The right entity spotlight panel shows fundamentals bars but lacks: prediction market odds, recent claim snippets, knowledge graph mini-preview. These are Worldview's differentiators and should be prominent here.

---

### 06 — Graph (Standalone Page)

**Grade: D** → **Deprecate as standalone page**

#### F-022 · CRITICAL · Standalone Graph Page Has No Value Proposition
- **Issue**: The standalone Graph page adds a navigation menu item for a feature that is only useful in the context of a specific instrument. No professional research workflow starts at "I want to see a graph" — they start at "I'm researching NVDA and want to see its network".
- **Decision required**: Remove the standalone Graph page from the navigation. The entity graph functionality moves to the Intelligence tab of Instrument Detail. A "full-screen graph" option can be accessible from the Intelligence tab via an expand button.

---

### 07 — Screener

**Grade: B**

**What works**:
- Dense table with many relevant columns (ticker, company, price, change, volume, momentum, score, signal)
- Filter chip display is clear
- Row density is appropriate for professionals

**Critical Issues**:

#### F-023 · BLOCKING · Missing Top Nav and Sidebar
- Same issue — needs standard nav structure.

#### F-024 · MAJOR · Filter Builder Too Simple (Chip-Only)
- **Issue**: Professional screeners (Bloomberg, Finviz Elite) allow complex multi-condition criteria: `(Market Cap > $10B AND P/E < 30 AND ROE > 20%) OR (Sector = Technology AND RSI < 30)`. The current design only shows filter chips without a criteria builder.
- **Bloomberg pattern**: A spreadsheet-style criteria builder where each row is: `[Field dropdown] [Operator dropdown] [Value input] [AND/OR toggle]`
- **Finviz pattern**: Dropdown menus per category (Descriptive, Fundamental, Technical, All) with value selectors. Saved screens as named templates.
- **Minimum viable**: Add a `[+ Add Filter]` button that opens a popover with field selector + operator + value. Show resulting conditions as removable chips with field name, operator, and value visible.

#### F-025 · MAJOR · No Pre-Built Screen Templates
- Professionals want to start from known screens: "Graham Value", "High Momentum", "Overbought RSI", "Insider Buying". Finviz has ~20 built-in screens. This reduces time-to-value significantly for new users.
- **Fix**: Add a `[Load Screen]` dropdown with 6-8 pre-built templates.

#### F-026 · MINOR · No Export Function
- Research analysts export screener results to Excel/CSV constantly. Add an `[Export CSV]` button.

---

### 08 — Portfolio

**Grade: D − (Near-F)**

**What works**: Nothing in the current design aligns with the target spec.

**Critical Issues**:

#### F-027 · BLOCKING · Portfolio Not Redesigned — Old Design Active
- **Issue**: The current portfolio design (`Dwod8`, State A: Performance View) is the pre-redesign version. It shows:
  - A bar chart of portfolio performance occupying 40% of the page
  - A basic holdings table (5 rows)
  - A donut chart for sector allocation
  - Only uses ~1/3 of the 900px height (rest is empty black)
  - Does NOT implement the strategy-centric design from REDESIGN_PLAN.md
- **Impact**: Showing this to stakeholders would immediately undermine confidence that the platform supports serious portfolio management.

#### F-028 · BLOCKING · Complete Redesign Required — Target Architecture
The portfolio page must be rebuilt from scratch to match this specification:
```
[Page header: "My Strategies"] [+ Create Strategy]
─────────────────────────────────────────────────────
[StrategyCard] [StrategyCard] [StrategyCard]  ← 3-column grid
  Growth         Dividend Inc.  Quant Momentum
  $47,320.50     $28,140.00    $12,890.75
  +$1,243 +2.7%  -$84 -0.3%    +$312 +2.5%
  [sparkline]    [sparkline]   [sparkline]
─────────────────────────────────────────────────────
[Tabs: Holdings | Performance | Analytics | Transactions | Watchlists | Settings]
─────────────────────────────────────────────────────
Holdings tab:
  [Total Value: $47,320.50] [Daily P&L: +$1,243.18 (+2.69%)]
  [Holdings table: Qty | Avg Cost | Current | Value | Unreal P&L | Daily % | Weight bar]
  AAPL  50  $148.20  $173.42  $8,671  +$1,261 +17.0%  +1.37%  ████░  18.3%
  NVDA   8  $650.00  $924.73  $7,398  +$2,198 +42.3%  +3.14%  ███░░  15.6%

Analytics tab:
  [P&L Curve chart — full-width, 6 months]
  [Risk Metrics row: Sharpe 1.42 | Beta 0.87 | Max Drawdown -8.32% | Vol 14.3%]
  [Sector allocation: bar chart]
  [Asset class: bar chart]
```

---

### 09 — Settings

**Grade: C−**

**What works**:
- State B (System Status) showing service health is actually useful for a technical user
- API configuration is present

**Critical Issues**:

#### F-029 · MAJOR · Settings Is Incomplete for Professional Users
- **Current categories**: API Configuration only + System Status
- **Missing for a professional platform**:
  - **Profile**: Name, email, organization, role (Analyst / Quant / Active Retail / Other)
  - **Notifications**: Per-severity alert routing (push / email / Slack webhook), quiet hours
  - **Data Sources**: Connected broker accounts (SnapTrade integration), data refresh rate
  - **Display**: Default instrument detail tab, chart type (candlestick/OHLC/line), color theme, font size, table density (compact/standard)
  - **Keyboard Shortcuts**: Editable shortcut map (Bloomberg-style terminal commands)
  - **Workspace**: Default panel layout, saved layouts
  - **Account**: Subscription tier, billing, usage limits

#### F-030 · MINOR · Sidebar Navigation Is Missing Settings Sub-Sections
- The settings page uses a sidebar with items "API Keys", "Notifications", "Alerts", "Privacy", "System Status" but the content area only shows API Keys. The other sections appear empty or missing.

---

### 10 — Onboarding

**Grade: C**

**What works**:
- "Connect your first data source" with IB, Alpaca, Manual Import is a reasonable entry point
- Empty state designs (watchlist, graph) communicate what comes next

**Critical Issues**:

#### F-031 · MAJOR · Onboarding Doesn't Match Target Audience
- **Issue**: The onboarding asks users to connect a brokerage first. But the primary value proposition of Worldview is research intelligence, not portfolio tracking. A research analyst at a hedge fund may not want to connect a brokerage — they want to research companies.
- **Better first-run flow**:
  1. **What describes you?** → Researcher / Trader / Active Investor / Quant (personalization)
  2. **Build your watchlist** → Search 3-5 companies you follow
  3. **Your Morning Brief is ready** → Show personalized brief for the watchlist
  4. **Optional: Connect your portfolio** → Brokerage integration (defer, not mandatory)
  5. **Optional: Set up alerts** → One-click template alerts for watchlist
- The current flow forces a technical step (brokerage auth) before showing value. High churn risk.

#### F-032 · MINOR · Empty States Lack Visual Polish
- The empty watchlist and empty graph states are functional annotations but lack the visual richness that makes a first impression memorable. Consider showing a subtle animated placeholder or "suggested first action" with one CTA.

---

### 11 — Alerts

**Grade: B−**

**What works**:
- Alert feed with severity filter tabs (All, Critical, High, Medium, Low) is clean
- Right panel shows alert detail and create alert UI
- Severity color coding is consistent

**Critical Issues**:

#### F-033 · MAJOR · Create Alert Conditions Too Limited
- **Current**: Only shows "Price crosses [value]" as condition type
- **Professional traders need**:
  - Price crosses above/below [value]
  - % change exceeds [threshold] in [timeframe]
  - RSI crosses [level]
  - Volume spike: [N]× average
  - News event: entity mentioned + sentiment [positive/negative]
  - Earnings report filed (SEC 8-K)
  - Analyst rating change
- **Pattern**: Bloomberg's alert system uses: "IF [field] [operator] [value] THEN [notify via channel]" — a simple 3-column condition builder

#### F-034 · MAJOR · No Alert Creation Entry Point in Instrument Detail
- **Issue**: User explicitly requested a "Create Alert" button on the Instrument Detail page for the current ticker. Currently there's no cross-page CTA to alert creation.
- **Fix**: Add `[🔔 Create Alert]` button in the Company/Instrument Detail header actions row (Row 4, alongside Add to Watchlist and Open in Workspace).

---

### 12 — Chat / Brief

**Grade: B+**

**What works**:
- Thread list on left is organized and clean
- Center chat area has good typography and citation handling
- AI/User message differentiation is clear
- Daily Brief section is well-positioned

**Critical Issues**:

#### F-035 · MINOR · Missing Top Nav + Sidebar Consistency
- The Chat/Brief page uses a different/simplified nav structure. Must match the dashboard's top nav bar and sidebar exactly.

#### F-036 · MINOR · Sources Panel Organization
- The right sources panel shows citations but they appear in a linear list without grouping. When a thread has 8+ citations from multiple sources, grouping by source type (Reuters/news, Apple IR/company, Wedbush/analyst) would improve scannability.

---

### MISSING: Workspace / Workstation

**Grade: F — Does Not Exist**

#### F-037 · BLOCKING · Workspace Page Completely Absent
- **Issue**: The Workspace (multi-panel configurable terminal) is the platform's flagship differentiator. It is explicitly one of Worldview's 6 unique capabilities. It appears in the landing page as the primary feature spotlight with an annotated screenshot — yet no actual design exists.
- **This is the most critical missing page for a stakeholder presentation** — they will inevitably ask to see the thing that's being sold as the primary value proposition.
- **Required panels to design**: ChartPanel, NewsFeedPanel, AlertsPanel, ChatPanel, FundamentalsPanel, PredictionMarketsPanel, ScreenerPanel, EntityGraphPanel, HeatmapPanel, PortfolioSummaryPanel, MacroEventsPanel
- **Required layout states**: Default 2×2, 3-panel (chart + news + chat), single-panel expanded, panel settings overlay

---

## Color System Assessment

### Current State
The v1 design uses: near-black background (`#080A0E`) + sky-500 primary (`#0EA5E9`) + amber (`#F0C040`) + teal-green positive (`#26A69A`) + muted red negative (`#EF5350`).

### Assessment

**Strengths**:
- The near-black background is appropriately dark and serious
- Sky-500 primary creates a distinct identity (not generic blue-500)
- Amber for AI content creates an instant visual language ("amber = AI")
- Teal-green positive is more professional than generic green-500

**Issues**:
- The **amber yellow** (`#F0C040`) is the right hue but may be too bright in isolation. Testing against the `$card` background (`#10141C`) and verifying WCAG AA contrast ratio (≥4.5:1) is needed.
- The **yellow-black combination** the user suggested (full amber/yellow as primary, not just AI indicator) would create a Bloomberg-terminal feel. Worth testing as Variant B.
- The **red accent** (negative `#EF5350`) is only used for down prices — it never serves a constructive role. Consider using `$negative` ONLY for price data, never for navigation or CTAs.
- **Proposed 3 variants to test** (as separate design strips):
  - **Variant A**: Current (sky-500 primary + amber AI)
  - **Variant B**: Amber/Gold primary everywhere (Bloomberg DNA — `#F0C040` CTAs)
  - **Variant C**: Deeper amber-orange primary (`#FB8B1E`, Bloomberg Terminal exact)

---

## Full Issue Inventory

| ID | Severity | Page | Category | One-Line Summary |
|----|----------|------|----------|-----------------|
| F-001 | CRITICAL | Landing | Copy | "Everything a serious analyst needs" — wrong register |
| F-002 | CRITICAL | Landing | Copy | "Finally, a Bloomberg alternative that's actually affordable" — budget positioning |
| F-003 | MAJOR | Landing | Content | Unstructured data / NLP capabilities absent from feature section |
| F-004 | MINOR | Landing | Color | Amber CTA harshness on near-black |
| F-005 | MINOR | Landing | Mobile | State C is annotation only |
| F-006 | BLOCKING | Dashboard | Structure | States A/B/C outside design column (x=1540) |
| F-007 | MAJOR | Dashboard | Feature | Search bar missing from top nav |
| F-008 | MAJOR | Dashboard | Design | No color variants tested |
| F-009 | MINOR | Dashboard | Content | Status bar missing bonds, FX, commodities, crypto |
| F-010 | BLOCKING | Company Detail | Chart | Bar chart not candlestick OHLCV |
| F-011 | MAJOR | Company Detail | Layout | Instrument brief not integrated into header |
| F-012 | MAJOR | Company Detail | Intelligence Tab | Entity graph too simplistic (no edges, no layout) |
| F-013 | MAJOR | Company Detail | News Tab | News tab position conflict — needs investigation |
| F-014 | MINOR | Company Detail | Structure | Graph should be subtab, not standalone page |
| F-015 | BLOCKING | Markets | Structure | Missing top nav and sidebar |
| F-016 | MAJOR | Markets | Purpose | Markets and Intelligence should merge |
| F-017 | MAJOR | Markets | Content | Missing asset class tabs (ETFs, Crypto, Bonds, FX) |
| F-018 | MINOR | Markets | Content | No macro events integration |
| F-019 | BLOCKING | Intelligence | Structure | Missing top nav and sidebar |
| F-020 | MAJOR | Intelligence | Layout | Left filter panel too wide |
| F-021 | MINOR | Intelligence | Content | Entity spotlight lacks prediction markets + graph preview |
| F-022 | CRITICAL | Graph | Purpose | Standalone graph page has no workflow rationale |
| F-023 | BLOCKING | Screener | Structure | Missing top nav and sidebar |
| F-024 | MAJOR | Screener | Feature | Filter builder too simple — no multi-condition criteria |
| F-025 | MAJOR | Screener | Feature | No pre-built screen templates |
| F-026 | MINOR | Screener | Feature | No export function |
| F-027 | BLOCKING | Portfolio | Version | Old design active — not redesigned |
| F-028 | BLOCKING | Portfolio | Content | Complete strategy-centric redesign required |
| F-029 | MAJOR | Settings | Content | Settings incomplete — profile, notifications, display missing |
| F-030 | MINOR | Settings | Navigation | Sub-section content missing |
| F-031 | MAJOR | Onboarding | UX Flow | Brokerage-first flow creates friction before showing value |
| F-032 | MINOR | Onboarding | Polish | Empty states lack visual polish |
| F-033 | MAJOR | Alerts | Feature | Create alert conditions too limited |
| F-034 | MAJOR | Alerts | Cross-page | No alert creation CTA from Instrument Detail |
| F-035 | MINOR | Chat/Brief | Structure | Inconsistent nav vs dashboard |
| F-036 | MINOR | Chat/Brief | Content | Sources panel lacks grouping |
| F-037 | BLOCKING | Workspace | Existence | Page does not exist — critical for stakeholder demo |

**Severity totals**: BLOCKING=7, CRITICAL=3, MAJOR=18, MINOR=9 → **Total: 37 findings**

---

## Implementation Wave Plan

All waves are for canvas design work in `worldview-mvp_v1.pen`. Execution skill: `/design-ui` per wave.

---

### Wave 0 — Structural Fixes (Day 1, ~2h)
**Priority: BLOCKING blockers before any other design work**

Tasks:
- [ ] **W0-1**: Move dashboard states A/B/C (fBOiy, UbwGX, NZEgU) inside the `vsdgH` frame — correct column positioning
- [ ] **W0-2**: Add global ticker search bar to top nav on Dashboard State A (between market strip and notification bell)
- [ ] **W0-3**: Propagate search bar to all pages that currently have a top nav (Company Detail, Markets, Intelligence, Screener, Chat, Alerts)
- [ ] **W0-4**: Add standard top nav + sidebar to Markets page, Intelligence page, Screener page, Chat page, Alerts page
- [ ] **W0-5**: Rename "03-Company-Detail" → "03-Instrument-Detail" across all frames
- [ ] **W0-6**: Remove 06-Graph as a navigation menu item (keep frame for reference but add "DEPRECATED" note)

**Acceptance criteria**: Every app page has consistent top nav (44px) + sidebar (200px) + status bar (24px).

---

### Wave 1 — Candlestick Chart (Day 1–2, ~3h)
**Priority: Most visible professional credibility signal**

Tasks:
- [ ] **W1-1**: Redesign chart in Company Detail Overview tab as proper OHLCV candlestick:
  - Green candles (close > open): green body, thin wicks to high/low
  - Red candles (close < open): red body, thin wicks
  - Volume sub-panel below (20% height), bars colored by direction
  - MA50 line in amber, MA200 line in sky-500
  - Y-axis right-aligned, IBM Plex Mono, price levels
  - X-axis: date labels
  - Timeframe tabs: 1D | 1W | 1M | 3M | 1Y | All
  - Indicator toggles: MA50 | MA200 | Volume
- [ ] **W1-2**: Ensure the same chart renders correctly in Fundamentals tab context (smaller, since accordion takes space)
- [ ] **W1-3**: Ensure chart is consistent with the landing page hero screenshot (which showed a proper candlestick chart — align both)

**Acceptance criteria**: Any professional trader would recognize this as a real candlestick chart.

---

### Wave 2 — Landing Page Copy + Color Variants (Day 2, ~2h)

Tasks:
- [ ] **W2-1**: Replace "Everything a serious analyst needs" → test 3 options in canvas:
  - Option A: "The edge no single platform delivers"
  - Option B: "Six capabilities, zero compromises"
  - Option C: "From filing to thesis. In minutes."
- [ ] **W2-2**: Replace "Finally, a Bloomberg alternative that's actually affordable" → test 3 options:
  - Option A: "Bloomberg depth. No lock-in."
  - Option B: "Institutional-grade research. Independent pricing."
  - Option C: "The full stack. At independent researcher pricing."
- [ ] **W2-3**: Add "unstructured data" capability spotlight in feature section: "Every 10-K, every earnings call, every filing — structured by AI into searchable intelligence. Not headlines. Understanding."
- [ ] **W2-4**: Create 3 color variant strips (same morning brief card + sector tile + nav item):
  - Variant A: Current (sky-500 primary + amber AI)
  - Variant B: Amber/Gold primary everywhere (Bloomberg DNA)
  - Variant C: Amber-orange primary (`#FB8B1E`)
- [ ] **W2-5**: Place color variant strips as a row on the canvas for side-by-side comparison

**Acceptance criteria**: Marketing copy uses professional register. Three color options available for stakeholder decision.

---

### Wave 3 — Instrument Detail: Header + Brief Integration + Chart (Day 2–3, ~3h)

Tasks:
- [ ] **W3-1**: Integrate instrument brief inline with header — add collapsible "AI BRIEF" row below 52w range bar
- [ ] **W3-2**: Redesign Overview tab right panel — remove instrument brief card, add: key metrics 3×3 + analyst consensus only
- [ ] **W3-3**: Redesign Intelligence tab entity graph:
  - Force-directed layout with visible edges between nodes
  - Edge labels: relationship type text
  - Node type color differentiation (company=sky-blue, person=green, fund=purple)
  - Graph controls panel: depth (2/3-hop), confidence threshold slider
- [ ] **W3-4**: Investigate and fix News tab position overlap — verify State D (jZEVF) is correctly positioned
- [ ] **W3-5**: Add "Create Alert for NVDA" button to header actions row (alongside Watchlist + Workspace buttons)
- [ ] **W3-6**: Redesign News tab with proper article cards: score | tier badge | impact sparkline | headline | excerpt | entity chips
- [ ] **W3-7**: Ensure sidebar in all Company Detail states matches the dashboard sidebar exactly (including watchlist section)

**Acceptance criteria**: All 5 tabs look complete and professional. Alert creation entry point exists. Graph is visually credible.

---

### Wave 4 — Markets + Intelligence Merge (Day 3, ~2h)

Tasks:
- [ ] **W4-1**: Redesign Markets page as unified "Markets & Intelligence":
  - Left 60%: S&P 500 treemap heatmap (tabs: S&P 500 | NASDAQ | Russell 2000 | ETFs | Crypto)
  - Right 40%: News feed with tier filter (DEEP/MEDIUM/LIGHT) + entity filter
  - Below heatmap: Sector performance bars + Macro events strip
  - Full top nav + sidebar matching dashboard
- [ ] **W4-2**: Remove Intelligence as a separate page OR keep as "News" (standalone news feed for users who want just the news view)
- [ ] **W4-3**: Add cross-asset tabs to the Markets page: Equities | Bonds | FX | Commodities | Crypto

**Acceptance criteria**: A professional trader can see market context + news drivers on a single page without navigation.

---

### Wave 5 — Portfolio Complete Redesign (Day 3–4, ~4h)

Tasks:
- [ ] **W5-1**: Redesign the portfolio page from scratch following REDESIGN_PLAN.md spec:
  - Page header: "My Strategies" + `[+ Create Strategy]`
  - 3 StrategyCards: Growth Portfolio, Dividend Income, Quant Momentum
  - Each card: strategy name, total value (large mono), daily P&L (colored), holding count, 5d sparkline
- [ ] **W5-2**: Holdings tab (below selected strategy):
  - Holdings table: Qty | Avg Cost | Current | Value | Unreal P&L | Daily % | Weight bar
  - Footer: total positions, total value, unrealized P&L
- [ ] **W5-3**: Analytics tab:
  - P&L curve chart (6 months, full width)
  - Risk metrics row: Sharpe, Beta, Max Drawdown, Volatility, Alpha
  - Sector exposure bar chart
  - Top 5 holdings by weight
- [ ] **W5-4**: Transactions tab: date | ticker | action (BUY/SELL) | qty | price | total | notes
- [ ] **W5-5**: Add standard top nav + sidebar

**Acceptance criteria**: Portfolio page could be shown to a portfolio manager without embarrassment.

---

### Wave 6 — Workspace / Workstation Design (Day 4–5, ~5h)

Tasks:
- [ ] **W6-1**: Create new page frame: 13-Workspace (1440×900px)
- [ ] **W6-2**: Design default 2×2 layout:
  - Top-left (6 cols × 6 rows): ChartPanel (NVDA, 1D candlestick)
  - Top-right (6 cols × 6 rows): NewsFeedPanel
  - Bottom-left (6 cols × 5 rows): AlertsPanel
  - Bottom-right (6 cols × 5 rows): ChatPanel
- [ ] **W6-3**: Panel wrapper design: drag handle bar + panel label chip + active ticker chip + [Link 🔗] + [Minimize] + [✕ Close]
- [ ] **W6-4**: Top workspace bar: active ticker context chip + `[+ Add Panel]` + `[Save Layout]` + `[Reset Default]`
- [ ] **W6-5**: Add Panel overlay design: modal showing 11 panel types as a grid with icons and names
- [ ] **W6-6**: Design "linked panels" state — when ticker changes in ChartPanel, NewsFeedPanel and ChatPanel update to show the same ticker
- [ ] **W6-7**: Alternative layout state: 3-panel (chart 50% + news 25% + chat 25%)

**Acceptance criteria**: A Bloomberg/IB TWS user would immediately understand the workspace concept and value.

---

### Wave 7 — Screener Enhancement (Day 5, ~2h)

Tasks:
- [ ] **W7-1**: Add standard top nav + sidebar to Screener page
- [ ] **W7-2**: Redesign filter builder:
  - Add `[+ Add Filter]` button opening popover
  - Popover: [Field ▼] [Operator ▼] [Value] [Add] — field dropdown shows categorized metrics
  - Conditions display: existing chips PLUS show full condition (e.g., "Mkt Cap > $100B × ")
- [ ] **W7-3**: Add `[Load Screen ▼]` dropdown with 8 pre-built templates: Graham Value | High Momentum | RSI Oversold | Insider Buying | Revenue Growth | Dividend Yield | AI Positive Signal | Technical Breakout
- [ ] **W7-4**: Add `[Export CSV]` button to top-right of results
- [ ] **W7-5**: Add column customizer: `[⚙ Columns]` button that opens a checkbox list of available columns

**Acceptance criteria**: A Finviz Elite user could replicate their screening workflow here.

---

### Wave 8 — Settings Redesign (Day 5–6, ~2h)

Tasks:
- [ ] **W8-1**: Redesign Settings page with full category sidebar:
  - Profile | Notifications | Data Sources | Display | Keyboard Shortcuts | Workspace | Account
- [ ] **W8-2**: Profile tab: name, email, role (dropdown), organization, avatar initials
- [ ] **W8-3**: Notifications tab: per-severity routing (push/email/Slack), quiet hours toggle, watchlist price alerts, earnings notifications
- [ ] **W8-4**: Display tab: default instrument tab, chart type, table density (Compact/Standard/Spacious), font size
- [ ] **W8-5**: Keep existing API Configuration as "Data Sources" tab
- [ ] **W8-6**: Keep existing System Status as "System" tab

**Acceptance criteria**: Settings page looks like a professional SaaS product, not a developer's config panel.

---

### Wave 9 — Onboarding Redesign (Day 6, ~2h)

Tasks:
- [ ] **W9-1**: Redesign onboarding flow as role-first:
  - Step 1: "What best describes you?" → Researcher / Trader / Active Investor / Quant
  - Step 2: "Build your watchlist" → search 5 companies/tickers → live preview of morning brief generating
  - Step 3: "Your briefing is ready" → show morning brief for watchlist
  - Step 4: Optional — "Connect portfolio" → IB/Alpaca/Manual or Skip
  - Step 5: Optional — "Set your first alert" → one template per role or Skip
- [ ] **W9-2**: Each step has visual progress indicator (Step 1 of 5)
- [ ] **W9-3**: Skip option on steps 4–5 for users who want to explore first
- [ ] **W9-4**: Completion screen: "Your intelligence platform is ready" with shortcut buttons to Dashboard, Screener, Search

**Acceptance criteria**: A non-technical research analyst can complete onboarding in < 3 minutes.

---

### Wave 10 — Polish and Consistency Pass (Day 6–7, ~3h)

Tasks:
- [ ] **W10-1**: Audit every page for sidebar consistency (expanded 200px, same nav items, watchlist section, alerts section)
- [ ] **W10-2**: Verify IBM Plex Mono is applied to ALL numeric values across all pages
- [ ] **W10-3**: Verify `$border` (1px visible border) exists on every panel on every page
- [ ] **W10-4**: Add "Create Alert for ticker" button to Company Detail header on all tab states
- [ ] **W10-5**: Status bar consistency — same content on all pages (SPX, NDX, VIX, US10Y, DXY, WTI, BTC)
- [ ] **W10-6**: Update Design System page with: new candlestick chart component, workspace panel wrapper component, strategy card component, sector heat tile all-states

---

## Competitive Intelligence Summary (from research)

### What Bloomberg/TradingView do better (key patterns to replicate):

**Charts**: TradingView's chart panel has: toolbar with drawing tools, indicator search, left Y-axis price scale, right Y-axis volume-weighted, price alert line (drag to set), crosshair with OHLCV tooltip on hover. The key differentiator is the **hover tooltip** — when hovering over any candle, show: O: $870.20 H: $891.40 L: $868.50 C: $875.40 V: 48.2M.

**Screener (Bloomberg)**: Bloomberg's equity search uses a natural language + structured filter combination. Users can type "tech stocks P/E < 30 with positive earnings surprise" or use the structured query builder. The key is that Bloomberg's result table has **column resizing by drag**, **right-click to add to watchlist**, and **sort by clicking header**.

**Screener (Finviz)**: Finviz's power is in its preset filter categories. Each category (Descriptive, Fundamental, Technical, All) has dropdowns showing all available values. The key is the **"run" button** — you build criteria and run the screen. Results show a heatmap view AND a table view. Export to CSV is prominent.

**Workspace (Bloomberg)**: Bloomberg's terminal layout uses launchpad "pages" (named layouts). You can have multiple pages (Morning Research, Trading, Portfolio) each with different panel arrangements. Panels are windows, draggable and resizable. Each window has a command line at the top.

**Portfolio (IB TWS)**: TWS shows: unrealized P&L in green/red, realized P&L separately, delta, gamma for options, risk weighted value per position. Key: **color-coding the entire row** (not just the P&L column) — the whole row turns green/red based on daily performance.

### What professional traders actually value:
1. **Speed of information retrieval** — Bloomberg's famous command-line approach lets professionals navigate in 2 keystrokes. Worldview needs keyboard shortcuts.
2. **Data trust** — professionals evaluate source quality. Worldview's tier system (DEEP/MEDIUM/LIGHT) and citation grounding are strong differentiators here.
3. **Cross-asset context** — no tool is used in isolation. Bond yields affect equity multiples. Worldview needs to show cross-asset data prominently.
4. **Workflow continuity** — professionals hate switching tabs. The workspace multi-panel approach addresses this directly.

### What messaging converts professionals:
- **Does NOT work**: "affordable", "easy", "all-in-one", "powerful", "modern"
- **Does work**: "research edge", "from filing to thesis", "before the market moves", "conviction-backed analysis", "what your Bloomberg doesn't show you"
- **The strongest angle for Worldview**: "Bloomberg indexes news headlines. Worldview indexes entity relationships, filing claims, and market impact." — this is the knowledge graph + NLP angle that no competitor touches.

---

## Stakeholder Readiness Assessment

| Page | Ready for Demo? | Blocker |
|------|----------------|---------|
| Landing | YES (with copy fixes) | F-001, F-002 (copy) |
| Dashboard | YES (after move) | F-006 (structural position) |
| Instrument Detail (Overview) | NO | F-010 (chart) |
| Instrument Detail (Fundamentals) | YES | — |
| Instrument Detail (Intelligence) | PARTIAL | F-012 (graph) |
| Instrument Detail (News) | UNKNOWN | F-013 (position) |
| Instrument Detail (Chat) | YES | — |
| Markets | NO | F-015 (nav) |
| Intelligence | NO | F-019 (nav) |
| Screener | NO | F-023 (nav) |
| Portfolio | NO | F-027, F-028 (not redesigned) |
| Alerts | YES | F-034 (CTA from detail) |
| Chat/Brief | YES | F-035 (nav) |
| Workspace | NO | F-037 (doesn't exist) |
| Settings | PARTIAL | F-029 (incomplete) |
| Onboarding | PARTIAL | F-031 (wrong flow) |

**Bottom line for stakeholders**: Dashboard + Landing + Fundamentals tab + Chat tab can be demo'd now. Everything else needs work ranging from minor nav fixes to complete rebuilds. The candlestick chart, portfolio redesign, and workspace creation are the three highest-ROI efforts before any stakeholder demo.

---

## Next Steps

1. **Immediate** (before any demo): Execute Wave 0 (structural fixes) and Wave 1 (candlestick chart)
2. **Day 2–3**: Wave 2 (landing copy + color variants), Wave 3 (instrument detail)
3. **Day 3–4**: Wave 4 (markets merge), Wave 5 (portfolio)
4. **Day 4–5**: Wave 6 (workspace — highest effort, critical for pitch)
5. **Day 5–6**: Waves 7–9 (screener, settings, onboarding)
6. **Day 6–7**: Wave 10 (polish pass)

Invoke `/design-ui <wave-description>` for each wave.
