/**
 * app/(app)/prediction-markets/page.tsx — Prediction Markets browser
 *
 * WHY THIS EXISTS: The PredictionMarketsWidget on the dashboard links to this page
 * via `<Link href="/prediction-markets">`. Without this page, that link returns a
 * Next.js 404 (BP-383: missing page linked from dashboard widget).
 *
 * DATA SOURCE: S9 GET /v1/signals/prediction-markets via gateway.getPredictionMarkets().
 * Populated by the content-ingestion Polymarket adapter (gamma-api.polymarket.com
 * → market.prediction.v1 Kafka → S3 market-data DB).
 *
 * DESIGN: Full-page browser with category filter pills, text search, and a
 * probability bar per market. Matches the terminal dark aesthetic (11px mono, 22px rows).
 */

"use client";
// WHY "use client": uses useInfiniteQuery for paginated market data + useState for filters.

import { useInfiniteQuery, useQuery, type InfiniteData } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
// HF-10: shared compact-currency formatter for "$1.2M" / "$42.5K" output.
import { formatCompactCurrency } from "@/lib/format";
import { TrendingUp, Search, AlertCircle } from "lucide-react";
import type { PredictionMarket, PredictionMarketsResponse } from "@/types/api";
// PLAN-0056 Wave E2: analytical enrichment — event groups, an in-app detail
// Sheet (opened from a row) and an honest per-row status signal badge.
import { EventGroupings } from "@/components/prediction-markets/EventGroupings";
import { MarketDetailSheet } from "@/components/prediction-markets/MarketDetailSheet";
import { SignalBadge } from "@/components/prediction-markets/SignalBadge";

// ── Pagination constants ──────────────────────────────────────────────────────

/**
 * PAGE_SIZE — markets fetched per useInfiniteQuery page.
 *
 * WHY 25: terminal-density rows are ~22px tall; 25 fits a screenful on a
 * typical 1080p monitor, giving the user a meaningful chunk per "Load more"
 * click. Previously the page eagerly fetched limit=200 markets up-front which
 * wasted bandwidth when users only inspected the top few.
 */
const PAGE_SIZE = 25;

// ── Probability sparkline ─────────────────────────────────────────────────────

/**
 * ProbabilitySparkline — 60×14px inline SVG showing YES probability over 7 data points.
 *
 * WHY inline SVG (not recharts): recharts is heavy (50KB+). A 60×14 sparkline
 * is 7 line segments — pure SVG is appropriate here and avoids a canvas/DOM
 * overhead on potentially 200 rows.
 *
 * WHY graceful flat-line fallback: the API may not return recent_yes_history
 * (backend gap noted in §B.10). We never crash — we show a flat midpoint line
 * instead, which communicates "no data" without breaking the table layout.
 *
 * DESIGN REFERENCE: PRD-0089 DESIGN-09 §B.6 sparkline spec (60×14px, stroke-primary/70)
 */
function ProbabilitySparkline({ data }: { data?: number[] | null }) {
  const W = 60;
  const H = 14;

  // WHY flat-line fallback: backend gap means data may be absent. A flat line
  // at the midpoint is visually neutral — it communicates "no history" without
  // crashing the row or showing an empty cell.
  if (!data || data.length < 2) {
    return (
      <svg width={W} height={H} aria-hidden>
        <line
          x1={0}
          y1={H / 2}
          x2={W}
          y2={H / 2}
          stroke="currentColor"
          strokeWidth={1}
          className="text-border"
        />
      </svg>
    );
  }

  // WHY min/max with 5pp padding: auto-scaling Y to the data range makes small
  // probability moves visible. Adding ±5 percentage-point padding prevents the
  // line from touching the SVG edges (clipping artefacts).
  const yMin = Math.max(0, Math.min(...data) - 0.05);
  const yMax = Math.min(1, Math.max(...data) + 0.05);
  const yRange = yMax - yMin || 0.01; // guard against all-equal series

  // Map data[i] → SVG coordinates
  const points = data.map((val, i) => {
    const x = (i / (data.length - 1)) * W;
    // WHY inverted Y: SVG Y axis goes top→bottom; probability 1.0 should be
    // at the TOP of the sparkline. Subtract from H to invert.
    const y = H - ((val - yMin) / yRange) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  // Direction: is the last value higher or lower than the first?
  const isUp = data[data.length - 1] >= data[0];

  return (
    <svg width={W} height={H} aria-hidden>
      <polyline
        points={points.join(" ")}
        fill="none"
        // WHY color-based stroke: positive direction = text-positive (teal-green),
        // negative = text-negative (red). Uses currentColor so Tailwind class controls.
        stroke={isUp ? "hsl(var(--positive))" : "hsl(var(--negative))"}
        strokeWidth={1}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ── Category filter pills ─────────────────────────────────────────────────────

// 2026-06-10 filtering fix: pills are now SERVER-DRIVEN. The static list
// ("politics/crypto/sports/macro") + client-side synonym matching is gone —
// the filter is pushed down via the documented `?category=` param (S9 does a
// case-insensitive equality on S3's category column) and the pill set comes
// from GET /v1/signals/prediction-markets/categories, so a pill can never
// name a bucket the backend would return zero rows for. "all" remains the
// client-side sentinel meaning "omit the param".
const ALL_CATEGORY = "all";

// ── YES/NO probability color helper ───────────────────────────────────────────

/**
 * probColorClass — Tailwind text color for a probability value.
 *
 * WHY three tiers (not just green/red): the spec §B.6 uses text-positive for ≥65%,
 * text-warning for 35–64%, and text-negative for <35%. This matches how
 * financial analysts interpret probability:
 *   ≥65% = likely/high-confidence → green
 *   35–64% = uncertain → amber
 *   <35% = unlikely → red
 *
 * NOTE: The design task spec says YES ≥ 60% → text-positive, NO ≥ 60% → text-negative.
 * We use 65% threshold from the design spec §B.6 for the primary color logic.
 */
function probColorClass(pct: number): string {
  if (pct >= 65) return "text-positive";
  if (pct >= 35) return "text-warning";
  return "text-negative";
}

// ── Market row ────────────────────────────────────────────────────────────────

/**
 * Extended PredictionMarket type that includes optional Wave-J fields.
 * These fields are not in the current API response but the design proposes adding them.
 * Graceful degradation: if absent, we skip the bid/ask chip and show flat sparkline.
 */
type PredictionMarketExtended = PredictionMarket & {
  /** Last 7 YES probability data points — proposed backend addition §B.10 */
  recent_yes_history?: number[] | null;
  /** Best bid price — proposed backend addition §B.10 */
  best_bid?: number | null;
  /** Best ask price — proposed backend addition §B.10 */
  best_ask?: number | null;
};

function MarketRow({
  market,
  onSelect,
}: {
  market: PredictionMarketExtended;
  // PLAN-0056 Wave E2: clicking a row now opens the in-app detail Sheet instead
  // of navigating straight to Polymarket. The Sheet preserves the list's scroll
  // + filter state (a route push would tear the list down) and still offers the
  // external Polymarket link inside it. Passed up so the page owns the Sheet.
  onSelect: (market: PredictionMarket) => void;
}) {
  const volume = market.volume_usd ?? 0;
  // HF-10: delegate to the shared formatter ("$1.2M" / "$42.5K" / "$847.00").
  const formattedVolume = formatCompactCurrency(volume, "USD", { maxDecimals: 1 });

  const closeDate = market.resolution_date ? new Date(market.resolution_date) : null;
  const daysLeft = closeDate
    ? Math.max(0, Math.round((closeDate.getTime() - Date.now()) / 86_400_000))
    : null;

  // Derive YES% and NO% as integer percentages (clamp to [0,100]).
  const yesPct = Math.round(Math.min(1, Math.max(0, market.yes_probability ?? 0)) * 100);
  // WHY not always 100 - yesPct: market.no_probability may be explicitly set by
  // the backend (e.g., multi-outcome markets). Fall back to 100 - yesPct for binary markets.
  const noPct = Math.round(
    Math.min(1, Math.max(0, market.no_probability ?? (1 - (market.yes_probability ?? 0)))) * 100,
  );

  const handleRowClick = () => onSelect(market);

  return (
    <div
      role="button"
      data-testid="market-row"
      onClick={handleRowClick}
      // PRD-0089 Wave J: new 7-column layout adds YES%, sparkline, and NO% columns.
      // grid-cols spec from §B.4: [source 20px][question 1fr][YES% 60px][spark 80px][NO% 60px][vol 80px][closes 60px]
      // Source icon not yet implemented (backend gap) — collapsed into question col for now.
      className={cn(
        "grid grid-cols-[1fr_60px_70px_60px_80px_56px] h-[22px] items-center gap-2 border-b border-border/30 px-3",
        "cursor-pointer hover:bg-card/60",
      )}
    >
      {/* Question — truncated 1 line, 11px, with an honest status signal badge.
          WHY only status here (no "moving"): list rows don't fetch per-row
          history, so a move badge would be unfounded. The badge shows only for
          resolved/closed markets (from status); the detail Sheet adds the
          history-derived "moving" badge. See SignalBadge for the full rationale. */}
      <div className="flex min-w-0 items-center gap-1.5">
        <p className="truncate text-[11px] text-foreground">{market.title}</p>
        <SignalBadge status={market.status} className="shrink-0" />
      </div>

      {/* YES% — colored based on probability tier */}
      {/*
       * WHY inline chip (not a bar): the market row is now 22px — there's no
       * vertical room for a multi-layer probability bar. A single numeric value
       * with color coding is more information-dense at 22px row height.
       */}
      <span
        className={cn(
          "text-right font-mono text-[11px] tabular-nums",
          probColorClass(yesPct),
        )}
      >
        {yesPct}%
      </span>

      {/* 7-day YES probability sparkline */}
      {/*
       * WHY 70px column (not 80px spec): accommodates the compact grid while
       * still giving the 60px-wide SVG 5px breathing room on each side.
       */}
      <div className="flex items-center justify-center">
        <ProbabilitySparkline data={market.recent_yes_history} />
      </div>

      {/* NO% — symmetric inverse coloring */}
      <span
        className={cn(
          "text-right font-mono text-[11px] tabular-nums",
          // WHY inverted: if NO is ≥60%, it's "likely NO" → text-negative;
          // if YES is ≥60%, NO is ≤40% → green (unlikely) ... wait, the spec
          // says NO ≥ 60% → text-negative. So we use the same probColorClass
          // since a high NO% is actually a "strong NO" signal (red).
          probColorClass(noPct),
        )}
      >
        {noPct}%
      </span>

      {/* Bid/Ask chips — shown when best_bid/best_ask available (§B.10 backend gap) */}
      {/*
       * WHY collapsed into the volume column: bid/ask data is not yet in the
       * list endpoint (§B.10 backend gap). We show "–" as placeholder when absent,
       * and render actual values in-line when the fields eventually arrive.
       * The chips replace the full-width probability bar that was previously here.
       */}
      <div className="flex items-center justify-end gap-1">
        {market.best_bid != null && market.best_ask != null ? (
          <>
            <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
              BID {(market.best_bid * 100).toFixed(0)}
            </span>
            <span className="text-[9px] text-border">/</span>
            <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
              ASK {(market.best_ask * 100).toFixed(0)}
            </span>
          </>
        ) : (
          // WHY show volume when bid/ask unavailable: the volume column is
          // always informative for market size estimation.
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{formattedVolume}</span>
        )}
      </div>

      {/* Days until close */}
      <span className="text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {daysLeft !== null ? `${daysLeft}d` : "—"}
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PredictionMarketsPage() {
  const { accessToken } = useAuth();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>(ALL_CATEGORY);
  // PLAN-0056 Wave E2: the market selected for the detail Sheet (null = closed).
  const [selectedMarket, setSelectedMarket] = useState<PredictionMarket | null>(null);

  // ── Category pills — server-driven (2026-06-10 filtering fix) ─────────────
  // One cheap GROUP BY on the backend; counts reflect the FULL open universe
  // so the pills stay truthful regardless of how many pages are loaded.
  // Rows with category IS NULL are uncounted here by design (they only show
  // under "all" — the backend's documented filter semantics).
  const { data: categoryCounts } = useQuery({
    queryKey: ["prediction-markets-page-categories"],
    queryFn: () => createGateway(accessToken).getPredictionMarketCategories(),
    enabled: !!accessToken,
    staleTime: 5 * 60_000,
  });
  // "all" first (reset affordance), then real buckets by count desc so the
  // densest filters sit closest to the reset.
  const categoryPills: Array<{ value: string; count: number | null }> = useMemo(() => {
    const buckets = (categoryCounts?.items ?? [])
      .filter((c): c is { category: string; count: number } => c.category != null && c.count > 0)
      .sort((a, b) => b.count - a.count)
      .map((c) => ({ value: c.category, count: c.count }));
    return [{ value: ALL_CATEGORY, count: categoryCounts?.total ?? null }, ...buckets];
  }, [categoryCounts]);

  // WHY useInfiniteQuery: PRD-0103 dashboard regression #3 — paginate the
  // prediction markets browser using offset+limit pages instead of the prior
  // limit=200 eager fetch. Users now scroll/click through the universe at
  // their own pace; bandwidth is proportional to how many pages they view.
  //
  // WHY category in the queryKey AND the params (2026-06-10 fix): the filter
  // previously matched `m.category` client-side — a field the gateway never
  // mapped (always undefined), so EVERY category pill yielded zero rows.
  // Server-side filtering also makes pagination correct under a filter:
  // offset walks the filtered universe, so "politics" can page through all
  // 181 politics rows instead of whatever subset happened to be loaded.
  const { data, isLoading, isError, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery<
      PredictionMarketsResponse,
      Error,
      InfiniteData<PredictionMarketsResponse>,
      readonly unknown[],
      number
    >({
      queryKey: ["prediction-markets-page-infinite", category],
      queryFn: ({ pageParam }) =>
        createGateway(accessToken).getPredictionMarkets({
          status: "open",
          limit: PAGE_SIZE,
          offset: pageParam,
          category: category === ALL_CATEGORY ? undefined : category,
        }),
      initialPageParam: 0,
      getNextPageParam: (lastPage, allPages) => {
        // WHY total-based: backend always returns the (filter-scoped) total;
        // stop when we've fetched every row. Fallback: partial page = end.
        const loaded = allPages.reduce((n, p) => n + p.markets.length, 0);
        if (lastPage.total != null) return loaded < lastPage.total ? loaded : undefined;
        return lastPage.markets.length === PAGE_SIZE ? loaded : undefined;
      },
      enabled: !!accessToken,
      staleTime: 60_000,
    });

  // WHY flatMap: collapse paginated pages into a single array for the filter
  // pipeline below. The client-side category + search filters operate on the
  // currently-loaded universe (subsequent pages widen the searched set).
  const allLoadedMarkets = useMemo(
    () => data?.pages.flatMap((p) => p.markets) ?? [],
    [data],
  );
  // WHY total fallback to loaded count: hides the "Load more" button cleanly
  // when backend omits total.
  const total = data?.pages[0]?.total ?? allLoadedMarkets.length;

  const markets: PredictionMarket[] = useMemo(() => {
    let result = allLoadedMarkets;

    // 2026-06-10: NO client-side category filter anymore — the server already
    // scoped every loaded page via `?category=` (see queryFn above). The
    // previous client-side path filtered on `m.category`, a field the gateway
    // dropped (always undefined) — every pill returned zero rows. The synonym
    // map died with it: the server's equality semantics ARE the taxonomy the
    // counts endpoint reports, so pills and rows can't disagree.

    // Text search on title + category — client-side over the LOADED pages
    // only (the backend's `query` param exists, but wiring it would refetch
    // per keystroke; debounced server search is a follow-up). ``title``
    // defaults to "" when missing so we never call .toLowerCase on undefined.
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter((m) => {
        const title = (m.title ?? "").toLowerCase();
        const cat = (m.category ?? "").toLowerCase();
        return title.includes(q) || cat.includes(q);
      });
    }

    return result;
  }, [allLoadedMarkets, search]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background">

      {/* ── Page header ─────────────────────────────────────────────────────── */}
      {/* Density bundle 2026-05-09: px-5 py-3 → px-3 py-2 for terminal density */}
      <div className="border-b border-border/50 px-3 py-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-muted-foreground" strokeWidth={1.5} />
          <h1 className="text-[11px] font-medium uppercase tracking-[0.1em] text-foreground">
            Prediction Markets
          </h1>
          {total > 0 && (
            <Badge variant="outline" className="ml-auto font-mono text-[9px]">
              {total.toLocaleString()} open
            </Badge>
          )}
        </div>

        {/* Category pills + search */}
        <div className="mt-2.5 flex items-center gap-2">
          <div className="flex gap-1" role="group" aria-label="Filter by category">
            {/* Server-driven pills (2026-06-10): one per backend bucket with a
                non-zero count, plus "all". Counts shown so the trader knows
                the bucket size BEFORE clicking (same idiom as the dashboard
                widget's pill row). */}
            {categoryPills.map(({ value, count }) => (
              <button
                key={value}
                onClick={() => setCategory(value)}
                aria-pressed={category === value}
                className={cn(
                  "rounded-[2px] px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider transition-colors",
                  // WHY bg-primary/20 text-primary (not hardcoded yellow HSL): design-system tokens.
                  category === value
                    ? "bg-primary/20 text-primary"
                    : "bg-muted/30 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                {value}
                {count != null && count > 0 ? (
                  <span className="ml-1 opacity-70 tabular-nums">{count}</span>
                ) : null}
              </button>
            ))}
          </div>

          <div className="relative ml-auto w-52">
            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" strokeWidth={1.5} />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search markets…"
              autoComplete="off"
              className="h-6 pl-6 font-mono text-[10px]"
            />
          </div>
        </div>
      </div>

      {/* ── Event groupings (collapsible, opt-in context) ───────────────────── */}
      {/* PLAN-0056 Wave E2: thematic Polymarket event groups above the flat list. */}
      <EventGroupings />

      {/* ── Column headers ───────────────────────────────────────────────────── */}
      {/* PRD-0089 Wave J: updated to match new 6-column layout with YES/sparkline/NO. */}
      <div className="grid grid-cols-[1fr_60px_70px_60px_80px_56px] gap-2 border-b border-border/50 px-3 py-1">
        {(["Question", "YES%", "7D", "NO%", "BID/ASK", "Closes"] as const).map((label) => (
          <span
            key={label}
            className={cn(
              "font-mono text-[9px] uppercase tracking-wider text-muted-foreground",
              label !== "Question" && "text-right",
              // WHY center for 7D (sparkline column): aligns header over the centered SVG.
              label === "7D" && "text-center",
            )}
          >
            {label}
          </span>
        ))}
      </div>

      {/* ── Market list ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {isLoading &&
          // WHY h-[22px]: match the real row height token — avoids layout shift when data arrives.
          Array.from({ length: 14 }).map((_, i) => (
            <div key={i} className="grid grid-cols-[1fr_160px_80px_80px] h-[22px] items-center gap-2 border-b border-border/30 px-3" style={{ animationDelay: `${i * 30}ms` }}>
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-1.5 w-full" />
              <Skeleton className="h-3 w-8 ml-auto" />
              <Skeleton className="h-3 w-6 ml-auto" />
            </div>
          ))}

        {isError && !isLoading && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
            <AlertCircle className="h-5 w-5" strokeWidth={1.5} />
            <p className="text-[11px]">Failed to load prediction markets</p>
            <p className="text-[10px] text-muted-foreground/60">
              The Polymarket data pipeline may still be populating.
            </p>
          </div>
        )}

        {!isLoading && !isError && markets.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted-foreground">
            <TrendingUp className="h-5 w-5" strokeWidth={1.5} />
            <p className="text-[11px]">
              {search || category !== ALL_CATEGORY ? "No markets match your filters" : "No prediction markets available"}
            </p>
            {!search && category === ALL_CATEGORY && (
              <p className="text-[10px] text-muted-foreground/60">
                Run <code className="font-mono text-[9px]">make seed</code> to populate Polymarket data.
              </p>
            )}
          </div>
        )}

        {!isLoading && !isError && markets.map((m) => (
          // WHY cast to PredictionMarketExtended: the current API type doesn't
          // include best_bid/best_ask/recent_yes_history (backend gap §B.10).
          // The row renders gracefully when these fields are absent.
          <MarketRow
            key={m.market_id}
            market={m as PredictionMarketExtended}
            onSelect={setSelectedMarket}
          />
        ))}

        {/* ── Load more button ─────────────────────────────────────────────── */}
        {/* WHY render below the rows (not pinned): a "scroll-to-discover"
            action that integrates naturally with the list. Hidden when no more
            pages or while filters are active in a way that already exhausts
            the loaded set. We always show if backend has more rows so users
            can pull more rows in even when their filter currently matches few. */}
        {!isLoading && !isError && hasNextPage && (
          <div className="flex items-center justify-center border-b border-border/30 px-3 py-2">
            <button
              type="button"
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground disabled:pointer-events-none"
            >
              {isFetchingNextPage
                ? "Loading…"
                : `Load more (${allLoadedMarkets.length}/${total})`}
            </button>
          </div>
        )}
      </div>

      {/* ── Market detail Sheet ─────────────────────────────────────────────── */}
      {/* PLAN-0056 Wave E2: right-side panel opened from a row. Controlled by
          selectedMarket; onOpenChange(false) clears the selection so the list
          keeps its scroll + filter state underneath. */}
      <MarketDetailSheet
        market={selectedMarket}
        open={selectedMarket !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedMarket(null);
        }}
      />
    </div>
  );
}
