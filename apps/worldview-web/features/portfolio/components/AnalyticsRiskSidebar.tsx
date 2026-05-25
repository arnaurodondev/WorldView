/**
 * features/portfolio/components/AnalyticsRiskSidebar.tsx
 *
 * WHY THIS EXISTS: The 11-tile risk sidebar is the Analytics tab's canonical
 * "did I get paid for my risk?" summary. IBKR Portfolio Analyst is the reference —
 * their 10-tile header strip (Sharpe/Sortino/Beta/Alpha/Vol/MaxDD/Calmar/WinRate/
 * CAGR/Return) is the institutional standard for a risk-adjusted performance overview.
 * We render 11 tiles in a 4-column grid to keep the sidebar compact while covering
 * every metric a risk-aware PM needs.
 *
 * DATA SOURCE: GET /v1/portfolios/{id}/risk-metrics
 * The endpoint currently returns: drawdown_max, volatility_annualized, sharpe, sortino,
 * beta_vs_spy. Wave G backend pre-task (design spec §3 gap #6) adds: calmar, win_rate,
 * alpha, cagr, var_95, period_return. Until those fields arrive the tiles show "—".
 *
 * WHY 4-column grid: 11 tiles in 4 columns = 2 full rows of 4 + 1 row of 3 (last
 * row has the last tile alone). This avoids a 3-column layout that would make each
 * tile too wide relative to its label.
 *
 * WHY no period param in the query key: risk-metrics is always keyed to lookback_days
 * (currently 90 by default). The analytics tab's period selector controls the chart
 * window but not the risk-metrics lookback. Future: extend the endpoint to accept
 * a period string and cascade the query key when the period changes.
 *
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §4.3, §5.3, §9 Decision 4
 */
"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { ExtendedRiskMetricsResponse } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface AnalyticsRiskSidebarProps {
  portfolioId: string;
  /** Active analytics period — used only for cache invalidation coherence; the
   *  risk-metrics endpoint currently ignores it (lookback_days=90 default). */
  period: string;
}

// ── Tile config ───────────────────────────────────────────────────────────────

// WHY a typed config array (not inline JSX): 11 tiles with varying formatting
// rules would produce 11 near-identical JSX blocks. A config array centralises
// the formatting logic and keeps the render path a single map() call.
type MetricFormat = "ratio" | "percent" | "win_rate";

interface TileConfig {
  label: string;
  /** Key in ExtendedRiskMetricsResponse that holds the raw value. */
  field: keyof ExtendedRiskMetricsResponse;
  format: MetricFormat;
  /** When true, positive values use text-positive and negatives use text-negative. */
  signColor: boolean;
}

// WHY this exact ordering: matches the design spec §4.3 ASCII art top-to-bottom
// order, which groups "risk-adjusted" ratios first, then raw risk numbers, then
// return metrics at the bottom (matches IBKR Port Analyst column order).
const TILES: TileConfig[] = [
  { label: "SHARPE",   field: "sharpe",               format: "ratio",    signColor: false },
  { label: "SORTINO",  field: "sortino",               format: "ratio",    signColor: false },
  { label: "CALMAR",   field: "calmar",                format: "ratio",    signColor: false },
  { label: "WIN RATE", field: "win_rate",              format: "win_rate", signColor: false },
  { label: "ALPHA",    field: "alpha",                 format: "ratio",    signColor: true  },
  { label: "BETA",     field: "beta_vs_spy",           format: "ratio",    signColor: false },
  { label: "VOL (ANN)",field: "volatility_annualized", format: "percent",  signColor: false },
  { label: "MAX DD",   field: "drawdown_max",          format: "percent",  signColor: true  },
  { label: "VAR 95",   field: "var_95",                format: "percent",  signColor: true  },
  { label: "CAGR",     field: "cagr",                  format: "percent",  signColor: true  },
  { label: "RETURN",   field: "period_return",         format: "percent",  signColor: true  },
];

// ── Formatting helpers ────────────────────────────────────────────────────────

/**
 * Format a metric value for display.
 *
 * WHY per-format rules:
 *  - ratio (Sharpe/Sortino/Calmar/Alpha/Beta): unitless, 2dp — "1.42"
 *  - percent (Vol/MaxDD/VaR/CAGR/Return): multiply by 100, show sign — "+18.4%"
 *  - win_rate: same as percent but never sign-coloured (it's a fraction in [0,1])
 */
function fmtValue(value: number | null | undefined, format: MetricFormat): string {
  if (value == null) return "—";
  switch (format) {
    case "ratio":
      return value.toFixed(2);
    case "percent":
    case "win_rate": {
      // WHY Math.round * 10 / 10: toFixed(1) already does rounding but the
      // intermediate multiplication can introduce a tiny float error; using
      // toFixed directly is cleaner.
      const pct = (value * 100).toFixed(format === "win_rate" ? 1 : 2);
      // Win rate never shows a sign prefix — "58.3%" is already self-evident.
      if (format === "win_rate") return `${pct}%`;
      // For percentages, always show sign so positive values are distinguishable
      // from negative at a glance (matches Bloomberg PORT convention).
      return value >= 0 ? `+${pct}%` : `${pct}%`;
    }
  }
}

/**
 * Determine the value's text colour class.
 *
 * WHY signColor flag: ratios like Beta and Vol are context numbers — neither
 * "good" nor "bad" by sign alone — so we don't colour them. Percentages
 * (drawdown, return, alpha) are directional and should be coloured.
 */
function valueColorClass(
  value: number | null | undefined,
  signColor: boolean,
  format: MetricFormat,
): string {
  if (value == null) return "text-muted-foreground";
  // Win rate: colour-neutral (ratio can be any value in [0,1])
  if (format === "win_rate") return "text-foreground";
  if (!signColor) return "text-foreground";
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── Tile component ────────────────────────────────────────────────────────────

interface TileProps {
  label: string;
  display: string;
  valueClassName: string;
}

/**
 * Tile — one risk metric cell.
 *
 * WHY p-2 bg-muted/30: light fill distinguishes each tile as a discrete card
 * without using heavy border or elevation. The 30% opacity preserves the
 * terminal background colour underneath (translucent overlay pattern used
 * throughout the app for section fills).
 *
 * WHY text-[9px] for label: the 11-tile grid at 200px sidebar width requires
 * compact labels. 9px is the minimum legible size in Terminal Dark (which uses
 * IBM Plex Mono — a metrics-optimised mono face).
 */
function Tile({ label, display, valueClassName }: TileProps) {
  return (
    <div
      className="p-2 bg-muted/30 rounded"
      // WHY aria-label: a11y — screen readers announce the tile as
      // e.g. "SHARPE: 1.42" matching the RiskMetricsStrip F-211 pattern.
      aria-label={`${label}: ${display}`}
    >
      <div className="text-[9px] font-mono text-muted-foreground uppercase tracking-wide">
        {label}
      </div>
      <div
        className={cn(
          "text-[13px] font-mono tabular-nums",
          // WHY text-[13px] (not 14px): 11 tiles stacked vertically in ~440px;
          // one notch below the 5-tile horizontal strip's 14px keeps rows tight.
          valueClassName,
        )}
      >
        {display}
      </div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalyticsRiskSidebar({
  portfolioId,
}: AnalyticsRiskSidebarProps) {
  const { accessToken } = useAuth();

  // WHY qk.portfolios.riskMetrics: uses the existing key shape so the 5-tile
  // RiskMetricsStrip on the overview page shares the same cache entry when the
  // user navigates to the analytics tab immediately after the overview.
  const { data, isLoading } = useQuery({
    queryKey: qk.portfolios.riskMetrics(portfolioId),
    queryFn: () => createGateway(accessToken).getRiskMetrics(portfolioId),
    enabled: !!accessToken && !!portfolioId,
    // WHY 5min staleTime: risk metrics are recomputed once per daily snapshot.
    // Checking every minute is wasted computation for data that changes daily.
    staleTime: 300_000,
  });

  // Cast to extended type — the base type covers the existing fields;
  // the extended type adds the optional Wave G fields. A plain cast is safe
  // because ExtendedRiskMetricsResponse extends RiskMetricsResponse and all
  // new fields are optional (nullable with undefined ≡ null for display logic).
  const metrics = data as ExtendedRiskMetricsResponse | undefined;

  // ── Loading: 11 skeleton tiles ────────────────────────────────────────────
  if (isLoading) {
    return (
      <div
        data-testid="risk-sidebar-skeleton"
        className="grid grid-cols-4 gap-1.5"
      >
        {Array.from({ length: 11 }).map((_, i) => (
          <div key={i} className="p-2 bg-muted/30 rounded flex flex-col gap-1">
            <Skeleton className="h-2 w-10" />
            <Skeleton className="h-4 w-8" />
          </div>
        ))}
      </div>
    );
  }

  // ── Render 11 tiles ───────────────────────────────────────────────────────
  return (
    <div
      role="group"
      aria-label="Risk metrics"
      // WHY gap-1.5: tighter than the chart gutter (gap-2) so the 11 tiles
      // fill the sidebar column without spilling below the drawdown chart.
      className="grid grid-cols-4 gap-1.5"
    >
      {TILES.map((tile) => {
        // Read the raw value from the metrics object. Uses a generic index
        // access because TypeScript cannot narrow keyof T to number | null.
        const raw = metrics?.[tile.field] as number | null | undefined;
        const display = fmtValue(raw, tile.format);
        const colorClass = valueColorClass(raw, tile.signColor, tile.format);

        return (
          <Tile
            key={tile.field}
            label={tile.label}
            display={display}
            valueClassName={colorClass}
          />
        );
      })}
    </div>
  );
}
