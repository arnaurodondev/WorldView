/**
 * hooks/useScreenerSparklines.ts — TanStack Query hook for batched OHLCV bars
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-09): The screener renders an inline 30-day
 * sparkline per row. Fetching one OHLCV endpoint per row would mean 50 HTTP
 * round-trips for a default page — way too slow. The batch endpoint
 * (POST /v1/quotes/bars/batch from PLAN-0049 T-A-1-05) returns all bars in one
 * request. This hook wraps that endpoint with caching, chunking and a
 * convenient {[instrumentId]: bars} map shape for the table renderer.
 *
 * WHY 50-id chunks:
 *   - The S9 batch endpoint is documented as "limit 100 per request" but we
 *     stay under by half to leave headroom for overhead and to avoid hitting
 *     S3's per-batch DB query timeout under load.
 *   - 50 also matches the default screener PAGE_SIZE so a single page is
 *     usually one request.
 *
 * WHY staleTime 300_000 (5 min) and NOT 30s:
 *   - Daily bars (timeframe=1d) update at most once per trading day.
 *     Refetching every 30s would burn S3 quota for zero new data.
 *   - 5 min is short enough that the freshly-closed bar appears within a
 *     reasonable session window; long enough that tab switches don't cause
 *     refetches mid-session.
 *
 * WHY a Record<string, OHLCVBar[]> return shape:
 *   - The table renderer needs O(1) lookup by instrument_id. Arrays would
 *     force a scan per row.
 *   - Empty arrays (rather than undefined) for missing IDs: lets the UI
 *     unconditionally pass `sparklines[id]` to MiniChart without optional-
 *     chaining noise. MiniChart already handles empty bars gracefully.
 *
 * WHO USES IT: components/screener/ScreenerTable.tsx (sparkline column)
 */

"use client";
// WHY "use client": TanStack Query hooks rely on React Context (QueryClient).
// They cannot run on the server during Next.js RSC pre-render.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import type { OHLCVBar } from "@/types/api";

// ── Public types ─────────────────────────────────────────────────────────────

export interface UseScreenerSparklinesOptions {
  /** Limit of bars per instrument. Default 30 (≈ one trading month). */
  limit?: number;
  /** Daily by default — daily bars update at most once per trading day. */
  timeframe?: "1d" | "1h" | "5m";
  /** Disable the query (e.g. while no auth token is loaded yet). */
  enabled?: boolean;
}

export interface UseScreenerSparklinesResult {
  /** Bars per instrument id. Missing ids return an empty array. */
  sparklines: Record<string, OHLCVBar[]>;
  isLoading: boolean;
  isError: boolean;
}

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * chunk — splits an array into sub-arrays of size `n`.
 *
 * WHY 50 not 100: see file-level "WHY 50-id chunks".
 */
function chunk<T>(arr: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += n) {
    out.push(arr.slice(i, i + n));
  }
  return out;
}

const CHUNK_SIZE = 50;

// ── Public hook ──────────────────────────────────────────────────────────────

/**
 * useScreenerSparklines — fetch 30d daily bars for many instruments at once.
 *
 * WHY a single TanStack Query (not many parallel useQueries):
 *   - One query key, one cache entry, one isLoading flag → trivial UX state.
 *   - The hook itself fans out the chunked HTTP calls inside queryFn — the
 *     React tree never sees the chunking.
 *
 * WHY queryKey includes the joined ids string:
 *   - Different visible row sets (after filter changes) need a different
 *     cache entry. Joining on "," makes the key stable and human-readable
 *     in the React Query devtools.
 *   - We sort the ids before joining so [A,B] and [B,A] hit the same cache
 *     entry (same data, different request order).
 */
export function useScreenerSparklines(
  instrumentIds: readonly string[],
  options: UseScreenerSparklinesOptions = {},
): UseScreenerSparklinesResult {
  const { accessToken } = useAuth();
  const { limit = 30, timeframe = "1d", enabled = true } = options;

  // WHY sort + dedupe: see queryKey rationale above. Dedupe also guards
  // against accidentally requesting the same id twice in one batch.
  const stableIds = [...new Set(instrumentIds)].sort();

  const query = useQuery({
    queryKey: ["screener-sparklines", timeframe, limit, stableIds.join(",")],
    enabled: enabled && !!accessToken && stableIds.length > 0,
    // WHY 5 min: see file-level "WHY staleTime 300_000".
    staleTime: 300_000,
    // WHY gcTime 30 min: keep the bars around even after the user navigates
    // away from the screener — switching tabs and coming back should hit
    // cache, not network.
    gcTime: 1_800_000,
    queryFn: async () => {
      const gw = createGateway(accessToken);
      // Fan out chunked batch requests in parallel. Promise.all preserves
      // the order, then we flatten into a single results list.
      const chunks = chunk(stableIds, CHUNK_SIZE);
      const responses = await Promise.all(
        chunks.map((idsChunk) =>
          gw.getBatchOhlcvBars({
            instrument_ids: idsChunk,
            timeframe,
            limit,
          }),
        ),
      );
      // Build the lookup map.
      const map: Record<string, OHLCVBar[]> = {};
      for (const resp of responses) {
        for (const r of resp.results) {
          map[r.instrument_id] = r.bars;
        }
      }
      // Ensure every requested id has at least an empty array — see file-level
      // "WHY a Record<...> return shape".
      for (const id of stableIds) {
        if (!map[id]) map[id] = [];
      }
      return map;
    },
  });

  return {
    sparklines: query.data ?? {},
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
