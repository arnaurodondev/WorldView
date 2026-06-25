/**
 * components/instrument/hooks/useFinancialsSidebarData.ts — sidebar data bundle (T-04)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 Δ20 splits the old single-hook approach into
 * two: `useFinancialsTabData` (grid + income + chart) and this hook (sidebar
 * tables — insider, institutional, fund holders, peers). The split keeps each
 * hook's concern clear and prevents the sidebar data from blocking the grid
 * render: if institutional holders is slow the DenseMetricsGrid still renders.
 *
 * WHY 4 separate useQuery calls (not one batch): the four resources are
 * independent and have different update cadences — insider transactions change
 * on filing (quarterly), institutional holders change on 13F filings (quarterly),
 * peers are derived from static market-cap rankings (rarely change), and
 * ownership (insider summary) is seeded by the page bundle. TanStack Query
 * de-duplicates requests to already-warm keys, so no extra network round-trips
 * occur when other components also fetch these keys.
 *
 * WHO USES IT: FinancialsTab.tsx orchestrator — passes slice data as props into
 *   InsiderTransactionsTable, InstitutionalHoldersTable, FundHoldersTable, and
 *   PeerComparisonTable (all receive server-fetched data rather than fetching
 *   independently, to avoid 4× duplicate requests).
 *
 * DATA SOURCE:
 *   - insider:        qk.instruments.ownership → seeded by InstrumentPageClient
 *   - institutional:  qk.instruments.institutionalHolders → S9 GET /v1/fundamentals/{id}/institutional-holders
 *   - fundHolders:    qk.instruments.fundHolders → S9 GET /v1/fundamentals/{id}/fund-holders
 *   - peers:          qk.instruments.peers → S9 GET /v1/instruments/{id}/peers
 */

"use client";
// WHY "use client": all four useQuery calls require the TanStack Query context
// which only exists in the browser. The hook cannot run on the server.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { FundamentalsSectionResponse } from "@/types/api";
import type { PeersResponse } from "@/lib/api/instruments";

// 24h staleTime: insider/institutional data changes at most quarterly (13F
// filing cadence). Re-fetching more frequently wastes bandwidth with no gain.
const STALE_24H = 24 * 60 * 60 * 1000;

export interface FinancialsSidebarData {
  // insider: the page-bundle already seeds qk.instruments.ownership(id).
  // Reading it here dedupes against the pre-warmed cache key rather than
  // firing a new request. The InsiderTransactionsTable receives this slice.
  insiderData: FundamentalsSectionResponse | undefined;
  // institutional: top 10 institutions by shares held (Vanguard, BlackRock, etc.)
  institutionalData: FundamentalsSectionResponse | undefined;
  // fundHolders: top 10 mutual/ETF fund holders
  fundHoldersData: FundamentalsSectionResponse | undefined;
  // peers: 5 instruments with same GICS industry, closest market-cap to self
  peersData: PeersResponse | undefined;
  // isLoading: true while ANY of the four legs is still fetching cold.
  // Sidebar components each handle their own loading state; this aggregate
  // flag is available for the orchestrator to render a placeholder wrapper.
  isLoading: boolean;
  // isError: true if any leg errored. Individual tables handle their own
  // error states, but the aggregate flag allows top-level error boundaries.
  isError: boolean;
}

export function useFinancialsSidebarData(instrumentId: string): FinancialsSidebarData {
  const token = useAccessToken();
  const gw = createGateway(token);

  // WHY ownership key for insider (not a separate insiderTxns key): per Δ21
  // the page-bundle already pre-warms `qk.instruments.ownership(id)` which
  // returns the insider_transactions_snapshot section. Reusing the same cache
  // key means this useQuery hits warm cache immediately — zero network cost.
  const { data: insiderData, isLoading: insiderLoading, isError: insiderError } = useQuery({
    queryKey: qk.instruments.ownership(instrumentId),
    queryFn: () => gw.getInsiderTransactions(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId,
  });

  const { data: institutionalData, isLoading: instLoading, isError: instError } = useQuery({
    queryKey: qk.instruments.institutionalHolders(instrumentId),
    queryFn: () => gw.getInstitutionalHolders(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId,
  });

  const { data: fundHoldersData, isLoading: fundLoading, isError: fundError } = useQuery({
    queryKey: qk.instruments.fundHolders(instrumentId),
    queryFn: () => gw.getFundHolders(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId,
  });

  const { data: peersData, isLoading: peersLoading, isError: peersError } = useQuery({
    queryKey: qk.instruments.peers(instrumentId),
    queryFn: () => gw.getPeers(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId,
  });

  return {
    insiderData,
    institutionalData,
    fundHoldersData,
    peersData,
    // WHY logical OR (not some([])): any leg loading = show placeholder;
    // partial data is fine but partial loading means the tab is not settled.
    isLoading: insiderLoading || instLoading || fundLoading || peersLoading,
    isError: insiderError || instError || fundError || peersError,
  };
}
