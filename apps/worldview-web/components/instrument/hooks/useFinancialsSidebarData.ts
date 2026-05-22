/**
 * components/instrument/hooks/useFinancialsSidebarData.ts — Financials sidebar data hook
 *
 * WHY THIS EXISTS: The Financials tab sidebar (7 panels, 240px) fetches 4
 * slow-changing data sets independently of the main tab data (income statement,
 * metrics grid). Splitting these into a dedicated hook keeps useFinancialsTabData
 * focused on the left-column fast-changing data and avoids a single large hook
 * that blocks the whole tab until all 4 slow resources resolve.
 *
 * WHY 24h staleTime for all 4 queries:
 *   - Insider transactions: SEC Form 4 filings come in batches; daily cadence ok.
 *   - Institutional holders: 13F filings are quarterly; 24h is extremely fresh.
 *   - Fund holders: same as institutional — quarterly filings.
 *   - Peers: sector/industry classification changes rarely; 24h is safe.
 *
 * WHO USES IT: FinancialsTab.tsx (sidebar data wiring), sidebar panel components.
 * DATA SOURCES:
 *   - Insider: S9 GET /v1/fundamentals/{id}/insider-transactions (reuses qk.instruments.ownership)
 *   - Institutional: S9 GET /v1/fundamentals/{id}/institutional-holders
 *   - Fund holders: S9 GET /v1/fundamentals/{id}/fund-holders
 *   - Peers: S9 GET /v1/instruments/{id}/peers?n=5
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §8 (query keys)
 */

"use client";
// WHY "use client": uses TanStack Query hooks which require the QueryClient
// context — only available in the browser React tree.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { FundamentalsSectionResponse, PeersResponse } from "@/types/api";

const STALE_24H = 24 * 60 * 60 * 1000;

export interface FinancialsSidebarData {
  // Insider transactions — array of recent Form 4 filings.
  // Section "insider_transactions_snapshot" per EODHD schema.
  insiderData: FundamentalsSectionResponse | undefined;
  insiderLoading: boolean;

  // Top institutional shareholders (fund name, % held, shares).
  institutionalData: FundamentalsSectionResponse | undefined;
  institutionalLoading: boolean;

  // Mutual fund / ETF holders.
  fundHoldersData: FundamentalsSectionResponse | undefined;
  fundHoldersLoading: boolean;

  // 5 nearest market-cap peers in the same GICS industry.
  peersData: PeersResponse | undefined;
  peersLoading: boolean;
}

/**
 * useFinancialsSidebarData — parallel data loader for the 7-panel Financials sidebar.
 *
 * @param instrumentId  S9 instrument UUID (same as entity_id post-F2 unification)
 */
export function useFinancialsSidebarData(instrumentId: string): FinancialsSidebarData {
  const token = useAccessToken();

  // WHY qk.instruments.ownership: the design doc §8 (DISCUSS-7 / Δ21) specifies
  // reusing the ownership key for insider transactions to avoid a second cache
  // entry for the same data. InsiderTransactionsTable reads from qk.instruments.ownership.
  const { data: insiderData, isLoading: insiderLoading } = useQuery({
    queryKey: qk.instruments.ownership(instrumentId),
    queryFn: () => createGateway(token).getInsiderTransactions(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId && !!token,
  });

  const { data: institutionalData, isLoading: institutionalLoading } = useQuery({
    queryKey: qk.instruments.institutionalHolders(instrumentId),
    queryFn: () => createGateway(token).getInstitutionalHolders(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId && !!token,
  });

  const { data: fundHoldersData, isLoading: fundHoldersLoading } = useQuery({
    queryKey: qk.instruments.fundHolders(instrumentId),
    queryFn: () => createGateway(token).getFundHolders(instrumentId),
    staleTime: STALE_24H,
    enabled: !!instrumentId && !!token,
  });

  // WHY limit=5: PeerComparisonTable shows 5 peers + self = 6 rows. Using the
  // same limit as W5 PeersStrip means the shared cache entry is reused (no
  // extra fetch when the user navigates between Quote and Financials tabs).
  const { data: peersData, isLoading: peersLoading } = useQuery({
    queryKey: qk.instruments.peers(instrumentId, 5),
    queryFn: () => createGateway(token).getPeers(instrumentId, 5),
    staleTime: STALE_24H,
    enabled: !!instrumentId && !!token,
  });

  return {
    insiderData,
    insiderLoading,
    institutionalData,
    institutionalLoading,
    fundHoldersData,
    fundHoldersLoading,
    peersData,
    peersLoading,
  };
}
