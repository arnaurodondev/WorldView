/**
 * components/portfolio/RiskMetricsPanel.tsx — Full 2×3 risk-metric grid with lookback chips.
 *
 * WHY THIS EXISTS: RiskMetricsStrip is a single horizontal bar (5 KPIs in a row)
 * used inside the equity-curve section. This panel is a standalone, larger 2×3
 * grid intended for dedicated risk sections of the portfolio overview — more
 * breathing room per metric, plus an interactive lookback selector so the user
 * can compare 90D vs 180D vs 1Y risk without navigating away.
 *
 * WHO USES IT: portfolio overview page Wave B-1 risk section.
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/risk-metrics?lookback_days=N
 *   (same endpoint as RiskMetricsStrip; lookback_days changes which period is used).
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Risk Grid.
 */
"use client";
// WHY "use client": uses React.useState for the active chip + useQuery for live data.
// Any component that reads React context or manages local state must be a client component.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPercent, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { qk } from "@/lib/query/keys";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface RiskMetricsPanelProps {
  portfolioId: string;
}

// ── Lookback chip configuration ───────────────────────────────────────────────

// WHY named tuples (not just numbers): the chip label and the lookback_days param
// must always stay in sync. A separate mapping ensures no chip can show "90D"
// while actually querying 180 days of data.
const LOOKBACK_CHIPS: Array<{ label: string; days: number }> = [
  { label: "90D", days: 90 },
  { label: "180D", days: 180 },
  { label: "1Y", days: 365 },
];

// ── Cell primitive ────────────────────────────────────────────────────────────

interface MetricCellProps {
  /** Row label shown above the value — e.g. "Max Drawdown". */
  label: string;
  /** Pre-formatted display string — null values must be rendered as "—" by the caller. */
  display: string;
  /** Optional Tailwind colour override for the value text. */
  valueClassName?: string;
}

/**
 * MetricCell — one tile in the 2×3 grid.
 *
 * WHY tabular-nums: risk numbers like "-12.50%" and "-8.20%" must align
 * decimal points across rows so the user can scan columns at a glance.
 * Without tabular-nums each glyph has variable width and the decimals drift.
 *
 * WHY label text-[9px]: 22px standard row height leaves very little room for
 * two text lines. 9px label + 12px value fits within the cell without wrapping.
 */
function MetricCell({ label, display, valueClassName }: MetricCellProps) {
  return (
    <div className="flex flex-col justify-center gap-0.5 px-3 py-1.5 border border-border bg-card">
      <div className="text-[9px] font-mono uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "text-[12px] font-mono tabular-nums leading-none",
          valueClassName ?? "text-foreground",
        )}
      >
        {display}
      </div>
    </div>
  );
}

// ── Formatting helpers ────────────────────────────────────────────────────────

/**
 * fmtPct — render a 0-1 fraction as a signed percent string.
 *
 * WHY always show sign: drawdown is always negative — the "+" prefix on
 * zero is intentional (0.00% is not a drawdown). Sharpe-type ratios use
 * fmtRatio instead. Returns "—" for null/undefined to match the Bloomberg
 * convention for absent metrics.
 */
function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${formatPercent(v)}`;
}

/**
 * fmtRatio — render a unitless ratio (Sharpe / Sortino / Beta) to 2dp.
 * Returns "—" for null/undefined.
 */
function fmtRatio(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

/**
 * fmtVaR — 95% Value-at-Risk is a loss figure, always negative.
 * Rendered with sign for clarity ("−3.42%"), "—" when absent.
 */
function fmtVaR(v: number | null | undefined): string {
  if (v == null) return "—";
  // VaR is already expressed as a fraction (e.g. -0.0342 = -3.42%)
  return fmtPct(v);
}

// ── Colour helpers ────────────────────────────────────────────────────────────

/** Sharpe/Sortino > 1 → teal, < 0 → red, otherwise neutral. */
function ratioQualityClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  if (v > 1.0) return "text-[#26A69A]";
  if (v <= 0) return "text-[#EF5350]";
  return "text-foreground";
}

/** Max drawdown severity — < -20% is severe (red). */
function drawdownClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  if (v <= -0.2) return "text-[#EF5350]";
  return "text-foreground";
}

// ── RiskMetricsPanel ──────────────────────────────────────────────────────────

export function RiskMetricsPanel({ portfolioId }: RiskMetricsPanelProps) {
  // WHY useState for lookbackDays: the chip selection is ephemeral UI state —
  // it does not need to survive page navigation (no URL param) and does not
  // affect sibling components. Local state is the right scope here.
  const [lookbackDays, setLookbackDays] = useState<number>(90); // default: 90D chip

  const { accessToken } = useAuth();

  // WHY qk.portfolios.riskMetrics(portfolioId): the key factory nests under
  // detail(portfolioId) so a portfolio mutation automatically cascades an
  // invalidation to this panel — no manual invalidation call needed.
  // NOTE: lookbackDays is appended inline because the base key is shared
  // with RiskMetricsStrip; including the lookback in the key lets different
  // lookback windows cache independently without evicting each other.
  const { data, isLoading, isError } = useQuery({
    queryKey: [...qk.portfolios.riskMetrics(portfolioId), lookbackDays],
    queryFn: () =>
      createGateway(accessToken).getRiskMetrics(portfolioId, lookbackDays),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000, // risk metrics change on every new snapshot (~daily)
  });

  // Pre-compute safe display strings — null when loading/error so every cell
  // shows "—" rather than crashing on undefined.toFixed().
  const safe = isLoading || isError || !data ? null : data;

  const drawdownDisplay    = fmtPct(safe?.drawdown_max);
  const volDisplay         = fmtPct(safe?.volatility_annualized);
  const sharpeDisplay      = fmtRatio(safe?.sharpe);
  const sortinoDisplay     = fmtRatio(safe?.sortino);
  const betaDisplay        = fmtRatio(safe?.beta_vs_spy);
  // WHY var_95: VaR 95% is not part of RiskMetricsResponse today; render "—"
  // until the backend exposes it. The cell is reserved per the design spec.
  // If the API adds it later, the field will be safe?.var_95.
  const var95Display       = fmtVaR((safe as (typeof safe & { var_95?: number | null }) | null)?.var_95);

  return (
    <div className="flex flex-col gap-1 bg-[#131722]" data-testid="risk-metrics-panel">
      {/* ── Header: title + lookback chip row ──────────────────────────── */}
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Risk Metrics
        </span>

        {/* WHY chip row in the header (not a separate toolbar): keeps the
            lookback control visually paired with the panel it governs.
            Placing it beside the title follows Bloomberg's "action adjacent
            to context" UX convention (e.g., period tabs on equity curves). */}
        <div className="flex items-center gap-1" role="group" aria-label="Lookback period">
          {LOOKBACK_CHIPS.map(({ label, days }) => (
            <button
              key={days}
              onClick={() => setLookbackDays(days)}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[10px] font-mono transition-colors",
                lookbackDays === days
                  ? "bg-[#0EA5E9]/20 text-[#0EA5E9]"  // active chip — highlight with primary blue
                  : "bg-muted/20 text-muted-foreground hover:text-foreground", // inactive
              )}
              aria-pressed={lookbackDays === days}
              data-testid={`chip-${label}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── 2×3 grid of metric cells ──────────────────────────────────── */}
      {isLoading ? (
        // WHY 6 skeleton cells: the grid must not collapse or reflow during load.
        // Matching the final 2-row × 3-col grid prevents layout shift (CLS).
        <div className="grid grid-cols-3 gap-px" data-testid="risk-metrics-skeleton">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex flex-col gap-1 px-3 py-1.5 border border-border bg-card">
              <Skeleton className="h-2 w-20" />
              <Skeleton className="h-3 w-14" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-px">
          {/* Row 1 */}
          <MetricCell
            label="Max Drawdown"
            display={drawdownDisplay}
            valueClassName={drawdownClass(safe?.drawdown_max)}
          />
          <MetricCell
            label="Volatility (Ann.)"
            display={volDisplay}
            // Volatility > 30% annualised is considered high — show in warning amber.
            // WHY not red: vol is not a directional quality signal; it is a
            // magnitude indicator. Amber signals "pay attention" without implying loss.
            valueClassName={
              safe?.volatility_annualized != null && safe.volatility_annualized > 0.3
                ? "text-[#FFB000]"
                : "text-foreground"
            }
          />
          <MetricCell
            label="Sharpe Ratio"
            display={sharpeDisplay}
            valueClassName={ratioQualityClass(safe?.sharpe)}
          />

          {/* Row 2 */}
          <MetricCell
            label="Sortino Ratio"
            display={sortinoDisplay}
            valueClassName={ratioQualityClass(safe?.sortino)}
          />
          <MetricCell
            label="Beta (vs SPY)"
            display={betaDisplay}
            // Beta is a factor exposure, not a quality score — neutral colour always.
            valueClassName="text-foreground"
          />
          <MetricCell
            label="VaR 95%"
            display={var95Display}
            // VaR is a loss estimate — render in red when it exceeds 5% of portfolio.
            valueClassName={
              (safe as (typeof safe & { var_95?: number | null }) | null)?.var_95 != null &&
              ((safe as (typeof safe & { var_95?: number | null }) | null)?.var_95 ?? 0) <= -0.05
                ? "text-[#EF5350]"
                : "text-muted-foreground"
            }
          />
        </div>
      )}

      {/* ── Error state ─────────────────────────────────────────────────── */}
      {isError && (
        <div className="px-3 py-1 text-[10px] font-mono text-[#EF5350]">
          Failed to load risk metrics — please refresh.
        </div>
      )}
    </div>
  );
}
