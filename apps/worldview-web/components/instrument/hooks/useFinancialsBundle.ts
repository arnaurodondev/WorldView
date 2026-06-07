/**
 * useFinancialsBundle.ts
 *
 * WHY THIS HOOK EXISTS (PLAN-0099 follow-up E):
 *   The instrument Financials tab previously fired ~8 unique S9 round-trips
 *   on cold-start (fundamentals, snapshot, income-statement, earnings
 *   history, technicals, share statistics, splits/dividends, plus the
 *   per-panel beat-miss-history and fundamentals-timeseries fetches). Each
 *   is gated by S9 auth + internal-JWT issuance so the page was
 *   wave-serialized by the slowest leg.
 *
 *   This hook fires a SINGLE POST to /v1/fundamentals/{id}/financials-bundle
 *   that fans the legs out in parallel server-side via asyncio.gather and
 *   returns a composite object. The hook then HYDRATES each per-widget
 *   TanStack cache key via queryClient.setQueryData so the existing child
 *   components (`BeatMissHistoryPanel`, `IncomeStatementTable`,
 *   `FundamentalsTab`, etc.) hit warm cache instead of issuing their own
 *   initial fetches.
 *
 * MIRRORS: features/dashboard/hooks/useDashboardBundle.ts (F-2 pattern).
 *
 * WHAT THIS HOOK DOES NOT DO:
 *   - It does NOT remove or replace the per-widget endpoints. Each child
 *     component keeps its own useQuery so it can refetch independently
 *     (e.g. when the user clicks a refresh button or navigates back to
 *     the tab with stale-time elapsed).
 *   - It does NOT transform the bundle legs. The legs are forwarded into
 *     per-widget caches verbatim; the existing per-widget hooks already
 *     own their typing.
 */

"use client";
// WHY "use client": useQuery + useQueryClient are React hooks that only run
// in the browser. Any component that imports this hook must also be a
// Client Component.

import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { FinancialsBundleResponse } from "@/lib/api/instruments";
import type {
  Fundamentals,
  FundamentalsSnapshot,
  FundamentalsSectionResponse,
} from "@/types/api";

// staleTime = 10 minutes: the bundle aggregates legs whose individual
// stale-times range from 5m (technicals — not in this bundle) to 24h
// (income-statement). 10m is a conservative middle that keeps the bundle
// fresh during a typical session without hammering the gateway on every
// tab-switch. Per-widget hooks still own their own stale-time for refetch
// semantics; the bundle's stale-time only governs when THIS hook re-fires.
const BUNDLE_STALE_TIME_MS = 10 * 60 * 1000;

/**
 * useFinancialsBundle — fetches the composite bundle once for the page and
 * hydrates per-widget TanStack caches from the legs.
 *
 * Caller usage:
 *   const { isLoading } = useFinancialsBundle(instrumentId);
 *
 * The hook returns the underlying TanStack query result so callers can
 * gate their initial-paint skeleton on `isLoading`. Read the actual leg
 * data through the existing per-widget hooks (e.g. `useFinancialsTabData`)
 * — they'll read from the warm cache this hook just populated.
 */
export function useFinancialsBundle(instrumentId: string) {
  const token = useAccessToken();
  const queryClient = useQueryClient();
  const enabled = !!instrumentId && !!token;

  const query = useQuery<FinancialsBundleResponse>({
    // WHY a dedicated bundle cache key: the bundle is a distinct resource
    // from any of its individual legs, so it gets its own key. Hydration
    // happens in the useEffect below — the bundle cache itself just
    // tracks whether the composite fetch is in-flight / fresh.
    queryKey: ["instruments", "detail", instrumentId, "financials-bundle"],
    // WHY createGateway inside queryFn: the gateway factory binds the
    // current access token at call time. If the token refreshes between
    // renders, the next refetch automatically uses the fresh token.
    queryFn: () => createGateway(token).getFinancialsBundle(instrumentId),
    enabled,
    staleTime: BUNDLE_STALE_TIME_MS,
    // WHY refetchOnWindowFocus=false: the bundle is large; tab-switching
    // should not trigger a full re-fetch. Per-widget hooks own their own
    // focus-refetch behaviour for the cells users actually care about.
    refetchOnWindowFocus: false,
  });

  // ── Cache hydration ─────────────────────────────────────────────────────
  //
  // WHY useEffect (not inside queryFn): TanStack Query's cache lives in
  // queryClient state; mutating it from inside a queryFn breaks the
  // unidirectional flow. The effect runs after the bundle resolves and
  // pre-warms each per-widget key so the child useQuery calls in
  // `useFinancialsTabData`, `BeatMissHistoryPanel`, etc. read from the
  // cache instead of firing their own HTTP requests.
  //
  // WHY null-guard each leg before setQueryData: a failed leg degrades to
  // null at the gateway. Writing null into the cache would cause child
  // hooks to display "no data" instead of falling back to their own
  // self-fetch. If the bundle leg is null, we LEAVE the cache untouched
  // so the child hook performs its normal fetch.
  useEffect(() => {
    const bundle = query.data;
    if (!bundle || !instrumentId) return;

    if (bundle.fundamentals != null) {
      queryClient.setQueryData(
        qk.instruments.fundamentals(instrumentId),
        // WHY cast: the legs are typed as `unknown` in FinancialsBundleResponse
        // (the structural mirror — see lib/api/instruments.ts) because the
        // generated OpenAPI types have not yet been re-rolled. The per-widget
        // hooks already typed their data shapes, so the cast just re-asserts
        // what the gateway documents.
        bundle.fundamentals as Fundamentals,
      );
    }
    if (bundle.fundamentals_snapshot != null) {
      queryClient.setQueryData(
        qk.instruments.fundamentalsSnapshot(instrumentId),
        bundle.fundamentals_snapshot as FundamentalsSnapshot,
      );
    }
    if (bundle.income_statement != null) {
      queryClient.setQueryData(
        qk.instruments.incomeStatement(instrumentId),
        bundle.income_statement as FundamentalsSectionResponse,
      );
    }
    if (bundle.earnings_history != null) {
      queryClient.setQueryData(
        qk.instruments.earningsHistory(instrumentId),
        bundle.earnings_history as FundamentalsSectionResponse,
      );
      // WHY a SECOND setQueryData for the same payload: BeatMissHistoryPanel
      // uses a different cache key (`["earnings-history", id]`) — it shares
      // the underlying HTTP request via TanStack dedup only when both keys
      // are in-flight in the same render cycle. Hydrating both keys from
      // the bundle ensures the panel reads from cache on cold start too.
      queryClient.setQueryData(
        ["earnings-history", instrumentId],
        bundle.earnings_history as FundamentalsSectionResponse,
      );
    }
    if (bundle.share_statistics != null) {
      queryClient.setQueryData(
        qk.instruments.shareStatistics(instrumentId),
        bundle.share_statistics as FundamentalsSectionResponse,
      );
    }
    if (bundle.splits_dividends != null) {
      queryClient.setQueryData(
        qk.instruments.splitsDividends(instrumentId),
        bundle.splits_dividends as FundamentalsSectionResponse,
      );
    }
    // fundamentals_timeseries is intentionally NOT hydrated — the chart panel
    // owns a metric/period selector, so the bundle endpoint cannot prefetch
    // a specific (metric, period) pair. The panel keeps its self-fetch.
  }, [query.data, instrumentId, queryClient]);

  return query;
}
