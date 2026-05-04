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

import { useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
// WHY useRouter: used for router.back() in the back nav button so the user returns
// to their previous page (e.g., screener, dashboard) rather than always going to /dashboard.
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
// PLAN-0059 W1 (2026-04-30) — Bloomberg-style mnemonic chords on the instrument
// page. When focus is NOT inside an input, single-letter keypresses jump to the
// matching tab: D=DES (Overview), F=FA (Fundamentals), N=CN (News), I=Intel.
// Auto-suspended inside inputs by useChordHotkeys; auto-unregistered when the
// page unmounts. Closes audit F-LAYOUT-001 + supports the symbol-first workflow
// grammar described in the deep-dive layout report §7.2.
import { HotkeyScope } from "@/components/shell/HotkeyScope";

// ── Component ─────────────────────────────────────────────────────────────────

export default function InstrumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  // WHY decodeURIComponent: entity_id from URL may be percent-encoded
  const entityId = decodeURIComponent(params.entityId as string);
  const { accessToken } = useAuth();
  // PLAN-0052 platform-QA round 7 (2026-05-01): the literal slug "undefined"
  // arrived from broken link generators (notably the screener row when a row
  // had no entity_id). Backend page-bundle accepts it and returns 200 with
  // synthetic data, but the page is junk. Redirect to /instruments instead
  // of letting the user stare at a fake instrument page.
  useEffect(() => {
    if (!params.entityId || entityId === "undefined") {
      router.replace("/instruments");
    }
  }, [params.entityId, entityId, router]);
  // ── Controlled tab state ───────────────────────────────────────────────────
  // WHY controlled Tabs (not defaultValue): OverviewLayout's "More news" button
  // needs to programmatically switch to the News tab. Controlled Tabs allow this.
  const [activeTab, setActiveTab] = useState("overview");

  // ── Fetch instrument page-bundle (PLAN-0059 I-5) ───────────────────────────
  // The page-bundle endpoint composes overview + fundamentals + technicals +
  // insider + top-news in one round-trip. We use it as the page-level query;
  // sub-resources are SEEDED into TanStack Query's cache via setQueryData so
  // child-component queries (FundamentalsTab, InsiderTransactionsTable, etc.)
  // hit cache instead of refetching.
  //
  // Backwards-compat: existing children continue using their own queryKeys
  // (["fundamentals", instrumentId], etc.). The seed only PRIMES the cache —
  // children remain authoritative for refetch / staleTime semantics, and any
  // user-driven refresh flows through their own hook.
  const queryClient = useQueryClient();
  const { data: bundle, isLoading: overviewLoading } = useQuery({
    queryKey: ["instrument-page-bundle", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentPageBundle(entityId),
    enabled: !!accessToken && !!entityId,
    // 5min — overview is expensive; LiveQuoteBadge handles intraday refresh.
    staleTime: 5 * 60_000,
  });

  // ── Cache priming — seed child-component query caches (PLAN-0059 I-5) ──────
  // The bundle's sub-resources match the dedicated endpoints' shapes verbatim
  // (per S9 contract). We setQueryData for the keys child components watch so
  // they read from cache on first paint instead of firing a duplicate request.
  //
  // Effect runs once per bundle change; bundle.* are server-trusted values
  // and we never overwrite a fresher cache entry (TanStack Query handles
  // staleness — setQueryData only stamps an `updatedAt` of NOW for the key).
  useEffect(() => {
    if (!bundle) return;
    const md_id = bundle.instrument_id;
    if (bundle.overview) {
      queryClient.setQueryData(["company-overview", entityId], bundle.overview);
    }
    if (bundle.fundamentals) {
      queryClient.setQueryData(["fundamentals", md_id], bundle.fundamentals);
    }
    if (bundle.technicals) {
      queryClient.setQueryData(["technicals", md_id], bundle.technicals);
    }
    if (bundle.insider) {
      queryClient.setQueryData(["insider-transactions", md_id], bundle.insider);
    }
    // QA-iter1: top_news seed REMOVED. The bundle returns 5 articles for
    // a "Top related" widget, but NewsTab paginates with NEWS_PAGE_SIZE=20
    // and reads `total` from the server. Seeding the offset=0 cache key
    // with a 5-article payload would render NewsTab as if the entire first
    // page = 5 articles for ~2min (the staleTime). Instead, NewsTab fires
    // its own /v1/news/entity/{id}?limit=20 query on tab open. The
    // bundle's top_news is still surfaced if/when an "OverviewTopNews"
    // widget consumes it directly (separate cache key, no shape conflict).
  }, [bundle, entityId, queryClient]);

  // overview reference points at the bundle's overview (or null when bundle
  // failed entirely / is still loading). Downstream code reads instrument.*
  // exactly as before — no consumer changes.
  const overview = bundle?.overview ?? null;
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
        <p className="text-[11px] text-muted-foreground">Instrument not found.</p>
        <button
          onClick={() => router.back()}
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-primary"
        >
          <ArrowRight className="h-3 w-3" strokeWidth={1.5} />
          Go back
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

      {/*
       * PLAN-0059 W1 — Bloomberg mnemonic chords on the instrument page.
       * Single-letter keys jump to the matching tab when no input is focused.
       * useChordHotkeys auto-suspends inside <input>/<textarea>/contenteditable
       * so typing a "d" in the AskAi composer (when open) does NOT navigate.
       *
       * D = DES (Description / Overview)   — Bloomberg mnemonic for an issue's
       *                                       description page.
       * F = FA  (Financial Analysis)       — Bloomberg's fundamentals view.
       * N = CN  (Company News)             — Bloomberg's news page.
       * I = Intelligence                   — local extension (Bloomberg has no
       *                                       direct equivalent; we surface AI
       *                                       claims/contradictions here).
       *
       * The bindings are scoped `page` and gated to /instruments/ so they only
       * fire on this route. They do not appear in the cheat sheet on other pages.
       */}
      <InstrumentMnemonicHotkeys onTabChange={setActiveTab} />

      {/* ── Tab navigation (controlled) ────────────────────────────────────── */}
      {/* WHY value + onValueChange (not defaultValue): OverviewLayout's "More news"
          button programmatically switches to the "news" tab. Uncontrolled Tabs
          (defaultValue) cannot be changed imperatively from a child component. */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0 rounded-none border-b border-border/40 bg-transparent px-2">
          {/* WHY compact tabs: bloomberg-style — tabs are small, content area is large */}
          <TabsTrigger value="overview" className="text-[11px]">Overview</TabsTrigger>
          <TabsTrigger value="fundamentals" className="text-[11px]">Fundamentals</TabsTrigger>
          {/* WHY no count badge: PLAN-0050 — NewsTab manages its own data fetch.
              The article count is shown in the NewsTab filter toolbar. */}
          <TabsTrigger value="news" className="text-[11px]">News</TabsTrigger>
          <TabsTrigger value="intelligence" className="text-[11px]">Intelligence</TabsTrigger>
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

// ── Local helper: instrument-page mnemonic hotkeys ──────────────────────────
//
// PLAN-0059 W1 — split out as a child component so we can memoise the bindings
// list without polluting the parent's render. Bindings need stable identity to
// avoid re-registering on every keystroke (the registration effect's dep array
// is `[bindings]`). useMemo here gives a single stable array per onTabChange.

interface InstrumentMnemonicHotkeysProps {
  /** Tab-change callback — usually `setActiveTab` from the parent's useState. */
  readonly onTabChange: (tab: string) => void;
}

function InstrumentMnemonicHotkeys({ onTabChange }: InstrumentMnemonicHotkeysProps) {
  const bindings = useMemo(
    () => [
      {
        id: "ins.tab.overview",
        chord: "d",
        group: "Symbol" as const,
        label: "DES — Overview",
        handler: () => onTabChange("overview"),
      },
      {
        id: "ins.tab.fundamentals",
        chord: "f",
        group: "Symbol" as const,
        label: "FA — Fundamentals",
        handler: () => onTabChange("fundamentals"),
      },
      {
        id: "ins.tab.news",
        chord: "n",
        group: "Symbol" as const,
        label: "CN — News",
        handler: () => onTabChange("news"),
      },
      {
        id: "ins.tab.intelligence",
        chord: "i",
        group: "Symbol" as const,
        label: "Intel — AI Intelligence",
        handler: () => onTabChange("intelligence"),
      },
    ],
    [onTabChange],
  );

  return <HotkeyScope scope="page" page="/instruments/" bindings={bindings} />;
}
