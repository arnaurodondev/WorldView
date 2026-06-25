/**
 * features/portfolio/hooks/useHoldingsSeries.ts — 14-day close-price sparkline data
 *
 * WHY THIS EXISTS: SemanticHoldingsTable has a SPARK column that renders a
 * 14-day close-price mini-chart per row (PLAN-0108 W3). A naïve per-row fetch
 * (one GET /v1/ohlcv/<id> per holding) would cause N sequential HTTP round-trips
 * — 20 holdings = 20 requests, all competing for S3 market-data bandwidth at
 * render time. The batch sparkline endpoint (PLAN-0108 W2) accepts a
 * comma-separated list and returns a Record<instrument_id, number[]> in one
 * round-trip, making it the correct primitive for a table column.
 *
 * WHY staleTime 15min (not 30s like live quotes):
 *   Sparkline close prices are end-of-day bars — they change at most once per
 *   trading session. A 15-minute stale window means re-mounts and tab-switches
 *   hit the TanStack cache instead of the network while staying fresh enough
 *   that intra-day users see the latest session close within a reasonable lag.
 *   Contrast with holdingsQuotes (staleTime=0, refetchInterval=15s) which uses
 *   real-time bid/ask — that endpoint would be expensive to poll for sparklines.
 *
 * WHY gcTime 30min:
 *   Matches useScreenerSparklines (the reference implementation for batch
 *   sparkline patterns in this codebase). Keeps bars alive for one typical
 *   browsing session so the user can switch portfolio tabs and come back without
 *   a re-fetch.
 *
 * WHY retry: 1 (not the default 3):
 *   Sparklines are decorative — if the endpoint is down, the table still renders
 *   fully functional without the SPARK column (SparklineCellRenderer shows "—").
 *   Over-retrying wastes quota and increases perceived latency for what is a
 *   non-blocking enhancement.
 *
 * GRACEFUL DEGRADATION: On error or any missing instrument_id key, the returned
 * `series` is `{}` (error) or a partial Record (partial miss). SparklineCellRenderer
 * MUST handle `series[id] === undefined` by rendering "—", not by throwing.
 *
 * DATA SOURCE: GET /v1/market/sparklines?instrument_ids=<comma-list>&days=14
 *   Deployed by PLAN-0108 W2. Routed through S9 API Gateway at /api/v1/market/sparklines.
 *   Response shape: { data: Record<string, number[]> }
 *   Each value is an array of 14 close prices, oldest-first.
 *
 * WHO USES IT: SemanticHoldingsTable (PLAN-0108 W3 SPARK column cell renderer).
 */

"use client";
// WHY "use client": TanStack Query hooks depend on QueryClientProvider React
// Context. They cannot run in Next.js server components during RSC pre-render.

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/_client";
import { useAuth } from "@/hooks/useAuth";

// ── Public types ─────────────────────────────────────────────────────────────

export interface UseHoldingsSeriesResult {
  /**
   * Close-price arrays keyed by instrument_id.
   *
   * WHY Record (not array): O(1) lookup at render time — the table renderer
   * can do `series[holding.instrument_id]` without scanning. Matches the
   * pattern established by useScreenerSparklines in this codebase.
   */
  series: Record<string, number[]>;
  /** True while the first fetch is in-flight (no cached data yet). */
  isLoading: boolean;
  /** True if the fetch failed after all retries. series will be {}. */
  isError: boolean;
}

// ── S9 response envelope ─────────────────────────────────────────────────────

/**
 * SparklinesBatchResponse — structural mirror of the PLAN-0108 W2 S9 response.
 *
 * WHY defined here (not in @/types/api): the generated OpenAPI types have not
 * been re-rolled since this endpoint landed; defining the shape locally unblocks
 * callers immediately. A future types-sync can replace this with the canonical
 * generated type and delete this interface.
 */
interface SparklinesBatchResponse {
  data: Record<string, number[]>;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

/**
 * useHoldingsSeries — fetches 14-day sparkline series for all holdings.
 *
 * @param instrumentIds  Array of instrument UUIDs (from holdings.instrument_id).
 *                       Empty array disables the query — no request is made.
 * @param enabled        External gate (default true). Pass false when the parent
 *                       component is hidden or the holdings data isn't ready.
 *                       Combined with the instrumentIds.length guard internally
 *                       so callers don't need to compose both conditions.
 */
export function useHoldingsSeries(
  instrumentIds: string[],
  enabled = true,
): UseHoldingsSeriesResult {
  const { accessToken } = useAuth();

  // WHY sort before joining: instrument IDs arrive in whatever order the
  // holdings API returned them. [A,B] and [B,A] are the same logical request
  // — sorting gives a stable query key so both orderings share one cache entry.
  // Without this, a re-sort of the holdings table would trigger a redundant
  // re-fetch even though the underlying data is identical.
  const sortedIds = [...instrumentIds].sort();
  const idsParam = sortedIds.join(",");

  const query = useQuery<Record<string, number[]>>({
    // WHY "holdings-series" prefix (not reusing "screener-sparklines"):
    //   These are different logical caches with different stale windows and
    //   different consumers. Sharing a key would mean the 15-min sparkline TTL
    //   contaminates the 5-min screener TTL (or vice versa) if both hooks run
    //   simultaneously. Separate prefixes keep the caches independent.
    queryKey: ["holdings-series", idsParam],

    // WHY the combined enabled guard:
    //   - `enabled`: external caller can gate on holdings being loaded
    //   - `instrumentIds.length > 0`: firing with an empty list would send
    //     `?instrument_ids=&days=14` — a malformed request that returns a 422
    //   - `!!accessToken`: apiFetch injects the Bearer header; without a token
    //     the gateway returns 401, wasting a retry budget
    enabled: enabled && instrumentIds.length > 0 && !!accessToken,

    // WHY 15min: see file-level "WHY staleTime 15min".
    staleTime: 15 * 60 * 1000,

    // WHY 30min: see file-level "WHY gcTime 30min".
    gcTime: 30 * 60 * 1000,

    // WHY retry: 1: see file-level "WHY retry: 1".
    retry: 1,

    queryFn: async () => {
      // WHY apiFetch (not createGateway): this endpoint was deployed by
      // PLAN-0108 W2 and is not yet registered as a named method on the
      // gateway client. Using apiFetch directly avoids modifying gateway.ts
      // (a shared file with ~91 import sites) for a task-scoped addition.
      // A follow-up gateway registration can replace this without changing
      // the hook contract.
      //
      // WHY token passed explicitly: apiFetch injects `Authorization: Bearer
      // <token>` from the options.token field. The accessToken from useAuth()
      // is bound at query execution time (inside queryFn) — not at hook
      // construction time — so it always reflects the latest refresh.
      const response = await apiFetch<SparklinesBatchResponse>(
        `/v1/market/sparklines?instrument_ids=${encodeURIComponent(idsParam)}&days=14`,
        { token: accessToken ?? undefined },
      );

      // WHY response.data (not the whole response): the S9 envelope wraps the
      // Record<instrument_id, number[]> in a `data` key, matching the pattern
      // used by other batch endpoints (e.g. getBatchQuotes → response.quotes).
      return response.data ?? {};
    },
  });

  return {
    // WHY ?? {}: query.data is undefined while the query is loading or
    // disabled. Returning {} (not undefined) means callers can unconditionally
    // do `series[id]` without optional-chaining; missing keys naturally return
    // undefined which SparklineCellRenderer renders as "—".
    series: query.data ?? {},
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
