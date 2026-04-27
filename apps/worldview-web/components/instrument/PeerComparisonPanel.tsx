/**
 * components/instrument/PeerComparisonPanel.tsx — Peer/competitor comparison panel
 *
 * WHY THIS EXISTS: Fundamental ratios (P/E, market cap, growth) are only meaningful
 * in the context of peers. A P/E of 35x is expensive for a utility but cheap for
 * a SaaS company. Analysts immediately compare to competitors when evaluating a
 * security — Bloomberg DES shows a comparable companies table alongside key metrics.
 *
 * WHY COMPETES_WITH EDGES FIRST: S7 knowledge graph COMPETES_WITH edges are
 * analyst-curated relationships (extracted from SEC filings and news). They are
 * more accurate than mechanical "same sector" peers. Sector fallback handles the
 * case where no COMPETES_WITH edges exist (newly listed or niche companies).
 *
 * WHY SCREENER FOR PEER DATA: After getting competitor entity_ids from the graph,
 * we use the screener endpoint (POST /v1/fundamentals/screen) to batch-fetch P/E,
 * market cap, and daily return for all competitors in one API call. The screener
 * already enriches results with these fields from S3.
 *
 * WHY NOT N+1 INDIVIDUAL QUERIES: Each instrument's fundamentals would be a
 * separate GET /v1/fundamentals/{id} call. For 5 peers, that's 6 requests (5 peers
 * + 1 already loaded). A single screener POST with a `tickers` filter reduces
 * this to 1 request.
 *
 * WHO USES IT: FundamentalsTab right sidebar (Wave D-2)
 * DATA SOURCE: S9 graph + screener endpoints
 * DESIGN REFERENCE: PLAN-0041 §T-D-2-03
 */

"use client";
// WHY "use client": uses useQuery for graph + screener fetches.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMarketCap, formatRatio, formatPercent, priceChangeClass } from "@/lib/utils";
import type { Instrument, ScreenerResult } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface PeerComparisonPanelProps {
  entityId: string;
  /** Instrument for current security — used to highlight it and as sector fallback */
  instrument: Instrument | null;
  /** Current security's fundamentals data for the current row */
  currentMarketCap?: number | null;
  currentPeRatio?: number | null;
  currentDailyReturn?: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PeerComparisonPanel({
  entityId,
  instrument,
  currentMarketCap,
  currentPeRatio,
  currentDailyReturn,
}: PeerComparisonPanelProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // ── Fetch entity graph for COMPETES_WITH edges ────────────────────────────
  // WHY depth=1: we only need direct competitors (1 hop), not their competitors.
  // WHY staleTime 600_000: knowledge graph relationships change very rarely.
  const { data: graph, isLoading: graphLoading } = useQuery({
    queryKey: ["entity-graph", entityId, 1],
    queryFn: () => gateway.getEntityGraph(entityId, 1),
    enabled: !!accessToken && !!entityId,
    staleTime: 600_000, // 10 min — KG data changes very rarely
  });

  // ── Extract competitor entity IDs from COMPETES_WITH edges ───────────────
  // WHY both source + target: COMPETES_WITH edges can be bidirectional in S7.
  // An edge {source: AAPL, target: MSFT} and an edge {source: MSFT, target: AAPL}
  // both represent competition. Extract the "other" entity_id in each case.
  const competitorEntityIds: string[] = (graph?.edges ?? [])
    .filter((e) => e.label === "COMPETES_WITH")
    .map((e) => (e.source === entityId ? e.target : e.source))
    .filter((id) => id !== entityId) // exclude self-loops if any
    .slice(0, 4); // max 4 competitors to keep the panel compact

  // ── Fetch screener data for competitors ───────────────────────────────────
  // WHY entity_ids filter: screener accepts entity_id filters for precise matching.
  // WHY wait until graph loaded: competitor IDs come from the graph; we must have
  // them before running the screener. `enabled` condition prevents premature fetch.
  const { data: peerData, isLoading: peersLoading } = useQuery({
    queryKey: ["peer-screener", competitorEntityIds.join(",")],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          {
            // WHY entity_ids filter: the screener POST /v1/fundamentals/screen
            // accepts an `entity_ids` filter that matches exact entity UUIDs.
            // This is more reliable than ticker-based filters (tickers can change).
            field: "entity_id",
            operator: "in",
            value: competitorEntityIds,
          },
        ],
        sort_by: "market_cap",
        sort_dir: "desc",
        limit: 5,
      }),
    enabled: !!accessToken && competitorEntityIds.length > 0 && !graphLoading,
    staleTime: 300_000,
  });

  // ── Sector fallback screener ──────────────────────────────────────────────
  // WHY separate query (not unified): if COMPETES_WITH edges exist we use those.
  // The sector fallback runs only when no competitors were found in the graph.
  // Two independent queries are simpler than a combined conditional fetch.
  const hasPeers = (peerData?.results?.length ?? 0) > 0;
  const { data: sectorData, isLoading: sectorLoading } = useQuery({
    queryKey: ["sector-peers", instrument?.gics_sector],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          {
            field: "gics_sector",
            operator: "eq",
            value: instrument?.gics_sector ?? "",
          },
          {
            // WHY exclude self: the screener returns the current instrument in
            // sector results; filter it out to show only peer comparison rows.
            field: "entity_id",
            operator: "neq",
            value: entityId,
          },
        ],
        sort_by: "market_cap",
        sort_dir: "desc",
        limit: 4,
      }),
    // WHY enabled check: sector fallback only runs when graph loaded + no peers found
    enabled:
      !!accessToken &&
      !!instrument?.gics_sector &&
      !graphLoading &&
      !peersLoading &&
      !hasPeers,
    staleTime: 300_000,
  });

  // ── Build peer rows ───────────────────────────────────────────────────────
  // WHY use peerData if available, sector otherwise: COMPETES_WITH > sector peers
  const peers: ScreenerResult[] = hasPeers
    ? (peerData?.results ?? [])
    : (sectorData?.results ?? []);

  const isLoading = graphLoading || peersLoading || sectorLoading;

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          COMPETITORS
        </span>
        {/* WHY source label: shows analyst whether they're seeing curated KG peers
            or mechanical sector peers — different quality signals. */}
        <span className="ml-auto text-[9px] font-mono text-muted-foreground/60">
          {hasPeers ? "KG" : instrument?.gics_sector ? "sector" : ""}
        </span>
      </div>

      {/* ── Column headers ──────────────────────────────────────────────── */}
      <div className="flex items-center h-[20px] px-2 border-b border-border/30">
        <span className="text-[9px] uppercase font-mono text-muted-foreground/60 w-10 flex-none">
          TKR
        </span>
        <span className="text-[9px] uppercase font-mono text-muted-foreground/60 flex-1 text-right">
          P/E
        </span>
        <span className="text-[9px] uppercase font-mono text-muted-foreground/60 w-16 text-right">
          MCAP
        </span>
        <span className="text-[9px] uppercase font-mono text-muted-foreground/60 w-12 text-right">
          RET
        </span>
      </div>

      {/* ── Current instrument row (highlighted) ──────────────────────── */}
      {instrument && (
        <div className="flex items-center h-[22px] px-2 bg-primary/5 border-b border-border/30">
          <span className="font-mono text-[11px] text-primary font-medium w-10 flex-none truncate">
            {instrument.ticker}
          </span>
          <span className="font-mono text-[11px] tabular-nums flex-1 text-right text-foreground">
            {formatRatio(currentPeRatio ?? null)}
          </span>
          <span className="font-mono text-[10px] tabular-nums w-16 text-right text-muted-foreground">
            {formatMarketCap(currentMarketCap ?? null)}
          </span>
          <span className={`font-mono text-[10px] tabular-nums w-12 text-right ${priceChangeClass(currentDailyReturn ?? null)}`}>
            {currentDailyReturn != null ? formatPercent(currentDailyReturn) : "—"}
          </span>
        </div>
      )}

      {/* ── Loading state ──────────────────────────────────────────────── */}
      {isLoading && (
        <>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center h-[22px] px-2 gap-2 border-b border-border/30">
              <Skeleton className="h-3 w-8 flex-none" />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-12" />
              <Skeleton className="h-3 w-10" />
            </div>
          ))}
        </>
      )}

      {/* ── Peer rows ──────────────────────────────────────────────────── */}
      {!isLoading && peers.length === 0 && (
        <div className="px-2 py-1.5 text-[10px] font-mono text-muted-foreground">
          No peer data available
        </div>
      )}
      {!isLoading &&
        peers.map((peer) => (
          <div
            key={peer.instrument_id}
            className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0"
          >
            <span className="font-mono text-[11px] text-muted-foreground w-10 flex-none truncate">
              {peer.ticker}
            </span>
            <span className="font-mono text-[11px] tabular-nums flex-1 text-right text-foreground">
              {formatRatio(peer.pe_ratio ?? null)}
            </span>
            <span className="font-mono text-[10px] tabular-nums w-16 text-right text-muted-foreground">
              {formatMarketCap(peer.market_cap ?? null)}
            </span>
            <span className={`font-mono text-[10px] tabular-nums w-12 text-right ${priceChangeClass(peer.daily_return ?? null)}`}>
              {peer.daily_return != null ? formatPercent(peer.daily_return) : "—"}
            </span>
          </div>
        ))}
    </div>
  );
}
