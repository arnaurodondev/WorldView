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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ChevronDown } from "lucide-react";

// PLAN-0053 T-A-1-09 — typed quote shape for the per-cell renderer.
// `stale_reason` accepts null because the gateway returns Quote with that
// nullability and we re-use the same object directly.
type IndexQuote = {
  price?: number;
  change_pct?: number | null;
  freshness_status?: string;
  stale_reason?: string | null;
};

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

  // PLAN-0053 T-A-1-09: extract ticker render into a cell component so we can
  // reuse it both inline (large viewports) and inside the Popover (narrow).
  // Typography: symbol bold-white (`font-bold text-foreground`), price+change
  // colored only by daily return — answers the user feedback that the previous
  // muted-symbol/colored-price ordering was inverted vs Bloomberg convention.
  const renderCell = (ticker: { id: string; label: string }) => {
    const instrumentId = tickerToId?.[ticker.id];
    const quote: IndexQuote | undefined = instrumentId ? quotes[instrumentId] : undefined;
    const isStale =
      !!quote?.freshness_status &&
      ["delayed", "stale", "unavailable"].includes(quote.freshness_status);
    const colorClass = !quote || isStale
      ? "text-muted-foreground"
      : priceChangeClass(quote.change_pct ?? null);
    return (
      <div key={ticker.id} className="flex items-center gap-1">
        <span className="text-xs font-bold text-foreground">{ticker.label}</span>
        <span
          className={`font-mono text-xs tabular-nums ${colorClass}`}
          title={isStale ? (quote?.stale_reason ?? "Delayed data") : undefined}
        >
          {quote ? formatPrice(quote.price) : "—"}
        </span>
        {quote && !isStale && (
          <span className={`font-mono text-xs tabular-nums ${priceChangeClass(quote.change_pct ?? null)}`}>
            {formatPercentDirect(quote.change_pct ?? null)}
          </span>
        )}
        {quote && isStale && (
          <span className="text-[10px] text-muted-foreground" title={quote.stale_reason ?? "Delayed"}>
            ·
          </span>
        )}
        {isError && <span className="text-xs text-muted-foreground">—</span>}
      </div>
    );
  };

  // Pinned ticker (SPY) is always visible inline; the rest collapse into a
  // Popover below `lg:` (1024px) so the strip never overflows the TopBar.
  const [pinned, ...overflow] = INDEX_TICKERS;

  return (
    <div className="flex items-center gap-2">
      {/* Always-visible pinned ticker (SPY). */}
      {renderCell(pinned)}

      {/* lg+ viewports: render the rest inline (current behavior). */}
      <div className="hidden lg:flex items-center gap-2">
        {overflow.map(renderCell)}
      </div>

      {/* <lg viewports: collapse the rest into a Popover trigger. */}
      <div className="lg:hidden">
        <Popover>
          <PopoverTrigger
            className="flex h-6 items-center gap-0.5 rounded-[2px] border border-border bg-card px-1.5 text-[10px] font-medium text-muted-foreground hover:bg-muted/50"
            aria-label={`Show ${overflow.length} more index tickers`}
          >
            <span>+{overflow.length}</span>
            <ChevronDown className="h-3 w-3" />
          </PopoverTrigger>
          <PopoverContent
            align="end"
            sideOffset={4}
            className="w-auto min-w-[180px] p-2"
          >
            <div className="flex flex-col gap-1.5">
              {overflow.map(renderCell)}
            </div>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  );
}
