/**
 * components/dashboard/WatchlistQuickViewWidget.tsx — Top-5 positions quick view
 *
 * WHY THIS EXISTS (Round 2 enhancement, 2026-06-10): PortfolioSummary answers
 * "how is my WHOLE portfolio doing?" (totals + period P&L). This widget
 * answers the complementary scan question: "how are my BIGGEST positions
 * moving TODAY?" — top-5 by market value, each with live price, day P&L in
 * DOLLARS (quote.change × quantity — the number that actually hits the
 * account), and a 5-day sparkline for trend context.
 *
 * DATA PATH (5 queries — 4 of them shared caches, ~0 extra network):
 *   1. getPortfolios            → qk.portfolios.list()        (shared w/ PortfolioSummary)
 *   2. useResolvedPortfolioId   → respects the PortfolioSwitcher chip (QA A-F-002)
 *   3. getHoldings(id)          → ["holdings", id]            (same key as PortfolioSummary
 *                                                              → TanStack dedupes the fetch)
 *   4. getBatchQuotes(ids)      → ["holdings-quotes", ids]    (same key as PortfolioSummary)
 *   5. getCompanyOverviewsBatch → qk.instruments.overviewsBatch(ids)  (same key — ticker
 *                                 enrichment for brokerage imports w/ ticker:null, BUG-3)
 *   6. getMarketSparklines      → the ONLY widget-private query: ONE batched
 *                                 GET /v1/market/sparklines?days=5 for the top-5 ids
 *                                 (same endpoint TopMovers uses — never per-row fan-out).
 *
 * WHY THE SHARED QUERY KEYS MATTER: this widget mounts on the same page as
 * PortfolioSummary. Using IDENTICAL keys for portfolios/holdings/quotes means
 * TanStack Query fires each fetch ONCE and both widgets read the same cache
 * entry — adding this widget costs one extra request (sparklines), not five.
 *
 * NAVIGATION: row click → /instruments/[ticker] (PRD-0089 F2 ticker-first
 * URLs; the [ticker] route also resolves UUIDs, so the instrument_id fallback
 * for unenriched holdings still lands on the right page). Header links to
 * /portfolio for the full table.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-3).
 * DATA SOURCE: S9 GET /v1/portfolios → /v1/portfolios/{id}/holdings →
 *   POST /v1/quotes/batch → GET /v1/market/sparklines.
 */

"use client";
// WHY "use client": useQuery hooks, useAuth, useRouter for row navigation.

// W4 task 5: useState (page window) + useRef/useEffect (IntersectionObserver
// sentinel) added for client-side infinite scroll over ALL holdings.
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { useResolvedPortfolioId } from "@/hooks/useResolvedPortfolioId";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): shared EmptyState primitive (§15.12) for the named
// no-positions state — copy key keeps the test-pinned title string.
import { EmptyState } from "@/components/primitives/EmptyState";
// Round 4 (item 1): named error state + Retry. Pre-Round-4 a failed
// portfolios/holdings fetch fell through to the "Track your top positions
// here" cold-start state — misleading for users who DO have positions.
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
// DESIGN-QA D-1: skeleton max-wait so this widget never spins forever.
import { useSkeletonTimeout } from "@/components/dashboard/useSkeletonTimeout";
import { Wallet } from "lucide-react";
import { Sparkline } from "@/components/primitives/Sparkline";
import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import { QUOTE_REFETCH_MS } from "@/hooks/usePortfolioMetrics";
import type { Holding, Quote } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * PAGE_SIZE — how many positions are revealed initially AND appended each time
 * the infinite-scroll sentinel comes into view (W4 task 5).
 *
 * W4 (user report 2026-06-12 "on pagination I would display in blocks of 30"):
 * the reveal block is 30 (was 5). The widget cell still scrolls internally, so
 * the panel stays compact at rest while a block of 30 holdings loads per scroll
 * (a typical book has <30 names, so the first block usually shows them all).
 * Reuses the same pattern as PredictionMarketsWidget (IntersectionObserver
 * sentinel) but windows a client-side array instead of a server
 * `useInfiniteQuery`, because the holdings come back in ONE
 * `/v1/holdings/{id}` response (no server paging).
 */
const PAGE_SIZE = 30;

/** Sparkline window — 5 trading days, same convention as TopMovers Round 1. */
const SPARKLINE_DAYS = 5;

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistQuickViewWidget() {
  const { accessToken } = useAuth();

  // ── Query 1: portfolio list (shared cache with PortfolioSummary) ──────────
  // Round 4 (item 1): error flags destructured for the named error + Retry.
  const {
    data: portfolios,
    isLoading: portfoliosLoading,
    isError: portfoliosError,
    refetch: refetchPortfolios,
    isFetching: portfoliosFetching,
  } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000, // portfolios rarely change intra-day
  });

  // WHY useResolvedPortfolioId (not portfolios[0]): respects the user's
  // PortfolioSwitcher chip selection — picking [0] regardless was the exact
  // half-shipped bug QA A-F-002 fixed in three other widgets. Don't repeat it.
  const portfolioId = useResolvedPortfolioId(portfolios);

  // ── Query 2: holdings (IDENTICAL key to PortfolioSummary → one fetch) ─────
  // Round 4 (item 1): error flags destructured (same rationale as Query 1).
  const {
    data: holdingsResp,
    isLoading: holdingsLoading,
    isError: holdingsError,
    refetch: refetchHoldings,
    isFetching: holdingsFetching,
  } = useQuery({
    queryKey: ["holdings", portfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(portfolioId!),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 30_000,
  });

  const holdings = useMemo(
    () => holdingsResp?.holdings ?? [],
    [holdingsResp],
  );

  // WHY ALL instrument ids (not just top-5): the quotes/overview keys must
  // byte-match PortfolioSummary's keys (which use the full list) for the
  // cache to be shared — AND we can't know which 5 are "top by value" until
  // we have prices anyway (value = price × qty needs the quote).
  const instrumentIds = useMemo(
    () => holdings.map((h) => h.instrument_id),
    [holdings],
  );

  // ── Query 3: live quotes (shared key with PortfolioSummary) ───────────────
  const { data: quotesData, isLoading: quotesLoading } = useQuery({
    queryKey: ["holdings-quotes", instrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled: !!accessToken && instrumentIds.length > 0,
    // Same cadence as PortfolioSummary/usePortfolioMetrics so the shared
    // cache entry stays warm instead of two consumers fighting over staleness.
    refetchInterval: QUOTE_REFETCH_MS,
    staleTime: QUOTE_REFETCH_MS,
  });

  // ── Query 4: ticker/name enrichment (shared key, BUG-3 pattern) ───────────
  // Brokerage-imported holdings can have ticker:null until enrichment runs;
  // the overview batch supplies the display ticker so rows never show UUIDs.
  const { data: overviewsMap } = useQuery({
    queryKey: qk.instruments.overviewsBatch(instrumentIds),
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const map = await gw.getCompanyOverviewsBatch(instrumentIds);
      // Project to the {ticker, name} shape PortfolioSummary caches under
      // this key — the SHAPE must match too, not just the key string,
      // otherwise whichever widget fetches first poisons the other's reads
      // (same silent shape-mismatch class as the Round 1 hydrator bug).
      return Object.fromEntries(
        instrumentIds.map((id) => [
          id,
          {
            ticker: map[id]?.instrument?.ticker ?? null,
            name: map[id]?.instrument?.name ?? null,
          },
        ]),
      ) as Record<string, { ticker: string | null; name: string | null }>;
    },
    enabled: !!accessToken && instrumentIds.length > 0,
    staleTime: 300_000, // ticker/name are effectively immutable
  });

  // ── Sort ALL holdings by market value (W4 task 5: no longer capped at 5) ───
  const quotes = useMemo(() => quotesData?.quotes ?? {}, [quotesData]);
  // The FULL list, sorted by value desc. Windowing happens below via
  // `visibleCount`; the sort itself runs over every holding so deeper rows
  // (revealed by scroll) stay in correct value order.
  const sortedHoldings = useMemo(() => {
    const valueOf = (h: Holding) => {
      const q = quotes[h.instrument_id];
      // price>0 guard (B-2 pattern): batch quotes return price:0 for closed/
      // delisted instruments — fall back to snapshot values, never value→0.
      const price =
        q?.price && q.price > 0 ? q.price : h.current_price ?? h.average_cost;
      return price * h.quantity;
    };
    return [...holdings].sort((a, b) => valueOf(b) - valueOf(a));
  }, [holdings, quotes]);

  // ── Infinite-scroll window state ────────────────────────────────────────────
  // visibleCount grows by PAGE_SIZE each time the sentinel scrolls into view.
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  // Whether more rows remain to reveal — drives the sentinel + the "showing
  // N of M" footer.
  const hasMore = visibleCount < sortedHoldings.length;

  // WHY reset on the holdings list changing: switching portfolio (via the
  // PortfolioSwitcher chip) loads a different holdings set — we must rewind the
  // window to the first page so the user doesn't land mid-scroll in a list
  // they haven't seen. Keyed on the length + first id (cheap identity proxy).
  const holdingsIdentity =
    sortedHoldings.length + ":" + (sortedHoldings[0]?.holding_id ?? "");
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [holdingsIdentity]);

  // The windowed slice actually rendered.
  const topHoldings = useMemo(
    () => sortedHoldings.slice(0, visibleCount),
    [sortedHoldings, visibleCount],
  );

  const topIds = useMemo(
    () => topHoldings.map((h) => h.instrument_id),
    [topHoldings],
  );

  // ── Infinite-scroll sentinel (IntersectionObserver) ─────────────────────────
  // Same pattern as PredictionMarketsWidget: a 1px div after the last row;
  // when it becomes half-visible inside the widget's overflow-auto list we
  // reveal the next PAGE_SIZE rows. No network call — purely client-side
  // windowing of the already-fetched holdings array.
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

  // ── Query 5: 5-day sparkline series (one batch request, widget-private) ───
  // WHY retry:1 — sparklines are decorative trend context; on failure rows
  // still render fully functional with the Sparkline dashed placeholder.
  const { data: sparkSeries } = useQuery({
    queryKey: ["watchlist-quickview-sparklines", ...[...topIds].sort()],
    queryFn: () =>
      createGateway(accessToken).getMarketSparklines(topIds, SPARKLINE_DAYS),
    enabled: !!accessToken && topIds.length > 0,
    staleTime: 15 * 60_000, // daily closes change at most once per session
    retry: 1,
  });

  const isLoading = portfoliosLoading || holdingsLoading || quotesLoading;
  // DESIGN-QA D-1 "Skeletons that never resolve": cap how long the skeleton
  // may show. After the budget we fall through to the data or the named
  // empty/cold-start state instead of spinning if a holdings/quotes leg hangs.
  const skeletonTimedOut = useSkeletonTimeout(isLoading);

  // ── Shared panel chrome ────────────────────────────────────────────────────
  // Header carries the /portfolio link in BOTH data and empty states — the
  // round-trip to the full portfolio table is the widget's primary action.
  const header = (
    <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        TOP POSITIONS
      </span>
      <Link
        href="/portfolio"
        // Round 3 (item 5): keyboard focus ring on the header's primary action.
        className="text-[10px] text-muted-foreground-dim transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        Portfolio →
      </Link>
    </div>
  );

  // ── Error state (Round 4, item 1) ──────────────────────────────────────────
  // BEFORE the loading/empty checks: a failed fetch leaves the data
  // undefined, which the empty branch would misread as "no positions yet".
  // Retry targets only the FAILED query — refetch() ignores `enabled`, so
  // retrying the holdings query while portfolioId is null would crash on
  // the `portfolioId!` assertion (see PortfolioSummary for the same guard).
  if (portfoliosError || holdingsError) {
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="Top positions">
        {header}
        <WidgetErrorState
          copyKey="dashboard.portfolio-error"
          icon={Wallet}
          onRetry={() =>
            void (portfoliosError ? refetchPortfolios() : refetchHoldings())
          }
          retrying={portfoliosFetching || holdingsFetching}
        />
      </div>
    );
  }

  // ── Loading state — fixed-height skeleton rows prevent layout jump ────────
  if (isLoading && !holdingsResp && !skeletonTimedOut) {
    return (
      // Round 4 (item 2): role="region" + aria-label on every return branch.
      <div className="flex h-full flex-col bg-background" role="region" aria-label="Top positions">
        {header}
        {/* Round 3 (item 3): skeleton cells mirror the loaded QuickViewRow's
            exact column slots (ticker 44 · sparkline 48×14 · price flex ·
            day-P&L 64) so data arrival swaps content without any column
            shift. Previously the sparkline slot was missing entirely. */}
        <div className="divide-y divide-border/30">
          {Array.from({ length: PAGE_SIZE }).map((_, i) => (
            <div key={i} className="flex h-[24px] items-center gap-2 px-2">
              <Skeleton className="h-3 w-[44px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-[14px] w-[48px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-3 min-w-0 flex-1" style={{ animationDelay: `${i * 50}ms` }} />
              <Skeleton className="h-3 w-[64px] shrink-0" style={{ animationDelay: `${i * 50}ms` }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Named empty state — no portfolio OR a portfolio with zero holdings ────
  // WHY one shared message: from the user's POV both mean "nothing to show
  // yet, go add positions" — splitting copy would add nuance nobody needs.
  if (!portfolioId || holdings.length === 0) {
    // Round 3 (item 4): shared EmptyState primitive. Copy key
    // dashboard.no-positions keeps the title "Track your top positions here"
    // (PINNED by __tests__/dashboard-round2.test.tsx) and the action Link
    // keeps the accessible name /Add holdings in Portfolio/ (also pinned).
    return (
      <div className="flex h-full flex-col bg-background" role="region" aria-label="Top positions">
        {header}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-cold-start"
            copyKey="dashboard.no-positions"
            icon={Wallet}
            action={
              <Link
                href="/portfolio"
                className="font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                Add holdings in Portfolio →
              </Link>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-background" role="region" aria-label="Top positions">
      {header}
      {/* WHY overflow-y-auto: Row-3 cells are overflow-hidden with a bounded
          minmax height — the row list scrolls independently if the cell ever
          shrinks below 5 rows (e.g. md breakpoint with auto row heights). */}
      <div className="flex-1 overflow-y-auto" data-testid="top-positions-scroll">
        <div className="divide-y divide-border/30">
          {topHoldings.map((h) => (
            <QuickViewRow
              key={h.holding_id}
              holding={h}
              quote={quotes[h.instrument_id] ?? null}
              // Overview enrichment beats the raw holding fields (BUG-3).
              displayTicker={
                overviewsMap?.[h.instrument_id]?.ticker || h.ticker || null
              }
              sparkline={sparkSeries?.[h.instrument_id]}
            />
          ))}
        </div>

        {/* ── Infinite-scroll sentinel + footer (W4 task 5) ─────────────────
            The 1px sentinel sits after the last visible row inside the SAME
            overflow-y-auto container, so scrolling toward the bottom reveals
            the next PAGE_SIZE rows. The footer caption tells the user how many
            of their total holdings are currently shown (mono numerics). When
            everything is revealed the sentinel is gone and the footer reads
            "all N positions". */}
        {hasMore ? (
          <div
            ref={sentinelRef}
            data-testid="top-positions-sentinel"
            // h-px keeps the sentinel invisible but observable; the caption
            // above it gives the user a visible "more below" affordance.
            className="flex items-center justify-center py-1 text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim"
            aria-hidden
          >
            <span className="font-mono tabular-nums">
              {topHoldings.length} of {sortedHoldings.length} · scroll for more
            </span>
          </div>
        ) : (
          sortedHoldings.length > PAGE_SIZE && (
            <div className="flex items-center justify-center py-1 text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim">
              <span className="font-mono tabular-nums">
                all {sortedHoldings.length} positions
              </span>
            </div>
          )
        )}
      </div>
    </div>
  );
}

// ── QuickViewRow ──────────────────────────────────────────────────────────────

interface QuickViewRowProps {
  holding: Holding;
  /** Live quote — null when the batch response misses this instrument. */
  quote: Quote | null;
  /** Enriched ticker (overview → holding fallback) — null when unresolved. */
  displayTicker: string | null;
  /** 5-day close series (oldest-first) — undefined while loading / on miss. */
  sparkline?: number[];
}

/**
 * QuickViewRow — ticker · 5d sparkline · price · day P&L $ (24px row).
 *
 * WHY day P&L in DOLLARS (not %): the position % move is already implied by
 * the sparkline + price; the dollar figure is position-size-aware
 * (quote.change × quantity) — "AAPL −$312 today" is the number a holder
 * actually feels. ADR-F-15: every numeric font-mono + tabular-nums.
 */
function QuickViewRow({ holding, quote, displayTicker, sparkline }: QuickViewRowProps) {
  const router = useRouter();

  // Live price with the B-2 zero-price guard (see topHoldings WHY above).
  const hasLiveQuote = quote != null && quote.price > 0;
  const price = hasLiveQuote
    ? quote.price
    : holding.current_price ?? holding.average_cost;

  // Day P&L $: per-share day change × shares. ONLY computable from a live
  // quote (quote.change = move vs previous close); the cost-basis fallback
  // would be TOTAL unrealised P&L — a different metric, so show "—" instead
  // of silently swapping semantics (truthfulness principle).
  const dayPnl = hasLiveQuote && quote.change != null ? quote.change * holding.quantity : null;
  const isUp = dayPnl != null && dayPnl >= 0;

  // PRD-0089 F2 ticker-first URL; UUID fallback still resolves server-side.
  const navId = displayTicker || holding.instrument_id;

  return (
    <div
      // WHY 24px rows (vs the 22px Row-2 strips): Row 3 has more vertical
      // budget and the sparkline needs 16px + breathing room.
      // Round 3 (item 5): inset focus-visible ring for keyboard tabbing.
      className="flex h-[24px] cursor-pointer items-center gap-2 px-2 transition-colors hover:bg-muted/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      onClick={() => router.push(`/instruments/${navId}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(`/instruments/${navId}`);
      }}
      role="button"
      tabIndex={0}
      aria-label={`Open ${displayTicker ?? "instrument"} detail page`}
    >
      {/* Ticker — identification first (column order matches TopMovers rows) */}
      <span className="w-[44px] shrink-0 truncate font-mono text-[11px] font-medium tabular-nums text-foreground">
        {displayTicker ?? "—"}
      </span>

      {/* 5-day sparkline — trend="auto" tints by first-vs-last delta.
          DESIGN-QA D-4 "Dead sparkline columns": the shared <Sparkline>
          renders a dotted grey placeholder line when it has <2 points, which
          the QA flagged as a "dead column" that reads as broken/loading at
          rest. We instead render the sparkline ONLY when there are ≥2 real
          points; otherwise we keep an empty fixed-size slot so the price/P&L
          columns stay aligned, but show NO dotted placeholder. */}
      <span
        className="flex shrink-0 items-center"
        style={{ width: 48, height: 14 }}
      >
        {sparkline && sparkline.length >= 2 ? (
          <Sparkline
            data={sparkline}
            width={48}
            height={14}
            label={`${displayTicker ?? "position"} 5-day trend`}
          />
        ) : null}
      </span>

      {/* Price — flex-1 right-aligned so the two money columns scan as columns */}
      <span className="min-w-0 flex-1 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
        {price > 0 ? formatPrice(price) : "—"}
      </span>

      {/* Day P&L $ — the row's primary signal, color-coded + signed.
          WHY explicit sign (not formatPrice alone): for a CHANGE value the
          +/− IS the signal (same rationale as MarketSnapshotWidget). */}
      <span
        className={cn(
          "w-[64px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          dayPnl == null && "text-muted-foreground",
          dayPnl != null && (isUp ? "text-positive" : "text-negative"),
        )}
      >
        {dayPnl != null
          ? `${isUp ? "+" : "−"}${formatPrice(Math.abs(dayPnl))}`
          : "—"}
      </span>
    </div>
  );
}
