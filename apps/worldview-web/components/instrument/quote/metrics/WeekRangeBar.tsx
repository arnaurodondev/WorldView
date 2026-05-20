/**
 * components/instrument/quote/metrics/WeekRangeBar.tsx — compact 52W range bar
 *
 * WHY: PRD-0088 §6.7.2 §52W RANGE asks for a visual marker showing where the
 * live price sits inside its 52-week band, alongside the HI/LO numeric rows.
 *
 * WHY separate from top-level `52WeekRangeBar.tsx`: the top-level one is
 * tuned for the page header (taller, labelled). This one lives in the 22px
 * right-rail row and needs aggressive size/label compression.
 *
 * WHY clamp [0, 100]: live quote can briefly dip outside the cached 52W band
 * (after-hours print, stale fundamentals) and an unclamped width would blow
 * the bar off-screen. Also defends against high === low (divide-by-zero).
 * WHY null → 0% fill: keeps 22px row cadence stable while data loads.
 *
 * DATA: high/low from Fundamentals, current from Quote. REF: PLAN-0090 §T-B-02.
 */

// WHY no "use client": pure display — props only.

interface WeekRangeBarProps {
  /** 52-week high price; null when fundamentals not loaded. */
  high: number | null;
  /** 52-week low price; null when fundamentals not loaded. */
  low: number | null;
  /** Current/live price; null while quote pending. */
  current: number | null;
}

export function WeekRangeBar({ high, low, current }: WeekRangeBarProps) {
  // WHY guard nulls AND high <= low: each condition yields a meaningless
  // percentage. Collapse all to 0% so the bar still renders (no layout
  // shift) but visually signals "no data". Math.max/Math.min then clamps
  // any transient outlier where `current` lies outside [low, high].
  let percent = 0;
  if (high != null && low != null && current != null && high > low) {
    const raw = ((current - low) / (high - low)) * 100;
    percent = Math.max(0, Math.min(100, raw));
  }
  // WHY .toFixed(1) + "%": stable CSS string, avoids fractional-pixel rounding.
  const width = `${percent.toFixed(1)}%`;

  return (
    // WHY h-[22px]: aligns with surrounding MetricRow rhythm.
    <div className="flex items-center h-[22px] px-3">
      <span className="text-[9px] font-mono text-muted-foreground">LOW</span>
      {/* Track — flex-1 fills row; relative so fill can be absolutely placed. */}
      <div className="flex-1 mx-2 relative h-[4px] bg-muted rounded-full">
        {/* WHY inline width style: Tailwind can't enumerate every percent. */}
        <div style={{ width }} className="h-full bg-primary rounded-full absolute left-0" />
      </div>
      <span className="text-[9px] font-mono text-muted-foreground">HIGH</span>
    </div>
  );
}
