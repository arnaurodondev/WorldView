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
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";

// R3 polish: BarChart3 is the category icon for the "insufficient analytics
// data" EmptyState (attribution table) — gives an instant visual category.
import { BarChart3 } from "lucide-react";

import { cn } from "@/lib/utils";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
// R3 polish (DS §15.12): shared EmptyState primitive replaces the ad-hoc
// bordered <div> empty states so every surface renders identically.
import { EmptyState } from "@/components/primitives/EmptyState";
import { AnalyticsPeriodSelector } from "./AnalyticsPeriodSelector";
import { AnalyticsPeriodReturnsTable } from "./AnalyticsPeriodReturnsTable";
// R2 sprint: the TWR chart replaces the old inline $-NAV PerformanceChart
// (raw NAV cannot be overlaid against a benchmark — see AnalyticsTwrChart).
import { AnalyticsTwrChart } from "./AnalyticsTwrChart";
// R2 sprint: client-computed period-aligned risk panel (Sharpe/MaxDD/Vol/Beta).
import { AnalyticsRiskMetricsPanel } from "./AnalyticsRiskMetricsPanel";
// R2 sprint: SPY/QQQ daily closes shared by the TWR overlay + beta.
import { useBenchmarkSeries } from "@/features/portfolio/hooks/useBenchmarkSeries";
// R2 sprint: drawdown math moved to the pure, unit-tested risk-metrics lib
// (formula unchanged: dd_t = V_t / max(V_0..t) − 1).
import { drawdownSeries } from "@/features/portfolio/lib/risk-metrics";
import type { RiskMetricsResponse } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsTabProps {
  /** Active portfolio UUID. */
  portfolioId: string;
}

// ── Period → days map ─────────────────────────────────────────────────────────

// R2 sprint: "1W" added (brief requires a 1W/1M/3M/1Y/ALL selector; the
// extra 6M/YTD/2Y pills predate R2 and are kept — removing them would
// regress existing functionality and tests).
// WHY "ALL": undefined — omitting `days` makes S1 return the FULL snapshot
// history, instead of the previous hardcoded 1825-day approximation that
// silently truncated portfolios older than 5 years.
const PERIOD_DAYS: Record<string, number | undefined> = {
  "1W": 7,
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "YTD": 365, // server handles real YTD
  "1Y": 365,
  "2Y": 730,
  "ALL": undefined,
};

/**
 * riskLookbackDays — lookback for the BACKEND risk-metrics endpoint.
 * The endpoint requires a concrete `lookback_days` in 10–3650:
 *   - "ALL" maps to 1825 (5y) — widest window well inside the range.
 *   - "1W" (7) clamps UP to 10 — VERIFIED LIVE (2026-06-10): the endpoint
 *     422s on lookback_days=7 ("Input should be ≥ 10"). The sidebar hint
 *     shows the clamped value so the user sees the real window used.
 * Distinct from PERIOD_DAYS, which may be undefined to request full
 * value-history (the value-history endpoint has no such floor).
 */
function riskLookbackDays(period: string): number {
  return Math.max(PERIOD_DAYS[period] ?? 1825, 10);
}

// ── Format helpers ────────────────────────────────────────────────────────────

function fmtPct(val: number | null | undefined, fractions = 2): string {
  if (val == null || Number.isNaN(val)) return "—";
  const pct = (val * 100).toFixed(fractions);
  // R3 polish: strictly-positive gets "+"; ZERO stays unsigned — same
  // convention as signedPrice (PortfolioKPIStrip, R1): a flat value has no
  // direction, so "+0.00%" would falsely imply a gain.
  return val > 0 ? `+${pct}%` : `${pct}%`;
}

function fmtNum(val: number | null | undefined, fractions = 2): string {
  if (val == null || Number.isNaN(val)) return "—";
  return val.toFixed(fractions);
}

// R2 sprint: the drawdown computation moved to the pure risk-metrics lib
// (drawdownSeries) so the same unit-tested formula backs the chart AND the
// MAX DD tile in the client risk panel. Behavior is identical:
// dd_t = V_t / max(V_0..t) − 1.

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

  const {
    data: risk,
    isLoading: riskLoading,
    isPlaceholderData: riskIsStale,
  } = useQuery<RiskMetricsResponse>({
    // R2 sprint (bug fix): the key previously omitted `period`, so changing
    // the period pill recomputed `lookback_days` in the queryFn but NEVER
    // refetched — the sidebar silently showed metrics for the previous
    // period. Appending period to the canonical key makes the cache entry
    // period-scoped (spread keeps qk.* as the cascade-invalidation prefix).
    queryKey: [...qk.portfolios.riskMetrics(portfolioId), period],
    queryFn: () =>
      apiClient.getRiskMetrics(portfolioId, riskLookbackDays(period)),
    staleTime: 5 * 60_000,
    enabled: Boolean(portfolioId),
    // R3 polish (transition quality): switching period changes the queryKey,
    // which without placeholderData would unmount every populated tile back
    // to a skeleton — a jarring flash for a 200ms refetch. Carrying the
    // previous period's data forward keeps the tiles populated; the
    // isPlaceholderData flag dims them (opacity below) so the user can see
    // the numbers are momentarily from the prior window.
    placeholderData: (prev) => prev,
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
      hint: `${riskLookbackDays(period)}D`,
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
      hint: `${riskLookbackDays(period)}D`,
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
    // R3 polish: opacity-60 while isPlaceholderData — previous-period values
    // stay visible (no skeleton flash) but visibly dimmed until the new
    // period's metrics land. transition-opacity makes the swap subtle.
    <div
      data-stale={riskIsStale || undefined}
      className={cn(
        "border border-border rounded-[2px] h-full overflow-hidden transition-opacity",
        riskIsStale && "opacity-60",
      )}
    >
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
// R2 sprint: the inline $-NAV PerformanceChart was replaced by
// AnalyticsTwrChart (separate file) — a cumulative-return chart rebased to
// 0% at period start with toggleable SPY/QQQ benchmark overlays. Raw $ NAV
// cannot share an axis with a benchmark price; the $ view still lives in
// the Holdings tab's PerformanceChartPanel.

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

  const { data, isLoading, isError, isPlaceholderData } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        // R2 sprint: "ALL" omits days (full history). The conditional spread
        // MUST stay identical to AnalyticsTwrChart / AnalyticsRiskMetricsPanel
        // — all three share this query key, so divergent fetch params would
        // make the cached window depend on which component fetched first.
        ...(PERIOD_DAYS[period] != null ? { days: PERIOD_DAYS[period] } : {}),
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
    // R3 polish (transition quality): the queryKey is period-scoped, so a
    // period change would otherwise unmount the populated chart back to a
    // skeleton. Carrying the previous period's series forward keeps the
    // chart drawn; isPlaceholderData dims it until the new window lands.
    placeholderData: (prev) => prev,
  });

  // isLoading is only true on the very FIRST fetch (placeholderData supplies
  // data on subsequent period switches) — so the skeleton renders exactly
  // once per portfolio, never on period changes.
  if (isLoading) {
    return <Skeleton className="h-[100px] w-full" data-testid="drawdown-chart-skeleton" />;
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

  // R2 sprint: same formula as before, now sourced from the pure unit-tested
  // lib (dd_t = V_t / max(V_0..t) − 1). Map value-history points into the
  // lib's DatedValue shape first.
  const ddSeries = drawdownSeries(
    (data?.points ?? []).map((p) => ({ date: p.date, value: p.value })),
  );

  if (ddSeries.length === 0) {
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

  // R3 polish (DS §15.11 color-token fix): this chart previously used
  // `var(--negative, #ef4444)` / `var(--border, #333)` / `var(--muted-foreground, #888)`.
  // Our tokens hold SPACE-SEPARATED HSL TRIPLES ("0 63% 62%"), which are
  // INVALID as a bare color value — and because the variable IS defined, the
  // hex fallback never applied either, so SVG fills silently mis-painted
  // (the no-paint bug class from the R1 sparkline / instrument chips).
  // hsl(var(--token)) is the canonical composition form for SVG/chart JS.
  // WHY tickFontFamily: ADR-F-15 — axis tick labels are numeric data and
  // must render in IBM Plex Mono like every other number on the surface.
  return (
    <div
      role="img"
      aria-label={`Portfolio drawdown chart for ${period} period`}
      data-stale={isPlaceholderData || undefined}
      className={cn(
        "h-[100px] border border-border rounded-[2px] transition-opacity",
        // Dim the stale (previous-period) series while the new one loads.
        isPlaceholderData && "opacity-60",
      )}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={ddSeries}
          margin={{ top: 4, right: 8, bottom: 4, left: 8 }}
        >
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            interval={Math.max(0, Math.floor(ddSeries.length / 5) - 1)}
            tickFormatter={(v: string) => (typeof v === "string" ? v.slice(5) : v)}
          />
          <YAxis
            tick={{ fontSize: 9, fill: "hsl(var(--muted-foreground))", fontFamily: "var(--font-mono)" }}
            tickLine={false}
            axisLine={false}
            width={40}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          {/* Zero reference line — the "waterline" */}
          <ReferenceLine y={0} stroke="hsl(var(--border))" strokeWidth={1} />
          {/* Drawdown area — red fill at 20% opacity (design spec §6) */}
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="hsl(var(--negative))"
            strokeWidth={1.5}
            fill="hsl(var(--negative))"
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
        // R2 sprint: identical params to AnalyticsTwrChart / DrawdownChart —
        // shared query key requires identical fetch params (see DrawdownChart).
        ...(PERIOD_DAYS[period] != null ? { days: PERIOD_DAYS[period] } : {}),
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
    // R3 polish: keep the previous period's rows during a period switch
    // instead of flashing back to the skeleton (same rationale as the
    // charts above — the key is period-scoped).
    placeholderData: (prev) => prev,
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
    // R3 polish (DS §15.12): named "insufficient analytics data" state via
    // the shared EmptyState primitive — copy lives in lib/copy/empty-states.ts
    // so the attribution table and TWR chart speak with one voice.
    return (
      <div
        data-testid="attribution-empty"
        className="border border-border rounded-[2px]"
      >
        <EmptyState
          condition="empty-no-data"
          copyKey="portfolio.analytics-insufficient"
          icon={BarChart3}
        />
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
                {/* R3 polish: zero stays unsigned (signedPrice convention). */}
                {row.contribBps > 0 ? "+" : ""}
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

  // ── R2 sprint: benchmark overlay toggles ─────────────────────────────────
  // WHY SPY on by default: pre-R2 the chart header showed a static "SPY"
  // badge promising a benchmark; defaulting the overlay ON delivers it.
  // QQQ defaults off — a second dashed line is opt-in noise.
  const [benchmarks, setBenchmarks] = useState<{ SPY: boolean; QQQ: boolean }>({
    SPY: true,
    QQQ: false,
  });

  // Window start for benchmark OHLCV — derived from the SAME day count the
  // value-history queries use so the overlay covers the chart's window.
  // "ALL" → undefined → full available OHLCV history.
  const periodDays = PERIOD_DAYS[period];
  const benchmarkFromDate =
    periodDays != null
      ? (() => {
          const d = new Date();
          d.setDate(d.getDate() - periodDays);
          return d.toISOString().slice(0, 10);
        })()
      : undefined;

  // SPY closes are ALWAYS fetched (not just when the overlay is on) because
  // the client risk panel needs them for beta regardless of the toggle.
  // QQQ closes only load when its overlay is toggled on.
  const { closesByTicker } = useBenchmarkSeries({
    tickers: benchmarks.QQQ ? ["SPY", "QQQ"] : ["SPY"],
    fromDate: benchmarkFromDate,
    enabled: Boolean(portfolioId),
  });

  // ── Risk metrics for the sidebar's DataFreshnessPill ─────────────────────
  const { data: risk } = useQuery<RiskMetricsResponse>({
    // R2 sprint: period-scoped key — same fix as RiskSidebar (the key
    // previously ignored period, pinning the freshness pill to stale data).
    queryKey: [...qk.portfolios.riskMetrics(portfolioId), period],
    queryFn: () =>
      apiClient.getRiskMetrics(portfolioId, riskLookbackDays(period)),
    staleTime: 5 * 60_000,
    enabled: Boolean(portfolioId),
    // R3 polish: keep the previous as_of so the DataFreshnessPill doesn't
    // blink out of existence on every period switch (the pill is layout-
    // conditional — unmounting it shifts the controls row).
    placeholderData: (prev) => prev,
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
        {/* R2 sprint: benchmark TOGGLES replace the static SPY badge.
            aria-pressed exposes the on/off state to AT + tests; the active
            style mirrors the period pills so the affordance is recognisable. */}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground font-mono">
            Benchmark
          </span>
          {(["SPY", "QQQ"] as const).map((ticker) => {
            const active = benchmarks[ticker];
            return (
              <button
                key={ticker}
                type="button"
                aria-pressed={active}
                title={`${active ? "Hide" : "Show"} ${ticker} overlay (both series rebased to 0% at period start)`}
                onClick={() =>
                  setBenchmarks((b) => ({ ...b, [ticker]: !b[ticker] }))
                }
                className={cn(
                  "text-[10px] font-mono px-1.5 py-0.5 rounded-[2px] border transition-colors",
                  // R3 polish: keyboard parity with hover — focus-visible ring
                  // (--ring = primary) so tabbing reaches the toggles visibly.
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  active
                    ? "border-primary text-primary bg-primary/10"
                    : "border-border/60 text-muted-foreground hover:text-foreground hover:border-border",
                )}
              >
                {ticker}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Main grid: charts (9 cols) + risk sidebar (3 cols) ──────────── */}
      <div className="grid grid-cols-12 gap-2">

        {/* Charts column — col-span-9 */}
        <div className="col-span-12 lg:col-span-9 space-y-2">
          {/* R2 sprint: cumulative-return (TWR-style) chart with benchmark
              overlays — every series rebased to 0% at period start so the
              vertical gap IS the excess return. */}
          <AnalyticsTwrChart
            portfolioId={portfolioId}
            period={period}
            periodDays={periodDays}
            benchmarks={benchmarks}
            benchmarkCloses={closesByTicker}
          />
          {/* Drawdown chart — shares x-axis with performance chart above */}
          <DrawdownChart portfolioId={portfolioId} period={period} />
        </div>

        {/* Risk sidebar — col-span-3 */}
        <div className="col-span-12 lg:col-span-3 space-y-2">
          <RiskSidebar portfolioId={portfolioId} period={period} />
          {/* R2 sprint: client-computed, PERIOD-ALIGNED risk metrics
              (Sharpe rf=0 / MaxDD / Vol / Beta·SPY) from the same daily
              series the charts above draw — see AnalyticsRiskMetricsPanel
              for why this coexists with the lookback-window RiskSidebar. */}
          <AnalyticsRiskMetricsPanel
            portfolioId={portfolioId}
            period={period}
            periodDays={periodDays}
            spyCloses={closesByTicker["SPY"]}
          />
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
