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
 * by market cap proximity give coverage when KG has fewer than 4 competitors, or
 * when no COMPETES_WITH edges exist yet (newly listed / niche companies).
 * The source badge ("KG", "KG+sector", "sector") lets analysts know what they're seeing.
 *
 * WHY getCompanyOverview PER COMPETITOR (not screener):
 * The screener POST /v1/fundamentals/screen accepts ScreenFilterRequest which requires
 * metric/min_value/max_value — it has no entity_id filter. Using getCompanyOverview
 * per competitor resolves correctly because entity_id = instrument_id (M-017 convention),
 * so each call fetches ticker + fundamentals for exactly the right company.
 *
 * BUG FIX 2026-05-04 (BP-367):
 *   Root cause #1: e.label === "COMPETES_WITH" — DB stores lowercase "competes_with";
 *   the proxy sets label from canonical_type which is lowercase. The UPPERCASE filter
 *   never matched, producing 0 competitor entity_ids every time.
 *
 *   Root cause #2: Screener called with legacy {field, operator, value} format which
 *   the backend's ScreenFilterRequest model doesn't accept (requires metric/min_value).
 *
 * WHO USES IT: FundamentalsTab right sidebar (Wave D-2)
 * DATA SOURCE: S9 graph + company overview + screener endpoints
 * DESIGN REFERENCE: PLAN-0041 §T-D-2-03
 */

"use client";
// WHY "use client": uses useQuery for graph + overview + screener fetches.

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

// ── Internal display row (unified shape for KG + sector peers) ────────────────

interface PeerRow {
  /** React list key — instrument_id or entity_id */
  key: string;
  ticker: string;
  pe_ratio: number | null;
  market_cap: number | null;
  daily_return: number | null;
  /** "kg" — from COMPETES_WITH edge; "sector" — market-cap-similar sector peer */
  source: "kg" | "sector";
}

// ── Component ─────────────────────────────────────────────────────────────────

const MAX_PEERS = 4; // max peer rows (current instrument row is shown separately above)

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
  // WHY lowercase "competes_with": S9 proxy sets edge label from canonical_type
  // (proxy.py:1649 `rel.get("canonical_type")`). The DB stores lowercase
  // relation types ("competes_with" not "COMPETES_WITH"). See BP-367.
  // WHY both source + target: COMPETES_WITH edges can be bidirectional.
  // Extract the "other" entity_id in each case.
  const competitorEntityIds: string[] = (graph?.edges ?? [])
    .filter((e) => e.label === "competes_with")
    .map((e) => (e.source === entityId ? e.target : e.source))
    .filter((id) => id !== entityId)
    .slice(0, MAX_PEERS);

  // ── Fetch company overview for each KG competitor ────────────────────────
  // WHY getCompanyOverview (not screener): screener POST /v1/fundamentals/screen
  // requires ScreenFilterRequest{metric, min_value, max_value} and has no entity_id
  // filter. getCompanyOverview(entityId) works because entity_id = instrument_id
  // per M-017 convention — S9 calls S3 at /api/v1/instruments/{entityId}.
  // WHY Promise.all in queryFn: a single cache entry per competitor set is simpler
  // than useQueries — the set changes rarely (KG COMPETES_WITH is near-static).
  const cacheKey = competitorEntityIds.slice().sort().join(",");
  const { data: kgOverviews, isLoading: kgLoading } = useQuery({
    queryKey: ["peer-overviews", cacheKey],
    queryFn: async () => {
      const results = await Promise.all(
        competitorEntityIds.map((id) =>
          gateway
            .getCompanyOverview(id)
            .catch(() => null), // WHY catch: one 404 should not kill the whole batch
        ),
      );
      return results;
    },
    enabled: !!accessToken && competitorEntityIds.length > 0 && !graphLoading,
    staleTime: 300_000, // 5 min — fundamentals change rarely
  });

  // ── Build KG peer rows from overview data ────────────────────────────────
  const kgPeers: PeerRow[] = (kgOverviews ?? [])
    .filter((ov) => ov !== null && ov.instrument)
    .map((ov) => ({
      key: ov!.instrument.instrument_id,
      ticker: ov!.instrument.ticker,
      pe_ratio: ov!.fundamentals?.pe_ratio ?? null,
      market_cap: ov!.fundamentals?.market_cap ?? null,
      daily_return: ov!.fundamentals?.daily_return ?? null,
      source: "kg" as const,
    }));

  // ── Sector fill-in screener ───────────────────────────────────────────────
  // WHY always run when kgPeers < MAX_PEERS (not only when 0):
  // User request: combine KG precision + market-cap similarity for coverage.
  // We fill remaining slots with sector peers sorted by |market_cap - current_market_cap|.
  // WHY metric="market_capitalization" min_value=0: ScreenFilterRequest requires a
  // `metric` (required field pattern ^[a-z_][a-z0-9_]{0,63}$). The sector field on
  // the filter narrows results to the same GICS sector without a separate filter clause.
  // WHY min_value=0: excludes negative/null market caps from results.
  const slotsLeft = MAX_PEERS - kgPeers.length;
  const { data: sectorData, isLoading: sectorLoading } = useQuery({
    queryKey: ["sector-peers-fill", instrument?.gics_sector, entityId],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          {
            metric: "market_capitalization",
            min_value: 0,
            // WHY sector on the filter (not a separate clause): ScreenFilterRequest
            // has an optional `sector` field that scopes the metric filter to a
            // single GICS sector without needing a second filter entry.
            sector: instrument?.gics_sector ?? undefined,
          },
        ],
        sort_by: "market_cap",
        sort_dir: "desc",
        limit: 20, // fetch more than needed so we can exclude self + KG peers + sort by similarity
      }),
    enabled:
      !!accessToken &&
      !!instrument?.gics_sector &&
      !graphLoading &&
      !kgLoading &&
      slotsLeft > 0,
    staleTime: 300_000,
  });

  // ── Build sector fill rows sorted by market-cap similarity ───────────────
  // WHY exclude KG competitors: they're already shown in kgPeers; avoid duplicates.
  // WHY sort by |mcap - current|: closest peers by size are most meaningful
  // for ratio comparison (P/E of a $10B company vs a $10B benchmark is relevant;
  // vs a $500B mega-cap it's less so).
  const kgIds = new Set(competitorEntityIds);
  const sectorFill: PeerRow[] = (sectorData?.results ?? [])
    .filter((r) => r.entity_id !== entityId && !kgIds.has(r.entity_id))
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

  // ── Final peers list — KG first, then sector fill ─────────────────────────
  const peers: PeerRow[] = [...kgPeers, ...sectorFill];
  const hasKg = kgPeers.length > 0;
  const hasSectorFill = sectorFill.length > 0;

  // ── Source badge label ────────────────────────────────────────────────────
  // WHY three states: analysts need to know if they're seeing analyst-curated
  // relationships, mechanical sector peers, or a combination of both.
  const sourceLabel = hasKg && hasSectorFill
    ? "KG+sector"
    : hasKg
    ? "KG"
    : instrument?.gics_sector
    ? "sector"
    : "";

  const isLoading = graphLoading || kgLoading || sectorLoading;

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          COMPETITORS
        </span>
        {/* WHY source label: shows analyst whether they're seeing curated KG peers,
            sector fill-in, or a hybrid — different quality signals. */}
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
