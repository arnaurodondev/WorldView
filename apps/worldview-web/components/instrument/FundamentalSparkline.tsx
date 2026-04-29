/**
 * components/instrument/FundamentalSparkline.tsx — mini trend chart for a single metric
 *
 * WHY THIS EXISTS: A sparkline gives fundamentals data a temporal dimension.
 * Seeing that P/E has been compressing from 42→34 over 8 quarters is more
 * informative than a single "P/E: 34" number. Used in the Overview sidebar
 * (switchable metric) and inline within Fundamentals section cards.
 *
 * WHY SVG polyline (not recharts/lightweight-charts): sparklines are purely
 * decorative trend indicators — no tooltips, axes, or interactions needed.
 * A self-contained SVG with a computed polyline is 0 bytes of additional
 * dependency vs importing a charting library, and renders synchronously.
 *
 * WHY staleTime 300_000 (5 min): fundamentals data changes at most quarterly.
 * A 5-minute cache means dozens of sparkline panels on the same instrument page
 * share a single cached fetch — no redundant network calls.
 *
 * WHO USES IT: OverviewLayout sidebar (Wave C-1 T-C-1-03), FundamentalsTab
 * section cards (Wave D-1), anywhere a trend indicator is needed
 * DATA SOURCE: S9 GET /v1/fundamentals/timeseries (public endpoint, no auth)
 * DESIGN REFERENCE: PLAN-0041 §T-B-1-04
 */

"use client";
// WHY "use client": uses useQuery for async data fetching — requires browser runtime.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundamentalSparklineProps {
  /** Instrument ID (UUIDv7) — passed to the timeseries endpoint as instrument_id */
  instrumentId: string;
  /**
   * Metric key — must match S3's fundamentals_metrics.metric_key column.
   * Examples: "pe_ratio", "revenue", "gross_margin", "net_margin", "roe",
   * "debt_to_equity", "earnings_per_share"
   */
  metric: string;
  /** SVG height in pixels. Default 48 — compact for sidebar panels */
  height?: number;
  /** Additional className for the root wrapper */
  className?: string;
  /**
   * When true, renders:
   *   - X-axis: first and last as_of_date (YYYY-MM) as year-tick labels below the sparkline
   *   - Y-axis: min and max values right-aligned alongside the SVG chart
   *
   * Default false — labels add vertical space and horizontal space; omit for dense sidebar use.
   * T-F-6-07: year ticks (x-axis) + right Y-axis added in this wave.
   */
  showAxis?: boolean;
}

// ── SVG sparkline helpers ─────────────────────────────────────────────────────

/**
 * buildPolylinePoints — convert (index, value) pairs to SVG polyline points string
 *
 * WHY normalize to viewBox coords (not raw values): SVG viewBox="0 0 100 HEIGHT"
 * lets us position points as percentages of width (0–100) and map values to
 * the HEIGHT range without knowing the rendered pixel dimensions.
 *
 * @param values  Array of numeric data points (already filtered for non-null)
 * @param height  SVG viewBox height
 * @returns       Space-separated "x,y" pairs for SVG polyline `points` attribute
 */
function buildPolylinePoints(values: number[], height: number): string {
  if (values.length < 2) return "";

  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal;

  return values
    .map((v, i) => {
      // WHY (values.length - 1): maps last index to x=100 (full width)
      const x = values.length === 1 ? 50 : (i / (values.length - 1)) * 100;
      // WHY invert y (height - ...): SVG y=0 is top; higher values should appear
      // at the top of the chart (graphical convention for financial charts)
      const y =
        range === 0
          ? height / 2 // flat line for constant data
          : height - ((v - minVal) / range) * (height - 4) - 2; // 2px padding each side
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/**
 * formatYAxisLabel — compact representation of a numeric value for the Y-axis tick.
 *
 * WHY compact formatting: the right Y-axis sits in a ~28px wide column alongside the SVG.
 * Full numbers like "2800000" are unreadable at text-[8px]. Using K/M/B suffixes and
 * limiting to 3 significant figures keeps the label scannable at small size.
 *
 * T-F-6-07: new helper introduced for the right Y-axis (was not needed before).
 */
function formatYAxisLabel(value: number): string {
  // WHY handle zero explicitly: Math.abs(0) < 1000 so the fallback branch runs, fine.
  // But toFixed(1) on 0 = "0.0" which is wordier than just "0" — special-case it.
  if (value === 0) return "0";

  const abs = Math.abs(value);
  // WHY 3 significant digits for all branches: enough precision to see "2.80T" vs
  // "2.75T" without overflowing the 28px column. toPrecision(3) handles leading zeros.
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toPrecision(3)}B`;
  if (abs >= 1_000_000)     return `${(value / 1_000_000).toPrecision(3)}M`;
  if (abs >= 1_000)         return `${(value / 1_000).toPrecision(3)}K`;
  // For small values (ratios like P/E = 28.5, margins = 0.44), use 2 decimal places.
  // WHY parseFloat(toFixed(...)): removes trailing zeros ("28.50" → "28.5").
  return String(parseFloat(value.toFixed(2)));
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FundamentalSparkline({
  instrumentId,
  metric,
  height = 48,
  className = "",
  showAxis = false,
}: FundamentalSparklineProps) {
  // ── Data fetch — public endpoint, no token needed ─────────────────────────
  // WHY ["fundamentals-ts", instrumentId, metric]: unique cache key per instrument+metric
  // pair. Two sparklines on the same page for different metrics get independent caches.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["fundamentals-ts", instrumentId, metric],
    queryFn: () =>
      createGateway().getFundamentalsTimeseries(instrumentId, metric, { limit: 20 }),
    staleTime: 300_000, // 5 min — fundamentals are slow-moving data
    enabled: !!instrumentId && !!metric,
  });

  // ── Loading state — skeleton matching the sparkline dimensions ───────────
  if (isLoading) {
    return (
      <div className={`w-full ${className}`}>
        <Skeleton className="w-full rounded-[2px]" style={{ height: `${height}px` }} />
        {showAxis && <Skeleton className="h-3 w-full mt-0.5" />}
      </div>
    );
  }

  // ── Error / empty state ──────────────────────────────────────────────────
  // WHY render a placeholder line (not nothing): keeps the layout stable across
  // loading, error, and success states so surrounding panels don't shift.
  const points = data?.data ?? [];
  const numericValues = points
    .map((p) => p.value_numeric)
    .filter((v): v is number => v != null);

  if (isError || numericValues.length < 2) {
    return (
      <div
        className={`w-full flex items-center justify-center text-muted-foreground text-[10px] font-mono ${className}`}
        style={{ height: `${height}px` }}
      >
        —
      </div>
    );
  }

  // ── Trend color — compare first vs last data point ───────────────────────
  // WHY first→last (not low→high): we want to color the DIRECTION of change,
  // not the distance. A stock that went 100→90→95 trends down (first=100, last=95).
  const firstVal = numericValues[0];
  const lastVal = numericValues[numericValues.length - 1];
  const trendClass =
    lastVal > firstVal
      ? "text-positive"          // positive trend  — #26A69A
      : lastVal < firstVal
      ? "text-negative"          // negative trend  — #EF5350
      : "text-muted-foreground"; // flat — no change

  const polylinePoints = buildPolylinePoints(numericValues, height);

  // ── Axis labels ──────────────────────────────────────────────────────────
  const firstDate = points.find((p) => p.value_numeric != null)?.as_of_date ?? "";
  const lastDate = [...points].reverse().find((p) => p.value_numeric != null)?.as_of_date ?? "";

  // ── Y-axis values (T-F-6-07: right-side Y-axis) ──────────────────────────
  // WHY min + max only (not full Y-axis grid): in a 48px-tall sparkline there is no
  // room for intermediate ticks. Showing max at the top and min at the bottom gives
  // analysts the full value range without cluttering the compact chart.
  const minVal = Math.min(...numericValues);
  const maxVal = Math.max(...numericValues);
  const yMaxLabel = formatYAxisLabel(maxVal);
  const yMinLabel = formatYAxisLabel(minVal);

  return (
    <div className={`w-full ${className}`}>
      {/* ── Sparkline row: SVG (flex-1) + right Y-axis (fixed 28px) ─────────
          WHY flex (not block): aligns the SVG and the Y-axis column horizontally.
          The Y-axis is only rendered when showAxis=true; when false the SVG fills
          the full container width as before, keeping the loading/non-axis states
          pixel-identical to the original behaviour. */}
      <div className={showAxis ? "flex items-stretch" : undefined}>

        {/* ── SVG sparkline — viewBox: 0 0 100 HEIGHT keeps proportions constant ── */}
        {/* WHY preserveAspectRatio none: we want the SVG to stretch to fill the
            container width while keeping the fixed height — standard sparkline behaviour. */}
        {/* WHY width="100%" inside flex child: the flex-1 parent handles sizing;
            the SVG still needs an explicit width attribute so it doesn't collapse to 0. */}
        <svg
          viewBox={`0 0 100 ${height}`}
          width="100%"
          height={height}
          preserveAspectRatio="none"
          aria-hidden="true"
          className={showAxis ? "flex-1" : undefined}
        >
          {/* WHY currentColor + className on <svg>: lets the stroke inherit the
              Tailwind text color class applied to the SVG element, avoiding
              hardcoded hex values in SVG attributes. */}
          <polyline
            points={polylinePoints}
            fill="none"
            className={`stroke-current ${trendClass}`}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" // WHY: keeps 1.5px stroke regardless of viewBox scale
          />
        </svg>

        {/* ── T-F-6-07: Right Y-axis — max at top, min at bottom ───────────── */}
        {/* WHY justify-between on a flex-col: pushes max label to the top of the
            SVG height and min label to the bottom without needing absolute positioning.
            WHY w-[28px] shrink-0: "999M" (4 chars × ~6px) = ~24px; 28px gives 4px
            breathing room and keeps all labels left-edge aligned regardless of digits.
            WHY tabular-nums: ensures digit widths are consistent so "88.5" and "12.0"
            appear the same width — avoids jitter as the metric selector changes. */}
        {showAxis && (
          <div
            className="flex flex-col justify-between shrink-0 w-[28px] ml-0.5"
            style={{ height: `${height}px` }}
            aria-hidden="true"
          >
            {/* Max value — top of the Y range */}
            <span className="font-mono text-[8px] tabular-nums text-muted-foreground leading-none">
              {yMaxLabel}
            </span>
            {/* Min value — bottom of the Y range */}
            <span className="font-mono text-[8px] tabular-nums text-muted-foreground leading-none">
              {yMinLabel}
            </span>
          </div>
        )}
      </div>

      {/* ── Optional x-axis labels — year ticks: first and last YYYY-MM date ─ */}
      {/* T-F-6-07: these are the "year ticks" for the x-axis.
          WHY YYYY-MM (not full ISO): the sidebar column is ~220px wide after the
          Y-axis column; "2024-01" (7 chars at 9px mono) fits cleanly at both ends. */}
      {showAxis && (firstDate || lastDate) && (
        <div className="flex justify-between mt-0.5">
          <span className="font-mono text-[9px] text-muted-foreground">
            {firstDate ? firstDate.slice(0, 7) : ""} {/* YYYY-MM */}
          </span>
          <span className="font-mono text-[9px] text-muted-foreground">
            {lastDate ? lastDate.slice(0, 7) : ""}
          </span>
        </div>
      )}
    </div>
  );
}
