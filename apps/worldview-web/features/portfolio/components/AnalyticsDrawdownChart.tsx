/**
 * features/portfolio/components/AnalyticsDrawdownChart.tsx
 *
 * WHY THIS EXISTS: The underwater / drawdown chart is the canonical risk visual
 * in institutional analytics (Bloomberg PORT, IBKR Portfolio Analyst). It shows
 * the portfolio's distance from its prior high-water mark at every point in time.
 * A deep trough with a long recovery tells the investor how long they could have
 * been underwater — a critical risk dimension that volatility alone doesn't capture.
 *
 * DATA SOURCE: Fetches value-history (same cache entry as AnalyticsPerformanceChart
 * on the same tab). Drawdown is computed client-side in O(n) — no extra round-trip.
 *
 * FORMULA: For each point i, drawdown[i] = (value[i] − running_max[i]) / running_max[i].
 * This is always ≤ 0 by construction. The TerminalAreaChart fills the region below
 * zero with a red gradient so the depth is immediately readable.
 *
 * WHY client-side (Decision 5 in the design spec): the formula is well-known,
 * trivially O(n), and reuses an already-cached array. Backend extending risk-metrics
 * with `?include=drawdown_series` is deferred to a future wave.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3, §9 Decision 5
 */
"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { TerminalAreaChart } from "@/components/charts/TerminalAreaChart";

// ── Period → days mapping (shared with AnalyticsPerformanceChart) ─────────────

// WHY duplicate (not imported): AnalyticsPerformanceChart is a sibling — importing
// a non-exported constant from a sibling would create an implicit coupling. Each
// component is self-contained. Future refactor: move to a shared analytics utils
// module when ≥3 components need the same mapping.
const PERIOD_TO_DAYS: Record<string, number | null> = {
  "1M":  30,
  "3M":  90,
  "6M":  180,
  "YTD": null,
  "1Y":  365,
  "2Y":  730,
  "ALL": null,
};

function buildValueHistoryParams(period: string) {
  const days = PERIOD_TO_DAYS[period];
  return {
    ...(days != null ? { days } : {}),
    granularity: "1d" as const,
  };
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsDrawdownChartProps {
  portfolioId: string;
  /** Active analytics period (e.g. "YTD"). */
  period: string;
}

// ── Drawdown computation ──────────────────────────────────────────────────────

/**
 * Compute the drawdown series from portfolio value history points.
 *
 * WHY running_max (not global max): true drawdown is computed relative to the
 * running maximum — the question is "how far below my best-ever value am I at
 * this point?", not "how far from the all-time high after seeing the full series?".
 * Using the global max would show the final data points as severely underwater
 * even when the portfolio is at a new high (because you'd compare to the future max).
 *
 * Returns { date, drawdown } points where drawdown ≤ 0. Empty array if
 * fewer than 2 points (no meaningful drawdown to show).
 */
function computeDrawdown(
  points: Array<{ date: string; value: number }>,
): Array<{ date: string; drawdown: number }> {
  if (points.length < 2) return [];

  let runningMax = points[0].value;
  return points.map((p) => {
    // Update the running maximum so we always compare current value
    // against the highest it has ever been up to this point.
    if (p.value > runningMax) runningMax = p.value;

    // WHY guard runningMax === 0: prevents division by zero for brand-new
    // portfolios where the first snapshot has $0 value.
    const drawdown = runningMax === 0 ? 0 : (p.value - runningMax) / runningMax;

    return { date: p.date, drawdown };
  });
}

/**
 * Extract the maximum drawdown scalar from the drawdown series.
 *
 * WHY extract here (not pass from RiskMetricsResponse): the chart computes
 * the full series anyway; extracting the min is a single pass O(n) operation.
 * Avoids an extra query for risk-metrics just to show the label.
 */
function getMaxDrawdown(series: Array<{ drawdown: number }>): number | null {
  if (series.length === 0) return null;
  return Math.min(...series.map((p) => p.drawdown));
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsDrawdownChart({
  portfolioId,
  period,
}: AnalyticsDrawdownChartProps) {
  const { accessToken } = useAuth();

  // WHY qk.portfolios.valueHistory: identical key to AnalyticsPerformanceChart
  // on the same tab — TanStack Query serves this component from the warm cache
  // left by the performance chart's earlier fetch. Zero extra network calls.
  const { data: historyData, isLoading } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      createGateway(accessToken).getValueHistory(
        portfolioId,
        buildValueHistoryParams(period),
      ),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // Drawdown series — O(n) over value-history points.
  const drawdownSeries = useMemo(() => {
    const points = historyData?.points ?? [];
    return computeDrawdown(points);
  }, [historyData]);

  const maxDrawdown = useMemo(
    () => getMaxDrawdown(drawdownSeries),
    [drawdownSeries],
  );

  // ── Loading state ─────────────────────────────────────────────────────────
  if (isLoading) {
    return <div className="h-[120px] animate-pulse rounded bg-muted" />;
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (drawdownSeries.length === 0) {
    return (
      <div className="h-[120px] flex items-center justify-center text-[11px] text-muted-foreground font-mono">
        No drawdowns recorded yet.
      </div>
    );
  }

  // Format the max drawdown label: e.g. "-8.24%"
  // WHY show "0.00%" for 0: a portfolio that never dipped shows a truthful
  // zero rather than "—" which implies missing data.
  const maxDdLabel =
    maxDrawdown != null
      ? `${(maxDrawdown * 100).toFixed(2)}%`
      : "—";

  return (
    <div className="flex flex-col gap-1">
      {/* Label row above the chart.
          WHY "MAX DRAWDOWN: -8.24%" above (not as chart annotation): chart
          annotations in Recharts require a custom label component, which is
          harder to style and breaks the terminal aesthetic. A simple text row
          above the chart gives the same information at zero complexity cost. */}
      <div className="text-[10px] font-mono text-muted-foreground px-1 uppercase tracking-wide">
        Max Drawdown:&nbsp;
        <span
          className={
            maxDrawdown != null && maxDrawdown < 0
              ? "text-negative"
              : "text-foreground"
          }
        >
          {maxDdLabel}
        </span>
      </div>

      {/* Drawdown area chart.
          WHY hsl(var(--destructive)): drawdown represents loss magnitude —
          the destructive (red) colour token communicates this semantically
          without requiring a custom token. Consistent with the convention
          used by RiskMetricsStrip's drawdown tile colour logic. */}
      <TerminalAreaChart
        data={drawdownSeries}
        height={120}
        areas={[
          {
            key: "drawdown",
            // WHY destructive: red fill signals "loss from peak" — the only
            // correct semantic for an underwater equity chart.
            color: "hsl(var(--destructive))",
            label: "Drawdown",
          },
        ]}
        yTickFormatter={(v) => `${(v * 100).toFixed(1)}%`}
        tooltipFormatter={(v) => `${(v * 100).toFixed(2)}%`}
        zeroLine={true}
      />
    </div>
  );
}
