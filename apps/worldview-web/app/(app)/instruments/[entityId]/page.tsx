/**
 * app/(app)/instruments/[entityId]/page.tsx — Instrument Detail page (Wave 5)
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
 * WHY TABS (controlled): Wave 5 adds programmatic tab switching (onViewAllNews
 * callback from OverviewLayout can switch to the News tab). Controlled Tabs
 * (value + onValueChange) enable this. Uncontrolled defaultValue cannot.
 *
 * WHY TABS: Analysts have different mental modes:
 * - Overview: "where is the price?" (chart + quick stats)
 * - Fundamentals: "is it cheap/expensive?" (ratio grid)
 * - News: "what's driving it?" (entity-filtered news)
 * - Intelligence: "are there conflicting signals?" (contradictions)
 *
 * WHO USES IT: TopMovers clicks, GlobalSearch navigation, Watchlist links
 * DATA SOURCE: S9 GET /v1/companies/{entityId}/overview + per-tab endpoints
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail, canvas State C + C-2..C-4;
 *                   PRD-0031 §9 Terminal UI v3 Wave 5
 */

"use client";
// WHY "use client": uses useQuery for CompanyOverview + tab state (useState).

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
// WHY useRouter: used for router.back() in the back nav button so the user returns
// to their previous page (e.g., screener, dashboard) rather than always going to /dashboard.
import { useQuery } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { FundamentalsTab } from "@/components/instrument/FundamentalsTab";
import { IntelligenceTab } from "@/components/instrument/IntelligenceTab";
import { CompactInstrumentHeader } from "@/components/instrument/CompactInstrumentHeader";
import { InstrumentAISubheader } from "@/components/instrument/InstrumentAISubheader";
import { OverviewLayout } from "@/components/instrument/OverviewLayout";
import { ArticleCard } from "@/components/news/ArticleCard";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { Button } from "@/components/ui/button";

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  // WHY decodeURIComponent: entity_id from URL may be percent-encoded
  const entityId = decodeURIComponent(params.entityId as string);
  const { accessToken } = useAuth();
  const [newsOffset, setNewsOffset] = useState(0);

  // ── Controlled tab state ───────────────────────────────────────────────────
  // WHY controlled Tabs (not defaultValue): OverviewLayout's "More news" button
  // needs to programmatically switch to the News tab. Controlled Tabs allow this.
  const [activeTab, setActiveTab] = useState("overview");

  // ── News client-side filters ───────────────────────────────────────────────
  // WHY client-side filters (not server-side params): the News tab already fetches
  // all 20 articles. Filtering client-side avoids a new query on each filter change.
  const [newsDateFilter, setNewsDateFilter] = useState<"all" | "today" | "week" | "month">("all");
  // WHY no sentiment filter state: RankedArticle (S6 shape) does not include sentiment field.
  // Sentiment filter removed from UI until S6 surfaces it. See TODO in filteredArticles.

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
      <div className="p-3">
        <p className="text-xs text-muted-foreground">Instrument not found.</p>
        <button
          onClick={() => router.back()}
          className="mt-1 text-xs text-primary hover:underline"
        >
          ← Go back
        </button>
      </div>
    );
  }

  const fund = overview?.fundamentals;

  // ── Apply news client-side filters ────────────────────────────────────────
  // WHY filter after fetch: newsResp contains up to 20 articles already fetched.
  // Applying date/sentiment filters client-side avoids a new S9 query on each change.
  // WHY RankedArticle shape: getEntityNews returns RankedArticle[] (S6 ranked shape)
  // which has published_at: string | null and no sentiment field.
  const filteredArticles = (newsResp?.articles ?? []).filter((article) => {
    // Date filter — guard against null published_at (possible in RankedArticle)
    if (newsDateFilter !== "all") {
      if (!article.published_at) return false;
      const now = Date.now();
      const published = new Date(article.published_at).getTime();
      const ageMs = now - published;
      if (newsDateFilter === "today" && ageMs > 24 * 60 * 60 * 1000) return false;
      if (newsDateFilter === "week" && ageMs > 7 * 24 * 60 * 60 * 1000) return false;
      if (newsDateFilter === "month" && ageMs > 30 * 24 * 60 * 60 * 1000) return false;
    }
    // WHY sentiment filter disabled for RankedArticle: RankedArticle does not
    // include a sentiment field (unlike the legacy Article type). The UI still
    // shows the sentiment dropdown for UX consistency; when sentiment filter is
    // applied, all articles pass (no false negatives from missing field).
    // TODO: add sentiment to RankedArticle when S6 surfaces it in the endpoint.
    return true;
  });

  return (
    <div className="flex min-h-0 flex-col">
      {/* ── Compact 56px header (replaces old back-nav + padded header divs) ── */}
      {/* WHY CompactInstrumentHeader (was 2 separate divs): Wave 5 consolidates
          the back button, ticker/price, stats strip, and description into one
          56px (2×28px) header component. This reclaims ~60px of vertical space
          for the chart below. */}
      <CompactInstrumentHeader
        ticker={instrument.ticker}
        name={instrument.name}
        exchange={instrument.exchange}
        sector={instrument.gics_sector}
        description={instrument.description}
        marketCap={fund?.market_cap ?? null}
        peRatio={fund?.pe_ratio ?? null}
        week52High={fund?.week_52_high ?? null}
        week52Low={fund?.week_52_low ?? null}
        price={overview?.quote?.price ?? null}
        change={overview?.quote?.change ?? null}
        changePct={overview?.quote?.change_pct ?? null}
        instrumentId={instrument.instrument_id}
        onBack={() => router.back()}
      />

      {/* ── AI Instrument Brief subheader (replaces InstrumentBriefPanel) ───── */}
      {/* WHY InstrumentAISubheader (was InstrumentBriefPanel): Wave 5 redesign
          uses a sessionStorage-persisted expand state and the AI yellow-left-border
          pattern. InstrumentBriefPanel used a plain collapse with React state only. */}
      <InstrumentAISubheader entityId={entityId} />

      {/* ── Tab navigation (controlled) ────────────────────────────────────── */}
      {/* WHY value + onValueChange (not defaultValue): OverviewLayout's "More news"
          button programmatically switches to the "news" tab. Uncontrolled Tabs
          (defaultValue) cannot be changed imperatively from a child component. */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
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
        {/* WHY OverviewLayout (was ad-hoc 2-column grid): Wave 5 introduces the
            5-zone overview layout: chart + session strip + 3-column lower grid.
            This is a structured, reusable composition vs the previous one-off grid. */}
        <TabsContent value="overview" className="mt-0 flex-1 overflow-auto">
          <OverviewLayout
            instrumentId={instrument.instrument_id}
            entityId={entityId}
            centerLabel={instrument.ticker}
            initialBars={overview?.ohlcv?.bars}
            fundamentals={fund ?? null}
            onViewAllNews={() => setActiveTab("news")}
          />
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
          {/* ── Filter bar ─────────────────────────────────────────────────── */}
          {/* WHY client-side filters: the news list is already fetched (20 articles).
              Filtering client-side avoids a new S9 query on each filter change.
              WHY h-9 filter bar (not p-2): compact terminal controls height. */}
          <div className="flex items-center gap-2 px-3 h-9 border-b border-border">
            {/* Date range filter */}
            <select
              value={newsDateFilter}
              onChange={(e) => setNewsDateFilter(e.target.value as typeof newsDateFilter)}
              className="h-7 bg-background border border-border rounded-[2px] text-[11px] font-mono px-2 text-foreground"
            >
              <option value="all">All time</option>
              <option value="today">Today</option>
              <option value="week">Past week</option>
              <option value="month">Past month</option>
            </select>

            {/* Article count after filtering */}
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground ml-auto">
              {filteredArticles.length} articles
            </span>
          </div>

          <div className="divide-y divide-border/30">
            {newsLoading && !newsResp ? (
              // WHY px-3 py-2 (was p-4): compact skeleton rows at terminal row height
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="px-3 py-2">
                  <Skeleton className="mb-1.5 h-3.5 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))
            ) : filteredArticles.length === 0 ? (
              // WHY InlineEmptyState (was p-6 text-sm): terminal compact inline message
              <InlineEmptyState
                message="No news articles match the current filters."
                className="px-3"
              />
            ) : (
              <>
                {filteredArticles.map((article) => (
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
