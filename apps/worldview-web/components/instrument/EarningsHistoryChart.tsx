/**
 * components/instrument/EarningsHistoryChart.tsx — Historical EPS chart
 *
 * WHY THIS EXISTS: EPS history is the single most important trailing indicator
 * in fundamental analysis. Analysts check EPS growth trajectory before P/E —
 * a declining EPS with a high P/E is a compression risk; a growing EPS justifies
 * premium multiples. Bloomberg DES shows EPS history in the bottom panel.
 *
 * WHY /earnings-annual-trend (not /earnings-trend or timeseries):
 * - /earnings-trend → forward-looking analyst consensus estimates (period "+1q", "+1y")
 * - /fundamentals/timeseries for earnings_per_share → no data populated for AAPL
 *   (the timeseries table holds computed metrics; EPS is stored as EODHD section data)
 * - /earnings-annual-trend → historical per-fiscal-year EPS actuals stored as
 *   `{date: "YYYY-MM-DD", epsActual: N}` records — confirmed 33 records for AAPL
 *
 * WHY ANNUAL: Quarterly EPS has seasonal patterns that obscure the growth trajectory
 * (e.g., Apple Q4 is always a blowout due to holiday sales). Annual shows the clean
 * year-over-year trend analysts use for valuation. 8 years = one full business cycle.
 *
 * WHY GREEN/GREY COLORING (not beat/miss): Beat vs miss coloring requires matching
 * historical actuals with contemporary estimates — two separate EODHD records that
 * may not align on dates. Positive/negative EPS coloring is the most reliable signal:
 * is the company profitable this year, or not?
 *
 * DATA SHAPE: `gateway.getEarningsHistory(id)` → `{records: [{data: {date, epsActual}}, ...]}`
 * Each record is one fiscal year. Records are ordered most-recent-first from EODHD;
 * we reverse + slice for left-to-right temporal chart display.
 *
 * WHO USES IT: FundamentalsTab left column (Wave D-3), below the metrics grid
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}/earnings-annual-trend
 * DESIGN REFERENCE: PLAN-0041 §T-D-3-01
 */

"use client";
// WHY "use client": uses useQuery for earnings fetch + useState for the
// hover-tooltip index.
//
// PLAN-0059 G-1 (2026-05-02): migrated off recharts to a hand-rolled SVG.
// Rationale identical to RevenueTrendSparklines — this is an 8-bar
// categorical chart at 110px tall; pulling in a chart library for
// rendering 8 rectangles + a tooltip is a needless ~50KB gz tax.
// lightweight-charts is the canonical replacement for time-series, but
// fiscal-year buckets aren't a continuous time axis so it doesn't fit.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ─────────────────────────────────────────────────────────────────────

interface EarningsHistoryChartProps {
  instrumentId: string;
}

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Shape of each record's data field from /earnings-annual-trend.
 *
 * WHY separate interface: `FundamentalsSectionResponse.records[].data` is typed as
 * `Record<string, unknown>` — the DB stores generic JSON. We cast to this interface
 * for typed access. All accesses are null-guarded because the cast is unvalidated.
 */
interface EarningsAnnualRecord {
  date?: string | null;       // Fiscal year end date: "YYYY-MM-DD"
  epsActual?: number | null;  // Diluted EPS actual for the fiscal year
}

// ── Color constants ────────────────────────────────────────────────────────────
// WHY hex (not CSS variables): recharts SVG attributes don't resolve CSS vars.
// --positive: #26A69A (teal green) — profitable year
// --negative: #EF5350 (red) — loss year

const COLOR_POSITIVE = "#26A69A40"; // 25% opacity green — matches OHLCVChart volume bars
const COLOR_POSITIVE_STROKE = "#26A69A";
const COLOR_NEGATIVE = "#EF535040"; // 25% opacity red
const COLOR_NEGATIVE_STROKE = "#EF5350";
const COLOR_NEUTRAL = "rgba(255,255,255,0.08)"; // muted for zero/null EPS

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFiscalYear(dateStr: string): string {
  // WHY UTC parse: dates from EODHD are fiscal year-end dates in ISO format.
  // Parsing without timezone can shift the date by one day in UTC-offset environments.
  const date = new Date(dateStr + "T00:00:00Z");
  return `FY${String(date.getUTCFullYear()).slice(2)}`;
}

// ── SVG chart geometry ────────────────────────────────────────────────────────
// Fixed 480×110 viewbox with internal margins. preserveAspectRatio="none" on
// the rendered <svg> stretches it to the panel width; the 1:1 viewbox keeps
// the bar widths well-proportioned at any size.
const VIEW_W = 480;
const VIEW_H = 110;
const M_TOP = 4;
const M_BOTTOM = 14;
const M_LEFT = 8;
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

// ── Component ─────────────────────────────────────────────────────────────────

export function EarningsHistoryChart({ instrumentId }: EarningsHistoryChartProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // ── Fetch historical EPS records ──────────────────────────────────────────
  // WHY staleTime 600_000: annual EPS records are only updated after earnings
  // releases (quarterly). 10-minute stale window prevents refetch thrashing on
  // tab navigation while staying current within a typical research session.
  const { data, isLoading } = useQuery({
    queryKey: ["earnings-history", instrumentId],
    queryFn: () => gateway.getEarningsHistory(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 600_000,
  });

  // ── Build chart data from records ─────────────────────────────────────────
  // WHY sort + slice at the end (not at fetch): records come from EODHD in
  // most-recent-first order. For a bar chart reading left-to-right as a timeline,
  // we reverse to ascending order. We take the 8 most recent fiscal years after
  // sorting to show one complete business cycle.
  const rawRecords = data?.records ?? [];
  const chartData = rawRecords
    .map((rec) => {
      const d = rec.data as EarningsAnnualRecord | undefined;
      return { date: d?.date ?? "", eps: d?.epsActual ?? null };
    })
    .filter((d) => !!d.date) // Drop records with missing date
    .sort((a, b) => a.date.localeCompare(b.date)) // Ascending: oldest → newest
    .slice(-8) // Keep last 8 fiscal years (right-end of timeline = most recent)
    .map((d) => ({ label: formatFiscalYear(d.date), eps: d.eps }));

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            EPS TREND
          </span>
        </div>
        <Skeleton className="m-2 h-[120px] rounded-[2px]" />
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (chartData.length === 0) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            EPS TREND
          </span>
        </div>
        <div className="px-2 py-2 text-[11px] font-mono text-muted-foreground">
          Earnings history not available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          EPS TREND
        </span>
        <span className="text-[9px] font-mono text-muted-foreground/60 ml-auto">
          Annual · {chartData.length}Y
        </span>
      </div>

      {/* ── Bar chart (hand-rolled SVG) ─────────────────────────────────── */}
      <ChartBars chartData={chartData} />
    </div>
  );
}

// ── Inner SVG bar chart ───────────────────────────────────────────────────────
// Extracted into its own component so the hover-state useState is co-located
// with the SVG it controls and not coupled to the data-fetching wrapper.

function ChartBars({
  chartData,
}: {
  chartData: { label: string; eps: number | null }[];
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Y scale must accommodate negatives — a loss-year bar grows DOWN from
  // the zero line. Compute min/max defensively across the actual data.
  const values = chartData
    .map((d) => d.eps)
    .filter((v): v is number => v != null);
  const dataMin = values.length ? Math.min(0, ...values) : 0;
  const dataMax = values.length ? Math.max(0, ...values) : 1;
  const range = Math.max(0.01, dataMax - dataMin);

  const slotW = PLOT_W / chartData.length;
  const barW = Math.min(36, slotW * 0.7);
  const xCenter = (i: number) => M_LEFT + slotW * i + slotW / 2;
  // Y-coordinate of the EPS-zero baseline within the plot area.
  const yZero = M_TOP + PLOT_H - ((0 - dataMin) / range) * PLOT_H;
  const yEps = (v: number) => M_TOP + PLOT_H - ((v - dataMin) / range) * PLOT_H;

  return (
    <div className="relative pt-1" data-testid="eps-trend-chart">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        height={VIEW_H}
        preserveAspectRatio="none"
        role="img"
        aria-label="Annual EPS history"
        onMouseLeave={() => setHoverIdx(null)}
      >
        {chartData.map((d, i) => {
          // Bar geometry: positive bars grow UP from zero line, negative bars
          // grow DOWN. Null-EPS records render as a faint placeholder so the
          // X-axis spacing stays consistent.
          const x = xCenter(i) - barW / 2;
          if (d.eps == null) {
            return (
              <rect
                key={`bar-${i}`}
                x={x}
                y={yZero - 1}
                width={barW}
                height={2}
                fill={COLOR_NEUTRAL}
              />
            );
          }
          const y = d.eps >= 0 ? yEps(d.eps) : yZero;
          const h = Math.abs(yEps(d.eps) - yZero);
          const fill = d.eps >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE;
          const stroke = d.eps >= 0 ? COLOR_POSITIVE_STROKE : COLOR_NEGATIVE_STROKE;
          return (
            <rect
              key={`bar-${i}`}
              x={x}
              y={y}
              width={barW}
              height={Math.max(0, h)}
              fill={fill}
              stroke={stroke}
              strokeWidth={1}
            />
          );
        })}

        {/* Zero baseline — only visible when the series spans positive AND
            negative values, which is when it carries information. */}
        {dataMin < 0 && dataMax > 0 && (
          <line
            x1={M_LEFT}
            x2={M_LEFT + PLOT_W}
            y1={yZero}
            y2={yZero}
            stroke="rgba(255,255,255,0.15)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        )}

        {/* X-axis labels — first + last only */}
        <text
          x={xCenter(0)}
          y={VIEW_H - 2}
          fill="currentColor"
          fontSize={9}
          fontFamily="monospace"
          textAnchor="middle"
          className="text-muted-foreground"
        >
          {chartData[0].label}
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
            {chartData[chartData.length - 1].label}
          </text>
        )}

        {/* Per-slot hit areas — wider than the bar so users don't
            pixel-hunt a 30px target. */}
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
      </svg>

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
          {chartData[hoverIdx].eps != null ? (
            <p
              className={
                chartData[hoverIdx].eps! >= 0
                  ? "text-positive"
                  : "text-negative"
              }
            >
              EPS: ${chartData[hoverIdx].eps!.toFixed(2)}
            </p>
          ) : (
            <p className="text-muted-foreground">EPS: —</p>
          )}
        </div>
      )}
    </div>
  );
}
