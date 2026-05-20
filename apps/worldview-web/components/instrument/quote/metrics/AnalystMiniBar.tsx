/**
 * components/instrument/quote/metrics/AnalystMiniBar.tsx — compact analyst breakdown
 *
 * WHY: PRD-0088 §6.7.2 wants a one-row analyst-rating summary in the Stats
 * rail. AnalystConsensusStrip is too tall for a 22px row, so this mini
 * variant compresses Strong-Buy / Buy / Hold / Sell / Strong-Sell into a
 * 4px tri-segment bar plus a "{B}B · {H}H · {S}S" textual breakdown.
 *
 * WHY collapse 5 buckets → 3 (Buy / Hold / Sell): 5 segments in a 4px-tall
 * bar would render sub-pixel slivers for low-coverage tickers. Three colours
 * (positive/amber/negative) match our threshold-colour vocabulary.
 *
 * WHY total === 0 guard: all-null OR all-zero counts would divide by zero
 * and produce NaN%. Guard renders an empty bar shell — preserves layout,
 * no console errors. Below-bar text reads "0B · 0H · 0S" in that case.
 *
 * WHY font-mono: tabular numerals column-align across stacked instances.
 *
 * DATA: parent reads AnalystConsensus (types/api.ts). REF: PLAN-0090 §T-B-02.
 */

// WHY no "use client": pure display — props only.

interface AnalystMiniBarProps {
  /** Strong-Buy count; null when consensus unavailable. */
  strongBuy: number | null;
  /** Buy count. */
  buy: number | null;
  /** Hold count. */
  hold: number | null;
  /** Sell count. */
  sell: number | null;
  /** Strong-Sell count. */
  strongSell: number | null;
}

// WHY tiny `n` helper: null → 0 keeps arithmetic terse and ensures we never
// propagate null into a width calculation. Centralises the divide-by-zero
// guard reasoning below.
const n = (x: number | null): number => (x == null ? 0 : x);

export function AnalystMiniBar({ strongBuy, buy, hold, sell, strongSell }: AnalystMiniBarProps) {
  // Collapse 5 buckets → 3 per the WHY note above.
  const buyCount = n(strongBuy) + n(buy);
  const holdCount = n(hold);
  const sellCount = n(sell) + n(strongSell);
  const total = buyCount + holdCount + sellCount;

  // WHY closes over `total` and short-circuits on 0: never divide by zero.
  // Returning "0%" yields a valid CSS width that simply collapses the segment.
  const pct = (count: number): string => (total === 0 ? "0%" : `${(count / total) * 100}%`);

  return (
    <div className="flex flex-col gap-0.5 px-3 py-1">
      {/* Stacked-segment bar. gap-px draws a 1px gutter so segments read as
          distinct blocks even at very thin widths. */}
      <div className="flex h-[4px] rounded-full overflow-hidden gap-px">
        <div style={{ width: pct(buyCount) }} className="h-full bg-positive" />
        {/* WHY bg-warning (not bg-amber-400): off-palette colors test. */}
        <div style={{ width: pct(holdCount) }} className="h-full bg-warning" />
        <div style={{ width: pct(sellCount) }} className="h-full bg-negative" />
      </div>
      {/* WHY "{B}B · {H}H · {S}S": short for 22px row; mono dots centre cleanly. */}
      <span className="text-[10px] font-mono text-muted-foreground">
        {`${buyCount}B · ${holdCount}H · ${sellCount}S`}
      </span>
    </div>
  );
}
