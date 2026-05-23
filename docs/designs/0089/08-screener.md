# Screener — Design Spec (PRD-0089)

> Page route: `apps/worldview-web/app/(app)/screener/page.tsx`
> Status: design draft — PLAN-0091 iter-2 (2026-05-23): R-001 explanation field (Option A, backend + design), R-004 OP MGN% → opt-in column, E-001/E-003 avg_volume_30d + EV/EBITDA opt-in columns, R-005 dedup mutation, R-008 hotkey conflict resolved
> Author: agent-screener
> Density target: **20 result rows × 12 visible columns = 240 data cells above the fold at 1440×900**

---

## 1. Competitor research summary

The Screener is the page where Worldview is in **direct, head-to-head combat**
with the most polished tools in the industry. Below is the distilled lesson
from each.

### Finviz Screener (the density gold standard)

- 70+ filters compressed into a **single 6-row × 11-column grid of dropdowns**
  fitting in **~140 px of vertical chrome** at the top of the page.
- Every filter is a tiny `<select>` with the CURRENT VALUE rendered inline as
  the trigger label. Filters that are inactive show "Any" in muted grey;
  active filters render in **gold** (#A87900) so the user sees at a glance
  which knobs are dialed.
- Three filter macro-tabs above the grid: **Descriptive / Fundamental /
  Technical** — switches the visible 6×11 grid without reflowing the rest of
  the page.
- Quick "Filter presets" row above the tabs: textual preset slugs ("Major
  News, Most Volatile, Earnings Today, Heavy Buying, …") rendered as inline
  links — no spatial overhead.
- Results: **dense HTML table, 16 px row height, ~25-30 rows visible**, 11
  columns by default, **70+ columns available** via a "Custom" toggle that
  swaps the column set in-place.
- Sort: click header. Active sort header is gold-underlined with an arrow.
- Pagination: page-number bar at the bottom (1, 2, 3 … Next →) — they
  chose **paged** over infinite-scroll because the result count is the
  product (users scan totals, not feeds).
- Export: CSV download link inline with the column-set toggle.
- **Steal**: the inline-trigger-with-current-value dropdown convention,
  the macro-tab filter group switcher, the dense 16-px result row, and
  the visible "X / 7,453 total" counter.

### TradingView Stock Screener

- Filter bar lives in a **collapsible left rail** (~ 280 px wide) — different
  philosophy from Finviz: more readable individual filters but **half the
  density**.
- Best feature: **named presets** at the top of the rail ("Most Capitalized,
  Most Volatile, High Dividend, Earnings This Week, Top Gainers"). Each is
  one click. They lean on presets BECAUSE constructing a custom screen is
  more involved than Finviz.
- Result table is `12 px` body text, `28 px` rows. Mini sparklines per row.
  Multi-column sort indicator (sort by 2 fields shown with `1↓ 2↑` badges).
- Hover row: floats a "+ Watchlist / + Alert" mini-toolbar in the right of
  the row — context-aware action discovery.
- **Steal**: named presets as first-class UI, hover-row mini-toolbar, the
  multi-column sort indicator badge.

### Bloomberg EQS (Equity Screening)

- Three-pane layout: (1) saved-screens tree left, (2) criteria builder
  centre, (3) live count + preview right. The "live count" is the
  **killer feature**: as the user adds a criterion, the integer instrument
  count updates in <300 ms ("847 matches" → "212 matches" → "73 matches").
- Filters are not dropdowns; they are an **N-level criteria builder** where
  each leaf is an "operator + value" expression. Allows AND/OR/NOT groups.
  This is overkill for our v1 — we ship AND-only — but the *visible live
  count* is a must-have.
- Output table: dense, 14 px rows, infinite columns horizontally
  scrollable.
- **Steal**: the **live result count that updates as you build** (we already
  show `loadedCount of total match`, but it only fires on Apply — Bloomberg
  fires on every criterion change, debounced 250 ms).

### Stockanalysis.com Screener

- Modern, clean. Visible filter chips at the top: each active filter renders
  as a **dismissible chip** (`P/E ≤ 25  ×`). Inactive filters live in a "+
  Add filter" combobox that opens a categorised tree.
- The chip pattern is a **superb middle ground** between Finviz's 6×11
  dense grid (everything visible always) and TradingView's left rail
  (everything hidden behind toggles). Chips show what is set; everything
  else is one click away.
- Pagination: **load-more** (not paged). They chose this because their
  result count is small (US-listed only).
- **Steal**: the **active-filter chip strip** as the always-visible summary
  of what's filtered, plus a "+ Add filter" combobox for everything else.

### Koyfin / Tikr / Zacks

- Koyfin: ratio-driven, multi-period comparisons (TTM vs 3Y avg vs 5Y avg).
  We do not surface multi-period yet — defer to v2.
- Tikr: spreadsheet-style with pivot — too heavy for v1.
- Zacks: rank-based ("Zacks #1 Rank") — proprietary. We have our own
  `market_impact_score`; rank by it.

### What we steal vs leave on the table

| Steal (v1) | Source | Where in our design |
|------------|--------|---------------------|
| Dense `22 px` result row, 11 px monospace digits | Finviz | §6 |
| Active-filter chip strip + "+ Add filter" combobox | Stockanalysis | §4, §5 (FilterChipStrip) |
| 6-section macro grid as a "More filters" panel | Finviz | §4, §5 (FilterPanel) |
| Named preset row | TradingView | §4, §5 (PresetBar) |
| Live count debounced 250 ms | Bloomberg EQS | §7 |
| Hover-row mini-toolbar (+ Watchlist / + Alert) | TradingView | §7 |
| Load-more pagination (already in code) | Stockanalysis | §4 |
| CSV / PDF export (already in code) | Finviz | §5 (existing ExportMenu) |

| Defer (v2) | Why |
|------------|-----|
| Multi-period filters (TTM vs 3Y avg) | Backend doesn't expose multi-period aggregates yet |
| AND/OR/NOT criteria builder | Adds significant complexity; AND-only is good enough for the persona |
| 70+ column custom table | Backend `POST /v1/fundamentals/screen` returns only the standard fields + filter metrics |

---

## 2. User intent for this page

**Primary persona**: research analyst (F4) and quant trader (F5) — the same
two personas that run the Quote tab. The Screener is upstream of every
other page in the platform: it's where the user **decides which tickers to
investigate**.

**Primary tasks (top 3)**:

1. *"Show me cheap, profitable, growing US large caps."* — apply a 3-filter
   value-and-growth screen (P/E ≤ 20, ROE ≥ 15 %, Rev YoY ≥ 10 %), eyeball
   the top 20 rows, click into 3-5 tickers.
2. *"Compare two preset universes."* — load saved screen "Quality dividend
   stocks" vs "High-momentum growth", scan the differences.
3. *"Find names with recent news velocity."* — apply a news-velocity filter,
   sort by `score` desc, identify the top 10 stories driving the market today.

**Secondary tasks**:

- Save a custom screen for reuse next session.
- Export results to CSV for offline analysis.
- Adjust column visibility for a specific workflow (e.g. hide P/E if
  screening for early-stage growth).

**Anti-patterns** (things this page must NOT become):

- A wide spreadsheet that requires horizontal scrolling — every cell the
  user needs MUST fit at 1440 px.
- A wizard with multi-step "next" buttons — competitors are single-shot,
  we must be too.
- A page where adding a filter forces a full reload (kill the perceived
  responsiveness vs Finviz).
- A page where the result table is more than 28 px row height — that
  collapses density below institutional norms.

---

## 3. Backend data available

Cited from `docs/designs/0089/00-backend-data-inventory.md` §1.2 and
`docs/services/market-data.md` §screen.

### 3.1 Endpoint

**`POST /v1/fundamentals/screen`** (S9 → S3) — request body:

```jsonc
{
  "filters": [
    { "metric": "pe_ratio", "min_value": null, "max_value": 25,
      "period_type": "TTM" },
    { "metric": "roe_ttm",  "min_value": 0.15, "max_value": null,
      "period_type": "TTM", "sector": "Information Technology" }
  ],
  "limit": 50,                // PAGE_SIZE
  "offset": 0,
  "sort_by": "market_capitalization",   // whitelisted: metric name,
                                        //   `ticker`, or `name`
  "sort_order": "desc"
}
```

Response: `{ items: ScreenerResult[], total: number }`.

`ScreenerResult` fields (from `apps/worldview-web/types/api.ts`):
`instrument_id`, `entity_id`, `ticker`, `name`, `gics_sector`,
`current_price`, `daily_return`, `market_cap`, `pe_ratio`, `revenue`,
`beta`, `market_impact_score`, plus any filter metrics the user requested
(echoed back so the frontend can render the column without a second call).

### 3.2 Screenable metric names (server-side, AND logic, latest as_of_date per instrument)

From `docs/services/market-data.md` §807:

| Category | Frontend label | Backend metric name | Unit | Source |
|----------|----------------|---------------------|------|--------|
| Valuation | P/E (TTM) | `pe_ratio` | ratio | highlights / valuation_ratios |
| Valuation | P/B | `pb_ratio` | ratio | valuation_ratios |
| Valuation | P/S (TTM) | `price_sales_ttm` | ratio | valuation_ratios |
| Valuation | Forward P/E | `forward_pe` | ratio | valuation_ratios |
| Valuation | EV / EBITDA | `enterprise_value_ebitda` | ratio | valuation_ratios |
| Valuation | Dividend yield | `dividend_yield` | decimal (0.015 = 1.5 %) | highlights |
| Profitability | ROE (TTM) | `roe_ttm` | decimal | highlights |
| Profitability | ROA (TTM) | `roa_ttm` | decimal | highlights |
| Profitability | Operating margin (TTM) | `operating_margin_ttm` | decimal | highlights |
| Profitability | Net margin | `profit_margin` | decimal | highlights |
| Growth | Q rev growth YoY | `quarterly_revenue_growth_yoy` | decimal | highlights |
| Growth | Q earn growth YoY | `quarterly_earnings_growth_yoy` | decimal | highlights |
| Cap | Market cap | `market_capitalization` | USD | highlights |
| Risk | Beta | `beta` | ratio | technicals_snapshot |

### 3.3 Currently displayed vs missing

| Field | Source | Displayed today | Notes |
|-------|--------|----------------|-------|
| `ticker`, `name`, `gics_sector` | screen response | yes | pinned |
| `current_price`, `daily_return` | screen response | yes | already coloured |
| `market_cap`, `pe_ratio`, `revenue`, `beta` | screen response | yes | already coloured for beta |
| `market_impact_score` | screen response | yes | rendered as HeatCell |
| 30-day sparkline | `POST /v1/ohlcv/batch` | yes | already batched |
| **52W range** | NOT in screen response | **placeholder bar** | backend pending — column 11 in current code |
| **Avg volume** | `instrument_fundamentals_snapshot.avg_volume_30d` | **`—`** | backend exposes it but screen endpoint doesn't include it; **fix in design §3.4** |
| **Forward P/E** | `forward_pe` | **NO column** | backend supports it — surface as optional column |
| **Dividend yield** | `dividend_yield` | **NO column** | filter exists but column doesn't — add |
| **ROE TTM** | `roe_ttm` | **NO column** | filter exists but column doesn't — add |
| **Q rev growth** | `quarterly_revenue_growth_yoy` | **NO column** | filter exists but column doesn't — add |
| **Earnings date** | `economic-calendar` next event | NO | requires composed endpoint — defer to v2 |
| **News velocity 7d** | not exposed | NO | client-side TODO — keep stub |
| **Insider activity** | `/v1/fundamentals/{id}/insider-transactions` per row | NO | per-row N+1 — defer to v2 |

**Backend asks (proposed for v1)**:

- Include `avg_volume_30d` in `POST /v1/fundamentals/screen` response when
  the field is selected as a column (today it's already in
  `instrument_fundamentals_snapshot`).
- Echo the user-selected filter metrics in the response (already done) so
  the new columns below ("Div Y", "ROE", "Rev YoY", "Fwd P/E") render
  without extra round-trips.

### 3.4 Default new columns (v1 redesign)

| New column | Backend metric | Format | Color rule |
|------------|---------------|--------|------------|
| **DIV Y%** | `dividend_yield` * 100 | `2.45%` (2 dp) | text-foreground; `—` if null |
| **FWD P/E** | `forward_pe` | `18.3` (1 dp) | text-foreground |
| **ROE%** | `roe_ttm` * 100 | `14.2%` | green > 15, red < 0 |
| **REV YoY** | `quarterly_revenue_growth_yoy` * 100 | `+12.4%` | green > 0, red < 0 |

These four replace the current "REVENUE" column (absolute revenue is rarely
useful — analysts care about growth) and pull the screener into Finviz territory.

**Opt-in hidden columns** (available in `ColumnSettingsPopover`, not shown by default):

| Column | Backend metric | Format | Notes |
|--------|---------------|--------|-------|
| **OP MGN%** | `operating_margin_ttm` * 100 | `28.1%` | green > 20; dropped from defaults — 12 visible cols already fills 1440px |
| **EV/EBITDA** | `enterprise_value_ebitda` | `22.1×` (1 dp) | text-foreground; preferred by IB/PE analysts over P/E for capital-structure-neutral comparison |
| **AVG VOL** | `avg_volume_30d` | `50M` | backend ask: include `avg_volume_30d` in screen response; field lives in `instrument_fundamentals_snapshot.avg_volume_30d`; **backend must add this field to the screen response** |

---

## 4. Layout

### 4.1 1440×900 ASCII wireframe (full-width, no left rail — the left rail is the global TopBar's sidebar)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────── 1440 ──┐
│ TOPBAR (32px) — already global. Not part of this design.                                                                │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ROW 1 (28px) — page title + result count + saved-screen / columns / export ─────────────────────────────────────────────│
│ SCREENER  •  7,453 / 7,453 match           ⚡ Live  │  ◇ Saved Screens   ⋮ Columns   ↓ Export                            │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ROW 2 (24px) — PRESETS (TradingView pattern) — single horizontal scrollable row, each preset is a pill ────────────────│
│ [Quality stocks] [Cheap & growing] [High dividend] [Top by score] [Recent earnings] [Heavy buying] [+ New preset]        │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ROW 3 (28px) — ACTIVE FILTER CHIPS (Stockanalysis pattern) — wraps to row 4 if more than ~10 chips ────────────────────│
│ Sector: IT × │ Cap: Large × │ P/E ≤ 25 × │ ROE ≥ 15% × │ Rev YoY ≥ 10% │      [+ Add filter]    [Save…]  [Reset]        │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ROW 4 (22px sticky) — TABLE HEADER (12 columns) — header height = 22 px, body height = 22 px ─────────────────────────│
│ ┌────┬──────────────────┬──────────┬──────┬───────┬───────┬─────┬──────┬───────┬───────┬──────┬───────┬─────────┐      │
│ │TKR │ NAME             │ SECTOR   │PRICE │ CHG%  │ MKT C │ P/E │FWD PE│ DIV Y │ ROE   │REV YoY│ SCORE │ TREND   │      │
│ ├────┼──────────────────┼──────────┼──────┼───────┼───────┼─────┼──────┼───────┼───────┼───────┼───────┼─────────┤      │
│ │AAPL│ Apple Inc.       │ Tech     │184.71│ +1.24%│ 2.85T │28.4 │ 26.1 │ 0.55% │ 161%  │ +8.2% │ ▮▮▮▮▮ │  /\__/\ │ ◄ 22px│
│ │MSFT│ Microsoft Corp   │ Tech     │419.30│ +0.67%│ 3.12T │35.2 │ 32.5 │ 0.72% │  39%  │+17.6% │ ▮▮▮▮  │  __/--  │      │
│ │NVDA│ NVIDIA Corp      │ Tech     │942.10│ +2.45%│ 2.31T │72.8 │ 41.0 │ 0.02% │ 119%  │+265%  │ ▮▮▮▮▮ │   /--   │      │
│ │GOOG│ Alphabet Inc     │ Comm Svc │174.55│ −0.31%│ 2.18T │25.9 │ 22.4 │  —    │  29%  │+15.1% │ ▮▮▮▮  │ \--\__  │      │
│ │META│ Meta Platforms   │ Comm Svc │482.20│ +1.05%│ 1.23T │27.6 │ 24.8 │ 0.42% │  34%  │+27.3% │ ▮▮▮▮  │ __--/   │      │
│ │AMZN│ Amazon.com Inc   │ Cons Dis │188.99│ +0.88%│ 1.96T │51.2 │ 38.5 │  —    │  18%  │+12.6% │ ▮▮▮   │ /--\__  │      │
│ │BRK │ Berkshire Hath B │ Fin      │406.12│ +0.12%│ 887B  │ 9.1 │  9.4 │  —    │  10%  │ +1.2% │ ▮▮    │  ____/  │      │
│ │JPM │ JPMorgan Chase   │ Fin      │198.40│ +0.31%│ 565B  │11.4 │ 10.8 │ 2.20% │  17%  │ +9.5% │ ▮▮▮   │ /__--/  │      │
│ │V   │ Visa Inc Class A │ Fin      │275.66│ +0.45%│ 553B  │30.1 │ 27.0 │ 0.74% │  46%  │+10.0% │ ▮▮▮▮  │  /-/-   │      │
│ │MA  │ Mastercard Inc   │ Fin      │456.32│ +0.81%│ 423B  │35.8 │ 30.2 │ 0.55% │ 167%  │+12.8% │ ▮▮▮▮  │ ___---  │      │
│ │JNJ │ Johnson & Johnso │ Hlth     │156.10│ −0.05%│ 376B  │14.7 │ 13.9 │ 3.18% │  23%  │ +5.5% │ ▮▮    │ \____   │      │
│ │UNH │ UnitedHealth Grp │ Hlth     │491.40│ +0.92%│ 451B  │19.8 │ 18.1 │ 1.58% │  25%  │+11.3% │ ▮▮▮   │  __--/  │      │
│ │XOM │ Exxon Mobil Corp │ Energy   │112.85│ +1.61%│ 481B  │ 8.3 │ 11.2 │ 3.40% │  21%  │−15.2% │ ▮▮    │  /\__   │      │
│ │CVX │ Chevron Corp     │ Energy   │157.40│ +1.45%│ 296B  │11.2 │ 13.5 │ 4.15% │  16%  │−18.6% │ ▮▮    │  __/--  │      │
│ │WMT │ Walmart Inc      │ Cons Sta │ 67.34│ +0.18%│ 540B  │30.1 │ 27.5 │ 1.40% │  22%  │ +6.0% │ ▮▮    │ ___---  │      │
│ │PG  │ Procter & Gamble │ Cons Sta │166.45│ −0.21%│ 391B  │27.4 │ 25.0 │ 2.40% │  31%  │ +4.2% │ ▮▮    │ \__/-/  │      │
│ │HD  │ Home Depot Inc   │ Cons Dis │357.10│ +0.43%│ 354B  │25.8 │ 23.6 │ 2.60% │ ∞     │ −0.5% │ ▮▮▮   │ \--\__  │      │
│ │COST│ Costco Wholesale │ Cons Sta │865.20│ +1.12%│ 384B  │51.4 │ 47.0 │ 0.50% │  31%  │ +9.1% │ ▮▮▮   │  /--/   │      │
│ │LLY │ Eli Lilly & Co   │ Hlth     │784.65│ +1.78%│ 745B  │112  │ 60.5 │ 0.62% │  74%  │+36.9% │ ▮▮▮▮▮ │   /--   │      │
│ │ABBV│ AbbVie Inc       │ Hlth     │169.80│ +0.62%│ 300B  │54.2 │ 14.5 │ 3.43% │ 84%   │ +0.7% │ ▮▮▮   │  __--/  │  ◄ row 20│
│ └────┴──────────────────┴──────────┴──────┴───────┴───────┴─────┴──────┴───────┴───────┴───────┴───────┴─────────┘      │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ROW 5 (24px) — LOAD MORE bar ────────────────────────────────────────────────────────────────────────────────────────────│
│   [ Load 50 more ]   20 of 7,453 loaded                                                          ⌘K · / Search · F Filter│
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1a NL Screener Input (PLAN-0091 Wave F-2)

The NL input lives as **Row 2.5** — inserted between the preset bar (Row 2)
and the active filter chips (Row 3). It is conditionally visible: hidden when
collapsed, shown as a 28 px bar when the user activates it (via the `/` hotkey
or a "Search in natural language" affordance in the chip strip).

**Visual spec** (28 px height, full-width within `px-3` page margin):

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  e.g. profitable tech companies below 15× forward P/E with insider buying [→]│
└─────────────────────────────────────────────────────────────────────────────┘
Interpreted as: P/E < 15 AND revenue_growth > 0 AND insider_buy_90d > 0
[TECH ×] [P/E < 15 ×] [REVENUE GROWTH > 0% ×] [INSIDER BUY ×]          Apply
```

- **Input bar** (`bg-input border border-border/40 rounded-[2px]`): 28 px tall,
  full-width minus 32 px total page margin. Placeholder text in
  `text-muted-foreground text-[10px]`. Submit arrow button (`[→]`) is a 22×22 px
  icon button (`bg-primary/10 hover:bg-primary/20 text-primary`) flush against
  the right inner edge.
- **"Interpreted as:" line**: 16 px tall (`text-[10px] font-mono text-muted-foreground`).
  Populated from the `explanation` field of `NLScreenerResponse` — a 1-sentence
  plain-English description generated by the LLM (e.g. "Profitable technology stocks
  with P/E below 20 and positive net margins"). The backend returns this alongside
  `filters` in the new two-key response format (R-001 fix, Option A). Visible only
  after a successful translation. During translation: a 12 px tall skeleton bar
  (`bg-card animate-pulse rounded-[2px] w-3/4`).
- **Filter chips** (same 18 px chip height as the existing filter strip): rendered
  below the explanation line, using the identical `bg-primary/10 border-primary/60
  text-primary` styling as existing chips. An `Apply` button (`text-[10px]
  font-mono text-primary hover:text-foreground`) sits right-aligned on the same
  row as the chips.
- **Error state**: single line below input in `text-[10px] text-negative font-mono`:
  `"Could not translate — try being more specific"`.

**Interaction flow**:

1. User types a natural-language query in the input (placeholder:
   `"e.g. profitable tech companies below 15× forward P/E with insider buying"`).
2. Pressing `Enter` or clicking `[→]` calls `POST /v1/screener/nl-translate` with
   `{ query: str }`. This is a **mutation** (not a query) because LLM calls are
   non-idempotent.
3. While translating: skeleton bar replaces the "Interpreted as:" line; input
   is disabled; arrow button shows a spinner.
4. On success: `explanation` populates the "Interpreted as:" line; structured
   filter chips appear below it. The user may click `Apply` to execute the
   screener with the auto-populated filters, or individually dismiss chips (`×`)
   before applying. Clicking `Apply` calls `onFiltersApplied(filters)` on the
   parent page.
5. On parse failure (`422` or LLM returns `{ error }`):
   `"Could not translate — try being more specific"` appears in `text-negative`
   below the input. Existing filters are untouched.
6. NL is **additive, not destructive**: any filters already set in the chip strip
   survive. The NL-derived chips are appended to the existing set.
7. The user can always edit individual chips after NL auto-population (same
   chip-removal UX as the existing filter strip).

**Security note**: S9's `POST /v1/screener/nl-translate` validates all returned
`field` values against the allowlist served by `GET /v1/fundamentals/screen/fields`
before returning the `filters` array. As a defence-in-depth measure, the
`NLScreenerInput` component MUST also skip rendering any chip whose `field`
value is not present in the `qk.screener.fields()` cache. This prevents a
compromised or misbehaving LLM response from rendering a filter chip that maps to
an arbitrary DB column.

Column widths (sum = 1440 minus 1 px scrollbar gutter — frozen left, free right):

| # | Col | px | Frozen | Sortable |
|---|-----|----|--------|----------|
| 1 | TKR | 56 | yes (left-pinned) | yes |
| 2 | NAME | 200 | no | yes |
| 3 | SECTOR | 96 | no | yes |
| 4 | PRICE | 76 | no | yes |
| 5 | CHG% | 76 | no | yes |
| 6 | MKT C | 80 | no | yes |
| 7 | P/E | 60 | no | yes |
| 8 | FWD PE | 64 | no | yes |
| 9 | DIV Y | 64 | no | yes |
| 10 | ROE | 64 | no | yes |
| 11 | REV YoY | 76 | no | yes |
| 12 | SCORE | 72 | no | yes |
| 13 | TREND (30D) | 80 | no | no |
| — | **Total** | **1064 px** | — | — |

That leaves **376 px** of right-hand canvas. We use it for the **hover
mini-toolbar** (`+ Watchlist · + Alert · ⚐ Compare`) that floats over the
right edge of the hovered row — the toolbar is absolutely positioned and
does NOT consume a column.

When the user enables additional columns via the existing
`ColumnSettingsPopover`, they push into that 376 px before the table starts
horizontally scrolling.

### 4.2 Density math (above-the-fold @ 1440×900)

**Without NL input expanded** (NL row collapsed — default state):

```
viewport height       900 px
- topbar (global)      32 px  →  868
- row 1 (toolbar)      28 px  →  840
- row 2 (presets)      24 px  →  816
- row 3 (chips)        28 px  →  788
- row 4 (header)       22 px  →  766
- row 5 (load-more)    24 px  →  742  ← reserved at bottom regardless
- 20 rows × 22 px     440 px  →  302  ← below-fold buffer (lets users scroll
                                          one screen of rows without re-paginating)
```

**With NL input expanded** (28 px input + ~16 px "Interpreted as:" line +
~18 px chip row = ~62 px total for Row 2.5):

```
viewport height       900 px
- topbar (global)      32 px  →  868
- row 1 (toolbar)      28 px  →  840
- row 2 (presets)      24 px  →  816
- row 2.5 (NL input)   62 px  →  754  ← shown only when NL is active
- row 3 (chips)        28 px  →  726
- row 4 (header)       22 px  →  704
- row 5 (load-more)    24 px  →  680  ← reserved at bottom regardless
- ~17 rows × 22 px    374 px  →  306  ← below-fold buffer
```

The NL panel costs ~62 px when visible, reducing above-fold rows from 20 to
~17. This is acceptable because the NL input is only visible during the active
construction phase of a new screen, not during routine browsing.

So **20 result rows × 12 numeric columns = 240 data cells visible** before
any scroll (NL collapsed, default state). Target met.

When the user expands the "+ Add filter" panel (the Finviz 6-section
collapsible) the panel slides in BELOW row 3 with a max height of 220 px,
pushing the table down. Rows visible drop to ~10 — acceptable while the
user is actively building the screen.

### 4.3 Sticky regions

- Rows 1-3 (toolbar / presets / chips) — sticky to the top of the page on
  vertical scroll (table can scroll under them).
- Row 4 (table header) — sticky immediately below row 3.
- Row 5 (load-more) — sticky to the bottom of the viewport (always visible,
  even on long lists). Aligns with TradingView's persistent footer.

---

## 5. Component breakdown

All paths under `apps/worldview-web/`.

| Component | Path | Lines | Props | Renders |
|-----------|------|-------|-------|---------|
| `ScreenerPage` | `app/(app)/screener/page.tsx` | ~250 | — (route) | Composes the 5 rows; owns `appliedFilters`, `offset`, `accumulator`, AG Grid ref. Already exists; redesign reduces it from 401 → ~250 lines by extracting `ScreenerHeader` and `FilterChipStrip`. |
| `ScreenerHeader` | `components/screener/ScreenerHeader.tsx` | ~80 | `total, loaded, isLive, onOpenSaved, columns, onColumnsChange, rows, exportColumns` | Row 1 — page title, live result count (`X / Y match` debounced 250 ms), live-dot, `Saved Screens` button, `ColumnSettingsPopover`, `ExportMenu`. **NEW** — extracts the existing inline toolbar. |
| `PresetBar` | `components/screener/PresetBar.tsx` | ~120 | `presets: SavedScreen[], onApply: (s) => void, onSavePreset: () => void` | Row 2 — horizontally scrollable pill list. Each pill = saved-screen name; click loads the FilterState. The first 4 are **system presets** seeded in `lib/screener/presets.ts`; the rest are user-saved (from `SavedScreensDialog`). **NEW**. |
| `NLScreenerInput` | `components/screener/NLScreenerInput.tsx` | ~120 | `onFiltersApplied: (filters: ScreenerFilter[]) => void` | Row 2.5 (conditionally visible) — natural-language query bar. Calls `POST /v1/screener/nl-translate` via a TanStack mutation; renders "Interpreted as:" explanation line + auto-populated filter chips + `Apply` button. Frontend-side allowlist guard: skips chips for fields absent from `qk.screener.fields()` cache. **NEW** (PLAN-0091 Wave F-2). |
| `FilterChipStrip` | `components/screener/FilterChipStrip.tsx` | ~140 | `filters: FilterState, onRemove, onAddFilter, onSave, onReset` | Row 3 — renders one chip per active filter from `FilterState` (e.g. `P/E ≤ 25  ×`), an "+ Add filter" combobox that opens `FilterPanel` as a popover, and `Save…` + `Reset` actions. **NEW** — replaces the existing always-visible `ScreenerFilterBar` header row. |
| `FilterPanel` | `components/screener/FilterPanel.tsx` | ~400 | `value: FilterState, onChange, onApply, open, onOpenChange` | The "+ Add filter" popover content. Renders the Finviz 6-section grid (Valuation / Profitability / Growth / Leverage / Technical / News). Refactor of the existing `ScreenerFilterBar` — keep the `Section` + `RangeInput` sub-components, drop the toolbar wrapper, reduce sections from collapsible to always-expanded inside the popover. **REFACTOR** of existing file. |
| `ScreenerTable` (wraps `AgGridBase`) | `components/screener/ScreenerTable.tsx` | ~100 | `rows, columnDefs, onRowClick, onGridReady, sparklines` | Row 4 — already exists as inline `AgGridBase` in the page. Extract to its own component for testability. Adds the hover-row mini-toolbar overlay. **REFACTOR**. |
| `RowHoverToolbar` | `components/screener/RowHoverToolbar.tsx` | ~80 | `instrumentId, ticker, onWatch, onAlert, onCompare` | Floating absolute-positioned 3-button cluster (`+ Watch`, `⚐ Alert`, `Compare`) that appears on row hover. Uses Radix `Tooltip`. **NEW**. |
| `LoadMoreBar` | `components/screener/LoadMoreBar.tsx` | ~50 | `canLoadMore, isFetching, accumulatorCount, total, nextBatch, onLoadMore` | Row 5 — extracts the existing inline load-more block. **NEW** (extraction). |
| `ag-screener-columns.tsx` | `components/screener/ag-screener-columns.tsx` | ~400 | `sparklines: Record<id, OHLCVBar[]>` | AG Grid `ColDef[]` factory. **EXTEND** the existing file with 4 new columns (DIV Y, FWD P/E, ROE, REV YoY) and replace the "REVENUE" column with the more useful REV YoY. |
| `ag-screener-row-hover.tsx` | `components/screener/ag-screener-row-hover.tsx` | ~30 | — | AG Grid `cellRenderer` for an invisible right-pinned overlay column that mounts `RowHoverToolbar` on the focused row. Alternative: use AG Grid `rowMouseOver` event. **NEW**. |
| `lib/screener/presets.ts` | `lib/screener/presets.ts` | ~120 | — | Constant array of system presets (Quality, Cheap & Growing, High Dividend, Top by Score, Recent Earnings, Heavy Buying). Each is a `FilterState` literal. **NEW**. |
| `features/screener/lib/filter-state.ts` | (existing) | unchanged | — | Filter shape — already in place; reuse verbatim. |
| `features/screener/lib/build-filters.ts` | (existing) | unchanged | — | Maps `FilterState` → S9 `ScreenerRequest`; already in place. |
| `features/screener/lib/apply-client-filters.ts` | (existing) | unchanged | — | Applies client-side filters. |
| `SavedScreensDialog` | `components/screener/SavedScreensDialog.tsx` | unchanged | — | Already in place; reused for "Save…" in the chip strip. |
| `ColumnSettingsPopover` | `components/screener/ColumnSettingsPopover.tsx` | unchanged | — | Already in place. |
| `ExportMenu` | `components/screener/ExportMenu.tsx` | unchanged | — | Already in place. |

**Net file count delta**: +8 new, +2 refactor, 0 deletions (`NLScreenerInput`
adds 1 to the original +7). Filter state shape stays. `ScreenerFilterBar.tsx`
is **deleted** — its responsibilities move to `FilterChipStrip`
(always-visible chips) and `FilterPanel` (popover with the 6 sections).

---

## 6. Visual spec (numerical)

### 6.1 Spacing & rows

- **Page padding**: `px-3` (12 px) on left and right edges; no top padding
  (rows are flush against the global topbar).
- **Row 1 height**: 28 px (`h-7`). Internal gap between buttons: 8 px.
- **Row 2 height**: 24 px (`h-6`). Pill height: 22 px. Pill internal
  padding: `px-2.5 py-0.5`. Gap between pills: 6 px.
- **Row 3 height**: 28 px (auto-grows to 56 px max when wrapping). Chip
  height: 20 px. Chip internal padding: `px-2 py-0.5`. Gap between chips:
  6 px.
- **Row 4 (table header)**: 22 px. Internal cell padding: `px-2`. Header
  font: `text-[10px] uppercase tracking-[0.06em] font-mono text-muted-foreground`.
- **Row 5 (table body)**: 22 px per row. Internal cell padding: `px-2`.
  Body font: `text-[11px] font-mono tabular-nums text-foreground` for
  numeric cells; sans for `NAME`.
- **Row 6 (load-more)**: 24 px. Button height: 22 px.

### 6.2 Typography (from §Typography in `_INDEX.md`)

- Header chrome (row 1 title): `text-[10px]` uppercase tracking-[0.08em].
- Preset pills: `text-[10px]` uppercase tracking-[0.06em] mono.
- Filter chips: `text-[10px]` mono, label not uppercased.
- Table header: `text-[10px]` uppercase tracking-[0.06em] mono muted.
- Table body numeric: `text-[11px]` mono tabular-nums foreground.
- Table body NAME: `text-[11px]` sans foreground (one column is sans on
  purpose for readability of company names).
- Load-more count: `text-[10px]` mono tabular-nums muted.
- Hint badges ("client-side", "TODO: server"): `text-[9px]` mono warning.

### 6.3 Color palette (Terminal Dark — no new tokens)

| Element | Token |
|---------|-------|
| Page background | `bg-background` (#09090B) |
| Header / preset bar / chip strip background | `bg-card` (#0D0D10) |
| Hairlines between rows | `border-border` (#1F1F23) |
| Active filter chip border + text | `border-primary text-primary` |
| Inactive filter chip border | `border-border text-muted-foreground` |
| Active preset pill background | `bg-primary/10 border-primary text-primary` |
| Ticker cell text | `text-primary` |
| CHG% positive | `bg-positive/10 text-positive` |
| CHG% negative | `bg-negative/10 text-negative` |
| Beta > 1.5 | `text-warning` |
| ROE > 15 % | `text-positive` |
| ROE < 0 | `text-negative` |
| REV YoY > 0 | `text-positive` |
| REV YoY < 0 | `text-negative` |
| SCORE heat cells | existing `HeatCell` 7-step scale |
| Hover row background | `bg-foreground/[0.03]` (3 % white tint on dark) |

### 6.4 Pill / chip rendering rules

**Preset pill**:

```
┌─────────────────────────┐
│  Quality stocks         │   22 px h × auto w (px-2.5)
└─────────────────────────┘
```

- Default: `bg-card border border-border text-muted-foreground`
- Active (the currently-loaded preset): `bg-primary/10 border-primary text-primary`
- Hover: `text-foreground border-border/80`
- Border-radius: `rounded-[2px]` (corner = 2 px, terminal-grade)

**Filter chip**:

```
┌───────────────────┐
│ P/E ≤ 25       ×  │   20 px h × auto w
└───────────────────┘
```

- Always rendered with the **operator inline** (`P/E ≤ 25`, `ROE ≥ 15 %`,
  `Sector: IT`, `Cap: Large`).
- Trailing `×` dismisses the filter. Clicking the body (not `×`) opens the
  FilterPanel scrolled to that filter for editing.
- Default styling: `bg-primary/10 border-primary/60 text-primary` because
  every chip is, by definition, an active filter.
- `×` icon: `lucide:x`, 12 px, `text-muted-foreground hover:text-foreground`.

### 6.5 SCORE heat indicator

Replace the existing 1-cell `HeatCell` with a **5-segment bar** so the user
can read the score in peripheral vision at the same time as the digits:

```
SCORE
▮▮▮▮▮   ← 5/5 = ≥ 0.80
▮▮▮▮     ← 4/5 = 0.60-0.79
▮▮▮      ← 3/5 = 0.40-0.59
▮▮       ← 2/5 = 0.20-0.39
▮        ← 1/5 = 0.05-0.19
—        ← null or < 0.05
```

Each filled segment: `bg-primary`. Each empty segment: `bg-border`.
Segment width: 8 px. Gap between segments: 1 px.

### 6.6 Border radii & animations

- All buttons, chips, pills, inputs: `rounded-[2px]`. No rounded-full,
  ever — that would clash with the terminal aesthetic.
- Animations: only **grid-template-rows 0fr → 1fr** for the FilterPanel
  popover expand (already DESIGN_SYSTEM §0.5 approved). 150 ms ease-out.
- Hover transitions on chips / pills / rows: `transition-colors duration-100`.

---

## 7. Interaction model

### 7.1 Hotkeys (page-scoped — registered on mount, unregistered on unmount)

| Key | Action |
|-----|--------|
| `/` | **Within the screener page**: open/focus the `NLScreenerInput` bar. This **overrides** the global `/` handler (which opens the command palette) while the screener page is mounted. Registered via `useScopedHotkeys` with `preventDefault: true` — the global handler does NOT fire. When `NLScreenerInput` is already focused, `/` is a no-op (input already active). |
| `f` | Open the FilterPanel popover. |
| `s` | Open the Saved Screens dialog. |
| `r` | Reset all filters (with confirm if any are set). |
| `e` | Open the Export menu. |
| `n` | Save the current screen (open Save dialog). |
| `Esc` | Close any open popover; if none open, clear search input. |
| `Enter` (on focused row) | Navigate to `/instruments/{instrument_id}`. |
| `↑ ↓` | Move row focus. |
| `Shift + ↓` | Multi-select rows for batch Watchlist / Alert. |
| `⌘ + ↓` | Jump to bottom of loaded results; auto-fires Load More if any remain. |
| `?` | Open the cheat sheet overlay (already global). |

Hotkeys are registered via the existing `useScopedHotkeys` hook (from
`hooks/useScopedHotkeys.ts`). Each hotkey is **suppressed** when an input
or textarea is focused (the hook already does this).

### 7.2 Hover behaviour

- **Row hover**: background → `bg-foreground/[0.03]`. The
  `RowHoverToolbar` (right edge, 3 buttons) fades in over 100 ms.
- **Header hover**: cursor → pointer; underline appears on the sort arrow
  region. Tooltip with full column name (e.g. "Forward P/E Ratio") fires
  after 400 ms.
- **Chip hover**: `×` icon brightens; the chip body shows the underline
  cursor — clicking the body opens the FilterPanel; clicking the `×`
  removes the filter.
- **Preset hover**: pill border brightens.

### 7.3 Click behaviour

- Row click (anywhere except hover-toolbar buttons): navigate to
  `/instruments/{instrument_id}`.
- `+ Watchlist` button: adds to default watchlist via `POST /v1/watchlists/{id}/items`.
- `⚐ Alert` button: opens the Create Alert dialog (existing) pre-filled
  with the instrument.
- `Compare` button: pushes the instrument into a session-scoped compare
  set (toast: "AAPL added to compare set (2)"); when set reaches 2-5,
  show a floating "Compare 3" CTA → `/compare`.
- Header click: cycles asc → desc → unsorted (AG Grid default).
- Chip body click: opens FilterPanel scrolled to that section.

### 7.4 States

**Loading** (initial `isLoading === true`):

- Header shows `…` instead of `7,453 match`.
- Table renders 20 skeleton rows: each cell is a 12 px tall
  `bg-card animate-pulse` block, respecting the column widths.
- Load-more bar is hidden.

**Empty** (initial state, no filters, no apply yet):

- Render 20 placeholder rows of the top S&P 500 names sorted by market cap
  (i.e. fire the screen with no filters, sort by `market_capitalization`
  desc, limit 50). This makes the page **never empty** — competitors
  always show the universe by default.

**Empty after filter** (`!isLoading && filteredRows.length === 0`):

- Use existing `DashboardEmptyState` with copy:
  > **No instruments match these filters**
  > Try widening a range or removing a filter. Common culprits: P/E ≤ N
  > excludes negative earners; Dividend Yield ≥ N excludes growth names.
- Below the message: a "Reset filters" primary button.

**Error**:

- AG Grid does not render; instead a full-width error panel:
  > **Screener temporarily unavailable**
  > {error.message}
  > [Retry]
- The Retry button re-runs the query.

**Partial load** (Load More in progress):

- The Load More button text changes to `Loading…` and is disabled.
- A 1.5 px primary-coloured dot pulses in row 1 next to the result count.
- Already-loaded rows remain visible and interactive.

**Sparkline suppressed** (rows > 200):

- Existing `SPARKLINE_ROW_LIMIT = 200` behaviour kept. Sparkline column
  renders an `—` and tooltip "Sparklines hidden for performance — narrow
  the filter set below 200 rows to show".

### 7.5 Live result count (Bloomberg EQS pattern, debounced)

- As the user adjusts inputs in the FilterPanel, fire a **debounced 250 ms**
  `POST /v1/fundamentals/screen` with `limit: 0` (count-only) and update
  the "X / Y match" in row 1.
- Server already returns `total` via `COUNT(*) OVER()` — the count-only
  request just discards `items`. To save bandwidth: pass `limit: 1`.
- The Apply button in the FilterPanel becomes **redundant in spirit** but
  is kept for explicit commit (the table itself only re-fetches the full
  page when the user clicks Apply or hits Enter in the search). This
  preserves the existing perceived-performance contract.

---

## 8. Data fetching

### 8.1 TanStack Query keys

Adds to `lib/query/keys.ts` (`qk.screener.*`):

```ts
qk.screener = {
  // existing — full result page
  page: (filtersSerialized: string, offset: number) =>
    ["screener","page", filtersSerialized, offset] as const,

  // NEW — count-only debounced live count
  count: (filtersSerialized: string) =>
    ["screener","count", filtersSerialized] as const,

  // NEW — system + user presets list
  presets: () => ["screener","presets"] as const,

  // existing — list of screenable metric fields (also used by NLScreenerInput
  // as the allowlist to guard against unexpected LLM-produced field names)
  fields: () => ["screener","fields"] as const,

  // existing — column visibility prefs (localStorage-backed, no network)
  // ...
}
```

NL translation is a **mutation** (not a query key) because LLM calls are
non-idempotent. No query cache entry is created for NL results — they are
ephemeral (each submit is a fresh call; the user's typed query text is local
React state). See §8.5 for the full `useMutation` implementation with
`explanation` rendering and allowlist guard.

### 8.2 Stale times

| Key | staleTime | Justification |
|-----|-----------|---------------|
| `qk.screener.page(filters, offset)` | 30 000 ms (existing) | Match the existing setting; fundamentals don't change intra-minute, quotes are stale-tolerated for 30 s on this surface. |
| `qk.screener.count(filters)` | 5 000 ms | Live count is the responsiveness signal; 5 s is short enough to feel live without DDoSing S9. |
| `qk.screener.presets()` | 5 min | Presets rarely change; user-saved presets invalidate the key on save. |
| `qk.screener.fields()` | 1 hour (existing) | Field metadata is near-static. Also consumed by `NLScreenerInput` as the allowlist for returned filter fields. |
| Sparklines (`useScreenerSparklines`) | 60 s (existing) | Existing behaviour. |
| NL translate mutation | n/a (mutation) | Not cached — each submit is a fresh LLM call. |

### 8.3 Reuse opportunities


- `qk.quote.batch` (already used by watchlist + portfolio header) — for the
  hover-row `+ Alert` action that needs a fresh price quote, we
  `queryClient.fetchQuery(qk.quote.batch([id]))` rather than a one-off.
- `qk.screener.presets()` is reused by the Workspace page (PRD-0089 §9
  — Workspace can pin a screener panel that loads a preset).
- `qk.fundamentals.timeseries` is NOT used here; the screen response is
  point-in-time only.

### 8.4 Mutation: save preset

`POST /v1/screener/presets` — to be added to S9. Body:
`{ name: string, filters: FilterState }`. Response: `{ preset_id, name, created_at }`.
On success, invalidate `qk.screener.presets()`. **Backend addition
required** — currently presets live in `localStorage` via
`SavedScreensDialog`. v1 keeps that fallback and only migrates to the
server when the endpoint ships (defer to a follow-up task).

### 8.5 Mutation: NL screener translate (PLAN-0091 Wave F-2)

`POST /v1/screener/nl-translate` — body: `{ query: string }`. Response:
`NLScreenerResponse` (fields: `filters`, `natural_language_query`,
`explanation`). Both schemas live in
`services/api-gateway/src/api_gateway/schemas/screener.py` (implemented in
PLAN-0091 Wave E-1).

This is a **mutation**, not a query:
- LLM calls are non-idempotent.
- No query cache entry is written; result lives in local React state within
  `NLScreenerInput` and is discarded when the user types a new query.
- Errors: S9 returns `422` when the LLM produces an unparseable or
  field-invalid response. `NLScreenerInput` renders
  `"Could not translate — try being more specific"` in `text-negative`.
- The `[→]` submit button is disabled while a mutation is in-flight
  to prevent duplicate LLM submissions.

```ts
// In NLScreenerInput.tsx
const [explanation, setExplanation] = useState("");

const nlTranslateMutation = useMutation({
  mutationFn: (query: string) =>
    gateway.post<NLScreenerResponse>("/v1/screener/nl-translate", { query }),
  onSuccess: (data) => {
    // Render the LLM-generated plain-English explanation (R-001 Option A fix)
    setExplanation(data.explanation ?? "");

    // Defence-in-depth: skip chips for fields not in the known allowlist
    const allowedFields =
      queryClient.getQueryData<string[]>(qk.screener.fields()) ?? [];
    const safeFilters = data.filters.filter(
      (f) => allowedFields.includes(f.field),
    );
    onFiltersApplied(safeFilters);
  },
});
```

`NLScreenerResponse` shape (backend `schemas/screener.py`):
```ts
interface NLScreenerResponse {
  filters: Record<string, unknown>;      // field → {lte/gte/eq} condition
  natural_language_query: string;        // echo of original query
  explanation: string;                   // LLM plain-English description (new)
}
```

---

## 9. Tradeoffs & decisions

### 9.1 Filter chrome: chip strip + popover (chosen) vs Finviz dense grid vs TradingView left rail

**Chosen**: chip strip + popover.

**Alternative A — Finviz 6×11 grid always visible**: shows every filter at
all times. Pros: zero clicks to adjust any filter. Cons: consumes 140 px
of vertical chrome **forever**, even for users who only set 2 filters;
cognitively overwhelming for new analysts; doesn't fit our 6-section
schema cleanly (we have ~30 filters, not 70 — a 6×11 grid would have
~50 % empty cells).

**Alternative B — TradingView left rail**: filters live in a 280 px left
rail. Pros: clear separation of filter chrome and result data. Cons:
sacrifices 280 px of horizontal real estate **always**, dropping the table
from 12 to ~9 visible columns at 1440 px; also dragees users to scan
filter labels before they see results — opposite of what an analyst
scanning the universe wants.

**Why chip strip + popover wins**: zero-cost when no filters are set
(chips collapse to just the "+ Add filter" combobox), low-cost when 4-5
filters are set (chips inline), and full filter access is one click away
via the popover. This is the modern web app convention (Stockanalysis,
Linear, Notion) and is the **only option that maintains 20+ result rows
visible with 12 columns at 1440×900**.

### 9.2 Pagination: load-more (chosen) vs page-num bar

**Chosen**: load-more (preserve existing behaviour).

**Alternative — Finviz-style numbered pagination bar (1, 2, 3 … Next →)**:
makes total count and position obvious; classic discovery tool pattern.

**Why load-more wins for us**: the existing TanStack Query accumulator
pattern + AG Grid client-side sort means users can sort across pages they've
loaded so far — paginated UI would force a re-fetch on each page jump,
breaking sort continuity. Load-more is also the modern convention in
Stockanalysis and TradingView screeners. The user has the "X of Y loaded"
counter to know they're not at the end.

### 9.3 Live count: debounced 250 ms (chosen) vs explicit Apply only

**Chosen**: debounced 250 ms in the FilterPanel.

**Alternative — only update count on Apply click**: simpler; fewer
requests; matches existing behaviour.

**Why debounced live count wins**: Bloomberg EQS demonstrably trains
analysts to expect the count to react as they type. The cost (one S9
request per 250 ms of input idle) is bounded: most users don't twiddle
filters faster than that. The request itself is cheap (`limit: 1` returns
COUNT(*) only).

### 9.4 Row hover toolbar (chosen) vs right-click context menu

**Chosen**: hover toolbar (TradingView pattern).

**Alternative — right-click menu**: stays out of the way until invoked.

**Why hover toolbar wins**: visible affordance > hidden gesture; analysts
on a screener page are constantly choosing the next ticker to drill into,
and the most common follow-up actions (add to watchlist, set alert) need
to be one click away. Right-click is a discoverability dead-end.

### 9.5 New columns vs widening existing ones

**Chosen**: replace REVENUE with REV YoY; add DIV Y, FWD P/E, ROE, OP MGN%.

**Alternative — keep REVENUE, add new columns horizontally**: 14+ columns
would overflow 1440 px → horizontal scroll → density loss.

**Why replace REVENUE**: absolute revenue (e.g. "27.1 B") is only useful
in the same row as growth. REV YoY already encodes "revenue trend" which
is what an analyst actually wants when scanning. The full revenue ladder
lives on the Instrument Financials tab (PRD-0089 §6).

---

## 10. Open questions

1. **Preset persistence**: do we ship system presets only in v1 (hardcoded
   in `lib/screener/presets.ts`), or do we add a `POST /v1/screener/presets`
   endpoint to S9 and persist user presets server-side? Recommendation:
   v1 = system presets server-side + user presets in localStorage (existing
   `SavedScreensDialog`); v2 = full server-side persistence with sharing.
2. **Watchlist integration**: the `+ Watchlist` hover button needs a
   default-watchlist endpoint. Is `GET /v1/watchlists?default=true`
   acceptable, or do we always prompt the user to pick a watchlist?
   Recommendation: prompt on first click only, then remember per session.
3. **Compare set**: do we ship the "Compare 3" floating CTA in v1 or
   defer to v2 with a dedicated `/compare` route? Recommendation: hover
   button stub in v1, full compare route in v2.
4. **News velocity / controversy / insider activity client-side filters**:
   keep as visible-but-disabled stubs (current behaviour) or remove from
   the FilterPanel entirely until the composed S9 endpoint lands?
   Recommendation: **keep visible** as "Backend pending" badges — they
   advertise the roadmap to power users and round-trip in saved screens.
5. **Sparkline column for >200 rows**: should we replace the suppressed
   sparkline with a **server-rendered tiny static SVG** (1 round-trip per
   page), or keep the `—` placeholder? Recommendation: defer to v2.
6. **Live count count-only request**: confirm that S9's
   `POST /v1/fundamentals/screen` with `limit: 1` is efficient enough to
   fire every 250 ms of typing without overloading S3 (COUNT(*) OVER() on
   `fundamental_metrics` should be index-only). If not, we add a dedicated
   `POST /v1/fundamentals/screen/count` endpoint that returns `{ total }`
   without scanning rows.
7. **Right-pinned spare space (376 px)**: do we use it for an inline
   "+ N more columns" affordance (one-click add of the next-most-useful
   column), or leave it for the hover toolbar only? Recommendation:
   hover toolbar only — adding columns is rare enough to live in the
   gear menu.

---
