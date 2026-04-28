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
import Link from "next/link";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";
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
 * MoverRow — internal shape for a row in the gainers/losers columns. We
 * normalise both 1D (live quote) and 1W/1M (OHLCV-derived) into the same
 * shape so the rendering loop stays simple.
 */
interface WatchlistMover {
  instrumentId: string;
  ticker: string;
  name: string;
  // For 1D: latest live price. For 1W/1M: latest close from OHLCV.
  price: number | null;
  // Percentage change over the selected period (already in percent units,
  // e.g. 2.34 not 0.0234). May be null while we are still loading the
  // backing data for that row.
  changePct: number | null;
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
    // Sort ascending by created_at (oldest first). Date.parse handles the
    // ISO 8601 strings the gateway returns. Fallback to lexicographic
    // compare if for some reason the timestamp is unparseable.
    const sorted = [...watchlists].sort((a, b) => {
      const ta = Date.parse(a.created_at);
      const tb = Date.parse(b.created_at);
      if (!Number.isNaN(ta) && !Number.isNaN(tb)) return ta - tb;
      return a.created_at.localeCompare(b.created_at);
    });
    return sorted[0] ?? null;
  }, [watchlists]);

  // ── 2. Fetch members of the chosen watchlist ────────────────────────────
  // WHY enabled gated on firstWatchlist: skip the network call entirely
  // when the user has no watchlists — prevents an unnecessary 404/empty
  // round-trip and keeps the empty-state instant.
  const { data: members, isLoading: membersLoading } = useQuery({
    queryKey: [
      "dashboard-watchlist-movers-members",
      firstWatchlist?.watchlist_id,
    ],
    queryFn: () =>
      createGateway(accessToken).getWatchlistMembers(
        firstWatchlist!.watchlist_id,
      ),
    enabled: !!accessToken && !!firstWatchlist,
    staleTime: 60_000,
  });

  // Filter to members that have a resolved instrument_id — pending /
  // unresolved members can't be priced.
  const resolvedMembers = useMemo(
    () => (members ?? []).filter((m) => !!m.instrument_id),
    [members],
  );

  const instrumentIds = useMemo(
    () =>
      resolvedMembers
        .map((m) => m.instrument_id)
        .filter((id): id is string => !!id),
    [resolvedMembers],
  );

  // ── 3a. 1D path — live batch quotes ────────────────────────────────────
  // WHY a single batch quotes call: avoids N round-trips. S9 already has
  // a 5s Valkey cache so this is cheap server-side.
  // WHY staleTime 60_000: live ticks change second-by-second but for a
  // dashboard widget a 1-min refresh is the right cost/value tradeoff —
  // matches PreMarketMoversWidget.
  // WHY enabled gates on period === "1D": we only want to incur the cost
  // when this is the active path.
  const {
    data: batchQuotes,
    isLoading: quotesLoading,
  } = useQuery({
    queryKey: [
      "dashboard-watchlist-movers-quotes",
      firstWatchlist?.watchlist_id,
      instrumentIds,
    ],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled:
      !!accessToken &&
      period === "1D" &&
      instrumentIds.length > 0,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // ── 3b. 1W / 1M path — per-instrument OHLCV ─────────────────────────────
  // WHY useQueries (not Promise.all in a single query): each instrument's
  // OHLCV cache is keyed on (id, timeframe), so we get free per-instrument
  // memoisation. If the user toggles sectors the cached responses persist.
  // WHY enabled gates on period !== "1D" AND instrumentIds.length > 0:
  // we don't fan out 50 OHLCV requests just because the page mounted.
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

  // ── 4. Per-instrument sector lookup (Wave F-2 reuse) ───────────────────
  // WHY dedupe by instrument_id: a watchlist shouldn't have duplicates
  // but defensive — duplicate query keys produce TanStack warnings.
  // WHY staleTime 600_000: GICS sector almost never changes for a stock
  // (and never within a session) — cache aggressively.
  const overviewQueries = useQueries({
    queries: instrumentIds.map((id) => ({
      queryKey: ["mover-overview-sector", id],
      // Same query key as PreMarketMoversWidget so TanStack dedupes the
      // network call — the dashboard doesn't fetch the same overview
      // twice across two widgets.
      queryFn: () => createGateway(accessToken).getCompanyOverview(id),
      enabled: !!accessToken && !!id,
      staleTime: 600_000,
    })),
  });

  const sectorByInstrumentId = useMemo(() => {
    const map = new Map<string, string | null | undefined>();
    instrumentIds.forEach((id, i) => {
      map.set(id, overviewQueries[i]?.data?.instrument?.gics_sector);
    });
    return map;
  }, [instrumentIds, overviewQueries]);

  // ── 5. Build the mover rows (period-aware) ────────────────────────────
  // We map every member into a `WatchlistMover` then sort and split into
  // gainers / losers below. Computing once via useMemo prevents the work
  // from running on every keystroke / hover.
  const movers: WatchlistMover[] = useMemo(() => {
    return resolvedMembers
      .map((m, idx) => {
        const instrumentId = m.instrument_id!;
        // Member name/ticker may be null when local instrument cache missed
        // at add-time (BP-126-ish: "—" fallback in the gateway). Prefer
        // ticker, then "—".
        const ticker = m.ticker ?? "—";
        const name = m.name ?? "—";

        if (period === "1D") {
          const q = batchQuotes?.quotes?.[instrumentId];
          if (!q) {
            return {
              instrumentId,
              ticker,
              name,
              price: null,
              changePct: null,
            } satisfies WatchlistMover;
          }
          return {
            instrumentId,
            ticker,
            name,
            price: q.price ?? null,
            changePct: q.change_pct ?? null,
          } satisfies WatchlistMover;
        }

        // 1W / 1M: derive from first→last close in the OHLCV bars array.
        const ohlcv = ohlcvQueries[idx]?.data;
        const bars = ohlcv?.bars ?? [];
        if (bars.length < 2) {
          return {
            instrumentId,
            ticker,
            name,
            price: null,
            changePct: null,
          } satisfies WatchlistMover;
        }
        const first = bars[0]!.close;
        const last = bars[bars.length - 1]!.close;
        if (first <= 0) {
          // Defensive: avoid divide-by-zero / negative-price garbage from a
          // bad ingestion.
          return {
            instrumentId,
            ticker,
            name,
            price: last,
            changePct: null,
          } satisfies WatchlistMover;
        }
        const pct = ((last - first) / first) * 100;
        return {
          instrumentId,
          ticker,
          name,
          price: last,
          changePct: pct,
        } satisfies WatchlistMover;
      });
    // We deliberately keep rows with `changePct === null` in the array;
    // the gainers/losers split below filters them out via the
    // `m.changePct != null && > 0 / < 0` predicates, which avoids
    // the loaded vs. loading flicker.
  }, [resolvedMembers, period, batchQuotes, ohlcvQueries]);

  // ── 6. Apply sector filter ────────────────────────────────────────────
  // WHY graceful "still loading" behaviour (don't hide unloaded sectors):
  // matches PreMarketMoversWidget — overview queries stream in
  // independently and we don't want flicker.
  const filtered = useMemo(() => {
    if (selectedSector === ALL_SECTORS_VALUE) return movers;
    return movers.filter((m) => {
      const sector = sectorByInstrumentId.get(m.instrumentId);
      if (sector === undefined) return true; // overview not loaded yet
      return matchesSectorFilter(sector, selectedSector);
    });
  }, [movers, selectedSector, sectorByInstrumentId]);

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

  // ── 8. Loading composition ────────────────────────────────────────────
  // WHY combine watchlist + members + (period-specific data) loading: the
  // user shouldn't see a partially-rendered widget. Once *any* of these
  // complete unsuccessfully we fall through to the empty/no-data branch.
  const periodDataLoading =
    period === "1D"
      ? quotesLoading
      : ohlcvQueries.some((q) => q.isLoading);
  const isLoading =
    watchlistsLoading ||
    (!!firstWatchlist && (membersLoading || periodDataLoading));

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

        {/* Empty: no watchlist at all */}
        {noWatchlist && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-2 text-center">
            <span className="text-[12px] text-muted-foreground">
              No watchlist yet
            </span>
            <span className="text-[11px] leading-snug text-muted-foreground/80">
              Add instruments to your watchlist to see daily movers here.
            </span>
            {/* WHY a Link (not a router.push button): semantic anchor
                gives "open in new tab" middle-click and keyboard
                navigation for free. /screener is the canonical entry
                point for adding new tickers to a watchlist. */}
            <Link
              href="/screener"
              className="text-[11px] text-primary hover:underline"
            >
              Browse Screener →
            </Link>
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
      aria-label={`Open ${mover.ticker} instrument page`}
    >
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
