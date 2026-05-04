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

import { useMemo, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import { cn } from "@/lib/utils";

type Period = "1D" | "1W" | "1M";

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
  const { data: portfolios, isLoading: portfoliosLoading, isError: portfoliosError, refetch: refetchPortfolios } = useQuery({
    queryKey: ["dashboard-holdings-movers-portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  const firstPortfolio = useMemo(() => {
    if (!portfolios || portfolios.length === 0) return null;
    const sorted = [...portfolios].sort(
      (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
    );
    return sorted[0] ?? null;
  }, [portfolios]);

  // ── 2. Holdings ────────────────────────────────────────────────────────
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["dashboard-holdings-movers-holdings", firstPortfolio?.portfolio_id],
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
  const { data: quotes, isLoading: quotesLoading } = useQuery({
    queryKey: ["dashboard-holdings-movers-batch-quotes", instrumentIds.join(",")],
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

  const gainers = useMemo(
    () =>
      sorted
        .filter((m) => m.changePct != null && m.changePct > 0)
        .slice(0, 5),
    [sorted],
  );
  const losers = useMemo(
    () =>
      sorted
        .filter((m) => m.changePct != null && m.changePct < 0)
        .slice(0, 5),
    [sorted],
  );

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
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
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

      {/* Content */}
      <div className="flex min-h-0 flex-1 overflow-auto">
        {/* ── Error state ────────────────────────────────────────────────── */}
        {/* WHY min-h-[140px]: 5 rows × h-7 (28px) = 140px; prevents the
            widget from collapsing when the portfolio fetch fails cold. */}
        {isError && (
          <div className="flex flex-1 min-h-[140px] items-center justify-center gap-2">
            <AlertTriangle className="h-3 w-3 text-destructive" />
            <span className="text-xs text-muted-foreground">Failed to load</span>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={handleRetry}>
              Retry
            </Button>
          </div>
        )}

        {/* No-portfolio empty state — primary CTA is brokerage connection. */}
        {!isError && noPortfolio && (
          <div className="flex flex-1 items-center justify-center">
            <DashboardEmptyState
              title="No portfolio yet"
              message="Connect a brokerage to see your top movers."
              cta={{ label: "Connect brokerage →", href: "/portfolio" }}
            />
          </div>
        )}

        {!isError && !noPortfolio && noHoldings && (
          <div className="flex flex-1 items-center justify-center">
            <DashboardEmptyState
              title="No holdings"
              message="Add holdings or sync a brokerage to see daily movers here."
              cta={{ label: "Open portfolio →", href: "/portfolio" }}
            />
          </div>
        )}

        {!isError && !noPortfolio && !noHoldings && isLoading && (
          <div className="flex flex-1 gap-0">
            <div className="flex-1 divide-y divide-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={`g-skel-${i}`}
                  className="flex h-7 items-center gap-2 px-2"
                >
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[60px]" />
                  <Skeleton className="ml-auto h-3 w-[40px]" />
                </div>
              ))}
            </div>
            <div className="flex-1 divide-y divide-border/30 border-l border-border/30">
              {Array.from({ length: 5 }).map((_, i) => (
                <div
                  key={`l-skel-${i}`}
                  className="flex h-7 items-center gap-2 px-2"
                >
                  <Skeleton className="h-3 w-[40px]" />
                  <Skeleton className="h-3 w-[60px]" />
                  <Skeleton className="ml-auto h-3 w-[40px]" />
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
          </>
        )}
      </div>

      {/* Footer label — same idiom as WatchlistMovers so users can confirm
          the data context at a glance ("which portfolio?"). */}
      {!noPortfolio && !noHoldings && firstPortfolio && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          <span className="text-[10px] text-muted-foreground/60">
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
      className="flex h-7 cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
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
        {mover.price != null ? `$${mover.price.toFixed(2)}` : "—"}
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
