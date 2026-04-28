/**
 * app/(app)/alerts/page.tsx — Combined Alerts & News page (Wave 7 enhanced)
 *
 * WHY THIS EXISTS: Flow F6 (PRD-0028 §2) — "Alert response" — starts here.
 * Traders need a unified hub for: pending alerts (unacknowledged, actionable)
 * and news feeds (background context). Three tabs keep them in one URL.
 *
 * WHY TABBED (Alerts | News Feed | Top Today): Mirrors PRD-0028 §6.5 spec.
 * Alerts and news are related time-ordered feeds — same page, different signal
 * types. Bloomberg Terminal groups alerts + news in a single panel layout.
 *
 * WAVE 7 ADDITIONS:
 * - AlertsList rewritten with severity groups + ACK/Snooze (AlertsList.tsx)
 * - Category filter rail (7 categories) on News Feed + Top Today tabs
 * - [+ Create Rule] button opens AlertRuleBuilder dialog
 * - [⚙ Manage Rules] shows count from localStorage
 *
 * WHY CATEGORY FILTER CLIENT-SIDE: The S9 news endpoints don't support category
 * filtering. Client-side keyword matching is fast (20 articles) and avoids a
 * second round-trip. The categories are heuristic (keyword-based), not ML-tagged.
 *
 * WHO USES IT: TopBar AlertBell → "/alerts"; Sidebar "Alerts & News" link;
 *              WatchlistNews "View all news" → "/alerts?tab=news"
 * DATA SOURCE:
 *   Tab 1: S9 GET /api/v1/alerts/pending (AlertsList component)
 *   Tab 2: S9 GET /api/v1/news/relevant?limit=20 (getRelevantNews)
 *   Tab 3: S9 GET /api/v1/news/top?hours=72&limit=20 (getTopNews)
 * DESIGN REFERENCE: PRD-0031 §11 Alerts Wave 7
 */

"use client";
// WHY "use client": useSearchParams (tab deep-linking), useQuery (data fetching),
// useState (category filter). Tabs from shadcn/ui uses Radix state (client runtime).

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BellRing, Newspaper, TrendingUp } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertsList } from "@/components/alerts/AlertsList";
import { AlertRuleBuilder, getAlertRuleCount } from "@/components/alerts/AlertRuleBuilder";
import { ArticleCard } from "@/components/news/ArticleCard";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import type { Article } from "@/types/api";

// ── Category filter constants ─────────────────────────────────────────────────

/**
 * CATEGORIES — filter chips for the News Feed and Top Today tabs.
 * WHY 7 categories: covers the major news buckets institutional traders care
 * about. "All" is always first as the no-filter default.
 */
const CATEGORIES = [
  "All",
  "Earnings",
  "M&A",
  "Regulatory",
  "Macro",
  "Analyst",
  "SEC Filings",
] as const;

type NewsCategory = (typeof CATEGORIES)[number];

/**
 * CATEGORY_KEYWORDS — heuristic keyword sets for client-side article filtering.
 * WHY lowercase: `article.title.toLowerCase().includes(keyword)` comparison.
 */
const CATEGORY_KEYWORDS: Record<string, string[]> = {
  Earnings: ["earnings", "eps", "revenue", "quarterly"],
  "M&A": ["acquisition", "merger", "takeover", "deal"],
  Regulatory: ["sec", "regulation", "compliance", "fine", "penalty"],
  Macro: ["fed", "inflation", "gdp", "interest rate", "fomc"],
  Analyst: ["upgrade", "downgrade", "price target", "analyst", "rating"],
  "SEC Filings": ["10-k", "10-q", "8-k", "filing", "form"],
};

// ── Category filter helper ─────────────────────────────────────────────────────

/**
 * filterByCategory — filters Article[] by heuristic keyword matching.
 * WHY title-only (not summary): summary may be null on many articles;
 * title is always populated and sufficient for category heuristics.
 */
function filterByCategory(articles: Article[], category: NewsCategory): Article[] {
  if (category === "All") return articles;
  const keywords = CATEGORY_KEYWORDS[category] ?? [];
  return articles.filter((a) => {
    const title = (a.title ?? "").toLowerCase();
    return keywords.some((kw) => title.includes(kw));
  });
}

// ── Page component ────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const searchParams = useSearchParams();
  const { accessToken } = useAuth();

  // ── Default tab from URL param ────────────────────────────────────────────
  // WHY read ?tab= from URL: WatchlistNews widget has "View all news" link →
  // "/alerts?tab=news". Reading the param here means that link lands on the News
  // Feed tab, not the Alerts tab — matching user intent from the click origin.
  const defaultTab = searchParams.get("tab") ?? "alerts";

  // PLAN-0048 Wave B-3: deep-link to a specific alert via ?selected={alert_id}.
  // Reading the param here (rather than inside AlertsList) keeps the URL the
  // single source of truth — refresh + back/forward navigation Just Work.
  // When the param is absent we pass null and the AlertDetailSheet stays
  // closed on initial render.
  const selectedAlertId = searchParams.get("selected");

  // ── Rule count — read from localStorage for Manage Rules badge ────────────
  // WHY not state: rule count updates after AlertRuleBuilder saves; we re-read
  // localStorage synchronously via getAlertRuleCount() on each render.
  // This is safe — getAlertRuleCount() is cheap (one localStorage.getItem).
  const [ruleCount, setRuleCount] = useState(() =>
    // WHY guard: localStorage is not available in SSR (server component context).
    // "use client" ensures this runs in the browser, but typeof check is belt-and-suspenders.
    typeof window !== "undefined" ? getAlertRuleCount() : 0,
  );

  return (
    // WHY full-width p-3: terminal alert feeds should use the full viewport width.
    // p-3 (12px) is the standard terminal panel padding per design system.
    <div className="space-y-2 p-3">

      {/* ── Page header ────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Alerts &amp; News</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Pending alerts and latest market news
          </p>
        </div>

        {/* ── Rule management toolbar ─────────────────────────────────────── */}
        {/* WHY in page header: the + Create Rule and Manage Rules buttons affect
            all tabs, not just the Alerts tab, so they belong at the page level */}
        <div className="flex items-center gap-2">

          {/* Manage Rules — shows count from localStorage */}
          <button
            type="button"
            className="rounded-[2px] border border-border/40 bg-muted/20 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            aria-label={`Manage alert rules (${ruleCount} active)`}
          >
            ⚙ Rules ({ruleCount})
          </button>

          {/* Create Rule — opens AlertRuleBuilder dialog */}
          <AlertRuleBuilder onRuleSaved={() => setRuleCount(getAlertRuleCount())} />

        </div>
      </div>

      {/* ── Tabbed layout ──────────────────────────────────────────────────── */}
      {/* WHY shadcn Tabs: consistent with Instrument Detail page tab navigation.
          Radix UI handles keyboard navigation (Left/Right arrows + Home/End)
          and ARIA roles (role="tablist", role="tab", role="tabpanel"). */}
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="mb-2 grid w-full grid-cols-3">
          <TabsTrigger value="alerts" className="gap-1.5 text-xs">
            <BellRing className="h-3.5 w-3.5" aria-hidden="true" />
            Alerts
          </TabsTrigger>
          <TabsTrigger value="news" className="gap-1.5 text-xs">
            <Newspaper className="h-3.5 w-3.5" aria-hidden="true" />
            News Feed
          </TabsTrigger>
          <TabsTrigger value="top" className="gap-1.5 text-xs">
            <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
            Top Today
          </TabsTrigger>
        </TabsList>

        {/* ── Alerts tab ────────────────────────────────────────────────────── */}
        {/* WHY AlertsList (not inline): AlertsList owns its query + filter state
            and is independently testable. Keeping it as a component also allows
            WorkspaceAlertPanel (F-12) to reuse it without duplicating logic. */}
        <TabsContent value="alerts">
          <AlertsList selectedId={selectedAlertId} />
        </TabsContent>

        {/* ── News Feed tab ─────────────────────────────────────────────────── */}
        <TabsContent value="news">
          <NewsFeedTab accessToken={accessToken} />
        </TabsContent>

        {/* ── Top Today tab ─────────────────────────────────────────────────── */}
        <TabsContent value="top">
          <TopTodayTab accessToken={accessToken} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Shared TabProps ───────────────────────────────────────────────────────────

interface TabProps {
  accessToken: string | null;
}

// ── CategoryFilterRail ────────────────────────────────────────────────────────

/**
 * CategoryFilterRail — horizontal chip strip for filtering articles by category.
 *
 * WHY sticky: on scroll-heavy news lists the rail stays visible so the user
 * can switch categories without scrolling back to the top.
 */
interface CategoryFilterRailProps {
  active: NewsCategory;
  onChange: (cat: NewsCategory) => void;
}

function CategoryFilterRail({ active, onChange }: CategoryFilterRailProps) {
  return (
    // WHY border-b + overflow-x-auto: allows horizontal scroll on narrow viewports
    // without wrapping the chips to a second line which would push articles down.
    <div className="flex gap-0 overflow-x-auto border-b border-border">
      {CATEGORIES.map((cat) => (
        <button
          key={cat}
          type="button"
          // WHY h-7 px-3 (not h-[22px]): category chips are nav elements, not data
          // rows. Slightly taller gives adequate tap target for mobile.
          className={cn(
            "h-7 shrink-0 border-b-2 px-3 text-[10px] uppercase tracking-[0.08em]",
            "transition-colors duration-0",
            active === cat
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
          onClick={() => onChange(cat)}
          aria-pressed={active === cat}
        >
          {cat}
        </button>
      ))}
    </div>
  );
}

// ── NewsFeedTab ───────────────────────────────────────────────────────────────

/**
 * NewsFeedTab — general relevance-ranked news from GET /v1/news/relevant
 *
 * WHY a sub-component (not inline): each tab needs its own TanStack Query
 * instance with a unique cache key. If both tabs shared one component with
 * conditional fetches, switching tabs would show stale loading states or
 * trigger unnecessary re-fetches.
 */
function NewsFeedTab({ accessToken }: TabProps) {
  // WHY local category state: filter resets naturally on tab switch —
  // expected UX for a real-time alert feed.
  const [activeCategory, setActiveCategory] = useState<NewsCategory>("All");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["news-relevant"],
    queryFn: () => createGateway(accessToken).getRelevantNews(20),
    // WHY 5min auto-refresh: relevance-ranked news doesn't need sub-minute freshness
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  const allArticles = data?.articles ?? [];
  const filtered = filterByCategory(allArticles, activeCategory);

  return (
    <div>
      {/* WHY CategoryFilterRail rendered FIRST — outside loading/error guards:
          The rail must always be present immediately after tab activation so
          tests can assert on category chip presence without waiting for network.
          It also gives a better UX: users can pre-select a category while
          articles are still loading. */}
      <CategoryFilterRail active={activeCategory} onChange={setActiveCategory} />

      {/* Loading state — skeleton below the category rail */}
      {isLoading && <div className="mt-2"><NewsSkeletons /></div>}

      {/* Error state */}
      {isError && (
        <div className="mt-2 rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-center">
          <p className="text-sm text-destructive">Failed to load news feed</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Try again
          </button>
        </div>
      )}

      {/* Article list — only rendered after data is available */}
      {!isLoading && !isError && (
        allArticles.length === 0 ? (
          <div className="mt-2 rounded-[2px] border border-border/40 p-3 text-center">
            <Newspaper className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">No news available</p>
          </div>
        ) : (
          <div className="mt-2 space-y-2">
            {filtered.length === 0 ? (
              <p className="py-3 text-center text-xs text-muted-foreground">
                No {activeCategory} articles in this feed.
              </p>
            ) : (
              filtered.map((article) => (
                <ArticleCard key={article.article_id} article={article} />
              ))
            )}
          </div>
        )
      )}
    </div>
  );
}

// ── TopTodayTab ───────────────────────────────────────────────────────────────

/**
 * TopTodayTab — impact-scored articles from GET /v1/news/top?hours=72&limit=20
 *
 * WHY hours=72 (not 48): The WatchlistNews widget uses 48h for the dashboard
 * where brevity is key. The dedicated "Top Today" tab uses 72h so Friday's
 * top articles still appear on Monday — ensuring the weekend gap is filled
 * without requiring the user to change the time window manually.
 */
function TopTodayTab({ accessToken }: TabProps) {
  const [activeCategory, setActiveCategory] = useState<NewsCategory>("All");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["news-top-today", { hours: 72, limit: 20 }],
    queryFn: () => createGateway(accessToken).getTopNews({ hours: 72, limit: 20 }),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  // WHY TopTodayTab uses Article type: getTopNews returns RankedArticle but
  // ArticleCard accepts Article. We need to convert or cast the articles.
  // The ArticleCard component was built for the Article type from the legacy
  // news endpoint. For display purposes we only need title/url/source/published_at
  // which are present on both types.
  const rawArticles = data?.articles ?? [];

  // Convert RankedArticle → Article shape for ArticleCard compatibility
  const articles: Article[] = rawArticles.map((ra) => ({
    article_id: ra.article_id,
    title: ra.title ?? "Untitled",
    url: ra.url ?? "#",
    source: ra.source_name ?? ra.source_type ?? "Unknown",
    published_at: ra.published_at ?? new Date().toISOString(),
    summary: null,
    entity_ids: [],
    tickers: ra.primary_entity_symbol ? [ra.primary_entity_symbol] : [],
    display_relevance_score: ra.display_relevance_score,
    market_impact_score: ra.market_impact_score,
    sentiment: null,
    impact_window_t0: ra.impact_windows?.day_t0 ?? null,
    impact_window_t1: ra.impact_windows?.day_t1 ?? null,
    impact_window_t2: ra.impact_windows?.day_t2 ?? null,
    impact_window_t5: ra.impact_windows?.day_t5 ?? null,
    routing_tier:
      ra.routing_tier === "DEEP"
        ? "HIGH"
        : ra.routing_tier === "MEDIUM"
          ? "STANDARD"
          : ra.routing_tier === "LIGHT"
            ? "LIGHT"
            : undefined,
  }));

  const filtered = filterByCategory(articles, activeCategory);

  return (
    <div>
      {/* WHY CategoryFilterRail rendered FIRST — same reason as NewsFeedTab:
          rail is always present immediately after tab activation */}
      <CategoryFilterRail active={activeCategory} onChange={setActiveCategory} />

      {/* Loading state */}
      {isLoading && <div className="mt-2"><NewsSkeletons /></div>}

      {/* Error state */}
      {isError && (
        <div className="mt-2 rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-center">
          <p className="text-sm text-destructive">Failed to load top news</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          >
            Try again
          </button>
        </div>
      )}

      {/* Article list */}
      {!isLoading && !isError && (
        articles.length === 0 ? (
          <div className="mt-2 rounded-[2px] border border-border/40 p-3 text-center">
            <TrendingUp className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">No top stories in the last 72 hours</p>
          </div>
        ) : (
          <div className="mt-2 space-y-2">
            {filtered.length === 0 ? (
              <p className="py-3 text-center text-xs text-muted-foreground">
                No {activeCategory} articles in top today.
              </p>
            ) : (
              filtered.map((article) => (
                <ArticleCard key={article.article_id} article={article} />
              ))
            )}
          </div>
        )
      )}
    </div>
  );
}

// ── NewsSkeletons ─────────────────────────────────────────────────────────────

/**
 * NewsSkeletons — loading placeholder for news feed tabs.
 * WHY 5 skeletons: typical viewport shows 3–5 articles at once.
 */
function NewsSkeletons() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading news">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-[2px] border border-border/40 p-3">
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-3 w-10" />
          </div>
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <div className="flex items-center justify-between">
            <div className="flex gap-1">
              <Skeleton className="h-3 w-10" />
              <Skeleton className="h-3 w-10" />
            </div>
            <Skeleton className="h-3 w-6" />
          </div>
        </div>
      ))}
    </div>
  );
}
