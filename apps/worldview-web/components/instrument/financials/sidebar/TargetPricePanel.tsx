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

      {updatedAt && (
        <DataFreshnessPill lastUpdated={updatedAt} format="relative" />
      )}
    </div>
  );
}
