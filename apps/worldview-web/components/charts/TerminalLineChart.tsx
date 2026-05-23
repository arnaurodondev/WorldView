"use client";

/**
 * TerminalLineChart — thin Recharts wrapper styled for the Terminal Dark palette.
 *
 * WHY a wrapper instead of inline Recharts: every analytics chart in Wave G needs
 * identical grid/axis/tooltip styling. Centralising here means one change fixes all.
 *
 * WHY "use client": Recharts relies on DOM measurements (ResponsiveContainer uses
 * ResizeObserver). It cannot run on the server.
 */
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface LineConfig {
  key: string;       // data key in each datum object
  color: string;     // CSS color string or hsl(var(--token))
  dashed?: boolean;  // renders strokeDasharray="4 2"
  label?: string;    // legend label; falls back to key
}

interface TerminalLineChartProps {
  /** Array of data points. Each object must have a "date" string key plus
   *  numeric (or null) keys for each line. */
  data: Array<{ date: string; [key: string]: number | string | null }>;
  /** Line descriptors — one entry per series to render. */
  lines: LineConfig[];
  height: number;
  /** Formats Y-axis tick labels (e.g. v => `${(v*100).toFixed(1)}%`). */
  yTickFormatter?: (v: number) => string;
  /** Formats tooltip values (same signature as yTickFormatter). */
  tooltipFormatter?: (v: number) => string;
  /** Show the Recharts Legend below the chart. Default false. */
  showLegend?: boolean;
}

// Shared axis style — Terminal Dark palette uses muted-foreground for supporting text.
// text-[9px] is 9px which maps to fontSize 9 in SVG.
const AXIS_STYLE = {
  fontSize: 9,
  fontFamily: "var(--font-mono, 'IBM Plex Mono', monospace)",
  fill: "hsl(var(--muted-foreground))",
};

export function TerminalLineChart({
  data,
  lines,
  height,
  yTickFormatter,
  tooltipFormatter,
  showLegend = false,
}: TerminalLineChartProps) {
  return (
    // WHY w-full with explicit height: ResponsiveContainer needs a fixed height
    // dimension; the parent controls width via className.
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        {/* WHY opacity 0.5: full-opacity grid lines dominate the data ink in
            a dense terminal layout. Recharts default is solid — override here. */}
        <CartesianGrid
          strokeDasharray="2 2"
          stroke="hsl(var(--border))"
          opacity={0.5}
        />
        {/* X-axis: show at most 5 ticks to avoid label collision on narrow panels */}
        <XAxis
          dataKey="date"
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          // Recharts "preserveStartEnd" keeps the first/last tick and distributes
          // the rest evenly — good for variable-length date series.
        />
        <YAxis
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={yTickFormatter}
        />
        <Tooltip
          contentStyle={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
            borderRadius: 4,
            fontSize: 11,
            fontFamily: "var(--font-mono, 'IBM Plex Mono', monospace)",
            padding: "6px 8px",
          }}
          formatter={
            tooltipFormatter
              ? // WHY cast: Recharts v3 types ValueType as number|string|Array<...>|undefined;
                // our yTickFormatter only handles numbers. We guard the undefined case by
                // falling back to an empty string so TS is satisfied without unsafe casts.
                (value) => [
                  typeof value === "number" ? tooltipFormatter(value) : String(value ?? ""),
                  "",
                ]
              : undefined
          }
          labelStyle={AXIS_STYLE}
        />
        {showLegend && (
          <Legend
            wrapperStyle={{ fontSize: 9, fontFamily: AXIS_STYLE.fontFamily }}
          />
        )}
        {lines.map((l) => (
          <Line
            key={l.key}
            dataKey={l.key}
            name={l.label ?? l.key}
            stroke={l.color}
            strokeWidth={1.5}
            dot={false}
            // WHY dot={false}: at daily frequency over 1yr there are ~252 points;
            // dots at that density create visual noise with no information gain.
            strokeDasharray={l.dashed ? "4 2" : undefined}
            isAnimationActive={false}
            // WHY isAnimationActive=false: animations on every query-revalidation
            // flash the chart; terminal users find it distracting.
            connectNulls={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
