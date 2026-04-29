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
import { NewsTab } from "@/components/instrument/NewsTab";
import { CompactInstrumentHeader } from "@/components/instrument/CompactInstrumentHeader";
import { InstrumentAISubheader } from "@/components/instrument/InstrumentAISubheader";
import { OverviewLayout } from "@/components/instrument/OverviewLayout";

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  // WHY decodeURIComponent: entity_id from URL may be percent-encoded
  const entityId = decodeURIComponent(params.entityId as string);
  const { accessToken } = useAuth();
  // ── Controlled tab state ───────────────────────────────────────────────────
  // WHY controlled Tabs (not defaultValue): OverviewLayout's "More news" button
  // needs to programmatically switch to the News tab. Controlled Tabs allow this.
  const [activeTab, setActiveTab] = useState("overview");

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

  const instrument = overview?.instrument;

  // WHY kgEntityId derived before guards and queries: The URL segment (`entityId`) may
  // be a market-data instrument_id (dashboard/search navigate with instrument_id).
  // The S9 overview endpoint accepts both, but KG/news/briefing endpoints require the
  // authoritative KG entity_id. We derive it early so the news query also uses the
  // correct ID. Initially falls back to entityId (URL param) until overview loads.
  // ADR-F-12: entity_id ≠ instrument_id; all KG endpoints require entity_id.
  const kgEntityId = instrument?.entity_id ?? entityId;

  // WHY news fetch moved to NewsTab: PLAN-0050 Wave E extracted all news tab
  // logic into components/instrument/NewsTab.tsx. The page no longer owns the
  // news query or filter state — NewsTab handles fetching, filtering, and rendering.

  // ── Page loading state ─────────────────────────────────────────────────────
  // T-F-6-12: Skeleton expanded to match the 9-section instrument page layout.
  // WHY 9 sections: FundamentalsTab has 9 sections (Valuation, Profitability,
  // Growth, Dividends, Balance Sheet, 52-Week Range, Debt & Credit, Cash Flow
  // + the full-width Analyst Consensus strip above the grid). The skeleton
  // must visually match the loaded layout so there's no jarring reflow.
  if (overviewLoading && !overview) {
    return (
      // WHY p-3: standard terminal panel padding (12px) applied consistently
      // across all pages — avoids the default browser spacing resetting on load.
      <div className="space-y-3 p-3">
        {/* Section 1 (implicit): Compact instrument header — 56px / 2×28px */}
        {/* WHY h-6 + h-10: represents the two-row CompactInstrumentHeader:
            top row (back button + ticker) and bottom row (name + price strip). */}
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-10 w-72" />

        {/* Section 2 (implicit): AI Subheader strip — single collapsed row */}
        <Skeleton className="h-5 w-full" />

        {/* Section 3 (implicit): Tab navigation row */}
        <Skeleton className="h-7 w-64" />

        {/* Section 4: OHLCVChart — the primary price chart fills most of the viewport */}
        {/* WHY h-[280px]: matches OHLCVChart CHART_HEIGHT constant defined in Wave C-2.
            Using the exact same height prevents a height jump when the chart mounts. */}
        <Skeleton className="h-[280px] w-full" />

        {/* Sections 5–9: Fundamentals grid — 5 rows of 2-column section skeletons.
            WHY grid grid-cols-2 gap-2: mirrors the actual FundamentalsTab layout
            (grid-cols-2 on ≤lg, grid-cols-3 on ≥lg). The skeleton uses 2-col to
            represent the minimum: Valuation + Profitability, Growth + Dividends,
            Balance Sheet + 52-Week Range, Debt & Credit + Cash Flow, and the
            full-width Analyst Consensus strip. */}
        <div className="grid grid-cols-2 gap-2">
          {/* Section 5: Valuation */}
          <Skeleton className="h-[88px] w-full" />
          {/* Section 6: Profitability */}
          <Skeleton className="h-[88px] w-full" />
          {/* Section 7: Growth (YoY) */}
          <Skeleton className="h-[66px] w-full" />
          {/* Section 8: Dividends */}
          <Skeleton className="h-[66px] w-full" />
          {/* Section 9: Balance Sheet — spans both columns for the 52-Week Range bar */}
          <Skeleton className="col-span-2 h-[44px] w-full" />
        </div>
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
        dividendYield={fund?.dividend_yield ?? null}
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
      <InstrumentAISubheader entityId={kgEntityId} />

      {/* ── Tab navigation (controlled) ────────────────────────────────────── */}
      {/* WHY value + onValueChange (not defaultValue): OverviewLayout's "More news"
          button programmatically switches to the "news" tab. Uncontrolled Tabs
          (defaultValue) cannot be changed imperatively from a child component. */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0 rounded-none border-b border-border/40 bg-transparent px-4">
          {/* WHY compact tabs: bloomberg-style — tabs are small, content area is large */}
          <TabsTrigger value="overview" className="text-xs">Overview</TabsTrigger>
          <TabsTrigger value="fundamentals" className="text-xs">Fundamentals</TabsTrigger>
          {/* WHY no count badge: PLAN-0050 — NewsTab manages its own data fetch.
              The article count is shown in the NewsTab filter toolbar. */}
          <TabsTrigger value="news" className="text-xs">News</TabsTrigger>
          <TabsTrigger value="intelligence" className="text-xs">Intelligence</TabsTrigger>
        </TabsList>

        {/* ── Overview tab ─────────────────────────────────────────────────── */}
        {/* WHY OverviewLayout (was ad-hoc 2-column grid): Wave 5 introduces the
            5-zone overview layout: chart + session strip + 3-column lower grid.
            This is a structured, reusable composition vs the previous one-off grid. */}
        <TabsContent value="overview" className="mt-0 flex-1 overflow-auto">
          <OverviewLayout
            instrumentId={instrument.instrument_id}
            entityId={kgEntityId}
            centerLabel={instrument.ticker}
            initialBars={overview?.ohlcv?.bars}
            fundamentals={fund ?? null}
            instrument={instrument}
            currentPrice={overview?.quote?.price ?? null}
            onViewAllNews={() => setActiveTab("news")}
          />
        </TabsContent>

        {/* ── Fundamentals tab ─────────────────────────────────────────────── */}
        <TabsContent value="fundamentals" className="mt-0 flex-1 overflow-auto">
          <FundamentalsTab
            instrumentId={instrument.instrument_id}
            initialData={overview?.fundamentals}
            currentPrice={overview?.quote?.price ?? null}
            entityId={kgEntityId}
            instrument={instrument}
            onViewAllNews={() => setActiveTab("news")}
          />
        </TabsContent>

        {/* ── News tab ─────────────────────────────────────────────────────── */}
        {/* WHY NewsTab component (was inline JSX): PLAN-0050 Wave E extracts all
            news tab logic into a dedicated component with sentiment/impact pills,
            time-grouping, source filter, and sort. The page now only handles
            tab routing; NewsTab owns data fetching, filtering, and rendering. */}
        <TabsContent value="news" className="mt-0 flex-1 overflow-auto">
          <NewsTab entityId={kgEntityId} />
        </TabsContent>

        {/* ── Intelligence tab ─────────────────────────────────────────────── */}
        <TabsContent value="intelligence" className="mt-0 flex-1 overflow-auto">
          <IntelligenceTab entityId={kgEntityId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
