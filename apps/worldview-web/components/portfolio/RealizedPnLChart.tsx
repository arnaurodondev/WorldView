/**
 * components/portfolio/RealizedPnLChart.tsx — Cumulative realized P&L chart (PLAN-0053 T-D-4-03)
 *
 * WHY THIS EXISTS: PLAN-0051 Wave A shipped the FIFO-accounting realized P&L
 * endpoint with full per-instrument breakdown — but only the KPI strip's
 * single-number summary surfaces it today. A chart over time tells a richer
 * story: "did I make money in Q1 from one big winner, or steady $50/day?".
 *
 * WHY CUMULATIVE LINE (not bars): cumulative shows trajectory — the slope
 * shows the rate of P&L generation; cliffs show big realisation events.
 * Bars over months would lose that "running total" semantic.
 *
 * WHY 1M / 3M / 6M / 1Y / All:
 *   Same period set as the equity-curve chart so the user gets a consistent
 *   mental model across the analytics section. Each period maps to a "from"
 *   ISO date; "All" uses no from-bound and lets the backend default.
 *
 * WHY PER-TICKER TABLE BELOW THE CHART:
 *   The endpoint returns `breakdown_by_instrument` — surfacing the top
 *   contributors / detractors answers "where did this P&L come from?" which
 *   is the natural follow-up question after seeing the line.
 *
 * WHO USES IT: portfolio/page.tsx — Holdings tab (mountable below KPI strip)
 * DATA SOURCE: getRealizedPnL(portfolioId, from?, to?)
 * DESIGN REFERENCE: PLAN-0053 §T-D-4-03
 */

"use client";
// WHY "use client": SVG hover state via useState + useMemo on derived
// chart points + useQuery (TanStack Query is a client-only hook).
//
// PLAN-0059 G-1 finish (2026-05-02): migrated off recharts to hand-rolled
// SVG. The chart renders only two points (period start at 0 → period end at
// total_realized) — recharts' LineChart + Tooltip + Grid + ReferenceLine
// pulled the entire library for what is geometrically a line + a dashed
// horizontal rule. Hand-rolled SVG keeps the visual identical with zero
// chart-engine surface area.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatPrice, cn } from "@/lib/utils";

// ── Props / Types ────────────────────────────────────────────────────────────

export interface RealizedPnLChartProps {
  portfolioId: string | null | undefined;
}

type Period = "1M" | "3M" | "6M" | "1Y" | "All";

// Deterministic period → days mapping. Keeping it as a constant lets us
// build the "from" date with a single subtraction.
const PERIOD_DAYS: Record<Exclude<Period, "All">, number> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
};

// ── Component ────────────────────────────────────────────────────────────────

export function RealizedPnLChart({ portfolioId }: RealizedPnLChartProps) {
  const { accessToken } = useAuth();
  const [period, setPeriod] = useState<Period>("1Y");

  // Derive "from" ISO date from the active period. WHY compute on render:
  // useState would over-engineer this — the value is a pure function of
  // `period` and Date.now(); recomputing per render is cheaper than
  // memoising. Date math wraps automatically.
  const fromIso = useMemo(() => {
    if (period === "All") return undefined;
    const days = PERIOD_DAYS[period];
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
  }, [period]);

  const { data, isLoading } = useQuery({
    queryKey: ["realized-pnl-chart", portfolioId, fromIso],
    queryFn: () => createGateway(accessToken).getRealizedPnL(portfolioId!, fromIso),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // The endpoint returns aggregated totals, not per-day points — so we don't
  // get a true line chart from the response alone. We build a synthetic
  // 2-point series (from → to with the cumulative endpoint at "to") to
  // visualise the bracket. WHY this is good enough: the realised-pnl
  // endpoint is a closed accounting cut, not a daily series; the slope is
  // implicit in the period selector. A future T-D-4-03+ could extend the
  // backend to return a per-day breakdown for a true cumulative trace.
  const chartPoints = useMemo(() => {
    if (!data) return [];
    const start = data.from || fromIso || "";
    const end = data.to;
    return [
      { date: start, cumulative: 0 },
      { date: end, cumulative: data.total_realized },
    ];
  }, [data, fromIso]);

  if (!portfolioId) return null;

  return (
    <div className="flex flex-col bg-background" data-testid="realized-pnl-chart">
      {/* Header — title + period buttons + total readout */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-border px-2">
        <span
          className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground"
          title="Backend currently returns period totals only — chart shows the cumulative bracket (start → end). Per-day series will land in a follow-up plan."
        >
          REALIZED P&L
          <sup className="ml-0.5 text-[8px] text-muted-foreground/70">ⓘ</sup>
        </span>

        <div className="flex gap-px">
          {(["1M", "3M", "6M", "1Y", "All"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={period === p}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      {isLoading && (
        <div className="space-y-1 p-2">
          <Skeleton className="h-[140px] w-full" />
          <Skeleton className="h-[22px] w-full" />
        </div>
      )}

      {!isLoading && data && data.count === 0 && (
        <div className="px-3 py-3">
          <InlineEmptyState message="No realized P&L in this period" />
        </div>
      )}

      {!isLoading && data && data.count > 0 && (
        <>
          {/* Total badge above the chart */}
          <div className="flex items-center gap-3 border-b border-border/30 px-2 py-1.5">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              TOTAL
            </span>
            <span
              className={cn(
                "font-mono text-[12px] font-semibold tabular-nums",
                data.total_realized >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {data.total_realized >= 0 ? "+" : ""}
              {formatPrice(data.total_realized)}
            </span>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
              ({data.count} {data.count === 1 ? "lot" : "lots"})
            </span>
            <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
              LT {formatPrice(data.realized_long_term)} · ST{" "}
              {formatPrice(data.realized_short_term)}
            </span>
          </div>

          {/* Chart — hand-rolled SVG (PLAN-0059 G-1 finish) */}
          <div className="h-[160px] px-2 py-1">
            <RealizedPnLLine
              chartPoints={chartPoints}
              isPositive={data.total_realized >= 0}
            />
          </div>

          {/* Per-ticker breakdown table — top contributors & detractors */}
          {data.breakdown_by_instrument.length > 0 && (
            <div className="border-t border-border/40">
              <div className="flex h-6 items-center border-b border-border/30 px-2">
                <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                  BY INSTRUMENT
                </span>
              </div>
              <table className="w-full border-collapse text-[11px]">
                <tbody className="divide-y divide-border/30">
                  {data.breakdown_by_instrument.slice(0, 10).map((row) => (
                    <tr key={row.instrument_id} className="h-7 hover:bg-muted/30">
                      {/* WHY font-semibold (was font-bold): 700-weight at 11px causes blotchy
                          subpixel rendering on dark themes — 600-weight is the maximum for
                          terminal chrome text at small sizes (Bloomberg density rule) */}
                      <td className="px-2 font-mono text-[11px] font-semibold tabular-nums text-primary">
                        {row.ticker || "—"}
                      </td>
                      <td className="px-2 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                        {row.count} {row.count === 1 ? "lot" : "lots"}
                      </td>
                      <td
                        className={cn(
                          "px-2 text-right font-mono text-[11px] tabular-nums",
                          row.realized >= 0 ? "text-positive" : "text-negative",
                        )}
                      >
                        {row.realized >= 0 ? "+" : ""}
                        {formatPrice(row.realized)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Inner SVG line chart ─────────────────────────────────────────────────────
//
// WHY EXTRACTED: keeps the hover-tooltip useState close to the SVG it controls
// and out of the data-fetching wrapper. The chart is a 2-point bracket
// (period start → period end) over a Y axis that includes 0 as a hard datum
// so the user sees positive vs negative at a glance.

interface ChartPoint {
  date: string;
  cumulative: number;
}

const VIEW_W = 480;
const VIEW_H = 160;
const M_TOP = 8;
const M_BOTTOM = 18; // X-axis labels
const M_LEFT = 50; // Y-axis labels need width; matches recharts width=50
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

function RealizedPnLLine({
  chartPoints,
  isPositive,
}: {
  chartPoints: ChartPoint[];
  isPositive: boolean;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Defensive: if for any reason the wrapper passes <2 points, render a
  // baseline-only chart rather than crashing the panel.
  if (chartPoints.length < 2) {
    return null;
  }

  // Y-scale must include 0 (zero baseline is meaningful for P&L) and the
  // cumulative value. We pad the range by 10% so the line never touches the
  // top/bottom of the plot — a Bloomberg convention for readable lines.
  const values = chartPoints.map((p) => p.cumulative);
  const dataMin = Math.min(0, ...values);
  const dataMax = Math.max(0, ...values);
  const pad = Math.max(0.5, (dataMax - dataMin) * 0.1);
  const yMin = dataMin - pad;
  const yMax = dataMax + pad;
  const yRange = Math.max(0.01, yMax - yMin);

  // Geometry helpers. xAt distributes points evenly; yAt maps a value into
  // the plot rectangle.
  const xAt = (i: number) =>
    M_LEFT + (i / (chartPoints.length - 1)) * PLOT_W;
  const yAt = (v: number) =>
    M_TOP + PLOT_H - ((v - yMin) / yRange) * PLOT_H;
  const yZero = yAt(0);

  // Polyline path. The chart only has 2 points so this is a single L command,
  // but writing it as a loop keeps the migration cleanly extensible if the
  // backend ever grows a per-day series (T-D-4-03 follow-up).
  const linePath = chartPoints
    .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)} ${yAt(p.cumulative).toFixed(1)}`)
    .join(" ");

  // Y-axis label values: yMin / 0 / yMax. Including 0 explicitly is the whole
  // point of the chart. We round to whole-dollar amounts.
  const yLabels = [yMin, 0, yMax].map((v) => Math.round(v));

  // X-axis labels — period start (left) and period end (right).
  const xLabelStart = chartPoints[0].date.slice(0, 10);
  const xLabelEnd = chartPoints[chartPoints.length - 1].date.slice(0, 10);

  // Stroke colour follows the prior recharts behaviour: green when net
  // positive, red when net negative.
  const stroke = isPositive ? "hsl(var(--positive))" : "hsl(var(--negative))";

  return (
    <div className="relative h-full w-full">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        height="100%"
        preserveAspectRatio="none"
        role="img"
        aria-label="Realized P&L cumulative line"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* Horizontal grid lines at the three Y-label values — dashed
            replicates the prior CartesianGrid look. */}
        {yLabels.map((v) => (
          <line
            key={`grid-${v}`}
            x1={M_LEFT}
            x2={M_LEFT + PLOT_W}
            y1={yAt(v)}
            y2={yAt(v)}
            stroke="hsl(var(--border) / 0.4)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        ))}

        {/* Y-axis labels — right-aligned just inside the left margin. */}
        {yLabels.map((v) => (
          <text
            key={`ylabel-${v}`}
            x={M_LEFT - 4}
            y={yAt(v) + 3}
            fill="currentColor"
            fontSize={10}
            textAnchor="end"
            className="text-muted-foreground"
          >
            ${v}
          </text>
        ))}

        {/* Zero baseline — solid (slightly heavier than the dashed grid)
            because positive vs negative is the whole point of the chart. */}
        <line
          x1={M_LEFT}
          x2={M_LEFT + PLOT_W}
          y1={yZero}
          y2={yZero}
          stroke="hsl(var(--border))"
          strokeWidth={1}
        />

        {/* The line itself. */}
        <path
          d={linePath}
          fill="none"
          stroke={stroke}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Endpoint dots — match the recharts dot={{r:3}} look. */}
        {chartPoints.map((p, i) => (
          <circle
            key={`dot-${i}`}
            cx={xAt(i)}
            cy={yAt(p.cumulative)}
            r={3}
            fill={stroke}
          />
        ))}

        {/* X-axis labels — start and end dates. */}
        <text
          x={M_LEFT}
          y={VIEW_H - 4}
          fill="currentColor"
          fontSize={10}
          textAnchor="start"
          className="text-muted-foreground"
        >
          {xLabelStart}
        </text>
        <text
          x={M_LEFT + PLOT_W}
          y={VIEW_H - 4}
          fill="currentColor"
          fontSize={10}
          textAnchor="end"
          className="text-muted-foreground"
        >
          {xLabelEnd}
        </text>

        {/* Per-point hit areas around each dot for hover tooltip. We use a
            generous 20px-wide invisible rectangle so users can tooltip-target
            without pixel-hunting the 3px dot. */}
        {chartPoints.map((_, i) => (
          <rect
            key={`hit-${i}`}
            x={xAt(i) - 10}
            y={M_TOP}
            width={20}
            height={PLOT_H}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}
      </svg>

      {hoverIdx !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-[2px] border border-border bg-card px-2 py-1 font-mono text-[11px]"
          style={{
            // Convert the SVG x-coordinate back to a percentage of the wrapper
            // width so the tooltip tracks even after CSS resize.
            left: `${(xAt(hoverIdx) / VIEW_W) * 100}%`,
            top: 4,
          }}
          role="tooltip"
        >
          <div className="text-muted-foreground">
            {chartPoints[hoverIdx].date.slice(0, 10)}
          </div>
          <div className={isPositive ? "text-positive" : "text-negative"}>
            {formatPrice(chartPoints[hoverIdx].cumulative)}
          </div>
        </div>
      )}
    </div>
  );
}
