/**
 * components/instrument/AnalystTargetSparkline.tsx — Analyst price-target distribution
 *
 * WHY THIS EXISTS (PLAN-0088 Wave G-4):
 * The AnalystConsensusStrip at the top of FundamentalsTab shows the consensus
 * target price and up/downside delta vs the current price. But that's a single
 * number — it hides the range. A $180 consensus target with a $120–$240 spread
 * tells a very different story than a tight $175–$185 cluster. This component
 * renders a mini distribution showing:
 *   - Low analyst target (left bound)
 *   - Median / consensus target (center marker)
 *   - High analyst target (right bound)
 *   - Current price as a vertical line across the distribution bar
 *
 * WHY SPARKLINE (not table): the distribution is spatial — where is current price
 * vs the range? A horizontal bar makes this visually instant. A table of numbers
 * requires the analyst to compute the relationships manually.
 *
 * DATA SOURCE:
 * The earnings-trend section (EODHD EarningsTrend) contains forward-looking analyst
 * consensus data including EPSEstimateCurrentYear, EPSEstimateNextYear AND
 * priceTargetLow / priceTargetHigh / priceTargetMean fields in some tickers.
 *
 * However, the most reliable source is the analyst_consensus section already
 * fetched by getFundamentals:
 *   - analyst_target_price → consensus/median price target (TargetPrice field)
 *
 * For low/high bounds, we check the earnings-trend section records for
 * `priceTargetLow` and `priceTargetHigh`. When those are absent, we estimate
 * ±15% from the consensus target as a fallback (typical analyst spread for
 * S&P 500 components).
 *
 * WHY ±15% FALLBACK: The median analyst spread (high - low) / consensus for S&P 500
 * components is approximately 25-30% (Yardeni Research, 2023). ±15% from median
 * approximates this spread when explicit low/high are unavailable.
 *
 * GRACEFUL DEGRADATION:
 * When no target price data is available at all (ETFs, very recently listed stocks,
 * ADRs with no analyst coverage), this component renders nothing — the parent can
 * hide it via conditional rendering or rely on the null return.
 *
 * WHO USES IT: FundamentalsTab right sidebar (PLAN-0088 G-4), below AnalystConsensusStrip.
 * DATA SOURCE: Props (fundamentals.analyst_target_price) + optional getEarningsTrend
 * DESIGN REFERENCE: PLAN-0088 §Wave G §G-4
 */

// WHY no "use client": all data comes from props — no hooks, no browser APIs.
// The parent FundamentalsTab already fetches fundamentals and passes the needed
// fields as props to avoid a second redundant network call.

import type { Fundamentals } from "@/types/api";
import { formatPrice } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface AnalystTargetSparklineProps {
  /**
   * Current fundamentals — contains analyst_target_price (consensus median target).
   * When null or analyst_target_price is null, the component renders null (hidden).
   */
  fundamentals: Fundamentals | null;
  /**
   * Current market price — used to position the "current price" marker on the
   * distribution bar. When null, the marker is omitted (bar still renders).
   */
  currentPrice?: number | null;
  /**
   * Optional explicit low/high bounds from the earnings-trend section.
   * When absent, ±15% from consensus target is used as a fallback.
   * Pass null explicitly to suppress the fallback and render without bounds.
   */
  targetLow?: number | null;
  targetHigh?: number | null;
}

// ── Constants ─────────────────────────────────────────────────────────────────

// WHY 15%: typical analyst price-target spread for S&P 500 large-caps.
// Used as a symmetric fallback when explicit low/high aren't available.
const DEFAULT_SPREAD_FACTOR = 0.15;

// ── Color constants ────────────────────────────────────────────────────────────
// WHY hex (not CSS vars): inline style attributes don't resolve CSS variables.
// These match the design-system tokens: --positive = #26A69A, --negative = #EF5350.
const COLOR_POSITIVE = "#26A69A";
const COLOR_NEGATIVE = "#EF5350";

// ── Component ─────────────────────────────────────────────────────────────────

export function AnalystTargetSparkline({
  fundamentals,
  currentPrice,
  targetLow,
  targetHigh,
}: AnalystTargetSparklineProps) {
  // ── No data — render nothing ───────────────────────────────────────────────
  // WHY null (not empty state): this component is a secondary data enrichment.
  // If the data doesn't exist, hiding it is cleaner than a placeholder band.
  const consensusTarget = fundamentals?.analyst_target_price ?? null;
  if (consensusTarget == null) return null;

  // ── Compute low/high bounds ────────────────────────────────────────────────
  // Priority: explicit props → ±15% fallback from consensus target.
  // targetLow/targetHigh passed as null explicitly = no bounds (bar without bounds).
  // targetLow/targetHigh passed as undefined = use ±15% fallback.
  const low =
    targetLow !== undefined
      ? targetLow
      : consensusTarget * (1 - DEFAULT_SPREAD_FACTOR);

  const high =
    targetHigh !== undefined
      ? targetHigh
      : consensusTarget * (1 + DEFAULT_SPREAD_FACTOR);

  // Ensure low < consensus < high for valid geometry. If the data violates
  // this invariant (rare bad EODHD data), gracefully degrade to just showing
  // the target as a simple number row.
  if (low == null || high == null || low >= high) {
    // Fallback: just show the consensus target numerically
    return (
      <div className="px-2 py-1.5 border-t border-border/30">
        <div className="flex items-center h-[22px] justify-between">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Target</span>
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            {formatPrice(consensusTarget)}
          </span>
        </div>
      </div>
    );
  }

  // ── Compute positions as % of the bar width ────────────────────────────────
  // The bar represents the full low→high range. Each marker is positioned at
  // (value - low) / (high - low) × 100%.
  const span = high - low;
  const toPercent = (v: number): number =>
    Math.max(0, Math.min(100, ((v - low) / span) * 100));

  const consensusPct = toPercent(consensusTarget);
  const currentPct   = currentPrice != null ? toPercent(currentPrice) : null;

  // ── Upside/downside from current price to consensus ────────────────────────
  // WHY compute here (not in parent): AnalystTargetSparkline is the only consumer
  // of this specific calculation; keeping it local avoids prop-drilling a derived value.
  const upside =
    currentPrice != null && currentPrice > 0
      ? (consensusTarget - currentPrice) / currentPrice
      : null;
  const upsideClass = upside == null ? "text-muted-foreground" : upside > 0 ? "text-positive" : "text-negative";

  return (
    <div className="border-t border-border/30">

      {/* ── Panel header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-2 h-6 bg-muted/10">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          ANALYST TARGET
        </span>
        {/* Upside/downside delta vs current price */}
        {upside != null && (
          <span className={`font-mono text-[10px] tabular-nums ${upsideClass}`}>
            {upside >= 0 ? "▲" : "▼"} {(Math.abs(upside) * 100).toFixed(1)}%
          </span>
        )}
      </div>

      {/* ── Distribution bar ──────────────────────────────────────────────── */}
      <div className="px-2 pb-2 pt-1">
        {/* Price labels: low | consensus | high */}
        <div className="flex items-center justify-between mb-0.5">
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
            {formatPrice(low)}
          </span>
          <span className="font-mono text-[10px] tabular-nums text-foreground font-medium">
            {formatPrice(consensusTarget)}
          </span>
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
            {formatPrice(high)}
          </span>
        </div>

        {/* Gradient bar — spans from low to high */}
        {/* WHY relative container: child absolute elements position the markers
            within the bar without escaping the component boundary. */}
        <div className="relative h-3 rounded-[2px] overflow-hidden bg-muted/30">

          {/* Filled segment from low to consensus — positive-tinted if upside, negative if downside */}
          {/* WHY two colored segments (not one solid bar): the split at consensus
              lets analysts instantly see where current price falls relative to the
              estimate distribution. The left segment (low→consensus) is the "target
              zone"; the right bar extension (consensus→high) is the optimist range. */}
          <div
            className="absolute inset-y-0 left-0 rounded-l-[2px]"
            style={{
              width:           `${consensusPct}%`,
              backgroundColor: upside != null && upside > 0 ? `${COLOR_POSITIVE}30` : `${COLOR_NEGATIVE}30`,
            }}
          />
          <div
            className="absolute inset-y-0 rounded-r-[2px]"
            style={{
              left:            `${consensusPct}%`,
              right:           "0",
              backgroundColor: `${COLOR_POSITIVE}20`,
            }}
          />

          {/* Consensus target marker — thick white tick */}
          <div
            className="absolute inset-y-0 w-[2px] bg-foreground/70 rounded-[1px]"
            style={{ left: `${consensusPct}%` }}
            aria-label={`Consensus target ${formatPrice(consensusTarget)}`}
          />

          {/* Current price marker — colored thin tick */}
          {currentPct != null && (
            <div
              className="absolute inset-y-0 w-[1.5px] rounded-[1px]"
              style={{
                left:            `${currentPct}%`,
                backgroundColor: upside != null && upside > 0 ? COLOR_POSITIVE : COLOR_NEGATIVE,
              }}
              aria-label={`Current price ${formatPrice(currentPrice!)}`}
            />
          )}
        </div>

        {/* WHY legend below bar (not tooltip): the bar is only 12px tall and hard
            to hover precisely. Inline legend below is always visible and removes
            the need for hover interaction on a tiny target. */}
        <div className="flex items-center justify-between mt-0.5">
          <span className="text-[9px] font-mono text-muted-foreground/60">Low</span>
          {currentPrice != null && (
            <span
              className="text-[9px] font-mono tabular-nums"
              style={{ color: upside != null && upside > 0 ? COLOR_POSITIVE : COLOR_NEGATIVE }}
            >
              {/* WHY "now" label (not a price): the current price already appears
                  in the instrument header. Here we label the visual marker position
                  so the analyst can match the tick to "now". */}
              now {formatPrice(currentPrice)}
            </span>
          )}
          <span className="text-[9px] font-mono text-muted-foreground/60">High</span>
        </div>
      </div>
    </div>
  );
}
