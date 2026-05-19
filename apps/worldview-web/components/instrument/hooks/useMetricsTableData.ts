/**
 * useMetricsTableData.ts
 * WHY THIS EXISTS: MetricsTable (Quote tab) needs three independent S9
 *   sub-resources (snapshot, technicals, share statistics) with DIFFERENT
 *   freshness profiles. We expose them as one object with unified
 *   loading/error flags so MetricsTable stays declarative.
 * WHO USES IT: components/instrument/quote/metrics/MetricsTable.tsx (sole
 *   consumer — no inline useQuery allowed inside MetricsTable).
 * DATA SOURCE:
 *   snapshot    → /v1/fundamentals/{id}/snapshot
 *   technicals  → /v1/fundamentals/{id}/technicals
 *   shareStats  → /v1/fundamentals/{id}/share-statistics
 * DESIGN REFERENCE: PRD-0088 §6.7, PLAN-0090 T-A-03.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { FundamentalsSnapshot, FundamentalsSectionResponse } from "@/types/api";

export interface MetricsTableData {
  snapshot: FundamentalsSnapshot | undefined;
  technicals: FundamentalsSectionResponse | undefined;
  shareStats: FundamentalsSectionResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}

// WHY THREE separate useQuery (not Promise.all): each resource has its own
//   staleTime (snapshot 10m / technicals 5m / shareStats 60m) AND dedupes
//   across the Financials tab which reuses technicals + shareStats keys.
// WHY isLoading/isError = OR: the table cannot render meaningful rows
//   until all three resolve (every row mixes fields from multiple sources).
export function useMetricsTableData(instrumentId: string): MetricsTableData {
  const token = useAccessToken();
  const enabled = !!instrumentId;

  // 10min: snapshot is backfilled, not intraday.
  const snapshotQuery = useQuery({
    queryKey: qk.instruments.fundamentalsSnapshot(instrumentId),
    queryFn: () => createGateway(token).getFundamentalsSnapshot(instrumentId),
    staleTime: 10 * 60 * 1000,
    enabled,
  });

  // 5min: technicals shift with each new bar; sub-minute polling unnecessary.
  const technicalsQuery = useQuery({
    queryKey: qk.instruments.technicals(instrumentId),
    queryFn: () => createGateway(token).getTechnicals(instrumentId),
    staleTime: 5 * 60 * 1000,
    enabled,
  });

  // 60min: shares outstanding/float/%insiders/%inst effectively only change
  // on filings (10-K, 13F) — hourly is more than enough.
  const shareStatsQuery = useQuery({
    queryKey: qk.instruments.shareStatistics(instrumentId),
    queryFn: () => createGateway(token).getShareStatistics(instrumentId),
    staleTime: 60 * 60 * 1000,
    enabled,
  });

  return {
    snapshot: snapshotQuery.data,
    technicals: technicalsQuery.data,
    shareStats: shareStatsQuery.data,
    isLoading:
      snapshotQuery.isLoading || technicalsQuery.isLoading || shareStatsQuery.isLoading,
    isError: snapshotQuery.isError || technicalsQuery.isError || shareStatsQuery.isError,
  };
}
