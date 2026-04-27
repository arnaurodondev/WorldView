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
// WHY "use client": uses useQuery for earnings fetch.

import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
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

// ── Custom tooltip ─────────────────────────────────────────────────────────────

function EpsTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const eps = payload[0]?.value;
  return (
    <div className="rounded-[2px] border border-border bg-popover px-2 py-1.5 text-[10px] font-mono shadow-md">
      <p className="mb-0.5 font-medium text-foreground">{label}</p>
      {eps != null ? (
        <p className={eps >= 0 ? "text-[#26A69A]" : "text-[#EF5350]"}>
          EPS: ${eps.toFixed(2)}
        </p>
      ) : (
        <p className="text-muted-foreground">EPS: —</p>
      )}
    </div>
  );
}

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

      {/* ── Bar chart ───────────────────────────────────────────────────── */}
      <div className="pt-1">
        <ResponsiveContainer width="100%" height={110}>
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <Tooltip content={<EpsTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="eps" maxBarSize={36} radius={[1, 1, 0, 0]}>
              {chartData.map((entry, index) => {
                // WHY conditional color per cell: green = profitable year,
                // red = loss year, muted = no data. Per-cell coloring uses
                // recharts Cell component (not a single Bar fill).
                const eps = entry.eps;
                const fill =
                  eps == null ? COLOR_NEUTRAL : eps >= 0 ? COLOR_POSITIVE : COLOR_NEGATIVE;
                const stroke =
                  eps == null
                    ? "transparent"
                    : eps >= 0
                      ? COLOR_POSITIVE_STROKE
                      : COLOR_NEGATIVE_STROKE;
                return (
                  <Cell key={`cell-${index}`} fill={fill} stroke={stroke} strokeWidth={1} />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
