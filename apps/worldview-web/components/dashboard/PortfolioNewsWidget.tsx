/**
 * components/dashboard/PortfolioNewsWidget.tsx — Top ranked news articles
 *
 * WHY THIS EXISTS: The dashboard morning routine includes a quick news scan.
 * Showing the highest-relevance articles from the S6 ranked news endpoint
 * gives the trader immediate awareness of market-moving news before navigating
 * to the full Alerts & News page.
 *
 * PLAN-0053 T-D-4-01 (this revision): adds a filter/sort header strip:
 *   • Ticker dropdown (All + each holding ticker) — client-side filter
 *   • Sort buttons: Impact ↓ (default) | Date ↓ — toggle ascending on second click
 *   • Tier multi-select pills: Light / Medium / High / Deep
 *   Default ``limit`` bumped from 4 → 20 (already at 20; preserved here)
 *   so the buckets are deep enough to support filtering without going empty.
 *
 * WHY ALL FILTERING IS CLIENT-SIDE:
 *   The widget already fetches 20 articles in one round-trip. Re-fetching on
 *   every filter change would multiply the network load without any data
 *   benefit — the user is just slicing what's already loaded. Client-side
 *   filtering also gives instant feedback (zero latency).
 *
 * WHY ROUTING_TIER BADGE: The tier (LIGHT/MEDIUM/HIGH/DEEP) tells traders at
 * a glance how significant the S6 pipeline ranked the article — no need to
 * parse a score number.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: S9 GET /v1/news/top via createGateway().getTopNews({ limit: 20 })
 *              S9 GET /v1/portfolios → first portfolio's holdings (for ticker filter)
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7 + PLAN-0053 T-D-4-01
 */

"use client";
// WHY "use client": uses useQuery, useState, useMemo, click handlers.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
// Round 4 (item 3b): central query-key factory — the portfolios list query
// below shares qk.portfolios.list() with PortfolioSummary / the hydrator.
import { qk } from "@/lib/query/keys";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useAboveFoldReady } from "@/hooks/useAboveFoldReady";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): panel-level empty states use the shared EmptyState
// primitive (§15.12). Two named keys distinguish "feed is empty" from
// "filters excluded everything" — different user actions follow each.
import { EmptyState } from "@/components/primitives/EmptyState";
import { AlertTriangle, Newspaper } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatRelativeTime, cn } from "@/lib/utils";
import { getNewsLinkTarget, isSafeNewsUrl } from "@/hooks/useNewsLinkTarget";
import type { RankedArticle } from "@/types/api";

// ── Types ────────────────────────────────────────────────────────────────────

type SortMode = "impact" | "date";
// Tier filter values normalized to upper case (S6 returns "DEEP" / "HIGH" /
// "MEDIUM" / "LIGHT" but with occasional case drift). Including the literal
// strings here pins the contract.
const ALL_TIERS = ["LIGHT", "MEDIUM", "HIGH", "DEEP"] as const;
type Tier = (typeof ALL_TIERS)[number];

const ALL_TICKERS = "__ALL__";

// ── Component ────────────────────────────────────────────────────────────────

export function PortfolioNewsWidget() {
  const { accessToken } = useAuth();
  // F-4: Row-4 widget — defer all three queries (news, portfolios, holdings)
  // by one paint so Row-2 / Row-3 above-fold widgets get socket priority.
  const aboveFoldReady = useAboveFoldReady();

  // Filter/sort state — local to the widget, not URL-bound (no need to
  // bookmark a specific filter state).
  const [tickerFilter, setTickerFilter] = useState<string>(ALL_TICKERS);
  const [sortMode, setSortMode] = useState<SortMode>("impact");
  const [sortDesc, setSortDesc] = useState(true);
  // Multi-select tier pills. Empty Set === "show all tiers" so the user can
  // clear all filters by deselecting every pill. Using a Set keeps the
  // include/exclude check O(1).
  const [activeTiers, setActiveTiers] = useState<Set<Tier>>(new Set());

  // ── 1. Top news ─────────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dashboard-portfolio-news"],
    // PLAN-0050 T-F-6-02 / PLAN-0053 T-D-4-01: limit=20 keeps the filter
    // candidate pool deep enough that a tier or ticker filter doesn't
    // empty the widget on most days.
    // WHY hours=72: extend lookback to 72h so a brief ingestion hiccup
    // (S4→S5 stalls observed in QA-7) doesn't blank the widget. The
    // ranking layer still surfaces the freshest items first; older items
    // only appear if recent ones are sparse.
    queryFn: () => createGateway(accessToken).getTopNews({ limit: 20, hours: 72 }),
    enabled: !!accessToken && aboveFoldReady,
    // WHY 5min: S9 now caches /v1/news/top for 120s in Valkey, so cold
    // requests are already fast. 5min frontend staleTime avoids polling
    // the cache more than once per session, reducing server load.
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  // ── 2. Holdings — populates the ticker filter dropdown ─────────────────
  // We only need ticker strings, so we don't refetch this often. WHY pull
  // from holdings vs watchlists: this widget is "Portfolio News" — the
  // filter universe should match the portfolio universe.
  // Round 4 (item 3b, query-key drift): key aligned from the widget-private
  // ["dashboard-portfolio-news-portfolios"] to the shared qk.portfolios.list().
  // The queryFn is byte-identical to PortfolioSummary's (getPortfolios() →
  // Portfolio[]), so the private key was a pure duplicate of a fetch that
  // PortfolioSummary fires on the SAME page — one extra /v1/portfolios
  // round-trip per dashboard load for the same payload. Sharing the key also
  // means the F-2 bundle hydrator's seeded list is read here for free.
  const { data: portfolios } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken && aboveFoldReady,
    staleTime: 5 * 60_000,
  });

  const firstPortfolioId = useMemo(() => {
    if (!portfolios || portfolios.length === 0) return null;
    const sorted = [...portfolios].sort(
      (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
    );
    return sorted[0]?.portfolio_id ?? null;
  }, [portfolios]);

  // Round 4 (item 3b): holdings key aligned to the shared ["holdings", id]
  // family (PortfolioSummary + WatchlistQuickViewWidget). Identical queryFn
  // and response shape — when this widget's portfolio pick matches the
  // resolved one (the common single-portfolio case) the fetch dedupes to
  // zero extra requests instead of a third /holdings round-trip.
  const { data: holdingsResp } = useQuery({
    queryKey: ["holdings", firstPortfolioId],
    queryFn: () =>
      createGateway(accessToken).getHoldings(firstPortfolioId!),
    enabled: !!accessToken && aboveFoldReady && !!firstPortfolioId,
    staleTime: 5 * 60_000,
  });

  const tickerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const h of holdingsResp?.holdings ?? []) {
      if (h.ticker) set.add(h.ticker);
    }
    return Array.from(set).sort();
  }, [holdingsResp]);

  // ── 3. Filter + sort articles ──────────────────────────────────────────
  const articles = useMemo(() => {
    const all = data?.articles ?? [];
    let filtered = all;

    // Tier filter — empty set means "all".
    if (activeTiers.size > 0) {
      filtered = filtered.filter((a) => {
        const t = (a.routing_tier ?? "").toUpperCase() as Tier;
        return activeTiers.has(t);
      });
    }

    // Ticker filter — match against the article's primary entity symbol.
    // WHY primary_entity_symbol vs scanning the full entity list: the field
    // is what the global feed exposes today — backend doesn't surface a
    // per-article entity array on the news/top route. Good enough for the
    // common case (mega-cap news where the primary entity IS the
    // article's subject).
    if (tickerFilter !== ALL_TICKERS) {
      filtered = filtered.filter(
        (a) => a.primary_entity_symbol === tickerFilter,
      );
    }

    // Sort. Default impact desc; date desc on user toggle.
    const sorted = [...filtered].sort((a, b) => {
      let diff = 0;
      if (sortMode === "impact") {
        diff =
          (a.market_impact_score ?? a.display_relevance_score ?? 0) -
          (b.market_impact_score ?? b.display_relevance_score ?? 0);
      } else {
        // date: parse published_at — null sorts to the bottom (oldest).
        const ta = a.published_at ? Date.parse(a.published_at) : 0;
        const tb = b.published_at ? Date.parse(b.published_at) : 0;
        diff = ta - tb;
      }
      return sortDesc ? -diff : diff;
    });

    // Hard cap. PLAN-0050 / PLAN-0053: defence vs a backend bug returning
    // thousands of articles.
    return sorted.slice(0, 20);
  }, [data, activeTiers, tickerFilter, sortMode, sortDesc]);

  // Toggle helper for sort buttons. WHY a closure here: identical logic for
  // both buttons, but they each toggle a different sortMode. Inlining once
  // and parameterising keeps the JSX clean.
  function handleSortClick(mode: SortMode) {
    if (sortMode === mode) {
      setSortDesc(!sortDesc);
    } else {
      setSortMode(mode);
      setSortDesc(true);
    }
  }

  function toggleTier(t: Tier) {
    setActiveTiers((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  return (
    // Round 4 (item 2): role="region" + aria-label landmark for SR panel nav.
    <div className="flex h-full flex-col bg-background" role="region" aria-label="Portfolio news">
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PORTFOLIO NEWS
        </span>

        {/* Sort buttons — pinned right. Default Impact ↓. Click toggles
            asc/desc on the active mode. */}
        <div className="flex gap-px">
          <SortButton
            active={sortMode === "impact"}
            onClick={() => handleSortClick("impact")}
            label="IMPACT"
            arrow={sortMode === "impact" ? (sortDesc ? "↓" : "↑") : ""}
          />
          <SortButton
            active={sortMode === "date"}
            onClick={() => handleSortClick("date")}
            label="DATE"
            arrow={sortMode === "date" ? (sortDesc ? "↓" : "↑") : ""}
          />
        </div>
      </div>

      {/* ── Filter strip: ticker dropdown + tier pills ──────────────────── */}
      <div className="flex h-7 shrink-0 items-center gap-1.5 overflow-x-auto border-b border-border/30 px-2">
        {/* Ticker dropdown — native <select> for keyboard ergonomics + zero
            UI dep weight. */}
        <select
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
          // Round 3 (item 5): keyboard focus ring on the native select.
          className="h-5 shrink-0 rounded-[2px] border border-border bg-card px-1 font-mono text-[10px] uppercase tabular-nums text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          aria-label="Filter by ticker"
        >
          <option value={ALL_TICKERS}>ALL</option>
          {tickerOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        {/* Tier pills — multi-select. Active = filled pill. */}
        {ALL_TIERS.map((t) => {
          const active = activeTiers.has(t);
          return (
            <button
              key={t}
              onClick={() => toggleTier(t)}
              aria-pressed={active}
              // Round 3 (item 5): bg-muted hover + keyboard focus ring.
              className={cn(
                "h-5 shrink-0 rounded-[2px] border px-1.5 font-mono text-[9px] uppercase tracking-wider transition-colors",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                active
                  ? "border-primary bg-primary/20 text-primary"
                  : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {t}
            </button>
          );
        })}
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
              <Skeleton
                className="h-3 w-[30px]"
                style={{ animationDelay: `${i * 40}ms` }}
              />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-[24px]" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ────────────────────────────────────────────────────── */}
      {/* WHY min-h-[110px]: matches skeleton height so widget footprint is stable. */}
      {isError && (
        <div className="flex flex-1 min-h-[110px] items-center justify-center gap-2">
          <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
          <span className="text-xs text-muted-foreground">News unavailable</span>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      )}

      {!isLoading && !isError && articles.length === 0 && (
        <div className="flex flex-1 items-center justify-center">
          {/* Round 3 (item 4): filtered-to-zero vs genuinely-empty get
              DIFFERENT named copy keys — the first tells the user to clear
              filters, the second that the pipeline hasn't produced news. */}
          <EmptyState
            condition="empty-no-data"
            copyKey={
              activeTiers.size > 0 || tickerFilter !== ALL_TICKERS
                ? "dashboard.news-filter-no-match"
                : "dashboard.no-news"
            }
            icon={Newspaper}
          />
        </div>
      )}

      {/* ── Article rows ───────────────────────────────────────────────────── */}
      {!isLoading && !isError && articles.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {articles.map((article) => (
            <ArticleRow key={article.article_id} article={article} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── SortButton sub-component ────────────────────────────────────────────────

interface SortButtonProps {
  active: boolean;
  onClick: () => void;
  label: string;
  arrow: string;
}

function SortButton({ active, onClick, label, arrow }: SortButtonProps) {
  return (
    <button
      onClick={onClick}
      // Round 3 (item 5): bg-muted hover convention + keyboard focus ring.
      className={cn(
        "px-1.5 text-[9px] font-mono uppercase transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "bg-primary/20 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      aria-pressed={active}
    >
      {label}
      {arrow && <span className="ml-0.5">{arrow}</span>}
    </button>
  );
}

// ── ArticleRow sub-component ──────────────────────────────────────────────────

/**
 * ArticleRow — single article entry: impact indicator + title + relative time.
 *
 * WHY show market_impact_score as dot indicators instead of a numeric score:
 * In a 22px row, "0.82" is harder to parse than 4 filled dots. The dot pattern
 * encodes urgency in peripheral vision — traders don't need to read the exact
 * value to know "this is high-impact" vs "background noise."
 *
 * WHY click opens in new tab (default): the URL points to the original
 * publisher; opening in the same tab would navigate the user away from the
 * dashboard. PLAN-0050 T-F-6-20 layered a per-user preference on top.
 */
function ArticleRow({ article }: { article: RankedArticle }) {
  const score =
    article.market_impact_score ?? article.display_relevance_score ?? 0;
  const filledDots = Math.max(1, Math.min(4, Math.ceil(score * 4)));

  const dotColor = (() => {
    switch (article.routing_tier?.toUpperCase()) {
      case "DEEP":
      case "HIGH":
        return "text-negative";
      case "MEDIUM":
        return "text-warning";
      default:
        return "text-muted-foreground";
    }
  })();

  const publishedAt = article.published_at
    ? formatRelativeTime(article.published_at)
    : "—";

  function handleClick() {
    if (!isSafeNewsUrl(article.url)) return;
    const pref = getNewsLinkTarget();
    if (pref === "same-tab") {
      window.location.href = article.url!;
    } else {
      window.open(article.url!, "_blank", "noopener,noreferrer");
    }
  }

  const isInteractive = isSafeNewsUrl(article.url);

  return (
    <div
      // Round 3 (item 5): inset focus-visible ring — harmless on
      // non-interactive rows (they're not tabbable so it never triggers).
      className={`flex h-[22px] items-center gap-1.5 px-2 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring ${
        isInteractive ? "cursor-pointer hover:bg-muted/30" : ""
      }`}
      onClick={isInteractive ? handleClick : undefined}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onKeyDown={(e) => {
        if (isInteractive && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          handleClick();
        }
      }}
      aria-label={
        isInteractive && article.title
          ? `Open article: ${article.title}`
          : undefined
      }
    >
      <span
        className={`shrink-0 font-mono text-[9px] ${dotColor}`}
        aria-label={`Impact score ${filledDots}/4`}
        title={`Market impact: ${(score * 100).toFixed(0)}%`}
      >
        {"●".repeat(filledDots)}
        {"○".repeat(4 - filledDots)}
      </span>

      <span
        className="flex-1 truncate text-[11px] text-foreground"
        title={article.title ?? ""}
      >
        {article.title ?? "Untitled"}
      </span>

      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
        {publishedAt}
      </span>
    </div>
  );
}
