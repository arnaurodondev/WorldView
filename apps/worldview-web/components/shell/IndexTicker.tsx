/**
 * components/shell/IndexTicker.tsx — Live index price bar in TopBar
 *
 * WHY THIS EXISTS: Bloomberg Terminal's top bar always shows key index prices.
 * Portfolio managers need a constant visual reference for SPY, QQQ, VIX, and BTC
 * to quickly gauge market sentiment without navigating away.
 *
 * WHY batch quotes (not 4 individual requests):
 * POST /v1/quotes/batch fetches all 4 instruments in one round-trip.
 * 4 parallel requests would create unnecessary server load and could arrive in
 * inconsistent order. Batch ensures all 4 prices are from the same snapshot.
 *
 * WHY 15s refetch interval:
 * Equity prices update every 15-30s in production (rate limits on EODHD delayed quotes).
 * 15s matches the data freshness window — refreshing faster would show the same data
 * while burning API quota. Real-time would require the WebSocket path (different scope).
 *
 * WHO USES IT: components/shell/TopBar.tsx (center)
 * DATA SOURCE: S9 POST /api/v1/quotes/batch → S3 market data service
 * DESIGN REFERENCE: PRD-0028 §6.5 TopBar sub-components
 */

"use client";
// WHY "use client": Uses TanStack Query (useQuery) which manages client-side cache.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercentDirect, priceChangeClass } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

// WHY these 4 symbols: SPY (US equities), QQQ (tech/growth), VIX (volatility/fear gauge),
// BTC (crypto sentiment). Together they give an instant macro read in 4 numbers.
const INDEX_TICKERS = [
  { id: "SPY", label: "SPY" },
  { id: "QQQ", label: "QQQ" },
  { id: "VIX", label: "VIX" },
  { id: "BTC-USD", label: "BTC" },
];

export function IndexTicker() {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["index-tickers"],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.getBatchQuotes(INDEX_TICKERS.map((t) => t.id));
    },
    // WHY refetchInterval: prices should update every 15s while user is on screen
    refetchInterval: 15_000,
    // WHY staleTime 0: we always want fresh prices from the cache perspective;
    // refetchInterval handles the actual refresh cadence
    staleTime: 0,
    // WHY disabled when no token: batch quotes require auth. Show — placeholders.
    enabled: !!accessToken,
  });

  if (isLoading) {
    // WHY 4 skeletons: pre-reserves space so TopBar doesn't reflow when data arrives
    return (
      // WHY gap-2: matches the loaded state gap for layout stability during skeleton→data transition
      <div className="flex items-center gap-2">
        {INDEX_TICKERS.map((t) => (
          <Skeleton key={t.id} className="h-5 w-20" />
        ))}
      </div>
    );
  }

  // WHY show dashes (not nothing) on error: TopBar must stay stable.
  // A missing index ticker is not a critical error — user can see prices in instruments.
  const quotes = data?.quotes ?? {};

  return (
    // WHY gap-2 (was gap-4): tighter spacing keeps the 4-ticker strip compact in
    // the 44px TopBar chrome. gap-4 (16px) added unnecessary width on wide monitors.
    <div className="flex items-center gap-2">
      {INDEX_TICKERS.map((ticker) => {
        const quote = quotes[ticker.id];

        // WHY: stale/delayed prices should not show live change-direction coloring.
        // The price may have moved since it was recorded — green/red would be misleading.
        // A delayed SPY price might show +1.2% from yesterday's close, but SPY is
        // actually down -0.5% right now. Muted color prevents misreading.
        const isStale =
          !!quote?.freshness_status &&
          ["delayed", "stale", "unavailable"].includes(quote.freshness_status);

        return (
          <div key={ticker.id} className="flex items-center gap-1">
            {/* Label — small, muted, uppercase for terminal aesthetic */}
            <span className="text-xs font-medium text-muted-foreground">{ticker.label}</span>

            {/* Price — monospace for alignment, colored by change direction.
                WHY muted when stale: the price is not current, so directional coloring
                (green = up, red = down) would be misleading. Muted signals "old data". */}
            <span
              className={`font-mono text-xs tabular-nums ${
                !quote
                  ? "text-muted-foreground"
                  : isStale
                    ? "text-muted-foreground" // WHY muted: stale price is not current
                    : priceChangeClass(quote.change_pct ?? null)
              }`}
              title={isStale ? (quote?.stale_reason ?? "Delayed data") : undefined}
            >
              {quote ? formatPrice(quote.price) : "—"}
            </span>

            {/* Only show % change when price is live — stale % is misleading
                because the reference point (previous close) may also be stale. */}
            {quote && !isStale && (
              <span
                className={`font-mono text-xs tabular-nums ${priceChangeClass(quote.change_pct ?? null)}`}
              >
                {formatPercentDirect(quote.change_pct ?? null)}
              </span>
            )}
            {/* Show a subtle dot for stale prices instead of % change.
                WHY dot: signals "there is a price but it may be old" without
                cluttering the TopBar with a full badge for every index. */}
            {quote && isStale && (
              <span
                className="text-[10px] text-muted-foreground"
                title={quote.stale_reason ?? "Delayed"}
              >
                ·
              </span>
            )}

            {/* Error fallback */}
            {isError && <span className="text-xs text-muted-foreground">—</span>}
          </div>
        );
      })}
    </div>
  );
}
