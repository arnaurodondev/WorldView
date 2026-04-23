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
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, TrendingUp } from "lucide-react";
import Link from "next/link";
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
import { ArticleCard } from "@/components/news/ArticleCard";
import { formatMarketCap, formatPercentDirect } from "@/lib/utils";

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetailPage() {
  const params = useParams();
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
      <div className="space-y-4 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-[280px] w-full" />
      </div>
    );
  }

  // ── Not found state ────────────────────────────────────────────────────────
  if (!instrument) {
    return (
      <div className="flex flex-col items-center gap-4 p-12 text-center">
        <TrendingUp className="h-10 w-10 text-muted-foreground/30" />
        <p className="text-sm text-muted-foreground">Instrument not found.</p>
        <Link href="/dashboard" className="text-xs text-primary hover:underline">
          ← Back to dashboard
        </Link>
      </div>
    );
  }

  const fund = overview?.fundamentals;

  return (
    <div className="flex min-h-0 flex-col">
      {/* ── Back nav ─────────────────────────────────────────────────────── */}
      <div className="border-b border-border/40 px-4 py-2">
        <Link
          href="/dashboard"
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" />
          Dashboard
        </Link>
      </div>

      {/* ── Instrument header ─────────────────────────────────────────────── */}
      <div className="border-b border-border/40 px-4 py-4">
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
          <div className="mt-3 flex flex-wrap gap-4">
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
            <div className="border-b border-border/40 p-4 lg:border-b-0 lg:border-r">
              <h2 className="mb-2 text-xs font-semibold text-muted-foreground">
                Price Chart
              </h2>
              <OHLCVChart
                instrumentId={instrument.instrument_id}
                initialBars={overview?.ohlcv?.bars}
              />
            </div>

            {/* Right: entity graph */}
            <div className="p-4">
              <h2 className="mb-2 text-xs font-semibold text-muted-foreground">
                Related Entities
              </h2>
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
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="p-4">
                  <Skeleton className="mb-2 h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))
            ) : newsResp?.articles.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">
                No news articles found for this entity.
              </p>
            ) : (
              <>
                {newsResp?.articles.map((article) => (
                  <div key={article.article_id} className="px-4 py-3">
                    <ArticleCard article={article} />
                  </div>
                ))}

                {/* Pagination: load more */}
                {/* WHY 20: RankedNewsResponse has no .limit field (unlike NewsResponse).
                    Use the same hardcoded limit passed to getEntityNews above. */}
                {newsResp && newsOffset + 20 < newsResp.total && (
                  <div className="p-4 text-center">
                    <button
                      onClick={() => setNewsOffset((o) => o + 20)}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      Load more articles
                    </button>
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
