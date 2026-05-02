/**
 * components/instrument/RevenueTrendSparklines.tsx — Revenue + EPS trend chart
 *
 * WHY THIS EXISTS: A single YoY growth percentage hides the trajectory — is the
 * company accelerating or decelerating? Analysts need quarterly revenue bars and
 * an EPS line overlay to spot multi-quarter trends that a point-in-time figure
 * cannot show. Bloomberg DES shows revenue trend above the metrics grid.
 *
 * RENDER ENGINE (PLAN-0059 G-1, 2026-05-02): hand-rolled SVG. Recharts is
 * being phased out across the app; this surface previously imported
 * `ComposedChart`/`Bar`/`Line`/`XAxis`/`Tooltip`/`ResponsiveContainer`
 * (~50KB gz of recharts). The chart is a 120px-tall categorical bars + line
 * overlay over 12 quarters — too small to justify a chart library, and
 * lightweight-charts (the canonical replacement for time-series) is awkward
 * for categorical labels like `Q1'24` / `FY24`. Hand-rolled SVG is ~150 LOC
 * total, zero dependency footprint, and renders identically across browsers.
 *
 * WHY DUAL SERIES (revenue + EPS): Revenue shows growth scale; EPS shows whether
 * that growth is translating to bottom-line profit. Both together reveal margin
 * compression or expansion. Analysts check these in tandem (Bloomberg "CN" page).
 *
 * WHY QUARTERLY FIRST, ANNUAL FALLBACK: Quarterly bars reveal intra-year patterns
 * (seasonality, one-time charges) that annual bars smooth over. Annual is the
 * fallback for companies where S3 only has annual fundamentals data.
 *
 * WHY NO Y-AXIS LABELS: At 120px chart height, Y-axis labels crowd the bars.
 * Hover tooltips provide exact values. The chart's primary purpose is trend
 * direction, not exact values — that's what the MetricRow grid is for.
 *
 * WHO USES IT: FundamentalsTab.tsx (full-width section above metrics grid)
 * DATA SOURCE: S9 GET /v1/fundamentals/timeseries (via getFundamentalsTimeseries)
 * DESIGN REFERENCE: PLAN-0041 §T-D-1-02
 */

"use client";
// WHY "use client": uses useQuery for two timeseries fetches and useState
// for the hover-tooltip index.

import { useMemo, useState } from "react"; // useMemo retained for chartData merge
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import type { TimeseriesDataPoint } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface RevenueTrendSparklinesProps {
  /** Instrument ID for timeseries fetches */
  instrumentId: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatQuarterLabel — convert an ISO date string to "Q1'24" format
 *
 * WHY this function: the timeseries endpoint returns raw ISO dates
 * ("2024-03-31"). Analysts expect Bloomberg-style quarter labels.
 */
function formatQuarterLabel(dateStr: string): string {
  // T00:00:00Z forces UTC parsing — without it, "2024-03-31" parses as local
  // midnight and shifts to "2024-03-30" in UTC-offset locales.
  const date = new Date(dateStr + "T00:00:00Z");
  const month = date.getUTCMonth();
  const year = date.getUTCFullYear();
  const quarter = Math.floor(month / 3) + 1;
  return `Q${quarter}'${String(year).slice(2)}`;
}

function formatAnnualLabel(dateStr: string): string {
  const date = new Date(dateStr + "T00:00:00Z");
  return `FY${String(date.getUTCFullYear()).slice(2)}`;
}

/**
 * revenueToB — convert raw revenue value (units) to billions for display.
 * Fundamentals values come from S3 in absolute units (e.g. 81_797_000_000).
 */
function revenueToB(value: number | null): number | null {
  if (value == null) return null;
  return Math.round((value / 1e9) * 10) / 10;
}

// ── Chart color constants ─────────────────────────────────────────────────────
// Hex literals match the Bloomberg-yellow + positive-teal tokens; SVG fill
// attributes don't resolve CSS variables.

const COLOR_REVENUE_FILL = "rgba(255, 214, 10, 0.25)"; // primary @ 25%
const COLOR_REVENUE_STROKE = "#FFD60A";
const COLOR_EPS_LINE = "#26A69A";

// SVG viewport — fixed 480×120 with internal margins. The outer wrapper sets
// width:100% and preserveAspectRatio so it scales to the panel width while
// keeping the bar/line geometry rigorous.
const VIEW_W = 480;
const VIEW_H = 120;
const M_TOP = 8;
const M_BOTTOM = 14; // extra room for the X-axis tick labels
const M_LEFT = 8;
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

// ── Merged data shape ─────────────────────────────────────────────────────────

interface ChartPoint {
  date: string;
  label: string;
  revenue: number | null; // billions
  eps: number | null; // dollars
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RevenueTrendSparklines({
  instrumentId,
}: RevenueTrendSparklinesProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // 5-min staleTime — fundamentals timeseries updates daily at most.
  // limit=12 → 3 years of quarterlies → ~12 bars at 480px is readable.
  const { data: revenueTsResp, isLoading: revenueLoading } = useQuery({
    queryKey: ["fundamentals-ts", instrumentId, "revenue"],
    queryFn: () =>
      gateway.getFundamentalsTimeseries(instrumentId, "revenue", {
        period_type: "QUARTERLY",
        limit: 12,
      }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 300_000,
  });

  // Independent EPS query — S9 timeseries is per-metric; loading state
  // shouldn't couple revenue failure to EPS rendering.
  const { data: epsTsResp, isLoading: epsLoading } = useQuery({
    queryKey: ["fundamentals-ts", instrumentId, "earnings_per_share"],
    queryFn: () =>
      gateway.getFundamentalsTimeseries(instrumentId, "earnings_per_share", {
        period_type: "QUARTERLY",
        limit: 12,
      }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 300_000,
  });

  const revenuePoints: TimeseriesDataPoint[] = revenueTsResp?.data ?? [];
  const epsPoints: TimeseriesDataPoint[] = epsTsResp?.data ?? [];

  // Some companies only have ANNUAL data; switch the X-axis label format
  // when the API returns annual records.
  const firstPeriodType = revenuePoints[0]?.period_type ?? "QUARTERLY";
  const isAnnual = firstPeriodType === "ANNUAL";
  const formatLabel = isAnnual ? formatAnnualLabel : formatQuarterLabel;

  // Merge on the revenue dates (revenue is the primary series; orphan EPS
  // points without a matching revenue date are dropped).
  const chartData: ChartPoint[] = useMemo(
    () =>
      revenuePoints.map((r) => {
        const matchEps = epsPoints.find(
          (e) => e.as_of_date.slice(0, 10) === r.as_of_date.slice(0, 10),
        );
        return {
          date: r.as_of_date,
          label: formatLabel(r.as_of_date),
          revenue: revenueToB(r.value_numeric),
          eps: matchEps?.value_numeric ?? null,
        };
      }),
    [revenuePoints, epsPoints, formatLabel],
  );

  // Hover tooltip state — index of the bar under the cursor, or null.
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // ── Loading state ──────────────────────────────────────────────────────────
  if (revenueLoading && epsLoading) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            REVENUE TREND
          </span>
        </div>
        <Skeleton className="m-2 h-[120px] rounded-[2px]" />
      </div>
    );
  }

  // Empty state — keep the section header so analysts know the category is
  // tracked even when the data is missing (Bloomberg convention).
  if (chartData.length === 0) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            REVENUE TREND
          </span>
        </div>
        <div className="px-2 py-2 text-[11px] font-mono text-muted-foreground">
          Revenue trend data not available
        </div>
      </div>
    );
  }

  // ── Geometry ────────────────────────────────────────────────────────────────
  // Compute scales over the actual data ranges. Bars and the EPS line share
  // the same X grid (one slot per data point); they have separate Y scales
  // because revenue is in $B and EPS is in $.
  const revenueValues = chartData
    .map((d) => d.revenue)
    .filter((v): v is number => v != null);
  const epsValues = chartData
    .map((d) => d.eps)
    .filter((v): v is number => v != null);

  // For a single value or all-zero series, fall back to a 1-unit range so we
  // don't divide by zero.
  const revMax = Math.max(1, ...revenueValues);
  const epsMin = epsValues.length ? Math.min(...epsValues) : 0;
  const epsMax = epsValues.length ? Math.max(...epsValues) : 1;
  const epsRange = Math.max(0.01, epsMax - epsMin);

  // Each data point owns a vertical slot of width slotW; bars fill ~70% of
  // the slot to leave breathing room. Min(40px, slotW*0.7) caps width when
  // we have only 4-6 annual bars so they don't span the whole panel.
  const slotW = PLOT_W / chartData.length;
  const barW = Math.min(40, slotW * 0.7);

  const xCenter = (i: number) => M_LEFT + slotW * i + slotW / 2;
  const yRevenue = (v: number) => M_TOP + PLOT_H - (v / revMax) * PLOT_H;
  const yEps = (v: number) => M_TOP + PLOT_H - ((v - epsMin) / epsRange) * PLOT_H;

  // EPS polyline path — only emits points where eps is non-null. A null EPS
  // gap inside the series creates a Move-To rather than a line break, which
  // matches the prior `connectNulls` behaviour from recharts.
  // WHY plain const (not useMemo): the early-return branches above forbid a
  // hook call here (Rules of Hooks). The loop is O(n=12) string concat —
  // recomputing on every render is essentially free.
  const epsPathParts: string[] = [];
  let epsPathStarted = false;
  for (let i = 0; i < chartData.length; i++) {
    const v = chartData[i].eps;
    if (v == null) continue;
    const cmd = epsPathStarted ? "L" : "M";
    epsPathParts.push(
      `${cmd}${xCenter(i).toFixed(1)} ${yEps(v).toFixed(1)}`,
    );
    epsPathStarted = true;
  }
  const epsPath = epsPathParts.join(" ");

  // X-axis labels: only first + last to avoid crowding.
  const firstLabel = chartData[0].label;
  const lastLabel = chartData[chartData.length - 1].label;

  return (
    <div>
      {/* Section header + inline legend */}
      <div className="flex items-center gap-3 border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          REVENUE TREND
        </span>
        <div className="flex items-center gap-2 ml-auto">
          <div className="flex items-center gap-1">
            <div
              className="h-2 w-3 rounded-[1px]"
              style={{ backgroundColor: COLOR_REVENUE_STROKE, opacity: 0.5 }}
            />
            <span className="text-[9px] text-muted-foreground font-mono">Revenue</span>
          </div>
          <div className="flex items-center gap-1">
            <div
              className="h-0.5 w-3 rounded-full"
              style={{ backgroundColor: COLOR_EPS_LINE }}
            />
            <span className="text-[9px] text-muted-foreground font-mono">EPS</span>
          </div>
        </div>
      </div>

      {/* SVG chart — relative wrapper so the tooltip can absolute-position
          over the hovered bar without leaving the chart bounds. */}
      <div className="relative pb-1" data-testid="revenue-trend-chart">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          width="100%"
          height={VIEW_H}
          preserveAspectRatio="none"
          role="img"
          aria-label="Revenue and EPS trend"
          onMouseLeave={() => setHoverIdx(null)}
        >
          {/* Revenue bars */}
          {chartData.map((d, i) => {
            if (d.revenue == null) return null;
            const x = xCenter(i) - barW / 2;
            const y = yRevenue(d.revenue);
            const h = M_TOP + PLOT_H - y;
            return (
              <rect
                key={`bar-${i}`}
                x={x}
                y={y}
                width={barW}
                height={Math.max(0, h)}
                fill={COLOR_REVENUE_FILL}
                stroke={COLOR_REVENUE_STROKE}
                strokeWidth={1}
              />
            );
          })}

          {/* EPS overlay line — only drawn when at least one point exists */}
          {epsPath && (
            <path
              d={epsPath}
              fill="none"
              stroke={COLOR_EPS_LINE}
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* X-axis labels — first and last only to avoid crowding */}
          <text
            x={xCenter(0)}
            y={VIEW_H - 2}
            fill="currentColor"
            fontSize={9}
            fontFamily="monospace"
            textAnchor="middle"
            className="text-muted-foreground"
          >
            {firstLabel}
          </text>
          {chartData.length > 1 && (
            <text
              x={xCenter(chartData.length - 1)}
              y={VIEW_H - 2}
              fill="currentColor"
              fontSize={9}
              fontFamily="monospace"
              textAnchor="middle"
              className="text-muted-foreground"
            >
              {lastLabel}
            </text>
          )}

          {/* Invisible per-slot hit areas for hover. Wider than the bar
              itself so users don't have to pixel-hunt the ~30px revenue
              bar — the entire slot column is hoverable. */}
          {chartData.map((_, i) => (
            <rect
              key={`hit-${i}`}
              x={M_LEFT + slotW * i}
              y={M_TOP}
              width={slotW}
              height={PLOT_H}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
            />
          ))}

          {/* Hover guide line — light vertical rule at the hovered slot */}
          {hoverIdx !== null && (
            <line
              x1={xCenter(hoverIdx)}
              x2={xCenter(hoverIdx)}
              y1={M_TOP}
              y2={M_TOP + PLOT_H}
              stroke="rgba(255,255,255,0.15)"
              strokeWidth={1}
            />
          )}
        </svg>

        {/* Tooltip — absolute-positioned in CSS pixels (the SVG uses
            preserveAspectRatio=none so a CSS-pixel left = % of viewbox).
            Render only when the cursor is on a slot. */}
        {hoverIdx !== null && (
          <div
            className="pointer-events-none absolute -translate-x-1/2 rounded-[2px] border border-border bg-popover px-2 py-1.5 text-[10px] font-mono"
            style={{
              left: `${(xCenter(hoverIdx) / VIEW_W) * 100}%`,
              top: 4,
            }}
            role="tooltip"
          >
            <p className="mb-0.5 font-medium text-foreground">
              {chartData[hoverIdx].label}
            </p>
            {chartData[hoverIdx].revenue != null && (
              <p className="text-muted-foreground">
                Revenue:{" "}
                <span className="text-primary">
                  ${chartData[hoverIdx].revenue}B
                </span>
              </p>
            )}
            {chartData[hoverIdx].eps != null && (
              <p className="text-muted-foreground">
                EPS:{" "}
                <span className="text-positive">
                  ${chartData[hoverIdx].eps!.toFixed(2)}
                </span>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
