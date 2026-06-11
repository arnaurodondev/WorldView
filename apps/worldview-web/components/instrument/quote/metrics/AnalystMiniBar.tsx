/**
 * components/instrument/quote/metrics/AnalystMiniBar.tsx — compact analyst breakdown
 *
 * WHY: PRD-0088 §6.7.2 wants a one-glance analyst-rating summary in the Stats
 * rail. This mini variant compresses Strong-Buy / Buy / Hold / Sell /
 * Strong-Sell into a 4px tri-segment bar plus a colour-coded textual
 * breakdown.
 *
 * WHY collapse 5 buckets → 3 (Buy / Hold / Sell): 5 segments in a 4px-tall
 * bar would render sub-pixel slivers for low-coverage tickers. Three colours
 * (positive/amber/negative) match our threshold-colour vocabulary.
 *
 * ── WAVE-2 REDESIGN (2026-06-10) ─────────────────────────────────────────────
 * The old readout was the cryptic "0B · 0H · 0S" — meaningless noise when a
 * ticker has no coverage and hard to parse even when populated. Now:
 *   - total === 0 → the bar is HIDDEN and a single muted "No analyst
 *     coverage" line renders instead (honest empty state, no fake bar);
 *   - total > 0  → "{B} Buy · {H} Hold · {S} Sell" with each count coloured
 *     by its bucket, plus the total analyst count right-aligned so the
 *     sample size is never hidden ("31 Buy" from 47 analysts ≠ from 5).
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

  // ── Empty state: no coverage → no bar, one honest line ─────────────────────
  // WHY hide the bar entirely (Wave-2): an all-grey empty bar + "0B · 0H · 0S"
  // read as broken data. "No analyst coverage" is a real market fact for
  // small caps — name it.
  if (total === 0) {
    return (
      <div className="flex items-center h-[22px] px-3">
        <span className="text-[10px] font-mono text-muted-foreground/50 italic">
          No analyst coverage
        </span>
      </div>
    );
  }

  // Segment width helper — total > 0 is guaranteed here (guard above).
  const pct = (count: number): string => `${(count / total) * 100}%`;

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
      {/* Colour-coded textual breakdown + right-aligned sample size.
          WHY per-bucket colour spans: the eye maps text → bar segment without
          a legend; the total ("47 analysts") qualifies the consensus. */}
      <span className="flex items-baseline justify-between text-[10px] font-mono tabular-nums">
        <span>
          <span className="text-positive">{buyCount} Buy</span>
          <span className="text-muted-foreground/50"> · </span>
          <span className="text-warning">{holdCount} Hold</span>
          <span className="text-muted-foreground/50"> · </span>
          <span className="text-negative">{sellCount} Sell</span>
        </span>
        <span className="text-muted-foreground/60">{total} analysts</span>
      </span>
    </div>
  );
}
