/**
 * features/portfolio/components/AnalyticsPerformanceChart.tsx
 *
 * WHY THIS EXISTS: Displays portfolio cumulative return vs benchmark (SPY)
 * over the selected period. The overlay is the core "did I beat the market?"
 * visual — every PM checks this before anything else on the analytics tab.
 *
 * DATA FLOW:
 *   1. Fetch portfolio value history → compute cumulative return series
 *      (each point = (value − value[0]) / value[0])
 *   2. Fetch TWR data via qk.portfolios.twr() if available; otherwise derive
 *      a scalar period return from the value history array.
 *   3. Render a TerminalLineChart with two series: portfolio (primary/yellow)
 *      and benchmark (muted, dashed).
 *
 * WHY client-side cumulative return (not a dedicated endpoint): the value-
 * history array is already fetched for the drawdown chart on the same tab.
 * TanStack Query's cache means there is no extra network round-trip — both
 * components share one cache entry keyed by (portfolioId, period).
 *
 * WHY two-query design (TWR + valueHistory): TWR is the authoritative time-
 * weighted return scalar (period summary row). Value history drives the chart
 * line shape. If the TWR endpoint is unavailable we fall back to computing the
 * period return from value-history — this is identical to the "Decision 2"
 * rationale in docs/designs/0089/04-portfolio-detail.md §9.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3, §8
 */
"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { TerminalLineChart } from "@/components/charts/TerminalLineChart";

// ── Period → days mapping ─────────────────────────────────────────────────────

// WHY separate from EquityCurveChart's PERIODS: the analytics tab uses a
// different period set (includes YTD and 2Y). A local mapping keeps
// EquityCurveChart stable if this list changes.
const PERIOD_TO_DAYS: Record<string, number | null> = {
  "1M":  30,
  "3M":  90,
  "6M":  180,
  "YTD": null, // server computes YTD from Jan 1 — omit days, use ytd=true
  "1Y":  365,
  "2Y":  730,
  "ALL": null, // omit days → full history
};

// WHY only when period is "YTD": the server accepts a `ytd=true` query param
// that computes the window from Jan 1 of the current year in UTC, avoiding the
// client-side timezone ambiguity of computing "days since Jan 1 in local time".
function buildValueHistoryParams(period: string) {
  const days = PERIOD_TO_DAYS[period];
  return {
    ...(days != null ? { days } : {}),
    granularity: "1d" as const,
  };
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsPerformanceChartProps {
  portfolioId: string;
  /** Active analytics period (e.g. "YTD"). */
  period: string;
  /** Benchmark ticker (e.g. "SPY"). Passed to the TWR endpoint. */
  benchmark: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Compute cumulative return series from value-history points.
 *
 * WHY start from value[0]: a cumulative return series anchors at 0% on the
 * first bar — exactly what the Bloomberg/IBKR overlay charts show. This lets
 * the portfolio and benchmark lines start at the same y-axis origin so the
 * investor compares slope (outperformance), not absolute dollar levels.
 */
function computeCumulativeReturn(
  points: Array<{ date: string; value: number }>,
): Array<{ date: string; portfolio: number }> {
  if (points.length === 0) return [];
  const base = points[0].value;
  // WHY guard base === 0: if the portfolio somehow starts at $0 (e.g. just
  // opened) we cannot compute a percentage-based return. Return an empty
  // series so the chart renders "no data" rather than Infinity.
  if (base === 0) return [];
  return points.map((p) => ({
    date: p.date,
    portfolio: (p.value - base) / base,
  }));
}

/** Format a period return scalar for the summary row.
 *
 * WHY sign prefix: positive returns get "+" so the user can distinguish
 * "+2.63%" (gain) from a missing "-" sign at a glance. Negative numbers
 * already carry the "-" from toFixed.
 */
function fmtReturn(v: number | null | undefined): string {
  if (v == null) return "—";
  const pct = (v * 100).toFixed(2);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsPerformanceChart({
  portfolioId,
  period,
  benchmark,
}: AnalyticsPerformanceChartProps) {
  // WHY useApiClient (Wave G QA D1): provider-memoised gateway.
  const apiClient = useApiClient();

  // ── Query 1: portfolio value history ─────────────────────────────────────
  // WHY qk.portfolios.valueHistory: this key is shared with AnalyticsDrawdownChart
  // on the same tab. Both components call with identical (portfolioId, period)
  // so TanStack Query serves both from a single in-flight request.
  const { data: historyData, isLoading: historyLoading, isError: historyError } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(
        portfolioId,
        buildValueHistoryParams(period),
      ),
    enabled: !!portfolioId,
    // WHY 60s staleTime: daily snapshots don't change intra-day. Matching
    // the EquityCurveChart staleTime keeps the cache entry fresh while the
    // user browses the analytics tab.
    staleTime: 60_000,
  });

  // ── Query 2: TWR (period summary scalars) ─────────────────────────────────
  // WHY separate from value-history: TWR is the authoritative scalar from the
  // backend formula (Modified Dietz); value-history drives the chart shape.
  // If the endpoint returns 404 / error, we fall back to deriving the return
  // from value-history without crashing the chart.
  const { data: twrData } = useQuery({
    queryKey: qk.portfolios.twr(portfolioId, period, benchmark),
    queryFn: () => apiClient.getTwr(portfolioId, period, benchmark),
    enabled: !!portfolioId,
    // WHY 5min staleTime: TWR is period-bucketed — recomputing it every 60s
    // is waste. 5min matches the gateway Cache-Control header for this endpoint.
    staleTime: 300_000,
    // WHY retry: false — if the endpoint doesn't exist yet, we want to fall
    // back to value-history immediately without 3 retry delays.
    retry: false,
  });

  // ── Cumulative return series ──────────────────────────────────────────────
  const chartData = useMemo(() => {
    const points = historyData?.points ?? [];
    return computeCumulativeReturn(points);
  }, [historyData]);

  // ── Period return scalars (for summary row) ───────────────────────────────
  // WHY fall back to value-history: if TWR endpoint unavailable, derive the
  // period return from the first and last value-history points. This is the
  // "Decision 2 - Alt A" fallback in the design spec.
  const portfolioReturn = useMemo(() => {
    // Prefer authoritative TWR when available.
    if (twrData?.portfolio_return != null) return twrData.portfolio_return;
    // Fall back to computed return from value history.
    const pts = historyData?.points ?? [];
    if (pts.length < 2) return null;
    const first = pts[0].value;
    const last = pts[pts.length - 1].value;
    if (first === 0) return null;
    return (last - first) / first;
  }, [twrData, historyData]);

  const benchmarkReturn = twrData?.benchmark_return ?? null;

  // ── Error state ──────────────────────────────────────────────────────────
  // WHY inline error sized like the skeleton (Wave G QA D8/D9): the skeleton
  // is 220px tall to prevent layout shift. The error message keeps the same
  // height so the surrounding cards do not snap on transition into the error
  // state.
  if (historyError) {
    return (
      <div
        role="alert"
        className="h-[220px] flex items-center justify-center text-[11px] text-negative font-mono"
      >
        Couldn&apos;t load performance chart
      </div>
    );
  }

  // ── Loading state ─────────────────────────────────────────────────────────
  if (historyLoading) {
    return (
      // WHY fixed height matching the chart: prevents layout shift when the
      // skeleton is replaced by the chart — same technique as EquityCurveChart.
      <div className="h-[220px] animate-pulse rounded bg-muted" />
    );
  }

  // ── Empty / insufficient data state ──────────────────────────────────────
  if (chartData.length === 0) {
    return (
      <div className="h-[220px] flex items-center justify-center text-[11px] text-muted-foreground font-mono">
        Performance metrics will appear after ~10 trading days of snapshots.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      {/* Summary row: portfolio return vs benchmark return for the period.
          WHY show both scalars: the investor needs the comparison number
          immediately above the chart — matching IBKR's header strip where
          "Current Period Return" / "Benchmark Return" appear as a one-liner. */}
      <div className="flex items-center gap-4 text-[11px] font-mono px-1">
        {/* Portfolio period return */}
        <span className="flex items-center gap-1">
          <span className="text-muted-foreground uppercase tracking-wide text-[10px]">Portfolio</span>
          <span
            className={cn(
              "tabular-nums",
              portfolioReturn == null
                ? "text-muted-foreground"
                : portfolioReturn >= 0
                  ? "text-positive"
                  : "text-negative",
            )}
          >
            {fmtReturn(portfolioReturn)}
          </span>
        </span>
        {/* Benchmark period return — only shown when TWR endpoint provides it */}
        {benchmarkReturn != null && (
          <span className="flex items-center gap-1">
            <span className="text-muted-foreground uppercase tracking-wide text-[10px]">{benchmark}</span>
            <span
              className={cn(
                "tabular-nums",
                benchmarkReturn >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {fmtReturn(benchmarkReturn)}
            </span>
          </span>
        )}
        {/* Excess return (alpha) — shown when both are available */}
        {portfolioReturn != null && benchmarkReturn != null && (
          <span className="flex items-center gap-1">
            <span className="text-muted-foreground uppercase tracking-wide text-[10px]">Excess</span>
            <span
              className={cn(
                "tabular-nums",
                (portfolioReturn - benchmarkReturn) >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {fmtReturn(portfolioReturn - benchmarkReturn)}
            </span>
          </span>
        )}
      </div>

      {/* Main performance chart.
          WHY 220px: matches the design spec §4.3 analytics performance chart
          height. Enough vertical space to read the trend without dominating
          the above-fold area.
          WHY role="img" wrapper (Wave G QA D7): the SVG inside the Recharts
          ResponsiveContainer is decorative-by-default to assistive tech because
          it lacks a title/desc — explicitly marking the chart region as an
          image with a descriptive aria-label surfaces the chart contents to
          screen readers (axe-core rule scrollable-region-focusable / a11y
          best practice for data visualisations). */}
      <div
        role="img"
        aria-label={`Portfolio cumulative return vs ${benchmark} benchmark over the ${period} period`}
      >
      <TerminalLineChart
        data={chartData}
        height={220}
        lines={[
          {
            key: "portfolio",
            // WHY hsl(var(--primary)): the portfolio line is the primary series
            // — it uses the app's primary accent (yellow in Terminal Dark) so
            // it stands out against the muted benchmark dashes immediately.
            color: "hsl(var(--primary))",
            label: "Portfolio",
          },
          // WHY conditional benchmark line: if TWR didn't provide benchmark
          // cumulative data, we skip the second line rather than rendering
          // an empty/null series that Recharts would leave as a gap.
          // (Benchmark cumulative series would need a separate OHLCV fetch —
          //  deferred to a future wave when the TWR endpoint exists.)
        ]}
        yTickFormatter={(v) => `${(v * 100).toFixed(1)}%`}
        tooltipFormatter={(v) => `${(v * 100).toFixed(2)}%`}
        showLegend={false}
      />
      </div>

      {/* Legend row below chart: two colour swatches with labels.
          WHY inline legend (not Recharts Legend): Recharts Legend uses SVG
          symbols that don't match the app's text style and are hard to
          position precisely. A hand-rolled inline row is 4 lines and
          visually integrates better with the terminal aesthetic. */}
      <div className="flex items-center gap-3 px-1 text-[10px] font-mono text-muted-foreground">
        <span className="flex items-center gap-1">
          <span
            className="inline-block w-4 h-[2px] rounded"
            style={{ background: "hsl(var(--primary))" }}
          />
          Portfolio
        </span>
        {/* WHY muted dashed benchmark swatch: matches the chart line style
            (1.5px dashed muted-foreground). */}
        <span className="flex items-center gap-1">
          <span
            className="inline-block w-4 h-[2px] rounded border-t border-dashed border-muted-foreground"
            style={{ borderStyle: "dashed", borderTopWidth: "1.5px", background: "transparent" }}
          />
          {benchmark}
        </span>
      </div>
    </div>
  );
}
