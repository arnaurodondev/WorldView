"use client";

/**
 * TerminalAreaChart — Recharts AreaChart styled for Terminal Dark.
 *
 * WHY separate from TerminalLineChart: Area charts are used specifically for
 * drawdown visualisation where the filled region below zero communicates loss
 * magnitude at a glance. The fill gradient and reference-line behaviour differ
 * enough from pure line charts to warrant a separate primitive.
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface AreaConfig {
  key: string;
  color: string;     // used for both stroke and fill (fill gets opacity 0.15)
  label?: string;
}

interface TerminalAreaChartProps {
  data: Array<{ date: string; [key: string]: number | string | null }>;
  areas: AreaConfig[];
  height: number;
  yTickFormatter?: (v: number) => string;
  tooltipFormatter?: (v: number) => string;
  /** Draw a horizontal reference line at y=0. Default true. */
  zeroLine?: boolean;
  /**
   * Accessible label describing the chart contents (D7 fix).
   *
   * WHY optional with default: Recharts renders an SVG tree with no inherent
   * semantic role. Wrapping it in role="img" + aria-label gives screen readers
   * a single readable announcement. Defaults to "Chart" so the accessible name
   * is never empty when callers haven't supplied one.
   */
  ariaLabel?: string;
}

const AXIS_STYLE = {
  fontSize: 9,
  fontFamily: "var(--font-mono, 'IBM Plex Mono', monospace)",
  fill: "hsl(var(--muted-foreground))",
};

export function TerminalAreaChart({
  data,
  areas,
  height,
  yTickFormatter,
  tooltipFormatter,
  zeroLine = true,
  ariaLabel,
}: TerminalAreaChartProps) {
  return (
    // WHY role="img" wrapper (D7 fix): see TerminalLineChart for full rationale.
    // Same pattern — Recharts SVG tree needs an accessible name for SR users.
    <div role="img" aria-label={ariaLabel ?? "Chart"} className="w-full">
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {areas.map((a) => (
            // WHY linearGradient: solid fill below the curve obscures the
            // underlying grid; a top→transparent gradient preserves grid context.
            <linearGradient
              key={`grad-${a.key}`}
              id={`grad-${a.key}`}
              x1="0" y1="0" x2="0" y2="1"
            >
              <stop offset="5%" stopColor={a.color} stopOpacity={0.2} />
              <stop offset="95%" stopColor={a.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid
          strokeDasharray="2 2"
          stroke="hsl(var(--border))"
          opacity={0.5}
        />
        <XAxis
          dataKey="date"
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tick={AXIS_STYLE}
          tickLine={false}
          axisLine={false}
          width={44}
          tickFormatter={yTickFormatter}
        />
        {zeroLine && (
          // WHY ReferenceLine at 0: drawdown charts are always ≤0; the zero
          // line anchors the reader's eye and makes "no drawdown" immediately obvious.
          <ReferenceLine
            y={0}
            stroke="hsl(var(--border))"
            strokeDasharray="3 3"
          />
        )}
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
        {areas.map((a) => (
          <Area
            key={a.key}
            dataKey={a.key}
            name={a.label ?? a.key}
            stroke={a.color}
            strokeWidth={1.5}
            fill={`url(#grad-${a.key})`}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
    </div>
  );
}
