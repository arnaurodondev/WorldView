/**
 * components/instrument/financials/EarningsBarChart.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-C-02): EPS history is the single most important
 * trailing indicator in fundamental analysis. A growing EPS trajectory justifies
 * premium multiples; a declining one warns of multiple compression. This chart
 * renders the last 4 fiscal years of EPS as dual bars (actual vs estimate)
 * so the analyst can see beat/miss outcomes alongside the absolute trend.
 *
 * WHY HAND-ROLLED SVG (not recharts): the plan spec called for recharts, but
 * recharts is NOT currently in package.json — PLAN-0059 G-1 explicitly migrated
 * off it for the sibling EarningsHistoryChart to drop ~50KB gz of bundle cost
 * for a 4-bar categorical chart. We honor the rule "no new charting library"
 * by using the established inline-SVG pattern from EarningsHistoryChart.tsx.
 *
 * WHY DUAL BARS (actual filled + estimate outline): a single-color bar shows
 * only direction. The outline overlay encodes the consensus expectation in the
 * same visual slot — beats are bars taller than their outline, misses shorter.
 * This is the conventional Bloomberg/FactSet beat-bar display.
 *
 * DATA: S9 GET /v1/fundamentals/{id}/earnings-annual-trend → records with
 *   data = {date: "YYYY-MM-DD", epsActual: number, epsEstimate: number}.
 * Records arrive most-recent-first; we reverse + slice last 4 for L-to-R timeline.
 * DESIGN: PRD-0088 §6.8, PLAN-0090 §T-C-02.
 */

"use client";
// WHY "use client": useQuery requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

interface EarningsBarChartProps {
  instrumentId: string;
}

// WHY typed cast: FundamentalsSectionResponse.records[].data is JSONB. Typing
// stops a typo from silently dropping every bar. All fields nullable — ETFs
// and newly-listed names lack one or both EPS values.
interface EarningsAnnualRecord {
  date?: string | null;
  epsActual?: number | null;
  epsEstimate?: number | null;
}

// WHY hex (not CSS vars): SVG `fill`/`stroke` attributes don't resolve CSS vars.
// Hex values match --positive (#26A69A) / --negative (#EF5350) from the theme.
const COLOR_BEAT_FILL    = "#26A69A40"; // 25% green — beat
const COLOR_BEAT_STROKE  = "#26A69A";
const COLOR_MISS_FILL    = "#EF535040"; // 25% red — miss
const COLOR_MISS_STROKE  = "#EF5350";

// Chart viewbox: 480×80 (T-C-02 spec calls for 80px height; preserveAspectRatio
// = "none" lets the SVG stretch horizontally to whatever the container provides).
const VIEW_W = 480;
const VIEW_H = 80;
const M_TOP = 4;
const M_BOTTOM = 12;  // room for the FY labels at the foot
const M_LEFT = 8;
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

function formatFY(dateStr: string): string {
  // WHY UTC parse: prevents off-by-one-day at midnight UTC in western timezones.
  try {
    return `FY${String(new Date(dateStr + "T00:00:00Z").getUTCFullYear()).slice(2)}`;
  } catch {
    return dateStr.slice(0, 4);
  }
}

export function EarningsBarChart({ instrumentId }: EarningsBarChartProps) {
  const { accessToken } = useAuth();

  // WHY staleTime 24h: annual EPS records update only on quarterly earnings
  // releases. Matches T-A-03 useFinancialsTabData policy → TanStack dedupes
  // when both this component and the hook are mounted with the same key.
  const { data, isLoading } = useQuery({
    queryKey: ["earnings-history", instrumentId],
    queryFn: () => createGateway(accessToken).getEarningsHistory(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  // Build chart data: filter out missing dates, sort ascending (oldest left),
  // take the last 4 fiscal years (T-C-02 spec: 4 FY columns).
  const chartData = (data?.records ?? [])
    .map((rec) => {
      const d = rec.data as EarningsAnnualRecord | undefined;
      return { date: d?.date ?? "", actual: d?.epsActual ?? null, estimate: d?.epsEstimate ?? null };
    })
    .filter((d) => !!d.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-4)
    .map((d) => ({ label: formatFY(d.date), actual: d.actual, estimate: d.estimate }));

  if (isLoading) return <Skeleton className="h-[80px] rounded-[2px]" />;
  // Empty state hidden per T-C-02 spec — no chart rendered if no data.
  if (chartData.length === 0) return null;

  // Y-scale: include zero + the max of actuals and estimates, defensive
  // against an all-loss series (negative EPS bars grow down from zero line).
  const allValues = chartData.flatMap((d) =>
    [d.actual, d.estimate].filter((v): v is number => v != null),
  );
  const dataMin = allValues.length ? Math.min(0, ...allValues) : 0;
  const dataMax = allValues.length ? Math.max(0, ...allValues) : 1;
  const range = Math.max(0.01, dataMax - dataMin);

  const slotW = PLOT_W / chartData.length;
  // WHY barW < slotW: leave gutter between fiscal years; 0.6 ratio matches the
  // visual spacing on Finviz earnings panels at 4-column density.
  const barW = Math.min(36, slotW * 0.6);
  const xCenter = (i: number) => M_LEFT + slotW * i + slotW / 2;
  const yZero = M_TOP + PLOT_H - ((0 - dataMin) / range) * PLOT_H;
  const yFor = (v: number) => M_TOP + PLOT_H - ((v - dataMin) / range) * PLOT_H;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      width="100%"
      height={VIEW_H}
      preserveAspectRatio="none"
      role="img"
      aria-label="Annual EPS history (actual vs estimate)"
      data-testid="earnings-bar-chart"
    >
      {chartData.map((d, i) => {
        const x = xCenter(i) - barW / 2;
        // Beat = actual ≥ estimate (in-line = beat per sell-side convention).
        // Fall back to sign-coloring when estimate is absent.
        const isBeat = d.estimate != null
          ? (d.actual ?? 0) >= d.estimate
          : (d.actual ?? 0) >= 0;
        const fill   = isBeat ? COLOR_BEAT_FILL   : COLOR_MISS_FILL;
        const stroke = isBeat ? COLOR_BEAT_STROKE : COLOR_MISS_STROKE;

        return (
          <g key={`fy-${i}`}>
            {/* Solid actual bar — grows up from zero for positive, down for loss years. */}
            {d.actual != null && (
              <rect
                x={x}
                y={d.actual >= 0 ? yFor(d.actual) : yZero}
                width={barW}
                height={Math.max(1, Math.abs(yFor(d.actual) - yZero))}
                fill={fill}
                stroke={stroke}
                strokeWidth={1}
              />
            )}
            {/* Outline-only estimate bar overlaid in the same slot — taller-than-
                outline reads as beat; shorter as miss. Outline width is the same
                barW so it sits flush with the actual rectangle. */}
            {d.estimate != null && (
              <rect
                x={x}
                y={d.estimate >= 0 ? yFor(d.estimate) : yZero}
                width={barW}
                height={Math.max(1, Math.abs(yFor(d.estimate) - yZero))}
                fill="none"
                stroke="rgba(255,255,255,0.35)"
                strokeWidth={1}
                strokeDasharray="2 2"
              />
            )}
            {/* FY label at foot of bar — kept under each column rather than only
                first/last because 4 labels comfortably fit at 9px monospace. */}
            <text
              x={xCenter(i)}
              y={VIEW_H - 2}
              fill="currentColor"
              fontSize={9}
              fontFamily="monospace"
              textAnchor="middle"
              className="text-muted-foreground"
            >
              {d.label}
            </text>
          </g>
        );
      })}
      {/* Zero baseline — only when series straddles zero (otherwise visually noisy). */}
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
    </svg>
  );
}
