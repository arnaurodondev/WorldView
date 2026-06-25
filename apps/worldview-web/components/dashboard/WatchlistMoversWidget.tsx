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

// W4 pagination: useRef/useEffect added for the IntersectionObserver sentinel
// that windows the gainers/losers columns in blocks of 30 (client-side).
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, Eye } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
// Round 3 (item 4): the panel-level no-watchlist state migrates from the
// legacy DashboardEmptyState (components/ui — still used by workspace and
// screener surfaces) onto the shared EmptyState primitive (§15.12).
// InlineEmptyState stays for the in-column "No gainers"/"No losers" lines.
import { EmptyState } from "@/components/primitives/EmptyState";
import Link from "next/link";
import { cn } from "@/lib/utils";

// ── PLAN-0059 E-5 — extracted sub-components + ranking logic ─────────────
// The widget used to be 800 LOC; the row/summary/news-row sub-components
// + the period-aware row builder + sector filter + abs(%) ranking + 5/5
// partition all lived in this file. They now live under
// `features/dashboard/`. The pure functions are unit-tested in
// `features/dashboard/lib/__tests__/movers.test.ts` (19 tests).
import { WatchlistMoverRow } from "@/features/dashboard/components/WatchlistMoverRow";
import { WatchlistSummaryStrip } from "@/features/dashboard/components/WatchlistSummaryStrip";
import { BiggestNewsRow } from "@/features/dashboard/components/BiggestNewsRow";
import {
  buildMoverRows,
  applySectorFilter,
  rankByAbsChangePct,
  splitGainersLosers,
  pickFirstWatchlistByCreatedAt,
  type WatchlistPeriod,
} from "@/features/dashboard/lib/movers";

// PLAN-0048 Wave F-2: shared sector pill module (also used by F-1
// SectorHeatmapWidget and F-2 PreMarketMoversWidget). Importing the same
// constants/predicate guarantees consistent ordering, labels, and matching
// rules across every movers widget in the dashboard.
import { SECTOR_PILLS, ALL_SECTORS_VALUE } from "@/lib/sectors";

/**
 * PAGE_SIZE — block size for the client-side infinite-scroll window.
 *
 * W4 pagination (user report 2026-06-12 "display in blocks of 30"): the
 * gainers/losers columns previously hard-capped each side at 5 (via
 * splitGainersLosers' default topN). They now reveal in blocks of 30 per side
 * via an IntersectionObserver sentinel inside the panel's own scroll area —
 * the watchlist members + insights come back in one round-trip, so this windows
 * a client-side array (same pattern as HoldingsMoversWidget / Top Positions).
 */
const PAGE_SIZE = 30;

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
  const { data: watchlists, isLoading: watchlistsLoading, isError: watchlistsError, refetch: refetchWatchlists } = useQuery({
    queryKey: ["dashboard-watchlist-movers-watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // WHY useMemo on the chosen watchlist: keeps the dependency stable for
  // every downstream useQuery key — without it React would re-run the
  // queries on every render even though `firstWatchlist` resolves to the
  // same object.
  // PLAN-0059 E-5: deterministic "default watchlist" picker now lives in
  // features/dashboard/lib/movers.ts as a pure function (unit-tested).
  const firstWatchlist = useMemo(
    () => pickFirstWatchlistByCreatedAt(watchlists),
    [watchlists],
  );

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
  const enrichedMovers = useMemo(() => insights?.movers ?? [], [insights]);
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

  // ── 4-7. Build → filter → rank → split (PLAN-0059 E-5 pure functions) ──
  // The previous ~70 LOC of inline derivation is now four small calls into
  // `features/dashboard/lib/movers.ts`. Behaviour is identical (covered by
  // 19 unit tests in movers.test.ts):
  //   buildMoverRows: 1D pass-through; 1W/1M overrides price+change_pct
  //                   from per-instrument OHLCV first→last close
  //   applySectorFilter: keeps null-sector rows visible while loading
  //   rankByAbsChangePct: descending |change_pct|; null rows to bottom
  //   splitGainersLosers: top-5 each side; drops null/zero rows
  const ohlcvData = useMemo(
    () => ohlcvQueries.map((q) => q.data),
    [ohlcvQueries],
  );
  const movers = useMemo(
    () => buildMoverRows(enrichedMovers, period, ohlcvData),
    [enrichedMovers, period, ohlcvData],
  );
  const filtered = useMemo(
    () => applySectorFilter(movers, selectedSector),
    [movers, selectedSector],
  );
  // W4 pagination: split into the FULL ranked columns (topN = Infinity, no
  // longer the default 5) so deeper movers stay available; the visible slice is
  // windowed below by the infinite-scroll state.
  const { gainers: allGainers, losers: allLosers } = useMemo(
    () => splitGainersLosers(rankByAbsChangePct(filtered), Number.POSITIVE_INFINITY),
    [filtered],
  );

  // ── Infinite-scroll window state (W4 pagination) ──────────────────────────
  // visibleCount grows by PAGE_SIZE per sentinel intersection and applies to
  // BOTH columns symmetrically (the scroll area is shared).
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const hasMore =
    visibleCount < allGainers.length || visibleCount < allLosers.length;

  // WHY reset on data identity / period / sector changing: those rebuild the
  // movers — rewind the window so the user starts at the top of the new list.
  const moversIdentity =
    `${period}:${selectedSector}:${allGainers.length}:${allLosers.length}:` +
    `${allGainers[0]?.instrumentId ?? ""}:${allLosers[0]?.instrumentId ?? ""}`;
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [moversIdentity]);

  const gainers = useMemo(
    () => allGainers.slice(0, visibleCount),
    [allGainers, visibleCount],
  );
  const losers = useMemo(
    () => allLosers.slice(0, visibleCount),
    [allLosers, visibleCount],
  );

  // ── Infinite-scroll sentinel (IntersectionObserver) ───────────────────────
  // A 1px row after the columns inside the shared overflow-auto container;
  // scrolling it into view reveals the next PAGE_SIZE rows in both columns.
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasMore) {
          setVisibleCount((c) => c + PAGE_SIZE);
        }
      },
      { threshold: 0.5 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore]);

  // ── 7. Loading composition ────────────────────────────────────────────
  // WHY combine watchlist + insights + (period-specific data) loading: the
  // user shouldn't see a partially-rendered widget. Once *any* of these
  // complete unsuccessfully we fall through to the empty/no-data branch.
  const periodDataLoading =
    period === "1D" ? false : ohlcvQueries.some((q) => q.isLoading);
  const isLoading =
    watchlistsLoading || (!!firstWatchlist && (insightsLoading || periodDataLoading));

  // WHY isError: surface a Retry when the watchlist fetch fails — otherwise
  // the user sees a permanently blank widget with no feedback.
  const isError = watchlistsError;
  const handleRetry = () => { void refetchWatchlists(); };

  // ── 9. Empty state (no watchlist) ─────────────────────────────────────
  const noWatchlist = !watchlistsLoading && !watchlistsError && !firstWatchlist;

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
              // Round 3 (item 5): bg-muted hover convention + keyboard ring.
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
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
      {!isError && !noWatchlist && (
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
                  // WHY rounded-[2px]: design system mandates 2px radius; bare `rounded` = 4px default
                  // Round 3 (item 5): keyboard focus ring on the pill toggles.
                  "shrink-0 rounded-[2px] border border-border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
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
      {!isError && !noWatchlist && period === "1D" && insights && (
        <WatchlistSummaryStrip insights={insights} />
      )}

      {/* ── Single-biggest-news callout (PLAN-0050 T-B-2-06) ───────────
          Above the gainers/losers split so the highest-impact story
          touching any watchlist member is the first thing the user
          reads. Click opens the article (new tab, noopener). */}
      {!isError && !noWatchlist && period === "1D" && insights?.biggest_news?.title && (
        <BiggestNewsRow news={insights.biggest_news} />
      )}

      {/* ── Sub-headers: GAINERS | LOSERS ─────────────────────────────── */}
      {/* WHY render these even in the empty-state path: keeping the static
          chrome consistent makes the empty state feel like a deliberate
          state, not a broken widget. Hidden when there's no watchlist
          since the panel is fully replaced by the empty-state CTA. */}
      {!isError && !noWatchlist && (
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
      {/* W4: flex-COL so the two-column row + the infinite-scroll sentinel
          stack vertically inside the shared overflow-auto scroll area. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">

        {/* ── Error state ────────────────────────────────────────────────── */}
        {/* WHY min-h-[140px]: 5 rows × h-7 (28px) = 140px; prevents the
            widget from collapsing to zero height when the watchlist fetch
            fails cold (no cached data). */}
        {isError && (
          <div className="flex flex-1 min-h-[140px] items-center justify-center gap-2">
            <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
            <span className="text-xs text-muted-foreground">Failed to load</span>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={handleRetry}>
              Retry
            </Button>
          </div>
        )}

        {/* Empty: no watchlist at all (PLAN-0050 T-F-6-04 — DashboardEmptyState).
            Why the shared component: the prior bespoke 3-element JSX block
            duplicated the heading/message/CTA pattern that already lived in
            DashboardEmptyState. Using the shared component pins the visual
            voice across all dashboard widgets — no widget can drift on the
            empty-state pattern after this. */}
        {!isError && noWatchlist && (
          <div className="flex flex-1 items-center justify-center">
            {/* Round 3 (item 4): shared EmptyState primitive — copy key keeps
                the test-pinned "No watchlist yet" title; the action Link keeps
                the Browse-Screener CTA with a keyboard focus ring. */}
            <EmptyState
              condition="empty-cold-start"
              copyKey="dashboard.no-watchlist"
              icon={Eye}
              action={
                <Link
                  href="/screener"
                  className="font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Browse Screener →
                </Link>
              }
            />
          </div>
        )}

        {/* Loading: show 5 placeholder rows in each column */}
        {!isError && !noWatchlist && isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {/* Round 3 (item 3): h-7 matches the loaded WatchlistMoverRow
                  height (28px — NOT the dashboard's usual 22px, see the row
                  component's WHY) and the 4 cells mirror its column slots
                  (ticker 40 · name flex · price 52 · %chg 52) so rows swap
                  in without any height or column shift. */}
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={`g-skel-${i}`} className="flex h-7 items-center gap-1.5 px-2">
                  <Skeleton className="h-3 w-[40px] shrink-0" />
                  <Skeleton className="h-3 min-w-0 flex-1" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={`l-skel-${i}`} className="flex h-7 items-center gap-1.5 px-2">
                  <Skeleton className="h-3 w-[40px] shrink-0" />
                  <Skeleton className="h-3 min-w-0 flex-1" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty: watchlist exists but no movers (rare — flat day) */}
        {!isError &&
          !noWatchlist &&
          !isLoading &&
          gainers.length === 0 &&
          losers.length === 0 && (
            <div className="flex-1 px-2">
              <InlineEmptyState message="No movers in this watchlist" />
            </div>
          )}

        {/* Data: two-column row (gainers | losers) + infinite-scroll sentinel.
            W4: wrapped in a row so the sentinel below spans the full width
            beneath both columns. */}
        {!isError && !noWatchlist && !isLoading && (gainers.length > 0 || losers.length > 0) && (
          <>
            <div className="flex">
              {/* Gainers column */}
              <div className="flex-1 divide-y divide-border/30">
                {gainers.map((m) => (
                  <WatchlistMoverRow
                    key={`g-${m.instrumentId}`}
                    mover={m}
                    side="gainer"
                    showEnrichmentBadges={period === "1D"}
                    // PRD-0089 F2 step 11 (§6.6): ticker-first URL.
                    onClick={() =>
                      router.push(`/instruments/${m.ticker || m.instrumentId}`)
                    }
                  />
                ))}
                {gainers.length === 0 && (
                  <div className="px-2">
                    <InlineEmptyState message="No gainers" />
                  </div>
                )}
              </div>
              {/* Losers column */}
              <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
                {losers.map((m) => (
                  <WatchlistMoverRow
                    key={`l-${m.instrumentId}`}
                    mover={m}
                    side="loser"
                    showEnrichmentBadges={period === "1D"}
                    // PRD-0089 F2 step 11 (§6.6): ticker-first URL.
                    onClick={() =>
                      router.push(`/instruments/${m.ticker || m.instrumentId}`)
                    }
                  />
                ))}
                {losers.length === 0 && (
                  <div className="px-2">
                    <InlineEmptyState message="No losers" />
                  </div>
                )}
              </div>
            </div>

            {/* ── Infinite-scroll sentinel + footer (W4 pagination) ──────────
                1px sentinel beneath both columns inside the SAME overflow-auto
                scroll area; scrolling reveals the next PAGE_SIZE rows in both
                columns. Caption shows how many of each side are shown. */}
            {hasMore ? (
              <div
                ref={sentinelRef}
                data-testid="watchlist-movers-sentinel"
                className="flex items-center justify-center py-1 text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim"
                aria-hidden
              >
                <span className="font-mono tabular-nums">
                  {Math.min(visibleCount, allGainers.length)}/{allGainers.length} ·{" "}
                  {Math.min(visibleCount, allLosers.length)}/{allLosers.length} · scroll for more
                </span>
              </div>
            ) : (
              (allGainers.length > PAGE_SIZE || allLosers.length > PAGE_SIZE) && (
                <div className="flex items-center justify-center py-1 text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim">
                  <span className="font-mono tabular-nums">all shown</span>
                </div>
              )
            )}
          </>
        )}
      </div>

      {/* ── Footer: small label tying the data context together ──────── */}
      {/* WHY a footer at all: matches the rest of the dashboard widgets and
          lets users see at a glance which watchlist they're looking at when
          multiple watchlists are common (so they're not confused why a
          ticker they "added" isn't here — it's in another list). */}
      {!isError && !noWatchlist && firstWatchlist && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          <span className="text-[10px] text-muted-foreground-dim">
            {firstWatchlist.name}
            {period === "1D" ? " · today" : period === "1W" ? " · 1W" : " · 1M"}
          </span>
        </div>
      )}
    </div>
  );
}
