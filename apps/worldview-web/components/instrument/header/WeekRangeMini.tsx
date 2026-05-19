/**
 * components/instrument/header/WeekRangeMini.tsx — 52-week range mini-bar
 *
 * WHY THIS EXISTS: PRD-0088 §6.4 specifies a 60×6px bar that visualises
 * where the live price sits inside its 52-week low→high band — a glance
 * tells the trader "near top" vs "near bottom" without reading numbers.
 * WHO USES IT: components/instrument/header/InstrumentHeader.tsx only.
 * DATA SOURCE: fundamentals.week_52_high/low + quote.price.
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.4 right-cluster.
 * TARGET READER: junior Next.js dev — linear interp (current-low)/(high-low).
 */

interface WeekRangeMiniProps {
  /** 52-week high in instrument currency (e.g. USD). null when fundamentals not yet loaded. */
  readonly high: number | null;
  /** 52-week low in instrument currency. null when fundamentals not yet loaded. */
  readonly low: number | null;
  /** Current quote price. null when quote not yet fetched. */
  readonly current: number | null;
}

export function WeekRangeMini({ high, low, current }: WeekRangeMiniProps) {
  // WHY guard for null + zero-range: if any input is null we render the
  // empty (0% fill) bar instead of crashing. We also bail when high===low
  // because that would divide by zero — a degenerate but legitimate state
  // for newly listed instruments (no real 52-week history yet).
  const rawPercent =
    high != null && low != null && current != null && high !== low
      ? ((current - low) / (high - low)) * 100
      : 0;

  // WHY clamp [0,100]: a stock can briefly trade ABOVE its 52W high or
  // BELOW its 52W low on the very day the new extreme prints (the
  // fundamentals snapshot is end-of-day; the live quote is intraday).
  // Without the clamp the fill div would overflow its parent and look
  // like a layout bug to users.
  const percent = Math.max(0, Math.min(100, rawPercent));

  return (
    <div className="relative h-[6px] w-[60px] rounded-full bg-muted" aria-label="52-week price range">
      <div
        className="h-full rounded-full bg-primary"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
