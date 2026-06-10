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
// WHY qk: all queryKey literals must go through the central factory so
// invalidations from mutations, callbacks, and test assertions all point at
// the same cache entry. Inline string arrays are migration targets (PLAN-0070 D-1).
import { qk } from "@/lib/query/keys";
import {
  useRealizedPnL,
  defaultRealizedPnLRange,
} from "@/hooks/useRealizedPnL";
// PLAN sprint R1 (2026-06-10): the KPI strip's CASH / BUYING PWR tiles need the
// exposure endpoint. useExposure is the shared hook already used by
// ExposureBreakdown / ExposureCurrencyStrip — reusing it (same queryKey
// ["exposure", id]) means TanStack deduplicates: one network call feeds the KPI
// strip AND the exposure strips. This closes the BP-517-class regression where
// cash/buyingPower props were never passed to PortfolioKPIStrip and the tiles
// permanently rendered "—".
import { useExposure } from "@/hooks/useExposure";
import type {
  Portfolio,
  Holding,
  Watchlist,
  HoldingsResponse,
  TransactionsResponse,
  BatchQuoteResponse,
  ExposureResponse,
} from "@/types/api";

import {
  computePortfolioKPI,
  computeAllocations,
  computeScopeHint,
  type PortfolioKPI,
  type PortfolioAllocations,
  type AllocationSlice,
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
  /**
   * R4 hardening: re-runs the portfolio-list query (Query 1). Wired to the
   * Retry action on the page-level "Failed to load portfolio data" state so
   * a transient network failure is recoverable IN PLACE — the previous
   * InlineEmptyState forced a full browser reload, throwing away every other
   * warm cache entry (quotes, watchlists) that may have loaded fine.
   * WHY refetch (not invalidateQueries): refetch re-runs even while the
   * query is in error state and returns a promise the button can void;
   * invalidate alone would not refire a query with no active observers.
   */
  refetchPortfolios: () => void;
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
  /**
   * Server-side pagination offset for the transactions query (R1 sprint).
   * WHY exposed: the Transactions tab renders a Prev/Next pager when
   * `transactionsResp.total > limit`. The offset lives here (not in the tab)
   * so BOTH /portfolio?tab=transactions and /portfolio/transactions drive the
   * same cache entries and the offset resets when the portfolio changes.
   */
  txOffset: number;
  /** Move to another transactions page. Pass `offset + limit` / `offset - limit`. */
  setTxOffset: (offset: number) => void;
  /** Page size used by the transactions query (constant — 100 rows/page). */
  txPageSize: number;

  // ── Exposure (cash / buying power) ────────────────────────────────────
  /**
   * Exposure snapshot from GET /v1/portfolios/{id}/exposure.
   * `cash` feeds the CASH tile; BUYING PWR = cash for v1 cash accounts
   * (margin is v2 — see PortfolioKPIStrip prop docs).
   * undefined while loading / on error → tiles render "—" (never a fake $0).
   */
  exposure: ExposureResponse | undefined;

  /**
   * Best-effort asset-class lookup keyed by instrument_id, derived from the
   * transactions response (S1 enriches each transaction with asset_class via
   * an instruments JOIN — PLAN-0053 T-D-4-02). Drives the holdings table
   * ASSET column. Holdings with no transaction on the current page resolve
   * to undefined → the AssetTypeCellRenderer renders its "—" placeholder.
   *
   * WHY derived client-side (not fetched): neither the holdings payload nor
   * the company-overview batch carries asset_class today (backend gap), but
   * transactions already do — zero extra round-trips for real data.
   */
  assetClassByInstrument: Record<string, string | null>;

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

/**
 * TX_PAGE_SIZE — server-side page size for the transactions query.
 * WHY 100 (the legacy `limit: 100`): preserves the previous request shape so
 * the S1 query plan / Valkey cache behaviour is unchanged; the R1 sprint only
 * adds the `offset` dimension on top.
 */
const TX_PAGE_SIZE = 100;

export function usePortfolioData(
  args: UsePortfolioDataArgs,
): UsePortfolioDataResult {
  const { accessToken, selectedPeriod = "1D" } = args;
  const queryClient = useQueryClient();

  // WHY selectedPortfolioId in state (not URL): switching portfolios is
  // ephemeral. The URL always shows /portfolio regardless of which portfolio
  // is active.
  const [selectedPortfolioId, setSelectedPortfolioIdRaw] = useState<
    string | null
  >(null);

  // ── Transactions pagination state (R1 sprint) ─────────────────────────
  // WHY useState (not URL): the transactions page index is ephemeral browsing
  // state — sharing a deep link to "page 3 of my transactions" has no value
  // and would go stale as new fills arrive (newest-first ordering shifts rows
  // across pages).
  const [txOffset, setTxOffset] = useState(0);

  // WHY wrap the portfolio setter: switching portfolios must reset the
  // transactions pager to page 1 — portfolio B may have fewer transactions
  // than the current offset, which would render a confusing empty page.
  const setSelectedPortfolioId = useCallback((id: string | null) => {
    setTxOffset(0);
    setSelectedPortfolioIdRaw(id);
  }, []);

  // ── Query 1: portfolio list ────────────────────────────────────────────
  // WHY qk.portfolios.all: the root ["portfolios"] key; invalidating it
  // cascades to any partial-match child query under this prefix.
  const {
    data: portfolios,
    isLoading: portfoliosLoading,
    isError: portfoliosError,
    // R4 hardening: surfaced to the page so the named error state can offer
    // an in-place Retry (see the result-interface doc comment).
    refetch: refetchPortfolios,
  } = useQuery({
    queryKey: qk.portfolios.all,
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
  // WHY holdingsByPortfolio: uses the flat ["holdings", id] shape (not the
  // nested portfolios.detail path) to match the legacy cache entry shape.
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: qk.portfolios.holdingsByPortfolio(activePortfolioId ?? ""),
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
  // WHY holdingsQuotesByIds: the quotes key includes sorted instrument IDs so
  // the same set of holdings always hits the same cache bucket regardless of
  // iteration order (e.g. after a re-sort by the server response).
  const { data: holdingsQuotesData } = useQuery({
    queryKey: qk.portfolios.holdingsQuotesByIds(holdingInstrumentIds),
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(holdingInstrumentIds),
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 15_000,
    staleTime: 0,
  });

  // ── Query 4: transactions ───────────────────────────────────────────────
  // WHY transactionsByPortfolio: uses the flat ["transactions", id] shape to
  // match the legacy cache entry — different from qk.portfolios.transactions()
  // which nests under the detail path.
  // R1 sprint: txOffset appended to the key so each page gets its own cache
  // entry. Invalidations that target the ["transactions", id] PREFIX (e.g.
  // handlePositionAdded below) still match every page — TanStack invalidation
  // is prefix-based.
  const { data: transactionsResp, isLoading: txLoading } = useQuery({
    queryKey: [
      ...qk.portfolios.transactionsByPortfolio(activePortfolioId ?? ""),
      txOffset,
    ],
    queryFn: () =>
      createGateway(accessToken).getTransactions(activePortfolioId!, {
        limit: TX_PAGE_SIZE,
        offset: txOffset,
      }),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
    // WHY placeholderData keeps the previous page: without it, clicking
    // "Next" unmounts the table into the 6-row skeleton for the duration of
    // the fetch — a jarring flash for what is usually a <100ms cached hop.
    // Keeping the old rows visible until the new page lands matches the
    // behaviour of every terminal blotter pager.
    placeholderData: (prev) => prev,
  });

  // ── Query 5: watchlists ────────────────────────────────────────────────
  // WHY qk.watchlists.all: the root ["watchlists"] key. Safe to use here
  // since shape is identical to the old inline literal.
  const { data: watchlists, isLoading: watchlistsLoading } = useQuery({
    queryKey: qk.watchlists.all,
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
  // WHY watchlistQuotes(ids): sorted IDs give a stable cache key regardless of
  // watchlist ordering. The sort is done inside the factory method.
  const { data: watchlistQuotesData } = useQuery({
    queryKey: qk.portfolios.watchlistQuotes(watchlistInstrumentIds),
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(watchlistInstrumentIds),
    enabled: watchlistInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });

  // ── Query 6b: exposure — cash / buying power for the KPI strip ─────────
  // WHY useExposure (not an inline useQuery): the shared hook owns the
  // ["exposure", id] key that ExposureBreakdown and ExposureCurrencyStrip
  // already subscribe to — one network round-trip feeds all three surfaces.
  // The hook internally disables itself when portfolioId/token are null, so
  // no extra `enabled` plumbing is needed here.
  const exposureQuery = useExposure(activePortfolioId);

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
  // WHY performance(id, period): the period is part of the cache key because
  // performance data is computed server-side per horizon (1D vs 1W vs 1M
  // return different OHLCV windows).
  const { data: performanceData, isLoading: performanceLoading } = useQuery({
    queryKey: qk.portfolios.performance(activePortfolioId ?? "", selectedPeriod),
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
  // WHY holdingOverviews(ids): sorted IDs ensure a stable cache bucket even if
  // holdingInstrumentIds is produced in different iteration order after mutations.
  //
  // PLAN-0099 F-1 FIX (2026-06-06): collapsed the N parallel
  // getCompanyOverview() calls into a single POST /v1/companies/overviews:batch
  // round-trip. Previously a 20-holding portfolio fired 20 sequential HTTP +
  // auth round-trips; now it's exactly one. The returned shape (HoldingOverviewMap
  // keyed by instrument_id) is unchanged so all downstream call sites
  // (enrichedHoldings, computeAllocations) continue to work without edits.
  const { data: holdingOverviews } = useQuery({
    queryKey: qk.portfolios.holdingOverviews(holdingInstrumentIds),
    queryFn: async () => {
      // Batch fetch — S9 fans out server-side and returns null per leg on failure.
      const overviewsMap = await createGateway(accessToken)
        .getCompanyOverviewsBatch(holdingInstrumentIds)
        .catch(() => ({}) as Record<string, null>);
      return Object.fromEntries(
        holdingInstrumentIds.map((id) => {
          // WHY indirect: overviewsMap may be missing the key if the batch
          // endpoint returned a partial response — coerce to null safely.
          const ov = overviewsMap[id] ?? null;
          return [
            id,
            {
              sector: ov?.instrument?.gics_sector ?? null,
              ticker: ov?.instrument?.ticker ?? null,
              name: ov?.instrument?.name ?? null,
              entity_id: ov?.instrument?.entity_id ?? null,
            },
          ];
        }),
      ) as HoldingOverviewMap;
    },
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    staleTime: 300_000,
  });

  // ── Query 10: server-side sector breakdown (fast cached endpoint) ─────
  // WHY this replaces client-side computeAllocations() for the sector dim:
  //   The new GET /v1/portfolios/{id}/sector-breakdown endpoint returns a
  //   pre-computed sector snapshot in 31–86ms (60s Valkey cache), vs the
  //   ~640ms it took the old sector-attribution endpoint. Client-side
  //   computation was a further fallback when overviews hadn't resolved yet.
  //
  // WHY staleTime = 60_000: matches the Valkey TTL on the S9/S1 side —
  // fetching more often would still hit the cache, so there is no benefit
  // to a shorter window.
  //
  // WHY enabled guard on activePortfolioId (not holdingInstrumentIds.length):
  //   The breakdown is per-portfolio, not per-holding. An empty portfolio
  //   should still fire the request (server returns an empty segments array),
  //   consistent with how `getConcentration` behaves.
  const { data: sectorBreakdownData } = useQuery({
    queryKey: qk.portfolios.sectorBreakdown(activePortfolioId ?? ""),
    queryFn: () =>
      createGateway(accessToken).getSectorBreakdown(activePortfolioId!),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 60_000,
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

  // ── Asset-class lookup for the holdings ASSET column (R1 sprint) ──────
  // First-write-wins per instrument: every transaction for the same
  // instrument carries the same asset_class (it's an instruments-table JOIN
  // value, not per-trade data), so any row is authoritative.
  const assetClassByInstrument = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const tx of transactionsResp?.transactions ?? []) {
      if (tx.asset_class != null && map[tx.instrument_id] == null) {
        map[tx.instrument_id] = tx.asset_class;
      }
    }
    return map;
  }, [transactionsResp]);

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
  const { bySector: bySectorClientSide, byType } = useMemo(
    () => computeAllocations(enrichedHoldings, holdingOverviews, holdingsQuotes),
    [enrichedHoldings, holdingOverviews, holdingsQuotes],
  );

  // ── bySector: prefer server snapshot, fall back to client-side ────────
  // WHY prefer server: the sector-breakdown endpoint is pre-computed with full
  // market-data access and is 7–20× faster. Client-side computation uses only
  // the batch-quote subset, so holdings with missing quotes fall back to cost
  // basis — less accurate than what the server computes.
  //
  // WHY fall back to bySectorClientSide (not []): during cold-start the server
  // query is in-flight while the overviews query may already have resolved.
  // Keeping the client-side data visible prevents a blank SectorAllocationBar
  // flash as the server query settles.
  //
  // WHY multiply weight by totalPortfolioValue for `value`: AllocationSlice.value
  // is the market value in portfolio currency. SectorBreakdownSegment already
  // carries market_value directly so we use that field.
  const bySector: AllocationSlice[] = useMemo(() => {
    if (sectorBreakdownData?.segments?.length) {
      // Map SectorBreakdownSegment → AllocationSlice.
      // `weight` is a 0-1 fraction; `pct` on AllocationSlice is also 0-1.
      return sectorBreakdownData.segments.map((seg) => ({
        label: seg.sector,
        value: seg.market_value,
        pct: seg.weight,
      }));
    }
    // Server data not yet available — use client-side computation.
    return bySectorClientSide;
  }, [sectorBreakdownData, bySectorClientSide]);

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
      // WHY qk.portfolios.all: invalidating the root key cascades to every
      // portfolio-scoped child query (holdings, transactions, performance, etc.)
      // so the new portfolio appears across all sub-views without extra calls.
      void queryClient.invalidateQueries({ queryKey: qk.portfolios.all });
      setSelectedPortfolioId(newPortfolio.portfolio_id);
    },
    // setSelectedPortfolioId is itself a stable useCallback([]) wrapper (R1
    // sprint — it resets the tx pager), so including it satisfies
    // exhaustive-deps without ever re-creating this callback.
    [queryClient, setSelectedPortfolioId],
  );

  /**
   * handlePositionAdded — runs after AddPositionDialog succeeds. Invalidates
   * holdings (to show the new row), transactions (the BUY tx), live quotes
   * (the new position needs a price), portfolio performance, and the bundle
   * endpoint so all portfolio views refresh consistently.
   *
   * WHY guard on activePortfolioId: if for any reason we don't have an active
   * portfolio (e.g. the dialog opened before portfolios resolved), we'd
   * invalidate the empty-string key which is harmless but misleading. The
   * guard makes the no-op path explicit and avoids confusing cache entries.
   */
  const handlePositionAdded = useCallback(() => {
    if (!activePortfolioId) return;

    // WHY flat keys (not nested detail path): invalidation must match the
    // exact key shape used by the queries above — qk.portfolios.holdingsByPortfolio
    // and qk.portfolios.transactionsByPortfolio return ["holdings", id] and
    // ["transactions", id] respectively which is what these queries use.
    void queryClient.invalidateQueries({
      queryKey: qk.portfolios.holdingsByPortfolio(activePortfolioId),
    });
    void queryClient.invalidateQueries({
      queryKey: qk.portfolios.transactionsByPortfolio(activePortfolioId),
    });
    // WHY holdingsQuotesAll prefix invalidation: after adding a position the
    // instrument ID set changes — the cached batch-quote key is no longer valid
    // because it encoded the old ID list. qk.portfolios.holdingsQuotesAll is the
    // root prefix ["holdings-quotes"] that matches all variant keys (F-045).
    void queryClient.invalidateQueries({
      queryKey: qk.portfolios.holdingsQuotesAll,
    });
    // WHY performance: adding a position changes cost-basis and may change the
    // period return_pct / return_abs computed server-side. Stale performance
    // data would show the wrong P&L in the KPI strip after the add.
    void queryClient.invalidateQueries({
      queryKey: qk.portfolios.performance(activePortfolioId, selectedPeriod),
    });
    // WHY bundle: PLAN-0070 C-1 introduced a bundle endpoint that pre-fetches
    // holdings + transactions + performance in one round-trip. If this page was
    // previously loaded via the bundle, that cached snapshot is now stale.
    void queryClient.invalidateQueries({
      queryKey: qk.portfolios.bundle(activePortfolioId),
    });
  }, [queryClient, activePortfolioId, selectedPeriod]);

  // ── F-013: Delete portfolio mutation ──────────────────────────────────
  // WHY here: needs ["portfolios"] invalidation + a fall-back of the active
  // selection — both scoped to the page-level state owned by this hook.
  const deletePortfolioMutation = useMutation<unknown, Error, string>({
    mutationFn: (portfolioId: string) =>
      createGateway(accessToken).deletePortfolio(portfolioId),
    // WHY retry (CRIT-006 / FR-8.1): all S1 mutations are idempotent (W1-Backend
    // audit). deletePortfolio returns 404 on "already deleted" (not 5xx) so retry
    // only fires on transient network / 5xx failures — exactly what we want.
    retry: 3,
    retryDelay: (attemptIndex: number) =>
      Math.min(1000 * 2 ** (attemptIndex - 1), 4000),
    onSuccess: (_, deletedId) => {
      // WHY qk.portfolios.all: the root ["portfolios"] key cascades to every
      // portfolio-scoped child query so the portfolio selector re-loads the
      // updated list without the deleted entry.
      void queryClient.invalidateQueries({ queryKey: qk.portfolios.all });
      // WHY bundle: the PLAN-0070 C-1 bundle caches holdings + transactions +
      // performance keyed by portfolioId. Deleting a portfolio leaves a ghost
      // bundle in the TanStack cache that would surface stale data if the
      // portfolio ID were ever reused or the cache weren't purged. Explicit
      // invalidation ensures the ghost entry is evicted immediately.
      void queryClient.invalidateQueries({
        queryKey: qk.portfolios.bundle(deletedId),
      });
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
    // R4: TanStack's refetch returns a promise + takes optional options; the
    // exposed contract is a plain thunk so callers can't depend on either.
    refetchPortfolios: () => void refetchPortfolios(),
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
    txOffset,
    setTxOffset,
    txPageSize: TX_PAGE_SIZE,
    exposure: exposureQuery.data,
    assetClassByInstrument,
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
