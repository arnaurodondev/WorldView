/**
 * features/portfolio/components/AnalyticsRiskMetricsPanel.tsx — PERIOD-ALIGNED
 * client-computed risk metrics (R2 enhancement sprint).
 *
 * WHY THIS EXISTS next to the backend-driven RiskSidebar: the sidebar's
 * metrics come from S9 /risk-metrics, which computes over its own
 * `lookback_days` window server-side. This panel computes Sharpe / max
 * drawdown / annualized volatility / beta-vs-SPY CLIENT-SIDE from the very
 * same daily value-history series the TWR + drawdown charts above are
 * drawn from — so the numbers describe EXACTLY what the user is looking
 * at, for exactly the selected period. The two panels are labelled
 * distinctly ("RISK · 90D" vs "PERIOD RISK") so they never read as
 * contradictory duplicates.
 *
 * MATH lives in features/portfolio/lib/risk-metrics.ts (pure + unit-tested):
 *   Sharpe  = mean(r_d)/stdev(r_d, n−1) × √252, rf = 0 (ASSUMPTION — no
 *             risk-free feed in the platform; surfaced in the panel hint)
 *   Vol     = stdev(r_d, n−1) × √252
 *   Max DD  = min over t of ( V_t / max(V_0..t) − 1 )
 *   Beta    = cov(r_p, r_spy) / var(r_spy), pairwise-aligned daily returns
 *
 * INSUFFICIENT DATA: every metric renders an em-dash with an explanatory
 * tooltip when the series has < 20 daily-return observations
 * (MIN_OBSERVATIONS) — see the lib for the statistical rationale. We never
 * show a number computed from a handful of points.
 *
 * WHO USES IT: AnalyticsTab (right sidebar column, under RiskSidebar).
 */

"use client";
// WHY "use client": useQuery; rendered inside the client AnalyticsTab tree.

import { useQuery } from "@tanstack/react-query";

import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import {
  computeRiskMetrics,
  MIN_OBSERVATIONS,
  type DatedValue,
} from "@/features/portfolio/lib/risk-metrics";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsRiskMetricsPanelProps {
  portfolioId: string;
  /** Active period label — shared query key with the TWR/drawdown charts. */
  period: string;
  /** Days for the value-history fetch; undefined = full history ("ALL"). */
  periodDays?: number;
  /**
   * SPY daily closes from useBenchmarkSeries (lifted to AnalyticsTab; same
   * cache the TWR chart overlay reads). undefined/empty → beta renders "—"
   * with a "benchmark unavailable" tooltip instead of a fake number.
   */
  spyCloses?: DatedValue[];
}

// ── Formatting ────────────────────────────────────────────────────────────────

const INSUFFICIENT_TOOLTIP = `Insufficient data — needs ≥ ${MIN_OBSERVATIONS} daily observations in the selected period.`;

/** Signed percent for fractions ("-12.34%"). */
function fmtPct(v: number): string {
  const pct = (v * 100).toFixed(2);
  return v >= 0 ? `+${pct}%` : `${pct}%`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsRiskMetricsPanel({
  portfolioId,
  period,
  periodDays,
  spyCloses,
}: AnalyticsRiskMetricsPanelProps) {
  const apiClient = useApiClient();

  // Identical query key to AnalyticsTwrChart/DrawdownChart — cache hit, no
  // extra network round-trip for this panel.
  const { data, isLoading } = useQuery({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      apiClient.getValueHistory(portfolioId, {
        ...(periodDays != null ? { days: periodDays } : {}),
        granularity: "1d" as const,
      }),
    staleTime: 60_000,
    enabled: Boolean(portfolioId),
  });

  const points: DatedValue[] = (data?.points ?? []).map((p) => ({
    date: p.date,
    value: p.value,
  }));

  // Pure computation — beta only when SPY closes are genuinely available.
  const metrics = computeRiskMetrics(
    points,
    spyCloses && spyCloses.length > 0 ? spyCloses : undefined,
  );

  // Distinguish WHY beta is null: missing benchmark data vs short series.
  // Two different user messages — one says "toggle won't help, backend gap",
  // the other says "come back when more history accrues".
  const betaTooltip =
    metrics.beta != null
      ? `Beta vs SPY over the ${period} period (cov/var of paired daily returns).`
      : !spyCloses || spyCloses.length === 0
        ? "SPY price history unavailable — beta cannot be computed."
        : INSUFFICIENT_TOOLTIP;

  const tiles: Array<{
    label: string;
    /** Display string; "—" = honestly unavailable. */
    value: string;
    tooltip: string;
    colorClass: string;
  }> = [
    {
      label: "SHARPE",
      value: metrics.sharpe != null ? metrics.sharpe.toFixed(2) : "—",
      tooltip:
        metrics.sharpe != null
          ? `Annualized Sharpe (rf = 0 assumed — no risk-free feed) over ${metrics.nObservations} daily returns.`
          : INSUFFICIENT_TOOLTIP,
      colorClass:
        metrics.sharpe == null
          ? "text-muted-foreground"
          : metrics.sharpe > 1
            ? "text-positive"
            : metrics.sharpe < 0
              ? "text-negative"
              : "text-foreground",
    },
    {
      label: "MAX DD",
      value: metrics.maxDrawdown != null ? fmtPct(metrics.maxDrawdown) : "—",
      tooltip:
        metrics.maxDrawdown != null
          ? `Deepest peak-to-trough decline within the ${period} period.`
          : INSUFFICIENT_TOOLTIP,
      colorClass:
        metrics.maxDrawdown == null
          ? "text-muted-foreground"
          : metrics.maxDrawdown < -0.1
            ? "text-negative"
            : "text-foreground",
    },
    {
      label: "VOL ANN",
      value:
        metrics.volatilityAnnualized != null
          ? `${(metrics.volatilityAnnualized * 100).toFixed(2)}%`
          : "—",
      tooltip:
        metrics.volatilityAnnualized != null
          ? `Sample stdev of daily returns × √252 (${metrics.nObservations} observations).`
          : INSUFFICIENT_TOOLTIP,
      colorClass:
        metrics.volatilityAnnualized == null
          ? "text-muted-foreground"
          : "text-foreground",
    },
    {
      label: "BETA·SPY",
      value: metrics.beta != null ? metrics.beta.toFixed(2) : "—",
      tooltip: betaTooltip,
      colorClass:
        metrics.beta == null ? "text-muted-foreground" : "text-foreground",
    },
  ];

  return (
    <div
      data-testid="client-risk-panel"
      className="border border-border rounded-[2px] overflow-hidden"
    >
      {/* Header — names the window + the rf=0 assumption explicitly so the
          panel can never be mistaken for the lookback-window RiskSidebar. */}
      <div className="flex items-baseline justify-between border-b border-border bg-muted/20 px-2 py-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Period Risk
        </span>
        <span
          className="text-[9px] text-muted-foreground/60 font-mono"
          title="Computed client-side from the chart's daily NAV series. Sharpe assumes rf = 0."
        >
          {period} · rf=0
        </span>
      </div>

      {tiles.map((tile) => (
        <div
          key={tile.label}
          // Native title tooltip — zero extra DOM, screen-reader friendly,
          // and the panel is already information-dense (same rationale as
          // the KPITile hoverTitle).
          title={tile.tooltip}
          data-testid={`client-risk-${tile.label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
          className="flex items-baseline justify-between px-2 py-1 border-b border-border/40 last:border-0"
        >
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {tile.label}
          </span>
          {isLoading ? (
            <Skeleton className="h-[14px] w-12" />
          ) : (
            // ADR-F-15: every numeric is font-mono tabular-nums.
            <span
              className={cn(
                "font-mono tabular-nums text-[12px] leading-none",
                tile.colorClass,
              )}
            >
              {tile.value}
            </span>
          )}
        </div>
      ))}

      {/* Observation-count footer — quantifies how much data backs the
          numbers above (n < 20 explains why tiles show "—"). */}
      <div className="px-2 py-0.5 bg-muted/10">
        <span className="text-[9px] font-mono text-muted-foreground/60">
          n={isLoading ? "…" : metrics.nObservations} daily returns
        </span>
      </div>
    </div>
  );
}
