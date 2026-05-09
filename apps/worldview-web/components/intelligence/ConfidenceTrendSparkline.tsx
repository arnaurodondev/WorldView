/**
 * components/intelligence/ConfidenceTrendSparkline.tsx — Confidence trend mini-chart
 * (PLAN-0074 Wave H T-H-05)
 *
 * WHY THIS EXISTS: A sparkline gives the confidence score a temporal dimension.
 * Seeing that confidence has been rising from 0.45→0.78 over 30 days tells a
 * different story than just seeing "confidence: 0.78". Used in the entity sidebar.
 *
 * WHY HAND-ROLLED SVG POLYLINE (not a chart library):
 * This component MUST mirror the pattern in FundamentalSparkline.tsx exactly.
 * The reason is stated in the codebase rule: sparklines are purely decorative
 * trend indicators — no tooltips, axes, or interactions needed. A self-contained
 * SVG with a computed polyline is 0 bytes of additional dependency and renders
 * synchronously. recharts is NOT allowed (removed from package.json).
 *
 * PATTERN MATCH: The buildPolylinePoints function is copied exactly from
 * FundamentalSparkline.tsx to guarantee visual and behavioral consistency.
 * The color logic (positive/negative/flat) is also identical.
 *
 * WHO USES IT: EntitySidebar confidence section
 * DATA SOURCE: confidence_breakdown.confidence_trend from useEntityIntelligence
 */

// WHY no "use client": this component accepts data as props (no hooks).
// The parent (EntitySidebar) fetches and passes the data — this is pure display.

import { Skeleton } from "@/components/ui/skeleton";
import type { ConfidenceTrendPoint } from "@/types/intelligence";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ConfidenceTrendSparklineProps {
  /** Array of date/score data points from confidence_breakdown.confidence_trend */
  data: ConfidenceTrendPoint[];
  /** SVG height in pixels. Default 40 — compact for sidebar. */
  height?: number;
  /** Additional className for the root wrapper */
  className?: string;
  /** When true, renders a loading skeleton instead of the sparkline */
  isLoading?: boolean;
}

// ── SVG sparkline helpers — IDENTICAL to FundamentalSparkline.tsx ─────────────

/**
 * buildPolylinePoints — convert (index, value) pairs to SVG polyline points string.
 *
 * WHY this is copied (not imported) from FundamentalSparkline.tsx:
 * The function is a pure utility with no dependencies. Importing it would
 * require exporting it from FundamentalSparkline.tsx (changing its public API).
 * Co-locating keeps this component self-contained and avoids coupling two
 * visually independent sparklines to each other.
 *
 * The algorithm is identical: map index to x=0–100 (viewBox %), invert y so
 * higher confidence appears at the top, add 2px padding top + bottom.
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
      // WHY invert y: SVG y=0 is top; higher confidence should appear at top
      const y =
        range === 0
          ? height / 2 // flat line for constant confidence
          : height - ((v - minVal) / range) * (height - 4) - 2; // 2px padding
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ConfidenceTrendSparkline({
  data,
  height = 40,
  className = "",
  isLoading = false,
}: ConfidenceTrendSparklineProps) {
  // Loading state — skeleton matching the sparkline dimensions
  if (isLoading) {
    return (
      <div className={`w-full ${className}`}>
        <Skeleton className="w-full rounded-[2px]" style={{ height: `${height}px` }} />
      </div>
    );
  }

  // Sort ascending — data may come in any order from the API
  const points = [...data].sort((a, b) => a.date.localeCompare(b.date));
  const values = points.map((p) => p.avg_confidence);

  // Error / empty state — render a placeholder line, NOT nothing.
  // WHY placeholder (not null): keeps layout stable across loading/error/success.
  if (values.length < 2) {
    return (
      <div
        className={`w-full flex items-center justify-center text-muted-foreground text-[10px] font-mono ${className}`}
        style={{ height: `${height}px` }}
      >
        —
      </div>
    );
  }

  // Trend color — compare first vs last data point
  // WHY first→last (not min→max): we want the DIRECTION of change, not the distance.
  const firstVal = values[0];
  const lastVal = values[values.length - 1];
  const trendClass =
    lastVal > firstVal
      ? "text-positive"           // confidence rising — #26A69A
      : lastVal < firstVal
      ? "text-negative"           // confidence falling — #EF5350
      : "text-muted-foreground";  // flat — no change

  const polylinePoints = buildPolylinePoints(values, height);

  return (
    <div className={`w-full ${className}`}>
      {/* WHY viewBox="0 0 100 HEIGHT" + preserveAspectRatio="none":
          Keeps the chart proportions constant regardless of rendered pixel width.
          The SVG stretches to fill the container width. Same as FundamentalSparkline. */}
      <svg
        viewBox={`0 0 100 ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        aria-hidden="true"
        aria-label={`Confidence trend: ${firstVal.toFixed(2)} → ${lastVal.toFixed(2)}`}
      >
        {/* WHY currentColor + className on SVG: lets the stroke inherit the
            Tailwind text color class (trendClass) without hardcoded hex values. */}
        <polyline
          points={polylinePoints}
          fill="none"
          className={`stroke-current ${trendClass}`}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          // WHY vectorEffect="non-scaling-stroke": keeps the 1.5px stroke width
          // constant regardless of viewBox scale. Same as FundamentalSparkline.
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}
