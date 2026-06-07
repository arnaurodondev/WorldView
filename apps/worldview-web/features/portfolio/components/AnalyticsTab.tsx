/**
 * features/portfolio/components/AnalyticsTab.tsx — Portfolio Analytics tab.
 * (Wave G, PRD-0089 / PLAN-0090)
 *
 * WHY THIS EXISTS: The portfolio page currently has Holdings / Transactions /
 * Watchlist tabs. Wave G adds "Analytics" as a third data surface — TWR vs
 * benchmark, drawdown chart, 10-tile risk strip, period returns table, and
 * contribution-to-return attribution.
 *
 * LAYOUT (12-column grid):
 *   Period selector row (h=28px, full-width)
 *   ┌─────────────────────────────────────────────────────┬──────────────┐
 *   │ Performance chart col-span-9                        │ Risk sidebar │
 *   ├─────────────────────────────────────────────────────┤ col-span-3   │
 *   │ Drawdown chart col-span-9 (shares x-axis)           │              │
 *   └─────────────────────────────────────────────────────┴──────────────┘
 *   ┌───────────────────────────────┬────────────────────────────────────┐
 *   │ Period Returns col-span-6     │ Attribution col-span-6             │
 *   └───────────────────────────────┴────────────────────────────────────┘
 *
 * WHY the risk sidebar is separate from the chart (Decision 4 in spec §9):
 * 11 vertical tiles in a 200px column let the chart use full 720px width
 * while still showing every IBKR-equivalent metric. A horizontal 11-tile
 * strip would need ~1100px — too wide for standard laptop viewports.
 *
 * WHY TWR computed client-side (Decision 2 in spec §9):
 * The value-history endpoint is already cached by EquityCurveChart. Reusing
 * the same cache entry avoids a new round-trip. Formula: (last/first) - 1
 * from the daily snapshot series.
 *
 * WHO USES IT: portfolio/page.tsx (tab value="analytics")
 * DATA SOURCE:
 *   - qk.portfolios.valueHistory → equity curve + drawdown + period returns
 *   - qk.portfolios.riskMetrics  → Sharpe / Sortino / Beta / Drawdown
 *   - qk.portfolios.performance  → Calmar / Win Rate (via /performance endpoint)
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3
 */

"use client";
// WHY "use client": useQuery, useQueryState (period URL state), recharts chart
// components require a browser DOM.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

import { cn } from "@/lib/utils";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { AnalyticsPeriodSelector } from "./AnalyticsPeriodSelector";
import { AnalyticsPeriodReturnsTable } from "./AnalyticsPeriodReturnsTable";
import type { RiskMetricsResponse, ValueHistoryPoint } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsTabProps {
  /** Active portfolio UUID. */
  portfolioId: string;
}

// ── Period → days map ─────────────────────────────────────────────────────────

const PERIOD_DAYS: Record<string, number> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "YTD": 365, // server handles real YTD
  "1Y": 365,
  "2Y": 730,
  "ALL": 1825,
};

// ── Format helpers ────────────────────────────────────────────────────────────

function fmtPct(val: number | null | undefined, fractions = 2): string {
  if (val == null || Number.isNaN(val)) return "—";
  const pct = (val * 100).toFixed(fractions);
  return val >= 0 ? `+${pct}%` : `${pct}%`;
}

function fmtNum(val: number | null | undefined, fractions = 2): string {
  if (val == null || Number.isNaN(val)) return "—";
  return val.toFixed(fractions);
}

/** Compute drawdown series from value-history points. */
function computeDrawdownSeries(
  points: ValueHistoryPoint[],
): Array<{ date: string; drawdown: number }> {
  if (points.length === 0) return [];
  let peak = points[0].value;
  return points.map((p) => {
    if (p.value > peak) peak = p.value;
    const dd = peak > 0 ? (p.value - peak) / peak : 0;
    return { date: p.date, drawdown: dd };
  });
}

// ── Risk sidebar ──────────────────────────────────────────────────────────────

interface RiskSidebarProps {
  portfolioId: string;
  period: string;
}

/**
 * RiskSidebar — 11-tile vertical strip of risk metrics.
 *
 * WHY 11 tiles (not the existing 5-tile RiskMetricsStrip): Design Decision 4
 * (spec §9.4) adds TWR, Benchmark-TWR, Alpha, Calmar, and Win Rate to the
 * existing 5-tile strip (Sharpe/Sortino/Beta/MaxDD/Vol). 11 tiles in a narrow
 * column > 2-row strip that needs extra horizontal space.
 */
function RiskSidebar({ portfolioId, period }: RiskSidebarProps) {
  const apiClient = useApiClient();

  const { data: risk, isLoading: riskLoading } = useQuery<RiskMetricsResponse>({
    queryKey: qk.portfolios.riskMetrics(portfolioId),
    queryFn: () =>
      apiClient.getRiskMetrics(portfolioId, PERIOD_DAYS[period] ?? 90),
    staleTime: 5 * 60_000,
    enabled: Boolean(portfolioId),
  });

  // WHY perfLoading = false: no dedicated performance query for Calmar/WinRate yet.
  // Once the analytics endpoint ships, replace this with a real useQuery.
  // Keeping perfLoading as a constant false keeps the isLoading gate below
  // correct without triggering the ESLint "unused variable" rule on `perf`.
  const perfLoading = false;

  const tiles: Array<{
    label: string;
    value: string;
    hint?: string;
    colorClass?: string;
    ariaLabel?: string;
  }> = [
    {
      label: "MAX DD",
      value: fmtPct(risk?.drawdown_max),
      colorClass:
        risk?.drawdown_max == null
          ? "text-muted-foreground"
          : risk.drawdown_max < -0.1
          ? "text-negative"
          : "text-foreground",
      ariaLabel: `Max drawdown: ${fmtPct(risk?.drawdown_max)}`,
      hint: `${PERIOD_DAYS[period] ?? 90}D`,
    },
    {
      label: "CURR DD",
      value: fmtPct(risk?.drawdown_current),
      colorClass:
        risk?.drawdown_current == null
          ? "text-muted-foreground"
          : risk.drawdown_current < -0.05
          ? "text-negative"
          : "text-foreground",
      ariaLabel: `Current drawdown: ${fmtPct(risk?.drawdown_current)}`,
    },
    {
      label: "VOL ANN",
      value: fmtPct(risk?.volatility_annualized),
      colorClass: "text-foreground",
      ariaLabel: `Annualised volatility: ${fmtPct(risk?.volatility_annualized)}`,
      hint: "ann.",
    },
    {
      label: "SHARPE",
      value: fmtNum(risk?.sharpe),
      colorClass:
        risk?.sharpe == null
          ? "text-muted-foreground"
          : risk.sharpe > 1
          ? "text-positive"
          : risk.sharpe < 0
          ? "text-negative"
          : "text-foreground",
      ariaLabel: `Sharpe ratio: ${fmtNum(risk?.sharpe)}`,
      hint: `${PERIOD_DAYS[period] ?? 90}D`,
    },
    {
      label: "SORTINO",
      value: fmtNum(risk?.sortino),
      colorClass:
        risk?.sortino == null
          ? "text-muted-foreground"
          : risk.sortino > 1
          ? "text-positive"
          : risk.sortino < 0
          ? "text-negative"
          : "text-foreground",
      ariaLabel: `Sortino ratio: ${fmtNum(risk?.sortino)}`,
    },
    {
      label: "BETA·SPY",
      value: fmtNum(risk?.beta_vs_spy),
      colorClass: "text-foreground",
      ariaLabel: `Beta vs SPY: ${fmtNum(risk?.beta_vs_spy)}`,
      hint: "vs SPY",
    },
    // Performance tiles — Calmar and Win Rate are backend-pending (—) until
    // GET /v1/portfolios/{id}/analytics ships. Slots are pre-wired so they
    // auto-populate when data becomes available.
    {
      label: "CALMAR",
      // WHY "—": S9 does not yet expose a Calmar endpoint. Placeholder per spec.
      value: "—",
      colorClass: "text-muted-foreground",
      ariaLabel: "Calmar ratio: unavailable",
    },
    {
      label: "WIN RATE",
      // WHY "—": same rationale as CALMAR — backend-pending.
      value: "—",
      colorClass: "text-muted-foreground",
      ariaLabel: "Win rate: unavailable",
    },
  ];

  // WHY include perfLoading: the tile list includes performance tiles that will
  // populate once the backend analytics endpoint ships. Keep the loading gate
  // consistent so all tiles show skeletons simultaneously.
  const isLoading = riskLoading || perfLoading;

  return (
    // WHY border border-border rounded-[2px]: consistent with every panel in
    // the analytics tab — no shadows, no elevation cards (design spec §6).
    <div className="border border-border rounded-[2px] h-full overflow-hidden">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          aria-label={tile.ariaLabel}
          className="flex flex-col px-2 py-1.5 border-b border-border last:border-0"
        >
          <div className="flex items-baseline justify-between gap-1">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {tile.label}
            </span>
            {tile.hint && (
              <span className="text-[9px] text-muted-foreground/60">
                {tile.hint}
              </span>
            )}
          </div>
          {isLoading ? (
            <Skeleton className="h-[20px] w-14 mt-0.5" />
          ) : (
            <span
              className={cn(
                "font-mono tabular-nums text-[13px] leading-none mt-0.5",
                tile.colorClass ?? "text-foreground",
              )}
            >
              {tile.value}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Performance chart ─────────────────────────────────────────────────────────

interface PerformanceChartProps {
  portfolioId: string;
  period: string;
}

/**
 * PerformanceChart — portfolio equity curve with recharts LineChart.
 *
 * WHY recharts (not lightweight-charts): the codebase already uses recharts
 * extensively (EquityCurveChart.tsx). Adding lightweight-charts as a second
 * chart library would double the charting bundle. The spec allows either.
 *
 * WHY no benchmark series yet: the backend risk-metrics endpoint is hard-coded
 * to SPY but doesn't return a daily SPY series. Until `GET /v1/portfolios/{id}/twr`
 * ships, the benchmark line is omitted (Decision 2, spec §9.2).
 */
function PerformanceChart({ portfolioId, period }: PerformanceChartProps) {
  const apiClient = useApiClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        days: PERIOD_DAYS[period] ?? 90,
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  if (isLoading) {
    return <Skeleton className="h-[180px] w-full" />;
  }

  if (isError || !data) {
    return (
      <div className="h-[180px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-negative font-mono">
          Couldn&apos;t load performance series.
        </p>
      </div>
    );
  }

  const points = data.points ?? [];

  if (points.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-muted-foreground font-mono">
          Performance metrics will appear after ~10 trading days of snapshots.
        </p>
      </div>
    );
  }

  // ── Custom tooltip ─────────────────────────────────────────────────────
  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ value: number }>;
    label?: string;
  }) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-card border border-border rounded-[2px] px-2 py-1.5">
        <p className="text-[10px] text-muted-foreground">{label}</p>
        <p className="text-[11px] font-mono tabular-nums text-foreground">
          ${payload[0].value.toLocaleString("en-US", { maximumFractionDigits: 0 })}
        </p>
      </div>
    );
  };

  return (
    <div
      role="img"
      aria-label={`Portfolio equity curve for ${period} period`}
      className="h-[180px] border border-border rounded-[2px]"
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "var(--muted-foreground, #888)" }}
            tickLine={false}
            axisLine={false}
            // Show max 5 x-ticks as per design spec §4.3
            interval={Math.max(0, Math.floor(points.length / 5) - 1)}
            // WHY slice(5,10): convert "YYYY-MM-DD" to "MM-DD" for compact labels
            tickFormatter={(v: string) => (typeof v === "string" ? v.slice(5) : v)}
          />
          <YAxis
            tick={{ fontSize: 9, fill: "var(--muted-foreground, #888)" }}
            tickLine={false}
            axisLine={false}
            width={50}
            tickFormatter={(v: number) =>
              `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}`
            }
          />
          <Tooltip content={<CustomTooltip />} />
          {/* Portfolio equity line — 1.5px solid primary (design spec §6) */}
          <Line
            type="monotone"
            dataKey="value"
            stroke="var(--primary, #3b82f6)"
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3 }}
          />
          {/* Cost-basis line — dashed muted (helps visualise unrealised gain area) */}
          <Line
            type="monotone"
            dataKey="cost_basis"
            stroke="var(--muted-foreground, #888)"
            strokeWidth={1}
            strokeDasharray="4 2"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Drawdown chart ────────────────────────────────────────────────────────────

interface DrawdownChartProps {
  portfolioId: string;
  period: string;
}

/**
 * DrawdownChart — underwater chart (always ≤ 0), red-shaded area below zero.
 *
 * WHY client-side computation (Decision 5, spec §9.5): the formula is
 * `1 - value/runningPeak` rolled over the value-history series. O(n) over the
 * already-cached points, ~50 lines, zero new endpoint.
 *
 * Data reuse: shares the same qk.portfolios.valueHistory cache key as
 * PerformanceChart — single in-flight request, two chart consumers.
 */
function DrawdownChart({ portfolioId, period }: DrawdownChartProps) {
  const apiClient = useApiClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        days: PERIOD_DAYS[period] ?? 90,
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  if (isLoading) {
    return <Skeleton className="h-[100px] w-full" />;
  }

  if (isError) {
    return (
      <div className="h-[100px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-negative font-mono">
          Couldn&apos;t load drawdown series.
        </p>
      </div>
    );
  }

  const drawdownSeries = computeDrawdownSeries(data?.points ?? []);

  if (drawdownSeries.length === 0) {
    return (
      <div className="h-[100px] flex items-center justify-center border border-border rounded-[2px]">
        <p className="text-[11px] text-muted-foreground font-mono">
          No drawdowns recorded yet.
        </p>
      </div>
    );
  }

  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ value: number }>;
    label?: string;
  }) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-card border border-border rounded-[2px] px-2 py-1.5">
        <p className="text-[10px] text-muted-foreground">{label}</p>
        <p className="text-[11px] font-mono tabular-nums text-negative">
          {fmtPct(payload[0].value)}
        </p>
      </div>
    );
  };

  return (
    <div
      role="img"
      aria-label={`Portfolio drawdown chart for ${period} period`}
      className="h-[100px] border border-border rounded-[2px]"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={drawdownSeries}
          margin={{ top: 4, right: 8, bottom: 4, left: 8 }}
        >
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "var(--muted-foreground, #888)" }}
            tickLine={false}
            axisLine={false}
            interval={Math.max(0, Math.floor(drawdownSeries.length / 5) - 1)}
            tickFormatter={(v: string) => (typeof v === "string" ? v.slice(5) : v)}
          />
          <YAxis
            tick={{ fontSize: 9, fill: "var(--muted-foreground, #888)" }}
            tickLine={false}
            axisLine={false}
            width={40}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          {/* Zero reference line — the "waterline" */}
          <ReferenceLine y={0} stroke="var(--border, #333)" strokeWidth={1} />
          {/* Drawdown area — red fill at 20% opacity (design spec §6) */}
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="var(--negative, #ef4444)"
            strokeWidth={1.5}
            fill="var(--negative, #ef4444)"
            fillOpacity={0.2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Attribution table ─────────────────────────────────────────────────────────

interface AttributionTableProps {
  portfolioId: string;
  period: string;
}

/**
 * AttributionTable — top contributors + detractors.
 *
 * WHY client-side computation: the backend attribution endpoint doesn't exist
 * yet (Backend Gap 3, spec §3). The client-side fallback computes
 * contribution = weight × period_return from holdings + value-history
 * (both already cached). The spec says to degrade gracefully and flag in PR.
 *
 * FLAG FOR FOLLOW-UP: migrate to GET /v1/portfolios/{id}/attribution?period=YTD
 * once the endpoint ships. See spec Decision 2 pattern.
 */
function AttributionTable({ portfolioId, period }: AttributionTableProps) {
  const apiClient = useApiClient();

  // WHY two queries here: holdings for weights, value-history for period return.
  // Both are already in the TanStack cache from usePortfolioData at the page level.
  const { data: holdingsData, isLoading: holdingsLoading } = useQuery({
    queryKey: qk.portfolios.holdingsByPortfolio(portfolioId),
    queryFn: () => apiClient.getHoldings(portfolioId),
    staleTime: 30_000,
    enabled: Boolean(portfolioId),
  });

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        days: PERIOD_DAYS[period] ?? 90,
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  const isLoading = holdingsLoading || historyLoading;

  // Compute portfolio period return from value-history.
  const portfolioPeriodReturn = (() => {
    const pts = historyData?.points ?? [];
    if (pts.length < 2) return null;
    const first = pts[0].value;
    const last = pts[pts.length - 1].value;
    return first > 0 ? (last - first) / first : null;
  })();

  // Compute per-holding contribution = weight × portfolio_period_return.
  // WHY proxy with portfolio return (not holding return): we don't have per-
  // holding price history. This approximation matches the HoldingContributionStat
  // formula already used in the holdings tab.
  const rows = (() => {
    const holdings = holdingsData?.holdings ?? [];
    if (holdings.length === 0 || portfolioPeriodReturn == null) return [];

    const totalCost = holdings.reduce(
      (s, h) => s + h.quantity * h.average_cost,
      0,
    );
    return holdings
      .map((h) => {
        const cost = h.quantity * h.average_cost;
        const weight = totalCost > 0 ? cost / totalCost : 0;
        const contribBps = weight * portfolioPeriodReturn * 10000;
        return {
          ticker: h.ticker,
          weight,
          contribBps,
        };
      })
      .sort((a, b) => b.contribBps - a.contribBps);
  })();

  if (isLoading) {
    return (
      <div className="border border-border rounded-[2px] overflow-hidden">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[24px] w-full mb-px" />
        ))}
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="border border-border rounded-[2px] p-3 text-[11px] text-muted-foreground font-mono">
        Attribution requires ≥30 days of history.
      </div>
    );
  }

  // Show top 5 contributors + top 5 detractors.
  const topContributors = rows.slice(0, 5);
  const detractors = [...rows].reverse().slice(0, 5).filter((r) => r.contribBps < 0);

  return (
    <div className="border border-border rounded-[2px] overflow-hidden">
      <table className="w-full text-[11px] font-mono border-collapse">
        <thead>
          <tr className="h-[22px] border-b border-border bg-muted/20">
            <th className="text-left text-[10px] uppercase tracking-wide text-muted-foreground px-2 py-1 font-normal">
              TICKER
            </th>
            <th className="text-right text-[10px] uppercase tracking-wide text-muted-foreground px-2 py-1 font-normal">
              WT
            </th>
            <th className="text-right text-[10px] uppercase tracking-wide text-muted-foreground px-2 py-1 font-normal">
              CONTRIB
            </th>
          </tr>
        </thead>
        <tbody>
          {topContributors.map((row) => (
            <tr
              key={row.ticker}
              className="h-[24px] border-b border-border/40 hover:bg-muted/20"
            >
              <td className="px-2 py-0.5 text-primary">{row.ticker}</td>
              <td className="px-2 py-0.5 tabular-nums text-right text-muted-foreground">
                {(row.weight * 100).toFixed(1)}%
              </td>
              <td
                className={cn(
                  "px-2 py-0.5 tabular-nums text-right",
                  row.contribBps >= 0 ? "text-positive" : "text-negative",
                )}
              >
                {row.contribBps >= 0 ? "+" : ""}
                {row.contribBps.toFixed(0)}bps
              </td>
            </tr>
          ))}

          {/* Separator + detractors section */}
          {detractors.length > 0 && (
            <>
              <tr>
                <td
                  colSpan={3}
                  className="px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground bg-muted/10"
                >
                  Detractors
                </td>
              </tr>
              {detractors.map((row) => (
                <tr
                  key={row.ticker}
                  className="h-[24px] border-b border-border/40 hover:bg-muted/20"
                >
                  <td className="px-2 py-0.5 text-primary">{row.ticker}</td>
                  <td className="px-2 py-0.5 tabular-nums text-right text-muted-foreground">
                    {(row.weight * 100).toFixed(1)}%
                  </td>
                  <td className="px-2 py-0.5 tabular-nums text-right text-negative">
                    {row.contribBps.toFixed(0)}bps
                  </td>
                </tr>
              ))}
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsTab({ portfolioId }: AnalyticsTabProps) {
  const apiClient = useApiClient();

  // ── Period state — local (not URL-backed here to avoid collision with the
  //    page-level ?period= equity curve state). If the design spec's nuqs
  //    URL state is needed, replace useState with useQueryState.
  // WHY "YTD" default: matches the IBKR Portfolio Analyst default and the
  //    spec ASCII art which shows "YTD·" as the active pill.
  const [period, setPeriod] = useState("YTD");

  // ── Risk metrics for the sidebar's DataFreshnessPill ─────────────────────
  const { data: risk } = useQuery<RiskMetricsResponse>({
    queryKey: qk.portfolios.riskMetrics(portfolioId),
    queryFn: () =>
      apiClient.getRiskMetrics(portfolioId, PERIOD_DAYS[period] ?? 90),
    staleTime: 5 * 60_000,
    enabled: Boolean(portfolioId),
  });

  return (
    // WHY p-2 space-y-2: 8px padding + 8px gaps — terminal density target.
    <div className="p-2 space-y-2">

      {/* ── Period selector row (h=28px) ─────────────────────────────────── */}
      {/* WHY h-7: 28px matches the spec §6 spacing table for the period bar. */}
      <div className="flex items-center h-7">
        <AnalyticsPeriodSelector
          value={period}
          onChange={setPeriod}
          lastUpdated={risk?.as_of}
        />
        {/* Benchmark indicator — static SPY for v1 (Decision 1, spec §OQ-1) */}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
            Benchmark
          </span>
          <span className="text-[10px] font-mono text-foreground border border-border/60 px-1.5 py-0.5 rounded-[2px]">
            SPY
          </span>
        </div>
      </div>

      {/* ── Main grid: charts (9 cols) + risk sidebar (3 cols) ──────────── */}
      <div className="grid grid-cols-12 gap-2">

        {/* Charts column — col-span-9 */}
        <div className="col-span-12 lg:col-span-9 space-y-2">
          {/* Performance equity curve */}
          <PerformanceChart portfolioId={portfolioId} period={period} />
          {/* Drawdown chart — shares x-axis with performance chart above */}
          <DrawdownChart portfolioId={portfolioId} period={period} />
        </div>

        {/* Risk sidebar — col-span-3 */}
        <div className="col-span-12 lg:col-span-3">
          <RiskSidebar portfolioId={portfolioId} period={period} />
        </div>
      </div>

      {/* ── Period returns + attribution row ─────────────────────────────── */}
      <div className="grid grid-cols-12 gap-2">

        {/* Period returns table (col-span-6) */}
        <div className="col-span-12 md:col-span-6">
          <div className="flex items-center mb-1">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
              Period Returns
            </span>
          </div>
          <AnalyticsPeriodReturnsTable portfolioId={portfolioId} />
        </div>

        {/* Attribution table (col-span-6) */}
        <div className="col-span-12 md:col-span-6">
          <div className="flex items-center mb-1">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
              Attribution (top contributors)
            </span>
          </div>
          <AttributionTable portfolioId={portfolioId} period={period} />
        </div>
      </div>
    </div>
  );
}
