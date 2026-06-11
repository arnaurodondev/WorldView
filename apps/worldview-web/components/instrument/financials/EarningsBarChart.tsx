/**
 * components/instrument/financials/EarningsBarChart.tsx — EPS beat/miss chart (T-11)
 *
 * WHY THIS EXISTS (PLAN-0090 T-C-02 + PLAN-0089 W3 T-11): EPS history is the
 * single most important trailing indicator in fundamental analysis. A growing
 * EPS trajectory justifies premium multiples; a declining one warns of multiple
 * compression. Dual bars (actual filled + estimate outline) encode the beat/miss
 * outcome per year — analysts see trajectory AND reliability simultaneously.
 *
 * WHY 64px HEIGHT (was 80px): T-11 spec reduces height to 64px so the chart
 * consumes less vertical real estate in the 7-block left column. 64px gives
 * enough bar height to read the beat/miss pattern at a glance.
 *
 * WHY EPS SURPRISE CHIP (T-11 Δ): the surprise % chip floats above each bar.
 * It quantifies the beat/miss magnitude (e.g. "+5.2%" for beat) so analysts
 * can scan across 4 years without calculating manually. The chip is null-safe
 * — hidden entirely when all 4 periods have no surprise_percent data.
 *
 * DATA: S9 GET /v1/fundamentals/{id}/earnings-annual-trend → records with
 *   data = {date, epsActual, epsEstimate, surprisePercent (optional)}.
 * DESIGN: PRD-0088 §6.8, PLAN-0090 §T-C-02, PLAN-0089 W3 T-11.
 */

"use client";
// WHY "use client": useQuery requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { PanelHeader } from "./PanelHeader";

interface EarningsBarChartProps {
  instrumentId: string;
}

interface EarningsAnnualRecord {
  date?: string | null;
  epsActual?: number | null;
  epsEstimate?: number | null;
  // WHY optional: EODHD backfills surprisePercent for older records but may
  // omit it for recent quarters not yet in the system.
  surprisePercent?: number | null;
}

// WHY hex (not CSS vars): SVG fill/stroke don't resolve CSS custom properties.
const COLOR_BEAT_FILL   = "#26A69A40";
const COLOR_BEAT_STROKE = "#26A69A";
const COLOR_MISS_FILL   = "#EF535040";
const COLOR_MISS_STROKE = "#EF5350";

// WHY 64px (T-11): reduced from 80px to free vertical space for the 3 new
// tables below the chart. Still tall enough for 4 bars to be readable.
const VIEW_W = 480;
const VIEW_H = 64;
const M_TOP = 14;  // WHY 14px top margin: room for the surprise chip above bars
const M_BOTTOM = 12;
const M_LEFT = 8;
const M_RIGHT = 8;
const PLOT_W = VIEW_W - M_LEFT - M_RIGHT;
const PLOT_H = VIEW_H - M_TOP - M_BOTTOM;

function formatFY(dateStr: string): string {
  try {
    return `FY${String(new Date(dateStr + "T00:00:00Z").getUTCFullYear()).slice(2)}`;
  } catch {
    return dateStr.slice(0, 4);
  }
}

// WHY ±% format: surprise percent is already in percent units from EODHD.
// +5.2 → "+5.2%", -3.1 → "-3.1%".
function formatSurprise(v: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

export function EarningsBarChart({ instrumentId }: EarningsBarChartProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    queryKey: ["earnings-history", instrumentId],
    queryFn: () => createGateway(accessToken).getEarningsHistory(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  const chartData = (data?.records ?? [])
    .map((rec) => {
      const d = rec.data as EarningsAnnualRecord | undefined;
      return {
        date: d?.date ?? "",
        actual: d?.epsActual ?? null,
        estimate: d?.epsEstimate ?? null,
        surprisePercent: d?.surprisePercent ?? null,
      };
    })
    .filter((d) => !!d.date)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-4)
    .map((d) => ({
      label: formatFY(d.date),
      actual: d.actual,
      estimate: d.estimate,
      surprisePercent: d.surprisePercent,
    }));

  // Wave-2 redesign: the chart was an ORPHAN SVG — no header band, so it
  // floated between two table panels with nothing naming it (a key "sloppy"
  // signal). The skeleton now mirrors the final header+chart shape.
  if (isLoading) {
    return (
      <div role="status" aria-label="Loading earnings history" className="space-y-1 border-t border-border px-2 py-1">
        <Skeleton className="h-5 w-1/3 rounded-[2px]" />
        <Skeleton className="h-[64px] rounded-[2px]" />
      </div>
    );
  }
  // Zero records → the WHOLE panel (header included) stays hidden: an empty
  // chart band would be chrome with no information (kept behaviour).
  if (chartData.length === 0) return null;

  // WHY check all-null: hide the entire chip row if no period has surprise data.
  // This prevents empty chip "—" noise for instruments with incomplete backfill.
  const hasSurprise = chartData.some((d) => d.surprisePercent != null);

  const allValues = chartData.flatMap((d) =>
    [d.actual, d.estimate].filter((v): v is number => v != null),
  );
  const dataMin = allValues.length ? Math.min(0, ...allValues) : 0;
  const dataMax = allValues.length ? Math.max(0, ...allValues) : 1;
  const range = Math.max(0.01, dataMax - dataMin);

  const slotW = PLOT_W / chartData.length;
  const barW = Math.min(36, slotW * 0.6);
  const xCenter = (i: number) => M_LEFT + slotW * i + slotW / 2;
  const yZero = M_TOP + PLOT_H - ((0 - dataMin) / range) * PLOT_H;
  const yFor = (v: number) => M_TOP + PLOT_H - ((v - dataMin) / range) * PLOT_H;

  return (
    // Wave-2 redesign: uniform 24px accent-bar header (PanelHeader) + a
    // compact legend so the dual-bar encoding (filled actual vs dashed
    // estimate outline) is named instead of guessed.
    <div data-testid="earnings-panel" className="border-t border-border">
      <PanelHeader label="EARNINGS" meta="annual EPS · actual vs estimate">
        {/* Legend — mono 9px, mirrors the SVG's exact fill/stroke treatment.
            aria-hidden: the header meta already names the encoding for SRs. */}
        <span aria-hidden className="flex items-center gap-2 font-mono text-[9px] text-muted-foreground/60">
          <span className="flex items-center gap-1">
            {/* Filled swatch = actual EPS bar (teal when beat). */}
            <span className="inline-block h-[7px] w-[7px] border border-positive bg-positive/25" />
            ACT
          </span>
          <span className="flex items-center gap-1">
            {/* Dashed swatch = estimate outline bar. */}
            <span className="inline-block h-[7px] w-[7px] border border-dashed border-foreground/35" />
            EST
          </span>
        </span>
      </PanelHeader>

      <div className="px-2 py-1">
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
        const isBeat = d.estimate != null
          ? (d.actual ?? 0) >= d.estimate
          : (d.actual ?? 0) >= 0;
        const fill   = isBeat ? COLOR_BEAT_FILL   : COLOR_MISS_FILL;
        const stroke = isBeat ? COLOR_BEAT_STROKE : COLOR_MISS_STROKE;

        // Surprise chip y-position: floats above the actual bar top (or below
        // zero for loss years). Clamped to M_TOP to stay within the SVG bounds.
        const barTop = d.actual != null
          ? Math.min(yFor(d.actual), yZero)
          : yZero;
        const chipY = Math.max(M_TOP + 1, barTop - 2);

        return (
          <g key={`fy-${i}`}>
            {/* EPS surprise % chip — float above each bar when data available */}
            {hasSurprise && d.surprisePercent != null && (
              <text
                x={xCenter(i)}
                y={chipY}
                fill={isBeat ? COLOR_BEAT_STROKE : COLOR_MISS_STROKE}
                fontSize={7}
                fontFamily="monospace"
                textAnchor="middle"
                fontWeight="600"
              >
                {formatSurprise(d.surprisePercent)}
              </text>
            )}

            {/* Actual EPS bar */}
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

            {/* Estimate outline bar */}
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

            {/* FY label */}
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

      {/* Zero baseline */}
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
      </div>
    </div>
  );
}
