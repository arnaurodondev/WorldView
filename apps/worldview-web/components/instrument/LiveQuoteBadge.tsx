/**
 * components/instrument/LiveQuoteBadge.tsx — Real-time price + change badge
 *
 * WHY THIS EXISTS: The instrument header needs a prominent live price display.
 * Bloomberg and Refinitiv show price in large type + absolute/% change colored
 * green/red. Traders scan the header for "where is it now" before reading tabs.
 *
 * WHY 15s REFETCH (changed from 5s in PLAN-0036 Wave 1):
 * S9 now sources quotes from the PriceSnapshot backend (S3 Valkey, 2h TTL).
 * Quotes themselves are fetched by S2 on a tiered cadence (T0=5min, T1=15min).
 * Polling S9 faster than the underlying data changes wastes credits and serves
 * identical responses. 15s matches the minimum cadence (T0 tier) with headroom.
 * Market hours only — outside hours the daily close is "live" so 15s is fine.
 *
 * WHY StaleBadge: When a quote is delayed or stale (EODHD quota exhausted,
 * circuit breaker open, or market closed), users need a visual cue. An amber
 * DELAYED badge or red STALE badge appears next to the price per PRD-0036 §6.8.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx
 * DATA SOURCE: S9 GET /v1/quotes/{instrumentId} (enriched with freshness fields)
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail header, canvas State B
 */

"use client";
// WHY "use client": uses useQuery with refetchInterval (live data).

import { useQuery } from "@tanstack/react-query";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
import { StaleBadge } from "@/components/ui/StaleBadge";

// ── Props ─────────────────────────────────────────────────────────────────────

interface LiveQuoteBadgeProps {
  instrumentId: string;
  /** Initial price from CompanyOverview (shows while quote is fetching) */
  initialPrice?: number | null;
  /**
   * When true, renders only a StaleBadge (freshness indicator) without the full
   * price block. Use in CompactInstrumentHeader where price is already displayed
   * inline — the badge then provides freshness context without duplicating price.
   *
   * WHY compact prop (not a separate component): both modes share the same polling
   * logic (useQuery with 15s refetchInterval) — extracting to two components would
   * duplicate the query and hit the API twice for the same instrument.
   */
  compact?: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

// WHY 15_000ms: S2 ingests T0 (portfolio holdings) quotes every 5 min, T1 every
// 15 min. Polling S9 faster than S2 fetch cadence serves stale cache hits.
// 15s matches T0 cadence and avoids burning EODHD credits via unnecessary polls.
const REFETCH_INTERVAL_MS = 15_000;

// ── Component ─────────────────────────────────────────────────────────────────

export function LiveQuoteBadge({ instrumentId, initialPrice, compact = false }: LiveQuoteBadgeProps) {
  const { accessToken } = useAuth();

  const { data: quote } = useQuery({
    queryKey: ["quote-live", instrumentId],
    queryFn: () => createGateway(accessToken).getQuote(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    refetchInterval: REFETCH_INTERVAL_MS,
    staleTime: 0,
    // WHY placeholderData: show initial price immediately while first quote loads.
    // Freshness fields intentionally absent — placeholder is local, not from S9.
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
    // ── Loading: compact mode shows nothing (price displayed by parent); full mode shows skeleton
    if (compact) return null;
    return (
      <div className="h-10 w-32 animate-pulse rounded-[2px] bg-muted" />
    );
  }

  // ── Compact mode: just the freshness badge (no price block) ───────────────
  // WHY: in CompactInstrumentHeader, price+change are already rendered inline from
  // props. The compact badge just signals data freshness alongside that static display.
  // StaleBadge renders nothing for "live"/"recent" — stays invisible on fresh data.
  if (compact) {
    return (
      <StaleBadge
        status={quote.freshness_status}
        staleReason={quote.stale_reason}
        dataAsOf={quote.data_as_of}
      />
    );
  }

  const isPositive = quote.change_pct > 0;
  const isNegative = quote.change_pct < 0;
  const TrendIcon = isPositive ? TrendingUp : isNegative ? TrendingDown : Minus;

  // WHY muted-foreground on stale: if data is unavailable, dim the price so
  // traders don't act on it. Matches Bloomberg's gray-out behavior.
  const priceColorClass =
    quote.freshness_status === "unavailable" ? "text-muted-foreground" : "text-foreground";

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline gap-3">
        {/* Current price — large and prominent */}
        <span className={`font-mono text-2xl font-semibold tabular-nums ${priceColorClass}`}>
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

        {/*
          StaleBadge: renders nothing for "live"/"recent", amber DELAYED for
          "delayed", red STALE for "stale", gray N/A for "unavailable".
          WHY here: the price row is the logical place for freshness context.
        */}
        <StaleBadge
          status={quote.freshness_status}
          staleReason={quote.stale_reason}
          dataAsOf={quote.data_as_of}
        />
      </div>

      {/* Timestamp row */}
      {/* WHY optional guard on quote.timestamp: S9 may return a quote without a
          timestamp if the price snapshot was created before the timestamp field was
          added, or if placeholderData is used without a valid ISO string. Calling
          new Date(undefined).toISOString() throws RangeError: Invalid time value
          which bubbles up through React and triggers the error boundary. */}
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {quote.timestamp ? new Date(quote.timestamp).toISOString().slice(11, 19) + " UTC" : "—"}
      </span>
    </div>
  );
}
