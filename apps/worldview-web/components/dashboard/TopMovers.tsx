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
// WHY "use client": uses useQuery, useState for tab toggle, useRouter for nav.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Sparkline } from "@/components/primitives/Sparkline";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
// HF-10: locale-grouped USD price ("$4,892.11").
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Mover } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type MoverType = "gainers" | "losers";

/** How many rows we request per side. 10 fills the Row-3 cell without scroll. */
const MOVERS_LIMIT = 10;

/** Sparkline window — Round 1 spec: 5 trading days of closes per row. */
const SPARKLINE_DAYS = 5;

// ── Component ─────────────────────────────────────────────────────────────────

export function TopMovers() {
  const { accessToken } = useAuth();
  const [type, setType] = useState<MoverType>("gainers");

  // ── Movers query (per active tab) ─────────────────────────────────────────
  // WHY fetch only the ACTIVE tab (not both): switching tabs is the explicit
  // user intent to see the other side; fetching the inactive side up-front
  // doubles network cost for a view the user may never open. The hydrator
  // seeds BOTH sides from the bundle anyway, so in practice the first tab
  // switch is usually a cache hit.
  const { data, isLoading, isError } = useQuery({
    // WHY this exact key shape: must match DashboardBundleHydrator's
    // setQueryData key so the bundle-seeded cache is actually read here.
    queryKey: qk.dashboard.topMovers({ type, limit: MOVERS_LIMIT, period: "1D" }),
    queryFn: () => createGateway(accessToken).getTopMovers(type, MOVERS_LIMIT),
    enabled: !!accessToken,
    // WHY 60s: market movers are a macro view, not a real-time tick feed.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // WHY useMemo: `?? []` would mint a fresh array reference each render and
  // invalidate the downstream id-list memo (same pattern as PreMarketMovers).
  const movers: Mover[] = useMemo(() => data?.movers ?? [], [data]);

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
            {/* Loading: fixed-height skeleton rows prevent layout jump. */}
            {isLoading && (
              <div className="divide-y divide-border/30">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex h-[22px] items-center gap-2 px-2">
                    <Skeleton className="h-3 w-[40px]" style={{ animationDelay: `${i * 50}ms` }} />
                    <Skeleton className="h-3 flex-1" />
                    <Skeleton className="h-3 w-[56px]" />
                  </div>
                ))}
              </div>
            )}

            {/* Error — WHY muted (not destructive red): "unavailable" is a
                transient backend issue, not a user error. Red alarming text
                makes the dashboard look broken; muted text is professional. */}
            {!isLoading && isError && (
              <p className="px-2 py-2 text-xs text-muted-foreground">
                Market movers unavailable — data will appear when market data is ingested.
              </p>
            )}

            {/* Empty — only when the fetch succeeded but the side is empty
                (e.g. pre-market with no negative movers yet). */}
            {!isLoading && !isError && movers.length === 0 && (
              <div className="px-2">
                <InlineEmptyState message="No data available" />
              </div>
            )}

            {/* Data rows */}
            {!isLoading && !isError && (
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
      className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
      onClick={() => router.push(`/instruments/${navId}`)}
      onKeyDown={(e) => {
        if (e.key === "Enter") router.push(`/instruments/${navId}`);
      }}
      role="button"
      tabIndex={0}
      aria-label={`Navigate to ${mover.ticker} instrument page`}
    >
      {/* Ticker — fixed 44px for column alignment */}
      <span className="w-[44px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
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
      <span className="shrink-0">
        <Sparkline
          data={sparkline ?? []}
          width={40}
          height={14}
          trend={isUp ? "positive" : "negative"}
          label={`${mover.ticker} 5-day trend`}
        />
      </span>

      {/* Price — right-aligned, muted: context, not the signal.
          WHY "—" when price is 0: truthfulness — the movers feed carries no
          price and the overview patch may not have resolved; never $0.00. */}
      <span className="w-[60px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {mover.price > 0 ? formatPrice(mover.price) : "—"}
      </span>

      {/* % change — right-aligned, colored by direction */}
      <span
        className={cn(
          "w-[52px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          isUp ? "text-positive" : "text-negative",
        )}
      >
        {isUp ? "+" : ""}
        {mover.change_pct.toFixed(2)}%
      </span>
    </div>
  );
}
