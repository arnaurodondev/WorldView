/**
 * app/(app)/alerts/page.tsx — Combined Alerts & News page (Wave F-7)
 *
 * WHY THIS EXISTS: Flow F6 (PRD-0028 §2) — "Alert response" — starts here.
 * Traders need a unified hub for: pending alerts (unacknowledged, actionable)
 * and news feeds (background context). Three tabs keep them in one URL.
 *
 * WHY TABBED (Alerts | News Feed | Top Today): Mirrors PRD-0028 §6.5 spec.
 * Alerts and news are related time-ordered feeds — same page, different signal
 * types. Bloomberg Terminal groups alerts + news in a single panel layout.
 *
 * WHY REPLACES OLD SINGLE-TAB ALERTS PAGE: The old page (F-4 era) handled
 * alerts only. F-7 adds the two news tabs and the shared ArticleCard component.
 * The AlertsList component extracted here is also reused by WorkspaceAlertPanel (F-12).
 *
 * WHO USES IT: TopBar AlertBell → "/alerts"; Sidebar "Alerts & News" link;
 *              WatchlistNews "View all news" → "/alerts?tab=news"
 * DATA SOURCE:
 *   Tab 1: S9 GET /api/v1/alerts/pending (AlertsList component)
 *   Tab 2: S9 GET /api/v1/news/relevant?limit=20 (getRelevantNews)
 *   Tab 3: S9 GET /api/v1/news/top?hours=72&limit=20 (getTopNews)
 * DESIGN REFERENCE: PRD-0028 §6.5 "Page: Alerts & News"
 */

"use client";
// WHY "use client": useSearchParams (tab deep-linking), useQuery (data fetching).
// Also: Tabs from shadcn/ui uses Radix state, which requires the client runtime.

import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BellRing, Newspaper, TrendingUp } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertsList } from "@/components/alerts/AlertsList";
import { ArticleCard } from "@/components/news/ArticleCard";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

// ── Page component ────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const searchParams = useSearchParams();
  const { accessToken } = useAuth();

  // ── Default tab from URL param ────────────────────────────────────────────
  // WHY read ?tab= from URL: WatchlistNews widget has "View all news" link →
  // "/alerts?tab=news". Reading the param here means that link lands on the News
  // Feed tab, not the Alerts tab — matching user intent from the click origin.
  const defaultTab = searchParams.get("tab") ?? "alerts";

  return (
    // WHY max-w-4xl: single-column feed is harder to scan when lines are too long.
    // 896px cap balances data density with readability on wide monitors.
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      {/* ── Page header ────────────────────────────────────────────────────── */}
      <div>
        {/* WHY text-lg (not text-xl): matches the global heading hierarchy —
            all page titles use text-lg font-semibold tracking-tight. */}
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Alerts &amp; News</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Pending alerts and latest market news
        </p>
      </div>

      {/* ── Tabbed layout ──────────────────────────────────────────────────── */}
      {/* WHY shadcn Tabs: consistent with Instrument Detail page tab navigation.
          Radix UI handles keyboard navigation (Left/Right arrows + Home/End)
          and ARIA roles (role="tablist", role="tab", role="tabpanel"). */}
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="mb-4 grid w-full grid-cols-3">
          {/* Alerts tab — unacknowledged pending alerts */}
          <TabsTrigger value="alerts" className="gap-1.5 text-xs">
            <BellRing className="h-3.5 w-3.5" aria-hidden="true" />
            Alerts
          </TabsTrigger>

          {/* News Feed tab — general relevance-ranked news */}
          <TabsTrigger value="news" className="gap-1.5 text-xs">
            <Newspaper className="h-3.5 w-3.5" aria-hidden="true" />
            News Feed
          </TabsTrigger>

          {/* Top Today tab — ranked by PRD-0026 impact score */}
          <TabsTrigger value="top" className="gap-1.5 text-xs">
            <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
            Top Today
          </TabsTrigger>
        </TabsList>

        {/* ── Alerts tab ───────────────────────────────────────────────────── */}
        {/* WHY AlertsList (not inline): AlertsList owns its query + filter state
            and is independently testable. Keeping it as a component also allows
            WorkspaceAlertPanel (F-12) to reuse it without duplicating logic. */}
        <TabsContent value="alerts">
          <AlertsList />
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

// ── NewsFeedTab ───────────────────────────────────────────────────────────────

/**
 * NewsFeedTab — general relevance-ranked news from GET /v1/news/relevant
 *
 * WHY a sub-component (not inline): each tab needs its own TanStack Query
 * instance with a unique cache key. If both tabs shared one component with
 * conditional fetches, switching tabs would show stale loading states or
 * trigger unnecessary re-fetches.
 */
interface TabProps {
  accessToken: string | null;
}

function NewsFeedTab({ accessToken }: TabProps) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["news-relevant"],
    queryFn: () => createGateway(accessToken).getRelevantNews(20),
    // WHY 5min auto-refresh: relevance-ranked news doesn't need sub-minute freshness.
    // 5 min is aggressive enough to surface breaking stories but gentle on S9 load.
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  if (isLoading) return <NewsSkeletons />;

  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center">
        <p className="text-sm text-destructive">Failed to load news feed</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          Try again
        </button>
      </div>
    );
  }

  const articles = data?.articles ?? [];

  if (articles.length === 0) {
    return (
      <div className="rounded-lg border border-border/50 p-8 text-center">
        <Newspaper className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">No news available</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {articles.map((article) => (
        <ArticleCard key={article.article_id} article={article} />
      ))}
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
 *
 * WHY 5min auto-refresh: matches NewsFeedTab cadence; prevents staggered
 * simultaneous requests to S9 from the two tabs.
 */
function TopTodayTab({ accessToken }: TabProps) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["news-top-today", { hours: 72, limit: 20 }],
    queryFn: () => createGateway(accessToken).getTopNews({ hours: 72, limit: 20 }),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  });

  if (isLoading) return <NewsSkeletons />;

  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center">
        <p className="text-sm text-destructive">Failed to load top news</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-2 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          Try again
        </button>
      </div>
    );
  }

  const articles = data?.articles ?? [];

  if (articles.length === 0) {
    return (
      <div className="rounded-lg border border-border/50 p-8 text-center">
        <TrendingUp className="mx-auto mb-2 h-8 w-8 text-muted-foreground/50" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">No top stories in the last 72 hours</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {articles.map((article) => (
        <ArticleCard key={article.article_id} article={article} />
      ))}
    </div>
  );
}

// ── NewsSkeletons ─────────────────────────────────────────────────────────────

/**
 * NewsSkeletons — loading placeholder for news feed tabs
 *
 * WHY 5 skeletons: typical viewport shows 3–5 articles at once. 5 gives the
 * impression of a full loaded list without excessive DOM nodes during loading.
 */
function NewsSkeletons() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading news">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-lg border border-border/50 p-3">
          {/* Source badge + timestamp row */}
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-3 w-10" />
          </div>
          {/* Title — two lines */}
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          {/* Tickers + score row */}
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
