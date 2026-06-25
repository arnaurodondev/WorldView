# Investigation Report: Portfolio, Dashboard & Watchlist UX Issues

**Date**: 2026-04-28
**Investigator**: Claude (investigate skill)
**Severity**: MEDIUM–HIGH (mix of data correctness bugs and UX improvements)
**Status**: Root cause identified for all issues

---

## 1. Issue Summary

Multi-area UI investigation covering 17 distinct issues across the Portfolio page,
Dashboard, Watchlist, and Instruments pages. Issues range from data correctness bugs
(transaction type wrong, dashboard shows instrument IDs) to UX polish requests
(top bar spacing, empty state alignment) and feature additions (portfolio analytics,
period buttons).

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| TransactionDirection enum = INFLOW/OUTFLOW | `services/portfolio/src/portfolio/domain/enums.py:38-39` | Root cause of wrong type display |
| Gateway maps `tx.direction` not `tx.transaction_type` | `apps/worldview-web/lib/gateway.ts:829` | Confirms transaction bug |
| KPI double "+" | `PortfolioKPIStrip.tsx:158` + `lib/utils.ts:81` | `formatPercent` adds sign; template also adds "+" |
| PortfolioSummary no company overview query | `PortfolioSummary.tsx:225–262` | Missing enrichment; shows `h.instrument_id.slice(0,8)` |
| PendingAlertResponse has no `body`/`title` | `services/alert/src/alert/api/schemas.py:13-23` | Why fallback reaches `a.alert_type` = "SIGNAL" |
| searchInstruments fakes entity_id | `gateway.ts:1660–1662` | `entity_id: inst.id` — instrument_id not KG entity_id |
| TopLoser livePrice fallback | `portfolio/page.tsx:822` | `q?.price` = 0 gives pnlPct = -100% |
| IndexTicker uses gap-2 between items | `IndexTicker.tsx:111` | No visual separator between tickers |
| WatchlistTable InlineEmptyState | `WatchlistsTabPanel.tsx:165` | Not vertically centered |

---

## 3. Root Cause Analysis Per Issue

### BUG-1 · Transaction type shows INFLOW/OUTFLOW (CRITICAL)

**File**: `apps/worldview-web/lib/gateway.ts:829`
**Code**: `type: tx.direction.toUpperCase() as "BUY" | "SELL"`
**Root cause**: S1's `TransactionDirection` enum is `INFLOW` / `OUTFLOW` (asset direction).
The gateway incorrectly uses `direction` as if it were `BUY`/`SELL`. The correct field is
`tx.transaction_type` which is `TransactionType.BUY / SELL / DIVIDEND`.
**Impact**: All BUY/SELL/DIV filter buttons show 0 results; badge shows "INFLOW"/"OUTFLOW"
without color styling; DIVIDEND check `isDividend = tx.type === "DIVIDEND"` never triggers.

### BUG-2 · Transaction ticker is empty (HIGH)

**File**: `apps/worldview-web/lib/gateway.ts:825`
**Code**: `ticker: ""`
**Root cause**: S1's `TransactionListItem` does not include ticker. Gateway hardcodes
empty string. No enrichment from instrument cache.
**Impact**: Ticker column shows "—" for all rows.

### BUG-3 · Dashboard Portfolio shows instrument_id prefix (019dbf56) (HIGH)

**File**: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx:243`
**Code**: `{h.name || h.instrument_id.slice(0, 8)}`
**Root cause**: `PortfolioSummary` makes 3 queries (portfolios → holdings → quotes) but
does NOT make a 4th company-overview query like `portfolio/page.tsx` does. Holdings
from S1 have `name: null` and `ticker: null`. Fallback renders `h.instrument_id.slice(0,8)`.
**Impact**: Every holding on the dashboard shows "019dbf56" as name and "—" as ticker.

### BUG-4 · Top Gainer displays double "++" (HIGH)

**File**: `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx:158`
**Code**: `` `${topGainer.ticker} +${formatPercent(topGainer.pnlPct / 100)}` ``
**Root cause**: Template literal adds `+` before `formatPercent(...)`. `formatPercent`
(`lib/utils.ts:81`) also adds `+` sign for positive values: `const sign = value >= 0 ? "+" : ""`.
Result: `"GOOGL " + "+" + "+143.70%" = "GOOGL ++143.70%"`.

### BUG-5 · Top Loser VTV shows -100% (MEDIUM)

**File**: `apps/worldview-web/app/(app)/portfolio/page.tsx:822`
**Code**: `const livePrice = q?.price ?? h.current_price ?? h.average_cost`
**Root cause**: `getBatchQuotes` may return `price: 0` for a closed/delisted instrument
(VTV position was fully sold). `livePrice = 0` → `pnlPct = ((0 - avgCost) / avgCost) * 100 = -100%`.
The `?? fallback` chain only skips `null`/`undefined`, not `0`.

### BUG-6 · Recent Alerts shows only "SIGNAL" (HIGH)

**File**: `apps/worldview-web/components/dashboard/RecentAlerts.tsx:74`
**Code**: `?? a.body ?? a.alert_type ?? ""`
**Root cause**: S10's `PendingAlertResponse` (`schemas.py:13-23`) has fields:
`pending_id`, `alert_id`, `entity_id`, `alert_type`, `source_topic`, `payload`, `created_at`, `severity`.
No `body`, `title`, or `ticker` fields. The frontend `Alert` type includes `body: string` and
`title: string` but these are absent in the actual API response.
Fallback chain: `payload.message` (not set in SIGNAL payloads) → `a.body` (undefined) →
`a.alert_type` ("SIGNAL"). All 20 alerts show "SIGNAL".

### BUG-7 · Watchlist add symbol silently fails (HIGH)

**File**: `apps/worldview-web/lib/gateway.ts:1660–1662`
**Code**: `entity_id: inst.id` (search result uses instrument_id as entity_id)
**Root cause**: `searchInstruments` transforms S3's `InstrumentListResponse` where
`entity_id` is synthesised as `inst.id` (= the instrument_id UUID, NOT the KG entity_id).
S1's `POST /v1/watchlists/{id}/members` requires a real entity_id from S7 Knowledge Graph.
Posting an instrument_id as entity_id causes S1 to fail to find the entity, and the add silently
fails (or creates an orphaned member with no instrument data).

### BUG-8 · Top quotes in TopBar hard to read (MEDIUM)

**File**: `apps/worldview-web/components/shell/IndexTicker.tsx:127`
**Code**: `<div key={ticker.id} className="flex items-center gap-1">`; outer `gap-2`
**Root cause**: The `gap-1` between label and value within a ticker item is similar to
`gap-2` between adjacent tickers. No visual separator exists, causing the 4 ticker items
to blend together at small font size (12px).

### BUG-9 · Watchlist tab has huge empty space and "search above" not centered (LOW)

**File**: `WatchlistsTabPanel.tsx:165` → `InlineEmptyState`
**Root cause**: `InlineEmptyState` renders as a small inline element at the top of the
`WatchlistTable` content area. The container has `flex flex-col` + remaining height,
so the empty state sits at the top of a tall space rather than being centered.

---

## 4. Feature Requests (Design/Enhancement)

### FEAT-1 · Portfolio analytics section below holdings

**Request**: Add portfolio growth chart (1D/1W/1M), sector exposure pie chart,
portfolio stats (total invested, cost basis, beta, etc.)
**API available**: `GET /v1/portfolios/{id}/performance?period=1D|1W|1M` already exists.
Sector allocation: `SectorAllocationPanel.tsx` component already exists but is rendered
inside the Holdings tab, not below it.
**New endpoint needed**: Portfolio historical value timeseries (not yet in S1/S9).

### FEAT-2 · Top bar additional metrics

**Request**: Add daily P&L, unrealized P&L, or other key metrics to top bar.
**Current**: TopBar shows `PORT $343K` (compact portfolio value). User wants more detail.

### FEAT-3 · Dashboard Portfolio: period buttons + price column + remove ID

**Request**: Add 1D/1W/1M buttons, show current price per holding, remove instrument_id.
**Note**: Comment in code says "PLAN-0043 A-3 removes period buttons — no period-based
endpoint yet." But `getPortfolioPerformance(portfolioId, period)` exists in gateway.ts.
The period data should be usable.

### FEAT-4 · Replace AI Signals with more relevant dashboard widget

**Request**: Remove AI Signals, add something more investor-relevant.
**Recommendation**: Replace with **Portfolio Performance Sparkline** (compact 1W/1M line
chart per holding) or **News Sentiment Summary** (aggregated market sentiment from S6).
Alternatively: **Top Holdings Changes** (which positions moved most today).

### FEAT-5 · Instruments landing page distinct from screener

**Request**: `/instruments` should feel different from `/screener`.
**Current**: `/instruments` page already exists (instruments/page.tsx) with a simple
search bar + ScreenerTable. It's functionally different from /screener (no filter bar,
no sector/cap-tier dropdowns). The visual similarity confuses users.
**Recommendation**: Add a page header with total instrument count, featured categories
(Equities, ETFs, Crypto), and top-level stats. Keep the search table below.

### FEAT-6 · Morning Brief format and content

**Request**: Investigate preferred briefing format; fix empty/thin content.
**Preferred format for investors**: Bloomberg-style briefing:
- **1-line executive summary** (biggest market event today)
- **Bullet points** for key index moves (S&P +/-, VIX level, big sectors)
- **Numbered top 3 stories** with 1-line explanation each
- **Risk factors** (2-3 bullet points: macro, sector, portfolio-specific)
- Total: 150-300 words, no generic filler
**Frontend**: MorningBriefCard already renders markdown. S8 prompt engineering needed.

### FEAT-7 · Top Movers / Portfolio News minimum entry fill

**Request**: Components should have enough entries to fill the full component height.
**Top Movers**: Currently `PreMarketMoversWidget` shows 5 gainers + 5 losers.
If market data is thin, fewer entries show. Fix: either increase limit or show a
"prior session" indicator when fewer than 5 per side are available.
**Portfolio News**: Currently `limit: 4` articles. If fewer than 4 available,
empty space appears. Fix: show placeholder "loading more…" or adjust to show
available articles with padded empty rows.

---

## 5. Implementation Plan

The fixes are organized into 3 implementation waves by priority:

---

### Wave A — Critical Data Correctness Fixes (implement first)

**A-1: Fix transaction type mapping**

File: `apps/worldview-web/lib/gateway.ts:819-836`

Change the type mapping to use `tx.transaction_type` (BUY/SELL/DIVIDEND) instead of
`tx.direction` (INFLOW/OUTFLOW):

```typescript
// BEFORE (wrong):
type: tx.direction.toUpperCase() as "BUY" | "SELL",

// AFTER (correct):
type: (
  tx.transaction_type?.toUpperCase() === "DIVIDEND" ? "DIVIDEND" :
  tx.direction?.toUpperCase() === "INFLOW" ? "BUY" : "SELL"
) as "BUY" | "SELL" | "DIVIDEND",
```

Also update the `Transaction` frontend type in `types/api.ts` to add `"DIVIDEND"` to the
union since it was missing from the `BUY | SELL` type:
- File: `apps/worldview-web/types/api.ts` — change `type: "BUY" | "SELL"` to
  `type: "BUY" | "SELL" | "DIVIDEND"` on the `Transaction` interface.

**A-2: Fix transaction ticker enrichment**

The ticker can be resolved from the instrument_id via the company overview endpoint.
The portfolio page already does this async enrichment per holding. Add the same enrichment
to transactions in the `getTransactions` gateway call output, or do it in `TransactionsTable`
via a lookup against the already-loaded `holdingOverviews` map.

Best approach: In `portfolio/page.tsx`, the `holdingOverviews` map is keyed by instrument_id.
Pass it as a prop to `TransactionsTable`, which can do `holdingOverviews[tx.instrument_id]?.ticker`.

Changes:
1. `TransactionsTable.tsx`: accept optional `tickerByInstrumentId: Record<string, string>` prop
2. Render `tickerByInstrumentId[tx.instrument_id] || "—"` in the TICKER column
3. `portfolio/page.tsx`: pass `holdingOverviews` as ticker lookup map to `TransactionsTable`

**A-3: Fix Recent Alerts "SIGNAL" message**

File: `apps/worldview-web/components/dashboard/RecentAlerts.tsx:62-82`

The `PendingAlertResponse` from S10 has `payload: dict` but no human-readable body.
Construct a meaningful message from available fields:

```typescript
message: (() => {
  // Try payload.message first (ideal case when S10 includes it)
  const payloadMsg = (a.payload as Record<string, unknown>)?.message;
  if (typeof payloadMsg === "string" && payloadMsg.trim()) return payloadMsg;

  // Try payload.signal_label + entity (for SIGNAL type alerts)
  const label = (a.payload as Record<string, unknown>)?.signal_label;
  const entityName = (a.payload as Record<string, unknown>)?.entity_name;
  if (label && entityName) return `${entityName}: ${label} signal`;

  // Try payload.title
  const payloadTitle = (a.payload as Record<string, unknown>)?.title;
  if (typeof payloadTitle === "string" && payloadTitle.trim()) return payloadTitle;

  // Try a.body (legacy field that may be set in some alert types)
  if (a.body?.trim()) return a.body;

  // Contextual fallback: severity + type (better than just "SIGNAL")
  return `${a.severity} ${a.alert_type} alert`;
})(),
```

Also fix `alert_id` vs `pending_id` mapping: the frontend uses `a.alert_id` for deduplication,
and S10's response does include `alert_id`. Verify the response shape by also including `pending_id`
in the frontend `Alert` type as optional, and use `a.alert_id ?? a.pending_id` for deduplication.

**A-4: Fix Dashboard Portfolio company overview enrichment**

File: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx`

Add a 4th query to fetch company overviews for holdings (identical to what `portfolio/page.tsx`
does at line 764). Then merge ticker/name from overviews:

```typescript
const { data: holdingOverviews } = useQuery({
  queryKey: ["holdings-overviews-dashboard", instrumentIds],
  queryFn: async () => {
    const gw = createGateway(accessToken);
    const results = await Promise.all(
      instrumentIds.map((id) => gw.getCompanyOverview(id).catch(() => null))
    );
    return Object.fromEntries(
      instrumentIds.map((id, i) => [id, {
        ticker: results[i]?.instrument?.ticker ?? null,
        name:   results[i]?.instrument?.name ?? null,
      }])
    );
  },
  enabled: instrumentIds.length > 0 && !!accessToken,
  staleTime: 300_000,
});
```

Then in the topHoldings map: `const ticker = holdingOverviews?.[h.instrument_id]?.ticker ?? h.ticker;`

---

### Wave B — UX Correctness Fixes

**B-1: Fix Top Gainer double "++" sign**

File: `apps/worldview-web/components/portfolio/PortfolioKPIStrip.tsx:158`

Remove the manual `+` prefix since `formatPercent` already adds it:

```typescript
// BEFORE:
value={topGainer ? `${topGainer.ticker} +${formatPercent(topGainer.pnlPct / 100)}` : "—"}

// AFTER:
value={topGainer ? `${topGainer.ticker} ${formatPercent(topGainer.pnlPct / 100)}` : "—"}
```

**B-2: Fix Top Loser -100% for zero-price quotes**

File: `apps/worldview-web/app/(app)/portfolio/page.tsx:822`

Guard against `price: 0` from batch quotes (which indicates unavailable data, not a real price):

```typescript
// BEFORE:
const livePrice = q?.price ?? h.current_price ?? h.average_cost;

// AFTER:
const livePrice = (q?.price && q.price > 0) ? q.price : (h.current_price ?? h.average_cost);
```

Apply this fix in both `portfolio/page.tsx` (line ~822) and `PortfolioSummary.tsx` (line ~128).

**B-3: Fix watchlist symbol add (entity_id resolution)**

File: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx` + `gateway.ts`

The core problem: `searchInstruments` returns instrument_id as entity_id. The watchlist
POST requires the real entity_id from S7 KG.

**Solution**: Use the `/v1/fundamentals/screen` (screener) endpoint for watchlist search
instead of `/v1/search/instruments`. The screener returns `entity_id` (real KG entity ID)
plus ticker, name, exchange for each result.

In `AddSymbolBar` (`WatchlistsTabPanel.tsx:247`), replace `searchInstruments` with a new
gateway method `searchFundamentals(q, limit)` that calls the screener endpoint with a
`name_ticker contains` filter:

```typescript
// New gateway method:
async searchFundamentals(q: string, limit = 8): Promise<SearchResponse> {
  const body: ScreenerRequest = {
    filters: [{ field: "name_ticker", operator: "contains", value: q }],
    limit, offset: 0,
  };
  const raw = await apiFetch<{ results: ScreenerResult[]; total: number }>(...);
  return { results: raw.results.map(r => ({
    instrument_id: r.instrument_id,
    entity_id: r.entity_id,   // real entity_id from KG
    ticker: r.ticker,
    name: r.name,
    exchange: r.exchange ?? "—",
    type: "equity",
  })), query: q };
}
```

In `AddSymbolBar`, change the query to use `searchFundamentals` (or simply call `runScreener`
directly). The result `entity_id` will be the real KG entity_id, making the watchlist POST succeed.

**B-4: Fix TopBar index ticker readability**

File: `apps/worldview-web/components/shell/IndexTicker.tsx:111`

Add a `|` divider between ticker items (Bloomberg style):

```tsx
// Add between items:
{INDEX_TICKERS.map((ticker, idx) => (
  <>
    {idx > 0 && <span className="text-border select-none">|</span>}
    <div key={ticker.id} className="flex items-center gap-1">
      ...
    </div>
  </>
))}
```

Or use `divide-x divide-border` on the container with `px-2` on each item.

**B-5: Fix watchlist empty state centering**

File: `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:164`

Wrap the empty state in a centered container:

```tsx
if (members.length === 0) {
  return (
    <div className="flex flex-1 items-center justify-center py-8">
      <InlineEmptyState message="Search above to add your first symbol." />
    </div>
  );
}
```

**B-6: Handle zero-qty / empty transactions display**

File: `apps/worldview-web/components/portfolio/TransactionsTable.tsx`

Some brokerage-imported transactions have qty=0 and price=0 (e.g., dividend events with
amount in the fee field, or corporate actions). Currently these show "—" for total which is
confusing next to non-zero transactions.

Add a visual indicator for these rows:
- If `tx.quantity === 0 && tx.price === 0` and `tx.type !== "DIVIDEND"`: show a subtle
  `text-muted-foreground/50` row with "pending" or "n/a" in the total column
- For DIVIDEND rows: the fee field repurposing is correct but needs the `isDividend` guard
  to work — once A-1 fixes the type mapping, this will auto-fix for real dividends

---

### Wave C — Feature Additions

**C-1: Portfolio analytics section below holdings**

File: `apps/worldview-web/app/(app)/portfolio/page.tsx` + new component
`components/portfolio/PortfolioAnalyticsSection.tsx`

Add below the `SemanticHoldingsTable` in the Holdings tab:

1. **Performance chart** using the existing `getPortfolioPerformance(portfolioId, period)`
   endpoint. Show a simple sparkline or mini line-chart (recharts `LineChart`) with
   1D/1W/1M toggle. Metrics: return_pct, return_abs.

2. **Sector allocation panel** — `SectorAllocationPanel.tsx` already exists and is
   rendered in the Holdings tab but may not be visible. Confirm it renders below the table.
   If hidden, move it to always-visible below the holdings table.

3. **Portfolio statistics strip** — a horizontal row of key metrics:
   - Total Invested (sum of avg_cost × qty)
   - Cost Basis
   - # Winners / Losers
   - Best day / Worst day (from performance endpoint)

**C-2: Top bar key metrics**

File: `apps/worldview-web/components/shell/TopBar.tsx` + layout

The TopBar currently passes `portfolioValue` from the layout. Extend to also pass
`dailyPnl` and `unrealisedPnl`:

```tsx
// In TopBar props:
dailyPnl?: number | null;
unrealisedPnl?: number | null;

// In render (right section):
{dailyPnl != null && (
  <span className={`font-mono text-[10px] tabular-nums ${dailyPnl >= 0 ? "text-positive" : "text-negative"}`}>
    D {formatPrice(dailyPnl, true)}
  </span>
)}
```

The layout (`app/(app)/layout.tsx`) already fetches portfolios for the portfolio value badge.
Extend that fetch to also compute daily P&L from batch quotes.

**C-3: Dashboard Portfolio period buttons + price column**

File: `apps/worldview-web/components/dashboard/PortfolioSummary.tsx`

1. Add a `period` state (`1D | 1W | 1M`) and period buttons in the header (same pattern as
   `PreMarketMoversWidget.tsx` which has gainers/losers tabs).
2. Add a `getPortfolioPerformance` query using the selected period.
3. Show the period return (return_pct, return_abs) instead of mark-to-market unrealized.
4. Add `price` column in the topHoldings list (show `livePrice`).
5. Remove the instrument_id placeholder (fixed in A-4).

**C-4: Replace AI Signals with Portfolio Performance Widget**

File: `apps/worldview-web/components/dashboard/` (new component)
`apps/worldview-web/app/(app)/dashboard/page.tsx:114`

Replace `AiSignalsWidget` with a new `PortfolioGainersLosers` component that shows:
- Top 3 portfolio gainers today (ticker, P&L%, change$)
- Top 3 portfolio losers today (ticker, P&L%, change$)
- Same period buttons (1D/1W/1M) as other widgets
- Data from holdings + batch quotes (already loaded in `PortfolioSummary` — share query cache)

This is more actionable for investors than abstract ML confidence bars.

**C-5: Instruments page distinct from screener**

File: `apps/worldview-web/app/(app)/instruments/page.tsx`

Add a header section above the search bar:
- Total instrument count badge
- 3-4 category quick-filter chips: "Equities", "ETFs", "Crypto", "All"
- When a chip is clicked, apply a category filter to the screener query
- The page title should clearly say "INSTRUMENT BROWSER" (not just "Instruments")

**C-6: Morning Brief format improvement**

This is primarily an S8 prompt engineering task (not frontend):
- Update the morning brief generation prompt in `services/rag-chat/` to produce:
  - 1-line executive summary
  - 5 bullet points for key market moves
  - 3 numbered top stories with 1-line each
  - 2-3 risk factors
- The `MorningBriefCard.tsx` already renders markdown and extracts headlines correctly
- Ensure S8's `generate_morning_brief` function includes portfolio-specific context

**C-7: Top Movers and Portfolio News fill guarantee**

`PreMarketMoversWidget.tsx`: Increase the limit from 5 to 8 per side so there's always
content to fill the widget height. Add `min_rows=5` padding with skeleton rows if data
is thin.

`PortfolioNewsWidget.tsx`: Increase `limit: 4` to `limit: 8` and show up to 8 articles.
The Row 4 cell height fits 8 rows at 22px each (176px) plus 24px header = 200px total
(matches `minmax(200px, 1fr)`).

---

## 6. Files to Change (complete list)

| File | Changes |
|------|---------|
| `lib/gateway.ts:829` | Wave A-1: use `tx.transaction_type` not `tx.direction` |
| `types/api.ts:558` | Wave A-1: add `DIVIDEND` to `Transaction.type` union |
| `components/portfolio/TransactionsTable.tsx` | Wave A-2: accept `tickerByInstrumentId` prop |
| `app/(app)/portfolio/page.tsx:870+` | Wave A-2: pass ticker lookup map to TransactionsTable |
| `components/dashboard/RecentAlerts.tsx:74` | Wave A-3: construct meaningful alert message |
| `components/dashboard/PortfolioSummary.tsx:57` | Wave A-4: add company overview query |
| `components/portfolio/PortfolioKPIStrip.tsx:158` | Wave B-1: remove manual "+" before formatPercent |
| `app/(app)/portfolio/page.tsx:822` | Wave B-2: guard against `price: 0` from batch quotes |
| `components/dashboard/PortfolioSummary.tsx:128` | Wave B-2: same zero-price guard |
| `lib/gateway.ts` (new method) | Wave B-3: `searchFundamentals` using screener endpoint |
| `components/portfolio/WatchlistsTabPanel.tsx:249` | Wave B-3: use `searchFundamentals` in AddSymbolBar |
| `components/shell/IndexTicker.tsx:111` | Wave B-4: add `|` divider between ticker items |
| `components/portfolio/WatchlistsTabPanel.tsx:165` | Wave B-5: center empty state |
| `components/portfolio/TransactionsTable.tsx:172` | Wave B-6: handle zero-qty rows gracefully |
| `app/(app)/portfolio/page.tsx` | Wave C-1: add analytics section below holdings |
| `components/shell/TopBar.tsx` | Wave C-2: daily P&L + unrealized metric in top bar |
| `components/dashboard/PortfolioSummary.tsx` | Wave C-3: period buttons + price column |
| `app/(app)/dashboard/page.tsx:114` | Wave C-4: replace AiSignalsWidget |
| `app/(app)/instruments/page.tsx` | Wave C-5: category chips + better header |
| `services/rag-chat/` | Wave C-6: S8 morning brief prompt update |
| `components/dashboard/PreMarketMoversWidget.tsx` | Wave C-7: increase limit to 8 |
| `components/dashboard/PortfolioNewsWidget.tsx` | Wave C-7: increase limit to 8 |

---

## 7. Compounding Notes

**New bug pattern candidates**:
- `tx.direction` vs `tx.transaction_type` confusion (gateway field mismatch) → add to BUG_PATTERNS.md
- `formatPercent` already adds sign; callers must NOT add a second sign → add to code comment

**Missing observability**:
- `RecentAlerts` should log a warning when `payload.message` is absent, so S10 knows to add it
- `WatchlistsTabPanel` addMutation should surface the error message to the user (currently silent on fail)

**Missing tests**:
- `TransactionsTable` test for INFLOW/OUTFLOW → correct BUY/SELL display
- `PortfolioSummary` test for enriched ticker/name display
- `RecentAlerts` test for message construction from various payload shapes
