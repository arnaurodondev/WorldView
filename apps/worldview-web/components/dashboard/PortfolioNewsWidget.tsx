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
 *   The widget already fetches the candidate articles up front. Re-fetching on
 *   every filter change would multiply the network load without any data
 *   benefit — the user is just slicing what's already loaded. Client-side
 *   filtering also gives instant feedback (zero latency).
 *
 * WHY ROUTING_TIER BADGE: The tier (LIGHT/MEDIUM/HIGH/DEEP) tells traders at
 * a glance how significant the S6 pipeline ranked the article — no need to
 * parse a score number.
 *
 * ── W4 FIX (user report 2026-06-12): PORTFOLIO-SCOPED NEWS ──────────────────
 * The widget previously fetched the GLOBAL `GET /v1/news/top` feed and only
 * filtered to the portfolio when the user manually picked a ticker — so its
 * DEFAULT view showed generic market headlines (Hugo Boss, random IPOs) that
 * had nothing to do with the user's holdings. That defeats the widget's whole
 * purpose ("Portfolio News").
 *
 * There is NO single portfolio-scoped news endpoint in S9 (checked
 * docs/services/api-gateway.md — `/v1/news/top` is global; `/v1/news/entity/
 * {id}` is per-entity). So we now fan out ONE `/v1/news/entity/{entity_id}`
 * call PER HOLDING (via TanStack `useQueries`) and AGGREGATE the results into a
 * single de-duplicated, impact-ranked feed. Every article shown is therefore
 * tied to a name the user actually owns (AAPL/JPM/MSFT/META/AMZN/…). The
 * per-entity calls share TanStack's cache with the Instrument-page News tab, so
 * revisiting an instrument is free.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 4, col-span-3)
 * DATA SOURCE: S9 GET /v1/portfolios → resolved portfolio's holdings →
 *              S9 GET /v1/news/entity/{entity_id} per holding (aggregated)
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7 + PLAN-0053 T-D-4-01
 *                   + W4 portfolio-scoping fix (2026-06-12)
 */

"use client";
// WHY "use client": uses useQuery, useState, useMemo, click handlers.

import { useMemo, useState } from "react";
// Task 2: ticker chips deep-link to the instrument page via Next.js client nav.
import Link from "next/link";
// W4 fix: useQueries fans out one /v1/news/entity/{id} call per holding in a
// single hook call (hooks can't be called inside a .map()), returning an
// aligned array of results we aggregate below.
import { useQuery, useQueries } from "@tanstack/react-query";
// Round 4 (item 3b): central query-key factory — the portfolios list query
// below shares qk.portfolios.list() with PortfolioSummary / the hydrator.
import { qk } from "@/lib/query/keys";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// 2026-06-10: shared active-portfolio resolution — follows the TopBar chip.
import { useResolvedPortfolioId } from "@/hooks/useResolvedPortfolioId";
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

  // ── 1. Holdings — drive BOTH the ticker filter AND the per-entity news ──
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

  // 2026-06-10 PortfolioSwitcher fix: resolve via the shared contract
  // (active-portfolio context first, fallback portfolios[0]) instead of the
  // widget-private created_at sort — the ticker-filter universe now follows
  // the TopBar chip like every other portfolio-scoped widget.
  const firstPortfolioId = useResolvedPortfolioId(portfolios);

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

  // ── 2. Per-holding entity list (drives the news fan-out) ────────────────
  // We pair each holding's entity_id with its ticker so that, after we fetch
  // each entity's news, we can stamp the article with the OWNING ticker for
  // the per-ticker dropdown filter (the per-entity feed doesn't carry a
  // primary_entity_symbol the way the global feed does).
  const holdingEntities = useMemo(() => {
    const seen = new Set<string>();
    const out: { entityId: string; ticker: string }[] = [];
    for (const h of holdingsResp?.holdings ?? []) {
      // Skip holdings with no resolved entity_id (brokerage imports awaiting
      // enrichment) — we have no entity feed to call for them.
      if (!h.entity_id || seen.has(h.entity_id)) continue;
      seen.add(h.entity_id);
      out.push({ entityId: h.entity_id, ticker: h.ticker ?? "" });
    }
    return out;
  }, [holdingsResp]);

  // ── 3. Fan out one /v1/news/entity/{id} call per holding ────────────────
  // WHY useQueries (not N useQuery): hooks must be called at the top of the
  // component, never inside a loop/map. useQueries fans out the calls in a
  // single hook and returns an aligned results array.
  // WHY hours-equivalent via limit only: the entity-news endpoint ranks by
  // relevance/recency server-side; we ask for 8 per holding so a 10-name
  // portfolio yields ~80 candidates before de-dup — deep enough that a tier
  // filter rarely empties the widget, without hammering S9.
  const PER_ENTITY_LIMIT = 8;
  const entityNewsQueries = useQueries({
    queries: holdingEntities.map(({ entityId }) => ({
      // Cache key shared with the Instrument-page News tab: revisiting an
      // instrument the user owns reads this entry for free.
      queryKey: ["entity-news", entityId, PER_ENTITY_LIMIT],
      queryFn: () =>
        createGateway(accessToken).getEntityNews(entityId, {
          limit: PER_ENTITY_LIMIT,
        }),
      enabled: !!accessToken && aboveFoldReady,
      staleTime: 5 * 60_000,
      refetchInterval: 5 * 60_000,
    })),
  });

  // Aggregate state across the fan-out:
  //   - isLoading: TRUE only while NOTHING has resolved yet (so we don't flash
  //     the skeleton once the first holding's news is in).
  //   - isError: TRUE only when EVERY query failed (partial failure still
  //     shows the holdings whose feeds DID load — R9 safe degradation).
  const isLoading =
    holdingEntities.length > 0 &&
    entityNewsQueries.length > 0 &&
    entityNewsQueries.every((q) => q.isLoading);
  const isError =
    entityNewsQueries.length > 0 && entityNewsQueries.every((q) => q.isError);
  // refetch() retries every per-entity query (used by the error-state button).
  const refetch = () => {
    for (const q of entityNewsQueries) void q.refetch();
  };

  // Build the aggregated, de-duplicated candidate pool. Each article is tagged
  // with the owning ticker(s) — the portfolio holding(s) whose entity feed it
  // surfaced under — so we can (a) filter by ticker and (b) render per-article
  // ticker badges (Task 2, user request 2026-06-12).
  const aggregatedArticles = useMemo(() => {
    // Map keyed by article_id so the SAME story surfacing under two holdings
    // (e.g. an "Apple sues Meta" article tied to both AAPL and META) appears
    // ONCE — but we ACCUMULATE every owning ticker across the fan-out into
    // `__ownerTickers` rather than keeping only the first. This is the
    // per-entity provenance the badges display; it derives purely from WHICH
    // holding's entity feed returned the article (the index→ticker pairing in
    // `holdingEntities`), so no extra fetch is needed.
    const byId = new Map<
      string,
      RankedArticle & { __ownerTicker: string; __ownerTickers: string[] }
    >();
    entityNewsQueries.forEach((q, idx) => {
      const ownerTicker = holdingEntities[idx]?.ticker ?? "";
      for (const a of q.data?.articles ?? []) {
        if (!a.article_id) continue;
        const existing = byId.get(a.article_id);
        if (existing) {
          // Already seen under another holding — append this ticker if it's a
          // new, non-empty one (dedup within the badge list too).
          if (ownerTicker && !existing.__ownerTickers.includes(ownerTicker)) {
            existing.__ownerTickers.push(ownerTicker);
          }
          continue;
        }
        // First sighting: seed both the legacy single-owner field (kept for the
        // ticker-dropdown filter contract) and the badge list.
        byId.set(a.article_id, {
          ...a,
          __ownerTicker: ownerTicker,
          __ownerTickers: ownerTicker ? [ownerTicker] : [],
        });
      }
    });
    return Array.from(byId.values());
  }, [entityNewsQueries, holdingEntities]);

  // ── 4. Filter + sort articles ──────────────────────────────────────────
  const articles = useMemo(() => {
    let filtered: (RankedArticle & {
      __ownerTicker: string;
      __ownerTickers: string[];
    })[] = aggregatedArticles;

    // Tier filter — empty set means "all".
    if (activeTiers.size > 0) {
      filtered = filtered.filter((a) => {
        const t = (a.routing_tier ?? "").toUpperCase() as Tier;
        return activeTiers.has(t);
      });
    }

    // Ticker filter — match against the OWNING holding ticker we stamped during
    // aggregation (every article already belongs to a held entity; this narrows
    // to a single name). Falls back to primary_entity_symbol for safety.
    if (tickerFilter !== ALL_TICKERS) {
      filtered = filtered.filter(
        (a) =>
          a.__ownerTicker === tickerFilter ||
          a.primary_entity_symbol === tickerFilter,
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
    // thousands of articles. W4 (user 2026-06-12 "blocks of 30"): 20 → 30 so
    // the holdings-scoped feed shows a fuller block of portfolio news.
    return sorted.slice(0, 30);
  }, [aggregatedArticles, activeTiers, tickerFilter, sortMode, sortDesc]);

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
          {/* Three distinct empty cases (W4): (1) the portfolio has no holdings
              with a resolved entity to scope news to, (2) the user's filters
              excluded everything, (3) the holdings simply have no recent news.
              Each gets its own named copy key so the message matches the cause. */}
          <EmptyState
            condition="empty-no-data"
            copyKey={
              holdingEntities.length === 0
                ? "dashboard.news-no-holdings"
                : activeTiers.size > 0 || tickerFilter !== ALL_TICKERS
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
            <ArticleRow
              key={article.article_id}
              article={article}
              // Task 2: the portfolio holding ticker(s) this article surfaced
              // under (its per-entity provenance from the fan-out aggregation).
              ownerTickers={article.__ownerTickers}
            />
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
 *
 * Task 2 (2026-06-12): `ownerTickers` is the set of portfolio holdings the
 * article surfaced under (derived from the per-entity fan-out provenance — see
 * `aggregatedArticles`). We render them as compact muted ticker chips so the
 * trader sees AT A GLANCE which of their positions a headline concerns. Chips
 * link to `/instruments/[ticker]`; clicking one must NOT also trigger the row's
 * "open article" handler, so each chip stops event propagation.
 */
function ArticleRow({
  article,
  ownerTickers = [],
}: {
  article: RankedArticle;
  ownerTickers?: string[];
}) {
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

      {/* Task 2: portfolio-holding ticker chips. Cap at 3 visible + "+N" so a
          headline shared across many holdings doesn't blow out the 22px row.
          Each chip is a Link to the instrument page; we stop propagation +
          preventDefault on the row's keyboard/click path so navigating to an
          instrument never ALSO opens the external article. */}
      <TickerBadges tickers={ownerTickers} />

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

// ── TickerBadges sub-component ────────────────────────────────────────────────

/**
 * TickerBadges — compact muted chips showing which portfolio holding(s) a news
 * article concerns (Task 2, user request 2026-06-12).
 *
 * WHY cap at 3 + "+N": a headline can surface under many holdings (e.g. a broad
 * "tech selloff" story tied to AAPL/MSFT/META/NVDA/…). Rendering all of them
 * would overflow the 22px terminal row. Showing the first 3 and a "+N" overflow
 * count keeps the row stable while still signalling breadth.
 *
 * WHY muted yellow chip (`bg-primary/15 text-primary`): the design system §2.2
 * defines the ticker badge as "yellow tint + mono". We dim it to /15 so the
 * chips read as secondary metadata, not a CTA — the headline stays the focus.
 *
 * WHY stopPropagation on the chip: the parent row is itself a click target that
 * opens the external article. Without stopping propagation, clicking a chip
 * would BOTH navigate to /instruments/[ticker] AND fire the row handler.
 */
function TickerBadges({ tickers }: { tickers: string[] }) {
  // Nothing to show (e.g. a holding with no resolved ticker) → render nothing
  // rather than an empty gap.
  if (tickers.length === 0) return null;

  const VISIBLE = 3;
  const shown = tickers.slice(0, VISIBLE);
  const overflow = tickers.length - shown.length;

  return (
    <span className="flex shrink-0 items-center gap-0.5" data-testid="portfolio-news-tickers">
      {shown.map((ticker) => (
        <Link
          key={ticker}
          href={`/instruments/${encodeURIComponent(ticker)}`}
          // Stop the row's "open article" handler from also firing.
          onClick={(e) => e.stopPropagation()}
          // Don't let an Enter/Space on the chip bubble to the row's key handler.
          onKeyDown={(e) => e.stopPropagation()}
          data-testid="portfolio-news-ticker-badge"
          title={`View ${ticker} instrument page`}
          className="rounded-[2px] bg-primary/15 px-1 font-mono text-[9px] font-semibold uppercase tracking-wider text-primary transition-colors hover:bg-primary/25 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {ticker}
        </Link>
      ))}
      {overflow > 0 && (
        // Overflow indicator — not a link (the hidden tickers aren't enumerated
        // here); just signals "this story touches N more of your holdings".
        <span
          className="font-mono text-[9px] text-muted-foreground"
          title={`+${overflow} more holding${overflow === 1 ? "" : "s"}`}
        >
          +{overflow}
        </span>
      )}
    </span>
  );
}
