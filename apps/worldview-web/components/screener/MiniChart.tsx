/**
 * components/screener/MiniChart.tsx — 18px tall inline sparkline (pure SVG)
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-09): The screener row needs a glance-able
 * trend indicator. Reading "+1.24%" tells you today; a 30-day sparkline tells
 * you context (rallying off a low? reversion? long bull run?).
 *
 * WHY PURE SVG (not Lightweight Charts, not Recharts):
 *   - 30 points, no axis, no interaction, no zoom — Lightweight Charts is
 *     overkill (~150KB gzipped, full chart engine) for this use case.
 *   - Recharts is React-component-tree heavy (each chart spawns a Surface +
 *     XAxis + YAxis virtual DOM tree even when invisible). For 50 rows that
 *     is 50 chart trees → measurable jank on first render.
 *   - Pure SVG: a single <path> + <polyline>, zero JS computation cost. The
 *     entire component is ~30 lines of geometry maths and renders in <1ms
 *     even for a hundred rows.
 *   - SVG also scales perfectly for high-DPI displays (no canvas blur).
 *
 * WHY hardcoded 18px height:
 *   - PRD-0031 §0.2 mandates 22px row height. 18px chart leaves 2px padding
 *     top + bottom — exactly what a Bloomberg row looks like.
 *
 * WHY width auto-fill (preserveAspectRatio="none"):
 *   - The screener column has a known fixed width. We let the SVG stretch
 *     to fill it horizontally so 30 points always span the full cell.
 *   - "none" trades aspect-ratio fidelity for column fit. Acceptable here:
 *     this is a directional indicator, not a precise time-series read.
 *
 * WHY positive/negative coloured by FIRST vs LAST close:
 *   - Mirrors how every terminal sparkline works (Bloomberg, Refinitiv,
 *     TradingView). It is the cumulative period return signal — what the
 *     user wants to know at a glance.
 *
 * WHO USES IT: components/screener/ScreenerTable.tsx (sparkline column)
 */

import { useMemo } from "react";
import type { OHLCVBar } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface MiniChartProps {
  /**
   * 30 daily OHLCV bars. Older first → newer last. We close-only here.
   *
   * WHY OHLCVBar (not just number[]):
   *   - The screener fetches OHLCV via getBatchOhlcvBars; consumers should
   *     not need to pre-extract `close`. Letting MiniChart take the raw bar
   *     keeps call sites short and avoids a duplicate map() at every row.
   */
  bars: readonly OHLCVBar[] | null | undefined;
  /** Optional explicit width override; default auto-stretches via CSS. */
  width?: number;
  /** Optional explicit height override; default 18px (designed for 22px rows). */
  height?: number;
  /** Optional aria-label for screen readers. */
  ariaLabel?: string;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * MiniChart — renders a 30-point sparkline (or empty placeholder if no data).
 *
 * EMPTY STATE: when bars is null/undefined/[]/single-point we render a flat
 * neutral line. WHY: a totally empty cell would mis-align the row. A subtle
 * grey line communicates "no data yet" without breaking the layout.
 */
export function MiniChart({
  bars,
  width = 60,
  height = 18,
  ariaLabel,
}: MiniChartProps) {
  // WHY useMemo: path computation runs on every parent re-render. The screener
  // re-renders frequently (TanStack Query fetches, sort changes). Memoising on
  // bars reference keeps render cost effectively zero across renders.
  const { path, color, valid } = useMemo(() => {
    if (!bars || bars.length < 2) {
      return { path: "", color: "var(--muted-foreground)", valid: false };
    }

    const closes = bars.map((b) => b.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1; // WHY: avoid divide-by-zero on flat series

    // WHY 1px stroke-aware padding: stroke is centered on the path; without
    // padding, peaks at exactly min/max get clipped at the SVG edge.
    const pad = 1;
    const innerHeight = height - pad * 2;
    const innerWidth = width - pad * 2;
    const step = innerWidth / (closes.length - 1);

    // Build an SVG path string: M x0,y0 L x1,y1 L x2,y2 ...
    // WHY <path d="M..L..L.."> (not <polyline points="...">):
    //   - Both work; <path> is the institutional convention because it
    //     extends naturally to area-fills later (M..L..Z).
    let d = "";
    for (let i = 0; i < closes.length; i++) {
      const x = pad + i * step;
      // WHY (max - close): SVG y axis points DOWN (0 is top). Inverting puts
      // higher prices at the top of the chart — what users expect.
      const y = pad + ((max - closes[i]) / range) * innerHeight;
      d += `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    }

    // WHY first vs last (not max vs min): see file-level WHY.
    const first = closes[0];
    const last = closes[closes.length - 1];
    let strokeColor: string;
    if (last > first) strokeColor = "var(--positive)";
    else if (last < first) strokeColor = "var(--negative)";
    else strokeColor = "var(--muted-foreground)";

    return { path: d, color: strokeColor, valid: true };
  }, [bars, width, height]);

  // ── Empty / insufficient-data render ───────────────────────────────────────
  if (!valid) {
    // WHY a flat grey line (not nothing): preserves row height, signals "no data".
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel ?? "No trend data available"}
        data-testid="mini-chart-empty"
      >
        <line
          x1={1}
          x2={width - 1}
          y1={height / 2}
          y2={height / 2}
          stroke="var(--muted-foreground)"
          strokeOpacity={0.3}
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel ?? "30-day price trend"}
      data-testid="mini-chart"
      data-direction={
        // Expose the trend direction as a data attribute so tests can assert
        // colour without parsing inline SVG styles.
        color === "var(--positive)" ? "positive" : color === "var(--negative)" ? "negative" : "flat"
      }
    >
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={1}
        // WHY round joins/caps: smoother line at the few pixel-level kinks
        // a 30-point series produces; consistent with the chart styling
        // we already use in lightweight-charts.
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
