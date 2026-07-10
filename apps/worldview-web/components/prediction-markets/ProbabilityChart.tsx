/**
 * components/prediction-markets/ProbabilityChart.tsx — implied-probability over
 * time for a prediction market's outcomes (PLAN-0056 Wave E2, task 2).
 *
 * WHY THIS EXISTS: the list row's 60×14 sparkline shows only a coarse 7-point
 * YES trend. When a trader opens a market they need the real curve — every
 * outcome, over a chosen window, on a labelled 0–100% axis with hover values.
 * This is that curve.
 *
 * ── RECHARTS + HEX PALETTE (known bug class) ──
 * recharts renders to SVG, and SVG fill/stroke do NOT resolve CSS custom
 * properties (`hsl(var(--...))` paints nothing inside the chart). So every
 * colour here is a HEX literal that MIRRORS a Midnight Pro token. Keep in sync
 * with globals.css. This mirrors the EarningsBarChart pattern exactly.
 *
 * ── INTERVAL TOGGLE ──
 * A 1h/1d/1w toggle (shadcn Tabs) re-keys the query so each window is a distinct
 * cache slot. The chart OWNS the interval state (so it works standalone) but
 * also emits `onIntervalChange` so a parent (the detail Sheet) can mirror the
 * window when it computes the "moving" signal from the same series.
 */

"use client";
// WHY "use client": useQuery needs React context; recharts renders in the browser.

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { usePredictionMarketPriceHistory } from "@/lib/api/prediction-markets-hooks";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, LineChart as LineChartIcon } from "lucide-react";
import { pivotPricePoints, type ProbabilityChartRow } from "./probability-series";

// ── Palette (HEX mirrors of Midnight Pro tokens — SVG can't read CSS vars) ────
// A small categorical ramp so multi-outcome markets get distinct, legible lines.
// First entry (yellow --primary) is the dominant/YES line; the rest cycle.
const SERIES_COLORS = [
  "#FFD60A", // --primary (48 100% 52%) — YES / first outcome
  "#3B82F6", // blue — second outcome (e.g. NO)
  "#00D26A", // --positive teal — third
  "#FF3B5C", // --negative red — fourth
  "#A855F7", // violet — fifth+
];
const COLOR_GRID = "rgba(148,163,184,0.10)";
const COLOR_AXIS = "#71717A"; // muted-foreground for ticks

export type ProbabilityInterval = "1h" | "1d" | "1w";
const INTERVALS: ProbabilityInterval[] = ["1h", "1d", "1w"];

// ── Custom hover tooltip ──────────────────────────────────────────────────────
// WHY custom (not recharts default): the default prints raw dataKey/value pairs
// with no % formatting. We render each outcome's implied probability as a clean
// percentage, colour-matched to its line — the EarningsTooltip pattern.
interface TooltipPayloadItem {
  dataKey: string;
  value: number | null;
  color: string;
  payload: ProbabilityChartRow;
}
function ProbabilityTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}) {
  if (!active || !payload?.length) return null;
  const label = payload[0]?.payload?.label ?? "";
  return (
    <div className="rounded-[2px] border border-border bg-popover px-2 py-1.5 font-mono text-[11px]">
      <div className="mb-1 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
        {label}
      </div>
      <div className="space-y-0.5 tabular-nums">
        {payload.map((item) => (
          <div key={item.dataKey} className="flex justify-between gap-3">
            <span className="flex items-center gap-1 text-muted-foreground">
              <span
                className="inline-block h-[7px] w-[7px] rounded-full"
                style={{ backgroundColor: item.color }}
              />
              {item.dataKey}
            </span>
            <span className="text-foreground">
              {item.value == null ? "—" : `${Math.round(item.value)}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface ProbabilityChartProps {
  /** Polymarket conditionId / S3 market_id. "" keeps the query idle. */
  conditionId: string;
  /** Initial interval; defaults to daily bars. */
  defaultInterval?: ProbabilityInterval;
  /** Notified whenever the interval toggle changes (parent can mirror it). */
  onIntervalChange?: (interval: ProbabilityInterval) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ProbabilityChart({
  conditionId,
  defaultInterval = "1d",
  onIntervalChange,
}: ProbabilityChartProps) {
  // The chart owns the interval so it works standalone; onIntervalChange lets a
  // parent observe it (single source of truth stays here).
  const [interval, setInterval] = useState<ProbabilityInterval>(defaultInterval);

  const { data, isLoading, isError } = usePredictionMarketPriceHistory(conditionId, interval);

  const { rows, series } = pivotPricePoints(data?.points ?? []);

  const handleInterval = (next: ProbabilityInterval) => {
    setInterval(next);
    onIntervalChange?.(next);
  };

  return (
    <div data-testid="probability-chart" className="space-y-2">
      {/* ── Header: title + interval toggle ─────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Implied probability
        </span>
        {/* shadcn Tabs used purely as a segmented toggle. WHY Tabs (not raw
            buttons): keyboard nav + active-state a11y come for free, and it
            matches the terminal tab idiom used elsewhere. */}
        <Tabs value={interval} onValueChange={(v) => handleInterval(v as ProbabilityInterval)}>
          <TabsList variant="terminal" className="h-6">
            {INTERVALS.map((iv) => (
              <TabsTrigger
                key={iv}
                value={iv}
                variant="terminal"
                className="px-2 font-mono text-[9px] uppercase"
              >
                {iv}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* ── States: loading / error / empty / chart ─────────────────────────── */}
      {isLoading && <Skeleton data-testid="probability-chart-loading" className="h-[180px] w-full rounded-[2px]" />}

      {!isLoading && isError && (
        <div
          data-testid="probability-chart-error"
          className="flex h-[180px] flex-col items-center justify-center gap-1 text-muted-foreground"
        >
          <AlertCircle className="h-5 w-5" strokeWidth={1.5} />
          <p className="text-[11px]">Couldn&apos;t load price history</p>
        </div>
      )}

      {!isLoading && !isError && rows.length === 0 && (
        <div
          data-testid="probability-chart-empty"
          className="flex h-[180px] flex-col items-center justify-center gap-1 text-muted-foreground"
        >
          <LineChartIcon className="h-5 w-5" strokeWidth={1.5} />
          <p className="text-[11px]">No price history for this window</p>
        </div>
      )}

      {!isLoading && !isError && rows.length > 0 && (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={COLOR_GRID} vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: COLOR_AXIS, fontSize: 9, fontFamily: "monospace" }}
              axisLine={{ stroke: COLOR_GRID }}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              // Fixed 0–100 domain: implied probability is a percentage; a fixed
              // axis keeps the curve comparable across markets and intervals.
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              tickFormatter={(v: number) => `${v}%`}
              tick={{ fill: COLOR_AXIS, fontSize: 9, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
              width={34}
            />
            <Tooltip content={<ProbabilityTooltip />} cursor={{ stroke: "rgba(148,163,184,0.2)" }} />
            {series.map((s, i) => (
              <Line
                key={s}
                type="monotone"
                dataKey={s}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={1.5}
                dot={false}
                // WHY connectNulls: a series may miss a bucket (feed gap); joining
                // across it reads better than a broken line for a 0–100% curve.
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
