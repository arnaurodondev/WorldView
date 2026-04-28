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

import { useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";

// ── ECON filter ───────────────────────────────────────────────────────────────

// PLAN-0050 T-F-6-01: the binary ECON keyword filter (ECON_KEYWORDS +
// isEconomics) was removed when the toggle was replaced by the multi-bucket
// category pill row — its job is now subsumed by `categorize()` which
// returns "macro" for the same set of titles.

// ── Category heuristic (PLAN-0048 D-2) ────────────────────────────────────────

/**
 * MACRO_KEYWORDS / POLITICS_KEYWORDS / SPORTS_KEYWORDS / CRYPTO_KEYWORDS
 *
 * WHY client-side categorisation: the Polymarket API doesn't return a
 * structured `category` field consistently — it lives in tags that aren't
 * exposed by our S4 ingestion path. Title keyword matching is good enough
 * for the dashboard chip and avoids an API change. Order matters: the FIRST
 * matching set wins, so "fed bitcoin" → macro (since macro is checked
 * before crypto). Most markets only match one set, so collisions are rare.
 *
 * WHY four buckets + "general" default: covers the dominant Polymarket
 * verticals that finance traders care about. Anything else falls into
 * "general" — neutral chip so the trader can still skim the row.
 */
const MACRO_KEYWORDS = [
  "fed", "rate", "inflation", "gdp", "cpi", "unemployment", "recession",
  "fomc", "payroll", "pce", "treasury", "yield", "deficit", "tariff",
  "economic", "fiscal", "monetary", "pmi",
];
const POLITICS_KEYWORDS = [
  "election", "president", "presidential", "senate", "congress", "vote",
  "primary", "governor", "supreme court", "impeach",
];
const SPORTS_KEYWORDS = [
  "nba", "nfl", "mlb", "nhl", "superbowl", "super bowl", "world cup",
  "olympics", "champion", "f1", "fifa", "uefa",
];
const CRYPTO_KEYWORDS = [
  "bitcoin", "ethereum", "btc", "eth", "crypto", "solana", "sol", "altcoin",
];

type Category = "macro" | "politics" | "sports" | "crypto" | "general";

/**
 * categorize — derive a coarse category for the market title.
 * WHY first-match wins: see comment block above. The order is macro → politics
 * → sports → crypto, putting the most finance-relevant categories first so
 * a "Fed cuts rates AND BTC > 100k" market is tagged macro (right call for
 * a finance dashboard).
 */
function categorize(title: string): Category {
  const t = title.toLowerCase();
  if (MACRO_KEYWORDS.some((k) => t.includes(k))) return "macro";
  if (POLITICS_KEYWORDS.some((k) => t.includes(k))) return "politics";
  if (SPORTS_KEYWORDS.some((k) => t.includes(k))) return "sports";
  if (CRYPTO_KEYWORDS.some((k) => t.includes(k))) return "crypto";
  return "general";
}

// ── Countdown helper (PLAN-0048 D-2) ──────────────────────────────────────────

/**
 * formatCountdown — convert a close-time ISO string to a relative label.
 *
 * WHY hand-rolled (not date-fns): keeping new deps to zero (project rule).
 * The four-state output (closed / closes today / closes in Nd / —) is small
 * enough that the formatting logic is clearer inline than via a library.
 *
 * Output:
 *   - null close-time → "—"  (no resolution date known)
 *   - close < now      → "closed"
 *   - same calendar UTC day → "closes today"
 *   - else → "closes in Nd"
 *
 * WHY UTC day comparison: avoids timezone surprises where a NY trader sees
 * a market labelled "closes in 1d" while a London trader sees "today" for
 * the same row. The trade-off: a market closing 03:00 UTC tomorrow shows
 * "closes in 1d" to a NY trader at 23:00 ET (their "today" is the close
 * day local). Acceptable since the precise close time is in the row title.
 */
function formatCountdown(closeIso: string | null | undefined): string {
  if (!closeIso) return "—";
  const close = new Date(closeIso);
  if (Number.isNaN(close.getTime())) return "—";
  const now = new Date();
  if (close.getTime() <= now.getTime()) return "closed";

  // Compare UTC day-of-year for "today" check.
  const sameUtcDay =
    close.getUTCFullYear() === now.getUTCFullYear() &&
    close.getUTCMonth() === now.getUTCMonth() &&
    close.getUTCDate() === now.getUTCDate();
  if (sameUtcDay) return "closes today";

  // Round UP days remaining: a market closing in 25 hours should read
  // "closes in 2d", not "1d" — traders need the upper bound to plan around.
  const msPerDay = 24 * 60 * 60 * 1000;
  const days = Math.ceil((close.getTime() - now.getTime()) / msPerDay);
  return `closes in ${days}d`;
}

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
const CATEGORY_CHIP_CLASS = "bg-muted text-muted-foreground text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0";

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PredictionMarketsWidget — top 3 open prediction markets with yes-probability.
 * Includes an optional ECON filter to show only economics-related markets.
 */
export function PredictionMarketsWidget() {
  const { accessToken } = useAuth();

  // PLAN-0050 T-F-6-01: replaced the binary ECON toggle with a category pill
  // row. The audit (F-D-005) noted the prior toggle hid the other 4 buckets the
  // categoriser already produced (politics/sports/crypto/general), forcing
  // traders interested in any of those to scroll past unrelated rows. The pill
  // row makes all 5 buckets first-class — same data, more useful filter axis.
  // null = "All" (no filter); a non-null value keeps only that category.
  const [categoryFilter, setCategoryFilter] = useState<Category | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-prediction-markets"],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarkets({ status: "open", limit: 8 }),
    enabled: !!accessToken,
    // WHY 60_000: prediction market prices update continuously; 1-min refresh
    // keeps the probabilities reasonably fresh for dashboard context.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // PLAN-0050 T-F-6-01: filter by selected category (null = no filter).
  // We overfetch (limit=8 vs the 3 we render) so any single bucket usually has
  // at least one row even after filtering. If the bucket is empty we show the
  // shared empty state below — the user can clear the filter to see everything.
  const allMarkets = data?.markets ?? [];
  const filteredMarkets = categoryFilter
    ? allMarkets.filter((m) => categorize(m.title) === categoryFilter)
    : allMarkets;
  const topMarkets = filteredMarkets.slice(0, 3);
  const totalMarkets = data?.total ?? 0;

  // ── Per-row history fetch (PLAN-0048 D-2) ──────────────────────────────────
  // WHY useQueries (not per-row useQuery in a child component): hooks must be
  // called at the top of the component, not conditionally inside a `.map()`.
  // useQueries fans out one query per market in a single hook call, returning
  // an aligned array of results. With at most 3 rows the parallelism is
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
          {(["all", "macro", "politics", "sports", "crypto"] as const).map((label) => {
            // null = "all" sentinel — keeps the state model boolean-like for filtering.
            const value: Category | null = label === "all" ? null : (label as Category);
            const active = categoryFilter === value;
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

      {/* ── Error / empty state ────────────────────────────────────────────── */}
      {(isError || (!isLoading && topMarkets.length === 0)) && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="Prediction market data loading…" />
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
            const yesPct = Math.round(market.yes_probability * 100);
            const noPct = 100 - yesPct;

            // WHY color threshold: >60% YES → positive (strong signal),
            // <40% YES → negative (unlikely), else neutral.
            // Matches Polymarket convention where >60% is a "strong" signal.
            const yesProbColor = yesPct > 60 ? "text-positive" : yesPct < 40 ? "text-muted-foreground" : "text-muted-foreground";
            const noProbColor = noPct > 60 ? "text-negative" : "text-muted-foreground";

            // WHY prefer market.url: API returns the Polymarket URL directly.
            // WHY market_slug fallback: PLAN-0043 B-2 added market_slug to the DB
            // (e.g. "will-gdp-exceed-2pct-q3-2026"). Polymarket uses event slugs in
            // canonical URLs: polymarket.com/event/{slug}. This gives a real page
            // rather than the generic homepage — traders land on the exact market.
            // WHY title-search last resort: if both url and market_slug are absent
            // (e.g. legacy rows), a title search on Polymarket finds the market
            // better than a silent no-op or homepage redirect.
            const marketUrl = market.url
              || (market.market_slug ? `https://polymarket.com/event/${market.market_slug}` : null)
              || `https://polymarket.com/markets?q=${encodeURIComponent(market.title)}`;

            function handleMarketClick() {
              // Open in new tab — trader reads market context alongside the terminal.
              window.open(marketUrl, "_blank", "noopener,noreferrer");
            }

            // WHY null/zero guard (BP-264): pre-D-1 the S3 list endpoint always
            // returned volume_24h=None; the gateway mapped null→0. PLAN-0048
            // D-1 wires real volume through the LATERAL JOIN, but markets
            // without snapshots still produce 0 — keep treating 0 == "no data".
            const formattedVolume = market.volume_usd > 0
              ? market.volume_usd >= 1_000_000
                ? `$${(market.volume_usd / 1_000_000).toFixed(1)}M vol`
                : market.volume_usd >= 1_000
                ? `$${(market.volume_usd / 1_000).toFixed(0)}K vol`
                : `$${market.volume_usd.toFixed(0)} vol`
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

      {/* ── Footer: View all link if more markets exist ───────────────────── */}
      {!isLoading && totalMarkets > 3 && (
        <div className="shrink-0 border-t border-border/30 px-2 py-0.5">
          {/* WHY text-primary: the "View all" link is the only interactive element —
              primary color distinguishes it from the muted footer note pattern */}
          <span className="font-mono text-[10px] tabular-nums text-primary/70">
            → View all ({totalMarkets})
          </span>
        </div>
      )}

    </div>
  );
}
