/**
 * useFinancialsTabData.ts
 * WHY THIS EXISTS: Financials tab needs 6 S9 sub-resources with different
 *   staleTimes. Reusing the technicals + shareStats keys from useMetricsTableData
 *   auto-dedupes via TanStack Query — request fires once across Quote+Financials.
 * WHO USES IT: components/instrument/financials/FinancialsTab.tsx and its
 *   FlatMetricsGrid (no inline useQuery allowed in either).
 * DATA SOURCE: /v1/fundamentals/{id} {,/snapshot,/income-statement,
 *   /earnings-annual-trend,/technicals,/share-statistics}.
 * DESIGN REFERENCE: PRD-0088 §6.8, PLAN-0090 T-A-03.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
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
//   fundamentals 5m, snapshot 10m, income/earnings 24h (filing cadence),
//   technicals 5m + shareStats 60m (shared keys → dedupe with MetricsTable).
// isLoading only ORs the four NEW queries — technicals/shareStats refresh
// in place once their shared cache resolves.
export function useFinancialsTabData(instrumentId: string): FinancialsTabData {
  const token = useAccessToken();
  const enabled = !!instrumentId;
  const gw = () => createGateway(token);

  const fundamentalsQuery = useQuery({
    queryKey: qk.instruments.fundamentals(instrumentId),
    queryFn: () => gw().getFundamentals(instrumentId),
    staleTime: 5 * 60 * 1000,
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
    isLoading:
      fundamentalsQuery.isLoading ||
      snapshotQuery.isLoading ||
      incomeStatementQuery.isLoading ||
      earningsHistoryQuery.isLoading,
  };
}
