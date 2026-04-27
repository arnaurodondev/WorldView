/**
 * components/shell/IndexTicker.tsx — Live index price bar in TopBar
 *
 * WHY THIS EXISTS: Bloomberg Terminal's top bar always shows key index prices.
 * Portfolio managers need a constant visual reference for SPY, QQQ, VIX, and BTC
 * to quickly gauge market sentiment without navigating away.
 *
 * WHY TWO-STEP (search → batch quote):
 * The batch quotes endpoint requires UUIDs (instrument_ids), not ticker symbols.
 * Step 1 resolves each ticker to its instrument_id UUID via the search API.
 * Step 2 batch-quotes the resolved UUIDs. The resolution is cached for 30 min
 * because instrument_ids are stable — they never change for a given ticker.
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

  // ── Step 1: Resolve ticker symbols → instrument_id UUIDs ─────────────────
  // WHY separate query (not inline): instrument_ids are stable — search results
  // don't change. Caching the resolution for 30 min avoids repeated search calls.
  // WHY Promise.allSettled (not Promise.all): one failed search should not block
  // the others — we render whatever tickers we could resolve.
  const { data: tickerToId } = useQuery({
    queryKey: ["index-ticker-ids"],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const searches = await Promise.allSettled(
        INDEX_TICKERS.map((t) =>
          gw.searchInstruments(t.id, 1).then((r) => ({
            ticker: t.id,
            instrumentId: r.results?.[0]?.instrument_id ?? null,
          }))
        )
      );
      const map: Record<string, string | null> = {};
      searches.forEach((r) => {
        if (r.status === "fulfilled") map[r.value.ticker] = r.value.instrumentId;
      });
      return map;
    },
    // WHY 30min: instrument_ids are stable identifiers — no need to re-resolve often.
    staleTime: 30 * 60_000,
    enabled: !!accessToken,
  });

  // ── Step 2: Batch-quote resolved instrument_id UUIDs ─────────────────────
  // WHY filter(Boolean): skip any ticker whose resolution failed (null instrumentId).
  const resolvedIds = Object.values(tickerToId ?? {}).filter((id): id is string => !!id);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["index-tickers", resolvedIds],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.getBatchQuotes(resolvedIds);
    },
    // WHY refetchInterval: prices should update every 15s while user is on screen
    refetchInterval: 15_000,
    // WHY staleTime 0: we always want fresh prices from the cache perspective;
    // refetchInterval handles the actual refresh cadence
    staleTime: 0,
    // WHY disabled when no resolved IDs: wait for Step 1 to finish before fetching.
    enabled: !!accessToken && resolvedIds.length > 0,
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
        // WHY lookup via tickerToId: batch quotes are keyed by instrument_id UUID,
        // not ticker symbol. Map back: ticker → instrument_id → quote.
        const instrumentId = tickerToId?.[ticker.id];
        const quote = instrumentId ? quotes[instrumentId] : undefined;

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
