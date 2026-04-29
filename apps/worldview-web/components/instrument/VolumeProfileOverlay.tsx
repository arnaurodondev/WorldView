/**
 * components/instrument/VolumeProfileOverlay.tsx — Right-side volume profile histogram
 *
 * WHY THIS EXISTS: Volume Profile shows which price levels had the most trading
 * activity over the visible chart range. Unlike time-based volume bars (which show
 * volume per candle), Volume Profile shows volume per price level — horizontal bars
 * on the right side of the chart. The Point of Control (POC) — the highest-volume
 * price — is highlighted as a key support/resistance reference.
 *
 * WHY SEPARATE COMPONENT (not inline in OHLCVChart): The volume profile is a pure
 * SVG rendering component. It has no lightweight-charts dependency — it only needs
 * the price-to-pixel converter and the profile data. Extracting it keeps OHLCVChart
 * focused on chart series management.
 *
 * WHY SVG (not lightweight-charts series): lightweight-charts v4 does not support
 * horizontal histogram series natively. We render the profile as an absolutely-
 * positioned SVG overlay on the right side of the chart, using priceToCoordinate
 * to map bucket prices to pixel Y positions.
 *
 * WHY RIGHT SIDE: Volume Profile by convention appears on the right side of the
 * price chart, occupying the rightmost ~60px of the chart width, inside the price
 * scale gutter. TradingView and Bloomberg use this exact placement.
 *
 * WHO USES IT: OHLCVChart
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-03
 */

// WHY no "use client": VolumeProfileOverlay is a pure render component.
// All data and converters are passed via props — no hooks needed.

import type { VolumeProfileBucket } from "@/lib/instrument-context";
import type { CoordinateConverter } from "@/components/instrument/DrawingCanvas";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface VolumeProfileOverlayProps {
  /** Volume profile buckets (from computeVolumeProfile in instrument-context.ts) */
  buckets: VolumeProfileBucket[];
  /** Coordinate converters from OHLCVChart (after chart init) */
  converters: CoordinateConverter | null;
  /** Chart height in pixels */
  chartHeight: number;
  /** Width of the profile histogram (px) — anchored to the right edge */
  profileWidth?: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * PROFILE_WIDTH_DEFAULT — width of the Volume Profile histogram (pixels).
 *
 * WHY 60px: wide enough to show bar length differences visually, narrow enough
 * not to occlude too much of the price action. TradingView default is ~60px.
 */
const PROFILE_WIDTH_DEFAULT = 60;

/**
 * BAR_COLOR — translucent brand teal for normal profile bars.
 *
 * WHY #26A69A (positive teal) at 40% opacity: reuses the existing positive color
 * so the profile integrates with the chart palette without introducing a new hue.
 * The opacity makes it clearly secondary to the candlestick price action.
 */
const BAR_COLOR = "#26A69A66"; // 40% opacity

/**
 * POC_COLOR — solid primary yellow for the Point of Control bar.
 *
 * WHY #FFD60A (brand primary): the POC is the most important price level in the
 * volume profile. Using the brand primary distinguishes it from the normal bars
 * and draws the analyst's attention immediately. Matches the annotation color.
 */
const POC_COLOR = "#FFD60A";

// ── Component ─────────────────────────────────────────────────────────────────

export function VolumeProfileOverlay({
  buckets,
  converters,
  chartHeight,
  profileWidth = PROFILE_WIDTH_DEFAULT,
}: VolumeProfileOverlayProps) {
  // WHY early return when no converters: the chart hasn't initialised yet.
  // Rendering without converters would place all bars at y=0.
  if (!converters || buckets.length === 0) return null;

  // Find the maximum volume across all buckets — used to normalise bar widths
  // so the widest bar fills `profileWidth` and narrower bars are proportional.
  const maxVolume = Math.max(...buckets.map((b) => b.volume));
  if (maxVolume === 0) return null;

  return (
    // WHY absolute inset-y-0 right-0: overlays exactly the right edge of the
    // chart container. The SVG sits above the chart canvas (z-5) but below the
    // drawing palette (z-10) and toolbar controls.
    <svg
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        width: profileWidth,
        height: chartHeight,
        pointerEvents: "none", // never intercept chart mouse events
        zIndex: 4,
      }}
      data-testid="volume-profile-overlay"
      aria-label="Volume profile histogram"
      aria-hidden="true" // decorative SVG — screen readers don't need to parse it
    >
      {buckets.map((bucket, i) => {
        // Convert price to pixel Y coordinate using the chart's price scale
        const py = converters.series.priceToCoordinate(bucket.price) as number | null;
        if (py === null) return null;

        // Normalise bar width: maxVolume bucket fills profileWidth, others proportional
        const barWidth = (bucket.volume / maxVolume) * profileWidth;

        // WHY bucket height of 3px (not price range derived): the pixel height of
        // a price bucket depends on zoom level — at very zoomed-out views, price
        // buckets collapse to sub-pixel height. A fixed 3px height ensures the
        // bars are always visible regardless of zoom. The bars may overlap at
        // zoom-out (visually acceptable — this is a heatmap-style profile, not a
        // precise y-coordinate chart).
        const barHeight = 3;

        return (
          <rect
            key={i}
            // WHY right-anchored: bars grow leftward from the right edge.
            // x = profileWidth - barWidth places the right edge at the SVG right.
            x={profileWidth - barWidth}
            y={py - barHeight / 2}
            width={barWidth}
            height={barHeight}
            fill={bucket.isPOC ? POC_COLOR : BAR_COLOR}
            // WHY rx=0: no border radius at this density — rounded corners would
            // add visual noise to 3px bars and affect alignment.
          />
        );
      })}

      {/* WHY the POC label: the POC is the most important price level. Showing
          the price value at the POC bar helps analysts immediately identify it
          as a key support/resistance without needing to hover. */}
      {buckets
        .filter((b) => b.isPOC)
        .map((poc) => {
          const py = converters.series.priceToCoordinate(poc.price) as number | null;
          if (py === null) return null;
          return (
            <text
              key="poc-label"
              x={2}
              y={py - 4}
              fill={POC_COLOR}
              fontSize={8}
              fontFamily="IBM Plex Mono, monospace"
            >
              POC
            </text>
          );
        })}
    </svg>
  );
}
