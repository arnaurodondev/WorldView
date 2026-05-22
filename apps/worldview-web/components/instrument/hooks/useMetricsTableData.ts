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
import { DEFAULT_STALE } from "@/lib/api/_client";
import { qk } from "@/lib/query/keys";
import type { Fundamentals, FundamentalsSnapshot, FundamentalsSectionResponse } from "@/types/api";

export interface MetricsTableData {
  // WHY add `fundamentals` (PLAN-0090 follow-up audit 2026-05-20): the page-bundle
  // `overview.fundamentals` payload only carries 5 fields (market_cap, pe_ratio,
  // week_52_high/low, daily_return). 16 MetricsTable rows depend on the FULL
  // /v1/fundamentals/{id} transformer output (gross_margin, roe, debt/equity,
  // analyst counts, payout_ratio, …). Reading from the slim bundle prop made
  // every one of those rows render "—" against AAPL even though the data is
  // present in postgres. Joining the rich endpoint here makes MetricsTable
  // declarative — it consumes `fundamentals` from the hook instead of relying
  // on QuoteTab to thread the right shape down.
  fundamentals: Fundamentals | undefined;
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
  // WHY !!token: same auth-race guard as useInstrumentBrief (see that hook for rationale).
  const enabled = !!instrumentId && !!token;

  // DEFAULT_STALE.fundamentals (1hr): full Fundamentals (highlights + valuation_ratios +
  // analyst_consensus + technicals_snapshot merged into the flat Fundamentals shape).
  // Quarterly cadence — HIGH-018 / FR-8.4. Shares the same queryKey as
  // useFinancialsTabData so the Financials tab and the Quote-tab MetricsTable both
  // warm the same cache entry — switching tabs is free after the first fetch.
  const fundamentalsQuery = useQuery({
    queryKey: qk.instruments.fundamentals(instrumentId),
    queryFn: () => createGateway(token).getFundamentals(instrumentId),
    staleTime: DEFAULT_STALE.fundamentals,
    enabled,
  });

  // 10min: snapshot is backfilled, not intraday. Carries derived fields
  // (eps_ttm, beta, free_cash_flow, …) that the rich /v1/fundamentals/{id}
  // endpoint does NOT compute — kept separate so the row count stays honest.
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
    fundamentals: fundamentalsQuery.data,
    snapshot: snapshotQuery.data,
    technicals: technicalsQuery.data,
    shareStats: shareStatsQuery.data,
    isLoading:
      fundamentalsQuery.isLoading ||
      snapshotQuery.isLoading ||
      technicalsQuery.isLoading ||
      shareStatsQuery.isLoading,
    isError:
      fundamentalsQuery.isError ||
      snapshotQuery.isError ||
      technicalsQuery.isError ||
      shareStatsQuery.isError,
  };
}
