/**
 * components/instrument/RevenueTrendSparklines.tsx — Revenue + EPS trend chart
 *
 * WHY THIS EXISTS: A single YoY growth percentage hides the trajectory — is the
 * company accelerating or decelerating? Analysts need quarterly revenue bars and
 * an EPS line overlay to spot multi-quarter trends that a point-in-time figure
 * cannot show. Bloomberg DES shows revenue trend above the metrics grid.
 *
 * WHY REAL CHART (was placeholder): Wave D-1 wires the S9 fundamentals/timeseries
 * endpoint (added in Wave A-1 and gated in Wave B-1) to this component. The
 * endpoint returns per-metric quarterly and annual time series from S3.
 *
 * WHY ComposedChart (recharts): recharts is already in package.json (v2.15.0).
 * ComposedChart lets us overlay a Bar series (revenue) and a Line series (EPS)
 * sharing the same X-axis without two separate charts stacked vertically.
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
 * Recharts tooltips provide exact values on hover. The chart's primary purpose
 * is trend direction, not exact values — that's what the MetricRow grid is for.
 *
 * WHO USES IT: FundamentalsTab.tsx (full-width section above metrics grid)
 * DATA SOURCE: S9 GET /v1/fundamentals/timeseries (via getFundamentalsTimeseries)
 * DESIGN REFERENCE: PLAN-0041 §T-D-1-02
 */

"use client";
// WHY "use client": uses useQuery for two timeseries fetches.

import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
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
 * WHY this function: recharts XAxis tickFormatter receives a raw date string
 * from the timeseries endpoint ("2024-03-31"). Analysts expect Bloomberg-style
 * quarter labels, not ISO dates.
 */
function formatQuarterLabel(dateStr: string): string {
  // WHY T00:00:00Z suffix: prevents timezone-offset date shift when parsing
  // ISO date-only strings (e.g., "2024-03-31" parsed as local time shifts to
  // "2024-03-30" in UTC-offset locales). UTC parse is always correct.
  const date = new Date(dateStr + "T00:00:00Z");
  const month = date.getUTCMonth(); // 0-indexed: 0=Jan, 11=Dec
  const year = date.getUTCFullYear();
  const quarter = Math.floor(month / 3) + 1;
  return `Q${quarter}'${String(year).slice(2)}`;
}

/**
 * formatAnnualLabel — convert an ISO date string to "FY24" format
 *
 * WHY separate from formatQuarterLabel: annual timeseries uses fiscal year
 * labels, not quarter numbers. Analysts expect "FY24" for annual data.
 */
function formatAnnualLabel(dateStr: string): string {
  const date = new Date(dateStr + "T00:00:00Z");
  return `FY${String(date.getUTCFullYear()).slice(2)}`;
}

/**
 * revenueToB — convert raw revenue value (units) to billions for chart display
 *
 * WHY billions: revenue values from S3 are in absolute units (e.g., 81,797,000,000
 * for $81.8B). Displaying in billions keeps axis labels readable. The tooltip
 * also shows the "$XB" formatted value.
 */
function revenueToB(value: number | null): number | null {
  if (value == null) return null;
  return Math.round((value / 1e9) * 10) / 10; // 1 decimal place
}

// ── Chart color constants ─────────────────────────────────────────────────────
// WHY hex (not CSS variables): recharts SVG attributes don't resolve CSS custom
// properties — only inline styles in container HTML elements do. These match the
// design system tokens defined in globals.css:
// --primary: #FFD60A (Bloomberg yellow)
// --positive: #26A69A (teal green for positive metrics)

const COLOR_REVENUE_BAR = "rgba(255, 214, 10, 0.25)"; // primary/25% opacity fill
const COLOR_REVENUE_STROKE = "#FFD60A";                // primary stroke
const COLOR_EPS_LINE = "#26A69A";                      // positive teal

// ── Merged data shape ─────────────────────────────────────────────────────────

interface ChartPoint {
  date: string;
  label: string;
  revenue: number | null; // in billions
  eps: number | null;     // in dollars
}

// ── Custom tooltip ─────────────────────────────────────────────────────────────

/**
 * ChartTooltip — minimal tooltip showing revenue + EPS values on hover
 *
 * WHY custom (not recharts default): the default tooltip renders white backgrounds
 * that clash with the terminal dark theme. Custom tooltip uses bg-popover +
 * border-border for design system consistency.
 */
function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { name: string; value: number | null }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const revenue = payload.find((p) => p.name === "revenue")?.value;
  const eps = payload.find((p) => p.name === "eps")?.value;

  return (
    <div className="rounded-[2px] border border-border bg-popover px-2 py-1.5 text-[10px] font-mono">
      <p className="mb-0.5 font-medium text-foreground">{label}</p>
      {revenue != null && (
        <p className="text-muted-foreground">
          Revenue: <span className="text-primary">${revenue}B</span>
        </p>
      )}
      {eps != null && (
        <p className="text-muted-foreground">
          EPS: <span className="text-positive">${eps.toFixed(2)}</span>
        </p>
      )}
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RevenueTrendSparklines({ instrumentId }: RevenueTrendSparklinesProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // ── Fetch revenue timeseries ───────────────────────────────────────────────
  // WHY staleTime 300_000: fundamentals timeseries updates once per day at most;
  // 5-minute stale window prevents redundant fetches on tab switches.
  // WHY limit 12: 3 years of quarterly data gives a meaningful trend without
  // overcrowding the 120px chart (recharts bars become too narrow past ~12 bars).
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

  // ── Fetch EPS timeseries ───────────────────────────────────────────────────
  // WHY separate query (not combined): S9 timeseries is per-metric; there's no
  // multi-metric endpoint. Two independent queries allow independent loading states
  // and avoid coupling revenue failure to EPS display.
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

  // ── Determine period type for label formatting ────────────────────────────
  const revenuePoints: TimeseriesDataPoint[] = revenueTsResp?.data ?? [];
  const epsPoints: TimeseriesDataPoint[] = epsTsResp?.data ?? [];

  // WHY check first point's period_type: the API may return annual instead of
  // quarterly when quarterly data doesn't exist. Use annual labels in that case.
  const firstPeriodType = revenuePoints[0]?.period_type ?? "QUARTERLY";
  const isAnnual = firstPeriodType === "ANNUAL";
  const formatLabel = isAnnual ? formatAnnualLabel : formatQuarterLabel;

  // ── Merge revenue and EPS on date ─────────────────────────────────────────
  // WHY merge on revenue dates: revenue is the primary series. EPS points that
  // don't have a matching revenue date are discarded (usually means mismatched
  // period ends — rare, but guard for it).
  const chartData: ChartPoint[] = revenuePoints.map((r) => {
    // WHY slice(0,10): as_of_date may have time portion; only compare date part
    const matchEps = epsPoints.find(
      (e) => e.as_of_date.slice(0, 10) === r.as_of_date.slice(0, 10),
    );
    return {
      date: r.as_of_date,
      label: formatLabel(r.as_of_date),
      revenue: revenueToB(r.value_numeric),
      eps: matchEps?.value_numeric ?? null,
    };
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (revenueLoading && epsLoading) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            REVENUE TREND
          </span>
        </div>
        {/* WHY h-[120px]: matches chart height defined below */}
        <Skeleton className="m-2 h-[120px] rounded-[2px]" />
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  // WHY always render the section header: the section should be visible even when
  // data is unavailable so analysts know this category is tracked (Bloomberg convention).
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

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          REVENUE TREND
        </span>
        {/* ── Legend ─────────────────────────────────────────────────────────
            WHY inline legend in header: at 120px chart height, a separate legend
            row would consume ~15% of vertical space. Inline in the header saves
            space while keeping the color mapping visible. */}
        <div className="flex items-center gap-2 ml-auto">
          <div className="flex items-center gap-1">
            <div className="h-2 w-3 rounded-[1px]" style={{ backgroundColor: COLOR_REVENUE_STROKE, opacity: 0.5 }} />
            <span className="text-[9px] text-muted-foreground font-mono">Revenue</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="h-0.5 w-3 rounded-full" style={{ backgroundColor: COLOR_EPS_LINE }} />
            <span className="text-[9px] text-muted-foreground font-mono">EPS</span>
          </div>
        </div>
      </div>

      {/* ── Recharts ComposedChart ───────────────────────────────────────────── */}
      {/* WHY pb-1: bottom padding prevents X-axis labels from clipping at the border */}
      <div className="pb-1">
        {/* WHY ResponsiveContainer width="100%": chart fills the full panel width
            regardless of panel resize. height is fixed at 120px — a full chart
            would take too much vertical space above the metrics grid. */}
        <ResponsiveContainer width="100%" height={120}>
          <ComposedChart
            data={chartData}
            margin={{ top: 8, right: 8, bottom: 0, left: 8 }}
          >
            {/* ── X Axis — quarter/annual labels ──────────────────────────── */}
            {/* WHY dataKey="label" (not "date"): label is the pre-formatted
                "Q1'24" string; recharts XAxis uses the tick value as the label
                when tickFormatter is omitted. */}
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fontFamily: "monospace", fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
              // WHY interval="preserveStartEnd": only shows first and last label
              // to prevent crowding at 120px height with 12 bars.
              interval="preserveStartEnd"
            />

            {/* ── Tooltip ──────────────────────────────────────────────────── */}
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ fill: "rgba(255,255,255,0.04)" }}
            />

            {/* ── Revenue bars ─────────────────────────────────────────────── */}
            {/* WHY semi-transparent fill: bars shouldn't occlude the EPS line
                that overlays them. 25% opacity primary yellow shows the bar
                height while the 100% yellow stroke edge makes bars readable. */}
            <Bar
              dataKey="revenue"
              name="revenue"
              fill={COLOR_REVENUE_BAR}
              stroke={COLOR_REVENUE_STROKE}
              strokeWidth={1}
              radius={[1, 1, 0, 0]}
              // WHY maxBarSize: prevents bars from becoming too wide when there
              // are only 4-6 data points (annual fallback case).
              maxBarSize={40}
            />

            {/* ── EPS line overlay ─────────────────────────────────────────── */}
            {/* WHY connectNulls: some quarters may have null EPS (earnings not
                yet reported); connecting nulls keeps the line continuous rather
                than breaking into disconnected segments. */}
            <Line
              type="monotone"
              dataKey="eps"
              name="eps"
              stroke={COLOR_EPS_LINE}
              strokeWidth={1.5}
              dot={false}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
