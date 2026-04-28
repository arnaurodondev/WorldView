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
  // F-023 (QA 2026-04-28): the strip's parent now uses
  // ``divide-x divide-border`` (matching PortfolioKPIStrip:117), so the
  // per-tile ``border-r`` was redundant and inconsistent with the rest of
  // the codebase. Removed from the className here.
  return (
    <div className="flex flex-col gap-0.5 px-3 py-1.5">
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

  // F-015 (QA 2026-04-28): when the gateway reports ``data_quality.status
  // !== "ok"``, render a single explanatory caption row above the strip
  // and grey out the tiles so the user understands why every value is
  // "—". The previous behaviour rendered the strip with five "—" cells
  // and no explanation.
  const dq = safe?.data_quality;
  const insufficient =
    dq?.status === "insufficient_data";
  const benchmarkUnavailable =
    dq?.status === "benchmark_unavailable";
  // F-209 (QA iter-2): the gateway flags the F-201 wipe pattern (final
  // snapshot suddenly $0 right after a non-zero snapshot) as a separate
  // data_quality status. Render an explanatory caption instead of letting
  // the user see -100% drawdown / -3.4 Sharpe as if it were real data.
  const dataAnomaly =
    dq?.status === "data_anomaly_detected";

  // Build the caption text from the actual numbers the gateway reports
  // — never hardcode "0/10". When ``data_quality`` is missing entirely
  // (older gateway) we fall back to a generic message but skip the row
  // so the UI doesn't lie.
  let caption: string | null = null;
  if (insufficient) {
    const have = dq?.n_returns ?? 0;
    const need = 10; // matches gateway _MIN_RETURNS
    caption = `Risk metrics will appear after ~${need} trading days of snapshots — currently ${have}/${need}.`;
  } else if (benchmarkUnavailable) {
    caption = "Beta vs SPY is unavailable while the benchmark series is being ingested.";
  } else if (dataAnomaly) {
    caption =
      "Detected a sudden zero in the value series — risk metrics suppressed until the broker resync completes.";
  }

  // F-211 (QA iter-2): a11y. The strip is a logical group of related KPIs
  // so we mark it with ``role="group"`` and an ``aria-label``; when the
  // caption is present it becomes the strip's accessible description via
  // ``aria-describedby``. Each tile also gets its own per-cell aria-label
  // so a screen reader announces e.g. "Sharpe: 1.20".
  const captionId = "risk-metrics-strip-caption";

  // Pre-compute per-tile aria labels so the JSX stays readable. ``display``
  // is already the user-visible string ("—" for nulls) so we reuse it.
  const drawdownDisplay = fmtPct(safe?.drawdown_max ?? null);
  const volDisplay = fmtPct(safe?.volatility_annualized ?? null);
  const sharpeDisplay = fmtRatio(safe?.sharpe ?? null);
  const sortinoDisplay = fmtRatio(safe?.sortino ?? null);
  const betaDisplay = fmtRatio(safe?.beta_vs_spy ?? null);

  return (
    <div className="flex flex-col">
      {caption && (
        // WHY full-width caption row above the strip: a per-tile tooltip
        // wouldn't surface the reason without hover, and a footnote below
        // the strip is too easy to miss. The caption sits in the user's
        // eye-line directly above the empty values.
        <div
          id={captionId}
          className="px-3 py-1 text-[10px] text-muted-foreground border border-b-0 border-border rounded-t-[2px] bg-muted/20"
        >
          {caption}
        </div>
      )}
      <div
        // F-211: strip is a logical group; the caption (when present)
        // becomes its accessible description.
        role="group"
        aria-label="Risk metrics"
        aria-describedby={caption ? captionId : undefined}
        className={cn(
          // F-023: use the project's divider convention ``divide-x divide-border``
          // identical to PortfolioKPIStrip — replaces the manual per-tile
          // ``border-r border-border last:border-r-0`` pattern in Tile.
          "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 border border-border rounded-[2px] divide-x divide-border",
          // Grey out tiles when there's no usable data so the user reads
          // them as "absent on purpose" not "still loading". Same treatment
          // for the data-anomaly state (F-209) since every metric is null.
          (insufficient || dataAnomaly) && "opacity-60",
          caption && "rounded-t-none",
        )}
      >
        <div aria-label={`Max drawdown: ${drawdownDisplay}`}>
          <Tile
            label="Max Drawdown"
            display={drawdownDisplay}
            valueClassName={drawdownQualityClass(safe?.drawdown_max ?? null)}
          />
        </div>
        <div aria-label={`Volatility annualised: ${volDisplay}`}>
          <Tile
            label="Vol (Ann.)"
            display={volDisplay}
            hint="ann."
            // Volatility colour: high vol → muted warning. We don't render
            // "vol = good" in either direction — it's a context number.
            valueClassName={
              safe?.volatility_annualized != null && safe.volatility_annualized > 0.30
                ? "text-negative"
                : "text-foreground"
            }
          />
        </div>
        <div aria-label={`Sharpe ratio: ${sharpeDisplay}`}>
          <Tile
            label="Sharpe"
            display={sharpeDisplay}
            valueClassName={ratioQualityClass(safe?.sharpe ?? null)}
          />
        </div>
        <div aria-label={`Sortino ratio: ${sortinoDisplay}`}>
          <Tile
            label="Sortino"
            display={sortinoDisplay}
            valueClassName={ratioQualityClass(safe?.sortino ?? null)}
          />
        </div>
        <div aria-label={`Beta versus SPY: ${betaDisplay}`}>
          <Tile
            label="Beta vs SPY"
            display={betaDisplay}
            // Beta is a factor exposure number, not a "good/bad" score —
            // render in the default foreground colour regardless of value.
            valueClassName="text-foreground"
          />
        </div>
      </div>
    </div>
  );
}
