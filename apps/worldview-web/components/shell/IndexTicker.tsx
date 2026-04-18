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
      <div className="flex items-center gap-4">
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
    <div className="flex items-center gap-4">
      {INDEX_TICKERS.map((ticker) => {
        const quote = quotes[ticker.id];

        return (
          <div key={ticker.id} className="flex items-center gap-1">
            {/* Label — small, muted, uppercase for terminal aesthetic */}
            <span className="text-xs font-medium text-muted-foreground">{ticker.label}</span>

            {/* Price — monospace for alignment, colored by change direction */}
            <span
              className={`font-mono text-xs tabular-nums ${
                quote ? priceChangeClass(quote.change_pct ?? null) : "text-muted-foreground"
              }`}
            >
              {quote ? formatPrice(quote.price) : "—"}
            </span>

            {/* Percent change — signed, colored */}
            {quote && (
              <span
                className={`font-mono text-xs tabular-nums ${priceChangeClass(quote.change_pct ?? null)}`}
              >
                {formatPercentDirect(quote.change_pct ?? null)}
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
