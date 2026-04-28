/**
 * components/portfolio/RiskMetricsStrip.tsx — 5 risk KPI tiles (PLAN-0046 W5 / T-46-5-06)
 *
 * WHY THIS EXISTS: Drawdown / volatility / Sharpe / Sortino / beta are the
 * five canonical risk numbers every portfolio manager checks before sizing
 * a trade. Showing them in a horizontal strip immediately under the equity
 * curve lets a trader scan "trajectory + risk" in one glance — same visual
 * pattern as the PortfolioKPIStrip above, just with risk-side numbers.
 *
 * WHY ALWAYS-FIVE-TILE LAYOUT: keeping the five tiles fixed in width
 * (CSS grid 5 cols) means the row's vertical rhythm never shifts. Even
 * when a metric is null ("—"), the tile still occupies its slot.
 *
 * WHY null → "—" (NOT "NaN" / "0"): a missing metric is honest data —
 * "we couldn't compute Sharpe because variance is 0" is meaningfully
 * different from "Sharpe = 0". Rendering "0" would lie to the user;
 * "NaN" leaks an internal numeric representation. "—" is the universal
 * "absent" glyph and matches every other empty cell in this app.
 *
 * QUALITY COLOUR CODING: Sharpe / Sortino above 1 → positive teal,
 * below 0 → negative red, in-between → muted. Drawdown / vol get only
 * a "magnitude" colour (red when severe). Beta is colour-neutral (a
 * factor exposure number, not a quality score).
 *
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/risk-metrics → composition
 * endpoint that calls /value-history + S3 SPY OHLCV and computes locally.
 */

"use client";
// WHY "use client": useQuery + reactive re-render on portfolioId change.

import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPercent, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface RiskMetricsStripProps {
  portfolioId: string;
  /** Lookback window in days (default 90 — matches the spec). */
  lookbackDays?: number;
}

// ── Tile primitives ──────────────────────────────────────────────────────────

interface TileProps {
  label: string;
  /** Pre-formatted display string ("—" for null). */
  display: string;
  /** Tailwind colour class for the value text — empty for default. */
  valueClassName?: string;
  /** Optional sub-label (e.g. "ann." for annualised stats). */
  hint?: string;
}

/**
 * Tile — one KPI cell. Five of these compose the strip.
 *
 * WHY tabular-nums + font-mono on the value line: every metric has the
 * same visual rhythm so the strip reads as "five equal tiles" rather than
 * "five tiles of varying width depending on number length".
 */
function Tile({ label, display, valueClassName, hint }: TileProps) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-1.5 border-r border-border last:border-r-0">
      <div className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "font-mono tabular-nums text-[14px] leading-none",
          valueClassName ?? "text-foreground",
        )}
      >
        {display}
        {hint && (
          <span className="ml-1 text-[9px] uppercase tracking-[0.06em] text-muted-foreground/80 align-baseline">
            {hint}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Formatting helpers ───────────────────────────────────────────────────────

/** Render a fraction (e.g. -0.125) as "-12.50%" — null → "—". */
function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${formatPercent(v)}`;
}

/** Render a unitless ratio (Sharpe/Sortino/Beta) — null → "—". */
function fmtRatio(v: number | null): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

// ── Quality colour mapping ───────────────────────────────────────────────────

/**
 * Colour the Sharpe / Sortino tile by quality bucket.
 *   > 1.0  → text-positive  (institutionally "good")
 *   > 0    → text-foreground (neutral)
 *   ≤ 0    → text-negative   (worse than risk-free)
 *   null   → text-muted-foreground (unknown)
 */
function ratioQualityClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v > 1.0) return "text-positive";
  if (v <= 0) return "text-negative";
  return "text-foreground";
}

/**
 * Drawdown is always negative (or zero). Severity bucket:
 *   > -10% → text-foreground (mild)
 *   > -20% → muted warning   (text-warning if defined, else default)
 *   ≤ -20% → text-negative   (severe)
 */
function drawdownQualityClass(v: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v <= -0.20) return "text-negative";
  return "text-foreground";
}

// ── RiskMetricsStrip ─────────────────────────────────────────────────────────

export function RiskMetricsStrip({
  portfolioId,
  lookbackDays = 90,
}: RiskMetricsStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["risk-metrics", portfolioId, lookbackDays],
    queryFn: () =>
      createGateway(accessToken).getRiskMetrics(portfolioId, lookbackDays),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // ── Loading skeleton — 5 tile-shaped placeholders so layout doesn't jump
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 border border-border rounded-[2px] divide-x divide-border">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="px-3 py-1.5 flex flex-col gap-1">
            <Skeleton className="h-2 w-16" />
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </div>
    );
  }

  // On error or no data, render the strip with all metrics as "—" so the
  // layout stays stable instead of collapsing the row entirely.
  const safe = isError || !data ? null : data;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 border border-border rounded-[2px]">
      <Tile
        label="Max Drawdown"
        display={fmtPct(safe?.drawdown_max ?? null)}
        valueClassName={drawdownQualityClass(safe?.drawdown_max ?? null)}
      />
      <Tile
        label="Vol (Ann.)"
        display={fmtPct(safe?.volatility_annualized ?? null)}
        hint="ann."
        // Volatility colour: high vol → muted warning. We don't render
        // "vol = good" in either direction — it's a context number.
        valueClassName={
          safe?.volatility_annualized != null && safe.volatility_annualized > 0.30
            ? "text-negative"
            : "text-foreground"
        }
      />
      <Tile
        label="Sharpe"
        display={fmtRatio(safe?.sharpe ?? null)}
        valueClassName={ratioQualityClass(safe?.sharpe ?? null)}
      />
      <Tile
        label="Sortino"
        display={fmtRatio(safe?.sortino ?? null)}
        valueClassName={ratioQualityClass(safe?.sortino ?? null)}
      />
      <Tile
        label="Beta vs SPY"
        display={fmtRatio(safe?.beta_vs_spy ?? null)}
        // Beta is a factor exposure number, not a "good/bad" score —
        // render in the default foreground colour regardless of value.
        valueClassName="text-foreground"
      />
    </div>
  );
}
