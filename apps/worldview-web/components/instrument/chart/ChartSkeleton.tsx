/**
 * components/instrument/chart/ChartSkeleton.tsx — shape-matched chart skeleton
 *
 * WHY THIS EXISTS (Round-3 polish, item 4): the OHLCV chart's cold-load state
 * was a single flat <Skeleton> rectangle — technically "not blank", but it
 * gave no hint that a CHART was coming, and the price/time axes popped in
 * with no visual precedent. The polish-sprint rule is "shape-matched
 * skeletons: chart = full-height block w/ axis hints" — this component
 * renders:
 *   - a full-bleed pulsing plot surface (reserves the canvas footprint →
 *     zero layout shift when lightweight-charts paints in-place),
 *   - a right-edge COLUMN of short bars where the price scale will appear,
 *   - a bottom ROW of short bars where the time scale will appear.
 * Both axis hints mirror lightweight-charts' default layout (price axis
 * right, time axis bottom — see useChartSeries.ts chart options), so the
 * skeleton→chart transition reads as "the same surface filled in".
 *
 * WHY absolute inset-0 (positioning owned here, not by the caller): the
 * caller (OHLCVChart) overlays this on the always-mounted WebGL container
 * (the container must stay mounted to preserve the GL context — see the
 * containerRef comment there). Owning the overlay geometry here keeps the
 * call site a one-liner and guarantees the skeleton always covers exactly
 * the canvas slot.
 *
 * WHY role="status": loading is announceable state (same convention as the
 * EmptyState primitive and GraphColumn's GraphSkeleton); the bars themselves
 * are decorative → aria-hidden.
 *
 * WHO USES IT: OHLCVChart (cold first fetch, before any bars exist).
 */

// WHY no "use client": pure presentational — no hooks, no browser APIs.

// WHY fixed counts (6 price ticks / 7 time ticks): approximates lightweight-
// charts' default tick density at the Quote tab's canvas size; exact counts
// don't matter — the silhouette does.
const PRICE_TICKS = [0, 1, 2, 3, 4, 5] as const;
const TIME_TICKS = [0, 1, 2, 3, 4, 5, 6] as const;

export function ChartSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading price chart"
      data-testid="chart-skeleton"
      // Round-4 item 4: animation removed per DS §6.2 — skeletons are STATIC
      // by default (raw animate-pulse is banned; the geometry alone carries
      // the "chart loading" signal).
      className="pointer-events-none absolute inset-0 flex"
    >
      {/* ── Plot surface ──────────────────────────────────────────────────
          Faint fill bounded above/below like a real candle series (price
          action rarely touches the canvas edges). */}
      <div className="relative min-w-0 flex-1">
        <div aria-hidden className="absolute inset-x-2 top-[12%] bottom-[18%] rounded-[2px] bg-muted/15" />
        {/* Bottom time-axis hint — short bars where date labels will sit. */}
        <div aria-hidden className="absolute inset-x-4 bottom-1 flex items-center justify-between">
          {TIME_TICKS.map((i) => (
            <span key={i} className="h-2 w-8 rounded-[1px] bg-muted/40" />
          ))}
        </div>
      </div>

      {/* ── Right price-axis hint — column of short bars where price labels
          will sit; border-l mirrors the real scale's edge. ──────────────── */}
      <div
        aria-hidden
        className="flex w-12 shrink-0 flex-col items-start justify-between border-l border-border/30 py-6 pl-1"
      >
        {PRICE_TICKS.map((i) => (
          <span key={i} className="h-2 w-9 rounded-[1px] bg-muted/40" />
        ))}
      </div>
    </div>
  );
}
