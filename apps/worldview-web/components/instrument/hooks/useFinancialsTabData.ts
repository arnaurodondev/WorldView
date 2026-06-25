/**
 * useFinancialsTabData.ts
 *
 * WHY THIS EXISTS: Financials tab needs the same 6 S9 sub-resources it always
 *   did (fundamentals, snapshot, income-statement, earnings history,
 *   technicals, share statistics), but PLAN-0099 follow-up E now FRONT-LOADS
 *   them via `useFinancialsBundle` — a single composite POST that pre-warms
 *   each per-widget TanStack cache key via `queryClient.setQueryData`.
 *
 *   This hook is now a thin façade: it fires `useFinancialsBundle` (single
 *   POST) and then reads each sub-resource via the SAME per-widget query
 *   keys it always used. The downstream useQuery calls now hit warm cache
 *   on cold start — no extra HTTP round-trips. They still own their
 *   per-widget staleTime so refetch semantics are unchanged.
 *
 * WHO USES IT: components/instrument/financials/FinancialsTab.tsx and its
 *   FlatMetricsGrid (no inline useQuery allowed in either).
 *
 * DATA SOURCE: /v1/fundamentals/{id}/financials-bundle (single RTT) →
 *   hydrates `/v1/fundamentals/{id}{,/snapshot,/income-statement,
 *   /earnings-annual-trend,/technicals,/share-statistics}` cache keys.
 *
 * DESIGN REFERENCE: PRD-0088 §6.8, PLAN-0090 T-A-03, PLAN-0099 follow-up E.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { DEFAULT_STALE } from "@/lib/api/_client";
import { qk } from "@/lib/query/keys";
import { useFinancialsBundle } from "./useFinancialsBundle";
import type {
  Fundamentals,
  FundamentalsSnapshot,
  FundamentalsSectionResponse,
} from "@/types/api";

export interface FinancialsTabData {
  fundamentals: Fundamentals | undefined;
  snapshot: FundamentalsSnapshot | undefined;
  incomeStatement: FundamentalsSectionResponse | undefined;
  earningsHistory: FundamentalsSectionResponse | undefined;
  technicals: FundamentalsSectionResponse | undefined;
  shareStats: FundamentalsSectionResponse | undefined;
  isLoading: boolean;
}

// staleTime rationale per query (annotated inline):
//   fundamentals DEFAULT_STALE.fundamentals (1hr — quarterly data, HIGH-018/FR-8.4),
//   snapshot 10m, income/earnings 24h (filing cadence),
//   technicals 5m + shareStats 60m (shared keys → dedupe with MetricsTable).
//
// The per-key useQuery calls below are now CACHE-FIRST on cold start: the
// `useFinancialsBundle` hook above hydrates each of these keys (except
// technicals — not in the bundle today) via `queryClient.setQueryData`, so
// the queryFn only fires when:
//   (a) the bundle leg degraded to null (failed downstream), OR
//   (b) the cache went stale and the user-triggered refetch happens.
//
// In other words, the queryFn fallbacks below are the resilience floor;
// the happy path serves all 6 fields from the bundle in one RTT.
export function useFinancialsTabData(instrumentId: string): FinancialsTabData {
  const token = useAccessToken();
  const enabled = !!instrumentId;
  const gw = () => createGateway(token);

  // PLAN-0099 follow-up E — fire the composite bundle. The hook itself
  // performs cache hydration via setQueryData; we only care about its
  // isLoading state so we can gate the initial-paint skeleton on the
  // bundle's first arrival.
  const bundleQuery = useFinancialsBundle(instrumentId);

  const fundamentalsQuery = useQuery({
    queryKey: qk.instruments.fundamentals(instrumentId),
    queryFn: () => gw().getFundamentals(instrumentId),
    staleTime: DEFAULT_STALE.fundamentals,
    enabled,
  });
  const snapshotQuery = useQuery({
    queryKey: qk.instruments.fundamentalsSnapshot(instrumentId),
    queryFn: () => gw().getFundamentalsSnapshot(instrumentId),
    staleTime: 10 * 60 * 1000,
    enabled,
  });
  // 24h: annual P&L only changes on new fiscal-year 10-K filings.
  const incomeStatementQuery = useQuery({
    queryKey: qk.instruments.incomeStatement(instrumentId),
    queryFn: () => gw().getIncomeStatement(instrumentId),
    staleTime: 24 * 60 * 60 * 1000,
    enabled,
  });
  // 24h: historical annual EPS is append-only — once per calendar day suffices.
  const earningsHistoryQuery = useQuery({
    queryKey: qk.instruments.earningsHistory(instrumentId),
    queryFn: () => gw().getEarningsHistory(instrumentId),
    staleTime: 24 * 60 * 60 * 1000,
    enabled,
  });
  // Shared with MetricsTable — TanStack dedupes by queryKey.
  // NOTE: technicals is NOT in the bundle today. It is shared with the
  // Quote tab's MetricsTable, which fires the request first on most user
  // flows; TanStack dedupe still saves the round-trip in that case.
  const technicalsQuery = useQuery({
    queryKey: qk.instruments.technicals(instrumentId),
    queryFn: () => gw().getTechnicals(instrumentId),
    staleTime: 5 * 60 * 1000,
    enabled,
  });
  const shareStatsQuery = useQuery({
    queryKey: qk.instruments.shareStatistics(instrumentId),
    queryFn: () => gw().getShareStatistics(instrumentId),
    staleTime: 60 * 60 * 1000,
    enabled,
  });

  return {
    fundamentals: fundamentalsQuery.data,
    snapshot: snapshotQuery.data,
    incomeStatement: incomeStatementQuery.data,
    earningsHistory: earningsHistoryQuery.data,
    technicals: technicalsQuery.data,
    shareStats: shareStatsQuery.data,
    // WHY include bundleQuery.isLoading: on cold start, the per-key
    // useQuery calls are immediately not-loading (they read from the
    // cache the bundle is about to populate). Gating on the bundle's
    // initial fetch prevents a flash of "—" placeholders before
    // hydration completes.
    isLoading:
      bundleQuery.isLoading ||
      fundamentalsQuery.isLoading ||
      snapshotQuery.isLoading ||
      incomeStatementQuery.isLoading ||
      earningsHistoryQuery.isLoading,
  };
}
