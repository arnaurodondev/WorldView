/**
 * components/instrument/52WeekRangeBar.tsx — 52-week price range visual bar
 *
 * WHY THIS EXISTS: Analysts need an instant visual read on where the current
 * price sits within its 52-week range. A plain "52W HI / 52W LO" number pair
 * requires mental arithmetic; this bar encodes position at a glance.
 *
 * VISUAL:
 *   $192.41 [────●──────────] $288.35
 *                ↑ current price marker
 *
 * WHY h-1 bar (not taller): Terminal UI §0.1 data density — the bar should
 * coexist with a 22px row without dominating it. The 4px bar + 12px label
 * row fits in a 22px row with standard px-2 padding.
 *
 * WHY clamp (not error): If current price is outside [low, high] due to live
 * quote latency vs stale 52-week data, clamping at 0%/100% is less confusing
 * than a marker outside the bar.
 *
 * WHO USES IT: CompactInstrumentHeader (Wave C-1), FundamentalsTab 52W Range
 * section (Wave D-1), OverviewSidebarMetrics (Wave C-1)
 * DATA SOURCE: Props from parent — low/high from Fundamentals, current from Quote
 * DESIGN REFERENCE: PLAN-0041 §T-B-1-03
 */

// WHY no "use client": pure display component — props only, no hooks or browser APIs.

import { formatPrice } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface WeekRangeBarProps {
  /** 52-week low price */
  low: number | null;
  /** 52-week high price */
  high: number | null;
  /** Current price — determines marker position */
  current: number | null;
  /** Optional extra className applied to the root wrapper */
  className?: string;
  /**
   * When false, omit the low/high label row below the track.
   * Default true. Set to false in compact contexts (e.g., header row) where
   * the labels would overflow the row height.
   */
  showLabels?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WeekRangeBar({ low, high, current, className = "", showLabels = true }: WeekRangeBarProps) {
  // ── Guard: if any required value is missing, render a flat unavailable bar ──
  // WHY render the shell (not null): keeps layout stable — the section always
  // takes up the same vertical space regardless of data availability.
  // F-QA-04 fix: when showLabels=false (compact header row 2), use the same
  // single-element render as the populated branch below so the parent flex
  // items-center centers the 4px bar correctly. The prior implementation
  // re-wrapped in a flex-col here, reintroducing the alignment bug T-F-6-08
  // closed in the populated branch.
  if (low == null || high == null || current == null) {
    if (!showLabels) {
      return <div className={`relative h-1 w-full rounded-full bg-muted ${className}`} />;
    }
    return (
      <div className={`flex flex-col gap-0.5 ${className}`}>
        {/* Flat muted bar — signals "no data" without showing numbers */}
        <div className="relative h-1 bg-muted rounded-full w-full" />
        {/* Empty labels maintain height */}
        <div className="flex justify-between">
          <span className="font-mono text-[10px] text-muted-foreground">—</span>
          <span className="font-mono text-[10px] text-muted-foreground">—</span>
        </div>
      </div>
    );
  }

  // ── Edge case: low >= high (degenerate range e.g. first-day listed stock) ──
  // WHY 50% (not 0%): centers the marker to signal "range unknown", not "at bottom"
  const rangeSpan = high - low;
  const rawPercent = rangeSpan > 0 ? ((current - low) / rangeSpan) * 100 : 50;

  // ── Clamp to [0, 100] — handles live price outside stale 52W bounds ──────
  const clampedPercent = Math.max(0, Math.min(100, rawPercent));

  // PLAN-0050 T-F-6-08 (closes F-I-010): when the labels are NOT shown
  // (compact header row 2), the prior `flex flex-col gap-0.5` wrapper put
  // the 4px bar at the top of its column box. Inside a parent `flex
  // items-center h-7` row that pushed the bar visually above the
  // mid-line of the row's text. Switching to a single-element render in
  // the no-labels branch lets the parent's `items-center` align the bar
  // with the text baseline. The labels branch keeps the column.
  if (!showLabels) {
    return (
      <div className={`relative h-1 w-full rounded-full bg-muted ${className}`}>
        <div
          className="absolute -top-0.5 h-2 w-1.5 rounded-full bg-primary"
          style={{ left: `${clampedPercent}%`, transform: "translateX(-50%)" }}
        />
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      {/* ── Bar + marker ──────────────────────────────────────────────────── */}
      {/* WHY relative on parent + absolute on marker: the marker must be
          positioned as a percentage of the bar's pixel width, which requires
          the bar to be the positioned ancestor. */}
      <div className="relative h-1 bg-muted rounded-full w-full">
        {/* Current price marker — vertical tick above the track */}
        {/* WHY -translate-x-1/2: centres the 6px marker over the percentage point */}
        {/* WHY -top-0.5 h-2: the marker extends 2px above and below the 4px track,
            giving it visual prominence without changing the bar's layout footprint */}
        <div
          className="absolute -top-0.5 h-2 w-1.5 bg-primary rounded-full"
          style={{ left: `${clampedPercent}%`, transform: "translateX(-50%)" }}
        />
      </div>

      {/* ── Low / High labels ──────────────────────────────────────────────── */}
      {/* WHY font-mono text-[10px]: terminal data label typography (§0.1) */}
      <div className="flex justify-between">
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatPrice(low)}
        </span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {formatPrice(high)}
        </span>
      </div>
    </div>
  );
}
