/**
 * components/portfolio/EquityCurveChart.tsx — Portfolio equity curve (PLAN-0046 Wave 5 / T-46-5-04)
 *
 * WHY THIS EXISTS: A line chart of portfolio total_value over time is the
 * single most important "how am I doing?" surface for a portfolio manager.
 * Every finance terminal (Bloomberg PORT, Schwab, Fidelity) puts the equity
 * curve at the top of the portfolio view. Numbers tell you the present;
 * the curve tells you the trajectory.
 *
 * WHY RECHARTS (not lightweight-charts): lightweight-charts is purpose-built
 * for OHLCV candlesticks (huge datasets, crosshair tooling). Equity curves
 * are simple line series — Recharts gives us a sane Tooltip API,
 * ResponsiveContainer, and tab-friendly resizing without the OHLCV-specific
 * baggage. Recharts is already in this project's bundle (used by sparklines,
 * earnings chart) — no new dependency.
 *
 * WHY PERIOD TOGGLE 1M/3M/6M/1Y/All (not 1D): the equity curve is a cumulative
 * series. 1D would only show one or two snapshot points which is meaningless;
 * the shortest informative window is 1M (~22 trading days).
 *
 * WHY HOVER TOOLTIP shows date + value + cost basis + return %: cost basis
 * lets the user instantly see "is the curve above or below my breakeven?";
 * return % lets them compare against the period selector.
 *
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/value-history → S1 daily snapshots.
 * The snapshot worker writes once per trading day at 21:30 UTC (after US close).
 * For a portfolio with no snapshots yet, the chart shows an empty state.
 *
 * DESIGN REFERENCE: PLAN-0046 Wave 5 spec, Midnight Pro palette.
 */

"use client";
// WHY "use client": Recharts is a client-side renderer; useState for the
// period selector; useQuery for fetching snapshots.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  type TooltipProps,
} from "recharts";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Period configuration ──────────────────────────────────────────────────────

/**
 * Period toggle options. The numeric value is days-back from today —
 * passed verbatim as the ``from`` query param to /value-history.
 *
 * "All" maps to a sentinel (10 years) so the API still receives a real
 * ``from`` date but in practice picks up every snapshot. An undefined
 * ``from`` would let the server's 90-day default kick in, defeating
 * the purpose of "All".
 */
const PERIODS = [
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "6M", days: 180 },
  { label: "1Y", days: 365 },
  { label: "All", days: 365 * 10 },
] as const;

type PeriodLabel = (typeof PERIODS)[number]["label"];

// ── Props ─────────────────────────────────────────────────────────────────────

export interface EquityCurveChartProps {
  /** Portfolio UUID (or ROOT id for the aggregate view). */
  portfolioId: string;
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

/**
 * Custom tooltip — Recharts default tooltip is too generic. We render
 * the date, total value, cost basis, and the cumulative return % so the
 * user gets all four numbers without leaving the chart.
 *
 * WHY tabular-nums + font-mono inline: the Tooltip is rendered inside
 * Recharts' SVG layer, OUTSIDE the main React tree the rest of the page
 * cascades from. Tailwind classes still apply (Recharts uses portals to
 * the document body), but inheriting font-mono from a parent is unreliable.
 * Setting it explicitly is the safe pattern.
 */
interface PointShape {
  date: string;
  value: number;
  cost_basis: number;
  cash: number;
}

function ChartTooltip({ active, payload }: TooltipProps<number, string>) {
  // payload[0].payload is the original data row (our PointShape).
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as PointShape;
  // WHY guard the cost basis: a brand-new portfolio with no transactions
  // would have cost_basis === 0 → division produces Infinity. Show "—".
  const returnPct =
    point.cost_basis > 0
      ? ((point.value - point.cost_basis) / point.cost_basis) * 100
      : null;

  return (
    <div
      // WHY raw bg-card / border-border / text-foreground tokens: Midnight Pro
      // palette is wired into Tailwind config — these CSS vars resolve to the
      // correct colours in dark mode without us referencing hex.
      className="bg-card border border-border rounded-[2px] px-2 py-1.5 shadow-md"
    >
      <div className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground mb-1">
        {point.date}
      </div>
      <div className="font-mono tabular-nums text-[11px] space-y-0.5">
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Value</span>
          <span className="text-foreground">{formatPrice(point.value)}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Cost</span>
          <span className="text-foreground">{formatPrice(point.cost_basis)}</span>
        </div>
        <div className="flex justify-between gap-3">
          <span className="text-muted-foreground">Return</span>
          <span
            className={
              returnPct == null
                ? "text-muted-foreground"
                : returnPct >= 0
                ? "text-positive"
                : "text-negative"
            }
          >
            {returnPct == null
              ? "—"
              : `${returnPct >= 0 ? "+" : ""}${formatPercent(returnPct / 100)}`}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── EquityCurveChart ─────────────────────────────────────────────────────────

export function EquityCurveChart({ portfolioId }: EquityCurveChartProps) {
  const { accessToken } = useAuth();

  // Default 3M — matches the Bloomberg PORT default. Long enough to show
  // a meaningful trend without compressing recent moves.
  const [period, setPeriod] = useState<PeriodLabel>("3M");

  // Compute `from` date from the period — server applies `to = today` default.
  const fromDate = useMemo(() => {
    const days = PERIODS.find((p) => p.label === period)!.days;
    const d = new Date();
    d.setDate(d.getDate() - days);
    // YYYY-MM-DD — matches the API's ISO-date contract.
    return d.toISOString().slice(0, 10);
  }, [period]);

  // Fetch via TanStack Query — keyed on (portfolioId, period) so
  // toggling the period triggers a fresh fetch but switching back
  // hits the cache.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["value-history", portfolioId, period],
    queryFn: () =>
      createGateway(accessToken).getValueHistory(portfolioId, {
        from: fromDate,
        granularity: "1d",
      }),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000, // 1 min — daily snapshots don't change intra-day
  });

  // ── Render: loading skeleton ────────────────────────────────────────────
  // WHY two skeleton blocks: matches the visual layout (header + chart area)
  // so the layout doesn't jump when data arrives.
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <div className="flex items-center justify-between h-6">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-40" />
        </div>
        <Skeleton className="flex-1 min-h-[180px] w-full" />
      </div>
    );
  }

  // ── Render: error state ──────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <ChartHeader period={period} setPeriod={setPeriod} />
        <div className="flex-1 min-h-[180px] flex items-center justify-center">
          <InlineEmptyState message="Failed to load equity curve." />
        </div>
      </div>
    );
  }

  // ── Render: empty state ──────────────────────────────────────────────────
  // BP-265 awareness: data.points may legitimately be empty (no snapshots
  // for the period — e.g. brand-new portfolio). Don't silently render an
  // empty chart — show an honest empty state.
  const points = data?.points ?? [];
  if (points.length === 0) {
    return (
      <div className="flex flex-col gap-2 h-full">
        <ChartHeader period={period} setPeriod={setPeriod} />
        <div className="flex-1 min-h-[180px] flex items-center justify-center">
          <InlineEmptyState message="No snapshots yet — the worker writes one per trading day." />
        </div>
      </div>
    );
  }

  // ── Render: chart ────────────────────────────────────────────────────────
  // WHY compute the colour from first→last value: rising = positive teal,
  // falling = negative red. This matches the colour convention the rest of
  // the app uses for P&L cells and gives the chart a glance-able verdict.
  const first = points[0]?.value ?? 0;
  const last = points[points.length - 1]?.value ?? 0;
  const isUp = last >= first;

  return (
    <div className="flex flex-col gap-2 h-full">
      <ChartHeader period={period} setPeriod={setPeriod} />
      <div className="flex-1 min-h-[180px]">
        {/* WHY ResponsiveContainer: the parent grid cell sizes dynamically;
            Recharts needs explicit numeric width/height OR a ResponsiveContainer
            to compute layout. */}
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={points}
            margin={{ top: 4, right: 8, left: 8, bottom: 4 }}
          >
            {/* Subtle grid — visible enough to read values, faint enough not
                to compete with the line. */}
            <CartesianGrid
              strokeDasharray="2 4"
              // WHY inline rgba: Recharts CartesianGrid does not respect Tailwind
              // CSS-var fills inside SVG; using a hard-coded but theme-appropriate
              // semi-transparent grey is the standard escape hatch.
              stroke="rgba(148, 163, 184, 0.15)"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "rgba(148,163,184,0.7)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={32}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "rgba(148,163,184,0.7)" }}
              tickLine={false}
              axisLine={false}
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => formatPrice(v)}
              width={64}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "rgba(148,163,184,0.3)" }} />
            <Line
              type="monotone"
              dataKey="value"
              stroke={isUp ? "var(--color-positive, #22d3aa)" : "var(--color-negative, #ef4444)"}
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── ChartHeader ──────────────────────────────────────────────────────────────

/**
 * Header above the chart: title on the left, period toggle on the right.
 * Extracted because the chart, error-state, and empty-state branches all
 * render the same header — DRY pays off the moment we add another state.
 */
function ChartHeader({
  period,
  setPeriod,
}: {
  period: PeriodLabel;
  setPeriod: (p: PeriodLabel) => void;
}) {
  return (
    <div className="flex items-center justify-between h-6 px-1">
      <h3 className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
        Equity Curve
      </h3>
      <div className="flex items-center gap-0.5">
        {PERIODS.map((p) => (
          <button
            key={p.label}
            onClick={() => setPeriod(p.label)}
            className={cn(
              "h-5 px-1.5 rounded-[2px] font-mono text-[10px] tabular-nums transition-colors",
              period === p.label
                ? "bg-primary/15 text-primary font-semibold"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
            )}
            aria-pressed={period === p.label}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
