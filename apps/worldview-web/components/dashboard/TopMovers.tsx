/**
 * components/dashboard/TopMovers.tsx — Top gainers / losers widget (Round 1 redesign)
 *
 * WHY THIS EXISTS: Traders scan for outliers — stocks with unusual daily moves
 * signal events worth investigating. TopMovers surfaces these instantly without
 * requiring a screener query. Bloomberg's "Market Movers" screen is a direct analogue.
 *
 * ROUND 1 FOUNDATION REDESIGN (2026-06-10) — replaces the horizontal tile
 * scroller with a vertical row list behind shadcn Tabs:
 *   - Two tabs: Gainers / Losers (shadcn <Tabs>, terminal variant — keyboard
 *     navigation and aria-selected handled by Radix for free).
 *   - Each row: ticker · name · 5-day sparkline · price · % change.
 *   - Row click navigates to /instruments/[ticker] (PRD-0089 F2 ticker-first
 *     URLs — the [ticker] route segment resolves tickers AND UUIDs).
 *
 * DATA PATH (three queries, all batched — no per-row fan-out):
 *   1. getTopMovers(type, 10)            → S9 /v1/market/top-movers (S3 period-movers).
 *      The wire rows are {instrument_id, ticker, name, period_return_pct} —
 *      NO price field. transformTopMoversResponse maps them to Mover[].
 *   2. getCompanyOverviewsBatch(ids)     → ONE POST /v1/companies/overviews:batch.
 *      Supplies quote.price (the S3 movers payload has none) so rows never
 *      show $0.00 for a real ticker (same fix as PreMarketMoversWidget).
 *   3. getMarketSparklines(ids, 5)       → ONE GET /v1/market/sparklines?days=5.
 *      5-day close arrays (oldest-first) for the per-row <Sparkline>.
 *
 * WHY queryKey = qk.dashboard.topMovers({type, limit, period}):
 *   DashboardBundleHydrator seeds EXACTLY these keys from the F-2 bundle's
 *   top_gainers/top_losers legs (after applying the same transform). Matching
 *   the key means this widget renders from the hydrated cache on cold start
 *   without firing its own initial fetch.
 *
 * WHO USES IT: components/dashboard/MoversWidgetTabs.tsx (MARKET tab).
 * DESIGN REFERENCE: Round 1 foundation spec §3; PRD-0028 §6.5 Dashboard TopMovers.
 */

"use client";
// WHY "use client": uses useInfiniteQuery/useQuery (data), useState (tab
// toggle), useRouter (nav), useRef + useEffect (IntersectionObserver sentinel).

import { useEffect, useMemo, useRef, useState } from "react";
import {
  useQuery,
  useInfiniteQuery,
  type InfiniteData,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Sparkline } from "@/components/primitives/Sparkline";
// Round 3 (item 4): panel-level empty state uses the shared EmptyState
// primitive (§15.12) with the named dashboard.no-movers copy key.
import { EmptyState } from "@/components/primitives/EmptyState";
// Round 4 (item 1): the bespoke muted error TEXT becomes a named error state
// with a Retry action — the old copy ("data will appear when market data is
// ingested") also misdiagnosed a fetch failure as a data gap.
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
import { TrendingUp } from "lucide-react";
// HF-10: locale-grouped USD price ("$4,892.11").
// formatPriceCompact: collapses very large prices (≥$1M, e.g. "$1.20M") to a
// suffix so they don't overflow the fixed price slot; below $1M it stays
// full-precision (the whitespace-nowrap + row overflow-hidden clamping handles
// the rest). formatChangePct: bounds extreme % moves so they fit the fixed
// w-[52px] %-change slot (see lib/format.ts).
import { formatPriceCompact, formatChangePct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Mover, TopMoversResponse } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type MoverType = "gainers" | "losers";

/**
 * MOVERS_PAGE_SIZE — block size for the infinite-scroll movers list.
 *
 * W4 pagination (user report 2026-06-12 "display in blocks of 30"): the MARKET
 * movers list now paginates the universe-wide leaderboard in blocks of 30 via
 * `useInfiniteQuery` + an IntersectionObserver sentinel — the SAME pattern as
 * PredictionMarketsWidget. The S9 `/v1/market/top-movers` endpoint supports
 * `limit` + `offset` (see lib/api/dashboard.ts getTopMovers), so each scroll
 * fetches the next 30 movers of the sorted universe. Previously the list was
 * hard-capped at 10 with no way to see deeper movers.
 */
const MOVERS_PAGE_SIZE = 30;

/** Sparkline window — Round 1 spec: 5 trading days of closes per row. */
const SPARKLINE_DAYS = 5;

// ── Component ─────────────────────────────────────────────────────────────────

export function TopMovers() {
  const { accessToken } = useAuth();
  const [type, setType] = useState<MoverType>("gainers");

  // ── Movers query (per active tab, paginated) ──────────────────────────────
  // WHY fetch only the ACTIVE tab (not both): switching tabs is the explicit
  // user intent to see the other side; fetching the inactive side up-front
  // doubles network cost for a view the user may never open.
  //
  // W4 PAGINATION: replaces the single capped-at-10 `useQuery` with
  // `useInfiniteQuery` so the trader can scroll past the first block into the
  // deeper leaderboard. Each page is `MOVERS_PAGE_SIZE` movers fetched via the
  // endpoint's `offset` param (same pattern as PredictionMarketsWidget).
  //
  // HYDRATION NOTE: the previous `useQuery` key matched DashboardBundleHydrator's
  // seed (qk.dashboard.topMovers({type, limit:10, period:"1D"})) so the MARKET
  // tab rendered from the cold-start bundle without a fetch. An infinite query
  // stores `InfiniteData<TopMoversResponse>` under a DIFFERENT key shape, so the
  // flat seed no longer matches and the first page is fetched here on mount
  // (one request). The hydrator is owned by another surface — if the cold-start
  // saving is wanted back, it should seed the infinite-query first page under
  // this key; documented as a follow-up (see FINAL REPORT).
  // Round 4 (item 1): refetch + isFetching destructured for the Retry action.
  const {
    data,
    isLoading,
    isError,
    refetch,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery<
    TopMoversResponse,
    Error,
    InfiniteData<TopMoversResponse>,
    readonly unknown[],
    number
  >({
    // WHY a dedicated infinite key (not qk.dashboard.topMovers): the cached
    // shape is now InfiniteData, distinct from the flat seed — a separate key
    // namespace avoids ever reading the flat hydrator seed as if it were paged.
    queryKey: ["dashboard-top-movers-infinite", type],
    queryFn: ({ pageParam }) =>
      createGateway(accessToken).getTopMovers(type, MOVERS_PAGE_SIZE, "1D", pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // WHY length-based: the S3 movers payload has no `total`, so we infer
      // "more pages exist" from a FULL last page. A short page = the end of the
      // (finite) universe. `offset` for the next page is the count loaded so far.
      const loaded = allPages.reduce((n, p) => n + p.movers.length, 0);
      return lastPage.movers.length === MOVERS_PAGE_SIZE ? loaded : undefined;
    },
    enabled: !!accessToken,
    // WHY 60s: market movers are a macro view, not a real-time tick feed.
    // (refetchInterval re-fetches ALL loaded pages — acceptable for the 1-3
    // pages a trader typically scrolls; deeper pages age out via gcTime.)
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // WHY useMemo: flattening `?? []` would mint a fresh array reference each
  // render and invalidate the downstream id-list memo (PreMarketMovers pattern).
  const movers: Mover[] = useMemo(
    () => data?.pages.flatMap((p) => p.movers) ?? [],
    [data],
  );

  // ── Infinite-scroll sentinel (IntersectionObserver) ────────────────────────
  // Same pattern as PredictionMarketsWidget: a 1px div after the last row
  // inside the SAME overflow-y-auto tab panel; when it becomes half-visible we
  // pull the next page. The guard on !isFetchingNextPage prevents duplicate
  // parallel fetches if the sentinel lingers in view during a fetch.
  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { threshold: 0.5 },
    );
    observer.observe(sentinel);
    // Disconnect on cleanup so the observer can't fetch a stale query after
    // unmount (dashboard navigation) or after the active tab switches.
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Stable id list for the two batch lookups below.
  const moverIds = useMemo(
    () => movers.map((m) => m.instrument_id).filter(Boolean),
    [movers],
  );

  // ── Price patch: batched company overviews ────────────────────────────────
  // WHY: the S3 period-movers payload carries NO price (rows are just
  // {instrument_id, ticker, name, period_return_pct}), so Mover.price is 0
  // after the transform. quote.price from the overview batch uses the full
  // PriceSnapshot fallback chain (FRESH_QUOTE → … → DAILY_CLOSE) — one HTTP
  // request for all rows. Failure degrades to "—" per row, never an error.
  const { data: overviewsMap } = useQuery({
    queryKey: qk.instruments.overviewsBatch(moverIds),
    queryFn: () => createGateway(accessToken).getCompanyOverviewsBatch(moverIds),
    enabled: !!accessToken && moverIds.length > 0,
    // WHY 10min: last-trade price on a 1-min-refresh dashboard widget is
    // context, not the signal — the % change is. Aggressive caching avoids
    // re-fetching 10 overviews on every tab flip.
    staleTime: 600_000,
  });
  const priceByInstrumentId = useMemo(() => {
    const map = new Map<string, number>();
    movers.forEach((m) => {
      const price = (overviewsMap ?? {})[m.instrument_id]?.quote?.price;
      if (typeof price === "number" && price > 0) map.set(m.instrument_id, price);
    });
    return map;
  }, [movers, overviewsMap]);

  // ── 5-day sparkline series (one batch request) ────────────────────────────
  // WHY retry: 1 — sparklines are decorative; if the endpoint is down the
  // rows still render fully functional with a dashed placeholder line.
  const { data: sparkSeries } = useQuery({
    queryKey: ["top-movers-sparklines", type, ...moverIds],
    queryFn: () =>
      createGateway(accessToken).getMarketSparklines(moverIds, SPARKLINE_DAYS),
    enabled: !!accessToken && moverIds.length > 0,
    // WHY 15min: end-of-day close arrays change at most once per session.
    staleTime: 15 * 60_000,
    retry: 1,
  });

  return (
    // WHY h-full flex-col: fills the MoversWidgetTabs panel so the row list
    // can scroll independently inside the Row-3 grid cell.
    <div className="flex h-full min-h-0 flex-col bg-background">
      <Tabs
        value={type}
        // WHY cast: Radix emits string; the two TabsTriggers below are the
        // only possible values so the narrow cast is safe.
        onValueChange={(v) => setType(v as MoverType)}
        className="flex h-full min-h-0 flex-col"
      >
        {/* WHY terminal variant + h-6 override: matches the 24px header rhythm
            of every other dashboard widget (Bloomberg density rule) — the
            default shadcn pill row is 36px which would steal two data rows. */}
        <TabsList variant="terminal" className="h-6 w-full shrink-0">
          {/* WHY lowercase label + CSS capitalize: existing tests (and the
              terminal chrome convention) match the literal text "gainers" /
              "losers"; the capitalize class handles presentation. */}
          <TabsTrigger
            value="gainers"
            variant="terminal"
            className="h-6 flex-1 font-mono text-[10px] uppercase tracking-[0.08em] data-[state=active]:text-positive"
          >
            gainers
          </TabsTrigger>
          <TabsTrigger
            value="losers"
            variant="terminal"
            className="h-6 flex-1 font-mono text-[10px] uppercase tracking-[0.08em] data-[state=active]:text-negative"
          >
            losers
          </TabsTrigger>
        </TabsList>

        {/* WHY a single shared panel body rendered per tab value: both tabs
            show the same row layout — only the data side differs. TabsContent
            keeps Radix a11y wiring (aria-labelledby/role=tabpanel) intact.
            WHY mt-0 override: TabsContent defaults to mt-2; the dense
            terminal layout wants the rows flush under the tab strip. */}
        {(["gainers", "losers"] as const).map((side) => (
          <TabsContent
            key={side}
            value={side}
            className="mt-0 min-h-0 flex-1 overflow-y-auto"
          >
            {/* Loading: fixed-height skeleton rows prevent layout jump.
                Round 3 (item 3): cells mirror the loaded MoverRow's 5 column
                slots (ticker 44 · name flex · sparkline 40×14 · price 60 ·
                %chg 52) — the previous 3-cell version visibly re-laid-out
                when the sparkline/price columns appeared. */}
            {isLoading && (
              <div className="divide-y divide-border/30">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex h-[22px] items-center gap-1.5 px-2">
                    <Skeleton className="h-3 w-[44px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
                    <Skeleton className="h-3 min-w-0 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
                    <Skeleton className="h-[14px] w-[40px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
                    <Skeleton className="h-3 w-[60px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
                    <Skeleton className="h-3 w-[52px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
                  </div>
                ))}
              </div>
            )}

            {/* Error — Round 4 (item 1): named error state + Retry replaces
                the bespoke muted text. The old copy claimed "data will appear
                when market data is ingested" for what is a FETCH failure —
                wrong triage signal. WHY flex h-full wrapper: centres the
                state in the tab panel the same way the empty state below is. */}
            {!isLoading && isError && (
              <div className="flex h-full flex-col">
                <WidgetErrorState
                  copyKey="dashboard.movers-error"
                  icon={TrendingUp}
                  onRetry={() => void refetch()}
                  retrying={isFetching}
                />
              </div>
            )}

            {/* Empty — only when the fetch succeeded but the side is empty
                (e.g. pre-market with no negative movers yet).
                Round 3 (item 4): shared EmptyState primitive + named copy key
                (the side has zero rows → panel-level condition, not an
                in-table message). */}
            {!isLoading && !isError && movers.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <EmptyState
                  condition="empty-no-data"
                  copyKey="dashboard.no-movers"
                  icon={TrendingUp}
                />
              </div>
            )}

            {/* Data rows + infinite-scroll sentinel (W4 pagination) */}
            {!isLoading && !isError && movers.length > 0 && (
              <>
                <div className="divide-y divide-border/30">
                  {movers.map((mover) => (
                    <MoverRow
                      key={mover.instrument_id}
                      // WHY spread with price patch: see priceByInstrumentId WHY.
                      mover={{
                        ...mover,
                        price: priceByInstrumentId.get(mover.instrument_id) ?? mover.price,
                      }}
                      sparkline={sparkSeries?.[mover.instrument_id]}
                    />
                  ))}
                </div>

                {/* Infinite-scroll sentinel — 1px tall (h-px) so it never shifts
                    layout but is still intersectable inside the overflow-y-auto
                    panel; rendered ONLY while more pages exist so the observer
                    naturally stops at the end of the universe. Only the ACTIVE
                    Radix tab panel is mounted, so the single `sentinelRef`
                    attaches to the visible side's sentinel. */}
                {hasNextPage && (
                  <div
                    ref={sentinelRef}
                    data-testid="top-movers-sentinel"
                    className="h-px"
                    aria-hidden
                  />
                )}

                {/* In-flight indicator for the next page — keeps the bottom edge
                    truthful while rows stream in (no spinner: §6.2 static rule). */}
                {isFetchingNextPage && (
                  <div className="flex h-[22px] items-center justify-center">
                    <span className="text-[10px] text-muted-foreground-dim">loading more…</span>
                  </div>
                )}
              </>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

// ── MoverRow ──────────────────────────────────────────────────────────────────

interface MoverRowProps {
  mover: Mover;
  /** 5-day close series (oldest-first) — undefined while loading / on miss. */
  sparkline?: number[];
}

/**
 * MoverRow — ticker · name · 5-day sparkline · price · % change (22px row).
 *
 * WHY this column order: identification first (ticker+name), trend context in
 * the middle (sparkline), then the two numbers right-aligned so they scan as
 * columns. ADR-F-15: all numeric values font-mono + tabular-nums.
 *
 * WHY clickable: rows navigate to the instrument detail page so traders can
 * dive directly from the mover list into the full chart + fundamentals view.
 */
function MoverRow({ mover, sparkline }: MoverRowProps) {
  const router = useRouter();

  // PRD-0089 F2 step 11 (§6.6): ticker-first URL. F2 superseded ADR-F-12 —
  // entity_id === instrument_id (M-017) for tradable kinds, so the URL slug is
  // the analyst-friendly ticker symbol. Fallback chain (ticker → entity_id →
  // instrument_id) preserves resilience: the [ticker] route middleware also
  // resolves UUIDs via resolve_security_id.
  const navId = mover.ticker || mover.entity_id || mover.instrument_id;

  const isUp = mover.change_pct >= 0;

  return (
    // WHY h-[22px]: §0 Terminal Quality Rules mandate 22px data rows.
    // WHY role="button" + tabIndex: keyboard nav — Tab + Enter navigates.
    <div
      // Round 3 (item 5): inset focus-visible ring — rows are tabbable
      // (tabIndex=0) and need a visible keyboard-focus affordance.
      // 2026-06-19 wrap fix: min-w-0 + overflow-hidden CLIP any horizontal
      // overflow inside the fixed 22px row instead of letting it bleed past the
      // column edge into the sibling list (see docs/audits/2026-06-19-winners-losers-wrap.md).
      className="flex h-[22px] min-w-0 cursor-pointer items-center gap-1.5 overflow-hidden px-2 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      onClick={() => router.push(`/instruments/${navId}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(`/instruments/${navId}`);
      }}
      role="button"
      tabIndex={0}
      aria-label={`Navigate to ${mover.ticker} instrument page`}
    >
      {/* Ticker — fixed 44px for column alignment.
          overflow-hidden + whitespace-nowrap: a long fallback ticker (e.g. the
          first word of a company name) is CLIPPED to 44px rather than bleeding
          into the name span. */}
      <span className="w-[44px] shrink-0 overflow-hidden whitespace-nowrap font-mono text-[11px] tabular-nums text-foreground">
        {mover.ticker}
      </span>

      {/* Company name — flexible middle column, truncated. min-w-0 lets the
          truncate actually engage inside the flex row. */}
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
        {mover.name}
      </span>

      {/* 5-day sparkline — trend colour derives from the side's % change so
          the line never disagrees with the % column (a 5-day series can trend
          opposite to the 1-day move; the % IS the row's signal).
          WHY NOT aria-hidden: the <Sparkline> svg carries role="img" + a
          per-ticker aria-label ("NVDA 5-day trend") — it conveys real trend
          information to screen-reader users, so it must stay in the a11y tree. */}
      {/* DESIGN-QA D-4 "Dead sparkline columns": only render the shared
          <Sparkline> when there are ≥2 real points. With <2 points it draws a
          dotted grey placeholder that reads as a perpetually "loading"/broken
          column at rest — so we render an empty fixed-size slot instead, which
          keeps the price/% columns aligned without the dead dotted line. */}
      <span className="shrink-0" style={{ width: 40, height: 14 }}>
        {sparkline && sparkline.length >= 2 ? (
          <Sparkline
            data={sparkline}
            width={40}
            height={14}
            trend={isUp ? "positive" : "negative"}
            label={`${mover.ticker} 5-day trend`}
          />
        ) : null}
      </span>

      {/* Price — right-aligned, muted: context, not the signal.
          WHY "—" when price is 0: truthfulness — the movers feed carries no
          price and the overview patch may not have resolved; never $0.00. */}
      {/* whitespace-nowrap: keep the price on one line. formatPriceCompact
          collapses ≥$1M prices to a suffix ("$1.20M") so they fit the 60px slot. */}
      <span className="w-[60px] shrink-0 whitespace-nowrap text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {mover.price > 0 ? formatPriceCompact(mover.price) : "—"}
      </span>

      {/* % change — right-aligned, colored by direction. formatChangePct bounds
          extreme moves (e.g. "+135.4%" / "+1.5K%") so the string never overflows
          this fixed 52px slot. whitespace-nowrap keeps it on one line. */}
      <span
        className={cn(
          "w-[52px] shrink-0 whitespace-nowrap text-right font-mono text-[11px] tabular-nums",
          isUp ? "text-positive" : "text-negative",
        )}
      >
        {formatChangePct(mover.change_pct)}
      </span>
    </div>
  );
}
