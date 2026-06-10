/**
 * sidebar/TargetPricePanel.tsx — 12-month consensus price target panel
 *
 * WHY THIS EXISTS (T-18): The analyst price target is the most-cited number
 * in institutional research. Rendering it large (14px, NOT 18px — per T-18
 * spec) and immediately below the consensus bar lets analysts scan the
 * "recommendation + magnitude" pair in one fixation. The ▲/▼ upside chip
 * quantifies the implied return, translating the abstract target into a
 * decision-relevant signal.
 *
 * WHY 14px HERO (not 18px): T-18 spec explicitly calls out "14px (NOT 18px!)".
 * The sidebar at 240px is narrower than 280px; 18px overflows on tickers with
 * 3-digit targets (e.g. "$421.50"). 14px fits comfortably at mono spacing.
 *
 * WHY DataFreshnessPill: analysts want to know if the consensus is fresh
 * (updated after last earnings) or stale (set 8 months ago). The pill answers
 * "when was this last revised?" without consuming additional vertical space.
 *
 * WHO USES IT: AnalystSidebar.tsx (T-24).
 * DATA SOURCE: analyst_target_price + updated_at from Fundamentals.
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

import { DataFreshnessPill } from "@/components/primitives/DataFreshnessPill";
import { formatPrice } from "@/lib/utils";

interface TargetPricePanelProps {
  targetPrice: number | null;
  /** Current price for upside/downside delta calculation. Optional. */
  currentPrice?: number | null;
  updatedAt: string | null;
}

function upsideColor(pct: number): string {
  if (pct > 0.05) return "text-positive";
  if (pct < -0.05) return "text-negative";
  return "text-foreground";
}

/**
 * markerPercents — positions of the current-price and target-price markers
 * on the 0–100% track.
 *
 * WHY the ±2% band padding: with exactly two values, an unpadded scale puts
 * one marker at 0% and the other at 100% — both half-clipped by the track's
 * rounded ends. Padding the band keeps both fully visible.
 *
 * WHY the span === 0 guard (Round-1 requirement 3): when a single analyst's
 * target EQUALS the current price (or only one value exists, min == max),
 * `(v - lo) / span` divides by zero → NaN% → the browser drops the style and
 * the bar collapses. Centering both markers at 50% keeps the bar rendering
 * for ANY input.
 */
function markerPercents(current: number, target: number): { current: number; target: number } {
  const lo = Math.min(current, target);
  const hi = Math.max(current, target);
  const span = hi - lo;
  if (span === 0) return { current: 50, target: 50 };
  // Pad the scale by 10% of the span on each side (clamped positions land in
  // [~9%, ~91%] — never clipped by the rounded track ends).
  const padded = span * 1.2;
  const start = lo - span * 0.1;
  return {
    current: ((current - start) / padded) * 100,
    target: ((target - start) / padded) * 100,
  };
}

export function TargetPricePanel({
  targetPrice,
  currentPrice,
  updatedAt,
}: TargetPricePanelProps) {
  // WHY optional upside: currentPrice may not be available at render time
  // (quote is a separate fetch). Gracefully hide the chip when absent.
  const upside =
    targetPrice != null && currentPrice != null && currentPrice !== 0
      ? (targetPrice - currentPrice) / currentPrice
      : null;

  return (
    <div className="flex flex-col gap-1 px-2 py-2 border-b border-border">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
        12-MO TARGET
      </span>

      <div className="flex items-baseline gap-2">
        {/* WHY text-[14px]: T-18 explicitly specifies 14px, not 18px. */}
        <span className="font-mono text-[14px] leading-tight text-foreground tabular-nums">
          {targetPrice != null ? formatPrice(targetPrice) : "—"}
        </span>

        {upside != null && (
          <span className={`font-mono text-[11px] tabular-nums ${upsideColor(upside)}`}>
            {upside > 0 ? "▲" : "▼"} {Math.abs(upside * 100).toFixed(1)}%
          </span>
        )}
      </div>

      {/* ── Current → target bar (Round-1 requirement 3) ─────────────────────
          Visualises where the consensus target sits relative to the live
          price. Renders for ANY non-null pair — including the single-analyst
          / target == current case (markerPercents guards the div-by-zero).
          Hidden only when one of the two prices is missing (a bar with one
          point carries no information). */}
      {targetPrice != null && currentPrice != null && (() => {
        const pos = markerPercents(currentPrice, targetPrice);
        return (
          <div
            className="relative mt-1 h-[4px] rounded-full bg-muted"
            data-testid="target-price-bar"
            aria-label={`Current ${formatPrice(currentPrice)}, target ${formatPrice(targetPrice)}`}
          >
            {/* Fill between the two markers — teal when target above current
                (upside), red when below. Zero-width when equal (markers
                overlap at 50%, which is the honest rendering). */}
            <div
              className={`absolute top-0 h-full ${targetPrice >= currentPrice ? "bg-positive/40" : "bg-negative/40"}`}
              style={{
                left: `${Math.min(pos.current, pos.target).toFixed(1)}%`,
                width: `${Math.abs(pos.target - pos.current).toFixed(1)}%`,
              }}
            />
            {/* Current-price marker — neutral foreground tick. -translate-x-1/2
                centres the 2px tick on its computed position. */}
            <div
              className="absolute top-[-2px] h-[8px] w-[2px] -translate-x-1/2 bg-foreground"
              style={{ left: `${pos.current.toFixed(1)}%` }}
              title={`Current ${formatPrice(currentPrice)}`}
            />
            {/* Target marker — primary (yellow) tick, the eye-catcher. */}
            <div
              className="absolute top-[-2px] h-[8px] w-[2px] -translate-x-1/2 bg-primary"
              style={{ left: `${pos.target.toFixed(1)}%` }}
              title={`Target ${formatPrice(targetPrice)}`}
            />
          </div>
        );
      })()}

      {updatedAt && (
        <DataFreshnessPill lastUpdated={updatedAt} format="relative" />
      )}
    </div>
  );
}
