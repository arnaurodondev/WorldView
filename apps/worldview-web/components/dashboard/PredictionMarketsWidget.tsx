/**
 * components/dashboard/PredictionMarketsWidget.tsx — Top prediction market odds
 *
 * WHY THIS EXISTS: Prediction markets (Polymarket) are increasingly used by
 * institutional traders as real-time probability signals for macro and
 * geopolitical events. Showing the top 3 open markets with their yes-probability
 * gives traders a quick pulse on market sentiment beyond price action.
 *
 * WHY TOP 3 ONLY (not all): The col-span-3 cell is compact. Three rows at
 * h-[22px] with a "View all" footer link is the right density — enough signal
 * to catch the user's attention without overwhelming the morning brief.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 3, col-span-3)
 * DATA SOURCE: S9 GET /v1/signals/prediction-markets via createGateway().getPredictionMarkets()
 * DESIGN REFERENCE: PRD-0031 §10 Dashboard Wave 7
 */

"use client";
// WHY "use client": uses useQuery, useAuth, useQueries, and useState for ECON filter toggle.

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
// HF-10: shared compact-currency formatter for "$1.2M" / "$42.5K" output.
import { formatCompactCurrency } from "@/lib/format";
// PLAN-0068 C-2-02: categorize/formatCountdown/keyword lists extracted to shared
// lib so the /prediction-markets page and this widget stay in sync.
import {
  categorize,
  formatCountdown,
  type Category,
} from "@/lib/prediction-markets";

// ── Pill configuration ─────────────────────────────────────────────────────────

/**
 * CATEGORY_PILLS — ordered list of category filter pills.
 * "all" is always first (the natural reset); other buckets follow in
 * descending finance relevance so the most-useful filters are visible
 * without scrolling on standard 1440px+ screens.
 *
 * WHY include ai/energy/tech: SA-2 PLAN-0088 Demo P1 classifier expansion
 * added these buckets to the categorize() function. The pill row reflects
 * the same set so users can filter by the new categories.
 *
 * WHY zero-count pills are hidden below: a "MACRO (0)" pill is confusing
 * because clicking it yields an empty state when the data is already loaded.
 * We hide any category pill whose count is 0 (or whose count is not yet
 * known) when the counts query has resolved. The "All" pill is always shown.
 */
const ORDERED_PILL_LABELS = [
  "all", "macro", "politics", "sports", "crypto", "ai", "energy", "tech",
] as const;
type PillLabel = (typeof ORDERED_PILL_LABELS)[number];

// ── ECON filter ───────────────────────────────────────────────────────────────

// PLAN-0050 T-F-6-01: the binary ECON keyword filter (ECON_KEYWORDS +
// isEconomics) was removed when the toggle was replaced by the multi-bucket
// category pill row — its job is now subsumed by `categorize()` which
// returns "macro" for the same set of titles.

// ── Sparkline (PLAN-0048 D-2) ─────────────────────────────────────────────────

/**
 * Sparkline — tiny inline-SVG line chart of yes-probability over N points.
 *
 * WHY inline SVG (no library): bundle-size discipline. A single <path>
 * with manually computed `d=` is ~30 lines of JS and zero external code.
 * No library covers the 60×16 trader-strip use case better than this.
 *
 * WHY no axes/labels: the value is in the SHAPE, not the absolute number.
 * The Yes/No pills already give the latest reading. The sparkline tells the
 * trader at a glance whether sentiment is rising, flat, or falling.
 *
 * WHY 1px stroke + no fill: matches the rest of the terminal density —
 * a thicker line would dominate the row visually.
 *
 * WHY positive-if-last>first: simple binary signal that's faster to read
 * than a numeric Δ. We already show the Δ in pp on the same line.
 */
function Sparkline({ values, width = 60, height = 16 }: { values: number[]; width?: number; height?: number }) {
  // Need at least 2 points for a line; otherwise render nothing (the empty
  // div keeps layout stable so other rows don't shift).
  if (values.length < 2) return <span className="inline-block" style={{ width, height }} />;

  const min = Math.min(...values);
  const max = Math.max(...values);
  // WHY epsilon range: when min == max (flat line), divide-by-zero would
  // produce NaN coordinates. A 1e-6 floor keeps the path renderable as a
  // straight horizontal line at mid-height.
  const range = Math.max(max - min, 1e-6);

  // Map each value to (x, y) where y is INVERTED — SVG y=0 is the top, but
  // a higher probability should appear higher on screen. We subtract from
  // height so the largest value is at y=0.
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const d = `M ${points[0]} L ${points.slice(1).join(" ")}`;

  // Up = positive (teal), down = negative (red). Equal/single-point = neutral.
  const trendClass =
    values[values.length - 1] > values[0]
      ? "stroke-positive"
      : values[values.length - 1] < values[0]
      ? "stroke-negative"
      : "stroke-muted-foreground";

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <path d={d} className={cn("fill-none", trendClass)} strokeWidth={1} />
    </svg>
  );
}

// ── Category chip styling (PLAN-0048 D-2) ─────────────────────────────────────

/**
 * Static class string per category — kept as a const so Tailwind's JIT
 * picks up every variant at build time (dynamic class names are dropped).
 * All chips share the same dimensions so the title row width is stable
 * across markets.
 */
// WHY rounded-[2px] (not bare `rounded`): design system mandates 2px radius
// everywhere — bare `rounded` gives 4px which is consumer-app scale, not terminal density.
const CATEGORY_CHIP_CLASS = "bg-muted text-muted-foreground text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-[2px] shrink-0";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PredictionMarketsWidget — top 3 open prediction markets with yes-probability.
 * Includes an optional ECON filter to show only economics-related markets.
 */
export function PredictionMarketsWidget() {
  const { accessToken } = useAuth();

  // PLAN-0050 T-F-6-01: replaced the binary ECON toggle with a category pill
  // row. SA-2 PLAN-0088: expanded from 4 to 7 buckets (+ ai, energy, tech).
  // null = "All" (no filter); a non-null value keeps only that category.
  const [categoryFilter, setCategoryFilter] = useState<Category | null>(null);

  // PLAN-0053 T-C-3-04: dynamic limit. The previous hard-coded ``limit=8`` left
  // most filtered category buckets empty (Polymarket's Gamma API exposes only
  // ~300 markets total; after a category filter, 8 markets often yields 0–2
  // matches). We bump the default to 25 (still fits in a single API page) and
  // expand to 50 when a category filter is active so the bucket is full enough
  // to populate the 3 visible rows even on rare categories like "macro".
  // WHY include categoryFilter in queryKey: TanStack Query refetches when the
  // key changes; switching from "all" to "macro" must trigger a new request
  // with the higher limit, otherwise the cache returns the smaller list.
  // WHY 100/75: default sort is now volume_24h DESC so we need a larger pool
  // to buffer filtering noise (some high-volume markets may not match the
  // active category filter). Previous 25/50 was sized for updated_at ordering
  // where markets were clustered by ingestion batch — not relevant once sorted
  // by volume. 75 open markets fetched → typically 6 high-volume ones surface
  // after filtering.
  const effectiveLimit = categoryFilter ? 100 : 75;
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dashboard-prediction-markets", categoryFilter, effectiveLimit],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarkets({ status: "open", limit: effectiveLimit }),
    enabled: !!accessToken,
    // WHY 60_000: prediction market prices update continuously; 1-min refresh
    // keeps the probabilities reasonably fresh for dashboard context.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // PLAN-0053 T-C-3-05: per-category counts for filter pills.
  // WHY separate query (and not derived from `data` above): the list query is
  // paginated AND filtered — once a category filter is active, `data` only has
  // markets in that bucket, so the other pill counts would be wrong. The
  // /categories endpoint counts the FULL open universe in one cheap GROUP BY
  // query.  staleTime 5min: counts shift slowly (markets resolve over hours).
  const { data: categoryCounts } = useQuery({
    queryKey: ["dashboard-prediction-market-categories"],
    queryFn: () => createGateway(accessToken).getPredictionMarketCategories(),
    enabled: !!accessToken,
    staleTime: 5 * 60_000,
  });

  // PLAN-0050 T-F-6-01: filter by selected category (null = no filter).
  // We overfetch (limit=8 vs the 3 we render) so any single bucket usually has
  // at least one row even after filtering. If the bucket is empty we show the
  // shared empty state below — the user can clear the filter to see everything.
  const allMarkets = data?.markets ?? [];
  const filteredMarkets = categoryFilter
    ? allMarkets.filter((m) => categorize(m.title) === categoryFilter)
    : allMarkets;
  // WHY 6: user requested 5-6 visible rows. 6 fills the widget height without
  // crowding; the "View all" link below handles discovery of the full 500+ set.
  const topMarkets = filteredMarkets.slice(0, 6);
  const totalMarkets = data?.total ?? 0;

  // ── Per-row history fetch (PLAN-0048 D-2) ──────────────────────────────────
  // WHY useQueries (not per-row useQuery in a child component): hooks must be
  // called at the top of the component, not conditionally inside a `.map()`.
  // useQueries fans out one query per market in a single hook call, returning
  // an aligned array of results. With at most 6 rows the parallelism is
  // bounded; staleTime=60s prevents repeated fetches when the user toggles
  // ECON or the parent re-renders.
  // WHY enabled gate on accessToken: the gateway requires a token; skipping
  // until the token is present prevents 401 noise in the network panel.
  // WHY queryKey includes market_id + days: each row's history is cached
  // independently — switching the filtered set doesn't invalidate the others.
  // WHY no refetchInterval: the parent's `data` query already polls every
  // 60s; refetching history at the same cadence would double the request
  // volume without meaningful UX benefit (sparkline updates daily-scale).
  const historyQueries = useQueries({
    queries: topMarkets.map((m) => ({
      queryKey: ["dashboard-prediction-market-history", m.market_id, 7],
      queryFn: () => createGateway(accessToken).getPredictionMarketHistory(m.market_id, 7),
      enabled: !!accessToken,
      staleTime: 60_000,
    })),
  });

  return (
    // WHY bg-background: consistent with all other dashboard widgets — the
    // gap-px grid already provides panel separation via background bleed.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern + ECON toggle ───────────────────── */}
      {/* WHY justify-between: section label on the left, ECON toggle on the right —
          follows the same header layout pattern as SectorHeatmapWidget and
          PreMarketMoversWidget. Keeps all controls in the header row (Bloomberg convention). */}
      <div className="flex h-6 shrink-0 items-center justify-between gap-2 border-b border-border px-2">
        <span className="shrink-0 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PREDICTION MARKETS
        </span>
        {/* PLAN-0050 T-F-6-01: category pill row (replaces the prior ECON
            boolean toggle). Pill order matches the categoriser's first-match
            priority (macro → politics → sports → crypto), which is also the
            "most-finance-relevant first" reading order. The "All" pill is
            always present — it is the natural reset and avoids a third "X
            clear filter" affordance that would not fit at 24px header height.

            WHY aria-pressed on every pill (not aria-selected): pills behave
            like a toggle group of independent buttons, not a listbox. SR
            users hear "macro, pressed" / "macro, not pressed" — matches the
            visible filled-vs-outlined state. */}
        {/* F-QA-16: overflow-x-auto + min-w-0 lets the pill row scroll
            horizontally on narrow viewports instead of overflowing the
            24px header rule. The header label keeps its shrink-0 anchor. */}
        <div
          className="flex min-w-0 items-center gap-0.5 overflow-x-auto"
          role="group"
          aria-label="Filter by category"
        >
          {ORDERED_PILL_LABELS.map((label: PillLabel) => {
            // null = "all" sentinel — keeps the state model boolean-like for filtering.
            const value: Category | null = label === "all" ? null : (label as Category);
            const active = categoryFilter === value;

            // PLAN-0053 T-C-3-05: render count next to the label (e.g. "MACRO 12").
            // Counts come from the /categories endpoint.
            const pillCount = label === "all"
              ? categoryCounts?.total
              : categoryCounts?.items.find((c) => c.category === value)?.count;

            // SA-2 PLAN-0088 Demo P1: hide zero-count category pills once the
            // counts query has resolved. A "MACRO (0)" pill is misleading —
            // clicking it immediately yields an empty state while all data is
            // loaded. The "All" pill is always visible (users need a reset path).
            // WHY only hide when categoryCounts has loaded (not undefined):
            // during loading we render all pills to avoid layout shift as counts
            // stream in. Once the query resolves and a bucket has count=0 we
            // hide it. If the active filter happens to be a hidden bucket (edge
            // case: user selected it then data refreshed to 0), we still show it
            // so the user can see WHY the list is empty and click "all" to reset.
            const countLoaded = categoryCounts !== undefined;
            const isZeroCount = countLoaded && label !== "all" && (pillCount === 0 || pillCount == null);
            const isActiveFilter = active && value !== null;
            if (isZeroCount && !isActiveFilter) return null;

            return (
              <button
                key={label}
                type="button"
                onClick={() => setCategoryFilter(value)}
                aria-pressed={active}
                className={cn(
                  "px-1.5 text-[9px] font-mono uppercase transition-colors",
                  active
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
                {/* WHY conditional: show count only when non-zero and loaded. */}
                {pillCount != null && pillCount > 0 ? (
                  <span className="ml-1 opacity-70">{pillCount}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex-1 divide-y divide-border/30">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex h-[22px] items-center gap-2 px-2">
              <Skeleton className="h-3 flex-1" style={{ animationDelay: `${i * 40}ms` }} />
              <Skeleton className="h-3 w-[40px]" />
            </div>
          ))}
        </div>
      )}

      {/* ── Error state ──────────────────────────────────────────────────────
          WHY separate isError branch: a network failure is distinct from an
          empty result set. Showing "data loading…" on error is misleading;
          AlertTriangle + Retry gives the trader an action to recover. */}
      {isError && (
        <div className="flex flex-1 min-h-[110px] items-center justify-center gap-2">
          <AlertTriangle className="h-3 w-3 text-destructive" strokeWidth={1.5} />
          <span className="text-xs text-muted-foreground">Markets unavailable</span>
          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────────────
          SA-2 PLAN-0088 Demo P1 gap fix: when no markets match the filter we
          show a compact centered notice rather than leaving a dark black gap.
          WHY flex-1 + flex + items-center + justify-center: the empty state
          cell occupies the same height as the market-rows cell would (preventing
          the panel from collapsing). Centering the text vertically/horizontally
          uses the same idiom as the error state above.
          WHY min-h-[88px]: 4 × 22px rows = 88px is the minimum readable height
          for the widget when it has no data. Without this, the panel collapses
          to just the header + footer and the gap between Row 3 cells is visible.
          PLAN-0053 T-C-3-05: when a category filter yields 0 results, surface
          the bucket size so the user understands WHY. */}
      {!isError && !isLoading && topMarkets.length === 0 && (
        <div className="flex flex-1 min-h-[88px] items-center justify-center px-2">
          {categoryFilter ? (
            (() => {
              // Look up the count for the active category — null when the
              // counts query hasn't returned yet.
              const bucketCount = categoryCounts?.items.find(
                (c) => c.category === categoryFilter,
              )?.count ?? 0;
              return (
                <span className="text-center text-[10px] text-muted-foreground">
                  {bucketCount > 0
                    ? `${bucketCount} ${categoryFilter} markets — none match current filter.`
                    : `No ${categoryFilter} markets open. Try 'All' or another filter.`}
                </span>
              );
            })()
          ) : (
            <span className="text-[10px] text-muted-foreground">
              Prediction market data loading…
            </span>
          )}
        </div>
      )}

      {/* ── Market rows ───────────────────────────────────────────────────── */}
      {/* WHY 2-row layout per market: one row for the market title (full width),
          one row for Yes/No probability pills + volume. This lets the trader read
          the full question title without truncation pressure, then scan the
          probability distribution on the second line. At 44px total height per
          market (2×22px rows), 3 markets = 132px which fits the col-span-3 cell.
          Bloomberg convention: title first, data below — same as news item rows. */}
      {!isLoading && topMarkets.length > 0 && (
        <div className="flex-1 divide-y divide-border/30 overflow-auto">
          {topMarkets.map((market, idx) => {
            // WHY conditional precision: probabilities <1% round to 0 with Math.round(),
            // making e.g. 0.4% and 0% indistinguishable. Show one decimal for <1% so
            // "0.4%" is distinct from a true zero market.
            const yesRaw = market.yes_probability * 100;
            const yesPct = yesRaw < 1 ? parseFloat(yesRaw.toFixed(1)) : Math.round(yesRaw);
            const noPct = parseFloat((100 - yesRaw).toFixed(1)) < 1
              ? parseFloat((100 - yesRaw).toFixed(1))
              : Math.round(100 - yesRaw);

            // WHY color threshold: >60% YES → positive (strong signal),
            // <40% YES → negative (unlikely), else neutral.
            // Matches Polymarket convention where >60% is a "strong" signal.
            const yesProbColor = yesPct > 60 ? "text-positive" : yesPct < 40 ? "text-muted-foreground" : "text-muted-foreground";
            const noProbColor = noPct > 60 ? "text-negative" : "text-muted-foreground";

            // WHY title-search default (density bundle 2026-05-09): the historic
            // ``/event/{slug}`` URL returned 404 for many markets because
            // Polymarket's canonical paths split ``/event/`` (grouped) vs
            // ``/market/`` (single binary) and the slug we receive from the
            // Gamma ``markets`` payload doesn't reliably match either path.
            // The ``/markets?_q=`` search URL ALWAYS resolves to a working
            // results page no matter the slug shape — so we use it as the
            // first-class link target and only fall back to the explicit
            // ``url`` if S3 supplied one (legacy / future correct slugs).
            const marketUrl = market.url
              || `https://polymarket.com/markets?_q=${encodeURIComponent(market.title)}`;

            function handleMarketClick() {
              // Open in new tab — trader reads market context alongside the terminal.
              window.open(marketUrl, "_blank", "noopener,noreferrer");
            }

            // WHY null/zero guard (BP-264): pre-D-1 the S3 list endpoint always
            // returned volume_24h=None; the gateway mapped null→0. PLAN-0048
            // D-1 wires real volume through the LATERAL JOIN, but markets
            // without snapshots still produce 0 — keep treating 0 == "no data".
            // HF-10: delegate to shared compact-currency formatter and append
            // " vol" suffix once. Removes the hand-built ladder + missing
            // thousands separators for sub-$1K values.
            const formattedVolume = market.volume_usd > 0
              ? `${formatCompactCurrency(market.volume_usd, "USD", { maxDecimals: 1 })} vol`
              : null;

            // ── PLAN-0048 D-2: derive category, delta, countdown, sparkline ──
            const category = categorize(market.title);
            const countdown = formatCountdown(market.resolution_date);

            // History query for THIS row (aligned by index).
            const history = historyQueries[idx]?.data?.points ?? [];

            // 24h Δ in percentage points (pp) — find the first snapshot
            // recorded ≥24h ago and subtract from the most recent.
            // WHY pp not %: a market moving from 50% to 55% is a 5pp change,
            // not a 10% change. Traders read prediction markets in pp.
            // WHY ≥24h boundary (not "the snapshot 24h ago exactly"): polling
            // intervals are not exactly daily, so we accept the closest
            // snapshot that's at LEAST 24h old. This favours "fresh enough"
            // over "perfectly aligned" for the dashboard scan.
            let deltaPp: number | null = null;
            if (history.length >= 2) {
              const latest = history[history.length - 1];
              const cutoffMs = new Date(latest.snapshot_at).getTime() - 24 * 60 * 60 * 1000;
              // Walk backwards from the second-newest looking for the first
              // sample older than 24h. Falls back to the OLDEST point if no
              // such sample exists (e.g. only 6h of data) — in that case the
              // delta is the full history Δ, which is still informative.
              let prev = history[0];
              for (let i = history.length - 2; i >= 0; i--) {
                if (new Date(history[i].snapshot_at).getTime() <= cutoffMs) {
                  prev = history[i];
                  break;
                }
              }
              deltaPp = (latest.yes_probability - prev.yes_probability) * 100;
            }

            // Pull just the yes_probability values for the sparkline.
            const sparkValues = history.map((p) => p.yes_probability);

            return (
              // WHY h-auto (not h-[22px]): this market block is 2 rows × 22px each.
              // WHY cursor-pointer + hover:bg-muted/30: standard terminal row interactivity.
              <div
                key={market.market_id}
                className="cursor-pointer px-2 transition-colors hover:bg-muted/30"
                onClick={handleMarketClick}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleMarketClick();
                  }
                }}
                aria-label={`Open prediction market: ${market.title}`}
              >
                {/* Line 1: Market title + category chip — full width, truncated if very long */}
                {/* WHY h-[22px]: maintains the §0 Terminal Quality row height rhythm
                    even when content fits on one line.
                    WHY chip AFTER title (not before): traders scan titles left-to-right;
                    the category chip is supplementary metadata, so it lives at the end
                    where it doesn't compete with the question for attention. */}
                <div className="flex h-[22px] items-center gap-1.5">
                  <span
                    className="min-w-0 truncate text-[11px] text-foreground"
                    title={market.title}
                  >
                    {market.title}
                  </span>
                  {/* Category chip — small, muted, never colored to avoid drawing
                      the eye away from the actual probability data. */}
                  <span className={CATEGORY_CHIP_CLASS}>{category}</span>
                </div>

                {/* Line 2: Yes/No pills + Δ24h + countdown + sparkline + volume */}
                {/* WHY single horizontal line at h-[22px]: density. The trader
                    must be able to read all secondary info in a single eye-scan.
                    Order: probability (primary signal) → delta (momentum) →
                    countdown (urgency) → sparkline (trend shape) → volume
                    (market activity). Each piece earns its place. */}
                <div className="flex h-[22px] items-center gap-1.5">
                  {/* YES probability pill */}
                  <span className={cn(
                    "rounded-[2px] px-1 font-mono text-[9px] tabular-nums",
                    "bg-positive/10",
                    yesProbColor,
                  )}>
                    Y {yesPct}%
                  </span>

                  {/* NO probability pill */}
                  <span className={cn(
                    "rounded-[2px] px-1 font-mono text-[9px] tabular-nums",
                    "bg-negative/10",
                    noProbColor,
                  )}>
                    N {noPct}%
                  </span>

                  {/* Δ 24h — only render when we actually have a delta.
                      WHY signed format with explicit "+": positive delta should
                      look distinct from "5pp" without a sign — traders parse
                      direction in <100ms by sign character.
                      WHY toFixed(1): one decimal of pp = ~1% step granularity,
                      which matches the smallest meaningful Polymarket movement
                      without flickering on every minor poll. */}
                  {deltaPp !== null && (
                    <span
                      className={cn(
                        "font-mono text-[9px] tabular-nums",
                        deltaPp > 0
                          ? "text-positive"
                          : deltaPp < 0
                          ? "text-negative"
                          : "text-muted-foreground",
                      )}
                      title={`24h change in pp`}
                    >
                      Δ {deltaPp > 0 ? "+" : ""}
                      {deltaPp.toFixed(1)}pp
                    </span>
                  )}

                  {/* Close countdown — relative time, mono-font for tabular align */}
                  <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
                    {countdown}
                  </span>

                  {/* Spacer — pushes the trailing items (sparkline, volume) right */}
                  <span className="flex-1" />

                  {/* Sparkline — 7-day trend; renders nothing when <2 points
                      WHY before volume: visual signal first, numeric second —
                      the eye picks up shape faster than text on a busy row. */}
                  {sparkValues.length >= 2 && (
                    <Sparkline values={sparkValues} />
                  )}

                  {/* Volume — right-aligned, muted (secondary info); hidden when null/0 (BP-264) */}
                  {formattedVolume && (
                    <span className="font-mono text-[10px] tabular-nums text-muted-foreground/70">
                      {formattedVolume}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Footer: View all link if more markets exist ─────────────────────
          PLAN-0053 T-C-3-05: wrap the previously-static text in a real
          ``<Link>`` to the dedicated /prediction-markets page so the trader
          can drill into the full universe. The page is a stub today (route
          owner is the parent merge) but the link is present as a forward-
          compatible affordance — Next.js renders it as a normal anchor and
          the page exists when the parent merge brings in the route file. */}
      {!isLoading && totalMarkets > 3 && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          <Link
            href="/prediction-markets"
            className="font-mono text-[10px] tabular-nums text-primary/70 hover:text-primary"
            aria-label={`View all ${totalMarkets} prediction markets`}
          >
            → View all ({totalMarkets})
          </Link>
        </div>
      )}

    </div>
  );
}
