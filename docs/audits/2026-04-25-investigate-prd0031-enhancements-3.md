# Investigation Report: PRD-0031 Enhancement Session 3 — BlackRock Readiness

**Date**: 2026-04-25
**Investigator**: Claude Code (investigation skill)
**Severity**: N/A (feature investigation — presentation readiness)
**Status**: All decisions confirmed — PRD-0031 updated
**Context**: Platform must be shown to a head of BlackRock. Institutional excellence is the minimum bar.

---

## 1. Issue Summary

Seven design questions requiring investigation and decisions:
1. Portfolio: tabs vs. boxes on a single page?
2. Fundamentals tab: what does an institutional analyst expect?
3. Chat page: how does Bloomberg GPT compare, what must be added?
4. Intelligence tab: signal quality, confidence display, depth indicators?
5. News page: Bloomberg-grade news feed requirements?
6. Alerts page: rule management, grouping, acknowledgment?
7. Workspace: presets, all 10 panel types, resize, symbol linking?

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|---|---|---|
| Bloomberg PORT uses tabs (Positions/Transactions/Risk) | Agent 1 research | Validates Worldview tab pattern |
| BlackRock Aladdin uses tabbed portfolio (Holdings/Transactions/Analytics/Reports) | Agent 1 research | Tabs confirmed as institutional standard |
| tastytrade, IBKR, Fidelity ATP all use tab-based portfolio | Agent 1 research | Universal industry pattern |
| Fundamentals tab missing: analyst consensus, debt metrics, cash flow, peer context | Agent 1 codebase audit | 4 new sections required |
| Chat: supports 7 intent types, has citations, no starter questions, no context injection | Agent 2 codebase audit | 4 chat enhancements required |
| Intelligence: shows contradictions only — not market_impact_score, not routing_tier | Agent 2 codebase audit | 5 intelligence enhancements required |
| News: no category filtering, no watchlist tab, no read/unread | Agent 3 codebase audit | 5 news enhancements required |
| Alerts: no rule builder, no grouped display, no ACK/snooze | Agent 3 codebase audit | 5 alert enhancements required |
| Workspace: 8 of 10 panel types implemented; no resize; no named workspaces | Agent 4 codebase audit | Watchlist + Brief panels missing; 4 presets needed |

---

## 3. Decisions (D-11 through D-17)

### D-11: Portfolio Layout — TABS ARE CORRECT (confirmed, no change)

**Question**: Should Holdings/Transactions/Watchlists/Brokerages be tabs or a unified scroll page?
**Answer**: KEEP TABS. This is the institutional standard.

Evidence: Bloomberg PORT (Positions → Transactions → Risk Dashboard) uses tabs. BlackRock Aladdin uses tabbed portfolio navigation. Interactive Brokers TWS uses separate windowable panels per section. tastytrade, Fidelity Active Trader Pro all use tabs.

**Why tabs are correct here**:
- Holdings (live P&L) and Transactions (historical audit) are fundamentally different mental modes — forcing them onto one page creates cognitive overload
- Transactions lazy-load only when tab is clicked (current behavior) — avoids unnecessary API calls
- Watchlists are a discovery/monitoring concern separate from portfolio management — mixing them on one page confuses the user's workflow
- Brokerages are admin/settings content — rarely accessed, belongs at the back

**The current code comment in `portfolio/page.tsx` lines 9–15 is exactly right.** The tab rationale is:
- Holdings = "Where is my money?"
- Transactions = "What did I do recently?"
- Watchlist = "What am I watching?"
- Brokerages = "Is my data pipeline healthy?"

No structural change. Enhancements are within each tab.

---

### D-12: Fundamentals Tab — 4 New Sections for Institutional Grade

**Current state**: 6 sections, 19 metrics. Solid but retail-grade.
**Target**: Bloomberg DES-equivalent. An institutional analyst opening this tab must not feel they need to open Bloomberg.

**New section 1: Analyst Consensus** (top of tab, most prominent)
```
ANALYST CONSENSUS  ────────────────────────────────────────────────────────────
Consensus             BUY       [███████████ Buy: 18 | Hold: 9 | Sell: 3]
12M Price Target      $210.00   High: $240 │ Median: $210 │ Low: $162
EPS Est. (FY 2026E)   $6.84     [↑ from $6.52 three months ago]
Revenue Est. (2026E)  $396B     [↑ from $389B estimate revised up]
# Analysts            32        Updated: Apr 22, 2026
```
- Source: EODHD analyst consensus (if available) — show "N/A — analyst data requires premium data feed" if not
- Estimate rows: use subtle `bg-muted/40` background to visually distinguish forward estimates from trailing actuals
- Rating bar: horizontal pill bar (green/grey/red segments proportional to counts)
- Revision arrow: `↑` (teal) or `↓` (red) next to estimate if estimate changed significantly in past 90 days

**New section 2: Debt & Credit** (after Balance Sheet)
```
DEBT & CREDIT  ────────────────────────────────────────────────────────────────
Interest Coverage     45.2×     [EBIT / Interest Expense — > 5× = healthy]
Net Debt / EBITDA     -0.7×     [negative = net cash position]
Debt Due < 1Y         $2.3B
Debt Due 1–3Y         $8.4B
Debt Due > 3Y         $95.2B
Credit Rating         AA+       [S&P, updated Dec 2025]
```
- Interest coverage color: `text-positive` if > 5×, `text-warning` if 2.5–5×, `text-negative` if < 2.5×
- Source: EODHD fundamentals + balance sheet fields
- Credit rating: if not available, show `—` — never leave blank

**New section 3: Cash Flow** (after Debt & Credit)
```
CASH FLOW (TTM)  ──────────────────────────────────────────────────────────────
Operating Cash Flow   $122.2B   [+12.4% YoY]
Capital Expenditure   $11.8B
Free Cash Flow        $110.4B   [= OpCF − CapEx]
FCF Margin            28.7%     [FCF / Revenue — higher is better]
Cash Conversion       90.5%     [OpCF / Net Income — > 100% is ideal]
```
- FCF Margin and Cash Conversion are color-coded: > 20% FCF margin = `text-positive`

**Enhancement to existing Valuation section: peer context**
```
VALUATION  ────────────────────────────────────────────────────────────────────
P/E Ratio (TTM)       28.4×     [vs Sector: 22.1× — premium]
Forward P/E           26.2×     [vs Sector: 20.5× — premium]
EV/EBITDA             18.9×     [vs Sector: 15.2× — premium]
PEG Ratio             2.3×      [P/E ÷ 5Y EPS growth rate]
```
- "vs Sector" in `text-muted-foreground` after each value — shows context without cluttering
- "premium" / "discount" / "inline" label based on premium/discount to sector

**Footer data freshness**:
- Already exists (code shows "Updated X minutes ago") ✓
- Add: "Estimates: N analysts · EODHD · Updated [date]" with `StaleDataBadge` if > 7 days old

**Implementation note**: Most of these fields are in EODHD fundamentals already imported into S3. The frontend just needs to display them. Analyst consensus requires a separate API call or data pipeline enhancement.

---

### D-13: Chat Page — 4 Institutional Enhancements

**Current state**: Two-column layout (threads + messages), SSE streaming, 7 intent types, citations as superscripts `[1]`. No starter questions, no context injection.

**Enhancement 1: Suggested Starter Questions (empty state)**

When a conversation has no messages, show 6 finance-specific prompt cards:
```
┌──────────────────────────────────────────────────────────────────┐
│  INTELLIGENCE CHAT                                               │
│  Ask research-grade questions about companies, markets, signals  │
│  ──────────────────────────────────────────────────────────────  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ What are the key risks   │  │ Compare MSFT and GOOGL cloud │  │
│  │ for [TICKER] next qtr?   │  │ revenue growth               │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ Summarize AAPL's latest  │  │ Recent insider transactions  │  │
│  │ earnings call            │  │ and what they signal         │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
│  ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│  │ What consensus estimates │  │ Search SEC filings for       │  │
│  │ show for [TICKER] 2026?  │  │ "supply chain" risks         │  │
│  └──────────────────────────┘  └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```
- Cards: `rounded-[2px] border border-border hover:border-primary/40 p-3 cursor-pointer text-[12px]`
- Clicking a card: injects the text into the input (user can edit before sending)
- `[TICKER]` placeholder: if context entity is available, auto-fill with the current entity name

**Enhancement 2: Context awareness (instrument page → chat)**

When user navigates from `/instruments/[entityId]` to `/chat`, or when `/chat?entity_id=X` URL param is present:
- Show amber badge: `[Context: AAPL — asking about Apple Inc.]` above the input
- Auto-populate the 6 starter questions with `[TICKER]` replaced by "AAPL"
- Inject a system context message (invisible to the user, sent as a hidden instruction) telling the RAG pipeline to bias towards AAPL-related documents
- Implementation: pass `entity_id` in the `/chat/stream` POST body (already supported by S8's `PORTFOLIO` intent)

**Enhancement 3: Citation type badges**

Current: `[1] Earnings Report — 87%`
Enhanced:
```
Sources:
[1] 📄 SEC 10-Q (Oct 2024) · Apple Inc. quarterly filing · 87% match
[2] 📰 Reuters · "Apple supply chain concerns" · 92% match
[3] 📊 Earnings Call · Q4 2024 Transcript · 78% match
```
- Source type icons: 📄 = SEC filing, 📰 = news, 📊 = earnings transcript, 🕸 = entity knowledge base
- Badge colors: SEC = `bg-primary/20`, news = `bg-muted`, earnings = `bg-positive/20`

**Enhancement 4: Thread naming**

Current: threads auto-named (truncated from first message).
Enhanced: double-click thread name in sidebar → inline rename (`contentEditable` span, Enter to confirm). Store custom name in localStorage keyed by thread ID. Visually distinguish renamed threads with a subtle pencil icon.

---

### D-14: Intelligence Tab — Signal Quality Depth

**Current state**: Entity graph + AI brief + contradictions list with HIGH/MED/LOW labels.
**Target**: Sell-side analyst quality — evidence-grade signal display.

**Enhancement 1: market_impact_score visual bar per signal**
```
[H] Management change      [▓▓▓▓▓▓▓▓░░] 87   SEC, WSJ   2d ago
[M] Supply chain risk      [▓▓▓▓▓░░░░░] 61   Reuters    5d ago
[L] New product patent     [▓▓░░░░░░░░] 34   USPTO      3w ago
```
- Progress bar: 10-segment horizontal bar using `--positive` color, proportional to `market_impact_score` (0–100)
- Score right-aligned in monospace after the bar

**Enhancement 2: Signal quality badges per row**

Each signal gets 2 inline badges:
- Routing tier: `DEEP` (teal, full extraction) | `MED` (yellow, partial) | `LIGHT` (grey, minimal)
- Novelty: `NEW` (if novelty_score > 0.85) | `DUP` (red, if < 0.40, meaning we've seen this claim before)

```
[H] Management change  [DEEP] [NEW]   87   SEC, WSJ   2d ago    [▾]
[M] Supply chain risk  [MED]  [DUP]   61   Reuters    5d ago    [▾]
```

**Enhancement 3: Confidence + resolution stage**

Expand row shows:
```
▾ Management change
   Claim: "CEO Tim Cook announces departure effective Q2 2026"
   Confidence: 98%  (Stage 1 — Direct alias match)
   Source: Apple Inc. Form 8-K filed Dec 15, 2024
   Novelty: 0.94 — Novel claim (no similar prior claims detected)
   [View source document ↗]
```

**Enhancement 4: Signal type distinctions**

Currently only "contradictions". Add signal type column:
- `CLAIM` — extracted factual claim from DEEP article
- `EVENT` — detected corporate event (earnings, exec change, M&A)
- `CONTRADICTION` — two conflicting claims detected
- `RELATION` — entity relationship update (new competitor, new supplier)

**Enhancement 5: Temporal histogram (signal volume chart)**

Above the signal list, a 30px-tall mini histogram showing signal count by week over the last 90 days. Hovering a bar filters the signal list to that week. Helps analysts spot "when did intelligence spike for this company?"

---

### D-15: News Page — 5 Bloomberg-Grade Enhancements

**Current state**: 3 tabs (Alerts | News Feed | Top Today), relevance score shown, routing tiers visible, no category filters, no watchlist feed, no read/unread.

**Enhancement 1: Category Filter Rail** (most impactful)
```
[All] [Earnings] [M&A] [Regulatory] [Macro] [Analyst] [SEC Filings]
```
- Persistent filter chips above the news feed
- Active chip: `bg-primary/20 text-primary border border-primary/40`
- Filters server-side via `?categories=earnings,ma` param (requires S9 news endpoint extension)
- Category detection: from NLP pipeline article classification (already done in Block 10)

**Enhancement 2: Watchlist-Filtered News Tab**

Add 4th tab `[My Holdings News]` or `[Watchlist]`:
- Queries `GET /v1/news/top?entity_ids=<comma-separated-watchlist-entity-ids>`
- Client-side entity_id list built from active watchlist members
- Empty state: "Connect a watchlist or brokerage to see news for your holdings"
- This is the most valuable news feature for a portfolio manager

**Enhancement 3: Read/Unread State**

- Articles scroll into view → mark as read (IntersectionObserver, no click required)
- Read articles: `opacity-60` on title + source
- Unread count badge on tab (e.g., `[News Feed (12 unread)]`)
- "Mark all read" button at top right of feed
- State stored in `localStorage['worldview-read-articles']` as Set of article IDs

**Enhancement 4: Holdings Mention Highlights**

Per article row, show tickers from user's portfolio/watchlist that are mentioned in that article:
```
[HI] Reuters  2h  94  Apple Q1 Earnings Beat All Estimates  [AAPL ▲]  ↗
```
- `[AAPL ▲]` badge: `bg-positive/20 text-positive font-mono text-[10px]` — shows ticker is in portfolio with current direction
- Up to 3 badges; overflow: `+2`
- Data: cross-reference article `entity_mentions` with user's holdings tickers (client-side join)

**Enhancement 5: Impact Score Sorting + Visual**

Current: shows relevance score (0–100) as plain number.
Enhanced:
- Show a colored dot before the score: green (>75), yellow (50–75), red (<50)
- Sort options: `[RELEVANCE ▾] [IMPACT ▾] [NEWEST ▾]` — default = RELEVANCE
- IMPACT sort uses `market_impact_score` (price-movement correlation, from S6 price-impact labeling)

---

### D-16: Alerts Page — 5 Institutional-Grade Enhancements

**Current state**: WebSocket real-time feed, severity filter, AlertRow with badge/ticker/message. No rule builder, no grouping, no ACK/snooze.

**Enhancement 1: Alert Rule Builder**

`[+ Create Alert]` button → slide-over panel (not modal, so they can still see alerts):
```
CREATE ALERT RULE
──────────────────
Rule Type:   [Price Threshold ▾]

Options:
  Price Threshold:  [Entity search ▾]  [crosses ▾]  [$][150.00]  [↑/↓/either]
  Volume Spike:     [Entity search ▾]  [volume >]   [3][× avg]
  News Signal:      [Entity search ▾]  [impact >]   [75]
  Portfolio Risk:   [Position > ]      [10][% portfolio]

Notify via:  [✓ In-app]  [☐ Email]
Label:       [optional description...]

[Save Rule]  [Cancel]
```
- Slide-over: 320px, `fixed right-0 top-0 h-full bg-card border-l border-border`
- Entity search uses `GET /v1/search?q=X`
- Saves to future `POST /v1/alerts/rules` endpoint; for now, store in localStorage as preview

**Enhancement 2: Severity-Grouped Display**

Replace flat chronological list with grouped sections:
```
● CRITICAL  (2)                                      [ACK ALL]
  AAPL  PRICE_SPIKE     +8.2% in 15min — vol 3× avg    2m   [ACK]
  Risk  CONCENTRATION   Position > 15% of portfolio       1m   [ACK]

● HIGH  (4)
  MSFT  EARNINGS_BEAT   EPS $2.94 vs $2.81 est            1h   [ACK]
  ...

● MEDIUM  (7)
  ...
```
- Each group header: `text-[10px] uppercase text-muted-foreground border-b border-border py-1`
- CRITICAL header: `text-negative`; HIGH: `text-warning`; MEDIUM: `text-muted-foreground`
- `[ACK ALL]` button on each group header: acknowledges all in that severity level

**Enhancement 3: Alert Management Panel**

Toggle via gear icon `⚙` at top right of alerts page:
- Right slide-over (320px): shows "Active Rules (N)" list
- Per rule: rule summary text | toggle on/off | `[✕]` delete
- Footer: `[+ Add Custom Rule]` button
- Preview of system rules (portfolio risk alerts, predefined defaults)

**Enhancement 4: Portfolio-Wide Risk Alerts (system alerts)**

Pre-configured non-editable system alerts that fire automatically:
- `CONCENTRATION` — when any single position exceeds 15% of total portfolio value
- `SECTOR_CONCENTRATION` — when any GICS sector exceeds 40% of portfolio
- `DRAWDOWN_5` — when portfolio day P&L < -5%
- `DRAWDOWN_10` — when portfolio day P&L < -10% from 20-day high water mark
- These appear labeled `[SYS]` in the alert feed to distinguish from user rules
- Computed client-side from live portfolio data (no backend required for initial impl)

**Enhancement 5: ACK + Snooze + History**

Per alert row:
- `[ACK]` button: marks alert as acknowledged; moves to "Acknowledged" section at bottom
- Hover `[ACK]` → dropdown: `Acknowledge | Snooze 1h | Snooze 4h | Dismiss`
- Acknowledged alerts: shown in collapsed "Acknowledged (N)" section at bottom of feed, 40% opacity
- Archive tab: "History" tab shows all acknowledged/dismissed alerts from last 24h

---

### D-17: Workspace — Complete 10 Panel Types + Presets

**Current state**: 8 of 10 panel types implemented; Watchlist and Brief panels missing. No drag-to-resize. No named workspaces. Panel headers 32px (oversized). Two placeholders still showing (Screener + Chat).

**Complete panel type specifications** (all 10):

| Panel | Min size | Key content | Data source |
|---|---|---|---|
| Chart | 300×250px | Candlestick + MA20/50/200 + Volume bars; RSI/Bollinger as toggle | `ohlcv/{id}` |
| Screener | 400×200px | 5 cols: Ticker/Name/Change%/MktCap/Score; top 20 by score | `fundamentals/screen` |
| News | 280×200px | Tier badge + title truncated + time + score dot; 22px rows | `news/top` |
| Alerts | 280×200px | Grouped by severity; 22px rows; left border color per severity | WebSocket + `alerts/pending` |
| Chat | 280×320px | 36px input + scrollable history; 11px sans; no full-page UI | `/chat/stream` SSE |
| Fundamentals | 220×200px | 6 key metrics only: MktCap/PE/EPS/DivYld/52W/Beta | `fundamentals/{id}` |
| Graph | 280×240px | 180px graph + scrollable entity table; click node navigates | `entities/{id}/graph` |
| Portfolio | 320×200px | 5 cols: Ticker/Qty/AvgCost/Current/P&L; 12 rows max | `holdings` + `quotes/batch` |
| Watchlist | 220×200px | 4 cols: Ticker/Price/Change%/MktCap; 22px rows; live refresh 30s | `quotes/batch` |
| Brief | 280×150px | Morning brief amber-bordered; collapsed 1 line; expand on click | `briefings/morning` |

**Chart panel technical indicators**:
- Default: Candlesticks + MA20 (blue) + MA50 (orange) + Volume bars below chart
- Toggle controls in panel header (right side): `[MA] [BB] [RSI] [Vol]` — each toggles indicator on/off
- MA lines: 0.5px opacity-60 — present but subtle, data takes center stage

**4 Workspace Presets** (ship with platform by default):

```
"Day Trading"          "Research"             "Portfolio Monitor"    "Brief + Screener"
┌──────┬──────┐        ┌──────┬──────┐        ┌──────┬──────┐        ┌────────────────┐
│Chart │Watch │        │Chart │News  │        │Port  │Chart │        │Brief           │
│1D    │list  │        │1W    │(rnkd)│        │folio │(ES)  │        │(full width)    │
├──────┼──────┤        ├──────┼──────┤        ├──────┼──────┤        ├──────┬─────────┤
│Scrn  │Alerts│        │Fndm  │Graph │        │Watch │News  │        │Scrnr │Alerts   │
│top20 │live  │        │6 KPIs│(2nd) │        │list  │(port)│        │top20 │live     │
└──────┴──────┘        └──────┴──────┘        └──────┴──────┘        └──────┴─────────┘
```

Preset storage: `localStorage['worldview-workspaces']` seeded on first load. User can rename/delete. "Reset to default" option in workspace tab right-click menu.

**react-resizable-panels integration**:
- Package: `react-resizable-panels` (maintained, 5.4kb gzip)
- Border hover: `1px border-border` → `3px border-primary/60` on drag handle hover
- Drag behavior: immediate (no animation, Bloomberg style)
- Snap: to 5% increments (prevents slivers of panels)
- Persistence: panel size ratios stored per workspace in localStorage

**Symbol linking implementation**:
- Panel header: 6px circle chip (click → popover with 5 colors + "unlink")
- Color groups: `Red (#EF5350) | Green (#26A69A) | Blue (#3B82F6) | Yellow (#FFD60A) | Purple (#A855F7)`
- Context: `SymbolLinkingContext` (React context, per workspace) stores `Map<color, currentSymbol>`
- `onSymbolChange(symbol)`: broadcasts to all panels with same color group
- Only affects symbol-aware panels (Chart, Fundamentals, Graph, Brief, News — filtered to entity)

---

## 4. BlackRock Readiness Checklist

For the executive presentation, the following must be true:

### Must-have (blocking a presentation):
- [ ] All 10 panel types implemented (no placeholders)
- [ ] Workspace has named presets (not "Workspace 1")
- [ ] Screener shows ≥10 columns at 1440px
- [ ] Holdings table has Sector column
- [ ] Fundamentals tab has Analyst Consensus section
- [ ] Intelligence signals show market_impact_score bar
- [ ] Chat has starter questions (no blank state)
- [ ] Zero console errors on all routes
- [ ] Row height 22px system-wide (no 32px rows)
- [ ] TypeScript typecheck passes (exit 0)

### Should-have (impresses a financial professional):
- [ ] Workspace drag-to-resize panels
- [ ] Alert rule builder (even localStorage-only for demo)
- [ ] News has "My Holdings" watchlist-filtered tab
- [ ] Portfolio has sector allocation chart
- [ ] Chat auto-injects entity context from instrument page
- [ ] Alerts are severity-grouped (not flat list)
- [ ] Dashboard sector heatmap in row 2

### Nice-to-have (demonstrates depth):
- [ ] Intelligence: signal depth badges (DEEP/MED/LIGHT)
- [ ] Intelligence: novelty indicator
- [ ] News: read/unread state
- [ ] Citation source type badges in chat

---

## 5. Compounding Updates

- PRD-0031 updated with D-11 through D-17 ✓
- No new bug patterns
- DESIGN_SYSTEM.md already updated in session 2

Compounding check: No additional doc updates required beyond PRD-0031.
