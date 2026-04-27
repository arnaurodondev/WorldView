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
   * When true, renders the first and last as_of_date as x-axis labels.
   * Default false — labels add vertical space; omit for dense sidebar use.
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

  return (
    <div className={`w-full ${className}`}>
      {/* ── SVG sparkline — viewBox: 0 0 100 HEIGHT keeps proportions constant ── */}
      {/* WHY preserveAspectRatio none: we want the SVG to stretch to fill the
          container width while keeping the fixed height — standard sparkline behaviour. */}
      <svg
        viewBox={`0 0 100 ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        aria-hidden="true"
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

      {/* ── Optional x-axis labels — first and last date ──────────────────── */}
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
