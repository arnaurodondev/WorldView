/**
 * useQuoteSidebarData.ts — Parallel data fetcher for the Quote-tab right-rail + strips.
 *
 * WHY THIS EXISTS (W5-T-05):
 * The Quote tab right rail needs 7 sub-resources that can all fire in parallel:
 *   - peers            GET /v1/instruments/{id}/peers
 *   - intradayStats    GET /v1/fundamentals/{id}/intraday-stats
 *   - multiPeriodReturns GET /v1/fundamentals/{id}/multi-period-returns
 *   - priceLevels      GET /v1/fundamentals/{id}/price-levels
 *   - ownership        GET /v1/fundamentals/{id}/share-statistics  (reuses Financials key)
 *   - earningsHistory  GET /v1/fundamentals/{id}/earnings-annual-trend (reuses Financials key)
 *   - entityNews       From the page-bundle seed (no extra fetch unless stale)
 *
 * WHY a dedicated hook (not inlined in QuoteTab):
 * Collocating all 7 query declarations keeps staleTime rationale and queryKey
 * references in one place. QuoteTab becomes a pure layout component that passes
 * the merged result object to children.
 *
 * WHY TanStack Query deduplication works here:
 * ownership and earningsHistory share the same queryKeys as useFinancialsTabData.
 * TanStack Query returns the cached entry — no duplicate network calls.
 *
 * WHO USES IT: QuoteTab.tsx (T-06 / T-25 wiring pass). No child components
 * should call useQuery directly for these resources.
 *
 * STALE-TIME RATIONALE:
 *   - peers: 24h (market cap movements are slow, S3 Valkey cache gates this anyway)
 *   - intradayStats: 60s during market hours (Δ28) — the hook passes lastBarTs
 *     from the OHLCV response so a new 5m bar invalidates without touching peers/levels.
 *     After-hours staleTime is not automatically switched here; callers that know the
 *     session state can manually invalidate via qk.instruments.intradayStats(id, ts).
 *   - multiPeriodReturns: 60 min — daily close changes once per session.
 *   - priceLevels: 60 min — floor pivot recomputes from prior-day OHLCV.
 *   - ownership / earningsHistory: 60 min / 24h (shared with Financials tab).
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type {
  PeersResponse,
  IntradayStatsResponse,
  MultiPeriodReturnsResponse,
  PriceLevelsResponse,
  FundamentalsSectionResponse,
} from "@/types/api";

// ── Return type ───────────────────────────────────────────────────────────────

export interface QuoteSidebarData {
  peers: PeersResponse | undefined;
  intradayStats: IntradayStatsResponse | undefined;
  multiPeriodReturns: MultiPeriodReturnsResponse | undefined;
  priceLevels: PriceLevelsResponse | undefined;
  /** share-statistics section (percent_insiders, shares_float, etc.) */
  ownership: FundamentalsSectionResponse | undefined;
  /** Earnings annual trend (last 4 annual EPS records) */
  earningsHistory: FundamentalsSectionResponse | undefined;
  /** True when any of the 4 W5 queries is still in-flight (not dedup'd shared ones). */
  isLoading: boolean;
  /** Per-resource error flags for graceful degradation. */
  errors: {
    peers: boolean;
    intradayStats: boolean;
    multiPeriodReturns: boolean;
    priceLevels: boolean;
  };
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * useQuoteSidebarData — fires 6 TanStack Query calls in parallel for the Quote tab.
 *
 * @param instrumentId   Canonical instrument_id (UUID or ticker). Gates all queries.
 * @param lastBarTs      Optional last OHLCV bar timestamp. Including it in the
 *                       intradayStats query key means a new 5m bar invalidates the
 *                       stats without evicting peers / levels (Δ28).
 */
export function useQuoteSidebarData(
  instrumentId: string,
  lastBarTs?: string,
): QuoteSidebarData {
  const token = useAccessToken();
  const enabled = !!instrumentId;
  // WHY factory: createGateway(token) is cheap (no network call); creating it
  // once per render avoids constructing N identical objects for N useQuery calls.
  const gw = () => createGateway(token);

  // ── 1. Peers ──────────────────────────────────────────────────────────────
  const peersQuery = useQuery({
    queryKey: qk.instruments.peers(instrumentId),
    queryFn: () => gw().getPeers(instrumentId, 5),
    staleTime: 24 * 60 * 60 * 1000, // 24h — matches S3 Valkey cache TTL
    enabled,
  });

  // ── 2. Intraday stats ─────────────────────────────────────────────────────
  // WHY lastBarTs in queryKey: if the OHLCV chart receives a new bar (real-time
  // update), the parent passes the new timestamp, invalidating only this query
  // without touching peers / levels / returns (per Δ28 contract).
  const intradayStatsQuery = useQuery({
    queryKey: qk.instruments.intradayStats(instrumentId, lastBarTs),
    queryFn: () => gw().getIntradayStats(instrumentId),
    staleTime: 60 * 1000, // 60s — VWAP/RSI update on each new 5m bar
    enabled,
  });

  // ── 3. Multi-period returns ───────────────────────────────────────────────
  const multiPeriodReturnsQuery = useQuery({
    queryKey: qk.instruments.multiPeriodReturns(instrumentId),
    queryFn: () => gw().getMultiPeriodReturns(instrumentId),
    staleTime: 60 * 60 * 1000, // 60 min — daily close updates once per session
    enabled,
  });

  // ── 4. Price levels ───────────────────────────────────────────────────────
  const priceLevelsQuery = useQuery({
    queryKey: qk.instruments.priceLevels(instrumentId),
    queryFn: () => gw().getPriceLevels(instrumentId),
    staleTime: 60 * 60 * 1000, // 60 min — pivots recompute from prior-day OHLCV
    enabled,
  });

  // ── 5. Ownership (share statistics) ──────────────────────────────────────
  // WHY same queryKey as useFinancialsTabData.shareStats: TanStack Query
  // returns the cached entry without a duplicate network call. The two hooks
  // coexist on the same page (Financials tab background fetch + Quote tab
  // foreground use) and the cache deduplication saves one round-trip.
  const ownershipQuery = useQuery({
    queryKey: qk.instruments.shareStatistics(instrumentId),
    queryFn: () => gw().getShareStatistics(instrumentId),
    staleTime: 60 * 60 * 1000,
    enabled,
  });

  // ── 6. Earnings history ───────────────────────────────────────────────────
  // WHY same queryKey as useFinancialsTabData.earningsHistory: same dedup rationale.
  const earningsHistoryQuery = useQuery({
    queryKey: qk.instruments.earningsHistory(instrumentId),
    queryFn: () => gw().getEarningsHistory(instrumentId),
    staleTime: 24 * 60 * 60 * 1000, // 24h — annual records are filing-cadence
    enabled,
  });

  return {
    peers: peersQuery.data,
    intradayStats: intradayStatsQuery.data,
    multiPeriodReturns: multiPeriodReturnsQuery.data,
    priceLevels: priceLevelsQuery.data,
    ownership: ownershipQuery.data,
    earningsHistory: earningsHistoryQuery.data,
    // WHY only W5 queries in isLoading: the shared ownership + earningsHistory
    // keys may already be resolved (Financials tab background fetch) — including
    // them would suppress the loading state when the tab is first opened.
    isLoading:
      peersQuery.isLoading ||
      intradayStatsQuery.isLoading ||
      multiPeriodReturnsQuery.isLoading ||
      priceLevelsQuery.isLoading,
    errors: {
      peers: peersQuery.isError,
      intradayStats: intradayStatsQuery.isError,
      multiPeriodReturns: multiPeriodReturnsQuery.isError,
      priceLevels: priceLevelsQuery.isError,
    },
  };
}
