# Investigation Report: Instrument Page UI Issues

**Date**: 2026-04-28
**Investigator**: Claude (investigate skill)
**Severity**: MEDIUM (UX, data readability, missing enrichment)
**Status**: Root causes identified — detailed fix plan included

---

## 1. Issue Summary

Eight UI issues identified on the Instrument Detail page (`/instruments/[entityId]`):

1. AI Brief renders raw markdown and lacks a "read more" UX
2. Grey label text is too dim to read on dark background
3. Key metrics sidebar shows "—" for EPS, BETA, AVG VOLUME (hardcoded) and FWD P/E, DIV YIELD, ROE, D/E (null from API)
4. Trend sparklines and revenue chart show 1985–1989 dates instead of recent quarters
5. Chart: large black empty area below session stats strip; VOL/MA buttons need redesign; no advanced indicators
6. Knowledge graph (compact SVG): no hover tooltips; hard to visualize
7. Fundamentals tab: all values missing, no Y-axis on revenue chart, competitors box mismatched, need more news
8. News tab: excessive vertical space per article; no enrichment data displayed

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| `InstrumentAISubheader.tsx` — preview renders raw markdown string slice | `components/instrument/InstrumentAISubheader.tsx:176` | Issue 1 |
| `--muted-foreground: 240 4% 46%` → hex `#71717A` on `#09090B` background = 3.7:1 contrast | `app/globals.css` | Issue 2 |
| EPS, BETA, AVG VOLUME hardcoded as `"—"` with "Wave D-3 placeholder" comments | `InstrumentKeyMetrics.tsx:164,182,219` | Issue 3 |
| `query_timeseries()` uses `.order_by(m.as_of_date.asc()).limit(limit)` | `fundamental_metrics_query.py:56` | Issue 4 |
| Apple EODHD data starts from ~1985 (quarterly history); limit=12 returns oldest 12 | Backend query + EODHD data | Issue 4 |
| `EntityGraphPanel` SVG container has fixed `HEIGHT=280` but surrounding div may be taller | `EntityGraphPanel.tsx:154-155` | Issue 5 |
| `ChartToolbar` renders plain text `ToolbarButton` components — no indicator sidebar | `ChartToolbar.tsx:52-76` | Issue 5 |
| `EntityGraphPanel` only sets `hoveredNodeId` — no tooltip div rendered | `EntityGraphPanel.tsx:124` | Issue 6 |
| `FundamentalsTab` fetches via `getFundamentals(instrumentId)` — separate endpoint from overview | `FundamentalsTab.tsx:244` | Issue 7 |
| `RevenueTrendSparklines` requests `limit:12 QUARTERLY` → same ASC ordering bug | `RevenueTrendSparklines.tsx:173` | Issue 7 |
| `RevenueTrendSparklines` comment: "WHY NO Y-AXIS LABELS: At 120px chart height, Y-axis labels crowd the bars" | `RevenueTrendSparklines.tsx:25-27` | Issue 7 |
| `ArticleCard` uses `p-3` (12px) + wrapper `py-2` (8px) → 20px overhead per article | `page.tsx:303`, `ArticleCard.tsx:120` | Issue 8 |
| `RankedArticle` has `display_relevance_score`, `routing_tier`, `impact_windows` but minimal display | `ArticleCard.tsx:102-109` | Issue 8 |

---

## 3. Root Cause Analysis

### Root Cause 1 — AI Brief: raw markdown + no "read more"

**File**: `components/instrument/InstrumentAISubheader.tsx`

The collapsed row at line 176 slices `brief.narrative.slice(0, 120)` — a raw markdown string. The brief content starts with `### 1. Entity Overview - **Ticker**: AAPL...` which shows markdown syntax verbatim. The expanded state (line 188) renders the full narrative inside a plain `<p>` tag — still no markdown parsing. There is no concept of "first 2 lines" — the 120-char preview is all on a single h-9 row. The toggle covers the entire band, there is no explicit "Read more" button. Text color at line 175 is `text-muted-foreground` (#71717A, contrast 3.7:1) — unreadable.

### Root Cause 2 — Grey text readability

**File**: `apps/worldview-web/app/globals.css` (dark mode)

`--muted-foreground: 240 4% 46%` resolves to zinc-500 `#71717A`. Against the app background `--background: 240 10% 4%` = `#09090B`, the contrast ratio is approximately 3.7:1. WCAG AA requires 4.5:1 for text ≤13px. Almost all label text in this app is 9–11px. This affects: metric labels, axis dates, source badges, timestamps, section headers, legend items, sparkline axis labels.

### Root Cause 3 — Key metrics: hardcoded placeholders + null API fields

**Files**: `InstrumentKeyMetrics.tsx:164,182,219`

Three metrics explicitly hardcoded as `"—"` with comments pointing to "Wave D-3":
- **EPS (TTM)** (line 164): hardcoded `"—"`, value_class `text-muted-foreground`
- **BETA** (line 182): hardcoded `"—"`, value_class `text-muted-foreground`
- **AVG VOLUME** (line 219): hardcoded `"—"`, value_class `text-muted-foreground`

The beta, forward_pe, dividend_yield, roe, and debt_to_equity fields exist in `types/api.ts` (the `Fundamentals` interface), but these return null from `getFundamentals()` for AAPL in the current dataset. The CompanyOverview endpoint returns `market_cap` and `pe_ratio` from a different, fresher snapshot (overview endpoint), while the detailed fundamentals endpoint may not have these fields populated (S3 fundamentals pipeline populates fields incrementally and some fields may not be in the DB yet for the test dataset).

### Root Cause 4 — Sparkline/chart dates 1985–1989

**File**: `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py:56`

```python
.order_by(m.as_of_date.asc())
.limit(limit)
```

The query orders ascending (oldest first) and returns the first `limit` rows. For AAPL which has EODHD quarterly data back to 1985, `limit=12` returns Q1'85–Q4'87 data, and `limit=20` returns Q1'85–Q4'89 data. The sparklines and revenue chart therefore show historical data from 40 years ago.

### Root Cause 5 — Chart: black space + VOL/MA button design

**Black space**: `EntityGraphPanel.tsx` in the Overview layout's lower-right zone uses a fixed `HEIGHT=280` for the SVG viewBox but the surrounding container div can be taller. The `bg-card/30` background appears as a large dark rectangle. Additionally, the `computeRadialLayout` places nodes at specific fixed coordinates (innerRadius=90, outerRadius=140 around a cx=160, cy=140 center). For sparse graphs (3-5 nodes), most of the 320×280 SVG is empty dark space.

**VOL/MA buttons**: `ChartToolbar.tsx` uses plain 10px text labels (`VOL`, `MA50`, `MA200`) inside small pill buttons. This is minimal but lacks visual differentiation between indicator types, doesn't show the color of each indicator, and doesn't scale to more indicators (RSI, MACD, Bollinger Bands would overload the toolbar row).

### Root Cause 6 — EntityGraphPanel: no hover tooltips

**File**: `EntityGraphPanel.tsx:124`

`hoveredNodeId` state exists and is set on mouse enter, but the component **never renders a tooltip div**. The only hover effect is changing the node circle radius (8→10px) and stroke width. There is no edge hover state at all. The full sigma.js `EntityGraph.tsx` (Intelligence tab) has complete `NodeTooltipPanel` and `EdgeTooltipPanel` components, but these are not replicated in the compact SVG version.

### Root Cause 7 — Fundamentals: missing values, no Y-axis, missing news

**Missing values**: `FundamentalsTab` calls `getFundamentals(instrumentId)` which returns an object with mostly null fields. The CompanyOverview endpoint (which populates the sidebar in Overview tab) uses a different, fresher endpoint (`/v1/companies/{id}/overview`) that joins quotes and recent fundamentals. The fundamentals-only endpoint (`/v1/fundamentals/{id}`) returns a flat object from the `fundamentals_metrics` table, but many fields may not be populated for all instruments in the current dataset.

**Revenue trend dates**: Same root cause as Issue 4 — `RevenueTrendSparklines.tsx:173` requests `period_type: "QUARTERLY", limit: 12` from the same ASC-ordered endpoint.

**No Y-axis**: Intentionally omitted per comment: "WHY NO Y-AXIS LABELS: At 120px chart height, Y-axis labels crowd the bars." This was a design choice but produces a chart that cannot be read without tooltip hover.

**Competitors not a box**: `PeerComparisonPanel` in the sidebar renders as a flat list (`No peer data available`) because the graph query returns no direct competitors. It renders visually the same as other sidebar entries (MARKET CAP, CAP TIER) with just a `—`.

**Not enough news**: `FundamentalsTopNews` fetches a fixed limit (likely 3-4 articles). There's space in the 280px sidebar for 6-8 compact rows.

### Root Cause 8 — News tab: vertical space + missing enrichment

**File**: `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx:303`, `ArticleCard.tsx:120`

Each article renders as a full card with:
- External wrapper: `py-2` (8px top + 8px bottom = 16px)
- ArticleCard: `p-3` (12px all sides)
- 1px border + separator
- Total overhead: ~32px of padding per article before any content

The card layout (border, rounded, bg-card) is designed for dashboard widgets — not dense terminal lists. For the News tab, a compact row design (like screener rows at 22-44px) would fit 2-3x more articles.

The `display_relevance_score` badge is shown as a small number badge at top-right (good), but the `routing_tier` is only shown for HIGH tier. `impact_windows` data (day_t0 price impact) exists in `RankedArticle` but is never displayed. Source (`source_name`) is often null for RankedArticle, rendering as `"—"` badge.

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | Preview text is raw markdown slice (not stripped/rendered) | CONFIRMED | Code read `InstrumentAISubheader.tsx:146,175` |
| H-2 | muted-foreground contrast <4.5:1 at 46% lightness | CONFIRMED | Contrast calculation on hex values |
| H-3 | EPS/BETA/AVG VOLUME hardcoded (not missing from API) | CONFIRMED | Code read lines 164,182,219 |
| H-4 | Timeseries endpoint sorts ASC, limit gets oldest records | CONFIRMED | `fundamental_metrics_query.py:56` `.order_by(m.as_of_date.asc())` |
| H-5 | EntityGraphPanel has no tooltip render despite hover state | CONFIRMED | Code read — no tooltip JSX found |
| H-6 | RevenueTrendSparklines same ASC sort bug | CONFIRMED | `RevenueTrendSparklines.tsx:173-176` |
| H-7 | ArticleCard p-3 + py-2 wrapper = excessive vertical space | CONFIRMED | Code read page.tsx:303 + ArticleCard.tsx:120 |
| H-8 | Black space = sparse EntityGraphPanel SVG with dark background | CONFIRMED | EntityGraphPanel fixed HEIGHT=280 + sparse radial layout |

---

## 5. Impact Analysis

- **Immediate**: AI brief is unreadable, trend charts show useless historical dates, key metrics all show "—", news tab is information-sparse
- **Data integrity**: None — display-only issues
- **Blast radius**: Instrument Detail page only (all tabs affected)

---

## 6. Detailed Fix Plan

---

### Fix 1: AI Brief — Markdown rendering + "read more" UX

**Files to change**: `components/instrument/InstrumentAISubheader.tsx`

**What to install**: `react-markdown` (check if already in package.json; if not, add via pnpm)

**Changes**:

1. **Strip markdown from preview text**: Create a `stripMarkdown(text: string): string` helper that removes `###`, `##`, `#`, `**`, `*`, `_`, `` ` `` syntax from the preview. Use a simple regex:
   ```ts
   function stripMarkdown(text: string): string {
     return text
       .replace(/#{1,6}\s+/g, '')   // headings
       .replace(/\*\*(.+?)\*\*/g, '$1')  // bold
       .replace(/\*(.+?)\*/g, '$1')      // italic
       .replace(/_(.+?)_/g, '$1')        // underscore italic
       .replace(/`(.+?)`/g, '$1')        // inline code
       .replace(/\n+/g, ' ')             // newlines to spaces
       .trim();
   }
   ```

2. **Change the collapsed row to a 2-line preview**: Instead of a single h-9 row, change to:
   - Row 1 (h-9): `AI BRIEF` label + chevron toggle button (NOT the full row as a button)
   - Row 2 (visible always, max 2 lines): stripped preview text (200 chars), smaller font (10px), muted style
   - "Read more →" button: inline at end of preview if `hasMore`

   New layout for collapsed state:
   ```jsx
   <div className="border-b border-border border-l-2 border-l-primary bg-primary/10 shrink-0">
     {/* Header row */}
     <div className="flex items-center h-9 px-2 gap-1.5">
       <button onClick={toggle} className="flex items-center gap-1.5">
         {expanded ? <ChevronDown .../> : <ChevronRight .../>}
         <span className="text-[10px] uppercase tracking-[0.08em] text-primary">AI BRIEF</span>
       </button>
       {/* Preview — 2-line clamp of stripped markdown */}
       {!expanded && (
         <span className="line-clamp-2 text-[10px] text-foreground/70 ml-1 flex-1 leading-tight">
           {strippedPreview}
           {hasMore && (
             <button onClick={toggle} className="ml-1 text-primary text-[10px] shrink-0">
               Read more →
             </button>
           )}
         </span>
       )}
     </div>

     {/* Expanded content with ReactMarkdown */}
     <div className="grid transition-[grid-template-rows] duration-150 ease-out"
          style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}>
       <div className="overflow-hidden">
         <div className="px-3 pb-3 text-[11px] leading-relaxed prose prose-invert prose-sm max-w-none">
           <ReactMarkdown>{brief.narrative}</ReactMarkdown>
         </div>
       </div>
     </div>
   </div>
   ```

3. **Fix prose styling**: Add minimal prose styles for the rendered markdown:
   - `h3` → `text-[11px] uppercase tracking-wide text-primary font-semibold mt-2 mb-0.5`
   - `strong` → `text-foreground font-medium`
   - `p` → `text-foreground/80 text-[11px]`
   - `ul` → compact list with `-` style bullets, tight spacing

4. **Import**: `import ReactMarkdown from 'react-markdown'` (lazy if needed)

**PREVIEW_CHARS** → change to 250 to get 2 lines of content.

---

### Fix 2: Grey text readability

**File**: `apps/worldview-web/app/globals.css`

**Change**: In the `.dark` block, update `--muted-foreground` from zinc-500 to zinc-400:

```css
/* Before */
--muted-foreground: 240 4% 46%;

/* After — zinc-400 = 60% lightness, contrast ~5.3:1 on #09090B */
--muted-foreground: 240 5% 64.9%;
```

This single change propagates to all 100+ usages of `text-muted-foreground` across the app. Contrast ratio improves from 3.7:1 to ~5.3:1, passing WCAG AA for small text.

**Validate**: Run contrast check: `#A1A1AA` on `#09090B` = 5.3:1 ✓

---

### Fix 3: Key metrics — wire real data for EPS, BETA, AVG VOLUME

**Files**:
- `components/instrument/InstrumentKeyMetrics.tsx`
- `components/instrument/OverviewLayout.tsx`
- `app/(app)/instruments/[entityId]/page.tsx`

**Changes**:

#### 3a. EPS (TTM)
The `Fundamentals` type at `types/api.ts:112` may not have `eps_ttm`. Check if the field exists. If it does, use it. If not:
- The `TechnicalSnapshot` endpoint returns EPS from `getTechnicals()`
- Alternatively, derive from earnings history first point
- Quickest fix: check `fundamentals?.eps_ttm` and format with `formatPrice`
- If field doesn't exist in type, add `eps_ttm?: number | null` to `Fundamentals` interface

In `InstrumentKeyMetrics.tsx`, replace:
```tsx
{/* Row 4 — was hardcoded */}
<MetricRow
  label="EPS (TTM)"
  value={fundamentals?.eps_ttm != null ? `$${formatPrice(fundamentals.eps_ttm)}` : "—"}
  valueClass={fundamentals?.eps_ttm != null ? "text-foreground" : "text-muted-foreground"}
/>
```

#### 3b. BETA
BETA is available from the technicals endpoint (`getTechnicals()`). The `Fundamentals` type at `types/api.ts` does not include beta. The `TechnicalSnapshot` component fetches and renders beta already. To add beta to the Overview sidebar:

Option A (no new fetch): Pass beta from `CompanyOverview` if that endpoint includes it.
Option B (new fetch in OverviewLayout): Fetch `getTechnicals()` in `OverviewLayout` and pass `beta` as prop to `OverviewSidebarMetrics`.

Recommended approach — add `beta?: number | null` prop to `OverviewSidebarMetricsProps` and pass it from `OverviewLayout` which fetches it via a separate `useQuery`:

```tsx
// In OverviewLayout.tsx
const { data: techData } = useQuery({
  queryKey: ["technicals", instrumentId],
  queryFn: () => createGateway(accessToken).getTechnicals(instrumentId),
  enabled: !!accessToken && !!instrumentId,
  staleTime: 5 * 60_000,
});
const beta = (techData?.records?.[0]?.data as Record<string, number | null> | undefined)?.beta ?? null;
```

Then in `InstrumentKeyMetrics.tsx`, replace the hardcoded BETA row with:
```tsx
<MetricRow
  label="BETA"
  value={beta != null ? beta.toFixed(2) : "—"}
  valueClass={beta != null ? "text-foreground" : "text-muted-foreground"}
/>
```

#### 3c. AVG VOLUME
Available from `getShareStatistics()`. The `OwnershipSnapshotPanel` already fetches this. Add avg_volume to the sidebar similarly to BETA:

Alternatively, the CompanyOverview endpoint may already include avg_volume in fundamentals. Check the `Fundamentals` type for `avg_volume` or `average_volume` field. If present, use `formatMarketCap(fundamentals?.avg_volume)` (the format function handles large numbers).

If not present in the type, add `avg_volume?: number | null` and wire from the overview response.

#### 3d. Forward P/E, DIV YIELD, ROE, DEBT/EQUITY (null from API)
These fields ARE in the `Fundamentals` type and the `OverviewSidebarMetrics` already reads them correctly. The issue is the underlying data. Two approaches:
1. Check the DB: `SELECT metric, value_numeric FROM fundamental_metrics WHERE instrument_id = 'AAPL_ID' AND metric IN ('forward_pe', 'dividend_yield', 'roe', 'debt_to_equity') ORDER BY as_of_date DESC LIMIT 1` — if empty, it's a data ingestion issue (S3 not populating these metrics).
2. If data exists but the API doesn't return it, check `GET /v1/fundamentals/{id}` response in dev tools.
3. If it's an ingestion gap, this is a backend data issue outside the UI scope. The UI correctly shows "—" for null — the fix is in the S3 fundamentals ingestion pipeline to ensure all EODHD fields are mapped.

**For the plan**: Document this as a known data gap. The frontend code is correct. A backend task must verify S3 populates `forward_pe`, `dividend_yield`, `roe`, `debt_to_equity` from EODHD.

---

### Fix 4: Sparkline + revenue trend dates (1985–1989 → recent quarters)

**Backend fix**: `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py`

Change `query_timeseries` to support `order` parameter:

```python
async def query_timeseries(
    session: AsyncSession,
    instrument_id: str,
    metric: str,
    start_date: date | None = None,
    end_date: date | None = None,
    period_type: str | None = None,
    limit: int = 1000,
    order: str = "asc",   # NEW parameter: "asc" | "desc"
) -> list[MetricDataPoint]:
    """Return timeseries ordered by as_of_date.

    Use order='desc' with limit to get the most recent N points,
    then reverse the result for chronological display.
    """
    ...
    stmt = (
        select(m.as_of_date, m.value_numeric, m.value_text, m.period_type)
        .where(and_(*conditions))
        .order_by(m.as_of_date.desc() if order == "desc" else m.as_of_date.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    points = [MetricDataPoint(...) for row in rows]
    # If desc, reverse so caller gets chronological order
    if order == "desc":
        points = list(reversed(points))
    return points
```

**Backend port update**: `services/market-data/src/market_data/application/ports/repositories.py:453` — add `order: str = "asc"` to the abstract method signature.

**Backend use case update**: `query_fundamental_metrics.py:31` — pass `order` through.

**Backend router update**: `fundamental_metrics.py:46` — add `order: str = Query("asc", regex="^(asc|desc)$")` parameter.

**Frontend gateway update**: `apps/worldview-web/lib/gateway.ts` — add `order?: "asc" | "desc"` to `getFundamentalsTimeseries` params:

```ts
getFundamentalsTimeseries(
  instrumentId: string,
  metric: string,
  params?: {
    start_date?: string;
    end_date?: string;
    period_type?: string;
    limit?: number;
    order?: "asc" | "desc";  // NEW
  },
): Promise<FundamentalsTimeseriesResponse>
```

**Frontend sparkline update** — `FundamentalSparkline.tsx:103`:
```ts
queryFn: () =>
  createGateway().getFundamentalsTimeseries(instrumentId, metric, {
    limit: 20,
    order: "desc",  // get most recent 20 records
  }),
```
The backend will reverse the desc list → chronological order for display.

**Frontend revenue trend update** — `RevenueTrendSparklines.tsx:174`:
```ts
queryFn: () =>
  gateway.getFundamentalsTimeseries(instrumentId, "revenue", {
    period_type: "QUARTERLY",
    limit: 12,
    order: "desc",  // get most recent 12 quarters
  }),
```
Same for the EPS query at line 187.

**Tests**: Add test in `tests/unit/test_fundamental_metrics_query.py` verifying that:
- `order="desc"` with limit=12 returns the 12 most recent rows
- The returned list is in ascending date order (reversed after desc fetch)

---

### Fix 5: Chart — fill black space + indicator sidebar redesign

#### 5a. EntityGraphPanel black space
**File**: `EntityGraphPanel.tsx`

The SVG has a fixed HEIGHT=280 but the surrounding container div has `bg-card/30` which creates a dark rectangle that shows the empty graph space.

Two options:
1. **Add a "LIVE" header** to the graph panel to fill vertical space and add context
2. **Reduce the panel height** to match actual content: make HEIGHT dynamic based on node count

Recommended approach — the SVG should show a proper label/header and make node labels more readable:

```tsx
{/* Header for the graph panel */}
<div className="flex items-center justify-between border-b border-border/30 px-3 h-6">
  <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
    RELATIONSHIPS
  </span>
  <span className="text-[9px] text-muted-foreground/60 font-mono">
    {graph.nodes.length - 1} connections
  </span>
</div>
```

Also increase `innerRadius` from 90 to 100 and `outerRadius` from 140 to 160 to spread nodes across more of the SVG area. Use `HEIGHT = 240` to reduce the dark dead zone. Additionally, for nodes where `label.length > 14`, use a tighter truncation (12 chars) but increase font size from 7 to 8px for readability.

#### 5b. VOL/MA/Indicator sidebar redesign
**Files**: `ChartToolbar.tsx`, `OHLCVChart.tsx`

**Current**: Flat toolbar row with VOL/MA50/MA200 text buttons
**New**: A collapsible indicator sidebar panel that slides in from the right

Design:
1. Replace the VOL/MA/MA200 buttons with a single `⋮ Indicators` button that opens a panel
2. The panel appears as a slide-in drawer (or absolute-positioned panel) over the right edge of the chart
3. Inside the panel: checkboxes/toggles for each overlay with color swatches

New `ChartToolbar` with indicator panel:
```tsx
// ChartToolbar now has an "Indicators" dropdown
<div className="ml-auto flex items-center gap-0.5">
  <button
    onClick={onToggleIndicators}
    className="flex items-center gap-1 rounded-[2px] border border-border/50 px-2 py-0.5 text-[10px] text-muted-foreground hover:border-border hover:text-foreground"
  >
    <span className="font-mono">⊕</span>
    <span>Indicators</span>
  </button>
  <button onClick={onFullscreen} ...>
    {isFullscreen ? "⊡" : "⛶"}
  </button>
</div>
```

Indicator panel (absolute positioned, right-0 top-7):
```tsx
{showIndicatorPanel && (
  <div className="absolute right-0 top-7 z-20 w-44 rounded-[2px] border border-border bg-card shadow-lg">
    <div className="border-b border-border px-2 py-1">
      <span className="text-[10px] uppercase text-muted-foreground">Overlays</span>
    </div>
    <div className="p-2 space-y-1">
      {/* Volume */}
      <label className="flex items-center gap-2 cursor-pointer group">
        <input type="checkbox" checked={showVolume} onChange={onToggleVolume} className="h-3 w-3" />
        <div className="h-2 w-3 rounded-sm" style={{ background: 'rgba(38,166,154,0.4)' }} />
        <span className="text-[11px] text-foreground group-hover:text-primary">Volume</span>
      </label>
      {/* MA50 */}
      <label className="flex items-center gap-2 cursor-pointer group">
        <input type="checkbox" checked={showMA50} onChange={onToggleMA50} className="h-3 w-3" />
        <div className="h-0.5 w-3 rounded-full bg-primary" />
        <span className="text-[11px] text-foreground group-hover:text-primary">MA 50</span>
      </label>
      {/* MA200 */}
      <label className="flex items-center gap-2 cursor-pointer group">
        <input type="checkbox" checked={showMA200} onChange={onToggleMA200} className="h-3 w-3" />
        <div className="h-0.5 w-3 rounded-full bg-sky-500" />
        <span className="text-[11px] text-foreground group-hover:text-primary">MA 200</span>
      </label>
    </div>
    <div className="border-t border-border px-2 py-1">
      <span className="text-[10px] uppercase text-muted-foreground">Lines</span>
    </div>
    <div className="p-2 space-y-1">
      {/* RSI — future phase */}
      <span className="text-[10px] text-muted-foreground/50 font-mono">RSI — coming</span>
      <span className="text-[10px] text-muted-foreground/50 font-mono">MACD — coming</span>
    </div>
  </div>
)}
```

Add `showIndicatorPanel` state and `onToggleIndicators` callback to `OHLCVChart` → `ChartToolbar` props.

---

### Fix 6: EntityGraphPanel — add hover tooltips

**File**: `EntityGraphPanel.tsx`

The component has `hoveredNodeId` state but never renders a tooltip. Add:

1. **Node tooltip state** with position:
   ```tsx
   const [tooltip, setTooltip] = useState<{
     id: string; label: string; type: string; x: number; y: number;
   } | null>(null);
   ```

2. **SVG wrapper div** with `relative` positioning so the tooltip can be absolute-positioned:
   ```tsx
   <div className="relative overflow-hidden">
     <svg ...>
       {/* existing edges/nodes */}
       <g
         onMouseEnter={(e) => setTooltip({ id: node.id, label: node.label, type: node.type, x: ..., y: ... })}
         onMouseLeave={() => setTooltip(null)}
       />
     </svg>
     {tooltip && (
       <div
         className="pointer-events-none absolute z-50 rounded-[2px] border border-border/50 bg-card px-2 py-1.5"
         style={{ left: tooltip.x + 10, top: tooltip.y - 30 }}
       >
         <p className="text-[11px] font-medium text-foreground">{tooltip.label}</p>
         <p className="text-[10px] capitalize text-muted-foreground">Type: {tooltip.type}</p>
       </div>
     )}
   </div>
   ```

3. **SVG coordinate to DOM coordinate conversion**: SVG `onMouseEnter` in React provides the React synthetic event which includes `clientX/clientY`. Subtract the container's `getBoundingClientRect().left/top` to get relative coordinates. Use a `ref` on the SVG container div.

4. **Edge tooltip**: SVG `<line>` elements are hard to hover (1px stroke). Increase the hover area by adding an invisible wider `<line>` with `strokeWidth={8} stroke="transparent"` behind each visible edge line, and attach `onMouseEnter`/`onMouseLeave` to it.

For edge tooltip content, show:
- Relationship type (edge label formatted: `CEO_OF` → `CEO of`)
- Strength: `edge.weight.toFixed(2)`

5. **Intelligence tab EntityGraph** (sigma.js) already has tooltips. Enhance the `EdgeTooltipPanel` at `EntityGraph.tsx:290` to also show:
   - Last mentioned date (if available from API)
   - Confidence score

---

### Fix 7: Fundamentals — Y-axis, more news, competitors box

#### 7a. Revenue Trend Y-axis
**File**: `RevenueTrendSparklines.tsx`

Change chart height from 120px to 160px to accommodate Y-axis labels. Add `YAxis` from recharts:

```tsx
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer
} from "recharts";

// Inside ComposedChart:
<YAxis
  yAxisId="revenue"
  dataKey="revenue"
  orientation="left"
  width={28}
  tick={{ fontSize: 8, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
  tickFormatter={(v) => `$${v}B`}
  axisLine={false}
  tickLine={false}
/>
<YAxis
  yAxisId="eps"
  dataKey="eps"
  orientation="right"
  width={24}
  tick={{ fontSize: 8, fontFamily: "monospace", fill: "#26A69A" }}
  tickFormatter={(v) => `$${v.toFixed(1)}`}
  axisLine={false}
  tickLine={false}
/>
// Update Bar and Line to use yAxisId
<Bar yAxisId="revenue" ... />
<Line yAxisId="eps" ... />
```

Change `ResponsiveContainer` height from 120 to 160. Change margin to `{ top: 4, right: 28, bottom: 0, left: 32 }` to make room for Y-axes.

#### 7b. More news in Fundamentals sidebar
**File**: `FundamentalsTopNews.tsx`

Change the news fetch limit from 3 to 6. Use a compact row layout (not full ArticleCard) that shows:
- Title (1-line clamp, 11px)
- Source + score + timestamp (1 row, 10px)
- Total height per article: ~44px (vs current ~100px per ArticleCard)

```tsx
{articles.slice(0, 6).map((article) => (
  <a key={article.article_id} href={safeExternalUrl(article.url)} target="_blank"
     rel="noopener noreferrer"
     className="block px-2 py-1.5 hover:bg-muted/20 border-b border-border/20 last:border-0 group">
    <p className="text-[11px] text-foreground leading-tight line-clamp-1 group-hover:text-primary">
      {article.title}
    </p>
    <div className="flex items-center gap-1.5 mt-0.5">
      {article.source_name && (
        <span className="text-[9px] text-muted-foreground">{article.source_name}</span>
      )}
      {article.display_relevance_score != null && (
        <span className="font-mono text-[9px] text-warning">
          {(article.display_relevance_score * 100).toFixed(0)}
        </span>
      )}
      <span className="text-[9px] text-muted-foreground ml-auto">
        {formatRelativeTime(article.published_at)}
      </span>
    </div>
  </a>
))}
```

#### 7c. Competitors box
**File**: `MarketPositionPanel.tsx`

The `COMPETITORS` row currently renders like any other flat `MetricRow`. It should be visually different — a table/card with columns: TICKER, P/E, MCAP, RET (1D). Currently showing "sector" and "No peer data available".

The `PeerComparisonPanel` in the sidebar already tries to fetch peers but shows "No peer data available" when the graph returns no direct company competitors. This is a data issue (the KG graph may not have COMPETITOR edges for this entity yet).

For the immediate fix, in `MarketPositionPanel.tsx`:
- Add a `bg-muted/10 border border-border/30 rounded-[2px]` wrapper around the competitors list
- Show "Peers not available" in a more visually distinct "empty state card" style rather than a flat text row
- Ensure the competitors table header (TKR / P/E / MCAP / RET) always shows even when data is missing

---

### Fix 8: News tab — compact rows + enrichment data

**Files**:
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (News tab section)
- `components/news/ArticleCard.tsx` (add compact variant)

#### Option A: Add `variant="compact"` to ArticleCard

Add a `compact?: boolean` prop to `ArticleCard`. When `compact=true`:
- Remove `p-3` padding → use `px-2 py-1.5` (4px top/bottom, 8px sides)
- Remove `border border-border/40 bg-card rounded-[2px]` card style
- Use a simple hover highlight: `hover:bg-muted/20`
- Show: score badge + timestamp on the RIGHT, title (1-line clamp) as main content, source + routing tier on line 2
- Total height per article: ~44px (was ~100px+)

```tsx
// Compact variant layout
if (compact) {
  return (
    <a href={safeExternalUrl(article.url)} target="_blank" rel="noopener noreferrer"
       className={cn(
         "flex items-start gap-2 px-3 py-1.5 hover:bg-muted/20 transition-colors group border-b border-border/20 last:border-0",
         isLightTier && "opacity-60",
       )}>
      {/* Score badge — left column, fixed width */}
      <div className="shrink-0 w-7 mt-0.5">
        {score != null ? (
          <span className={cn(scoreBadgeClass, "block text-center")}>
            {(score * 100).toFixed(0)}
          </span>
        ) : (
          <span className="block w-7 h-3.5 bg-muted/30 rounded-[2px]" />
        )}
      </div>

      {/* Content column */}
      <div className="flex-1 min-w-0">
        <p className="text-[11px] text-foreground leading-tight line-clamp-1 group-hover:text-primary">
          {article.title}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          {source !== "—" && (
            <span className="text-[9px] text-muted-foreground">{source}</span>
          )}
          {isHighTier && (
            <span className="text-[9px] font-semibold text-primary">TOP</span>
          )}
          {/* Day t0 impact if available */}
          {"impact_windows" in article && article.impact_windows?.day_t0 != null && (
            <span className={cn(
              "text-[9px] font-mono",
              article.impact_windows.day_t0 > 0 ? "text-positive" : "text-negative"
            )}>
              {article.impact_windows.day_t0 > 0 ? "▲" : "▼"}
              {Math.abs(article.impact_windows.day_t0 * 100).toFixed(1)}%
            </span>
          )}
        </div>
      </div>

      {/* Timestamp — right column */}
      <time className="shrink-0 font-mono text-[10px] text-muted-foreground tabular-nums">
        {formatRelativeTime(article.published_at)}
      </time>
    </a>
  );
}
```

#### In page.tsx News tab section

Change the outer wrapper from `py-2 px-3` card wrapper to a simple `divide-y divide-border/20` list:

```tsx
{filteredArticles.map((article) => (
  <ArticleCard
    key={article.article_id}
    article={article}
    compact={true}   // new prop
  />
))}
```

Remove the `<div key={...} className="px-3 py-2">` wrapper — ArticleCard compact handles its own padding.

This reduces per-article height from ~104px to ~44px, fitting ~3x more articles in the same viewport height.

---

## 7. Priority and Wave Organization

| Wave | Issues | Effort | Impact |
|------|--------|--------|--------|
| **Wave 1** (backend) | Fix 4 (timeseries sort order) | Small — 1 backend file + 1 test | HIGH — fixes dates everywhere |
| **Wave 2** (readability) | Fix 2 (muted-foreground color) | 1 line CSS | HIGH — affects all text |
| **Wave 3** (AI brief) | Fix 1 (markdown + read more) | Medium — 1 component + react-markdown | HIGH — unreadable content |
| **Wave 4** (metrics) | Fix 3a/3b/3c (EPS/BETA/AVG VOL) | Medium — 2-3 components + queries | MEDIUM — hardcoded placeholders |
| **Wave 5** (chart UX) | Fix 5 (indicator sidebar, black space) | Medium — 2 components redesigned | MEDIUM — UX improvement |
| **Wave 6** (graph) | Fix 6 (EntityGraph tooltips) | Small-medium — tooltip JSX added | MEDIUM — discoverability |
| **Wave 7** (fundamentals) | Fix 7 (Y-axis, news, competitors) | Medium — 3 sub-components | MEDIUM — data readability |
| **Wave 8** (news tab) | Fix 8 (compact rows + enrichment) | Small — ArticleCard variant | MEDIUM — density |

---

## 8. Prevention Recommendations

- **BP-261**: timeseries endpoints should always support `order` parameter (asc/desc) with `desc` as the recommended default for UI consumption (newest data first). Add note to `.claude-context.md` for market-data service.
- **Markdown rendering**: any component receiving AI-generated narrative content should always use `react-markdown` or a markdown sanitizer — never render raw markdown strings in `<p>` tags.
- **Contrast rule**: establish a project-wide rule: any text ≤12px must use at minimum `text-foreground/70` (not `text-muted-foreground`) to maintain WCAG AA contrast.
- **Placeholder guard**: Components with hardcoded `"—"` placeholders should include a `// TODO(PLAN-XXXX)` reference so they don't persist indefinitely.

---

## 9. Open Questions

1. Are `forward_pe`, `dividend_yield`, `roe`, `debt_to_equity` populated in the `fundamental_metrics` DB table for AAPL? (Backend data verification needed — run SQL query)
2. Does `react-markdown` need to be added to `package.json`, or is there an existing markdown renderer in the project?
3. For chart indicators (RSI, MACD): `lightweight-charts` v4 supports custom series API for RSI. Is there a plan/wave for this, or is it out of scope for this redesign?
4. Should the BETA/AVG VOLUME fetch in `OverviewLayout` use `placeholderData` from the CompanyOverview if those fields are included there?

---

**Next step**: `/implement` Wave 1 (timeseries sort order fix) first — it unblocks Waves 3, 7 and fixes the most visible data problem.
