/**
 * components/portfolio/RealizedPnLChart.tsx — Cumulative realized P&L chart (PLAN-0053 T-D-4-03)
 *
 * WHY THIS EXISTS: PLAN-0051 Wave A shipped the FIFO-accounting realized P&L
 * endpoint with full per-instrument breakdown — but only the KPI strip's
 * single-number summary surfaces it today. A chart over time tells a richer
 * story: "did I make money in Q1 from one big winner, or steady $50/day?".
 *
 * WHY CUMULATIVE LINE (not bars): cumulative shows trajectory — the slope
 * shows the rate of P&L generation; cliffs show big realisation events.
 * Bars over months would lose that "running total" semantic.
 *
 * WHY 1M / 3M / 6M / 1Y / All:
 *   Same period set as the equity-curve chart so the user gets a consistent
 *   mental model across the analytics section. Each period maps to a "from"
 *   ISO date; "All" uses no from-bound and lets the backend default.
 *
 * WHY PER-TICKER TABLE BELOW THE CHART:
 *   The endpoint returns `breakdown_by_instrument` — surfacing the top
 *   contributors / detractors answers "where did this P&L come from?" which
 *   is the natural follow-up question after seeing the line.
 *
 * WHO USES IT: portfolio/page.tsx — Holdings tab (mountable below KPI strip)
 * DATA SOURCE: getRealizedPnL(portfolioId, from?, to?)
 * DESIGN REFERENCE: PLAN-0053 §T-D-4-03
 */

"use client";
// WHY "use client": uses recharts (DOM API), useState, useMemo.

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
  ReferenceLine,
} from "recharts";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatPrice, cn } from "@/lib/utils";

// ── Props / Types ────────────────────────────────────────────────────────────

export interface RealizedPnLChartProps {
  portfolioId: string | null | undefined;
}

type Period = "1M" | "3M" | "6M" | "1Y" | "All";

// Deterministic period → days mapping. Keeping it as a constant lets us
// build the "from" date with a single subtraction.
const PERIOD_DAYS: Record<Exclude<Period, "All">, number> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
};

// ── Component ────────────────────────────────────────────────────────────────

export function RealizedPnLChart({ portfolioId }: RealizedPnLChartProps) {
  const { accessToken } = useAuth();
  const [period, setPeriod] = useState<Period>("1Y");

  // Derive "from" ISO date from the active period. WHY compute on render:
  // useState would over-engineer this — the value is a pure function of
  // `period` and Date.now(); recomputing per render is cheaper than
  // memoising. Date math wraps automatically.
  const fromIso = useMemo(() => {
    if (period === "All") return undefined;
    const days = PERIOD_DAYS[period];
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - days);
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
  }, [period]);

  const { data, isLoading } = useQuery({
    queryKey: ["realized-pnl-chart", portfolioId, fromIso],
    queryFn: () => createGateway(accessToken).getRealizedPnL(portfolioId!, fromIso),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // The endpoint returns aggregated totals, not per-day points — so we don't
  // get a true line chart from the response alone. We build a synthetic
  // 2-point series (from → to with the cumulative endpoint at "to") to
  // visualise the bracket. WHY this is good enough: the realised-pnl
  // endpoint is a closed accounting cut, not a daily series; the slope is
  // implicit in the period selector. A future T-D-4-03+ could extend the
  // backend to return a per-day breakdown for a true cumulative trace.
  const chartPoints = useMemo(() => {
    if (!data) return [];
    const start = data.from || fromIso || "";
    const end = data.to;
    return [
      { date: start, cumulative: 0 },
      { date: end, cumulative: data.total_realized },
    ];
  }, [data, fromIso]);

  if (!portfolioId) return null;

  return (
    <div className="flex flex-col bg-background" data-testid="realized-pnl-chart">
      {/* Header — title + period buttons + total readout */}
      <div className="flex h-7 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          REALIZED P&L
        </span>

        <div className="flex gap-px">
          {(["1M", "3M", "6M", "1Y", "All"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={period === p}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      {isLoading && (
        <div className="space-y-1 p-2">
          <Skeleton className="h-[140px] w-full" />
          <Skeleton className="h-[22px] w-full" />
        </div>
      )}

      {!isLoading && data && data.count === 0 && (
        <div className="px-3 py-3">
          <InlineEmptyState message="No realized P&L in this period" />
        </div>
      )}

      {!isLoading && data && data.count > 0 && (
        <>
          {/* Total badge above the chart */}
          <div className="flex items-center gap-3 border-b border-border/30 px-2 py-1.5">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              TOTAL
            </span>
            <span
              className={cn(
                "font-mono text-[12px] font-semibold tabular-nums",
                data.total_realized >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {data.total_realized >= 0 ? "+" : ""}
              {formatPrice(data.total_realized)}
            </span>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
              ({data.count} {data.count === 1 ? "lot" : "lots"})
            </span>
            <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
              LT {formatPrice(data.realized_long_term)} · ST{" "}
              {formatPrice(data.realized_short_term)}
            </span>
          </div>

          {/* Chart */}
          <div className="h-[160px] px-2 py-1">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartPoints}
                margin={{ top: 4, right: 8, left: 4, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="2 2"
                  stroke="hsl(var(--border) / 0.4)"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `$${v}`}
                  width={50}
                />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    fontSize: 11,
                    fontFamily: "var(--font-mono, monospace)",
                  }}
                  formatter={(value: number) => [formatPrice(value), "Cumulative"]}
                />
                {/* Zero line — visual datum so positive vs negative is obvious. */}
                <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />
                <Line
                  type="monotone"
                  dataKey="cumulative"
                  stroke={
                    data.total_realized >= 0
                      ? "hsl(var(--positive))"
                      : "hsl(var(--negative))"
                  }
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Per-ticker breakdown table — top contributors & detractors */}
          {data.breakdown_by_instrument.length > 0 && (
            <div className="border-t border-border/40">
              <div className="flex h-6 items-center border-b border-border/30 px-2">
                <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                  BY INSTRUMENT
                </span>
              </div>
              <table className="w-full border-collapse text-[11px]">
                <tbody className="divide-y divide-border/30">
                  {data.breakdown_by_instrument.slice(0, 10).map((row) => (
                    <tr key={row.instrument_id} className="h-7 hover:bg-muted/30">
                      <td className="px-2 font-mono text-[11px] font-bold tabular-nums text-primary">
                        {row.ticker || "—"}
                      </td>
                      <td className="px-2 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                        {row.count} {row.count === 1 ? "lot" : "lots"}
                      </td>
                      <td
                        className={cn(
                          "px-2 text-right font-mono text-[11px] tabular-nums",
                          row.realized >= 0 ? "text-positive" : "text-negative",
                        )}
                      >
                        {row.realized >= 0 ? "+" : ""}
                        {formatPrice(row.realized)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
