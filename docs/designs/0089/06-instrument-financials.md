# Instrument — Financials Tab — Design Spec (PRD-0089)

> **Status**: design-proposal (iteration 2 — supersedes PLAN-0090 T-C-01..T-C-03 shipped 2026-05-19)
> **Author**: agent-instr-financials
> **Parent**: `docs/designs/0089/_INDEX.md`
> **Inventory**: `docs/designs/0089/00-backend-data-inventory.md`
> **Date**: 2026-05-19
> **Branch**: `feat/frontend-platform-hardening` (no worktree — design-only)

---

## 0. Why this iteration exists

The currently-shipped Financials tab (commit `1689f7bd`) was reviewed live by the user. Verdict:

1. **"Table with too many gaps"** — VALUATION group renders 6 metrics across 3 columns (only 2 metrics per row). At 1440×900 the screen fits ~40 visible data cells; competitor benchmarks (Finviz fundamentals snapshot, Bloomberg DES) show 80–120 cells.
2. **"AI brief deleted"** — PLAN-0090 T-E-01 deleted the legacy `OverviewLayout` "About / AI brief" zone. The new Financials tab never restored an equivalent.
3. **"No description, sector"** — Company description, GICS sector, GICS industry, employee count, HQ city are present in `/v1/fundamentals/{id}` but **never rendered** (confirmed in inventory §1.4 line 261-263).
4. **"Sidebar looks empty"** — `AnalystSidebar` shows ~120px of content (bar + target + timestamp), leaving ~600px of unused vertical space in the 280px column.
5. **Backend data unused** — Institutional holders, fund holders, insider transactions, analyst target price are exposed by S9 (inventory §1.2a lines 75-77, §1.4 line 267, 277-278) but never displayed.

This doc proposes the **next iteration** — denser grid, restored narrative, full sidebar, peer comparison, insider/institutional tables below the fold.

---

## 1. Competitor research summary

### 1.1 Bloomberg Terminal FA (Financial Analysis) function
- **Density**: ~150 numeric cells visible on a single 1440-wide screen
- **Layout**: 6-column ratio block top-left (P/E, P/B, P/S, EV/EBITDA, P/FCF, PEG) with 4 trailing periods side-by-side; right side carries 12-row analyst panel with target distribution + consensus + revisions count
- **Row height**: ~16px; font: Bloomberg LiberationMono ~10px
- **Steal**: side-by-side trailing periods inside a single metric row (e.g. P/E shown for FY-3/FY-2/FY-1/TTM/FWD on one row); per-section trend sparkline column

### 1.2 TradingView Financials tab
- **Density**: middle — ~50 cells; chooses readability over data per inch
- **Pattern worth stealing**: dual annual/quarterly toggle on each block; analyst-revision count badges (`↑12 / ↓3 last 30D`)

### 1.3 Finviz fundamentals snapshot
- **Density**: GOLD STANDARD — 72 cells in a single non-scrolling block (12 rows × 6 cols)
- **Row height**: 18-20px
- **Pattern**: pure 6-col grid with mixed label/value cells (no group headers eating rows; sections separated by color hue not header rows)
- **Steal**: **6-col grid**, color-by-section instead of header rows, no scroll for the snapshot

### 1.4 Stockanalysis.com / Macrotrends
- **Pattern**: 10-year historical column table on every ratio; sparkline column at right
- **Steal**: sparkline column on the income-statement table

### 1.5 Koyfin
- **Pattern**: narrow analyst panel (~240px) with stacked: consensus → target distribution → revisions → top analyst rankings → forecast revisions chart
- **Steal**: full sidebar composition (see §4)

### 1.6 Citation table
| Source | Density (cells / 1440×900) | Row height | Sidebar usage |
|---|---|---|---|
| Bloomberg FA | ~150 | 16px | Always full (analyst ratings, revisions, sparkline) |
| Finviz | 72 | 18-20px | None — uses full width |
| TradingView | ~50 | 28px | Filters/toggle only |
| Stockanalysis | ~80 | 22px | Historical sparklines |
| Koyfin | ~90 | 20px | Full analyst panel ~280px |
| **Current Worldview** | **~40** | **32px** | **Mostly empty** |
| **Worldview iter-2 target** | **80+** | **18px** | **7 stacked panels** |

---

## 2. User intent for this page

### 2.1 Primary persona
**Buy-side equity analyst** (junior PM / sector specialist) running pre-trade due diligence. Has 3–10 minutes per name. Compares to peers, checks earnings trajectory, scans analyst sentiment, then decides "add / hold / kill".

### 2.2 Primary tasks (top 3)
1. **Scan fundamentals snapshot** — P/E, margins, growth, leverage in one glance, color-coded against thresholds. Needs zero scroll.
2. **Read the AI brief + company description** — what does the company do, what's the bull/bear case in 3 bullets. Must be visible without tab switch.
3. **Cross-check Wall Street consensus + 12-mo target + revisions** — is the sell side bullish? Are they revising up or down?

### 2.3 Secondary tasks
- Compare to 5 peers on key ratios (relative valuation)
- Inspect last-8-quarter EPS beat/miss history
- See who's buying/selling (insider activity + institutional flow)
- Drill into 4-FY income statement / quarterly toggle

### 2.4 Anti-patterns
- Tab MUST NOT scroll horizontally
- Sidebar MUST NOT have >120px of empty space
- Group headers MUST NOT eat a full row in a dense grid (Finviz proves you don't need them)
- AI brief MUST NOT disappear behind a hover or tab — always visible

---

## 3. Backend data available

All cited from `docs/designs/0089/00-backend-data-inventory.md`.

### 3.1 Currently displayed
- 45 fundamentals fields in `FlatMetricsGrid` (inventory §1.2a)
- `analyst_consensus` rating breakdown (5 buckets) + target_price (inventory §1.2a line 70, §3.2)
- 4-FY annual income statement (`/v1/fundamentals/{id}/income-statement`, inventory §1.2 line 73)
- 4-FY EPS history (`/v1/fundamentals/{id}/earnings-annual-trend`, inventory §1.2 line 45)
- Splits/dividends ex-date + pay-date (inventory §1.2 line 46)

### 3.2 Exposed but NOT displayed (MUST-restore in iter-2)
| Field | Endpoint | Source | iter-2 location |
|---|---|---|---|
| `Instrument.description` | `/v1/fundamentals/{id}` General | EODHD | Sidebar "COMPANY SNAPSHOT" panel |
| `Instrument.gics_sector` | `/v1/fundamentals/{id}` | EODHD | Sidebar "COMPANY SNAPSHOT" panel |
| `Instrument.gics_industry` | `/v1/fundamentals/{id}` | EODHD | Sidebar "COMPANY SNAPSHOT" panel |
| `General.FullTimeEmployees` | `/v1/fundamentals/{id}` | EODHD | Sidebar "COMPANY SNAPSHOT" panel |
| `General.AddressData.City/Country` | `/v1/fundamentals/{id}` | EODHD | Sidebar "COMPANY SNAPSHOT" panel |
| `Fundamentals.analyst_target_price` | `/v1/fundamentals/{id}` | EODHD | Sidebar "12-MO TARGET" panel (already displayed — keep) |
| `institutional_holders` | `/v1/fundamentals/{id}/institutional-holders` | EODHD | Below-fold "INSTITUTIONAL HOLDERS" table |
| `fund_holders` | `/v1/fundamentals/{id}/fund-holders` | EODHD | Below-fold "FUND HOLDERS" table |
| `insider_transactions_snapshot` | `/v1/fundamentals/{id}/insider-transactions` | EODHD | Below-fold "INSIDER TRANSACTIONS" table |
| `BriefingResponse.sections + risk_summary` | `/v1/briefings/instrument/{entity_id}` | S8 | Sidebar "AI BRIEF" panel | *(C-F2-03: cache key must NOT include `:{user_id}` suffix — use `qk.briefings.instrument(id)` per DISCUSS-7 lock. The brief is per-instrument, not per-user. AIBriefPanel staleTime = 30s to account for lazy-generate polling)* |
| `BriefingResponse.bullets` | `/v1/briefings/instrument/{entity_id}` | S8 | Sidebar "AI BRIEF" panel |
| `earnings-trend` (forward quarters) | `/v1/fundamentals/{id}/earnings-trend` | EODHD | Sidebar "EARNINGS BEAT/MISS" — needs `surprise_percent` from `earnings_annual` records (inventory §1.2 line 45) |

### 3.3 Currently always-null (handle gracefully)
| Field | Why null | iter-2 plan |
|---|---|---|
| `interest_coverage` | EODHD doesn't compute; would need derived worker | **HIDE the cell entirely** until backfilled (don't render placeholder row) |
| `credit_rating` | No credit-data provider integrated | **HIDE the cell** with a footnote "credit data pending" |
| `daily_return` | Lives on the Quote tab header, redundant here | **REMOVE from Financials grid** — already shown on Quote header strip |
| `RSI(14)`, `ATR(14)` | Computed from cached OHLCV but the chart is on Quote tab, not Financials | **MOVE to Quote tab only** — these are technicals, not fundamentals |

### 3.4 Net effect on grid
- Remove 5 fields (INT COVERAGE, CREDIT RATING, DAY RETURN, RSI(14), ATR(14)) → 40 fields remain
- Add nothing to the grid (everything else goes in sidebar or below-fold)

### 3.5 Peer comparison data (new endpoint requirement)
**Open Q-1**: there is no `/v1/instruments/{id}/peers` endpoint today. iter-2 has two options:
- **A**: derive peers client-side from screener (`/v1/fundamentals/screen` with `gics_industry == X` filter, top 5 by market cap)
- **B**: backend ships new endpoint `GET /v1/instruments/{id}/peers?n=5` (cached 24h)

Recommend **B** — cleaner contract, no double-fetch on every instrument page. Implementation is trivial (single SQL query in S9 with sector/industry filter). Flagged in §10.

---

## 4. Layout — 1440×900 ASCII wireframe

```
╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║ TopBar (32px)  — ticker • price • change • freshness                                                                                   ║
╠════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣
║ Tab strip (28px)   [ Quote ] [ Financials* ] [ Intelligence ]                                                                          ║
╠══════════════════════════════════════════════════════════════════════════════════════════════════════════════╤═════════════════════════╣
║ ── LEFT COLUMN (1200px = main grid + tables) ──────────────────────────────────────────────────────────────  │  RIGHT SIDEBAR (240px)  ║
║                                                                                                              │                         ║
║ ┌── FUNDAMENTALS SNAPSHOT (6-col grid, 18px rows) ────────────────────────────────────────────────────────┐  │ ┌─ ANALYST CONSENSUS ─┐ ║
║ │MKT CAP    $3.42T │P/E     28.7│FWD P/E  24.1│P/B    52.3│P/S     8.4│EV/EBITDA 22.1│ ◄ VALUATION         │  │ │bar 24px             │ ║
║ │GROSS MGN   43.3% │OP MGN  29.8│NET MGN 25.3 │ROE   154.8│ROA    27.5│EPS TTM   6.42│ ◄ PROFITABILITY     │  │ │ ▆▆▆▆▆▃▂  hold/buy   │ ║
║ │REV YoY      1.5% │EPS YoY  9.3│FCF MGN 26.7 │  —        │  —        │  —           │ ◄ GROWTH            │  │ └─────────────────────┘ ║
║ │DEBT/EQ      1.51 │CURR R   0.9│QUICK R  0.8 │ND/EBITDA 1.3│  —        │  —         │ ◄ BALANCE SHEET     │  │ ┌─ 12-MO TARGET ──────┐ ║
║ │OP CF       113.8B│CAPEX   9.7B│FCF    104.0B│   —        │  —        │  —          │ ◄ CASH FLOW         │  │ │ $303.38             │ ║
║ │DIV YIELD    0.4% │PAYOUT  14.9│EX-DIV 11/08│PAY 11/14   │  —        │  —          │ ◄ DIVIDENDS         │  │ │ ▲ +12.4% vs current  │ ║
║ │SHARES OUT 15.1B  │FLOAT  15.0B│%INSID 0.07 │%INST 60.9  │  —        │  —          │ ◄ OWNERSHIP         │  │ └─────────────────────┘ ║
║ │BETA         1.21 │52W H 250.1 │52W L 165.3 │50DMA 232.0 │200DMA 215 │AVG VOL 50M  │ ◄ TECHNICALS-LITE   │  │ ┌─ REVISIONS (30D) ───┐ ║
║ │SHRT SHRS  100M   │SHRT R  1.3 │SHRT %  0.7 │  —        │  —        │  —          │                     │  │ │ ↑ 12 upgrades       │ ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │ │ ↓  3 downgrades     │ ║
║   (8 rows × 6 cells visible = 48 cells in 144px height)                                                       │ │ ↑  8 target raises  │ ║
║                                                                                                              │ └─────────────────────┘ ║
║ ┌── INCOME STATEMENT (4-FY + TTM, 18px rows) ──────────────────────────────────────────────────────────────┐ │ ┌─ TGT BY ANALYST ────┐ ║
║ │            │ FY22  │ FY23  │ FY24  │ FY25  │ TTM   │ ▲ trend       [Annual ▼] [Quarterly]               │ │ │ MS    $315          │ ║
║ │ Revenue    │ 394B  │ 383B  │ 391B  │ 414B  │ 420B  │ ▁▁▂▃▄                                              │ │ │ GS    $310          │ ║
║ │ Gross Prof │ 170B  │ 169B  │ 180B  │ 192B  │ 195B  │ ▁▁▂▃▄                                              │ │ │ JPM   $305          │ ║
║ │ EBIT       │ 119B  │ 114B  │ 123B  │ 128B  │ 130B  │ ▁▁▂▃▄                                              │ │ │ BAC   $300          │ ║
║ │ Net Income │  99B  │  96B  │ 102B  │ 110B  │ 112B  │ ▁▁▂▃▄                                              │ │ │ WFC   $295          │ ║
║ │ EPS        │ 6.11  │ 6.13  │ 6.40  │ 6.92  │ 7.05  │ ▁▁▂▃▄                                              │ │ │ DB    $290          │ ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │ │ … (10 firms)        │ ║
║                                                                                                              │ └─────────────────────┘ ║
║ ┌── EARNINGS HISTORY (5-bar, 64px height) ─────────────────────────────────────────────────────────────────┐ │ ┌─ BEAT/MISS 8Q ──────┐ ║
║ │ ▆▆ ▆▇ ▆▇ ▆▇ ▆▇       │  Beat margin: +3.2% avg │ Last quarter: +4.1% beat                                 │ │ │ ▆▇▆▇▆▇▇▇  6 beats / │ ║
║ │ FY21 FY22 FY23 FY24 FY25                                                                                 │ │ │           2 misses  │ ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │ └─────────────────────┘ ║
║                                                                                                              │ ┌─ AI BRIEF ──────────┐ ║
║ ┌── PEER COMPARISON (6 rows × 9 cols, 18px) ───────────────────────────────────────────────────────────────┐ │ │ • Bull: Services    │ ║
║ │       │ MKT CAP │ P/E  │ FWD P/E │ ROE   │ NET MGN │ DEBT/EQ │ DIV Y │ REV YoY │ 1Y RET                  │ │ │   margin >70%       │ ║
║ │ AAPL  │ 3.42T   │ 28.7 │ 24.1    │ 154.8 │ 25.3%   │ 1.51    │ 0.4%  │ 1.5%    │ +24.3%                  │ │ │ • Bull: $200B cash   │ ║
║ │ MSFT  │ 3.10T   │ 35.2 │ 30.4    │  43.2 │ 36.7%   │ 0.34    │ 0.7%  │ 16.8%   │ +32.1%                  │ │ │   $$ buybacks pace  │ ║
║ │ GOOGL │ 2.04T   │ 22.9 │ 19.8    │  29.8 │ 24.0%   │ 0.10    │  —    │ 14.2%   │ +28.4%                  │ │ │ • Bear: iPhone Ch.  │ ║
║ │ META  │ 1.55T   │ 28.0 │ 24.1    │  35.1 │ 33.8%   │ 0.27    │ 0.5%  │ 22.1%   │ +49.2%                  │ │ │   share slip ~3pp   │ ║
║ │ AMZN  │ 2.40T   │ 48.3 │ 35.9    │  21.4 │  9.8%   │ 0.65    │  —    │ 12.4%   │ +18.7%                  │ │ │ Risk: 5.2/10  Conf: │ ║
║ │ — peer means highlighted; current ticker bolded                                                          │ │ │  HIGH   ⟶ expand    │ ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │ └─────────────────────┘ ║
║                                                                                                              │ ┌─ COMPANY SNAPSHOT ──┐ ║
║ ┌── INSIDER TRANSACTIONS (last 8, 18px) ──────────────────────────────────────────────────────────────────┐ │ │ SECTOR              │ ║
║ │ DATE       │ INSIDER            │ ROLE  │ TYPE │ SHARES   │ VALUE  │ POST-TX                            │ │ │  Technology         │ ║
║ │ 2026-05-10 │ Cook, Timothy D    │ CEO   │ SELL │ 100,000  │ $24.5M │ 3.28M                              │ │ │ INDUSTRY            │ ║
║ │ 2026-05-08 │ Maestri, Luca      │ CFO   │ SELL │  50,000  │ $12.3M │ 1.15M                              │ │ │  Consumer Electronics│ ║
║ │ 2026-05-05 │ Adams, Katherine   │ GC    │ SELL │  20,000  │  $4.9M │   422K                              │ │ │ EMPLOYEES            │ ║
║ │ 2026-04-29 │ Williams, Jeff     │ COO   │ SELL │  40,000  │  $9.8M │   860K                              │ │ │  164,000             │ ║
║ │ … (8 rows max, more in modal)                                                                          │ │ │ HQ                   │ ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │ │  Cupertino, CA, US   │ ║
║                                                                                                              │ │ DESCRIPTION (4-line) │ ║
║ ┌── TOP 10 INSTITUTIONAL HOLDERS (18px) ──────────────────────────────────────────────────────────────────┐ │ │ Apple Inc. designs,  │ ║
║ │ HOLDER                          │ SHARES   │ % OUT │ VALUE   │ Δ QoQ                                    │ │ │ manufactures, and    │ ║
║ │ Vanguard Group, Inc.            │ 1.34B    │ 8.9%  │ $328B   │ +0.21%                                   │ │ │ markets smartphones, │ ║
║ │ BlackRock Inc.                  │ 1.05B    │ 7.0%  │ $258B   │ +0.14%                                   │ │ │ tablets… [more]      │ ║
║ │ Berkshire Hathaway              │ 905M     │ 6.0%  │ $222B   │ –0.30%                                   │ │ └─────────────────────┘ ║
║ │ State Street Corp.              │ 580M     │ 3.8%  │ $142B   │ +0.05%                                   │ │                         ║
║ │ … (10 rows)                                                                                            │ │                         ║
║ └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘ │                         ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════╧═════════════════════════╝
```

### 4.1 Grid description
- **Outer**: `flex flex-row h-full overflow-hidden`
- **Left column**: `flex-1 min-w-0 overflow-y-auto` (allows scroll for below-fold tables)
- **Right column**: `w-[240px] shrink-0 overflow-y-auto border-l border-border` — sticky scroll, independent of left
- **Main grid**: `grid grid-cols-6 gap-x-3 gap-y-0` — 6 metric cells per row, **NO group-header rows** (color hue carries section instead)
- **F1 density wrapper**: the `DenseMetricsGrid` root `<div>` MUST wear `data-table-grid="dense"` (F1 §16.3). This drives `--row-h: 18px` and `--cell-px: 6px` from the design-system token. Peer / Insider / Institutional tables use plain `data-table-grid` (default 20px — not hyper-dense). (C-F1-01)
- **Group color hue (subtle)**: each section has a 4px left accent in `--muted-foreground/15` to delimit sections; first cell of each row gets `border-l-2 border-border` — **MUST use `border-border` not section-specific hues** (off-palette arch test). (C-F1-05)

### 4.2 Density math (above the fold @ 1440×900)
- TopBar 32 + Tab strip 28 = 60px chrome
- Available height for content: 900 − 60 = 840px
- Fundamentals snapshot: 8 rows × 18px = 144px (48 cells)
- Income statement: header 22 + 5 rows × 18 = 112px (25 cells)
- Earnings chart: 64px (5 cells)
- Subtotal above peer comparison: 144 + 112 + 64 + 24 (padding) = **344px**
- Remaining space: 840 − 344 = 496px → fits peer comparison (6 rows × 18 = 108px) + first 8 rows of insider table (8 × 18 = 144px) + first 8 institutional rows = visible peer + insider rows in same viewport
- **Above-fold cell count**: 48 (snapshot) + 25 (income) + 5 (earnings) + 54 (peer 6×9) + ~40 (insider 8 rows × 5 visible columns) = **~172 cells visible** without scroll on a 1440×900 viewport. Comfortably beats 80-cell target.

Sidebar above-fold cell count: 5 (consensus bar buckets) + 1 (target) + 3 (revisions) + 10 (analyst targets) + 8 (beat/miss bars) + 3 (AI bullets) + 5 (company snapshot rows) = ~35 cells in 240px width × 840px height. **Zero whitespace gaps.**

---

## 5. Component breakdown

### 5.1 New components

| Component | File path | Line budget | Props | Renders |
|---|---|---|---|---|
| `DenseMetricsGrid` (replaces `FlatMetricsGrid`) | `components/instrument/financials/DenseMetricsGrid.tsx` | ≤260 | `instrumentId, fundamentals, snapshot, technicals, shareStats, dividends` | 6-col grid, 8 rows, 48 visible cells, NO header rows |
| `DenseMetricCell` (replaces `MetricCell`) | **Reuse F1 primitive `components/primitives/MetricCell.tsx`** — no new file. The existing primitive has no hardcoded height; row height comes from `data-table-grid="dense"` parent CSS variable. Delete legacy `components/instrument/financials/MetricCell.tsx` after migration. (C-F1-02) | — | (same as F1 MetricCell) | 18px row via CSS var, 10px label + 11px value |
| `IncomeStatementTable` (refactor existing) | `components/instrument/financials/IncomeStatementTable.tsx` | +30 lines | + `periodType: "ANNUAL" | "QUARTERLY"` + `showSparkline: boolean` | 5-col data + 1 sparkline col; toggle annual/quarterly |
| `Sparkline` (shared primitive) | **Reuse F1 primitive `components/primitives/Sparkline.tsx`** — no new file. Pass `width={40} height={12}` (height override supported; default 16). Beat/miss sidebar panel reuses the same primitive. (C-F1-03) | — | (same as F1 Sparkline) | inline SVG polyline, trend="auto" |
| `EarningsBarChart` (refactor existing) | unchanged file | -20 lines | `instrumentId` (same) | Now 64px tall (was 80); add EPS surprise % chip per bar |
| `PeerComparisonTable` | `components/instrument/financials/PeerComparisonTable.tsx` | ≤180 | `instrumentId` | 5 peers + self × 9 ratio columns @ 18px |
| `InsiderTransactionsTable` | `components/instrument/financials/InsiderTransactionsTable.tsx` | ≤150 | `instrumentId` | 8 rows × 7 cols @ 18px, "view all" → modal |
| `InstitutionalHoldersTable` | `components/instrument/financials/InstitutionalHoldersTable.tsx` | ≤150 | `instrumentId` | 10 rows × 5 cols @ 18px |
| `AnalystSidebar` (rewrite) | `components/instrument/financials/AnalystSidebar.tsx` | ≤320 | `instrumentId` (self-fetches all 7 sub-panels) | 7 stacked panels (see §5.2) |

### 5.2 Sidebar composition (top → bottom, 240px wide)

| Panel | Px height | Source | Renders |
|---|---|---|---|
| `AnalystConsensusPanel` | ~76 (header 16 + bar 24 + caption 12 + count line 12 + padding 12) | `fundamentals.analyst_*_count` (already wired) | header, AnalystMiniBar, "N analysts" subline |
| `TargetPricePanel` | ~64 (header 16 + price 24 + delta 12 + padding 12) | `fundamentals.analyst_target_price` + `quote.price` | "12-MO TARGET", $price, "▲ +X% vs current" with positive/negative color |
| `RevisionsPanel` | ~80 (header 16 + 3 lines × 14 + padding 22) | derived: counts last-30-day deltas in `analyst_consensus` history snapshots | "↑ 12 upgrades" / "↓ 3 downgrades" / "↑ 8 target raises" |
| `TargetsByAnalystPanel` | ~180 (header 16 + 10 rows × 14 + padding 24) | NEW endpoint `/v1/fundamentals/{id}/analyst-targets-by-firm` (open Q-2) | 10 rows: `firm 3-letter | target | date` |
| `BeatMissHistoryPanel` | ~88 (header 16 + sparkline 24 + caption 24 + padding 24) | `earnings-annual-trend` records with `surprise_percent` | sparkline of 8 quarters + "6 beats / 2 misses" |
| `AIBriefPanel` | ~140 (header 16 + 3 bullets × 28 + risk line 14 + cta 14 + padding 12) | `/v1/briefings/instrument/{entity_id}` — `sections[0].bullets[0..2]` + `risk_summary` | 3 truncated bullets, risk score chip, "expand →" cta |
| `CompanySnapshotPanel` | ~140 (header 16 + 5 rows × 18 + 4-line desc 56 + padding 8) | fundamentals General section | SECTOR / INDUSTRY / EMPLOYEES / HQ / DESCRIPTION (4-line truncate, expandable) |

**Total stack**: 76+64+80+180+88+140+140 = **768px** in a 240×900 sidebar → fits with ~70px buffer for scroll padding. **Zero empty space.**

### 5.3 Orchestrator changes

`FinancialsTab.tsx` (rewrite):
- 240px sidebar (was 280)
- Left column: DenseMetricsGrid → IncomeStatementTable → EarningsBarChart → PeerComparisonTable → InsiderTransactionsTable → InstitutionalHoldersTable
- Single `useFinancialsTabData` extended hook fetches everything sidebar needs in parallel; sidebar components read from the shared cache (`enabled: false` pattern from inventory §1.2)

---

## 6. Visual spec (numerical)

### 6.1 Typography (from shared scale in `_INDEX.md` §Typography)
| Element | Token | Notes |
|---|---|---|
| Group section accent label (right-edge tag in grid) | `text-[9px]` 12 lh | uppercase tracking-[0.10em], `text-muted-foreground/60` |
| Metric cell label | `text-[9px]` 12 lh | uppercase tracking-[0.08em], `text-muted-foreground` (was 10px — bump down 1) |
| Metric cell value | `text-[11px]` 16 lh | font-mono tabular-nums |
| Table column header | `text-[9px]` 12 lh | uppercase tracking-[0.08em] |
| Table cell | `text-[11px]` 16 lh | font-mono tabular-nums (numeric) / IBM Plex (text) |
| Sidebar panel header | `text-[10px]` 14 lh | uppercase tracking-[0.08em], `text-muted-foreground` |
| Sidebar target price value | `text-[18px]` (one-off hero) | font-mono tabular-nums |
| Sidebar AI brief bullet | `text-[11px]` 16 lh | IBM Plex Sans normal weight |
| Sidebar description text | `text-[11px]` 16 lh | line-clamp-4 |
| FY tag below earnings chart bar | `text-[9px]` mono | unchanged |

### 6.2 Spacing
| Surface | Value |
|---|---|
| Grid: `gap-x-3 gap-y-0` | 12px horizontal between metric cells, **0 vertical** (rows touch — divider is the border-b) |
| Row height (data): `h-[18px]` | down from 22 (saves 4×8 = 32px of vertical chrome) |
| Row height (table headers): `h-[20px]` |  |
| Table cell padding: `py-0 px-2` | rows are full-height — vertical centering via `items-center` on a flex row |
| Sidebar panel separator: `border-b border-border` | 1px hairline; no margin around it |
| Sidebar panel inner padding: `p-2` | 8px |
| Section accent left-border (grid): `border-l-2` | 2px in `border-border` color |

### 6.3 Colors (palette only — no new tokens)
- Default text: `text-foreground` (#FAFAFA)
- Muted labels: `text-muted-foreground` (#71717A)
- Positive deltas / beats: `text-positive` (#00D26A)
- Negative deltas / misses: `text-negative` (#FF3B5C)
- Caution thresholds (P/E 20–35, D/E 0.5–2): `text-warning` (#FFB000)
- Cell hover bg: `hover:bg-muted/20` (existing token, already in income table)
- Self-row in peer table: `bg-muted/30` (background highlight, not text color)

### 6.4 Per-cell color rules (40 grid cells, 6×8)

| # | Row | Col 1 | Col 2 | Col 3 | Col 4 | Col 5 | Col 6 | Section |
|---|---|---|---|---|---|---|---|---|
| 1 | VALUATION | MKT CAP `formatMarketCap`, foreground | P/E `formatRatio`, peClass | FWD P/E `formatRatio`, peClass | P/B `formatRatio`, foreground | P/S `formatRatio`, foreground | EV/EBITDA `formatRatio`, foreground | accent: zinc-700 |
| 2 | PROFITABILITY | GROSS MGN `formatPercent`, signClass | OP MGN `formatPercent`, signClass | NET MGN `formatPercent`, signClass | ROE `formatPercent`, roeClass | ROA `formatPercent`, signClass | EPS TTM `formatPrice`, signClass | accent: blue-900 |
| 3 | GROWTH | REV YoY `formatPercent`, signClass | EPS YoY `formatPercent`, signClass | FCF MGN `formatPercent`, signClass | — (empty cell, no row) | — | — | accent: emerald-900 |
| 4 | BALANCE SHEET | DEBT/EQ `formatRatio`, deClass | CURRENT R `formatRatio`, foreground | QUICK R `formatRatio`, foreground | ND/EBITDA `formatRatio`, foreground | — | — | accent: amber-900 |
| 5 | CASH FLOW | OP CF `formatMarketCap`, foreground | CAPEX `formatMarketCap` abs(), foreground | FCF `formatMarketCap`, signClass | — | — | — | accent: cyan-900 |
| 6 | DIVIDENDS | DIV YIELD `formatPercent`, gt3pct→positive | PAYOUT `formatPercent`, foreground | EX-DIV `formatDate`, foreground | PAY DATE `formatDate`, foreground | — | — | accent: violet-900 |
| 7 | OWNERSHIP | SHARES OUT `formatMarketCap`, foreground *(field: `shareStats.SharesOutstanding`)* | FLOAT `formatMarketCap`, foreground *(field: `shareStats.SharesFloat`)* | %INSIDERS `formatPercent` ÷100, foreground *(field: `shareStats.PercentInsiders`)* | %INST `formatPercent` ÷100, foreground *(field: `shareStats.PercentInstitutions`)* | — | — | accent: rose-900 | *(C-NEW-05: `ShareStatisticsData` uses EODHD PascalCase keys verbatim — NOT snake_case. `PercentInsiders` is raw-percent value, e.g. 1.64 = 1.64%; divide by 100 before formatPercent)* |
| 8 | TECHNICALS-LITE | BETA `toFixed(2)`, foreground | 52W H `formatPrice`, foreground | 52W L `formatPrice`, foreground | 50DMA `formatPrice`, foreground | 200DMA `formatPrice`, foreground | AVG VOL 30D `formatVolume`, foreground | accent: slate-700 |
| 9 | SHORTS (sub-row of 8) | SHRT SHRS `formatVolume`, foreground | SHRT RATIO `formatRatio`, foreground | SHRT % `formatPercent`, foreground | — | — | — | accent: slate-700 |

> Section accent tokens are conceptual — implementation MUST use `border-l-2 border-border` for all sections (visual differentiation comes from a 1px section divider, NOT new palette colors — per `_INDEX.md` ban on new colors). The accent column above is design rationale only.

### 6.5 "—" cell strategy (explicit per cell)
- Cells with `—` because they're **always backend-null** (INT COVERAGE, CREDIT RATING): **REMOVED from grid** (40 fields instead of 45)
- Cells with `—` because they're **on a different tab** (DAY RETURN, RSI, ATR): **REMOVED from grid** (moved to Quote tab where they make sense)
- Cells with `—` because **data hasn't backfilled yet** (e.g. new IPO without 4 FY of revenue): render `—` in `text-muted-foreground/40` (existing behaviour, keep)
- Cells with `—` because **the metric doesn't apply** (e.g. ETF with no dividend): render as `n/a` not `—`, in `text-muted-foreground/30`

### 6.6 Row 3, 4, 5, 6, 7, 9 only fill 3–4 of 6 columns
**Visual concern**: empty trailing cells look like gaps. **Solution**: empty cells render an `<div className="h-[18px]"/>` placeholder (NOT a `MetricCell` with empty label) — keeps the grid alignment but no visible content. The accent border-l only applies to the first cell of each section, so the trailing empties look like clean negative space, not broken cells.

Alternative considered: **pack rows tighter** (Finviz style — 4×8 not 6×8). Rejected because the 6-col layout matches the design system's spacing scale better (12px gap × 6 = wider columns that fit longer labels like "EV/EBITDA" un-truncated at 9px).

---

## 7. Interaction model

### 7.1 Hotkeys (scoped to this tab)
- `p` / `P`: toggle income-statement Annual/Quarterly — `q` is reserved for the global InstrumentTabs chord (switches to Quote tab); use `p` (period) to avoid conflict (C-W1-04)
- `e` / `E`: expand AI brief sidebar panel to full-height overlay
- `c` / `C`: expand Company snapshot description to full-height overlay
- `1`-`5`: jump scroll to section (1=snapshot, 2=income, 3=earnings, 4=peers, 5=insider/instit)
- `Esc`: close any overlay

### 7.2 Hover behaviour
- Metric cell hover: bg-muted/20 + tooltip with full metric name + formula (e.g. P/E → "Price-to-Earnings = Market Cap / TTM Net Income")
- Peer table row hover: row highlight; click → navigate to that ticker's Financials tab
- Insider/Institutional row hover: highlight; click → modal with full history of that holder/insider

### 7.3 Click handlers
- Sidebar "12-MO TARGET" → opens modal with target distribution histogram (10 firms binned)
- Sidebar "REVISIONS" → opens modal with last 90 days of revisions timeline
- Sidebar "AI BRIEF" "expand →" → opens full-tab AI brief overlay (same content as Intelligence tab summary section, dedup)
- Sidebar "COMPANY SNAPSHOT" "[more]" link → expands description to full text (max 600 chars; longer pages get a "view full description" modal)
- Sidebar "TGT BY ANALYST" row → opens external link to that analyst firm's research portal (where available) — gated by user setting "open external links"
- Below-fold "view all" on insider table → modal listing last 100 transactions

### 7.4 States
- **Loading**: skeleton rows (3 in snapshot, 5 in income, 5 in peer, 8 in insider/inst, sidebar uses 3 skeleton panels) — `text-shimmer` from existing primitives
- **Error**: replace affected block with `text-[11px] text-muted-foreground` inline error "Failed to load — retry" with click-to-retry button. Sibling blocks render normally
- **Empty (no data)**:
  - Snapshot: render the cells with `—` for missing values (don't hide the block)
  - Income statement: "Income statement not available" (existing copy, keep)
  - Earnings chart: hide entirely (existing behaviour, keep)
  - Peer table: "Peers not configured" with link to manually pick comparables
  - Insider/Institutional: hide the block (don't show empty headers)
  - Sidebar AI brief: explicit lazy-generate call sequence (C-BE-05): (1) `GET /briefings/instrument/{id}` → if 404, (2) fire `POST /briefings/instrument/{id}/generate`, (3) poll `GET` every 30s up to 5 attempts (use `refetchInterval` + `refetchIntervalInBackground: false`), (4) abandon to "Brief unavailable — retry later" after 5 failed polls
  - Sidebar company snapshot: always rendered (fundamentals always has at least sector + description for live equities)

---

## 8. Data fetching

All resources go through `useFinancialsTabData(instrumentId)` extended hook, but presentational components self-fetch via shared TanStack Query keys to allow deduplication.

| Resource | Query key (qk.*) | New? | staleTime | Reused by |
|---|---|---|---|---|
| `/v1/fundamentals/{id}` | `qk.instruments.fundamentals(id)` | existing | 30min | Quote tab, Intelligence tab |
| `/v1/fundamentals/{id}/snapshot` | `qk.instruments.fundamentalsSnapshot(id)` | existing | 30min | Quote tab |
| `/v1/fundamentals/{id}/technicals` | `qk.instruments.technicals(id)` | existing | 30min | Quote tab |
| `/v1/fundamentals/{id}/share-statistics` | `qk.instruments.shareStats(id)` | existing | 30min | Quote tab |
| `/v1/fundamentals/{id}/income-statement` | `["income-statement", id]` | existing | 24h | — |
| `/v1/fundamentals/{id}/earnings-annual-trend` | `["earnings-history", id]` | existing | 24h | Sidebar beat/miss |
| `/v1/fundamentals/{id}/splits-dividends` | `qk.instruments.splitsDividends(id)` | existing | 24h | — |
| `/v1/fundamentals/{id}/insider-transactions` | `qk.instruments.ownership(id)` *(existing key — reuse; page-bundle already seeds this)* | existing | 24h | — | *(C-NEW-02: do NOT add `insiderTxns` key; `ownership` already exists and is seeded by the page-bundle)* |
| `/v1/fundamentals/{id}/institutional-holders` | `qk.instruments.institutionalHolders(id)` *(new key)* | **NEW** | 24h | — | *(C-BE-01: S9 proxy route does NOT exist today — must add `GET /v1/fundamentals/{id}/institutional-holders` to `services/api-gateway/src/api_gateway/routers/fundamentals.py` ~15 LOC + test)* |
| `/v1/fundamentals/{id}/fund-holders` | `qk.instruments.fundHolders(id)` *(new key)* | **NEW** | 24h | — | *(C-BE-01: same — must add S9 proxy route for `/fund-holders`)* |
| `/v1/instruments/{id}/peers?n=5` | `qk.instruments.peers(id)` *(new key)* | **NEW — promoted to this wave** | 24h | Intelligence tab (could reuse) | *(C-BE-02: original wave ordering put this in Wave F / Quote. Peer comparison is a primary user task (§2.2 #3) — promote the backend endpoint to this wave. ~30 LOC S9 SQL query by `gics_industry` + market cap sort)* |
| `/v1/briefings/instrument/{entity_id}` | `qk.briefings.instrument(entityId)` | existing | 30s | Intelligence tab |
| `/v1/fundamentals/{id}/analyst-targets-by-firm` | `qk.instruments.analystTargetsByFirm(id)` *(new key)* | **NEW (needs backend endpoint)** | 30min | — |

### 8.1 Dedup opportunities
- `fundamentals` is shared with Quote + Intelligence tabs — single fetch when user navigates between them
- `briefings/instrument` is shared with Intelligence tab — same
- `peers` (if added) would be reusable across Financials + Intelligence

### 8.2 Cache-coherent EPS calculation
`EarningsBarChart` adds a chip showing `surprise_percent` per bar — already in `earnings-annual-trend` records `surprise_percent` field (inventory §1.2 line 45). No new fetch.

---

## 9. Tradeoffs & decisions

### 9.1 6-column grid vs 4-column grid (chosen: 6)
- **4-col**: rows fit longer labels (e.g. "INT COVERAGE") without truncation; easier on the eyes
- **6-col** (chosen): matches Finviz density target; we already removed truncation-prone labels (INT COVERAGE, CREDIT RATING) so the longest remaining label is "EV/EBITDA" (9 chars) which fits at 9px in a ~190px column
- **Decision**: 6-col wins because the user explicitly asked for "2× more density" and the labels we kept are short

### 9.2 Drop group-header rows vs keep (chosen: drop)
- **Keep**: section headers (VALUATION etc) are clear visual breaks; analysts trained on Bloomberg expect them
- **Drop** (chosen): each header row = 22px = wasted space; Finviz proves you can group via color/border hue without dedicated rows
- **Decision**: drop. Each section's first cell carries a 2px left accent border to delimit; a 9px right-edge tag column shows the section name on the first row of each group. Saves 8 × 22 = 176px of vertical space (= 10 extra data rows visible above the fold).

### 9.3 240px sidebar vs 280px (chosen: 240)
- **280px**: more room for analyst firm names, less truncation
- **240px** (chosen): matches the spacing scale's preference for tight design; firm names can use 3-letter codes (MS, GS, JPM) which all fit in 240
- **Decision**: 240. Frees 40px for the left column → wider peer comparison table.

### 9.4 Sidebar with 7 stacked panels vs 4 (chosen: 7)
- **4 panels**: less cognitive load, more whitespace
- **7** (chosen): user explicitly said "sidebar looks empty" — empty space IS the complaint
- **Decision**: 7. Total stack 768px in 840px viewport — 70px buffer for scroll padding, no gaps.

### 9.5 Hide vs leave-with-dash for always-null cells (chosen: hide)
- **Leave with dash**: stable layout (cell count fixed)
- **Hide** (chosen): the user explicitly called the dashes "gaps"; hiding tightens the grid
- **Decision**: hide INT COVERAGE / CREDIT RATING / DAY RETURN / RSI(14) / ATR(14). Backend backfill can re-add cells later (the 6-col grid has natural slots).

### 9.6 Peer comparison: client-side derivation vs new endpoint (chosen: new endpoint)
- **Client**: re-uses existing `/v1/fundamentals/screen` — no backend work
- **Endpoint** (chosen): single round-trip, cacheable, cleaner code
- **Decision**: new endpoint. Trivial S9 implementation. Flagged as open Q-1.

### 9.7 Quarterly toggle on income statement: in-place vs separate route (chosen: in-place)
- **In-place** (chosen): hotkey `p` flips a state flag; same component renders quarterly with 8 columns (last 8 quarters)
- **Decision**: in-place. Avoids new route, matches TradingView pattern.

---

## 10. Open questions

| ID | Question | Blocker for | Recommendation |
|---|---|---|---|
| Q-1 | ~~Add backend endpoint `GET /v1/instruments/{id}/peers?n=5`~~ | PeerComparisonTable | **RESOLVED (C-BE-02)**: New endpoint promoted to this wave (not Wave F). ~30 LOC S9 SQL + test. |
| Q-2 | Add backend endpoint `GET /v1/fundamentals/{id}/analyst-targets-by-firm` returning per-firm target prices? EODHD exposes individual firm targets in `AnalystRatings.*` but we don't surface them today. | Sidebar TgtByAnalyst panel | New endpoint required. Confirm EODHD plan tier exposes this field. If not, panel renders only the consensus target and falls back to "individual firm targets pending data provider upgrade". |
| Q-3 | Where does `RevisionsPanel` source 30-day delta from? `analyst_consensus` is stored as a snapshot; we'd need to keep history of last 30 days of snapshots. Currently the section keeps only the latest record. | Sidebar RevisionsPanel | Add S3 worker rotation: keep last-90d of `analyst_consensus` records (already happens for `earnings_trend`). Confirm S3 logic. |
| Q-4 | Should the company description respect i18n (some EODHD entries have non-English text)? | CompanySnapshotPanel | Out of scope for design — defer to i18n PRD. |
| Q-5 | AI brief currently shows generic morning-brief format. Should we add an "instrument-specific" brief variant that emphasises fundamentals over news? | AIBriefPanel | Yes — propose new S8 prompt for `/v1/briefings/instrument/{entity_id}` that takes fundamentals snapshot as context. Tracked separately. |
| Q-6 | ~~DenseMetricCell vs MetricCell; Sparkline new vs reuse~~ | DenseMetricsGrid | **RESOLVED (C-F1-02, C-F1-03)**: Reuse F1 primitives `components/primitives/MetricCell.tsx` and `components/primitives/Sparkline.tsx`. No new files. Row height driven by `data-table-grid="dense"` CSS var. Delete legacy `components/instrument/financials/MetricCell.tsx` during migration. |
| Q-7 | Peer table 1Y return needs OHLCV data for each peer. Hit `/v1/ohlcv/batch` with the 5 peer instrument_ids? | PeerComparisonTable | Yes — `/v1/ohlcv/batch` already supports multi-instrument fetch; compute 1Y from first/last bar client-side. |

---

## 11. Acceptance checklist

For the implementation wave to be accepted:
- [ ] Above-fold cell count ≥ 80 on 1440×900 (target: 172)
- [ ] Sidebar empty space ≤ 100px (target: ~70px buffer only)
- [ ] AI brief panel renders ≥ 3 bullets + risk score (target: 3 bullets + 1 risk chip + expand cta)
- [ ] Company snapshot panel renders sector + industry + employees + HQ + 4-line description
- [ ] Insider transactions table renders ≥ 8 rows (or "no recent activity" empty state)
- [ ] Institutional holders table renders ≥ 10 rows (or empty state)
- [ ] Peer comparison renders self + 5 peers × 9 columns
- [ ] Income statement supports Annual + Quarterly toggle via `p` key
- [ ] Earnings bar chart shows EPS surprise % per bar
- [ ] No cells render dash `—` for INT COVERAGE / CREDIT RATING / DAY RETURN / RSI(14) / ATR(14) (those are removed)
- [ ] Architecture test `no-off-palette-colors` continues to pass
- [ ] Vitest density check: `expect(visibleCells).toBeGreaterThanOrEqual(80)` on the snapshot grid render test
- [ ] Playwright above-the-fold screenshot diff against design (manual review)

---

## 12. Files touched (forecasted)

**New**:
- `components/instrument/financials/DenseMetricsGrid.tsx`
- ~~`components/instrument/financials/DenseMetricCell.tsx`~~ — **removed** (C-F1-02: reuse F1 primitive)
- `components/instrument/financials/PeerComparisonTable.tsx`
- `components/instrument/financials/InsiderTransactionsTable.tsx`
- `components/instrument/financials/InstitutionalHoldersTable.tsx`
- `components/instrument/financials/sidebar/AnalystConsensusPanel.tsx`
- `components/instrument/financials/sidebar/TargetPricePanel.tsx`
- `components/instrument/financials/sidebar/RevisionsPanel.tsx`
- `components/instrument/financials/sidebar/TargetsByAnalystPanel.tsx`
- `components/instrument/financials/sidebar/BeatMissHistoryPanel.tsx`
- `components/instrument/financials/sidebar/AIBriefPanel.tsx`
- `components/instrument/financials/sidebar/CompanySnapshotPanel.tsx`
- ~~`components/instrument/shared/Sparkline.tsx`~~ — **removed** (C-F1-03: reuse F1 primitive)
- Test files for each of the above

**Modified**:
- `components/instrument/financials/FinancialsTab.tsx` (rewrite orchestrator, 240px sidebar, ordering)
- `components/instrument/financials/IncomeStatementTable.tsx` (annual/quarterly toggle, sparkline col)
- `components/instrument/financials/EarningsBarChart.tsx` (64px height, EPS surprise chip)
- `components/instrument/financials/AnalystSidebar.tsx` (now a thin shell hosting the 7 panels)
- `components/instrument/hooks/useFinancialsTabData.ts` (add insider/institutional/peers/brief)
- `lib/query/keys.ts` (add new qk.instruments.* keys)
- `lib/gateway.ts` (add 4 new endpoints)

**Backend (pending Q-1, Q-2, Q-3)**:
- New S9 routes: `/v1/instruments/{id}/peers`, `/v1/fundamentals/{id}/analyst-targets-by-firm`
- S3 worker: snapshot rotation for `analyst_consensus` 90-day history (Q-3)

---

## 13. Cross-references

- Inventory: `docs/designs/0089/00-backend-data-inventory.md` §1.2, §1.2a, §1.4, §3.2, §3.7
- Index: `docs/designs/0089/_INDEX.md` §Typography, §Spacing, §Density principle
- Sibling design (Quote tab): `docs/designs/0089/05-instrument-quote.md` (pending — coordinate to ensure RSI/ATR/DAY RETURN land on Quote)
- Sibling design (Intelligence tab): `docs/designs/0089/07-instrument-intelligence.md` (pending — coordinate AI brief and peers deduplication)
- Prior implementation: PLAN-0090 T-C-01..T-C-03 (`docs/plans/0090-instrument-detail-page-redesign-plan.md`)
- Spec: `docs/specs/0088-instrument-detail-page-ground-up-redesign.md` §6.8.1
