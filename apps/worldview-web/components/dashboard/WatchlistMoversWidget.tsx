/**
 * components/dashboard/WatchlistMoversWidget.tsx — Watchlist movers (PLAN-0048 Wave E-2)
 *
 * WHY THIS EXISTS: Watching a hand-picked list is more actionable than
 * scanning the entire market. Whereas the universe-wide TopMovers widget
 * (PreMarketMoversWidget) answers "what is moving today?", THIS widget
 * answers "which of MY tracked names is moving today?". For most retail
 * and prosumer investors that is the more useful question — they already
 * narrowed the universe to names they care about.
 *
 * WHY THIS REPLACES THE OLD MARKET-WIDE LAYOUT IN ROW 2 (PLAN-0048 E-1):
 * Row 2 is "macro context". A watchlist movers widget at col-span-5 sits
 * naturally next to the sector treemap — together they answer
 * "what's the broad market doing?" + "what are MY names doing?" in one
 * row, with TopMovers (universe-wide) moving down to Row 3 col-span-4.
 *
 * WHY 1D DEFAULT: most users check the dashboard intraday looking for
 * "what moved today?". 1W / 1M are only relevant for periodic review.
 *
 * WHY TOP 5 EACH SIDE (gainers vs losers): at col-span-5 (~520px on a
 * 1280px viewport, less the 12-col gap) the row width comfortably fits
 * a ticker + name + price + %. With h-7 rows, 5 + 5 = 10 rows fits
 * within the ~220px available content area without scrolling.
 *
 * WHY BUILT-IN SECTOR FILTER (Wave F-2 reuse): the same `lib/sectors.ts`
 * pill row used in PreMarketMoversWidget — so users get consistent
 * filtering UX across all three movers widgets in the dashboard.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-5)
 * DATA SOURCES:
 *   - S1 GET /v1/watchlists                 (createGateway().getWatchlists)
 *   - S1 GET /v1/watchlists/{id}/members    (createGateway().getWatchlistMembers)
 *   - S9 POST /v1/quotes/batch              (createGateway().getBatchQuotes) — 1D
 *   - S9 GET /v1/ohlcv/{instrument_id}      (createGateway().getOHLCV)        — 1W/1M
 *   - S9 GET /v1/companies/{id}/overview    (per-member sector lookup)
 *
 * DESIGN REFERENCE: PLAN-0048 Wave E (E-2) and PLAN-0047 Wave A spec.
 */

"use client";
// WHY "use client": uses useQuery / useQueries for data fetching, useAuth for
// the bearer token, useState for period + sector pill state, and useRouter
// for row navigation.

import { useMemo, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Bell, Newspaper } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useNewsLinkTarget, newsLinkAttrs } from "@/hooks/useNewsLinkTarget";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import { cn } from "@/lib/utils";
import type { WatchlistMoverEnriched } from "@/types/api";
// PLAN-0048 Wave F-2: shared sector pill module (also used by F-1
// SectorHeatmapWidget and F-2 PreMarketMoversWidget). Importing the same
// constants/predicate guarantees consistent ordering, labels, and matching
// rules across every movers widget in the dashboard.
import {
  SECTOR_PILLS,
  ALL_SECTORS_VALUE,
  matchesSectorFilter,
} from "@/lib/sectors";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Period selector — same set as PreMarketMoversWidget so users have a
 * consistent mental model: 1D = today's session (live), 1W = trailing 7
 * trading days, 1M = trailing ~21 trading days. 1D uses the realtime
 * batch-quotes path; 1W/1M derive change_pct from OHLCV first→last close.
 */
type WatchlistPeriod = "1D" | "1W" | "1M";

/**
 * MoverRow — internal shape for a row in the gainers/losers columns.
 *
 * PLAN-0050 Wave B: extended with the per-row enrichment columns so the row
 * sub-component can render the news icon + alert dot without a second lookup.
 * - For 1D: backed by `WatchlistInsights.movers[]` from the composite endpoint.
 * - For 1W/1M: change_pct comes from per-instrument OHLCV; the enrichment
 *   columns (sector, news, alerts) are still sourced from the insights payload
 *   so the badges remain consistent across periods.
 */
interface WatchlistMover {
  instrumentId: string;
  ticker: string;
  name: string;
  sector: string | null;
  // For 1D: latest live price. For 1W/1M: latest close from OHLCV.
  price: number | null;
  // Percentage change over the selected period (already in percent units,
  // e.g. 2.34 not 0.0234). May be null while we are still loading the
  // backing data for that row.
  changePct: number | null;
  newsCount24h: number;
  hasActiveAlert: boolean;
  topNewsTitle: string | null;
  topNewsUrl: string | null;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * WatchlistMoversWidget — top gainers + losers from the user's first
 * watchlist, with optional sector filter and period selector.
 */
export function WatchlistMoversWidget() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY local state (not URL): widget-scoped — no need to bookmark.
  // Default 1D matches the most common use-case (intraday check-in).
  const [period, setPeriod] = useState<WatchlistPeriod>("1D");

  // WHY local state for the sector pill: same rationale as
  // PreMarketMoversWidget — each movers widget filters independently so
  // the user can have e.g. "watchlist Tech only" while the universe-wide
  // TopMovers stays on "All".
  const [selectedSector, setSelectedSector] = useState<string>(ALL_SECTORS_VALUE);

  // ── 1. Fetch user's watchlists ──────────────────────────────────────────
  // WHY pick first by created_at: the spec ("PLAN-0047 Wave A: pick first
  // watchlist by created_at OR a 'default' concept if it exists") — there
  // is no explicit "is_default" flag on the Watchlist type today, so we
  // fall back to the oldest one. That maps to "the watchlist I made first"
  // which for >90% of users is their main / default list.
  // WHY staleTime 60_000: watchlist membership rarely changes intra-session.
  const { data: watchlists, isLoading: watchlistsLoading } = useQuery({
    queryKey: ["dashboard-watchlist-movers-watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // WHY useMemo on the chosen watchlist: keeps the dependency stable for
  // every downstream useQuery key — without it React would re-run the
  // queries on every render even though `firstWatchlist` resolves to the
  // same object.
  const firstWatchlist = useMemo(() => {
    if (!watchlists || watchlists.length === 0) return null;
    const sorted = [...watchlists].sort((a, b) => {
      const ta = Date.parse(a.created_at);
      const tb = Date.parse(b.created_at);
      if (!Number.isNaN(ta) && !Number.isNaN(tb)) return ta - tb;
      return a.created_at.localeCompare(b.created_at);
    });
    return sorted[0] ?? null;
  }, [watchlists]);

  // ── 2. PLAN-0050 Wave B: composite insights endpoint ────────────────────
  // Replaces the prior 5-query chain (members + quotes + per-member overviews
  // + news + alerts) with a single round-trip. The gateway composes everything
  // server-side so the widget only owns presentation.
  //
  // WHY 60s staleTime + 60s refetchInterval: matches the prior batch-quote
  // cadence. The composite endpoint's Cache-Control: max-age=60 also pins
  // the upstream cache to the same window so we don't hammer the gateway.
  const { data: insights, isLoading: insightsLoading } = useQuery({
    queryKey: [
      "dashboard-watchlist-movers-insights",
      firstWatchlist?.watchlist_id,
    ],
    queryFn: () =>
      createGateway(accessToken).getWatchlistInsights(
        firstWatchlist!.watchlist_id,
      ),
    enabled: !!accessToken && !!firstWatchlist,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // The insights envelope is the canonical source for sector/news/alerts;
  // we still need instrument_ids for the 1W/1M OHLCV fan-out path below.
  const enrichedMovers: WatchlistMoverEnriched[] = useMemo(
    () => insights?.movers ?? [],
    [insights],
  );
  const instrumentIds = useMemo(
    () => enrichedMovers.map((m) => m.instrument_id),
    [enrichedMovers],
  );

  // ── 3. 1W / 1M path — per-instrument OHLCV ─────────────────────────────
  // The insights endpoint covers 1D internally. For 1W/1M we still need
  // per-instrument OHLCV bars to derive change_pct over the period — the
  // composite endpoint deliberately omits this to keep the response small.
  const ohlcvQueries = useQueries({
    queries: instrumentIds.map((id) => ({
      queryKey: ["dashboard-watchlist-movers-ohlcv", id, period],
      queryFn: () =>
        createGateway(accessToken).getOHLCV(id, {
          timeframe: period,
        }),
      enabled:
        !!accessToken &&
        period !== "1D" &&
        instrumentIds.length > 0,
      // WHY long staleTime: a 1W/1M trend doesn't change minute-by-minute.
      // 5 min is enough to feel fresh without spamming the OHLCV endpoint.
      staleTime: 5 * 60_000,
    })),
  });

  // ── 4. Build the mover rows (period-aware) ────────────────────────────
  // Insights provides 1D fields directly. For 1W/1M we override change_pct
  // from the per-instrument OHLCV chain. All other enrichment (sector, news,
  // alerts) is period-agnostic and comes from insights.
  const movers: WatchlistMover[] = useMemo(() => {
    return enrichedMovers.map((em, idx) => {
      const base: WatchlistMover = {
        instrumentId: em.instrument_id,
        ticker: em.ticker,
        name: em.name,
        sector: em.sector,
        price: em.price,
        changePct: em.change_pct,
        newsCount24h: em.news_count_24h,
        hasActiveAlert: em.has_active_alert,
        topNewsTitle: em.top_news_title,
        topNewsUrl: em.top_news_url,
      };
      if (period === "1D") return base;

      // 1W / 1M: override price + change_pct from the OHLCV first→last close.
      const ohlcv = ohlcvQueries[idx]?.data;
      const bars = ohlcv?.bars ?? [];
      if (bars.length < 2) return { ...base, price: null, changePct: null };
      const first = bars[0]!.close;
      const last = bars[bars.length - 1]!.close;
      if (first <= 0) return { ...base, price: last, changePct: null };
      return {
        ...base,
        price: last,
        changePct: ((last - first) / first) * 100,
      };
    });
  }, [enrichedMovers, period, ohlcvQueries]);

  // ── 5. Apply sector filter ────────────────────────────────────────────
  // WHY graceful "still loading" behaviour: matches PreMarketMoversWidget —
  // we keep rows with unknown sector visible so the user doesn't see a
  // shrinking list during a refetch.
  const filtered = useMemo(() => {
    if (selectedSector === ALL_SECTORS_VALUE) return movers;
    return movers.filter((m) => {
      if (m.sector == null) return true; // sector lookup not loaded yet
      return matchesSectorFilter(m.sector, selectedSector);
    });
  }, [movers, selectedSector]);

  // ── 7. Sort by absolute |change_pct| desc, split into gainers / losers ─
  // WHY |change_pct| sort BEFORE the split: spec calls for "biggest absolute
  // movers" — a sector full of -4% losers is more interesting to surface
  // than a flat +0.1% gainer. Sorting by abs first then partitioning
  // ensures the top-5 of each side are the most extreme moves.
  const sortedByAbs = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const aa = a.changePct == null ? -1 : Math.abs(a.changePct);
      const bb = b.changePct == null ? -1 : Math.abs(b.changePct);
      return bb - aa;
    });
  }, [filtered]);

  const gainers = useMemo(
    () =>
      sortedByAbs
        .filter((m) => m.changePct != null && m.changePct > 0)
        .slice(0, 5),
    [sortedByAbs],
  );
  const losers = useMemo(
    () =>
      sortedByAbs
        .filter((m) => m.changePct != null && m.changePct < 0)
        .slice(0, 5),
    [sortedByAbs],
  );

  // ── 7. Loading composition ────────────────────────────────────────────
  // WHY combine watchlist + insights + (period-specific data) loading: the
  // user shouldn't see a partially-rendered widget. Once *any* of these
  // complete unsuccessfully we fall through to the empty/no-data branch.
  const periodDataLoading =
    period === "1D" ? false : ohlcvQueries.some((q) => q.isLoading);
  const isLoading =
    watchlistsLoading || (!!firstWatchlist && (insightsLoading || periodDataLoading));

  // ── 9. Empty state (no watchlist) ─────────────────────────────────────
  const noWatchlist = !watchlistsLoading && !firstWatchlist;

  // ── Render ────────────────────────────────────────────────────────────
  return (
    // WHY bg-background + flex h-full flex-col: matches the layout used by
    // PreMarketMoversWidget so the header / sub-headers / content rows all
    // align horizontally with the sibling widget across the row.
    // WHY min-h-0: parent grid cell uses overflow-hidden — we need
    // min-h-0 on this flex container so the inner overflow-auto has a
    // definite height (otherwise content area "pushes" the panel taller).
    <div className="flex h-full min-h-0 flex-col bg-background">

      {/* ── Section header + period selector ──────────────────────────── */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          WATCHLIST MOVERS
        </span>
        {/* WHY period buttons here: same Bloomberg-style header convention as
            PreMarketMoversWidget — controls live in the panel header, NOT
            buried below the data. Using gap-px (1px hairline) matches the
            repo-wide panel-seam aesthetic. */}
        <div className="flex gap-px">
          {(["1D", "1W", "1M"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              // WHY aria-pressed: these are toggle buttons — aria-pressed
              // communicates the selected state to assistive tech.
              aria-pressed={period === p}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* ── Sector filter pills (Wave F-2 reuse) ─────────────────────── */}
      {/* WHY hide pills for the empty-state branch: when the user has no
          watchlist, sector filters make no sense yet — the empty-state is
          the only thing that should occupy the panel. */}
      {!noWatchlist && (
        <div
          className="-mx-2 flex shrink-0 gap-1 overflow-x-auto border-b border-border/30 px-2 pb-1 pt-1"
          // role="tablist": same ARIA semantics as PreMarketMoversWidget for
          // a one-of-many pill selector.
          role="tablist"
          aria-label="Filter watchlist movers by sector"
        >
          {SECTOR_PILLS.map((pill) => {
            const isSelected = selectedSector === pill.value;
            return (
              <button
                key={pill.value}
                role="tab"
                aria-selected={isSelected}
                onClick={() => setSelectedSector(pill.value)}
                className={cn(
                  "shrink-0 rounded border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  isSelected
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70",
                )}
              >
                {pill.label}
              </button>
            );
          })}
        </div>
      )}

      {/* ── Per-watchlist summary strip (PLAN-0050 T-B-2-02) ────────────
          Shows the watchlist's equal-weighted day return + sector
          concentration mini-bar (T-B-2-03) + alert/news total counts.
          Hidden in 1W/1M because the underlying weighted_return_1d is
          a 1D figure; showing it next to a 1M label would be misleading.
          WHY equal-weighted (not market-cap-weighted): the widget shows
          a watchlist, not a portfolio — users hand-pick names they want
          to track equally. A market-cap weight would silently dominate
          the readout with whichever megacap they happen to follow. */}
      {!noWatchlist && period === "1D" && insights && (
        <WatchlistSummaryStrip insights={insights} />
      )}

      {/* ── Single-biggest-news callout (PLAN-0050 T-B-2-06) ───────────
          Above the gainers/losers split so the highest-impact story
          touching any watchlist member is the first thing the user
          reads. Click opens the article (new tab, noopener). */}
      {!noWatchlist && period === "1D" && insights?.biggest_news?.title && (
        <BiggestNewsRow news={insights.biggest_news} />
      )}

      {/* ── Sub-headers: GAINERS | LOSERS ─────────────────────────────── */}
      {/* WHY render these even in the empty-state path: keeping the static
          chrome consistent makes the empty state feel like a deliberate
          state, not a broken widget. Hidden when there's no watchlist
          since the panel is fully replaced by the empty-state CTA. */}
      {!noWatchlist && (
        <div className="flex shrink-0 border-b border-border/30">
          <div className="flex h-[22px] flex-1 items-center px-2">
            <span className="text-[10px] uppercase tracking-[0.08em] text-positive/70">
              GAINERS
            </span>
          </div>
          <div className="flex h-[22px] flex-1 items-center border-l border-border/30 px-2">
            <span className="text-[10px] uppercase tracking-[0.08em] text-negative/70">
              LOSERS
            </span>
          </div>
        </div>
      )}

      {/* ── Content ───────────────────────────────────────────────────── */}
      {/* WHY min-h-0 on the scroll container: enables independent scroll
          inside the bounded grid cell — the spec's "independent-scroll
          per cell" rule. Without min-h-0 the flex item's intrinsic size
          would prevent the overflow-auto from clipping. */}
      <div className="flex min-h-0 flex-1 overflow-auto">

        {/* Empty: no watchlist at all (PLAN-0050 T-F-6-04 — DashboardEmptyState).
            Why the shared component: the prior bespoke 3-element JSX block
            duplicated the heading/message/CTA pattern that already lived in
            DashboardEmptyState. Using the shared component pins the visual
            voice across all dashboard widgets — no widget can drift on the
            empty-state pattern after this. */}
        {noWatchlist && (
          <div className="flex flex-1 items-center justify-center">
            <DashboardEmptyState
              title="No watchlist yet"
              message="Add instruments to your watchlist to see daily movers here."
              cta={{ label: "Browse Screener →", href: "/screener" }}
            />
          </div>
        )}

        {/* Loading: show 5 placeholder rows in each column */}
        {!noWatchlist && isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={`g-skel-${i}`} className="flex h-7 items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[60px]" />
                  <Skeleton className="ml-auto h-3 w-[40px]" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={`l-skel-${i}`} className="flex h-7 items-center gap-2 px-2">
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[60px]" />
                  <Skeleton className="ml-auto h-3 w-[40px]" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty: watchlist exists but no movers (rare — flat day) */}
        {!noWatchlist &&
          !isLoading &&
          gainers.length === 0 &&
          losers.length === 0 && (
            <div className="flex-1 px-2">
              <InlineEmptyState message="No movers in this watchlist" />
            </div>
          )}

        {/* Data: gainers column */}
        {!noWatchlist && !isLoading && (gainers.length > 0 || losers.length > 0) && (
          <div className="flex-1 divide-y divide-border/30">
            {gainers.map((m) => (
              <WatchlistMoverRow
                key={`g-${m.instrumentId}`}
                mover={m}
                side="gainer"
                onClick={() => router.push(`/instruments/${m.instrumentId}`)}
              />
            ))}
            {gainers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No gainers" />
              </div>
            )}
          </div>
        )}

        {/* Data: losers column */}
        {!noWatchlist && !isLoading && (gainers.length > 0 || losers.length > 0) && (
          <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
            {losers.map((m) => (
              <WatchlistMoverRow
                key={`l-${m.instrumentId}`}
                mover={m}
                side="loser"
                onClick={() => router.push(`/instruments/${m.instrumentId}`)}
              />
            ))}
            {losers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No losers" />
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Footer: small label tying the data context together ──────── */}
      {/* WHY a footer at all: matches the rest of the dashboard widgets and
          lets users see at a glance which watchlist they're looking at when
          multiple watchlists are common (so they're not confused why a
          ticker they "added" isn't here — it's in another list). */}
      {!noWatchlist && firstWatchlist && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          <span className="text-[10px] text-muted-foreground/60">
            {firstWatchlist.name}
            {period === "1D" ? " · today" : period === "1W" ? " · 1W" : " · 1M"}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Row sub-component ────────────────────────────────────────────────────────

interface WatchlistMoverRowProps {
  mover: WatchlistMover;
  side: "gainer" | "loser";
  onClick: () => void;
}

/**
 * WatchlistMoverRow — one line of [ticker · name · price · change%].
 *
 * WHY h-7 (28px) instead of the dashboard's typical h-[22px]: spec calls
 * for a slightly taller row in this widget so the longer name column
 * (truncated) doesn't crowd the price+% on the right at col-span-5.
 * 28px = comfortable touch target while staying dense enough that 5+5
 * rows fit within Row 2's height budget.
 *
 * WHY text-[11px]: matches §0 Terminal Quality Rules data-text size.
 * Tabular-nums + font-mono on price and change% keeps columns aligned
 * across rows even when the digit count varies (e.g. $9.99 vs $192.50).
 */
function WatchlistMoverRow({ mover, side, onClick }: WatchlistMoverRowProps) {
  // Build the aria-label so SR users hear ticker + state badges in one pass
  // (instead of the dot + icon being unlabelled and silent).
  const badgeBits: string[] = [];
  if (mover.hasActiveAlert) badgeBits.push("active alert");
  if (mover.newsCount24h > 0) badgeBits.push(`${mover.newsCount24h} recent news`);
  const ariaLabel = `Open ${mover.ticker} instrument page${badgeBits.length ? `; ${badgeBits.join(", ")}` : ""}`;

  return (
    // WHY role="button" + tabIndex=0: rows are interactive but not <button>
    // elements (so we can layout-as-a-flex row with full bleed). Adding the
    // role + tab makes them accessible to keyboard + screen-reader users.
    <div
      className="flex h-7 cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick();
      }}
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
    >
      {/* PLAN-0050 T-B-2-05: active-alert dot — 6px destructive when there
          is at least one pending alert tagged to this member's entity_id.
          aria-hidden because the row's aria-label already enumerates the
          alert state textually for AT users. */}
      {mover.hasActiveAlert ? (
        <span
          className="h-[6px] w-[6px] shrink-0 rounded-full bg-destructive"
          aria-hidden="true"
          title="Active alert"
        />
      ) : (
        // Reserve the slot so ticker columns align across rows even when
        // a row has no dot — otherwise the slot collapses and tickers
        // shift left by 8px on rows with alerts.
        <span className="h-[6px] w-[6px] shrink-0" aria-hidden="true" />
      )}

      {/* Ticker — fixed slot for column alignment across rows */}
      <span className="w-[40px] shrink-0 font-mono text-[11px] font-bold tabular-nums text-foreground">
        {mover.ticker}
      </span>

      {/* Name — flex-1 + truncate so long company names don't push price
          off the right edge. min-w-0 on the parent flex row is what
          actually allows truncate to work — flex children default to
          min-content width otherwise. */}
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
        {mover.name}
      </span>

      {/* PLAN-0050 T-B-2-04: news-of-the-day icon with badge count.
          Renders only when news_count_24h > 0. Tooltip shows the top-news
          title so users can decide whether to click before navigating.
          WHY render in-row (not out of row): the user is scanning the
          gainers list and asking "did this move because of news?" — the
          icon next to the % change answers that without leaving the row. */}
      {mover.newsCount24h > 0 && (
        <span
          className="flex shrink-0 items-center gap-0.5 text-warning"
          title={mover.topNewsTitle ?? `${mover.newsCount24h} recent`}
          aria-hidden="true"
        >
          <Newspaper className="h-3 w-3" />
          <span className="font-mono text-[9px] tabular-nums">
            {mover.newsCount24h > 9 ? "9+" : mover.newsCount24h}
          </span>
        </span>
      )}

      {/* Price — right-aligned in a fixed slot. Muted color because change%
          is the primary signal; price is supporting context. */}
      <span className="w-[52px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {mover.price != null ? `$${mover.price.toFixed(2)}` : "—"}
      </span>

      {/* Change % — right-aligned, colored by direction. The `side`
          parameter reflects which column we're in, which (combined with
          the partition logic above) is always consistent with the sign
          of changePct. */}
      <span
        className={cn(
          "w-[52px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          side === "gainer" ? "text-positive" : "text-negative",
        )}
      >
        {mover.changePct != null
          ? `${mover.changePct >= 0 ? "+" : ""}${mover.changePct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}

// ── Summary strip (PLAN-0050 T-B-2-02 + T-B-2-03) ──────────────────────────

interface WatchlistSummaryStripProps {
  insights: import("@/types/api").WatchlistInsights;
}

/**
 * WatchlistSummaryStrip — single-row header showing equal-weighted return,
 * sector concentration mini-bar, and totals.
 *
 * WHY a single 22px strip (not three): the dashboard cell is height-bounded
 * (Row 2 = 130px). Stacking three header strips eats data rows. One strip
 * with three logical zones gives the user the same information density as
 * Bloomberg's account summary line.
 *
 * Sector mini-bar visual: a flex row of fills proportional to sector.weight.
 * Top-3 sectors get distinct hsl(var(--positive/warning/primary)) tints so
 * the user can tell at a glance whether their watchlist is concentrated in
 * one bucket. A 4th+ sector shows muted ("Other") to keep the strip readable.
 */
function WatchlistSummaryStrip({ insights }: WatchlistSummaryStripProps) {
  const wr = insights.weighted_return_1d;
  const wrColor =
    wr == null
      ? "text-muted-foreground"
      : wr > 0.005
        ? "text-positive"
        : wr < -0.005
          ? "text-negative"
          : "text-muted-foreground";

  // Top-3 sectors get colour; everything else collapses into "Other" so the
  // mini-bar stays scannable even on diverse 20+ symbol watchlists.
  const top3 = insights.sectors.slice(0, 3);
  const otherWeight = insights.sectors.slice(3).reduce((s, x) => s + x.weight, 0);
  // Slot colours for the top-3 buckets — chosen for legibility on the dark
  // panel background, not by sector identity (sectors aren't colour-coded
  // canonically anywhere in the design system).
  const slotColors = [
    "bg-[hsl(var(--primary))]",
    "bg-[hsl(var(--warning))]",
    "bg-[hsl(var(--positive))]",
  ] as const;

  return (
    <div
      className="flex h-[22px] shrink-0 items-center gap-2 border-b border-border/30 px-2"
      aria-label="Watchlist summary"
    >
      {/* Equal-weighted return slot */}
      <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] tabular-nums">
        <span className="text-muted-foreground">RET</span>
        <span className={wrColor}>
          {wr == null ? "—" : `${wr >= 0 ? "+" : ""}${wr.toFixed(2)}%`}
        </span>
      </span>

      {/* Members count */}
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
        · {insights.members_count} {insights.members_count === 1 ? "name" : "names"}
      </span>

      {/* Sector concentration mini-bar — flex-1 so it fills the remaining slot. */}
      <div
        className="flex h-2 flex-1 overflow-hidden rounded-[2px] bg-muted/40"
        aria-label="Sector concentration"
        title={top3.map((s) => `${s.sector} ${(s.weight * 100).toFixed(0)}%`).join(", ")}
      >
        {top3.map((s, i) => (
          <span
            key={s.sector}
            className={cn("h-full", slotColors[i])}
            style={{ width: `${s.weight * 100}%` }}
          />
        ))}
        {otherWeight > 0 && (
          <span
            className="h-full bg-muted-foreground/40"
            style={{ width: `${otherWeight * 100}%` }}
          />
        )}
      </div>

      {/* Pending-alerts counter — only shown when > 0 to keep the strip
          quiet on calm days. */}
      {insights.alerts_count > 0 && (
        <span className="flex shrink-0 items-center gap-0.5 font-mono text-[10px] tabular-nums text-destructive">
          <Bell className="h-3 w-3" aria-hidden="true" />
          <span>{insights.alerts_count}</span>
        </span>
      )}
    </div>
  );
}

// ── Biggest-news row (PLAN-0050 T-B-2-06) ──────────────────────────────────

interface BiggestNewsRowProps {
  news: import("@/types/api").WatchlistBiggestNews;
}

/**
 * BiggestNewsRow — single-line callout above the gainers/losers split.
 *
 * WHY h-7 (28px): one row's worth of vertical real estate. The article title
 * truncates with a tooltip — clicking opens the article in a new tab.
 *
 * WHY noopener,noreferrer: prevents the opened tab from accessing window.opener
 * (security — the article URL is external) and omits the Referer header.
 */
function BiggestNewsRow({ news }: BiggestNewsRowProps) {
  // PLAN-0050 T-F-6-20: honour the user's tab-target preference.
  // Defaults to new-tab so existing users see no change.
  const [target] = useNewsLinkTarget();
  const linkAttrs = newsLinkAttrs(target);
  if (!news.url || !news.title) return null;
  return (
    <a
      href={news.url}
      target={linkAttrs.target}
      rel={linkAttrs.rel}
      className="flex h-7 shrink-0 items-center gap-2 border-b border-border/30 bg-warning/5 px-2 transition-colors hover:bg-warning/10"
      aria-label={`Open biggest news: ${news.title}`}
    >
      {/* Newspaper icon + ticker chip pinned left so the title can truncate
          without pushing context off-screen. */}
      <Newspaper className="h-3 w-3 shrink-0 text-warning" aria-hidden="true" />
      {news.ticker && (
        <span className="shrink-0 font-mono text-[10px] font-bold uppercase tabular-nums text-foreground">
          {news.ticker}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-[11px] text-foreground" title={news.title}>
        {news.title}
      </span>
    </a>
  );
}
