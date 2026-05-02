/**
 * features/portfolio/hooks/usePortfolioData.ts — Portfolio page data orchestrator
 *
 * WHY THIS HOOK EXISTS (PLAN-0059 E-2 follow-up):
 * `app/(app)/portfolio/page.tsx` carried 8 inline `useQuery` calls + 6 derived
 * `useMemo` blocks plus the FIFO `useRealizedPnL` hook. That bloated the page
 * to 1,175 LOC and made the queryKey / refetchInterval / staleTime invariants
 * very hard to audit (any one of them being wrong silently breaks live-price
 * staleness or wastes API quota). Lifting the orchestration into a single
 * hook:
 *
 *   1. Pins all queryKey / staleTime / refetchInterval invariants in one
 *      file (this one). Future migrations to `qk.portfolios.*` keys touch a
 *      single place instead of 8 call sites.
 *   2. Frees the page to be a thin layout/event-wiring shell: render the
 *      header, the KPI strip, the three tab bodies — nothing else.
 *   3. Makes downstream tab components stateless props-driven views, which
 *      are far easier to unit-test than a tab nested inside a Tabs root
 *      whose data comes from 8 hooks.
 *
 * BEHAVIOR PARITY GUARANTEE: every observable behavior (queryKey shape,
 * staleTime, refetchInterval, the two cross-mutation invalidations,
 * sortedPortfolios ROOT-first ordering, scopeHint sub-line, KPI / sector
 * / type allocation maths) is preserved verbatim from the prior inline
 * implementation. The 31 unit tests in `lib/__tests__/kpi.test.ts` remain
 * the regression suite for the maths.
 *
 * SCOPE: imported only by the portfolio page. Not a public hook for other
 * pages — the dashboard `PortfolioSummary` widget has its own (slimmer)
 * hook because it doesn't need transactions / watchlists / brokerage state.
 */

"use client";
// WHY "use client": this hook drives mutable React state, useQuery (browser-
// only TanStack Query), and useCallback closures over setState. None of that
// runs in a server component.

import { useState, useMemo, useCallback } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import {
  useRealizedPnL,
  defaultRealizedPnLRange,
} from "@/hooks/useRealizedPnL";
import type {
  Portfolio,
  Holding,
  Watchlist,
  HoldingsResponse,
  TransactionsResponse,
  BatchQuoteResponse,
} from "@/types/api";

import {
  computePortfolioKPI,
  computeAllocations,
  computeScopeHint,
  type PortfolioKPI,
  type PortfolioAllocations,
  type HoldingOverviewMap,
} from "@/features/portfolio/lib/kpi";

// ── Public hook contract ──────────────────────────────────────────────────────

/**
 * Inputs the page wires into the hook. We keep the hook period-aware because
 * `getPortfolioPerformance` is the only query that depends on a period
 * value; KPI strip is hard-locked to "1D" (T-B-2-07) but this lets a future
 * variant add period chips back without rewriting the hook contract.
 */
export interface UsePortfolioDataArgs {
  /** Bearer token from `useAuth`. When null, all queries auto-disable. */
  accessToken: string | null;
  /** Period for the inline performance strip. Default "1D". */
  selectedPeriod?: "1D" | "1W" | "1M";
}

/**
 * Result returned to the page. Grouped logically so the page can
 * destructure exactly the slice each subcomponent needs.
 */
export interface UsePortfolioDataResult {
  // ── Portfolio selection ────────────────────────────────────────────────
  portfolios: Portfolio[] | undefined;
  sortedPortfolios: Portfolio[] | undefined;
  selectedPortfolioId: string | null;
  setSelectedPortfolioId: (id: string | null) => void;
  activePortfolioId: string | null;
  activePortfolio: Portfolio | undefined;
  /** True when the active portfolio is the kind=root aggregate view. */
  activeIsRoot: boolean;

  // ── Loading + error flags ─────────────────────────────────────────────
  portfoliosLoading: boolean;
  portfoliosError: boolean;
  holdingsLoading: boolean;
  txLoading: boolean;
  watchlistsLoading: boolean;

  // ── Holdings + enrichment ─────────────────────────────────────────────
  holdingsResp: HoldingsResponse | undefined;
  holdings: Holding[];
  /** Holdings merged with company-overview ticker/name/entity_id fallbacks. */
  enrichedHoldings: Holding[];
  holdingInstrumentIds: string[];
  holdingsQuotes: BatchQuoteResponse["quotes"];
  holdingOverviews: HoldingOverviewMap | undefined;

  // ── Transactions ──────────────────────────────────────────────────────
  transactionsResp: TransactionsResponse | undefined;

  // ── Watchlists ─────────────────────────────────────────────────────────
  watchlists: Watchlist[] | undefined;
  watchlistQuotes: BatchQuoteResponse["quotes"];

  // ── Performance ────────────────────────────────────────────────────────
  performanceData:
    | {
        portfolio_id: string;
        period: string;
        return_pct: number;
        return_abs: number;
        covered_pct: number;
      }
    | undefined;
  performanceLoading: boolean;

  // ── Realized P&L (FIFO) ───────────────────────────────────────────────
  realizedPnLQuery: ReturnType<typeof useRealizedPnL>;

  // ── Derived KPI / allocations / scope hint ────────────────────────────
  kpi: PortfolioKPI;
  bySector: PortfolioAllocations["bySector"];
  byType: PortfolioAllocations["byType"];
  scopeHint: string | null;

  // ── Mutations + invalidation callbacks ────────────────────────────────
  /** Run after CreatePortfolioDialog succeeds: invalidate list + select new. */
  handlePortfolioCreated: (newPortfolio: Portfolio) => void;
  /** Run after AddPositionDialog succeeds: invalidate holdings + transactions. */
  handlePositionAdded: () => void;
  /** Mutation handle for archiving a portfolio (F-013). */
  deletePortfolioMutation: ReturnType<
    typeof useMutation<unknown, Error, string>
  >;
}

// ── Implementation ────────────────────────────────────────────────────────────

export function usePortfolioData(
  args: UsePortfolioDataArgs,
): UsePortfolioDataResult {
  const { accessToken, selectedPeriod = "1D" } = args;
  const queryClient = useQueryClient();

  // WHY selectedPortfolioId in state (not URL): switching portfolios is
  // ephemeral. The URL always shows /portfolio regardless of which portfolio
  // is active.
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string | null>(
    null,
  );

  // ── Query 1: portfolio list ────────────────────────────────────────────
  const {
    data: portfolios,
    isLoading: portfoliosLoading,
    isError: portfoliosError,
  } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // ── Sort with ROOT first (PLAN-0046 W3 / T-46-3-04) ────────────────────
  // Slice to avoid mutating the TanStack Query cached array (would trigger
  // re-renders downstream and confuse staleness detection).
  const sortedPortfolios = useMemo(() => {
    if (!portfolios) return undefined;
    return portfolios.slice().sort((a, b) => {
      const aRoot = a.kind === "root" ? 0 : 1;
      const bRoot = b.kind === "root" ? 0 : 1;
      if (aRoot !== bRoot) return aRoot - bRoot;
      return a.name.localeCompare(b.name);
    });
  }, [portfolios]);

  // WHY derived activePortfolioId (not stored): default = sortedPortfolios[0]
  // (= ROOT once it lands in S1's response). Selecting a portfolio updates
  // selectedPortfolioId. Storing both would cause a double-render on init.
  const activePortfolioId =
    selectedPortfolioId ?? sortedPortfolios?.[0]?.portfolio_id ?? null;
  const activePortfolio = sortedPortfolios?.find(
    (p) => p.portfolio_id === activePortfolioId,
  );
  const activeIsRoot = activePortfolio?.kind === "root";

  // ── Query 2: holdings ───────────────────────────────────────────────────
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings", activePortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(activePortfolioId!),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 3: live quotes for holdings (15s refresh) ────────────────────
  // WHY a stable holdingInstrumentIds memo: the array reference is the
  // queryKey identity for batch quotes. Without memoisation the array
  // would be a fresh reference every render → every render becomes a new
  // queryKey → 15s polling becomes effectively continuous polling.
  const holdingInstrumentIds = useMemo(
    () => holdingsResp?.holdings.map((h) => h.instrument_id) ?? [],
    [holdingsResp],
  );
  const { data: holdingsQuotesData } = useQuery({
    queryKey: ["holdings-quotes", holdingInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(holdingInstrumentIds),
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 15_000,
    staleTime: 0,
  });

  // ── Query 4: transactions ───────────────────────────────────────────────
  const { data: transactionsResp, isLoading: txLoading } = useQuery({
    queryKey: ["transactions", activePortfolioId],
    queryFn: () =>
      createGateway(accessToken).getTransactions(activePortfolioId!, {
        limit: 100,
      }),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 5: watchlists ────────────────────────────────────────────────
  const { data: watchlists, isLoading: watchlistsLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // ── Query 6: live quotes for all watchlist members (30s refresh) ───────
  const watchlistInstrumentIds = useMemo(
    () =>
      (watchlists ?? [])
        .flatMap((wl) => wl.members.map((m) => m.instrument_id))
        .filter((id): id is string => id !== null),
    [watchlists],
  );
  const { data: watchlistQuotesData } = useQuery({
    queryKey: ["watchlist-quotes", watchlistInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(watchlistInstrumentIds),
    enabled: watchlistInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });

  // ── Query 7: realized P&L FIFO (PLAN-0051 T-A-1-05) ───────────────────
  // WHY default range = current calendar year: matches 1099-B statements;
  // future drill-down panel can override.
  const realizedRange = useMemo(() => defaultRealizedPnLRange(), []);
  const realizedPnLQuery = useRealizedPnL(
    activePortfolioId,
    realizedRange.from,
    realizedRange.to,
  );

  // ── Query 8: portfolio period performance ─────────────────────────────
  // WHY independent from holdings queries: performance depends on OHLCV
  // data from S3, not live quotes. Re-runs only when the portfolio or
  // period changes — not on the 15s quote poll cycle.
  const { data: performanceData, isLoading: performanceLoading } = useQuery({
    queryKey: ["portfolio-performance", activePortfolioId, selectedPeriod],
    queryFn: () =>
      createGateway(accessToken).getPortfolioPerformance(
        activePortfolioId!,
        selectedPeriod,
      ),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 60_000,
  });

  // ── Query 9: company overviews for holdings (sector + ticker) ─────────
  // WHY 5-min staleTime: gics_sector rebalances annually; ticker/name are
  // permanent. Avoids redundant requests on tab switches.
  const { data: holdingOverviews } = useQuery({
    queryKey: ["holdings-overviews", holdingInstrumentIds],
    queryFn: async () => {
      const results = await Promise.all(
        holdingInstrumentIds.map((id) =>
          createGateway(accessToken).getCompanyOverview(id).catch(() => null),
        ),
      );
      return Object.fromEntries(
        holdingInstrumentIds.map((id, i) => [
          id,
          {
            sector: results[i]?.instrument?.gics_sector ?? null,
            ticker: results[i]?.instrument?.ticker ?? null,
            name: results[i]?.instrument?.name ?? null,
            entity_id: results[i]?.instrument?.entity_id ?? null,
          },
        ]),
      ) as HoldingOverviewMap;
    },
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    staleTime: 300_000,
  });

  // ── Stable derived values ──────────────────────────────────────────────
  const holdingsQuotes = useMemo(
    () => holdingsQuotesData?.quotes ?? {},
    [holdingsQuotesData],
  );
  const watchlistQuotes = useMemo(
    () => watchlistQuotesData?.quotes ?? {},
    [watchlistQuotesData],
  );
  const holdings = useMemo(
    () => holdingsResp?.holdings ?? [],
    [holdingsResp],
  );

  // ── Enriched holdings: merge ticker/name/entity_id from overviews ─────
  // WHY parentheses around (a ?? b) || c: TS5076 disallows mixing ?? and ||
  // without explicit grouping. Intent: prefer enrichment value, else the
  // existing field, else a derived placeholder.
  const enrichedHoldings = useMemo(
    () =>
      holdings.map((h) => {
        const ov = holdingOverviews?.[h.instrument_id];
        return {
          ...h,
          ticker:
            (ov?.ticker ?? h.ticker) ||
            h.instrument_id.slice(0, 8).toUpperCase(),
          name:
            (ov?.name ?? h.name) ||
            `Instrument ${h.instrument_id.slice(-6)}`,
          entity_id: (ov?.entity_id ?? h.entity_id) || h.instrument_id,
        };
      }),
    [holdings, holdingOverviews],
  );

  // ── KPI / allocation / scope-hint (pure functions, unit-tested) ───────
  const kpi = useMemo(
    () =>
      computePortfolioKPI(enrichedHoldings, holdingsQuotes, transactionsResp),
    [enrichedHoldings, holdingsQuotes, transactionsResp],
  );

  // WHY separate memo from kpi: holdingOverviews resolves later than
  // holdingsQuotes (extra round-trip per holding). Keeping allocations in
  // its own memo means the KPI strip updates immediately when quotes
  // arrive, while SectorAllocationPanel fills in asynchronously without
  // blocking the KPI strip.
  const { bySector, byType } = useMemo(
    () => computeAllocations(enrichedHoldings, holdingOverviews, holdingsQuotes),
    [enrichedHoldings, holdingOverviews, holdingsQuotes],
  );

  // F-021 scope hint — rendered under the portfolio selector.
  const scopeHint = useMemo(
    () =>
      computeScopeHint(
        activePortfolio,
        activeIsRoot,
        sortedPortfolios,
        enrichedHoldings.length,
      ),
    [activePortfolio, activeIsRoot, sortedPortfolios, enrichedHoldings.length],
  );

  // ── Mutations + invalidation callbacks ────────────────────────────────

  /**
   * handlePortfolioCreated — runs after CreatePortfolioDialog succeeds.
   * Invalidates ["portfolios"] then pre-selects the new portfolio so the UI
   * switches to it as soon as the refetched list arrives.
   */
  const handlePortfolioCreated = useCallback(
    (newPortfolio: Portfolio) => {
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      setSelectedPortfolioId(newPortfolio.portfolio_id);
    },
    [queryClient],
  );

  /**
   * handlePositionAdded — runs after AddPositionDialog succeeds. Invalidates
   * holdings (to show the new row) and transactions (the BUY tx) for the
   * active portfolio.
   */
  const handlePositionAdded = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: ["holdings", activePortfolioId],
    });
    void queryClient.invalidateQueries({
      queryKey: ["transactions", activePortfolioId],
    });
  }, [queryClient, activePortfolioId]);

  // ── F-013: Delete portfolio mutation ──────────────────────────────────
  // WHY here: needs ["portfolios"] invalidation + a fall-back of the active
  // selection — both scoped to the page-level state owned by this hook.
  const deletePortfolioMutation = useMutation<unknown, Error, string>({
    mutationFn: (portfolioId: string) =>
      createGateway(accessToken).deletePortfolio(portfolioId),
    onSuccess: (_, deletedId) => {
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      // If we just deleted the active one, fall back to whichever portfolio
      // sortedPortfolios?.[0] resolves to next render (typically root).
      if (activePortfolioId === deletedId) {
        setSelectedPortfolioId(null);
      }
    },
  });

  return {
    portfolios,
    sortedPortfolios,
    selectedPortfolioId,
    setSelectedPortfolioId,
    activePortfolioId,
    activePortfolio,
    activeIsRoot,
    portfoliosLoading,
    portfoliosError,
    holdingsLoading,
    txLoading,
    watchlistsLoading,
    holdingsResp,
    holdings,
    enrichedHoldings,
    holdingInstrumentIds,
    holdingsQuotes,
    holdingOverviews,
    transactionsResp,
    watchlists,
    watchlistQuotes,
    performanceData,
    performanceLoading,
    realizedPnLQuery,
    kpi,
    bySector,
    byType,
    scopeHint,
    handlePortfolioCreated,
    handlePositionAdded,
    deletePortfolioMutation,
  };
}
