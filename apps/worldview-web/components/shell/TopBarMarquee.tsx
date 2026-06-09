/**
 * components/shell/TopBarMarquee.tsx — Rotating 10-ticker marquee for TopBar
 *
 * WHY THIS COMPONENT EXISTS: Replaces IndexTicker.tsx (4 static chips) with a
 * continuously scrolling strip of 10 index/commodity/crypto prices. The
 * scrolling strip gives a constant "market heartbeat" visual without consuming
 * additional vertical space — critical for the 36px TopBar height budget.
 *
 * WHY 10 TICKERS (SPY, QQQ, IWM, DIA, VIX, TLT, DXY, GLD, USO, BTC-USD):
 * Covers the 5 major asset classes relevant to an institutional portfolio manager:
 *   US Equities: SPY, QQQ, IWM, DIA
 *   Volatility:  VIX
 *   Fixed income: TLT
 *   FX:          DXY
 *   Commodities: GLD, USO
 *   Crypto:      BTC-USD
 * This breadth matches Bloomberg's default header strip.
 *
 * WHY PURE-CSS ANIMATION (not JS setInterval scroll):
 * CSS animations run on the compositor thread — no JS jank even if the main
 * thread is busy loading chart data. The 60s cycle (6s × 10 tickers) is slow
 * enough that every ticker is readable; each completes ~1.4 passes per minute,
 * which is below the threshold where motion feels distracting on a terminal.
 *
 * WHY RENDER THE LIST TWICE:
 * A single-pass animation `translate(-50% → 0)` would show a seam (white flash)
 * when the list loops. Rendering `[...TICKERS, ...TICKERS]` inside a single
 * flex row and animating to exactly `-50%` makes the seam invisible — the second
 * copy is pixel-identical to the first.
 *
 * WHY hover-pause:
 * Users mouse-over the bar to read a specific value. Pausing on hover mirrors
 * standard financial terminal UX (Reuters Eikon, Bloomberg).
 *
 * WHY REDUCED-MOTION FALLBACK:
 * WCAG 2.3.3 requires that any auto-playing animation can be stopped by users
 * with vestibular disorders. We swap to a static single-chip view of the first
 * 4 tickers (matching old IndexTicker behavior) — these users still get data.
 *
 * DATA FLOW:
 *   1. Resolve 10 ticker symbols → instrument_id UUIDs  (stale 30 min)
 *   2. Batch-quote all resolved UUIDs every 15 s
 *   3. Pass each ticker + its quote into MarqueeTickerChip (stateless)
 *
 * DEPENDENCIES: TanStack Query, gateway lib, MarqueeTickerChip, IndexQuote
 * WHO USES IT: components/shell/TopBar.tsx (center slot)
 * DESIGN: Handoff 2026-05-01 Tier-3 #7
 */

"use client";
// WHY "use client": TanStack Query (useQuery) is client-only.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { MarqueeTickerChip } from "@/components/shell/MarqueeTickerChip";
import type { TickerItem, IndexQuote } from "@/components/shell/MarqueeTickerChip";

// ── Ticker manifest ───────────────────────────────────────────────────────────
// WHY here (not imported): co-locating the list with the component that owns
// the data-fetch means changes to the ticker list are a one-file edit.
const MARQUEE_TICKERS: TickerItem[] = [
  { id: "SPY",     label: "SPY"  },
  { id: "QQQ",     label: "QQQ"  },
  { id: "IWM",     label: "IWM"  },
  { id: "DIA",     label: "DIA"  },
  { id: "VIX",     label: "VIX"  },
  { id: "TLT",     label: "TLT"  },
  { id: "DXY",     label: "DXY"  },
  { id: "GLD",     label: "GLD"  },
  { id: "USO",     label: "USO"  },
  { id: "BTC-USD", label: "BTC"  },
];

// One cycle = 6 s per ticker.  60 s for 10 tickers — slow enough to read each
// chip without motion feeling rushed or distracting on a professional terminal.
const ANIMATION_DURATION_S = MARQUEE_TICKERS.length * 6;

/**
 * TopBarMarquee — continuously scrolling 10-ticker strip with pause-on-hover,
 * reduced-motion fallback, and 15 s price refresh.
 */
export function TopBarMarquee() {
  const { accessToken } = useAuth();

  // ── Step 1: Resolve ticker symbols → instrument_id UUIDs ─────────────────
  // WHY resolveTickersBatch (not searchInstruments per ticker):
  // searchInstruments uses ILIKE '%TLT%' which returns CTLT first (alphabetic
  // substring match), mapping TLT → CTLT's UUID → $0 price. resolveTickersBatch
  // does an exact-match lookup and returns null for truly unknown tickers (DXY).
  // One batch call vs. 10 serial calls also reduces latency ~8×.
  const { data: tickerToId } = useQuery({
    queryKey: ["marquee-ticker-ids"],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const tickers = MARQUEE_TICKERS.map((t) => t.id);
      const result = await gw.resolveTickersBatch(tickers);
      const map: Record<string, string | null> = {};
      tickers.forEach((t) => {
        map[t] = result[t] ?? null;
      });
      return map;
    },
    staleTime: 30 * 60_000,
    enabled: !!accessToken,
  });

  // ── Step 2: Batch-quote resolved UUIDs every 15 s ────────────────────────
  const resolvedIds = Object.values(tickerToId ?? {}).filter((id): id is string => !!id);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["marquee-quotes", resolvedIds],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      return gw.getBatchQuotes(resolvedIds);
    },
    refetchInterval: 15_000,
    staleTime: 0,
    enabled: !!accessToken && resolvedIds.length > 0,
  });

  // ── Reduced-motion fallback: static 4-chip view ───────────────────────────
  // WHY useReducedMotion via CSS media query instead of JS hook:
  // avoids adding a dependency. The .marquee-strip class is already suppressed
  // in globals.css via the prefers-reduced-motion block; we hide the animated
  // outer wrapper and show a static fallback instead.
  const quotes = data?.quotes ?? {};

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center gap-2" aria-label="Loading market tickers">
        {MARQUEE_TICKERS.slice(0, 4).map((t) => (
          <Skeleton key={t.id} className="h-4 w-16" />
        ))}
      </div>
    );
  }

  // Build the chip list — undefined quote renders em-dash placeholders inside MarqueeTickerChip.
  const chips = MARQUEE_TICKERS.map((ticker) => {
    const instrumentId = tickerToId?.[ticker.id];
    const quote: IndexQuote | undefined = instrumentId ? quotes[instrumentId] : undefined;
    return { ticker, quote };
  });

  return (
    /*
     * Outer wrapper:
     *  - overflow-hidden: clips the scrolling track at the container edges
     *  - w-full: fills the TopBar flex-1 slot
     *  - group: enables group-hover on children for pause-on-hover
     *
     * Accessibility: role=marquee + aria-label gives screen readers context
     * without reading every price at every animation frame (the text content
     * is readable via keyboard focus when paused).
     */
    <div
      className="relative w-full overflow-hidden"
      role="marquee"
      aria-label="Market index ticker"
    >
      {/*
       * Scrolling track — the actual animated element:
       *  - flex: puts all chips in a single horizontal row
       *  - w-max: prevents flex-wrap (track must be one unbroken line)
       *  - marquee-strip: CSS class defined in globals.css with the @keyframes
       *    animation. Class is on the element that scrolls (not the wrapper)
       *    so overflow-hidden in the parent clips cleanly.
       *  - hover/focus-within pause: implemented via CSS animation-play-state
       *    in globals.css (the :hover selector cannot be inlined in Tailwind
       *    without a plugin because it needs to target the element itself).
       *
       * WHY ARIA-HIDDEN on the track:
       * The outer div already carries role=marquee + aria-label. Having the
       * inner track also be announced would double-announce all prices.
       */}
      <div
        className="marquee-strip flex w-max items-center"
        style={{ "--marquee-duration": `${ANIMATION_DURATION_S}s` } as React.CSSProperties}
        aria-hidden="true"
      >
        {/* First pass — visible copy */}
        {chips.map(({ ticker, quote }) => (
          <MarqueeTickerChip
            key={ticker.id}
            ticker={ticker}
            quote={quote}
            isError={isError}
          />
        ))}

        {/* Second pass — seamless loop continuation.
            key suffix "-2" prevents React from reusing DOM nodes. */}
        {chips.map(({ ticker, quote }) => (
          <MarqueeTickerChip
            key={`${ticker.id}-2`}
            ticker={ticker}
            quote={quote}
            isError={isError}
          />
        ))}
      </div>

      {/*
       * Reduced-motion fallback — shown via CSS only when the user has
       * prefers-reduced-motion: reduce active. The animated strip above is
       * hidden via globals.css; this static row takes its place.
       *
       * WHY aria-hidden=false here: this element IS the accessible version for
       * motion-sensitive users — their AT should announce these prices.
       */}
      <div
        className="marquee-static-fallback hidden items-center gap-3"
        aria-label="Market tickers (animation reduced)"
      >
        {chips.slice(0, 4).map(({ ticker, quote }) => (
          <MarqueeTickerChip
            key={ticker.id}
            ticker={ticker}
            quote={quote}
            isError={isError}
          />
        ))}
      </div>
    </div>
  );
}
