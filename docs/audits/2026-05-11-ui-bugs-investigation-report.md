# UI Bugs Investigation Report — 2026-05-11

**Investigator**: Claude Code (Principal Debugging Engineer)
**Session**: `/investigate` — continuation from bd8c7986
**Scope**: Four visual bugs observed live in the worldview frontend (Next.js 15 + React)
**Status**: All four root causes confirmed with exact file/line references

---

## Executive Summary

| # | Bug | Severity | Root Cause File | Lines | Fix Complexity |
|---|-----|----------|-----------------|-------|----------------|
| 1 | Portfolio page — totals footer values misaligned | Medium | `SemanticHoldingsTable.tsx` | 318–342 | Simple |
| 2 | Instrument chart — scrolls to oldest bar on load | High | `OHLCVChart.tsx` | 529–533 | 1-line fix |
| 3 | Instrument overview — KEY METRICS sidebar black area | Medium | `OverviewLayout.tsx` | 391 | 1 attribute |
| 4 | Same black area — EntityGraphPanel not filling grid cell | Medium | `OverviewLayout.tsx` | 391 | 1 class |

Bugs 3 and 4 are the same visual defect from two co-operating causes.
Bug 2 has a single-line fix but the race-condition it exploits is subtle — the section below explains it precisely so the fix is not re-introduced.

---

## Bug 1 — Portfolio page: values wrongly placed / wrong spacing (Image #1)

### Symptom

In the portfolio overview (Holdings tab), the totals row beneath the AG Grid shows P&L and Total Value numbers that are horizontally displaced from the column headers above them. A value like `-$153` appears in the wrong column position.

### Root Cause

**File**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:315–342`

The totals footer beneath the AG Grid is a plain `<div>` with hardcoded pixel widths that were calibrated to match the _initial_ column widths defined in `ag-holdings-columns.tsx`. It is not an AG Grid pinned-bottom row — it is a separate DOM element positioned below the grid.

The left spacer is hardcoded to 640 px:

```tsx
{/* Left spacer: TICKER(80) + NAME(130) + QTY(80) + AVG COST(90) + CURRENT(90) + DAY$(90) + DAY%(80) = 640 */}
<div className="shrink-0 w-[640px] px-2 text-[10px] ...">TOTAL</div>
```

The actual `HOLDINGS_AG_COL_WIDTHS` in `ag-holdings-columns.tsx:30–43` are:

```ts
ticker: 80, name: 130, qty: 80, avgCost: 90, current: 90,
dayChange: 90, dayChangePct: 80   // sum = 640 ← footer spacer
```

**The critical mismatch**: the TICKER column is **pinned left** (`lockPinned: true` in the AG Grid column definition). In AG Grid, pinned-left columns render in a completely separate DOM container (`ag-pinned-left-cols-container`) that sits alongside the scrollable main viewport container. The totals footer div is a flat sibling below the grid — it is NOT split into pinned/main sections.

This means:
- AG Grid visually renders: `[pinned: TICKER=80px] [scrollable: NAME…DAY%…PNL…VALUE=1060px]`
- Totals footer renders: `[spacer: 640px] [PNL: 100px] [PNL%: 80px] [VALUE: 100px]`

At initial render with no horizontal scroll, the spacer's first 80 px aligns with the pinned TICKER area and the next 560 px aligns with NAME through DAY%. This appears correct. But the following conditions cause drift:

1. **Horizontal scroll in the main viewport**: the AG Grid's main columns scroll; the pinned TICKER column stays put; the footer does not scroll. After the user scrolls right by any amount, the P&L and Value totals no longer align with their column headers.

2. **Column resize**: the comment in the code acknowledges this — "Width alignment drifts after the user resizes columns". Any column width change immediately breaks alignment.

3. **Viewport width**: if the page renders at a width where AG Grid auto-fits or compresses columns differently than the initial values, the mismatch exists from first paint.

The `-$153` displaced value the user sees is the `totalPnl` cell (`w-[100px]`) rendered at the wrong horizontal position because the 640 px spacer doesn't align correctly with the live grid layout.

### Fix

Replace the hardcoded-width footer div with an AG Grid **pinned bottom row**. AG Grid's pinned rows render inside the same scrolling + pinning infrastructure as data rows, so alignment is always correct.

**Alternative quick fix** (if a full AG Grid pinned-row migration is too large for one wave): remove the totals footer entirely and use AG Grid's built-in `columnFooter` / `valueFormatter` approach with `pinnedBottomRowData`. This is a 1-component change scoped to `SemanticHoldingsTable.tsx`.

**Minimal stop-gap fix** (1 line): Make the footer a sticky footer that scrolls horizontally with the grid:

```tsx
// Wrap the grid + footer in a single overflow-x-auto container so the footer
// scrolls in sync with the grid's horizontal scroll.
<div className="overflow-x-auto relative">
  <AgGridBase ... />
  <div className="flex h-[22px] shrink-0 items-center border-t-2 border-border min-w-[920px]">
    {/* same content but now scroll-locked to the grid */}
  </div>
</div>
```

**Recommended fix**: Use AG Grid `pinnedBottomRowData`. See AG Grid docs for `gridOptions.pinnedBottomRowData`. This is the correct architectural solution — zero hardcoded widths.

---

## Bug 2 — Instrument chart scrolls to the past on load (Image #2 + HTML dump)

### Symptom

When navigating to any instrument detail page, the OHLCV candlestick chart renders with the viewport positioned at the oldest historical bar (e.g., 1985 for AAPL), instead of the most recent bar. The chart canvas is `width: 51006px` (confirmed in the HTML dump — this is the full historical timeline), and the visible viewport is anchored at the leftmost edge.

### Root Cause — Race Condition in `pendingScrollToRealTime` Path

**File**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:529–533`

The `scrollToRealTime()` mechanism uses two `useRef` guards:

```ts
const hasScrolledToRealTime = useRef(false);   // prevents duplicate scrolls
const pendingScrollToRealTime = useRef(false);  // deferred scroll when chart not ready
```

The intended flow when `initialBars` (placeholderData) is available:

1. Data effect fires with `data.bars = initialBars` (React Query placeholder)
2. `chartRef.current` may be null — `initChart()` is async (dynamic import of `lightweight-charts`)
3. If chart is not ready → `pendingScrollToRealTime.current = true`
4. `initChart()` completes → checks the pending flag → calls `scrollToRealTime()`
5. Real API data arrives → data effect fires → guard blocks a second scroll

**The bug is at step 4**. The current code in `initChart()` (lines 529–533):

```ts
if (pendingScrollToRealTime.current) {
  pendingScrollToRealTime.current = false;
  hasScrolledToRealTime.current = true;    // ← BUG: marks done before any data is loaded
  chart.timeScale().scrollToRealTime();    // ← no-op: chart has zero data series at this point
}
```

When `initChart()` handles the pending flag:
- The chart has just been created (`createChart()`)
- No `setData()` has been called on any series yet
- `chart.timeScale().scrollToRealTime()` is a **documented no-op** when the chart has no data points
- But `hasScrolledToRealTime.current = true` IS set — the guard is raised

Now when real API data arrives and the data effect runs:

```ts
if (formattedBars.length > 0 && !hasScrolledToRealTime.current) {  // ← false: guard already set
  chartRef.current.timeScale().scrollToRealTime();
}
```

The guard blocks the scroll permanently. The chart renders all historical bars starting from bar index 0 (1985), and `scrollToRealTime()` is never called with actual data. The 51006 px canvas width confirms all historical bars were loaded — only the viewport position is wrong.

### Triggering Condition

This race is triggered specifically when `placeholderData` (from `memoizedPlaceholder`) is available and the React Query `data.bars` resolves **before** the `lightweight-charts` dynamic import completes. This is the common case on first load of the instrument page, since:
- `initialBars` comes from the bundle endpoint (already in memory when navigation happens)
- `lightweight-charts` dynamic import takes ~100–300ms (first load, CDN fetch or local bundle parse)

The `memoizedPlaceholder` (OHLCVChart.tsx:438–448) feeds the placeholder for `timeframe==="1D"` only. For other timeframes the race cannot happen. This explains why the bug appears specifically on `1D` initial load (the default timeframe).

### Why the Reset Doesn't Help

The reset effect (lines 299–303):

```ts
useEffect(() => {
  hasScrolledToRealTime.current = false;
  pendingScrollToRealTime.current = false;
}, [instrumentId, timeframe]);
```

Resets correctly on instrument/timeframe change, but the race re-occurs on the FIRST load of every instrument because the reset fires before any data loads, setting the stage for the same race.

### Fix

**File**: `OHLCVChart.tsx:529–533`

Remove `hasScrolledToRealTime.current = true` from the `initChart()` pending path. Also remove the no-op `scrollToRealTime()` call — it does nothing and the comment should be updated:

```ts
// BEFORE (buggy):
if (pendingScrollToRealTime.current) {
  pendingScrollToRealTime.current = false;
  hasScrolledToRealTime.current = true;    // ← REMOVE this line
  chart.timeScale().scrollToRealTime();    // ← REMOVE this call (no-op, misleading)
}

// AFTER (correct):
if (pendingScrollToRealTime.current) {
  pendingScrollToRealTime.current = false;
  // Chart has no data yet — scrollToRealTime() would be a no-op.
  // The data effect will call it when bars arrive (hasScrolledToRealTime is still false).
}
```

With this fix, the flow becomes correct in ALL cases:

**Case A — Normal (initChart completes before placeholder data)**:
1. `initChart()` runs → no pending flag → guard stays false
2. Placeholder bars arrive → data effect fires → `chartRef.current` is set → `scrollToRealTime()` called → guard set
3. Real API data arrives → guard blocks second scroll ✓

**Case B — Race (placeholder data before initChart completes)**:
1. Placeholder bars arrive → data effect fires → `chartRef.current = null` → `pendingScrollToRealTime = true`
2. `initChart()` completes → pending flag found → clears it → **guard stays false**
3. Real API data arrives → data effect fires → `chartRef.current` now set → `scrollToRealTime()` called → guard set ✓

---

## Bugs 3 & 4 — Black area below entity graph / KEY METRICS sidebar appearance

These two are co-located in `OverviewLayout.tsx` and one is the direct visual cause of the other.

### Symptom

In the instrument Overview tab, the lower section (news + insider + entity graph row) shows a black void below the entity graph panel. The grid row is `min-h-[400px]` but the entity graph SVG renders at its minimum height (280px), leaving ~120 px of raw `#09090B` background visible. This is the "black area" the user sees when selecting the div.

The KEY METRICS sidebar appearing "small" is a secondary perception effect: when the chart viewport is stuck at the far left (Bug 2), the dark chart canvas with no visible candles makes the adjacent 280px KEY METRICS sidebar look proportionally narrow.

### Root Cause — Missing `h-full` on EntityGraphPanel wrapper

**File**: `apps/worldview-web/components/instrument/OverviewLayout.tsx:391`

The lower section grid:

```tsx
<div className="grid grid-cols-3 min-h-[400px]">
  {/* Zone 6: Top News */}
  <div className="border-r border-border min-w-0">
    <InstrumentTopNews ... />
  </div>

  {/* Zone 7: Insider Activity */}
  <div className="border-r border-border min-w-0">
    <OverviewInsiderStrip ... />
  </div>

  {/* Zone 8: Entity Graph  ← BUG HERE */}
  <div className="min-w-0">    {/* ← missing h-full */}
    <EntityGraphPanel entityId={entityId} centerLabel={centerLabel} />
  </div>
</div>
```

Inside `EntityGraphPanel.tsx`, the component root is:

```tsx
<div className="relative overflow-hidden rounded-[2px] border border-border/30 bg-card/30 flex h-full min-h-[280px] flex-col">
```

The `h-full` on the EntityGraphPanel root refers to **the height of its parent div** (`<div className="min-w-0">`). That parent has no explicit height — it auto-sizes to fit its children. So `h-full` resolves to the computed height of the EntityGraphPanel content (minimum 280 px from `min-h-[280px]`), not to the 400 px grid cell height.

The CSS Grid sets the row's minimum height to 400 px via `min-h-[400px]` on the grid container. But `min-h` does not propagate down to grid cells as `height` — it only constrains the grid ROW's outer dimension. The individual grid items (`div.min-w-0`) do not inherit this height unless they have `h-full` themselves.

**Result**: EntityGraphPanel renders at 280 px. The grid cell is 400 px. The remaining 120 px below the `bg-card/30` panel shows the bare grid cell background — which inherits from `bg-background` (`#09090B`), appearing black.

The OverviewLayout.tsx comment at line 356–363 acknowledges this was a known issue from the old layout ("120px black void below the SVG") and states it was "fixed" in the 2026-05-09 redesign. But the fix was incomplete — the redesign changed the outer grid structure but forgot to add `h-full` to the Zone 8 wrapper div.

### Why Zones 6 and 7 don't have this issue

- `InstrumentTopNews` renders a flex column of article rows — it naturally expands to fill all available vertical space when there is content.
- `OverviewInsiderStrip` renders insider transaction rows — same pattern.
- `EntityGraphPanel` renders a Cytoscape.js SVG with a fixed-size canvas that does NOT auto-expand; it stops at `min-h-[280px]`.

### Fix

**File**: `OverviewLayout.tsx`, Zone 8 wrapper (line 391):

```tsx
{/* Zone 8: Entity Graph (1/3 col) */}
<div className="min-w-0 h-full">    {/* ← add h-full */}
  <EntityGraphPanel
    entityId={entityId}
    centerLabel={centerLabel}
  />
</div>
```

With `h-full` on the wrapper, the wrapper's height equals the grid cell height (≥400 px), and EntityGraphPanel's internal `h-full` correctly references the 400 px wrapper — filling the space completely.

### KEY METRICS Sidebar Width (Bug 3 secondary aspect)

The `OverviewLayout` right sidebar is hardcoded at `w-[280px] flex-shrink-0`:

```tsx
<div className="w-[280px] flex-shrink-0 flex flex-col overflow-y-auto">
```

This is intentional per the design comment: "WHY 280px fixed sidebar (not percentage): percentages collapse below readability at wide viewport widths." The 280 px is not a bug in itself, but the combination of:

1. Chart showing blank/historical view (Bug 2) — the chart area looks like a large black area
2. Many KEY METRICS values showing `—` (em-dash) because EODHD data is absent for FWD P/E, EPS, DIV YIELD, BETA, ROE

...makes the sidebar appear disproportionately small. Once Bug 2 is fixed (chart shows recent data) the sidebar will appear properly proportioned.

The `OverviewSidebarMetrics` uses `max-w-[55%] text-right` on value spans (55% of 280 px = 154 px), which is sufficient for values like `$4.31T` and `35.47x`. No width change is needed.

---

## Fix Implementation Order

Fix in this order to avoid regressions:

### Step 1 — Bug 2 (Chart scroll): 1-line change, zero risk

**File**: `apps/worldview-web/components/instrument/OHLCVChart.tsx`

Find lines 529–533:
```ts
if (pendingScrollToRealTime.current) {
  pendingScrollToRealTime.current = false;
  hasScrolledToRealTime.current = true;
  chart.timeScale().scrollToRealTime();
}
```

Replace with:
```ts
if (pendingScrollToRealTime.current) {
  pendingScrollToRealTime.current = false;
  // Chart has no data yet — the data-update effect will call scrollToRealTime()
  // as soon as the first bars are loaded (hasScrolledToRealTime stays false).
}
```

**Test**: Navigate to any instrument page (`/instruments/<id>`). On the `1D` timeframe, the chart must show the most recent bar on the right edge, not 1985-era data. Switch timeframes: each switch must re-scroll to the most recent bar.

---

### Step 2 — Bug 4 (Black area): 1-class change, zero risk

**File**: `apps/worldview-web/components/instrument/OverviewLayout.tsx`

Find line ~391 (Zone 8 wrapper):
```tsx
<div className="min-w-0">
  <EntityGraphPanel ... />
</div>
```

Replace with:
```tsx
<div className="min-w-0 h-full">
  <EntityGraphPanel ... />
</div>
```

**Test**: Navigate to any instrument's Overview tab. The lower row (News | Insider | Graph) must have no black gap below the entity graph panel. The graph should fill the full 400 px row height.

---

### Step 3 — Bug 1 (Totals footer): requires architecture decision

**File**: `apps/worldview-web/components/portfolio/SemanticHoldingsTable.tsx:298–342`

Option A (recommended): Convert the totals footer to an AG Grid pinned bottom row.

1. Add `pinnedBottomRowData` to `AgGridBase` props — pass a synthetic `EnrichedHoldingRow` with the computed totals.
2. Define value formatters/renderers for `pnl`, `pnlPct`, and `value` columns that detect the pinned row and render totals.
3. Remove the entire `{/* Totals footer */}` block (lines 315–342).

Option B (stop-gap): Wrap the `AgGridBase` + footer in a single `overflow-x-auto` scroll container so they scroll together:

```tsx
<div className="relative overflow-x-auto">
  <AgGridBase ... />
  {/* footer div with current hardcoded widths — now scrolls in sync */}
  <div className="flex h-[22px] shrink-0 items-center border-t-2 border-border min-w-fit">
    ...
  </div>
</div>
```

This prevents the horizontal-scroll misalignment but doesn't fix column-resize drift (acceptable for now per existing comment).

**Test**: Navigate to `/portfolio`. Holdings tab. Confirm the TOTAL, P&L, and Value labels align with their respective column headers. Resize any column — verify the footer tracks. Scroll the grid horizontally — verify the footer scrolls with it.

---

## Files Changed (Summary)

| File | Lines | Change |
|------|-------|--------|
| `components/instrument/OHLCVChart.tsx` | 529–533 | Remove `hasScrolledToRealTime.current = true` and `scrollToRealTime()` call from `initChart()` pending path |
| `components/instrument/OverviewLayout.tsx` | 391 | Add `h-full` class to Zone 8 EntityGraphPanel wrapper div |
| `components/portfolio/SemanticHoldingsTable.tsx` | 298–342 | Migrate totals footer to AG Grid `pinnedBottomRowData` (Option A) or add scroll sync (Option B) |

---

## New Bug Patterns (for BUG_PATTERNS.md)

### BP-XXX: scrollToRealTime() called on empty chart marks scroll guard prematurely done
- **Pattern**: Calling `chart.timeScale().scrollToRealTime()` before any `series.setData()` is a no-op, but setting a "scroll done" guard at the same time permanently prevents the scroll from firing when data actually loads.
- **Root cause**: Deferred-init guards must only be set `true` AFTER the operation actually succeeds on real data.
- **Detection**: Chart shows historical data from the far past on page load; canvas width is several thousand pixels but viewport is anchored at the left edge.

### BP-XXX: h-full on child element requires h-full on intermediate wrapper in CSS Grid
- **Pattern**: A grid cell's `min-h` does not propagate as an explicit height to its children. An element using `h-full` deep in a grid cell will resolve against its immediate parent's height, not the grid cell height.
- **Fix**: Add `h-full` to each intermediate wrapper between the grid item and the element that needs to fill it.

### BP-XXX: Fixed-pixel totals footer below AG Grid misaligns on column resize or pinned column
- **Pattern**: A hardcoded-width `<div>` positioned below AG Grid as a totals row cannot track column widths changed by user resize, or the positional shift caused by pinned columns rendering in a separate container.
- **Fix**: Use AG Grid `pinnedBottomRowData` for totals that must stay column-aligned.

---

## Appendix: Evidence Trail

- **HTML dump (user-provided)**: Chart canvas `width: 51006px` confirms all historical bars loaded (≈10,200 daily bars × 5px/bar). Viewport anchored at leftmost = `scrollToRealTime()` never called on data.
- **OverviewLayout.tsx:356**: Comment "120px black void below the SVG; 'black empty component' reported by the user" confirms this bug was known but incompletely fixed.
- **EntityGraphPanel.tsx:205**: Comment "WHY h-full (was h-[280px]): the panel is now sized by its parent grid cell" — confirms the intent was for `h-full` to work, but intermediate wrapper was left without `h-full`.
- **SemanticHoldingsTable.tsx:316**: Code comment "Width alignment drifts after column resize — acceptable until Phase 8" — explicitly acknowledges the footer alignment issue.
- **OHLCVChart.tsx:277–285**: Comment "WHY hasScrolledToRealTime ref" correctly explains intent; the `pendingScrollToRealTime` guard at line 529–533 violates this intent by setting the guard before data arrives.
