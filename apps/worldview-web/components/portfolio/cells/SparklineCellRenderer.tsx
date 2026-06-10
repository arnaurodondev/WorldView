/**
 * SparklineCellRenderer — AG Grid cell renderer: 60×16px inline SVG sparkline.
 *
 * WHY THIS EXISTS: Each holdings row needs a 14-day close-price sparkline to
 * show momentum at a glance. AG Grid requires a custom cell renderer to embed
 * SVG directly inside the grid cell. We use a pure inline SVG path (no chart
 * library) because the 60×16 viewport is far too small for lightweight-charts
 * or recharts — those libraries add kilobytes of overhead for a 60px rendering.
 *
 * WHO USES IT: ag-holdings-columns.tsx SPARK column cellRenderer.
 *
 * DATA SOURCE: holdingsSeries prop passed via AG Grid context
 * (params.context.holdingsSeries). When no context is provided (e.g. in tests
 * or before the series loads), renders "—" placeholder.
 *
 * KEYING (R1 sprint fix — every SPARK cell rendered "—" before this):
 * The S9 endpoint GET /v1/market/sparklines returns
 * `{"data": {"<instrument_id>": [closes…]}}` — keyed by INSTRUMENT_ID (see
 * services/api-gateway routes/market.py `get_market_sparklines`), and
 * useHoldingsSeries passes that map through untouched. The original renderer
 * looked the map up by TICKER, so the lookup always missed and the column was
 * permanently blank. We now look up by instrument_id FIRST and fall back to
 * ticker so any caller that re-keyed the map by ticker (older tests, future
 * batch endpoints) keeps working.
 *
 * DESIGN REFERENCE: PRD-0089 W2 §4.11, V7; PLAN-0108 W4-T402
 */

import type { ICellRendererParams } from "ag-grid-community";
import type { EnrichedHoldingRow } from "@/components/portfolio/holdings-columns";

// ── Context shape ─────────────────────────────────────────────────────────────

interface SparklineCellContext {
  /**
   * Close-price series (typically 14 bars of 1D OHLCV). Keyed by
   * instrument_id (the S9 sparklines response key) with a legacy ticker-key
   * fallback — see the file-header KEYING note. Provided by
   * SemanticHoldingsTable via AG Grid context.
   */
  holdingsSeries: Record<string, number[]>;
}

// ── SVG viewport constants ────────────────────────────────────────────────────

/**
 * SVG_W / SVG_H — the fixed viewport for all sparklines in this column.
 *
 * WHY 60×16: the AG Grid row height is 20px (default compact size). 16px leaves
 * 2px of natural whitespace above and below inside the flex container. 60px is
 * wide enough to show 14 data points without visual crowding while staying
 * narrow enough not to push other columns off-screen.
 */
const SVG_W = 60;
const SVG_H = 16;

/**
 * PADDING_Y — pixels reserved at the top and bottom of the SVG for stroke width.
 *
 * WHY 1px: strokeWidth is 1.5px. Without vertical padding the stroke would be
 * clipped by the SVG viewport edges at min/max values. 1px on each side gives
 * the stroke enough room to render fully without a clipPath rule.
 */
const PADDING_Y = 1;

// ── SVG path builder ──────────────────────────────────────────────────────────

/**
 * buildSparkPath — normalises `data` into the 60×16 viewport and returns an
 * SVG path `d` attribute string (e.g. "M 0,14 L 30,8 L 60,2").
 *
 * Algorithm (see inline comments for WHY each step):
 *
 *   1. Determine minY and maxY of the series.
 *   2. Compute range = maxY − minY.  Use range = 1 when all values are equal
 *      (flat line) to avoid division by zero — the normalised y becomes 0.5
 *      for every point, which draws the line at the vertical midpoint.
 *   3. For each point i:
 *        x(i) = (i / (n−1)) × SVG_W
 *        y(i) = SVG_H − PADDING_Y − ((data[i] − minY) / range) × (SVG_H − 2×PADDING_Y)
 *      The y formula maps the lowest value to the bottom (SVG_H − PADDING_Y)
 *      and the highest value to the top (PADDING_Y). SVG y-axis is inverted
 *      (0 = top) so we subtract from SVG_H.
 *   4. Join all points with "M x0,y0 L x1,y1 …".
 *
 * @param data  Array of close prices, length >= 2 (caller must guard).
 * @returns     SVG path `d` string.
 */
function buildSparkPath(data: number[]): string {
  // Step 1: find the min and max of the series.
  // WHY Math.min/max with spread: concise and correct for arrays up to ~100k
  // elements. The series is at most 30 bars (1 month of 1D candles), so stack
  // overflow risk is negligible.
  const minY = Math.min(...data);
  const maxY = Math.max(...data);

  // Step 2: guard against a flat line (all prices identical → range = 0).
  // WHY default to 1: dividing by 0 would produce NaN coordinates, breaking
  // the SVG path silently. With range = 1, the formula maps every point to
  // y = SVG_H/2 (middle of viewport), which correctly shows a horizontal line.
  const range = maxY - minY || 1;

  // Step 3: compute the drawable height area (viewport minus vertical padding).
  // WHY subtract 2×PADDING_Y: we reserve PADDING_Y pixels at both top and
  // bottom so the stroke is never clipped by the viewport edge.
  const drawH = SVG_H - 2 * PADDING_Y;

  // Step 4: build the path string by iterating over all data points.
  const n = data.length;
  const points = data.map((price, i) => {
    // WHY (i / (n-1)): distributes points evenly across the full width
    // (0 → left edge, n-1 → right edge). Avoids the right side being empty.
    const x = (i / (n - 1)) * SVG_W;

    // WHY (SVG_H - PADDING_Y - ...): SVG y=0 is the TOP; a higher price must
    // map to a SMALLER y value. We start from the bottom padding baseline
    // (SVG_H − PADDING_Y) and subtract the normalised height.
    const y = SVG_H - PADDING_Y - ((price - minY) / range) * drawH;

    // Round to 2 decimal places to keep the SVG markup compact.
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  // First point uses "M" (moveto), subsequent points use "L" (lineto).
  return `M ${points[0]} L ${points.slice(1).join(" L ")}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SparklineCellRenderer(params: ICellRendererParams<EnrichedHoldingRow>) {
  // WHY pinned-row guard: the totals footer has no meaningful sparkline — it
  // aggregates multiple instruments with incompatible price scales. Returning
  // null collapses the cell to empty, which is cleaner than a dash here.
  if (params.node?.rowPinned === "bottom") return null;

  // WHY read from params.data.h rather than params.value: the SPARK colDef
  // has no valueGetter (the whole row flows through), so we pull the lookup
  // keys straight off the row's Holding.
  const instrumentId = params.data?.h.instrument_id;
  const ticker = params.data?.h.ticker;

  // Cast context to our typed shape; guard against undefined (e.g. in tests
  // that don't inject context, or before SemanticHoldingsTable mounts).
  const context = params.context as SparklineCellContext | undefined;
  const seriesMap = context?.holdingsSeries;

  // Resolve the series: instrument_id first (the S9 response key — R1 fix),
  // then ticker (legacy keying kept for backward compatibility).
  // WHY fallback to []: an empty array triggers the "—" placeholder below;
  // this is safer than a null-check pyramid and matches the lazy-load contract.
  const data: number[] =
    (instrumentId ? seriesMap?.[instrumentId] : undefined) ??
    (ticker ? seriesMap?.[ticker] : undefined) ??
    [];

  // ── Fallback: "—" when there is no usable series ──────────────────────────
  if (data.length < 2) {
    // WHY em-dash (not skeleton): AG Grid re-renders the cell on every data
    // change; a skeleton would flash and disappear on each quote tick, which is
    // more jarring than a stable dash. The dash also signals "no data" clearly
    // to the trader without consuming layout space.
    return (
      <span className="font-mono text-[11px] text-muted-foreground">—</span>
    );
  }

  // ── Trend colour ──────────────────────────────────────────────────────────

  // WHY first vs last (not open vs close of the same bar): "first" is the
  // oldest bar in the 14-day window and "last" is the most recent. This gives
  // us the window-level trend (up/down) rather than intraday direction.
  const first = data[0];
  const last = data[data.length - 1];

  // WHY hsl(var(--chart-*)) (R1 sprint fix): this codebase is Tailwind 3.4 —
  // design tokens are HSL TRIPLETS (e.g. `--chart-positive: 150 100% 41%`)
  // that must be wrapped in hsl(). The previous `var(--color-positive)` token
  // does not exist anywhere in globals.css, so the SVG stroke resolved to an
  // invalid value and the line never painted. `--chart-positive/negative/
  // neutral` are the chart-specific sentiment tokens introduced by W0 FR-10.1
  // exactly for sparklines — they track --positive/--negative but can diverge
  // for chart fills without touching text colours.
  // WHY three-way (not two-way): per DESIGN_SYSTEM.md §sparklines a flat
  // window is NOT a downtrend; painting it red mis-signals direction.
  const strokeColor =
    last > first
      ? "hsl(var(--chart-positive))"   // uptrend → green (bull)
      : last < first
        ? "hsl(var(--chart-negative))" // downtrend → red (bear)
        : "hsl(var(--chart-neutral))"; // flat → neutral grey

  // ── SVG path ─────────────────────────────────────────────────────────────

  const pathD = buildSparkPath(data);

  return (
    // WHY flex + items-center: the sparkline SVG must be vertically centred in
    // the 20px AG Grid row. Without flex, SVG baseline-aligns to the text
    // baseline, which shifts it ~2px too low.
    <div className="flex items-center h-full">
      <svg
        width={SVG_W}
        height={SVG_H}
        // WHY viewBox="0 0 60 16": coordinates in buildSparkPath are already in
        // viewport space (0..60, 0..16), so viewBox matches 1:1.
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        // WHY preserveAspectRatio="none": the cell width is fixed (60px column)
        // and the viewport is already the right size. "none" prevents any
        // letterboxing if the container ever differs in width.
        preserveAspectRatio="none"
        aria-label={`${ticker ?? "instrument"} price trend`}
        role="img"
      >
        <path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth="1.5"
          // WHY round joins and caps: mitre joins can produce sharp spikes at
          // inflection points on a 1.5px stroke. Round smooths these out
          // without requiring a filter or clip.
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
