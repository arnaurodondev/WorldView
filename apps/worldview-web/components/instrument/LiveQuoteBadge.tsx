/**
 * components/instrument/LiveQuoteBadge.tsx — Real-time price + change badge
 *
 * WHY THIS EXISTS: The instrument header needs a prominent live price display.
 * Bloomberg and Refinitiv show price in large type + absolute/% change colored
 * green/red. Traders scan the header for "where is it now" before reading tabs.
 *
 * WHY 5s REFETCH: Individual quotes are cached at S9 (Valkey 5s TTL). Fetching
 * every 5s gives traders near-real-time data without excessive S9 load.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx
 * DATA SOURCE: S9 GET /v1/quotes/{instrumentId}
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail header, canvas State B
 */

"use client";
// WHY "use client": uses useQuery with 5s refetchInterval (live data), useState for blink effect.

import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface LiveQuoteBadgeProps {
  instrumentId: string;
  /** Initial price from CompanyOverview (shows while quote is fetching) */
  initialPrice?: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function LiveQuoteBadge({ instrumentId, initialPrice }: LiveQuoteBadgeProps) {
  const { accessToken } = useAuth();

  const { data: quote } = useQuery({
    queryKey: ["quote-live", instrumentId],
    queryFn: () => createGateway(accessToken).getQuote(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    // WHY 5s: S9 has 5s Valkey cache on quotes — polling faster is wasteful
    refetchInterval: 5_000,
    staleTime: 0,
    // WHY placeholderData: show initial price immediately while first quote loads
    placeholderData: initialPrice != null
      ? {
          instrument_id: instrumentId,
          ticker: "",
          price: initialPrice,
          change: 0,
          change_pct: 0,
          timestamp: new Date().toISOString(),
          volume: null,
        }
      : undefined,
  });

  if (!quote) {
    return (
      <div className="h-10 w-32 animate-pulse rounded bg-muted" />
    );
  }

  const isPositive = quote.change_pct > 0;
  const isNegative = quote.change_pct < 0;
  const TrendIcon = isPositive ? TrendingUp : isNegative ? TrendingDown : Minus;

  return (
    <div className="flex items-baseline gap-3">
      {/* Current price — large and prominent */}
      <span className="font-mono text-2xl font-semibold tabular-nums text-foreground">
        {formatPrice(quote.price)}
      </span>

      {/* Change amount + percentage */}
      <div className={`flex items-center gap-1 ${priceChangeClass(quote.change_pct)}`}>
        <TrendIcon className="h-3.5 w-3.5" />
        <span className="font-mono text-sm tabular-nums">
          {quote.change >= 0 ? "+" : ""}{formatPrice(Math.abs(quote.change))}
        </span>
        <span className="font-mono text-sm tabular-nums">
          ({formatPercent(quote.change_pct / 100)})
        </span>
      </div>

      {/* Timestamp */}
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {new Date(quote.timestamp).toISOString().slice(11, 19)} UTC
      </span>
    </div>
  );
}
