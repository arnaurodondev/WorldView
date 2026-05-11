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
 * more accurate than mechanical "same sector" peers. Sector fill-in pads remaining
 * slots (up to 4 total) with market-cap-similar peers from the same GICS sector.
 *
 * WHY COMBINED KG + SECTOR APPROACH (user request, investigation 2026-05-04):
 * KG competitors give precision (curated, relationship-aware). Sector peers sorted
 * by market cap proximity give coverage when KG has fewer than 4 competitors.
 *
 * ARCHITECTURE — KG entity_id ≠ S3 instrument_id (ADR-F-12, BP-367):
 * The KG entity_id (from COMPETES_WITH edges) is NOT the same UUID as S3's
 * instrument_id. S9 proxy normalises graph nodes to include `ticker` so that the
 * frontend can bridge the two ID spaces without a second lookup.
 * Resolution path: COMPETES_WITH edge → competitor entity_id → graph node.ticker
 * → screener result (matched by ticker) → fundamentals metrics.
 *
 * WHY SINGLE SCREENER CALL (not N getCompanyOverview calls):
 * The screener returns all instruments with their fundamentals in one request.
 * With ~30 instruments in the system, fetching all and filtering client-side by
 * ticker is efficient. This avoids N parallel getCompanyOverview calls where each
 * hits 4+ downstream services.
 *
 * BUG FIX 2026-05-04 (BP-367, v2):
 *   v1 used `e.label === "COMPETES_WITH"` (case mismatch) and tried screener
 *   entity_id filter (unsupported). v2 fixes:
 *   1. S9 now normalises edge labels to lowercase → `"competes_with"` always
 *   2. S9 now includes `ticker` in graph nodes → resolve entity → S3 instrument
 *   3. Single screener call → client-side ticker matching → no entity_id filter needed
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
import type { Instrument } from "@/types/api";

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

// ── Internal display row ───────────────────────────────────────────────────────

interface PeerRow {
  key: string;
  ticker: string;
  pe_ratio: number | null;
  market_cap: number | null;
  daily_return: number | null;
  /** "kg" — from COMPETES_WITH edge; "sector" — market-cap-similar sector peer */
  source: "kg" | "sector";
}

// ── Component ─────────────────────────────────────────────────────────────────

const MAX_PEERS = 4;

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
  // WHY staleTime 600_000: KG relationships change very rarely.
  const { data: graph, isLoading: graphLoading } = useQuery({
    queryKey: ["entity-graph", entityId, 1],
    queryFn: () => gateway.getEntityGraph(entityId, 1),
    enabled: !!accessToken && !!entityId,
    staleTime: 600_000,
  });

  // ── Extract competitor entity_ids and build entity_id → ticker map ────────
  // WHY toLowerCase(): S9 normalises canonical_type to lowercase (proxy.py fix),
  // but older seeded edges in the DB use uppercase ("COMPETES_WITH"). S9 now
  // lowercases in _transform_graph_response so this is defensive.
  // WHY build ticker map from nodes: S9 now includes ticker in each node.
  // KG entity_id ≠ S3 instrument_id — ticker is the bridge between the two
  // ID spaces (the only stable cross-service key). See BP-367 v2.
  const nodeTickerMap = new Map<string, string>(
    (graph?.nodes ?? [])
      .filter((n) => n.ticker)
      .map((n) => [n.id, n.ticker!]),
  );

  const competitorEntityIds: string[] = (graph?.edges ?? [])
    .filter((e) => e.label.toLowerCase() === "competes_with")
    .map((e) => (e.source === entityId ? e.target : e.source))
    .filter((id) => id !== entityId)
    .slice(0, MAX_PEERS);

  // Tickers of KG competitors — used to match screener results below.
  const competitorTickers = new Set<string>(
    competitorEntityIds
      .map((id) => nodeTickerMap.get(id) ?? "")
      .filter(Boolean),
  );

  // ── Fetch all instruments via screener ────────────────────────────────────
  // WHY fetch all (not per-competitor): screener has no entity_id or ticker
  // filter. With ~30-50 instruments total, fetching all and matching client-side
  // by ticker is efficient (1 request vs N parallel getCompanyOverview calls
  // that each fan-out to 4+ downstream services).
  // WHY wait until graph loaded: we need competitorTickers before we know
  // if we should enable the sector fallback or not. But the screener query
  // is cheap — always run it so sector fill-in works without a second roundtrip.
  // WHY three metrics in filters: backend ScreenFilterRequest only includes a
  // metric in the response `metrics` dict when it is listed in the filters.
  // The screener uses INNER JOIN per filter — instruments missing any metric
  // are excluded. This is acceptable: liquid large-caps (which have all three)
  // are exactly the instruments meaningful for ratio comparison.
  // WHY wide pe_ratio/daily_return ranges: no actual filtering desired — just
  // include them so they appear in the response metrics dict alongside market_cap.
  const { data: screenerData, isLoading: screenerLoading } = useQuery({
    queryKey: ["all-instruments-screener-v2"],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          { metric: "market_capitalization", min_value: 0 },
          { metric: "pe_ratio", min_value: -999999, max_value: 999999 },
          { metric: "daily_return", min_value: -1, max_value: 1 },
        ],
        sort_by: "market_capitalization",
        sort_dir: "desc",
        limit: 100, // cover entire instrument universe in one call
      }),
    enabled: !!accessToken && !graphLoading,
    staleTime: 300_000,
  });

  const allResults = screenerData?.results ?? [];

  // ── Partition screener results → KG competitors first, then sector fill ───
  const kgPeers: PeerRow[] = allResults
    .filter(
      (r) =>
        competitorTickers.has(r.ticker) &&
        r.ticker !== (instrument?.ticker ?? ""),
    )
    .slice(0, MAX_PEERS)
    .map((r) => ({
      key: r.entity_id || r.instrument_id,
      ticker: r.ticker,
      pe_ratio: r.pe_ratio,
      market_cap: r.market_cap,
      daily_return: r.daily_return,
      source: "kg" as const,
    }));

  // WHY sector + market-cap similarity fill: user asked for "similarity data"
  // combined with graph knowledge. After KG peers, fill remaining slots with
  // instruments from the same GICS sector sorted by closest market cap.
  const slotsLeft = MAX_PEERS - kgPeers.length;
  const kgTickers = new Set(kgPeers.map((p) => p.ticker));
  const sectorFill: PeerRow[] = allResults
    .filter(
      (r) =>
        r.gics_sector === instrument?.gics_sector &&
        r.ticker !== (instrument?.ticker ?? "") &&
        !kgTickers.has(r.ticker) &&
        !competitorTickers.has(r.ticker), // exclude KG peers already shown
    )
    .sort(
      (a, b) =>
        Math.abs((a.market_cap ?? 0) - (currentMarketCap ?? 0)) -
        Math.abs((b.market_cap ?? 0) - (currentMarketCap ?? 0)),
    )
    .slice(0, slotsLeft)
    .map((r) => ({
      key: r.entity_id || r.instrument_id,
      ticker: r.ticker,
      pe_ratio: r.pe_ratio,
      market_cap: r.market_cap,
      daily_return: r.daily_return,
      source: "sector" as const,
    }));

  const peers: PeerRow[] = [...kgPeers, ...sectorFill];
  const hasKg = kgPeers.length > 0;
  const hasSectorFill = sectorFill.length > 0;

  const sourceLabel =
    hasKg && hasSectorFill
      ? "KG+sector"
      : hasKg
        ? "KG"
        : instrument?.gics_sector
          ? "sector"
          : "";

  const isLoading = graphLoading || screenerLoading;

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          COMPETITORS
        </span>
        <span className="ml-auto text-[9px] font-mono text-muted-foreground/60">
          {sourceLabel}
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
            key={peer.key}
            className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0"
          >
            <span className="font-mono text-[11px] text-muted-foreground w-10 flex-none truncate">
              {peer.ticker}
            </span>
            <span className="font-mono text-[11px] tabular-nums flex-1 text-right text-foreground">
              {formatRatio(peer.pe_ratio)}
            </span>
            <span className="font-mono text-[10px] tabular-nums w-16 text-right text-muted-foreground">
              {formatMarketCap(peer.market_cap)}
            </span>
            <span className={`font-mono text-[10px] tabular-nums w-12 text-right ${priceChangeClass(peer.daily_return)}`}>
              {peer.daily_return != null ? formatPercent(peer.daily_return) : "—"}
            </span>
          </div>
        ))}
    </div>
  );
}
