# Investigation Report: PRD-0031 Enhancement Session 2

**Date**: 2026-04-25
**Investigator**: Claude Code (investigation skill)
**Severity**: N/A (feature investigation)
**Status**: All decisions confirmed — PRD-0031 updated
**Target**: `docs/specs/0031-terminal-ui-v3-ground-up-redesign.md`

---

## 1. Issue Summary

Five design questions requiring investigation:
1. Should News and Intelligence tabs be merged into a single tab?
2. Should the dashboard layout swap Sector Heatmap and Pre-Market Movers, adding Polymarket bets?
3. What are the strict design conventions (colors, typography, borders, layout) in professional finance UIs — is Worldview's current palette aligned?
4. What should the Portfolio page display — holdings, transactions, watchlists, brokerages?

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|---|---|---|
| Bloomberg Terminal color: amber `#FFA028` on `#000000` | Agent 1 web research | Confirms Worldview's `#FFD60A` yellow is industry-correct |
| TradingView background: `#131722` | Agent 1 web research | Very close to our `#09090B`; confirms near-black, not slate-blue |
| "1px solid borders" is the finance terminal standard | Agent 1 | Confirms our `--radius: 2px` + `border-border` 1px convention |
| IBM Plex Mono + tabular-nums is the correct choice | Agent 1 + DESIGN_SYSTEM.md | ADR-F-15 is validated against industry practice |
| Bloomberg separates NEWS function from DES (fundamentals) | Agent 3 | News and Intelligence should remain separate tabs |
| Intelligence contradictions have no `article_ids[]` backlink | Agent 3 | Merging would require backend API change, not worth it now |
| Holdings: missing sector, weight, holding period | Agent 2 | Portfolio page gaps confirmed |
| Transactions: DIVIDEND type blocked in gateway | Agent 2 | Backend gap — S1 supports it, gateway filters it |
| Watchlists: backend supports multiple, frontend only shows first | Agent 2 | UI-only fix, high ROI |
| Brokerage: SnapTrade flow complete; missing per-brokerage transaction audit | Agent 2 | Confirmed scope |
| DESIGN_SYSTEM.md: `--topbar-height: 44px` (stale), `--panel-header-height: 32px` (stale) | DESIGN_SYSTEM.md read | Design tokens need updating to match PRD-0031 |
| Polymarket: `market.prediction.v1` topic exists (PRD-0019) | Memory | Dashboard widget feasible |

---

## 3. Investigation Decisions (D-6 through D-10)

### Decision D-6: Keep News and Intelligence as Separate Tabs (CONFIRMED)

**Question**: Should they merge?
**Answer**: NO — keep as separate tabs.

**Evidence**:
- Bloomberg separates `NEWS` command from `DES`/`ANR` — this is the market pattern for 40+ years
- Intelligence contradictions do NOT have `article_ids[]` backlinks in the API (`GET /v1/entities/{id}/contradictions` returns claim pairs, not article references). Merging would require a new backend endpoint and backtracking logic
- Different use case modes: News = "what happened?" (exploratory, breadth), Intelligence = "do I see conflicts?" (risk-focused, depth)
- The 4-tab structure `[Overview] [Fundamentals] [News] [Intelligence]` is already streamlined (Brief moved to sticky subheader). No further merging is beneficial.

**Result**: Tab structure stays as PRD-0031 §9 specifies. No change.

---

### Decision D-7: Dashboard Layout Swap + Polymarket Addition

**User request**: Move Sector Heatmap to row 2 (where Pre-Market Movers was). Move Pre-Market Movers to row 3 alongside Polymarket bets.

**Rationale**: Sector heatmap answers the "market regime" question (which sectors are hot today) — this is row-2 priority information. Pre-market movers + Polymarket bets are more speculative/actionable signals that belong in the same row as secondary information.

**New dashboard layout**:

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  MORNING BRIEF (full width, collapsible, amber border)                               │
├──────────────────────────┬───────────────────────────────────────────────────────────┤
│  MARKET SNAPSHOT (4 cols)│  SECTOR HEATMAP (8 cols)              ← MOVED UP          │
│  ES / VIX / yields       │  Tech +1.2% ████  Energy +2.1% ████                       │
│  (placeholder data)      │  Finance +0.1% █  Health -0.4% ░░░                        │
├──────────────────────────┼─────────────────────────┬─────────────────────────────────┤
│  PORTFOLIO SUMMARY(4col) │  PRE-MKT MOVERS (5 cols)│  POLYMARKET BETS (3 cols)        │
│  $124k  +$234 today      │  TOP GAINERS  TOP LOSERS│  Fed cuts in Jun  62%           │
│  3 pos at day high       │  RCAT +18.2%  NVDA -4.1%│  BTC > 100k Jun  44%            │
│                          │  COIN  +9.4%  META -2.3%│  AAPL ER beat     71%           │
├──────────────────────────┴─────────────────────────┴─────────────────────────────────┤
│  ECON CALENDAR (3 cols)  │ EARNINGS CALENDAR (3 cols) │ PORTFOLIO NEWS │ RECENT ALERTS│
└──────────────────────────┴────────────────────────────┴────────────────┴──────────────┘
```

**Polymarket Bets widget spec**:
- Title: `PREDICTION MARKETS` (10px uppercase)
- Shows: top 3 most relevant Polymarket predictions ranked by market volume + entity match to user's portfolio/watchlist
- Columns: Question (truncated, 11px), Probability % (mono, right-aligned, colored: >60% green, <40% red, else muted)
- Row height: 22px
- Source: `GET /v1/predictions/top` or equivalent S9 endpoint (from PRD-0019 `market.prediction.v1` topic data)
- Footer: `[View all predictions →]` link to a future `/predictions` page
- If no data: `[Predictions coming soon]` placeholder (Polymarket integration pending full activation)

---

### Decision D-8: Finance Design System — Palette, Typography, Borders VALIDATED

**Question**: Is Worldview's current palette/design system aligned with professional finance terminals?

**Findings**:

#### Colors — VALIDATED ✓

| Design element | Bloomberg | TradingView | Worldview Terminal Dark | Status |
|---|---|---|---|---|
| Background | `#000000` | `#131722` | `#09090B` | ✓ Correct (near-black, zero hue) |
| Primary accent | `#FFA028` amber | `#2962FF` blue | `#FFD60A` yellow | ✓ Amber/yellow = terminal-grade |
| Positive | Teal-green | `#0ecb81` | `#26A69A` | ✓ Correct |
| Negative | Muted red | `#f6465d` | `#EF5350` | ✓ Correct |
| Text | Off-white | White | `#E4E4E7` | ✓ Correct |
| Labels | Muted grey | Muted grey | `#71717A` | ✓ Correct |

**No palette changes needed.** The Terminal Dark palette is industry-aligned.

#### Typography — VALIDATED ✓

- IBM Plex Mono for all numbers: **correct** (finance standard = monospace + tabular-nums)
- IBM Plex Sans for UI text: **correct** (high legibility, geometric, professional)
- `tabular-nums` on all prices/percentages: **required**, already specified in ADR-F-15

**One gap found**: DESIGN_SYSTEM.md `type scale` still uses `text-xs` (12px) for "Numeric value (table)". PRD-0031 specifies 11px (`text-[11px]`) for data rows. **The type scale needs updating** to match PRD-0031.

#### Borders and Lines — MOSTLY CORRECT, one gap

The "straight and thin lines" convention in finance terminals:
- **1px solid borders** between panels: ✓ specified (`border-border` = 1px `#27272A`)
- **Hairline row separators in tables**: 1px `border-b border-border/30` — correct
- **2px border-radius max on data surfaces**: ✓ `--radius: 0.125rem` = 2px
- **No decorative box-shadows**: ✓ already banned

**Gap found**: `--panel-header-height: 32px` in DESIGN_SYSTEM.md is stale — PRD-0031 says 24px. `--topbar-height: 44px` is stale — PRD-0031 says 36px. These CSS variables need updating.

#### Specific finance "straight line" conventions to enforce:

1. **Table row separators**: `divide-y divide-border/20` (not `gap-N` between card rows — no gap, just hairlines)
2. **Panel boundaries**: `gap-px` between workspace panels (1px seam, not 4px gap)
3. **Section headers in tables**: `text-[10px] uppercase tracking-widest text-muted-foreground` with a 1px `border-b` below
4. **Number alignment**: ALL numeric columns `text-right font-mono tabular-nums` — non-negotiable
5. **Column header alignment**: mirrors data alignment (numeric headers also `text-right`)

#### Color usage refinement (from research):

Bloomberg uses amber **only for non-semantic data** (labels, navigation) — green/red reserved strictly for P&L. Worldview uses `#FFD60A` for CTAs, active nav, and AI content (amber). This is correct — but needs one additional rule:

**New rule**: `text-primary` (`#FFD60A`) must NEVER appear on price or P&L values. It is for interactive elements and AI accent only. P&L values use only `text-positive` or `text-negative`.

---

### Decision D-9: Portfolio Page Full Spec

**Investigation findings** (from Agent 2 audit):

Current state gaps:
- Holdings table: missing Sector, Weight columns (sector requires fundamentals join)
- Transactions: only BUY/SELL (DIVIDEND blocked in gateway mapping)
- Watchlists: backend supports multiple named watchlists, frontend shows only the first
- Brokerages: connection flow complete but no per-brokerage transaction audit view
- KPIs: missing Realized P&L, Sector allocation chart, Portfolio Beta, Sharpe Ratio

**Full portfolio page spec**:

#### Tab structure:
```
[Holdings] [Transactions] [Watchlists] [Brokerages]
```

#### Holdings tab:

```
HOLDINGS                                              [+ Add Position]  [⬇ Export CSV]
──────────────────────────────────────────────────────────────────────────────────────
TICKER  NAME          QTY    AVG COST   CURRENT  P&L        P&L%    VALUE    WEIGHT  SECTOR
AAPL    Apple Inc.    100    150.00     172.34  +2,234     +14.9%  17,234   13.9%   Tech
MSFT    Microsoft     50     280.00     425.12  +7,256     +51.8%  21,256   17.1%   Tech
...
══════════════════════════════════════════════════════════════════════════════════════
TOTAL                                             +9,490     +8.8%  124,328
```

- `<table>` element (semantic, required for accessibility)
- Row height: 22px; font: 11px IBM Plex Mono (numbers), IBM Plex Sans (text)
- 9 columns: Ticker | Name | Qty | Avg Cost | Current | P&L$ | P&L% | Value | Weight | Sector
- Sector: fetched via `getFundamentals(instrument_id)` per holding — show loading skeleton, then sector name; cache in `sessionStorage` to avoid repeat calls
- Weight: computed as `(value / totalValue) × 100`, shown as `13.9%`
- Row click: navigate to `/instruments/[entityId]`
- Stale price: `~` prefix on Current column + `StaleDataBadge` in header
- Sort: click any column header; default sort = P&L% descending
- Total row: sticky at bottom

**Sector Allocation Panel** (below holdings table):

```
ALLOCATION BY SECTOR                         ALLOCATION BY TYPE
Technology    54% ████████████░░░░            Equity  87% ██████████████░░
Healthcare    18% ████████░░░░░░░░            Cash     8% ████░░░░░░░░░░░░
Finance       13% ██████░░░░░░░░░░            Options  5% ██░░░░░░░░░░░░░░
```

- Horizontal bar chart component: sector name, percentage, fill bar (positive teal at 30% opacity)
- Two side-by-side panels: "By Sector" and "By Asset Type"
- Data: computed client-side from holdings + fundamentals `gics_sector` field

#### Transactions tab:

```
TRANSACTIONS   [All types ▾]  [All time ▾]  [All tickers ▾]        [⬇ Export CSV]
──────────────────────────────────────────────────────────────────────────────────
DATE              TYPE   TICKER  QTY     PRICE      TOTAL       FEE
2026-04-22 14:32  BUY    AAPL    50      $168.40    $8,420.00   $0.65
2026-04-18 09:31  SELL   TSLA    25      $241.00    $6,025.00   $0.48
2026-04-15 09:30  DIV    AAPL    —       —          $23.75      —
```

Filters:
- Type: `[All] [BUY] [SELL] [DIVIDEND]` — enable DIVIDEND (requires gateway map fix)
- Date: `[All time] [Today] [1W] [1M] [3M] [1Y]`
- Ticker: dropdown of all unique tickers in transaction history

Columns: Date (ISO, absolute) | Type (badge: BUY=teal, SELL=red, DIV=yellow) | Ticker | Qty | Price | Total | Fee
Row height: 22px. Sorted newest-first (client-side). Pagination: "Load 100 more" at bottom.
Note in footer: "Dividend records require brokerage sync or manual entry."

**Backend gap**: gateway.ts maps `transaction.direction` to BUY/SELL only. Need to also map `DIVIDEND` type (S1 supports it). Fix: add `| 'DIVIDEND'` to the type union and map `s1Transaction.type === 'DIVIDEND'` in the gateway.

#### Watchlists tab:

```
[Tech Stocks] [Earnings Watch] [Macro Plays] [+ New Watchlist]          [Edit Watchlist ✎]
──────────────────────────────────────────────────────────────────────────────────────────
  [🔍 Search to add symbol...]
──────────────────────────────────────────────────────────────────────────────────────────
TICKER  NAME          PRICE       CHG%         52W HI/LO    MKT CAP    ADDED
AAPL    Apple Inc.    172.34  ▲  +0.72%        199 / 124    2.87T      Apr 1
MSFT    Microsoft     425.12  ▲  +1.23%        468 / 311    3.16T      Mar 15
NVDA    NVIDIA        875.21  ▼  -0.89%        974 / 434    2.15T      Mar 20
```

- Tabs: one tab per watchlist (max 5 visible; overflow → dropdown `▾ N more`)
- `[+ New Watchlist]` button: opens a name dialog → creates new watchlist → switches to it
- `[Edit Watchlist ✎]` button: opens inline rename + "Delete watchlist" option
- Search bar inline at top of watchlist: type to search instruments → click to add to current watchlist
- Remove symbol: hover row → `×` button appears at right
- Live prices: `GET /v1/quotes/batch` with watchlist `instrument_ids`, refresh every 30s
- Columns: Ticker | Name | Price | Change% | 52W Range | Mkt Cap | Date Added
- Row height: 22px. Click row → navigate to `/instruments/[entityId]`

**Backend gap**: Watchlist members don't have `52W Hi/Lo` or `Mkt Cap` — these require a fundamentals join per member. Use the same pattern as Holdings sector enrichment (fetch on mount, cache in sessionStorage).

#### Brokerages tab:

```
CONNECTED BROKERAGES                                          [+ Connect Brokerage]
──────────────────────────────────────────────────────────────────────────────────
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ● Interactive Brokers      STATUS: ACTIVE    Last sync: 2026-04-25 09:14 UTC  │
│                              [Sync Now]  [Sync Errors (0)]  [Disconnect]        │
│  Holdings synced: 12  │  Transactions synced: 847  │  Connected: Mar 8, 2026   │
└─────────────────────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ● Robinhood                STATUS: ERROR     Last sync: 2026-04-24 22:01 UTC  │
│                              [Retry Sync]  [Sync Errors (3)]  [Disconnect]      │
│  ⚠ 3 sync errors — click "Sync Errors" to view details                         │
└─────────────────────────────────────────────────────────────────────────────────┘
```

- One card per brokerage connection
- Status badge: `● ACTIVE` (teal), `● PENDING` (yellow), `● ERROR` (red), `● DISCONNECTED` (muted)
- Actions: `[Sync Now]` → POST `/{id}/sync` → show spinner → "Sync queued" toast; `[Sync Errors (N)]` → expands inline list of errors; `[Disconnect]` → confirm dialog → DELETE `/{id}`
- Stats row: "Holdings synced: N | Transactions synced: N" (from sync status metadata)
- `[+ Connect Brokerage]` → opens `ConnectBrokerageModal` (already exists)
- If no connections: `<InlineEmptyState message="Connect a brokerage to auto-sync your holdings and transactions." />` with `[Connect Brokerage]` CTA

---

### Decision D-10: KPI Strip Revised

Based on the portfolio audit, the 6 KPI tiles need to be redefined based on what can actually be computed:

```
Total Value  │  Day P&L      │  Unrealised P&L  │  Top Gainer    │  Top Loser    │  # Positions
$124,328     │  +$234 +0.19% │  +$8,234 +7.1%   │  MSFT +51.8%  │  GOOGL -3.2% │  8 positions
```

**Change from PRD-0031**: Remove "Realized P&L" KPI (requires lot-level cost basis tracking — a backend feature not yet built). Replace with "Top Gainer" and "Top Loser" (computed from holdings, no backend change needed). Remove "Beta" and "Sharpe Ratio" from KPIs (too complex to compute without dedicated backend; move to a future "Risk" tab).

**Final 6 KPIs**: Total Value | Day P&L | Unrealised P&L | Top Gainer | Top Loser | # Positions

---

## 4. Design Token Updates Required (DESIGN_SYSTEM.md)

Two CSS variable values in DESIGN_SYSTEM.md are stale relative to PRD-0031:

| Token | DESIGN_SYSTEM.md (stale) | PRD-0031 target | Fix |
|---|---|---|---|
| `--topbar-height` | 44px | 36px | Update CSS variable + component |
| `--panel-header-height` | 32px | 24px | Update CSS variable + component |

Additionally, the type scale table needs a new row for 11px data:
- Add: `Data row value | IBM Plex Mono | font-mono text-[11px] tabular-nums text-right | 11px/400`

---

## 5. Impact on PRD-0031

Sections to update:

| Section | Change |
|---|---|
| §10 Dashboard | Swap row 2/3 positions of Sector Heatmap and Pre-Market Movers; add Polymarket Bets widget |
| §8 Portfolio | Full spec: Holdings 9-col table + sector panel, Transactions with DIVIDEND, Watchlists multi-tab, Brokerages cards |
| §8 KPI strip | Replace Realized P&L/Beta/Sharpe with Top Gainer/Top Loser/# Positions |
| §12 Color System | Add new rule: `text-primary` NEVER on price/P&L values |
| §16 Acceptance Criteria | Add: watchlist multi-tab, brokerage card, DIVIDEND type in transactions |
| §14 Wave 4 | Update scope: adds Watchlists tab full spec, Brokerages redesign |

---

## 6. Compounding Updates

- DESIGN_SYSTEM.md: update `--topbar-height`, `--panel-header-height`, add 11px data row to type scale
- PRD-0031: updated below with D-7 through D-10

Compounding check: DESIGN_SYSTEM.md token updates needed (documented above).
