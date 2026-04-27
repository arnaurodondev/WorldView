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
// WHY "use client": uses useQuery, useAuth, and useState for ECON filter toggle.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { cn } from "@/lib/utils";

// ── ECON filter ───────────────────────────────────────────────────────────────

/**
 * Keywords that identify economics-related prediction markets.
 *
 * WHY client-side filter: the Polymarket API doesn't expose category tags
 * consistently; keyword matching on the title is more reliable. This list
 * covers the major macro/monetary topics that finance traders care about.
 * The filter is optional (toggled by the ECON button) so traders can see
 * all markets or economics-only markets as needed.
 */
const ECON_KEYWORDS = [
  "gdp", "inflation", "fed", "federal reserve", "interest rate", "cpi",
  "unemployment", "recession", "rate cut", "rate hike", "fomc", "payroll",
  "pce", "treasury", "yield", "deficit", "tariff", "trade war", "economic",
  "fiscal", "monetary", "pmi", "ism",
];

/**
 * isEconomics — true if the market title contains any economics keyword.
 * WHY case-insensitive: titles may use "Fed" or "fed" interchangeably.
 */
const isEconomics = (title: string): boolean =>
  ECON_KEYWORDS.some((kw) => title.toLowerCase().includes(kw));

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * PredictionMarketsWidget — top 3 open prediction markets with yes-probability.
 * Includes an optional ECON filter to show only economics-related markets.
 */
export function PredictionMarketsWidget() {
  const { accessToken } = useAuth();

  // WHY econOnly state: traders specialising in macro often only want economics
  // markets visible. The toggle persists for the session (local state) — not URL
  // because it's a dashboard widget preference, not a navigable view.
  const [econOnly, setEconOnly] = useState<boolean>(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard-prediction-markets"],
    queryFn: () =>
      createGateway(accessToken).getPredictionMarkets({ status: "open", limit: 5 }),
    enabled: !!accessToken,
    // WHY 60_000: prediction market prices update continuously; 1-min refresh
    // keeps the probabilities reasonably fresh for dashboard context.
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Apply ECON filter client-side: if econOnly, keep only economics markets.
  // WHY fetch 5 then filter: we overfetch slightly so the ECON filter has enough
  // candidates without an extra API call. The limit=5 limit is a reasonable
  // overfetch for a widget showing 3 results.
  const allMarkets = data?.markets ?? [];
  const filteredMarkets = econOnly ? allMarkets.filter((m) => isEconomics(m.title)) : allMarkets;
  const topMarkets = filteredMarkets.slice(0, 3);
  const totalMarkets = data?.total ?? 0;

  return (
    // WHY bg-background: consistent with all other dashboard widgets — the
    // gap-px grid already provides panel separation via background bleed.
    <div className="flex h-full flex-col bg-background">

      {/* ── Section header §0.9 pattern + ECON toggle ───────────────────── */}
      {/* WHY justify-between: section label on the left, ECON toggle on the right —
          follows the same header layout pattern as SectorHeatmapWidget and
          PreMarketMoversWidget. Keeps all controls in the header row (Bloomberg convention). */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PREDICTION MARKETS
        </span>
        {/* WHY ECON button: macro-focused traders only care about economics markets.
            The toggle filters client-side (no extra API call) — immediate response.
            WHY aria-pressed: communicates toggle state to screen readers. */}
        <button
          onClick={() => setEconOnly((v) => !v)}
          className={cn(
            "px-1.5 text-[9px] font-mono uppercase transition-colors",
            econOnly
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-pressed={econOnly}
        >
          ECON
        </button>
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
          {topMarkets.map((market) => {
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

            // WHY formatVolume: $1.2M is clearer than $1200000 at 10px text.
            const formattedVolume = market.volume_usd >= 1_000_000
              ? `$${(market.volume_usd / 1_000_000).toFixed(1)}M vol`
              : market.volume_usd >= 1_000
              ? `$${(market.volume_usd / 1_000).toFixed(0)}K vol`
              : `$${market.volume_usd.toFixed(0)} vol`;

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
                {/* Line 1: Market title — full width, truncated if very long */}
                {/* WHY h-[22px]: maintains the §0 Terminal Quality row height rhythm
                    even when content fits on one line. */}
                <div className="flex h-[22px] items-center">
                  <span
                    className="min-w-0 truncate text-[11px] text-foreground"
                    title={market.title}
                  >
                    {market.title}
                  </span>
                </div>

                {/* Line 2: Yes/No pills + volume — data line below the title */}
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

                  {/* Spacer — pushes volume to the right */}
                  <span className="flex-1" />

                  {/* Volume — right-aligned, muted (secondary info) */}
                  {/* WHY text-[10px] tabular-nums: consistent with other financial
                      secondary values across the dashboard row pattern. */}
                  <span className="font-mono text-[10px] tabular-nums text-muted-foreground/70">
                    {formattedVolume}
                  </span>
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
