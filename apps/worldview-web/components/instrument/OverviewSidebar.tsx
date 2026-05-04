/**
 * components/instrument/OverviewSidebar.tsx — Overview tab right sidebar (5 zones)
 *
 * WHY THIS EXISTS (PLAN-0053 Wave E T-E-5-01 + T-E-5-02): the Overview tab's
 * right column was previously just KEY METRICS + 2 sparkline panels. The redesign
 * adds two contextual zones (Overview Summary + Competitors + News) above the
 * existing metrics + sparklines so analysts get instant context — current price,
 * 52W range, 3 critical badges, peer comparison, and top headlines — without
 * navigating away from the Overview tab.
 *
 * Layout (top to bottom in the 280px column):
 *   ┌───────────────────────────────┐
 *   │ 1. Overview Summary  ~90px    │  Price · 52W bar · MktCap/PE/Yield badges
 *   ├───────────────────────────────┤
 *   │ 2. Competitors       ~120px   │  Collapsible — top 4 peers + ratios
 *   ├───────────────────────────────┤
 *   │ 3. Top News          ~140px   │  Collapsible — top 3-5 headlines
 *   ├───────────────────────────────┤
 *   │ 4. Key Metrics       scroll   │  Existing 12-row metric panel
 *   ├───────────────────────────────┤
 *   │ 5. Sparklines        2 panels │  Existing trend selectors
 *   └───────────────────────────────┘
 *
 * WHY zones 2 + 3 collapsible (not 1, 4, 5): the Overview Summary is the most
 * compact zone — collapsing it would defeat the redesign's purpose. Key Metrics
 * + Sparklines are the existing scroll content the analyst always wants visible.
 * Competitors + News are contextual — power users may want to hide them after
 * a first scan to focus on metrics.
 *
 * WHY EACH ZONE OWNS ITS OWN LOADING / EMPTY STATE: the sidebar is composed of
 * four data-fetching surfaces (snapshot, fundamentals, peers, news). A single
 * top-level skeleton would block visual feedback for zones that resolve faster
 * than the slowest. Per-zone skeletons honour BP-291: NEVER use `h-full` inside
 * skeleton items inside `min-h-*` parents — let the skeleton stack at natural
 * height so the zone occupies only the space it needs.
 *
 * WHO USES IT: OverviewLayout (right column)
 * DATA SOURCES:
 *   - Zone 1: props (currentPrice, fundamentals.market_cap/pe_ratio/dividend_yield)
 *   - Zone 2: getEntityGraph (depth=1, COMPETES_WITH edges) + runScreener
 *   - Zone 3: getEntityNews (limit=5)
 *   - Zone 4 / 5: passed-through children
 * DESIGN REFERENCE: PLAN-0053 §Wave E T-E-5-02
 */

"use client";
// WHY "use client": uses useQuery + useState; child collapsibles are interactive.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { WeekRangeBar } from "@/components/instrument/52WeekRangeBar";
import {
  formatMarketCap,
  formatRatio,
  formatPercent,
  priceChangeClass,
  formatRelativeTime,
} from "@/lib/utils";
import type {
  Fundamentals,
  Instrument,
  ScreenerResult,
  RankedArticle,
} from "@/types/api";

// ── Sentiment pill helpers (mirrors NewsTab Wave E config) ────────────────────
// WHY duplicated (not imported): NewsTab's SENTIMENT_CONFIG includes a `bgClass`
// for the full-width news rows. The sidebar wants the same colours but on a
// compact 22px row, so we keep this local map small (text only). Import would
// require widening the NewsTab module's public surface.
const SENT_TEXT: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-muted-foreground",
  mixed: "text-warning",
};

const SENT_LABEL: Record<string, string> = {
  positive: "+",
  negative: "−",
  neutral: "•",
  mixed: "~",
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewSidebarProps {
  /** Instrument primary key — used by the snapshot/screener/sparkline fetches. */
  instrumentId: string;
  /** Entity ID (KG) — used for graph + entity news lookups. */
  entityId: string;
  /** Pre-fetched core fundamentals (passed through to the metrics panel + summary). */
  fundamentals: Fundamentals | null;
  /** Instrument metadata — gives sector fallback for peers + sector row in metrics. */
  instrument: Instrument | null;
  /** Live current price — feeds the 52W range bar marker in zone 1 + 4. */
  currentPrice: number | null;
  /** Top section + sparkline panel children rendered below the new zones. */
  metricsAndSparklines: React.ReactNode;
  /** Callback to switch parent tab to News (used by zone 3 "More news →"). */
  onViewAllNews: () => void;
}

// ── Zone 1: Overview Summary ─────────────────────────────────────────────────

/**
 * OverviewSummaryZone — current price + 52W range + 3 critical badges
 *
 * WHY 90px tall (not 60px or 120px): 90px gives us 3 stacked rows at terminal
 * density (price 28px / range bar 32px / badges 22px) with 8px breathing room.
 * 60px would crowd the price next to the bar; 120px would push critical zones
 * (peers / news) below the fold on shorter viewports.
 *
 * WHY BADGES (not full MetricRows): MktCap / P/E / Yield are repeated in zone 4
 * for completeness — but zone 1 promotes them as "headline" stats so analysts
 * see them in <1 second without scrolling. Compact pills avoid duplication
 * fatigue while still anchoring the sidebar visually.
 */
function OverviewSummaryZone({
  fundamentals,
  currentPrice,
}: {
  fundamentals: Fundamentals | null;
  currentPrice: number | null;
}) {
  const isLoading = !fundamentals && currentPrice == null;
  const isEmpty = fundamentals == null && currentPrice == null;

  // WHY render skeleton at the same compact heights as the real content:
  // matching skeleton dimensions to final layout prevents reflow when the data
  // resolves. BP-291: NO h-full — each Skeleton has an explicit height class.
  if (isLoading) {
    return (
      <div className="border-b border-border px-2 py-1.5 space-y-1">
        <Skeleton className="h-4 w-20" /> {/* price line */}
        <Skeleton className="h-3 w-full" /> {/* range bar */}
        <div className="flex gap-1">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 flex-1" />
        </div>
      </div>
    );
  }

  // WHY explicit empty state (vs blank zone): if fundamentals never load (e.g.
  // an ETF without coverage), we still show a small "—" row so the zone has a
  // visible footprint and the analyst knows the data is missing, not loading.
  if (isEmpty) {
    return (
      <div className="border-b border-border px-2 py-1.5 text-[10px] text-muted-foreground">
        Overview unavailable
      </div>
    );
  }

  const dailyReturn = fundamentals?.daily_return ?? null;
  const peClass = (() => {
    const pe = fundamentals?.pe_ratio;
    if (pe == null) return "text-muted-foreground";
    if (pe > 35) return "text-negative";
    if (pe < 20) return "text-positive";
    return "text-warning";
  })();

  return (
    <div className="border-b border-border px-2 py-1.5">
      {/* ── Row 1: current price + daily return ──────────────────────────── */}
      <div className="flex items-baseline gap-2 mb-1">
        <span className="font-mono text-[14px] tabular-nums font-semibold text-foreground">
          {currentPrice != null ? `$${currentPrice.toFixed(2)}` : "—"}
        </span>
        {dailyReturn != null && (
          <span
            className={`font-mono text-[10px] tabular-nums ${priceChangeClass(dailyReturn)}`}
          >
            {dailyReturn >= 0 ? "▲" : "▼"} {formatPercent(dailyReturn)}
          </span>
        )}
      </div>

      {/* ── Row 2: 52W range bar (no labels — compact) ───────────────────── */}
      {/* WHY no labels: the same bar appears with labels in zone 4. The summary
          version is purely a position indicator — analyst already sees the price
          number above. */}
      <div className="mb-1.5">
        <WeekRangeBar
          low={fundamentals?.week_52_low ?? null}
          high={fundamentals?.week_52_high ?? null}
          current={currentPrice ?? null}
          showLabels={false}
        />
      </div>

      {/* ── Row 3: 3 critical badges ─────────────────────────────────────── */}
      <div className="flex items-center gap-1">
        <SummaryBadge label="MCAP" value={formatMarketCap(fundamentals?.market_cap ?? null)} />
        <SummaryBadge
          label="P/E"
          value={formatRatio(fundamentals?.pe_ratio ?? null)}
          valueClass={peClass}
        />
        <SummaryBadge
          label="YLD"
          value={formatPercent(fundamentals?.dividend_yield ?? null)}
          valueClass={
            (fundamentals?.dividend_yield ?? 0) > 0.03
              ? "text-positive"
              : "text-foreground"
          }
        />
      </div>
    </div>
  );
}

/** SummaryBadge — compact label/value pill used in zone 1's badge row. */
function SummaryBadge({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    // WHY flex-1: 3 badges share the row width evenly; analyst gets consistent
    // spacing regardless of value length ("$3.5T" vs "—").
    <div className="flex-1 flex flex-col rounded-[2px] bg-muted/30 px-1 py-0.5 min-w-0">
      <span className="text-[8px] uppercase tracking-[0.06em] text-muted-foreground/70 leading-none">
        {label}
      </span>
      <span className={`font-mono text-[10px] tabular-nums truncate ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Zone 2: Competitors ──────────────────────────────────────────────────────

/**
 * CompetitorsZone — collapsible peer comparison (3-5 peers).
 *
 * WHY rebuild here (not reuse PeerComparisonPanel directly): PeerComparisonPanel
 * is sized for the Fundamentals tab's 280px sidebar with a 4-column row (TKR /
 * P/E / MCAP / RET). The Overview sidebar wants a more compact 3-column layout
 * (TKR / P/E / Δ%) so 5 peers fit in the 120px zone. Sharing the data-fetch
 * pattern (graph → screener fallback by sector) but a leaner row layout.
 *
 * BACKEND NOTE: no getCompetitors(instrumentId) endpoint exists on S9.
 * We reuse the PeerComparisonPanel pattern:
 *   1. getEntityGraph(entityId, depth=1) → COMPETES_WITH edges → entity_ids
 *   2. runScreener({entity_id IN [...]}) → batch P/E + market cap + return
 *   3. Sector fallback if no COMPETES_WITH edges exist
 */
function CompetitorsZone({
  entityId,
  instrument,
}: {
  entityId: string;
  instrument: Instrument | null;
}) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);
  const [open, setOpen] = useState(true);

  // ── Graph → competitor IDs ────────────────────────────────────────────────
  // WHY staleTime 600_000 (10min): KG edges change rarely; aggressive caching
  // saves repeat fetches when the analyst flips between tabs.
  const { data: graph, isLoading: graphLoading } = useQuery({
    queryKey: ["entity-graph", entityId, 1],
    queryFn: () => gateway.getEntityGraph(entityId, 1),
    enabled: !!accessToken && !!entityId,
    staleTime: 600_000,
  });

  // WHY both source + target: COMPETES_WITH edges can be either direction.
  // WHY slice(0, 4): the zone has room for the current ticker + ~4 peer rows.
  const competitorIds: string[] = (graph?.edges ?? [])
    .filter((e) => e.label === "COMPETES_WITH")
    .map((e) => (e.source === entityId ? e.target : e.source))
    .filter((id) => id !== entityId)
    .slice(0, 4);

  // ── Screener for competitor metrics ───────────────────────────────────────
  const { data: peerData, isLoading: peersLoading } = useQuery({
    queryKey: ["overview-peers", competitorIds.join(",")],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          {
            field: "entity_id",
            operator: "in",
            value: competitorIds,
          },
        ],
        sort_by: "market_capitalization",
        sort_dir: "desc",
        limit: 4,
      }),
    enabled: !!accessToken && competitorIds.length > 0 && !graphLoading,
    staleTime: 300_000,
  });

  // ── Sector fallback ───────────────────────────────────────────────────────
  // WHY sector fallback: thin/new tickers may have no COMPETES_WITH edges.
  const hasGraphPeers = (peerData?.results?.length ?? 0) > 0;
  const { data: sectorData, isLoading: sectorLoading } = useQuery({
    queryKey: ["overview-sector-peers", instrument?.gics_sector],
    queryFn: () =>
      gateway.runScreener({
        filters: [
          {
            field: "gics_sector",
            operator: "eq",
            value: instrument?.gics_sector ?? "",
          },
          {
            field: "entity_id",
            operator: "neq",
            value: entityId,
          },
        ],
        sort_by: "market_cap",
        sort_dir: "desc",
        limit: 4,
      }),
    enabled:
      !!accessToken &&
      !!instrument?.gics_sector &&
      !graphLoading &&
      !peersLoading &&
      !hasGraphPeers,
    staleTime: 300_000,
  });

  const peers: ScreenerResult[] = hasGraphPeers
    ? (peerData?.results ?? [])
    : (sectorData?.results ?? []);
  const isLoading = graphLoading || peersLoading || sectorLoading;
  const dataSource = hasGraphPeers ? "KG" : instrument?.gics_sector ? "sector" : "";

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b border-border">
      {/* ── Trigger row (always visible) ─────────────────────────────────── */}
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center h-6 px-2 hover:bg-muted/40 transition-colors"
          aria-label={open ? "Collapse competitors" : "Expand competitors"}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 text-muted-foreground mr-1 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground mr-1 shrink-0" />
          )}
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            COMPETITORS
          </span>
          {dataSource && (
            <span className="ml-auto text-[9px] font-mono text-muted-foreground/60">
              {dataSource}
            </span>
          )}
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        {/* ── Column headers (compact 3-col: TKR / P/E / Δ%) ────────────── */}
        <div className="flex items-center h-[18px] px-2 border-b border-border/30">
          <span className="text-[9px] uppercase font-mono text-muted-foreground/60 w-12 flex-none">
            TKR
          </span>
          <span className="text-[9px] uppercase font-mono text-muted-foreground/60 flex-1 text-right">
            P/E
          </span>
          <span className="text-[9px] uppercase font-mono text-muted-foreground/60 w-12 text-right">
            Δ%
          </span>
        </div>

        {/* ── Loading state ──────────────────────────────────────────────── */}
        {isLoading && (
          <div>
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="flex items-center h-[22px] px-2 gap-2 border-b border-border/30 last:border-0"
              >
                <Skeleton className="h-3 w-10 flex-none" />
                <Skeleton className="h-3 flex-1" />
                <Skeleton className="h-3 w-10" />
              </div>
            ))}
          </div>
        )}

        {/* ── Empty state ────────────────────────────────────────────────── */}
        {!isLoading && peers.length === 0 && (
          <div className="px-2 py-1.5 text-[10px] text-muted-foreground">
            No peer data
          </div>
        )}

        {/* ── Peer rows ──────────────────────────────────────────────────── */}
        {!isLoading &&
          peers.map((peer) => (
            <div
              key={peer.instrument_id}
              className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0"
            >
              <span className="font-mono text-[11px] text-muted-foreground w-12 flex-none truncate">
                {peer.ticker}
              </span>
              <span className="font-mono text-[11px] tabular-nums flex-1 text-right text-foreground">
                {formatRatio(peer.pe_ratio ?? null)}
              </span>
              <span
                className={`font-mono text-[10px] tabular-nums w-12 text-right ${priceChangeClass(peer.daily_return ?? null)}`}
              >
                {peer.daily_return != null ? formatPercent(peer.daily_return) : "—"}
              </span>
            </div>
          ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

// ── Zone 3: News ─────────────────────────────────────────────────────────────

/**
 * NewsZone — collapsible top-5 entity news with sentiment pill + relative time.
 *
 * WHY rebuild here (not reuse InstrumentTopNews): InstrumentTopNews is wired
 * to render in the lower 50/50 grid with a routing-tier badge layout. This
 * sidebar variant uses a sentiment pill (more useful for a quick scan) and
 * tighter row height.
 */
function NewsZone({
  entityId,
  onViewAllNews,
}: {
  entityId: string;
  onViewAllNews: () => void;
}) {
  const { accessToken } = useAuth();
  const [open, setOpen] = useState(true);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["overview-sidebar-news", entityId],
    queryFn: () =>
      createGateway(accessToken).getEntityNews(entityId, {
        limit: 5,
        offset: 0,
        order_by: "display_relevance_score",
      }),
    staleTime: 60_000,
    enabled: !!accessToken && !!entityId,
  });

  const articles: RankedArticle[] = data?.articles ?? [];

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-b border-border">
      {/* ── Trigger row ──────────────────────────────────────────────────── */}
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center h-6 px-2 hover:bg-muted/40 transition-colors"
          aria-label={open ? "Collapse news" : "Expand news"}
        >
          {open ? (
            <ChevronDown className="h-3 w-3 text-muted-foreground mr-1 shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted-foreground mr-1 shrink-0" />
          )}
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            NEWS
          </span>
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent>
        {/* ── Loading state ──────────────────────────────────────────────── */}
        {isLoading && (
          <div>
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="flex items-center h-[22px] px-2 gap-1.5 border-b border-border/30 last:border-0"
              >
                <Skeleton className="h-3 w-3 shrink-0" />
                <Skeleton className="h-3 flex-1" />
                <Skeleton className="h-3 w-10 shrink-0" />
              </div>
            ))}
          </div>
        )}

        {/* ── Error state ────────────────────────────────────────────────── */}
        {isError && !isLoading && (
          <div className="px-2 py-1.5 text-[10px] text-muted-foreground">
            News unavailable
          </div>
        )}

        {/* ── Empty state ────────────────────────────────────────────────── */}
        {!isLoading && !isError && articles.length === 0 && (
          <div className="px-2 py-1.5 text-[10px] text-muted-foreground">
            No recent news
          </div>
        )}

        {/* ── Article rows ───────────────────────────────────────────────── */}
        {!isLoading &&
          !isError &&
          articles.map((article) => {
            const sent = article.sentiment;
            const sentKey = sent ?? "neutral";
            return (
              <div
                key={article.article_id}
                className="flex items-center h-[22px] px-2 gap-1.5 border-b border-border/30 last:border-0 hover:bg-muted/40 cursor-pointer"
                onClick={() => {
                  if (article.url) window.open(article.url, "_blank", "noopener,noreferrer");
                }}
              >
                {/* Sentiment pill — single-character compact form */}
                <span
                  className={`font-mono text-[11px] font-semibold shrink-0 ${SENT_TEXT[sentKey] ?? "text-muted-foreground"}`}
                  aria-label={`sentiment ${sentKey}`}
                >
                  {SENT_LABEL[sentKey] ?? "•"}
                </span>
                {/* Title — 1 line truncated */}
                <span className="text-[11px] text-foreground truncate flex-1">
                  {article.title ?? "Untitled"}
                </span>
                {/* Relative time */}
                <span className="font-mono text-[9px] tabular-nums text-muted-foreground shrink-0">
                  {formatRelativeTime(article.published_at)}
                </span>
              </div>
            );
          })}

        {/* ── More-news footer ───────────────────────────────────────────── */}
        <div className="flex items-center px-2 h-[22px]">
          <button
            type="button"
            onClick={onViewAllNews}
            className="text-[10px] text-primary"
          >
            More news →
          </button>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// ── OverviewSidebar (orchestrator) ────────────────────────────────────────────

export function OverviewSidebar({
  instrumentId,
  entityId,
  fundamentals,
  instrument,
  currentPrice,
  metricsAndSparklines,
  onViewAllNews,
}: OverviewSidebarProps) {
  // WHY void instrumentId: listed explicitly to keep the API symmetrical with the
  // OverviewLayout call site; the metrics panel receives it via the metricsAndSparklines slot.
  void instrumentId;

  return (
    // WHY overflow-y-auto on the outer wrapper: the entire sidebar scrolls as a
    // single unified block. T-F-6-16 (sidebar scroll unification) — neither the
    // collapsible zones nor the metrics panel define their own overflow class.
    <div className="flex flex-col overflow-y-auto">
      {/* Zone 1: Overview Summary */}
      <OverviewSummaryZone fundamentals={fundamentals} currentPrice={currentPrice} />

      {/* Zone 2: Competitors (collapsible) */}
      <CompetitorsZone entityId={entityId} instrument={instrument} />

      {/* Zone 3: News (collapsible) */}
      <NewsZone entityId={entityId} onViewAllNews={onViewAllNews} />

      {/* Zones 4 + 5: existing metrics panel + sparkline panels (passed through) */}
      {/* WHY a slot prop (not local children): the parent OverviewLayout already
          owns the metric-selector state for the two sparkline panels. Hoisting
          that state into this sidebar would require duplicating the SPARKLINE_METRICS
          constant and the dual-state useState calls. Slot keeps state ownership
          clean — sidebar is layout-only for zones 4+5. */}
      {metricsAndSparklines}
    </div>
  );
}
