/**
 * components/shell/MarqueeTickerChip.tsx — Single ticker chip inside TopBarMarquee
 *
 * WHY THIS EXISTS: Extracted from TopBarMarquee so the chip rendering logic
 * is testable in isolation (snapshot test + data contract) and re-usable if
 * the marquee layout ever changes (e.g. vertical vs horizontal scroll).
 *
 * WHY THIS SHAPE: Mirrors IndexTicker.tsx's renderCell but adds a separator
 * pipe (|) to the right so chips remain visually distinct in the continuous
 * scrolling strip without needing margin — margin creates a gap in the seamless
 * loop; a sibling pipe-char is easier to align.
 *
 * DATA CONTRACT:
 *   ticker  — { id: string; label: string }
 *   quote   — IndexQuote | undefined; undefined renders em-dash placeholders
 *   isError — boolean; shows fallback if batch-quote failed
 *
 * DESIGN REFERENCE: Handoff (2026-05-01) Tier-3 #7 TopBar marquee spec
 */

import { formatPrice, formatPercentDirect, priceChangeClass } from "@/lib/utils";

/** Quote shape returned by the batch-quotes endpoint. */
export type IndexQuote = {
  price?: number;
  change_pct?: number | null;
  freshness_status?: string;
  stale_reason?: string | null;
};

export type TickerItem = {
  id: string;    // API key (e.g. "BTC-USD")
  label: string; // Display label (e.g. "BTC")
};

type Props = {
  ticker: TickerItem;
  quote: IndexQuote | undefined;
  isError: boolean;
};

/**
 * MarqueeTickerChip renders one <symbol> <price> <change%> triple for the
 * scrolling marquee strip. Stateless: all data is passed via props so the
 * parent can debounce/cache fetches centrally.
 */
export function MarqueeTickerChip({ ticker, quote, isError }: Props) {
  const isStale =
    !!quote?.freshness_status &&
    ["delayed", "stale", "unavailable"].includes(quote.freshness_status);

  const colorClass =
    !quote || isStale || isError
      ? "text-muted-foreground"
      : priceChangeClass(quote.change_pct ?? null);

  return (
    /* WHY flex items-center: keeps symbol, price, and pct vertically centered
     * in the 36px TopBar without fighting the parent's flex-1 constraints. */
    <span
      className="flex items-center gap-1 px-3"
      aria-label={`${ticker.label} ${quote ? formatPrice(quote.price) : "unavailable"}`}
    >
      {/* Symbol — bold-white, matches Bloomberg ticker labelling convention. */}
      <span className="text-[11px] font-bold text-foreground">{ticker.label}</span>

      {/* Price in monospace so digits don't shift as values update. */}
      <span
        className={`font-mono text-[11px] tabular-nums ${colorClass}`}
        title={isStale ? (quote?.stale_reason ?? "Delayed data") : undefined}
      >
        {quote && !isError ? formatPrice(quote.price) : "—"}
      </span>

      {/* Daily % change — only show when fresh data is available. */}
      {quote && !isError && !isStale && (
        <span className={`font-mono text-[11px] tabular-nums ${priceChangeClass(quote.change_pct ?? null)}`}>
          {formatPercentDirect(quote.change_pct ?? null)}
        </span>
      )}

      {/* Visual separator between chips — avoids gap-based layout which
          breaks seamless loop when the list repeats. */}
      <span className="ml-2 text-[10px] text-border" aria-hidden="true">|</span>
    </span>
  );
}
