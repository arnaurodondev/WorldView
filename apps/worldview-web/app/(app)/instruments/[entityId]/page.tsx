/**
 * app/(app)/instruments/[entityId]/page.tsx — Instrument Detail page
 *
 * WHY THIS EXISTS: The instrument detail page is where analysts spend most of
 * their time — price chart, fundamentals, recent news, and AI intelligence
 * in one place. Bloomberg users open a security's DES page first; this is
 * our equivalent.
 *
 * WHY entityId IN URL (not instrumentId): ADR-F-12 — entity_id is the stable
 * cross-system identifier. instrument_id can change (e.g., on exchange migration)
 * but entity_id is permanent. URLs should use the stable identifier.
 *
 * WHY CompanyOverview FIRST: A single S9 endpoint returns instrument metadata +
 * quote + fundamentals + 30-day OHLCV. Fetching all four in one shot avoids
 * 4 loading waterfalls and gives us initialData for sub-components.
 *
 * WHY TABS: Analysts have different mental modes:
 * - Overview: "where is the price?" (chart + quick stats)
 * - Fundamentals: "is it cheap/expensive?" (ratio grid)
 * - News: "what's driving it?" (entity-filtered news)
 * - Intelligence: "are there conflicting signals?" (contradictions)
 *
 * WHO USES IT: TopMovers clicks, GlobalSearch navigation, Watchlist links
 * DATA SOURCE: S9 GET /v1/companies/{entityId}/overview + per-tab endpoints
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail, canvas State C + C-2..C-4
 */

"use client";
// WHY "use client": uses useQuery for CompanyOverview + tab state (useState).

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
// WHY useRouter: used for router.back() in the back nav button so the user returns
// to their previous page (e.g., screener, dashboard) rather than always going to /dashboard.
import { useQuery } from "@tanstack/react-query";
// WHY ArrowLeft only: TrendingUp removed from not-found state; no longer needed.
import { ArrowLeft } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { LiveQuoteBadge } from "@/components/instrument/LiveQuoteBadge";
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { IntelligenceTab } from "@/components/instrument/IntelligenceTab";
import { InstrumentBriefPanel } from "@/components/instrument/InstrumentBriefPanel";
import { ArticleCard } from "@/components/news/ArticleCard";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { Button } from "@/components/ui/button";
import { formatMarketCap, formatPercentDirect } from "@/lib/utils";

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  // WHY decodeURIComponent: entity_id from URL may be percent-encoded
  const entityId = decodeURIComponent(params.entityId as string);
  const { accessToken } = useAuth();
  const [newsOffset, setNewsOffset] = useState(0);

  // ── Fetch CompanyOverview — composite endpoint ─────────────────────────────
  // WHY pass entityId as instrumentId to getCompanyOverview:
  // MVP: S9 routes /v1/companies/{id}/overview accepts entity_id or instrument_id.
  // The backend resolves either form. Future: dedicated /v1/entities/{id}/overview.
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ["company-overview", entityId],
    queryFn: () => createGateway(accessToken).getCompanyOverview(entityId),
    enabled: !!accessToken && !!entityId,
    // WHY 5min: overview is expensive to compute; price is refreshed via LiveQuoteBadge
    staleTime: 5 * 60_000,
  });

  // ── Fetch entity news for the News tab ────────────────────────────────────
  const { data: newsResp, isLoading: newsLoading } = useQuery({
    queryKey: ["entity-news", entityId, newsOffset],
    queryFn: () =>
      createGateway(accessToken).getEntityNews(entityId, {
        limit: 20,
        offset: newsOffset,
        // WHY display_relevance_score: S6 endpoint accepts "display_relevance_score"
        // or "published_at". The old value "relevance" was a legacy S5 param name.
        order_by: "display_relevance_score",
      }),
    enabled: !!accessToken && !!entityId,
    staleTime: 2 * 60_000,
  });

  const instrument = overview?.instrument;

  // ── Page loading state ─────────────────────────────────────────────────────
  if (overviewLoading && !overview) {
    return (
      // WHY p-3 space-y-3 (was p-6 space-y-4): standard terminal panel padding
      <div className="space-y-3 p-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-10 w-72" />
        {/* WHY h-[360px] (was h-[280px]): matches updated OHLCVChart height */}
        <Skeleton className="h-[360px] w-full" />
      </div>
    );
  }

  // ── Not found state ────────────────────────────────────────────────────────
  if (!instrument) {
    return (
      // WHY p-6 (was p-12): reduced empty state padding per terminal design rules
      <div className="flex flex-col items-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">Instrument not found.</p>
        <button
          onClick={() => router.back()}
          className="text-xs text-primary hover:underline"
        >
          ← Go back
        </button>
      </div>
    );
  }

  const fund = overview?.fundamentals;

  return (
    <div className="flex min-h-0 flex-col">
      {/* ── Back nav ─────────────────────────────────────────────────────── */}
      <div className="border-b border-border/40 px-4 py-2">
        {/* WHY router.back() (was Link href="/dashboard"): takes the user back to
            wherever they came from — screener, dashboard, portfolio — rather than
            always navigating to /dashboard which is disorienting if they arrived
            from the screener. */}
        <button
          onClick={() => router.back()}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          Back
        </button>
      </div>

      {/* ── Instrument header ─────────────────────────────────────────────── */}
      {/* WHY py-2 (was py-4): tighter header preserves vertical space above the fold.
          The instrument header is chrome, not content — it should not dominate. */}
      <div className="border-b border-border/40 px-4 py-2">
        <div className="flex flex-wrap items-start gap-4">
          {/* Left: ticker + name + exchange badge */}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {/* WHY font-mono ticker: finance terminals always use monospace for symbols */}
              <h1 className="font-mono text-xl font-bold tabular-nums text-foreground">
                {instrument.ticker}
              </h1>
              <Badge variant="outline" className="text-[10px] uppercase">
                {instrument.exchange}
              </Badge>
              {instrument.gics_sector && (
                <Badge variant="secondary" className="text-[10px]">
                  {instrument.gics_sector}
                </Badge>
              )}
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">{instrument.name}</p>
            {/* Company description — sourced from EODHD General.Description via S9.
                WHY line-clamp-2: descriptions can be 500+ chars. Two lines is enough
                context without consuming too much header real estate. Traders who want
                more can click to the Intelligence tab's brief. */}
            {instrument.description && (
              <p className="mt-1 line-clamp-2 max-w-prose text-xs leading-relaxed text-muted-foreground/80">
                {instrument.description}
              </p>
            )}
          </div>

          {/* Right: live price badge */}
          <div className="shrink-0">
            <LiveQuoteBadge
              instrumentId={instrument.instrument_id}
              initialPrice={overview?.quote?.price ?? null}
            />
          </div>
        </div>

        {/* Quick stats row — market cap, 52W range, currency */}
        {fund && (
          // WHY gap-2 mt-2 (was gap-4 mt-3): tighter spacing, more data in less space
          <div className="mt-2 flex flex-wrap gap-2">
            {fund.market_cap != null && (
              <div>
                <span className="text-[10px] text-muted-foreground">Mkt Cap</span>
                <span className="ml-2 font-mono text-xs tabular-nums text-foreground">
                  {formatMarketCap(fund.market_cap)}
                </span>
              </div>
            )}
            {fund.week_52_high != null && fund.week_52_low != null && (
              <div>
                <span className="text-[10px] text-muted-foreground">52W</span>
                <span className="ml-2 font-mono text-xs tabular-nums text-foreground">
                  {fund.week_52_low.toFixed(2)} – {fund.week_52_high.toFixed(2)}
                </span>
              </div>
            )}
            {fund.pe_ratio != null && (
              <div>
                <span className="text-[10px] text-muted-foreground">P/E</span>
                <span className="ml-2 font-mono text-xs tabular-nums text-foreground">
                  {fund.pe_ratio.toFixed(1)}
                </span>
              </div>
            )}
            {fund.daily_return != null && (
              <div>
                <span className="text-[10px] text-muted-foreground">1D Ret</span>
                <span
                  className={`ml-2 font-mono text-xs tabular-nums ${fund.daily_return >= 0 ? "text-positive" : "text-negative"}`}
                >
                  {formatPercentDirect(fund.daily_return * 100)}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── AI Instrument Brief — shared across all tabs ─────────────────────── */}
      {/* WHY above the tabs (not inside Intelligence): analysts want a quick AI
          context summary regardless of which tab they're on. Placing it here means
          the brief is always visible without switching tabs (UI-003 fix). */}
      <InstrumentBriefPanel entityId={entityId} />

      {/* ── Tab navigation ─────────────────────────────────────────────────── */}
      <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0 rounded-none border-b border-border/40 bg-transparent px-4">
          {/* WHY compact tabs: bloomberg-style — tabs are small, content area is large */}
          <TabsTrigger value="overview" className="text-xs">Overview</TabsTrigger>
          <TabsTrigger value="fundamentals" className="text-xs">Fundamentals</TabsTrigger>
          <TabsTrigger value="news" className="text-xs">
            News
            {newsResp?.total != null && (
              <span className="ml-1 font-mono tabular-nums text-muted-foreground">
                {newsResp.total}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="intelligence" className="text-xs">Intelligence</TabsTrigger>
        </TabsList>

        {/* ── Overview tab ─────────────────────────────────────────────────── */}
        <TabsContent value="overview" className="mt-0 flex-1 overflow-auto">
          <div className="grid grid-cols-1 gap-0 lg:grid-cols-[1fr_320px]">
            {/* Left: OHLCV chart */}
            {/* WHY p-0 (was p-4): chart fills its container edge-to-edge.
                The chart controls provide their own internal padding.
                WHY no "Price Chart" heading: redundant — the chart IS the price chart.
                Removing the label recovers vertical space without losing information. */}
            <div className="border-b border-border/40 p-0 lg:border-b-0 lg:border-r">
              <OHLCVChart
                instrumentId={instrument.instrument_id}
                initialBars={overview?.ohlcv?.bars}
              />
            </div>

            {/* Right: entity graph */}
            {/* WHY p-2 (was p-4): EntityGraphPanel has its own PanelHeader; outer padding
                of 16px adds unnecessary gap between the panel border and the header strip. */}
            <div className="p-2">
              <EntityGraphPanel
                entityId={entityId}
                centerLabel={instrument.ticker}
              />
            </div>
          </div>
        </TabsContent>

        {/* ── Fundamentals tab ─────────────────────────────────────────────── */}
        <TabsContent value="fundamentals" className="mt-0 flex-1 overflow-auto">
          <FundamentalsTab
            instrumentId={instrument.instrument_id}
            initialData={overview?.fundamentals}
          />
        </TabsContent>

        {/* ── News tab ─────────────────────────────────────────────────────── */}
        <TabsContent value="news" className="mt-0 flex-1 overflow-auto">
          <div className="divide-y divide-border/30">
            {newsLoading && !newsResp ? (
              // WHY px-3 py-2 (was p-4): compact skeleton rows at terminal row height
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="px-3 py-2">
                  <Skeleton className="mb-1.5 h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))
            ) : newsResp?.articles.length === 0 ? (
              // WHY InlineEmptyState (was p-6 text-sm): terminal compact inline message
              <InlineEmptyState
                message="No news articles found for this entity."
                className="px-3"
              />
            ) : (
              <>
                {newsResp?.articles.map((article) => (
                  // WHY px-3 py-2 (was px-4 py-3): tighter outer padding; ArticleCard
                  // already has its own internal p-3 — double-padding wastes space.
                  <div key={article.article_id} className="px-3 py-2">
                    <ArticleCard article={article} />
                  </div>
                ))}

                {/* Pagination: load more */}
                {/* WHY 20: RankedNewsResponse has no .limit field (unlike NewsResponse).
                    Use the same hardcoded limit passed to getEntityNews above. */}
                {newsResp && newsOffset + 20 < newsResp.total && (
                  // WHY Button variant="outline" size="sm" (was plain button):
                  // styled button communicates interactivity more clearly than plain text
                  <div className="px-3 py-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setNewsOffset((o) => o + 20)}
                      className="h-7 text-xs"
                    >
                      Load more articles
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </TabsContent>

        {/* ── Intelligence tab ─────────────────────────────────────────────── */}
        <TabsContent value="intelligence" className="mt-0 flex-1 overflow-auto">
          <IntelligenceTab entityId={entityId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
