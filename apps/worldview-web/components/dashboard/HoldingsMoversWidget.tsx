/**
 * components/dashboard/HoldingsMoversWidget.tsx — Holdings movers (PLAN-0053 T-B-2-03)
 *
 * WHY THIS EXISTS: WatchlistMovers answers "which of my TRACKED names is
 * moving?" — but most users care more about "which of my OWNED positions is
 * moving?". For investors with a brokerage connected, the holdings list is a
 * truer reflection of "where is my capital today" than a hand-curated
 * watchlist. This widget surfaces top-5 gainers + losers from the user's
 * holdings, period-aware (1D / 1W / 1M).
 *
 * WHY ALONGSIDE WATCHLIST MOVERS (not replacing):
 *   The plan calls out adding alongside as a tab as the safer choice — users
 *   who curate watchlists (sector watching, IPO watching, candidate names)
 *   shouldn't lose that view. The dashboard mounts this in a tabbed control
 *   alongside the watchlist version so users can flip between the two
 *   without losing either signal.
 *
 * WHY 1D DEFAULT: same intraday-check-in rationale as WatchlistMovers — the
 * dashboard is a "morning routine" surface and 1D answers "what's happening
 * RIGHT NOW".
 *
 * WHY TOP 5 EACH SIDE: matches the WatchlistMovers cell footprint so the
 * dashboard layout doesn't shift when users swap between tabs.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (paired with WatchlistMoversWidget)
 * DATA SOURCES:
 *   - getPortfolios()                            — pick first portfolio
 *   - getHoldings(portfolio_id)                  — position list
 *   - getBatchQuotes(instrument_ids)             — 1D change_pct
 *   - getOHLCV(instrument_id, timeframe)         — 1W/1M derivation
 * DESIGN REFERENCE: PLAN-0053 §T-B-2-03
 */

"use client";
// WHY "use client": uses useQuery, useQueries, useState, useRouter.

// W4 pagination: useRef/useEffect added for the IntersectionObserver sentinel
// that windows the gainers/losers columns in blocks of 30 (client-side).
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, Briefcase } from "lucide-react";

import { createGateway } from "@/lib/gateway";
// Round 4 (item 3b): central query-key factory for the shared portfolios key.
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
// 2026-06-10: shared active-portfolio resolution — follows the TopBar chip.
import { useResolvedPortfolioId } from "@/hooks/useResolvedPortfolioId";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
// Round 3 (item 4): the panel-level no-portfolio / no-holdings states migrate
// from the legacy DashboardEmptyState (components/ui — now consumed only by
// workspace/screener surfaces) onto the shared EmptyState primitive (§15.12).
// InlineEmptyState stays for the in-column "No gainers"/"No losers" lines —
// that's exactly the in-list use case it documents.
import { EmptyState } from "@/components/primitives/EmptyState";
import Link from "next/link";
import { cn } from "@/lib/utils";
// HF-10: locale-grouped USD price ("$4,892.11").
import { formatPrice } from "@/lib/format";

type Period = "1D" | "1W" | "1M";

/**
 * PAGE_SIZE — block size for the client-side infinite-scroll window.
 *
 * W4 pagination (user report 2026-06-12 "display in blocks of 30"): the
 * gainers/losers columns previously hard-capped each side at 5 with no way to
 * see the rest of a larger book's movers. They now reveal in blocks of 30 per
 * side via an IntersectionObserver sentinel inside the panel's own scroll area
 * (same windowing pattern as WatchlistQuickViewWidget — the holdings list is
 * already fetched in ONE response, so this windows a client-side array rather
 * than paging the server).
 */
const PAGE_SIZE = 30;

/**
 * HoldingsMover — internal row shape. Same general layout as the watchlist
 * variant, sans the news/alert enrichment columns (those are watchlist-
 * specific via the `watchlist_insights` composite endpoint, which has no
 * holdings analogue today).
 */
interface HoldingsMover {
  instrumentId: string;
  ticker: string;
  name: string;
  /** Latest live price (1D) or last close (1W/1M). */
  price: number | null;
  /** Period change in percent units (e.g. 2.34 not 0.0234). null while loading. */
  changePct: number | null;
}

// ── Component ───────────────────────────────────────────────────────────────

export function HoldingsMoversWidget() {
  const { accessToken } = useAuth();
  const router = useRouter();
  const [period, setPeriod] = useState<Period>("1D");

  // ── 1. Fetch portfolios — pick the first as "active" ──────────────────
  // WHY first by created_at: matches the WatchlistMovers "default
  // watchlist" heuristic — there is no `is_default` flag, so the oldest
  // portfolio approximates the user's main book.
  // Round 4 (item 3b, query-key drift): key aligned from the widget-private
  // ["dashboard-holdings-movers-portfolios"] to the shared qk.portfolios.list()
  // — identical queryFn/shape to PortfolioSummary's list query, so the private
  // key duplicated a fetch already in the cache whenever the user opened the
  // HOLDINGS tab. Sharing the key makes the tab switch a cache hit.
  const { data: portfolios, isLoading: portfoliosLoading, isError: portfoliosError, refetch: refetchPortfolios } = useQuery({
    queryKey: qk.portfolios.list(),
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // 2026-06-10 PortfolioSwitcher fix: resolve via the shared contract
  // (active-portfolio context first, fallback portfolios[0]) instead of the
  // widget-private created_at sort. Before this, picking a portfolio in the
  // TopBar chip changed PortfolioSummary but NOT this widget — two panels on
  // the same dashboard silently described different books.
  const resolvedPortfolioId = useResolvedPortfolioId(portfolios);
  const firstPortfolio = useMemo(
    () => portfolios?.find((p) => p.portfolio_id === resolvedPortfolioId) ?? null,
    [portfolios, resolvedPortfolioId],
  );

  // ── 2. Holdings ────────────────────────────────────────────────────────
  // Round 4 (item 3b): aligned to the shared ["holdings", id] key family
  // (PortfolioSummary / WatchlistQuickViewWidget) — same queryFn + shape,
  // so when this widget resolves the same portfolio the cache is reused.
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings", firstPortfolio?.portfolio_id],
    queryFn: () =>
      createGateway(accessToken).getHoldings(firstPortfolio!.portfolio_id),
    enabled: !!accessToken && !!firstPortfolio,
    staleTime: 60_000,
  });

  const holdings = useMemo(() => holdingsResp?.holdings ?? [], [holdingsResp]);
  const instrumentIds = useMemo(
    () => holdings.map((h) => h.instrument_id),
    [holdings],
  );

  // ── 3. 1D path: batch quotes ───────────────────────────────────────────
  // Round 4 (item 3b): aligned to the shared ["holdings-quotes", ids] key
  // family — instrumentIds derives from the SAME holdings response in the
  // same order as PortfolioSummary's, so the array (and therefore the key)
  // matches and the 1D quotes fetch dedupes against the always-mounted
  // PortfolioSummary observer instead of firing its own.
  const { data: quotes, isLoading: quotesLoading } = useQuery({
    queryKey: ["holdings-quotes", instrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled: !!accessToken && period === "1D" && instrumentIds.length > 0,
    // 60s refresh — same cadence as WatchlistMovers (matches typical
    // dashboard refetch interval, prevents quote spam).
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // ── 4. 1W / 1M path: per-instrument OHLCV ─────────────────────────────
  const ohlcvQueries = useQueries({
    queries: instrumentIds.map((id) => ({
      queryKey: ["dashboard-holdings-movers-ohlcv", id, period],
      queryFn: () =>
        createGateway(accessToken).getOHLCV(id, { timeframe: period }),
      enabled:
        !!accessToken && period !== "1D" && instrumentIds.length > 0,
      staleTime: 5 * 60_000,
    })),
  });

  // ── 5. Build movers ────────────────────────────────────────────────────
  const movers: HoldingsMover[] = useMemo(() => {
    return holdings.map((h, idx) => {
      const base: HoldingsMover = {
        instrumentId: h.instrument_id,
        ticker: h.ticker,
        name: h.name,
        price: null,
        changePct: null,
      };

      if (period === "1D") {
        // BatchQuoteResponse.quotes is a Record<instrument_id, Quote>.
        // Direct lookup is O(1); we use the same id we sent in the request.
        const quote = quotes?.quotes?.[h.instrument_id];
        return {
          ...base,
          price: quote?.price ?? null,
          changePct: quote?.change_pct ?? null,
        };
      }

      // 1W / 1M — derive from OHLCV bars.
      const ohlcv = ohlcvQueries[idx]?.data;
      const bars = ohlcv?.bars ?? [];
      if (bars.length < 2) return base;
      const first = bars[0]!.close;
      const last = bars[bars.length - 1]!.close;
      if (first <= 0) return { ...base, price: last };
      return {
        ...base,
        price: last,
        changePct: ((last - first) / first) * 100,
      };
    });
  }, [holdings, period, quotes, ohlcvQueries]);

  // ── 6. Sort by |change_pct| desc, partition gainers/losers ──────────────
  const sorted = useMemo(() => {
    return [...movers].sort((a, b) => {
      const aa = a.changePct == null ? -1 : Math.abs(a.changePct);
      const bb = b.changePct == null ? -1 : Math.abs(b.changePct);
      return bb - aa;
    });
  }, [movers]);

  // W4 pagination: keep the FULL ranked gainers/losers (no longer .slice(0,5))
  // so deeper movers stay available; the visible slice is windowed below.
  const allGainers = useMemo(
    () => sorted.filter((m) => m.changePct != null && m.changePct > 0),
    [sorted],
  );
  const allLosers = useMemo(
    () => sorted.filter((m) => m.changePct != null && m.changePct < 0),
    [sorted],
  );

  // ── Infinite-scroll window state (W4 pagination) ──────────────────────────
  // visibleCount grows by PAGE_SIZE per sentinel intersection and applies to
  // BOTH columns symmetrically (the scroll area is shared). hasMore is true
  // while either side still has rows beyond the window.
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const hasMore =
    visibleCount < allGainers.length || visibleCount < allLosers.length;

  // WHY reset on the data identity changing: switching portfolio or period
  // rebuilds the movers — rewind the window so the user starts at the top of
  // the new list instead of mid-scroll. Keyed on lengths + first ids (cheap).
  const moversIdentity =
    `${period}:${allGainers.length}:${allLosers.length}:` +
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
  // Purely client-side — the holdings array is already fully fetched.
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

  // ── 7. Loading composition ──────────────────────────────────────────────
  const periodDataLoading =
    period === "1D"
      ? quotesLoading
      : ohlcvQueries.some((q) => q.isLoading);
  const isLoading =
    portfoliosLoading ||
    (!!firstPortfolio && (holdingsLoading || periodDataLoading));

  // WHY isError: surface a Retry button when the portfolio list fails so
  // the user isn't left with a permanently silent widget. Holdings/quotes
  // errors fall back to the empty-movers list (graceful degradation).
  const isError = portfoliosError;
  const handleRetry = () => { void refetchPortfolios(); };

  // ── 8. Empty state — no portfolio OR no holdings ───────────────────────
  const noPortfolio = !portfoliosLoading && !portfoliosError && !firstPortfolio;
  const noHoldings =
    !holdingsLoading && !!holdingsResp && holdings.length === 0;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* Header + period buttons (mirror WatchlistMovers) */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          HOLDINGS MOVERS
        </span>
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
              aria-pressed={period === p}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Sub-headers GAINERS | LOSERS — only when we have content to show */}
      {!isError && !noPortfolio && !noHoldings && (
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

      {/* Content — W4: flex-COL so the two-column row + the infinite-scroll
          sentinel stack vertically inside the shared overflow-auto scroll area. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        {/* ── Error state ────────────────────────────────────────────────── */}
        {/* WHY min-h-[140px]: 5 rows × h-7 (28px) = 140px; prevents the
            widget from collapsing when the portfolio fetch fails cold. */}
        {isError && (
          <div className="flex flex-1 min-h-[140px] items-center justify-center gap-2">
            <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
            <span className="text-xs text-muted-foreground">Failed to load</span>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={handleRetry}>
              Retry
            </Button>
          </div>
        )}

        {/* No-portfolio empty state — primary CTA is brokerage connection.
            Round 3 (item 4): shared EmptyState primitive — same copy key as
            PortfolioSummary's no-portfolio state so both "my money" panels
            speak with one voice; the action Link keeps the brokerage CTA. */}
        {!isError && noPortfolio && (
          <div className="flex flex-1 items-center justify-center">
            <EmptyState
              condition="empty-cold-start"
              copyKey="dashboard.no-portfolio"
              icon={Briefcase}
              action={
                <Link
                  href="/portfolio"
                  className="font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Connect brokerage →
                </Link>
              }
            />
          </div>
        )}

        {!isError && !noPortfolio && noHoldings && (
          <div className="flex flex-1 items-center justify-center">
            <EmptyState
              condition="empty-cold-start"
              copyKey="dashboard.no-holdings-movers"
              icon={Briefcase}
              action={
                <Link
                  href="/portfolio"
                  className="font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  Open portfolio →
                </Link>
              }
            />
          </div>
        )}

        {!isError && !noPortfolio && !noHoldings && isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={`g-skel-${i}`}
                  className="flex h-[22px] items-center gap-2 px-2"
                >
                  {/* Round 3 (item 3): 4 cells mirror MoverRow's columns
                      (ticker 40 · name flex · price 52 · %chg 52). */}
                  <Skeleton className="h-3 w-[40px] shrink-0" />
                  <Skeleton className="h-3 min-w-0 flex-1" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={`l-skel-${i}`}
                  className="flex h-[22px] items-center gap-2 px-2"
                >
                  {/* Round 3 (item 3): 4 cells mirror MoverRow's columns
                      (ticker 40 · name flex · price 52 · %chg 52). */}
                  <Skeleton className="h-3 w-[40px] shrink-0" />
                  <Skeleton className="h-3 min-w-0 flex-1" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                  <Skeleton className="h-3 w-[52px] shrink-0" />
                </div>
              ))}
            </div>
          </div>
        )}

        {!isError &&
          !noPortfolio &&
          !noHoldings &&
          !isLoading &&
          gainers.length === 0 &&
          losers.length === 0 && (
            <div className="flex-1 px-2">
              <InlineEmptyState message="No movers" />
            </div>
          )}

        {!isError && !noPortfolio && !noHoldings && !isLoading && (gainers.length > 0 || losers.length > 0) && (
          <>
            {/* Two-column row (gainers | losers) — wrapped so the sentinel below
                spans the full width beneath both columns. */}
            <div className="flex">
              <div className="flex-1 divide-y divide-border/30">
                {gainers.map((m) => (
                  <MoverRow
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
              <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
                {losers.map((m) => (
                  <MoverRow
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
            </div>

            {/* ── Infinite-scroll sentinel + footer (W4 pagination) ──────────
                The 1px sentinel sits beneath both columns inside the SAME
                overflow-auto scroll area; scrolling toward it reveals the next
                PAGE_SIZE rows in both columns. The caption tells the user how
                many of each side are shown; when everything is revealed the
                sentinel is gone and the caption reads "all shown". */}
            {hasMore ? (
              <div
                ref={sentinelRef}
                data-testid="holdings-movers-sentinel"
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

      {/* Footer label — same idiom as WatchlistMovers so users can confirm
          the data context at a glance ("which portfolio?"). */}
      {!noPortfolio && !noHoldings && firstPortfolio && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          <span className="text-[10px] text-muted-foreground-dim">
            {firstPortfolio.name}
            {period === "1D" ? " · today" : period === "1W" ? " · 1W" : " · 1M"}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Row sub-component ────────────────────────────────────────────────────────

interface MoverRowProps {
  mover: HoldingsMover;
  side: "gainer" | "loser";
  onClick: () => void;
}

/**
 * MoverRow — one ticker row. Same h-7 + 11px text rhythm as
 * WatchlistMoverRow so the two widgets feel like siblings when adjacent.
 */
function MoverRow({ mover, side, onClick }: MoverRowProps) {
  return (
    <div
      // Round 3 (item 5): inset focus-visible ring for keyboard tabbing.
      className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick();
      }}
      role="button"
      tabIndex={0}
      aria-label={`Open ${mover.ticker} instrument page`}
    >
      {/* WHY font-semibold (was font-bold): 700-weight at 11px causes blotchy subpixel
          rendering on dark themes — 600-weight is the maximum for terminal chrome text
          at small sizes (Bloomberg density rule) */}
      <span className="w-[40px] shrink-0 font-mono text-[11px] font-semibold tabular-nums text-foreground">
        {mover.ticker}
      </span>
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
        {mover.name}
      </span>
      <span className="w-[52px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatPrice(mover.price)}
      </span>
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
