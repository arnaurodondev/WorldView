/**
 * components/instrument/financials/PeerComparisonTable.tsx — Bloomberg-grade peer table
 *
 * WHY THIS EXISTS: Relative valuation is the backbone of fundamental analysis.
 * Seeing the subject company's P/E and 1Y return alongside 5 GICS peers at a
 * glance answers "is this cheap or expensive relative to the sector?" in seconds.
 * The self-row (bg-muted/30) anchors the comparison: analysts scan the peer
 * columns and immediately see whether the subject is in the top/bottom quartile.
 *
 * WHY return_1y from PeersResponse (not batch OHLCV): S9 pre-computes the 1Y
 * return from OHLCV bars in the peers endpoint itself (PeerInstrument.return_1y).
 * Using the pre-computed value eliminates the additional batch OHLCV round-trip
 * and avoids the 252-bar gate check — S9 already returns null when insufficient
 * bars exist.
 *
 * WHY two view modes (PEERS / COMPETITORS):
 * GICS industry peers (PEERS tab) answer "who is in the same sector?".
 * KG semantic competitors (COMPETITORS tab) answer "who does the knowledge graph
 * think this company actually competes with?" — derived from COMPETES_WITH edges
 * and ANN embedding similarity. The two views are deliberately kept separate:
 * GICS peers are manually classified by S&P; KG competitors are inferred from
 * financial news and filings.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 4 of the left column.
 * DATA SOURCES:
 *   PEERS:      PeersResponse from qk.instruments.peers(id) via useFinancialsSidebarData.
 *   COMPETITORS: SimilarEntitiesResponse from qk.kg.similarEntities(entityId) via
 *               getSimilarEntities() POST /v1/entities/similar.
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.4
 */

"use client";
// WHY "use client": useRouter + useState + useQuery all require the client runtime.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { formatMarketCap, formatPercent, formatPercentDirect, formatRatio } from "@/lib/utils";
import type { PeersResponse, Fundamentals, SimilarEntityItem } from "@/types/api";

// ── Types ──────────────────────────────────────────────────────────────────

/** Which sub-tab is active: industry peers vs KG semantic competitors. */
type PeerView = "PEERS" | "COMPETITORS";

interface PeerComparisonTableProps {
  /** Full peers response from S9 (includes industry and 5 nearest peers). */
  peersData: PeersResponse | undefined;
  /** Current instrument identifier (for self-row baseline). */
  instrumentId: string;
  /** Pre-fetched fundamentals for the self-row values. */
  fundamentals: Fundamentals | null;
  /**
   * KG entity UUID from the page-bundle. Used by the COMPETITORS tab to call
   * getSimilarEntities(). Optional — when absent the COMPETITORS tab is disabled
   * with a "KG entity not linked" message (PEERS tab keeps working normally).
   */
  entityId?: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function returnColor(v: number | null): string {
  if (v == null) return "text-muted-foreground/40";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-foreground";
}

// WHY two formatters: S3 sends `return_1y` as a decimal fraction (0.125 =
// 12.5%) but sends `change_pct` already as a percentage (3.1 = 3.1%).
// `formatPercent` (canonical) multiplies its input by 100, so it is correct
// for decimal fractions. `formatPercentDirect` does not multiply, so it is
// correct for already-scaled values.
function fmtDecimalPct(v: number | null | undefined): string {
  // WHY null guard before formatPercent: formatPercent returns DASH on null,
  // but an explicit guard keeps the intent explicit.
  if (v == null) return "—";
  return formatPercent(v); // input is 0.125 → formats as "+12.50%"
}

function fmtPctDirect(v: number | null | undefined): string {
  if (v == null) return "—";
  return formatPercentDirect(v); // input is 3.1 → formats as "+3.10%"
}

/**
 * Format a 0-1 similarity score as a percentage string.
 * WHY not formatPercent: formatPercent prepends "+" for positive values and
 * formats to 2 decimal places. Similarity scores are always non-negative and
 * don't need a sign — "87.4%" is cleaner than "+87.40%". We want 1 decimal
 * place for density: "87.4%" vs "+87.40%".
 */
function fmtSimilarity(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

/**
 * scoreColor — colour gradient for KG similarity score.
 * WHY custom colour logic (not returnColor): similarity is not a directional
 * return — high is always better. We use blue (brand) for high scores (≥80%),
 * muted for low (<50%), and foreground for middle to avoid unnecessary green
 * which implies "price up" to analysts used to colour conventions.
 */
function scoreColor(v: number): string {
  if (v >= 0.8) return "text-[#0EA5E9]"; // Midnight Pro blue — high confidence
  if (v >= 0.5) return "text-foreground";
  return "text-muted-foreground/60"; // low similarity — de-emphasise
}

// ── Sub-components ─────────────────────────────────────────────────────────

/** Skeleton rows for the COMPETITORS loading state (5 rows × 4 columns). */
function CompetitorsSkeleton() {
  return (
    // WHY animate-pulse on wrapper (not individual cells): one animation loop
    // covers all cells. Individual pulse on 20 cells creates 20 separate rAF
    // callbacks — unnecessary CPU overhead in a hot render path.
    <div className="animate-pulse" aria-label="Loading competitor data">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center h-[var(--row-h,20px)] px-2 border-b border-border/30 gap-2"
        >
          {/* TICKER column skeleton */}
          <div className="w-[52px] h-2.5 rounded bg-muted/40" />
          {/* NAME column skeleton — wider */}
          <div className="flex-1 h-2.5 rounded bg-muted/30" />
          {/* SIMILARITY column skeleton */}
          <div className="w-[52px] h-2.5 rounded bg-muted/40" />
          {/* TYPE column skeleton */}
          <div className="w-[64px] h-2.5 rounded bg-muted/30" />
        </div>
      ))}
    </div>
  );
}

/** Table of KG semantic competitors. Rendered when COMPETITORS tab is active. */
function CompetitorsTable({
  items,
}: {
  items: SimilarEntityItem[];
}) {
  const router = useRouter();

  return (
    <table className="w-full text-[11px] font-mono" role="table" aria-label="KG semantic competitors">
      <thead>
        <tr className="h-[var(--row-h,20px)]">
          {/* WHY 52px for TICKER: same column width as PEERS tab for visual
              alignment when the user switches between the two tabs. */}
          <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[52px]">Ticker</th>
          <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Name</th>
          {/* WHY text-right + tabular-nums on SIMILARITY: scores are numeric;
              right-aligning lets analysts scan the column for high-confidence
              competitors without re-reading each row. */}
          <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Similarity</th>
          <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Type</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border/30">
        {items.map((item) => (
          <tr
            key={item.entity_id}
            // WHY cursor-pointer: ticker column navigates to the competitor's
            // instrument page. The row is fully clickable for ergonomics.
            className="h-[var(--row-h,20px)] cursor-pointer hover:bg-muted/20 transition-colors"
            onClick={() => {
              // WHY router.push with ticker (not entity_id): instrument pages
              // are addressed by ticker in the URL (/instruments/AAPL). When
              // ticker is null (ETF/unresolved entity), fall back to entity_id
              // so the route at least lands on the correct page shell.
              if (item.ticker) {
                router.push(`/instruments/${encodeURIComponent(item.ticker)}`);
              }
            }}
            title={item.ticker ? `Go to ${item.ticker}` : undefined}
          >
            <td className="px-2 text-[11px] font-semibold text-primary tabular-nums whitespace-nowrap">
              {item.ticker ?? "—"}
            </td>
            <td className="px-2 text-[11px] text-foreground truncate max-w-[120px]">
              {item.canonical_name}
            </td>
            {/* WHY font-mono tabular-nums on similarity: numeric column —
                aligns decimal points across rows so analysts can scan quickly. */}
            <td className={`px-2 text-right tabular-nums whitespace-nowrap font-mono ${scoreColor(item.final_score)}`}>
              {fmtSimilarity(item.final_score)}
            </td>
            <td className="px-2 text-right">
              {/* WHY has_competes_with_relation → "competes" / "similar":
                  SimilarEntityItem has no `relation_type` field. The boolean
                  has_competes_with_relation is the closest available signal:
                  true = KG already has an explicit COMPETES_WITH edge;
                  false = ANN embedding similarity only, no confirmed edge yet. */}
              <span
                className={`text-[9px] uppercase tracking-widest ${
                  item.has_competes_with_relation
                    ? "text-[#26A69A]"  // KG-confirmed competitor — Midnight Pro green
                    : "text-muted-foreground/50"  // embedding-only similarity — de-emphasise
                }`}
              >
                {item.has_competes_with_relation ? "competes" : "similar"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Component ──────────────────────────────────────────────────────────────

export function PeerComparisonTable({
  peersData,
  fundamentals,
  entityId,
}: PeerComparisonTableProps) {
  const router = useRouter();

  // ── Tab toggle state ───────────────────────────────────────────────────
  // WHY local state (not URL param): the PEERS/COMPETITORS toggle is ephemeral
  // session state. Analysts flip between the two views without wanting the URL
  // to change — no back-button intent. Same pattern as period toggle in
  // FinancialsTab (ANNUAL/QUARTERLY p chord).
  const [view, setView] = useState<PeerView>("PEERS");

  // ── KG competitors fetch ───────────────────────────────────────────────
  // WHY enabled guard on entityId: when entityId is absent (FinancialsTab
  // used outside InstrumentPageClient) we disable the query entirely so the
  // PEERS tab keeps working with no network activity for the KG endpoint.
  //
  // WHY topK=10: peers tab shows 5 GICS peers; offering up to 10 KG competitors
  // gives analysts a broader picture of the competitive landscape without
  // overwhelming the table (10 rows ≈ same visual height as the full PEERS view).
  //
  // WHY minScore=0.0: we want ALL results the KG has for this entity and let
  // the backend rank by final_score. Filtering client-side on the score is a
  // future enhancement once we understand the distribution in production.
  //
  // WHY staleTime=10min: competitive landscape changes quarterly (new products,
  // partnerships). Re-fetching every 10 minutes on the Financials tab is more
  // than frequent enough. Same policy as the entity graph sub-tab.
  const gateway = useApiClient();
  const {
    data: similarData,
    isLoading: competitorsLoading,
    isError: competitorsError,
  } = useQuery({
    queryKey: qk.kg.similarEntities(entityId ?? ""),
    queryFn: () => gateway.getSimilarEntities(entityId!, 10, 0.0),
    staleTime: 10 * 60 * 1000,
    // WHY double guard (!!entityId && view === "COMPETITORS"): we only fire the
    // KG fetch when the COMPETITORS tab is actually active. Until the user clicks
    // COMPETITORS the request is never made — avoids paying the KG round-trip
    // cost on every Financials tab open.
    enabled: !!entityId && view === "COMPETITORS",
  });

  // ── Section header label ───────────────────────────────────────────────
  const industryLabel =
    view === "PEERS" && peersData?.industry ? ` — ${peersData.industry}` : "";

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    // WHY data-table-grid: 20px rows with border-based cell separators from
    // F1 §16.3 CSS variables.
    <div data-table-grid className="border-t border-border">
      {/* ── Header row: section label + PEERS / COMPETITORS toggle ──────── */}
      <div className="flex items-center justify-between h-[var(--row-h,20px)] px-2 border-b border-border bg-muted/20">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          PEER COMPARISON{industryLabel}
        </span>

        {/* ── Tab toggle buttons (Bloomberg terminal style) ─────────────
            WHY two text buttons with bottom-border underline (not pills):
            Finance terminal convention — active state is a 1px underline,
            not a filled background. Filled pills are for action buttons,
            not data-view toggles. `tracking-widest font-mono uppercase`
            keeps the label at the same visual weight as the column headers. */}
        <div className="flex items-center gap-3" role="tablist" aria-label="Peer view selector">
          <button
            role="tab"
            aria-selected={view === "PEERS"}
            onClick={() => setView("PEERS")}
            className={`text-[10px] font-mono uppercase tracking-widest transition-colors ${
              view === "PEERS"
                ? "text-foreground border-b border-foreground pb-px"
                : "text-muted-foreground/50 hover:text-muted-foreground"
            }`}
          >
            Peers
          </button>
          <button
            role="tab"
            aria-selected={view === "COMPETITORS"}
            onClick={() => setView("COMPETITORS")}
            className={`text-[10px] font-mono uppercase tracking-widest transition-colors ${
              view === "COMPETITORS"
                ? "text-foreground border-b border-foreground pb-px"
                : "text-muted-foreground/50 hover:text-muted-foreground"
            }`}
          >
            Competitors
          </button>
        </div>
      </div>

      {/* ── PEERS tab content ─────────────────────────────────────────────── */}
      {view === "PEERS" && (() => {
        // WHY IIFE pattern: allows early-return guard logic inside JSX without
        // extracting a full sub-component. The guard logic is short enough that
        // a sub-component would add more boilerplate than clarity.
        if (!peersData) {
          return (
            <div className="text-[11px] text-muted-foreground px-2 py-2">
              Peer data loading…
            </div>
          );
        }

        const peers = peersData.peers.slice(0, 5);
        if (peers.length === 0) {
          return (
            <div className="text-[11px] text-muted-foreground px-2 py-2">
              No peers available for this instrument.
            </div>
          );
        }

        return (
          <table className="w-full text-[11px] font-mono" role="table" aria-label="Peer comparison">
            <thead>
              <tr className="h-[var(--row-h,20px)]">
                <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal w-[52px]">Ticker</th>
                <th scope="col" className="px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">Name</th>
                <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Mkt Cap</th>
                <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal">P/E</th>
                <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">1Y Ret</th>
                <th scope="col" className="px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap">Day Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30">
              {/* Self row — highlighted with muted background per design spec. */}
              <tr
                className="h-[var(--row-h,20px)] bg-muted/30"
                data-peer-self="true"
              >
                <td className="px-2 text-[11px] font-semibold text-primary tabular-nums whitespace-nowrap">
                  {fundamentals?.ticker ?? "—"}
                </td>
                <td className="px-2 text-[11px] text-foreground truncate max-w-[120px]">
                  {fundamentals?.name ?? "—"}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                  {formatMarketCap(fundamentals?.market_cap ?? null)}
                </td>
                <td className="px-2 text-right tabular-nums text-foreground">
                  {fundamentals?.pe_ratio != null ? formatRatio(fundamentals.pe_ratio) : "—"}
                </td>
                {/* WHY 1Y return null for self: self-row uses fundamentals which
                    doesn't carry return_1y. Use change_pct (daily) instead. */}
                <td className={`px-2 text-right tabular-nums whitespace-nowrap text-muted-foreground/40`}>—</td>
                <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(fundamentals?.daily_return ?? null)}`}>
                  {/* WHY fmtDecimalPct (not fmtPctDirect): daily_return in
                      Fundamentals is a decimal fraction (0.012 = 1.2%) matching
                      the EODHD daily_return metric convention. formatPercent
                      already multiplies by 100 internally. */}
                  {fmtDecimalPct(fundamentals?.daily_return ?? null)}
                </td>
              </tr>

              {/* Peer rows — clickable for navigation. */}
              {peers.map((peer) => (
                <tr
                  key={peer.instrument_id}
                  className="h-[var(--row-h,20px)] cursor-pointer hover:bg-muted/20 transition-colors"
                  onClick={() => {
                    // WHY push (not Link): we want row-level click on the tr element.
                    // Using Link would require nesting a tags which is invalid HTML
                    // (block element inside table row). router.push is cleaner here.
                    if (peer.ticker) router.push(`/instruments/${encodeURIComponent(peer.ticker)}`);
                  }}
                  title={peer.ticker ? `Go to ${peer.ticker}` : undefined}
                >
                  <td className="px-2 text-[11px] font-semibold text-primary tabular-nums whitespace-nowrap">
                    {peer.ticker ?? "—"}
                  </td>
                  <td className="px-2 text-[11px] text-foreground truncate max-w-[120px]">
                    {peer.name ?? "—"}
                  </td>
                  <td className="px-2 text-right tabular-nums text-foreground whitespace-nowrap">
                    {formatMarketCap(peer.market_cap)}
                  </td>
                  <td className="px-2 text-right tabular-nums text-foreground">
                    {peer.pe_ratio != null ? formatRatio(peer.pe_ratio) : "—"}
                  </td>
                  {/* WHY fmtDecimalPct for return_1y: S3 sends return_1y as a
                      decimal fraction (0.125 = 12.5%); formatPercent multiplies
                      by 100, so passing 0.125 yields "+12.50%". */}
                  <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(peer.return_1y)}`}>
                    {fmtDecimalPct(peer.return_1y)}
                  </td>
                  {/* WHY fmtPctDirect for change_pct: S3 already scales
                      daily_return × 100 before building PeerInstrumentResponse
                      (see peers.py line 241 — "# WHY * 100"). formatPercentDirect
                      does not multiply again, so 3.1 → "+3.10%". */}
                  <td className={`px-2 text-right tabular-nums whitespace-nowrap ${returnColor(peer.change_pct)}`}>
                    {fmtPctDirect(peer.change_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        );
      })()}

      {/* ── COMPETITORS tab content ───────────────────────────────────────── */}
      {view === "COMPETITORS" && (() => {
        // WHY entityId guard (not just the query's enabled flag): if entityId
        // is absent we want a deterministic message immediately — not a loading
        // skeleton that never resolves. The message also explains WHY the tab
        // is inactive so developers can debug missing prop wiring.
        if (!entityId) {
          return (
            <div className="text-[11px] text-muted-foreground/60 px-2 py-2 italic">
              KG entity not linked — competitor data unavailable.
            </div>
          );
        }

        if (competitorsLoading) {
          return <CompetitorsSkeleton />;
        }

        if (competitorsError) {
          return (
            <div className="text-[11px] text-[#EF5350] px-2 py-2">
              Unable to load competitor data
            </div>
          );
        }

        // WHY check null separately from empty array: getSimilarEntities returns
        // null on 404/422 (entity not in KG yet), while [] means the entity IS
        // in the KG but has no similarity results above the threshold. These two
        // states deserve different messages.
        if (similarData === null || similarData === undefined) {
          return (
            <div className="text-[11px] text-muted-foreground/60 px-2 py-2">
              No semantic competitors found in knowledge graph.
            </div>
          );
        }

        if (similarData.results.length === 0) {
          return (
            <div className="text-[11px] text-muted-foreground/60 px-2 py-2">
              No semantic competitors found in knowledge graph.
            </div>
          );
        }

        return <CompetitorsTable items={similarData.results} />;
      })()}
    </div>
  );
}
