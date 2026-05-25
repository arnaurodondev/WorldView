/**
 * components/primitives/Sparkline.tsx — 40×16 trend-tinted single-path SVG
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — every watchlist row, holdings row,
 * top-movers card, peer-comparison sparkline shares one rendering. Inline
 * SVG path (no chart library) is the fastest possible render for hundreds
 * of mini-charts on one page (Holdings panel ~50, Screener ~240, Watchlist
 * ~12). Pure functional component — no client hooks, SSR-friendly.
 * WHO USES IT: Dashboard top-movers, Watchlist, Holdings sparkline column,
 *   Quote tab tiny-trend, Peer Comparison.
 * DATA SOURCE: Caller passes a number[] (typically close prices from
 *   /v1/instruments/{ticker}/sparkline-points). No internal fetching.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (Sparkline row); plan FU-5.6 — trend
 *   colour drives sentiment (positive green / negative red / flat muted),
 *   NOT primary yellow.
 *
 * TREND="auto" THRESHOLD: ±0.1% first-vs-last value (plan locked decision).
 *   first=100, last=99.9 → flat. first=100, last=101 → positive.
 *   first=100, last=98 → negative. Use semantic `trend` prop when caller
 *   already knows direction (avoids a second pass over the array).
 */

import type { ReactNode } from "react";

interface SparklineProps {
  /** Series points (typically daily closes). Need ≥2 to render a line. */
  readonly data: number[];
  /** SVG width in px. Defaults to 40 (tight enough for any dense row). */
  readonly width?: number;
  /** SVG height in px. Defaults to 16. */
  readonly height?: number;
  /** Color tint. "auto" computes from first-vs-last delta (±0.1% threshold). */
  readonly trend?: "auto" | "positive" | "negative" | "flat";
  /** Aria-label for screen readers. */
  readonly label?: string;
}

/** Resolve trend="auto" to one of positive|negative|flat via ±0.1% rule. */
function autoTrend(data: number[]): "positive" | "negative" | "flat" {
  if (data.length < 2) return "flat";
  const first = data[0];
  const last = data[data.length - 1];
  if (first === undefined || last === undefined || first === 0) return "flat";
  const pct = ((last - first) / first) * 100;
  if (pct >= 0.1) return "positive";
  if (pct <= -0.1) return "negative";
  return "flat";
}

// WHY currentColor on the path (not a fill prop): the wrapper <svg> sets
// text-positive / text-negative / text-muted-foreground via Tailwind, and
// the path inherits via stroke="currentColor". One token surface.
const TREND_CLASS: Record<"positive" | "negative" | "flat", string> = {
  positive: "text-positive",
  negative: "text-negative",
  flat: "text-muted-foreground",
};

export function Sparkline({
  data,
  width = 40,
  height = 16,
  trend = "auto",
  label,
}: SparklineProps): ReactNode {
  // Empty/short series — render the dotted-line loading skeleton equivalent.
  // Finance UX: never render a blank box where data is expected.
  if (data.length < 2) {
    return (
      <svg width={width} height={height} role="img" aria-label={label ?? "no data"}>
        <line
          x1={0}
          x2={width}
          y1={height / 2}
          y2={height / 2}
          stroke="currentColor"
          strokeDasharray="2 2"
          className="text-muted-foreground/30"
        />
      </svg>
    );
  }

  const resolvedTrend = trend === "auto" ? autoTrend(data) : trend;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1; // avoid divide-by-zero on flat series
  const stepX = width / (data.length - 1);
  // Build the `M x1 y1 L x2 y2 …` path.  Single pass, no allocations beyond
  // the points array — keeps render cheap for 240+ sparklines per page.
  const points = data
    .map((v, i) => `${i * stepX},${height - ((v - min) / range) * height}`)
    .join(" L ");
  return (
    <svg width={width} height={height} role="img" aria-label={label ?? "trend"} className={TREND_CLASS[resolvedTrend]}>
      <path d={`M ${points}`} fill="none" stroke="currentColor" strokeWidth={1} />
    </svg>
  );
}
