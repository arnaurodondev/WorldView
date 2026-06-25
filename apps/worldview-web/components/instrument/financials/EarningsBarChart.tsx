/**
 * components/instrument/financials/EarningsBarChart.tsx — EPS beat/miss chart
 * (Wave-4 readability rebuild — replaces the hand-rolled 64px SVG).
 *
 * WHY THIS EXISTS: EPS history is the single most important trailing indicator
 * in fundamental analysis. A growing EPS trajectory justifies premium
 * multiples; a declining one warns of multiple compression. Per period we show
 * the ACTUAL EPS (filled bar, coloured by beat/miss) against the ESTIMATE
 * (ghost outline bar) so an analyst reads trajectory AND reliability at once.
 *
 * ── WHAT WAS WRONG WITH THE OLD CHART (the component this replaces) ──
 *   1. STATIC: a raw <svg> with NO hover — you could not read the exact EPS or
 *      surprise of a year; you had to eyeball bar heights. On a finance
 *      surface "hover to read the number" is table stakes.
 *   2. UNREADABLE SCALE: only 64px tall with `preserveAspectRatio="none"`,
 *      which STRETCHES the bars horizontally and distorts every height — the
 *      one thing a bar chart must get right. No Y-axis, no value labels, so
 *      the bars encoded magnitude with nothing to decode it against.
 *   3. NO TREND CUE: four disconnected bars; the YoY trajectory (the actual
 *      signal) was left for the eye to infer.
 *
 * ── WHAT THIS REBUILD DOES ──
 *   - recharts <ComposedChart> (already in the bundle — used by the equity
 *     curve, sparklines, sector donut; NO new dependency) at 168px so bars
 *     have real vertical resolution and a labelled Y axis.
 *   - HOVER TOOLTIP: exact Actual / Estimate / Surprise per year, so the chart
 *     is now interactive and self-documenting.
 *   - A dashed EPS TREND LINE over the actual bars makes the multi-year
 *     trajectory obvious at a glance (the real signal).
 *   - Per-bar value labels (the EPS number) so the chart is readable even
 *     without hovering — finance-grade density.
 *   - ESTIMATE rendered as a faint ghost bar behind ACTUAL so beat (actual >
 *     estimate, teal) vs miss (red) is immediately visible.
 *
 * DATA: S9 GET /v1/fundamentals/{id}/earnings-annual-trend → records with
 *   data = {date, epsActual, epsEstimate, surprisePercent (optional)}.
 * DESIGN: PRD-0088 §6.8; Midnight Pro palette (--positive / --negative /
 *   --primary tokens via the hex mirrors below — SVG fill can't read CSS vars).
 */

"use client";
// WHY "use client": useQuery needs React context; recharts renders in the browser.

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { PanelHeader } from "./PanelHeader";
import { formatPrice } from "@/lib/format";

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

// ── Palette ─────────────────────────────────────────────────────────────────
// WHY hex literals (not CSS vars): SVG fill/stroke do NOT resolve CSS custom
// properties, and recharts renders to SVG. These mirror the Midnight Pro
// tokens exactly: --positive 150 100% 41% (#00D26A), --negative 350 100% 62%
// (#FF3B5C), --primary 48 100% 52% (#FFD60A). Keep in sync with globals.css.
const COLOR_BEAT = "#00D26A"; // actual ≥ estimate → teal
const COLOR_MISS = "#FF3B5C"; // actual < estimate → red
const COLOR_TREND = "#FFD60A"; // yellow EPS trajectory line (primary accent)
const COLOR_ESTIMATE = "rgba(148,163,184,0.28)"; // faint ghost bar for estimate
const COLOR_GRID = "rgba(148,163,184,0.10)";
const COLOR_AXIS = "#71717A"; // muted-foreground for ticks/labels

// ── Row shape recharts consumes ─────────────────────────────────────────────
interface ChartRow {
  label: string; // "FY24"
  actual: number | null;
  estimate: number | null;
  surprisePercent: number | null;
  isBeat: boolean;
}

function formatFY(dateStr: string): string {
  try {
    return `FY${String(new Date(dateStr + "T00:00:00Z").getUTCFullYear()).slice(2)}`;
  } catch {
    return dateStr.slice(0, 4);
  }
}

// Surprise % is already in percent units from EODHD: +5.2 → "+5.2%".
function formatSurprise(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

// EPS axis/label formatter: "$6.75". Negative (loss years) → "-$0.42".
// WHY formatPrice: the architecture gate (no-off-palette-colors.test.ts) bans
// hand-built `$${value.toFixed(N)}` literals — all USD must go through the
// shared formatter so locale grouping is applied consistently.
function formatEps(v: number | null | undefined): string {
  if (v == null) return "—";
  return formatPrice(v);
}

// ── Custom hover tooltip ──────────────────────────────────────────────────────
// WHY a custom tooltip (not recharts default): the default renders raw
// dataKey/value pairs ("actual : 6.75") with no formatting and no surprise
// context. We render the three numbers an analyst actually wants — Actual,
// Estimate, Surprise — formatted as currency/percent and colour-coded by the
// beat/miss verdict, matching the EquityCurveTooltip pattern used elsewhere.
interface TooltipPayloadItem {
  payload: ChartRow;
}
function EarningsTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    // bg-popover (one elevation step above the panel) so the tooltip floats
    // clearly above the chart in dark mode — same rationale as EquityCurveTooltip.
    <div className="rounded-[2px] border border-border bg-popover px-2 py-1.5 font-mono text-[11px]">
      <div className="mb-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
        {row.label}
      </div>
      <div className="space-y-0.5 tabular-nums">
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Actual</span>
          <span className={row.isBeat ? "text-positive" : "text-negative"}>
            {formatEps(row.actual)}
          </span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Estimate</span>
          <span className="text-foreground">{formatEps(row.estimate)}</span>
        </div>
        {row.surprisePercent != null && (
          <div className="flex justify-between gap-3">
            <span className="text-muted-foreground">Surprise</span>
            <span className={row.isBeat ? "text-positive" : "text-negative"}>
              {formatSurprise(row.surprisePercent)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Per-bar value label ───────────────────────────────────────────────────────
// Renders the actual EPS number above each bar so the chart is readable WITHOUT
// hovering (Finviz-grade density). recharts passes x/y/width per bar; we centre
// the text over the bar top. `value` is the actual EPS for this row.
interface BarLabelProps {
  x?: number;
  y?: number;
  width?: number;
  value?: number | null;
}
function ActualValueLabel({ x = 0, y = 0, width = 0, value }: BarLabelProps) {
  if (value == null) return null;
  return (
    <text
      x={x + width / 2}
      y={y - 4}
      fill={COLOR_AXIS}
      fontSize={9}
      fontFamily="monospace"
      textAnchor="middle"
    >
      {formatEps(value)}
    </text>
  );
}

export function EarningsBarChart({ instrumentId }: EarningsBarChartProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    queryKey: ["earnings-history", instrumentId],
    queryFn: () => createGateway(accessToken).getEarningsHistory(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  const chartData: ChartRow[] = (data?.records ?? [])
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
    // WHY last 6 (was 4): recharts gives us room for more bars than the cramped
    // 64px SVG did, and 6 fiscal years shows a fuller multi-cycle trajectory.
    .slice(-6)
    .map((d) => {
      const isBeat = d.estimate != null ? (d.actual ?? 0) >= d.estimate : (d.actual ?? 0) >= 0;
      return {
        label: formatFY(d.date),
        actual: d.actual,
        estimate: d.estimate,
        surprisePercent: d.surprisePercent,
        isBeat,
      };
    });

  // Loading skeleton mirrors the final header + 168px chart shape so the
  // layout doesn't jump when data lands.
  if (isLoading) {
    return (
      <div
        role="status"
        aria-label="Loading earnings history"
        className="space-y-1 border-t border-border px-2 py-1"
      >
        <Skeleton className="h-6 w-1/3 rounded-[2px]" />
        <Skeleton className="h-[168px] rounded-[2px]" />
      </div>
    );
  }
  // Zero records → hide the whole panel: an empty chart band is chrome with no
  // information (preserved behaviour from the old component).
  if (chartData.length === 0) return null;

  // Hide the surprise leg of the legend when no period has surprise data.
  const hasSurprise = chartData.some((d) => d.surprisePercent != null);

  // Detect any loss year so we know to render the zero reference line.
  const hasNegative = chartData.some((d) => (d.actual ?? 0) < 0 || (d.estimate ?? 0) < 0);

  return (
    // Uniform 24px accent-bar header (PanelHeader) + a legend naming the
    // dual-bar + trend-line encoding.
    <div data-testid="earnings-panel" className="border-t border-border">
      <PanelHeader label="EARNINGS" meta="annual EPS · actual vs estimate">
        {/* Legend — mono 9px, mirrors the chart's exact colour treatment.
            aria-hidden: the header meta already names the encoding for SRs. */}
        <span
          aria-hidden
          className="flex items-center gap-2 font-mono text-[9px] text-muted-foreground/60"
        >
          <span className="flex items-center gap-1">
            <span className="inline-block h-[7px] w-[7px] bg-positive" />
            ACT
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-[7px] w-[7px] border border-foreground/30 bg-foreground/10" />
            EST
          </span>
          {hasSurprise && (
            <span className="flex items-center gap-1">
              <span className="inline-block h-[2px] w-[10px] bg-primary" />
              TREND
            </span>
          )}
        </span>
      </PanelHeader>

      {/* WHY 168px (was 64px): real vertical resolution so bar heights are
          honest and the Y axis is readable. ResponsiveContainer fills the
          panel width and re-fits on resize. */}
      <div className="px-2 py-2">
        <ResponsiveContainer width="100%" height={168}>
          <ComposedChart
            data={chartData}
            margin={{ top: 16, right: 8, bottom: 4, left: 0 }}
            // recharts attaches data-testid to the root <svg> — keeps the
            // existing test selector ("earnings-bar-chart") valid.
            data-testid="earnings-bar-chart"
          >
            <CartesianGrid stroke={COLOR_GRID} vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: COLOR_AXIS, fontSize: 9, fontFamily: "monospace" }}
              axisLine={{ stroke: COLOR_GRID }}
              tickLine={false}
            />
            <YAxis
              // EPS axis labelled in dollars so magnitude is decodable.
              tickFormatter={(v: number) => formatEps(v)}
              tick={{ fill: COLOR_AXIS, fontSize: 9, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
              width={44}
            />
            {/* Zero baseline only when a loss year exists (keeps the axis clean
                for the all-profit common case). */}
            {hasNegative && <ReferenceLine y={0} stroke="rgba(148,163,184,0.25)" strokeDasharray="2 2" />}
            <Tooltip content={<EarningsTooltip />} cursor={{ fill: "rgba(148,163,184,0.06)" }} />

            {/* ESTIMATE — faint ghost bar drawn FIRST (behind), so the eye reads
                the coloured actual bar against the analyst expectation. */}
            <Bar dataKey="estimate" fill={COLOR_ESTIMATE} radius={[1, 1, 0, 0]} barSize={18} isAnimationActive={false} />

            {/* ACTUAL — coloured per beat/miss via <Cell>. Value label above. */}
            <Bar dataKey="actual" radius={[1, 1, 0, 0]} barSize={26} isAnimationActive={false} label={<ActualValueLabel />}>
              {chartData.map((row, i) => (
                <Cell key={`bar-${i}`} fill={row.isBeat ? COLOR_BEAT : COLOR_MISS} />
              ))}
            </Bar>

            {/* TREND — dashed yellow line over the actual EPS so the multi-year
                trajectory (the real signal) is obvious at a glance. */}
            <Line
              type="monotone"
              dataKey="actual"
              stroke={COLOR_TREND}
              strokeWidth={1.5}
              strokeDasharray="3 2"
              dot={{ r: 2, fill: COLOR_TREND, strokeWidth: 0 }}
              isAnimationActive={false}
              // The line shares the actual dataKey; the bar already labels the
              // values, so suppress the line's own labels to avoid duplicates.
              label={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
