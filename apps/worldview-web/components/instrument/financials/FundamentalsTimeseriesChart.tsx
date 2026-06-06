/**
 * components/instrument/financials/FundamentalsTimeseriesChart.tsx
 *
 * WHY THIS EXISTS (PLAN-0092 Wave B): The Financials tab shows snapshot metrics
 * in DenseMetricsGrid but lacked any historical trend view. This component adds
 * an 11-metric chip strip + period selector (1Y/3Y/5Y) so analysts can see how
 * key valuation and profitability multiples have evolved over time — the standard
 * view on Bloomberg, FactSet, and Morningstar.
 *
 * WHY inline SVG (not recharts/chart.js): established pattern in this codebase
 * (EarningsBarChart, EarningsHistoryChart) — avoids importing a charting lib for
 * a simple polyline. SVG fills the container width via preserveAspectRatio="none".
 *
 * DATA: S9 GET /v1/fundamentals/timeseries?instrument_id=…&metric=…&period_type=…
 *       &order=asc&limit=…
 * WHY order=asc: the backend default returns DESC (most-recent first); asc gives
 * us the oldest first so chart L→R is chronological. See BP audit 2026-04-28.
 *
 * WHY per-metric period_type: different metrics are stored at different cadences
 * in S3. Valuation multiples (P/E, P/B) are QUARTERLY; ROE is ANNUAL; Fwd P/E
 * and Div Yield are SNAPSHOT (point-in-time, not period-linked).
 *
 * WIRED INTO: FinancialsTab.tsx — inserted after EarningsBarChart, before PeerComparisonTable.
 *
 * DESIGN REF: docs/designs/0089/06-instrument-financials.md §E-002
 */

"use client";
// WHY "use client": hooks (useState, useQuery) require the browser runtime.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import type { TimeseriesDataPoint } from "@/types/api";

// ── Metric catalogue ─────────────────────────────────────────────────────────

/** Per-metric period_type tells S3 which cadence bucket to query.
 *  QUARTERLY for valuation/margin metrics (filed each quarter),
 *  ANNUAL for ROE (too noisy quarterly),
 *  SNAPSHOT for forward-looking/yield metrics (point-in-time, no period). */
const PERIOD_TYPE = {
  QUARTERLY: "QUARTERLY",
  ANNUAL: "ANNUAL",
  SNAPSHOT: "SNAPSHOT",
} as const;

interface MetricDef {
  key: string;
  label: string;
  periodType: keyof typeof PERIOD_TYPE;
  /** WHY pct: some metrics are stored as decimals (0.12 = 12%); flag for display. */
  pct?: boolean;
}

const METRICS: MetricDef[] = [
  { key: "pe_ratio",                label: "P/E",       periodType: "QUARTERLY" },
  { key: "price_to_book",           label: "P/B",       periodType: "QUARTERLY" },
  { key: "price_to_sales",          label: "P/S",       periodType: "QUARTERLY" },
  { key: "enterprise_value_ebitda", label: "EV/EBITDA", periodType: "QUARTERLY" },
  { key: "forward_pe",              label: "Fwd P/E",   periodType: "SNAPSHOT"  },
  { key: "revenue_growth_yoy",      label: "Rev Growth",periodType: "QUARTERLY", pct: true },
  { key: "eps_growth_yoy",          label: "EPS Growth",periodType: "QUARTERLY", pct: true },
  { key: "net_profit_margin",       label: "Net Margin",periodType: "QUARTERLY", pct: true },
  { key: "operating_margin_ttm",    label: "Op Margin", periodType: "QUARTERLY", pct: true },
  { key: "return_on_equity",        label: "ROE",       periodType: "ANNUAL",    pct: true },
  { key: "dividend_yield",          label: "Div Yield", periodType: "SNAPSHOT",  pct: true },
];

// ── Period options ────────────────────────────────────────────────────────────

interface PeriodOption {
  label: string;
  years: number;
}

const PERIOD_OPTIONS: PeriodOption[] = [
  { label: "1Y", years: 1 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
];

// ── SVG chart constants ───────────────────────────────────────────────────────

const VIEW_W = 480;
const VIEW_H = 120;
const M_TOP = 8;
const M_BOTTOM = 18; // room for date labels
const M_LEFT = 8;
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

// Design system color for the line (Bloomberg terminal teal)
const LINE_COLOR = "#26A69A";
const AREA_COLOR = "#26A69A22"; // 13% opacity fill under the line

// ── Helpers ───────────────────────────────────────────────────────────────────

/** ISO date string → short year label for X-axis tick. */
function toYearLabel(dateStr: string): string {
  try {
    return String(new Date(`${dateStr}T00:00:00Z`).getUTCFullYear());
  } catch {
    return dateStr.slice(0, 4);
  }
}

/** Compute ISO start_date from years-ago count. */
function startDateFromYears(years: number): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - years);
  return d.toISOString().slice(0, 10);
}

/** Format a numeric value for display in the legend/tooltip area.
 *  Percentage metrics: multiply by 100 if stored as decimal (<1), add "%".
 *  Multiplier metrics (ratios): 1 decimal place. */
function formatValue(value: number | null, pct?: boolean): string {
  if (value == null) return "—";
  if (pct) {
    // Values like 0.12 → 12.0%; values already like 12 pass through
    const v = Math.abs(value) < 2 ? value * 100 : value;
    return `${v.toFixed(1)}%`;
  }
  return value.toFixed(1);
}

// ── SVG Line Chart ────────────────────────────────────────────────────────────

interface LineChartProps {
  points: TimeseriesDataPoint[];
  pct?: boolean;
}

function LineChart({ points, pct }: LineChartProps) {
  if (points.length === 0) {
    return (
      <div className="flex h-[120px] items-center justify-center text-[11px] text-muted-foreground">
        No data for this metric / period combination.
      </div>
    );
  }

  const values = points.map((p) => p.value_numeric);
  const numeric = values.filter((v): v is number => v != null);
  if (numeric.length === 0) {
    return (
      <div className="flex h-[120px] items-center justify-center text-[11px] text-muted-foreground">
        No numeric values returned.
      </div>
    );
  }

  const dataMin = Math.min(...numeric);
  const dataMax = Math.max(...numeric);
  const range = Math.max(0.0001, dataMax - dataMin);

  // Compute SVG coordinates for each data point
  const n = points.length;
  const coords = points.map((p, i) => {
    const x = M_LEFT + (i / Math.max(1, n - 1)) * PLOT_W;
    const v = p.value_numeric;
    const y = v == null
      ? null
      : M_TOP + PLOT_H - ((v - dataMin) / range) * PLOT_H;
    return { x, y, date: p.as_of_date, value: v };
  });

  // Build polyline path (skip null segments)
  let polyline = "";
  let area = "";
  let firstX: number | null = null;
  let lastX: number | null = null;
  for (const pt of coords) {
    if (pt.y == null) continue;
    if (polyline === "") {
      polyline = `M ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
      area = `M ${pt.x.toFixed(1)} ${(M_TOP + PLOT_H).toFixed(1)} L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
      firstX = pt.x;
    } else {
      polyline += ` L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
      area += ` L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
    }
    lastX = pt.x;
  }
  if (firstX != null && lastX != null) {
    area += ` L ${lastX.toFixed(1)} ${(M_TOP + PLOT_H).toFixed(1)} Z`;
  }

  // X-axis year labels: show first + last + up to 3 intermediate ticks
  const tickIndices: number[] = [];
  if (n > 0) tickIndices.push(0);
  if (n > 3) tickIndices.push(Math.floor(n / 3));
  if (n > 6) tickIndices.push(Math.floor((2 * n) / 3));
  if (n > 1) tickIndices.push(n - 1);
  const uniqueTicks = [...new Set(tickIndices)];

  const latestValue = points[points.length - 1]?.value_numeric ?? null;

  return (
    <div>
      {/* Current value badge */}
      <div className="px-2 pb-1 text-right text-[11px] text-muted-foreground">
        Latest: <span className="font-mono text-foreground">{formatValue(latestValue, pct)}</span>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        width="100%"
        height={VIEW_H}
        preserveAspectRatio="none"
        aria-hidden
      >
        {/* Area fill under the line */}
        {area && (
          <path d={area} fill={AREA_COLOR} />
        )}
        {/* Line */}
        {polyline && (
          <path d={polyline} fill="none" stroke={LINE_COLOR} strokeWidth="1.5" />
        )}
        {/* X-axis tick labels */}
        {uniqueTicks.map((idx) => {
          const pt = coords[idx];
          if (!pt) return null;
          return (
            <text
              key={idx}
              x={pt.x}
              y={VIEW_H - 2}
              textAnchor="middle"
              fontSize="9"
              fill="#888"
            >
              {toYearLabel(pt.date)}
            </text>
          );
        })}
        {/* Zero line if data crosses zero */}
        {dataMin < 0 && dataMax > 0 && (() => {
          const yZero = M_TOP + PLOT_H - ((0 - dataMin) / range) * PLOT_H;
          return (
            <line
              x1={M_LEFT}
              y1={yZero}
              x2={M_LEFT + PLOT_W}
              y2={yZero}
              stroke="#444"
              strokeWidth="0.5"
              strokeDasharray="3,3"
            />
          );
        })()}
      </svg>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export interface FundamentalsTimeseriesChartProps {
  /** S9-side instrument_id for the fundamentals/timeseries endpoint. */
  readonly instrumentId: string;
}

export function FundamentalsTimeseriesChart({ instrumentId }: FundamentalsTimeseriesChartProps) {
  // Active metric (chip selection) — default to P/E as the most-commonly checked valuation.
  const [activeMetric, setActiveMetric] = useState<string>(METRICS[0].key);
  // Active time window — default 3Y for meaningful trend signal.
  const [activePeriod, setActivePeriod] = useState<string>("3Y");

  const metricDef = METRICS.find((m) => m.key === activeMetric) ?? METRICS[0];
  const periodOpt = PERIOD_OPTIONS.find((p) => p.label === activePeriod) ?? PERIOD_OPTIONS[1];

  const gateway = useApiClient();

  // WHY limit=60: 5Y quarterly = 20 points, 5Y annual = 5, SNAPSHOT ~100 max.
  // 60 is safe upper bound covering 5Y of quarterly data with buffer.
  const startDate = startDateFromYears(periodOpt.years);
  const { data, isLoading } = useQuery({
    queryKey: qk.instruments.fundamentalsTimeseries(instrumentId, `${activeMetric}:${activePeriod}`),
    queryFn: () =>
      gateway.getFundamentalsTimeseries(instrumentId, activeMetric, {
        period_type: PERIOD_TYPE[metricDef.periodType],
        start_date: startDate,
        order: "asc",
        limit: 60,
      }),
    enabled: !!instrumentId,
    // WHY staleTime 1h: timeseries data is updated at quarterly report cadence.
    // 1h avoids refetching on every chip click while staying reasonably fresh.
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="border-t border-border px-2 py-2">
      {/* ── Header row: section title ── */}
      <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        Historical Trend
      </div>

      {/* ── Metric chip strip (11 chips) ── */}
      <div className="flex flex-wrap gap-1 pb-2">
        {METRICS.map((m) => (
          <button
            key={m.key}
            onClick={() => setActiveMetric(m.key)}
            className={[
              "rounded px-2 py-0.5 text-[10px] font-medium transition-colors",
              activeMetric === m.key
                ? "bg-[#26A69A] text-black"
                : "bg-muted text-muted-foreground hover:bg-muted/70",
            ].join(" ")}
          >
            {m.label}
          </button>
        ))}

        {/* ── Period chips: 1Y / 3Y / 5Y, pushed to right ── */}
        <div className="ml-auto flex gap-1">
          {PERIOD_OPTIONS.map((p) => (
            <button
              key={p.label}
              onClick={() => setActivePeriod(p.label)}
              className={[
                "rounded px-2 py-0.5 text-[10px] font-medium transition-colors",
                activePeriod === p.label
                  ? "bg-muted-foreground text-background"
                  : "bg-muted text-muted-foreground hover:bg-muted/70",
              ].join(" ")}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Chart area ── */}
      {isLoading ? (
        <Skeleton className="h-[120px] w-full rounded-none" />
      ) : (
        <LineChart points={data?.data ?? []} pct={metricDef.pct} />
      )}
    </div>
  );
}
