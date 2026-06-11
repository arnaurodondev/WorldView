/**
 * components/dashboard/MarketClockWidget.tsx — US-equity session clock
 *
 * WHY THIS EXISTS (Round 2 enhancement, 2026-06-10): every other dashboard
 * widget shows WHAT the market is doing; none shows WHEN it is doing it.
 * "Is this price live or yesterday's close?" depends entirely on the session
 * state — a trader glancing at the dashboard pre-market needs to know the
 * open is 2h away. Bloomberg keeps a session clock permanently in the
 * terminal chrome for exactly this reason.
 *
 * WHAT IT SHOWS:
 *   - Current Eastern wall-clock time ("14:32:05 ET") — ticks every second.
 *   - Session state (PRE-MARKET / MARKET OPEN / AFTER HOURS / CLOSED) with a
 *     color-coded widget border + state label:
 *       regular   → --positive (teal)   "the tape is live"
 *       pre/after → --warning  (amber)  "extended hours — thin liquidity"
 *       closed    → muted border        "nothing is trading"
 *     (Semantic tokens ONLY — DESIGN_SYSTEM.md forbids hardcoded hex.)
 *   - Countdown to the next transition ("closes in 1h 28m").
 *
 * WHY STATE IS ISOLATED HERE (not lifted to the page): the clock re-renders
 * every second. The dashboard page is a SERVER component that renders each
 * widget independently — `useState` inside THIS client component means the
 * 1 Hz tick re-renders only this ~15-node subtree, never the siblings.
 *
 * WHY THE SSR PLACEHOLDER: the server cannot know the client's "now" — if it
 * rendered a real time, the client's first render would produce different
 * text and React would log a hydration mismatch. So the server (and the
 * client's FIRST render — they must match by definition) emit a deterministic
 * "--:--:-- ET" placeholder; `useEffect` (client-only, post-mount) swaps in
 * the live clock. This is the standard Next.js pattern for wall-clock UI.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-2, next to the
 * Market Snapshot index strip — the clock contextualises those quotes).
 * DATA SOURCE: none (pure client-side time math via features/dashboard/lib/
 * market-clock.ts — no network, no auth).
 */

"use client";
// WHY "use client": owns a 1 Hz interval timer via useState/useEffect.

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import {
  formatCountdown,
  formatNyClock,
  getMarketSession,
  SESSION_LABEL,
  type MarketSessionInfo,
} from "@/features/dashboard/lib/market-clock";

// ── Session → semantic token classes ─────────────────────────────────────────

// WHY border at 60% opacity: matches the page's `border-primary/60` accent
// convention on the Morning Brief — strong enough to read as a status signal,
// not so loud it competes with data.
const BORDER_BY_STATE: Record<MarketSessionInfo["state"], string> = {
  regular: "border-positive/60",
  pre: "border-warning/60",
  after: "border-warning/60",
  closed: "border-border/40",
};

const TEXT_BY_STATE: Record<MarketSessionInfo["state"], string> = {
  regular: "text-positive",
  pre: "text-warning",
  after: "text-warning",
  closed: "text-muted-foreground",
};

// Closed-reason captions — lowercase muted context line under the state.
const CLOSED_REASON_LABEL: Record<string, string> = {
  weekend: "weekend",
  holiday: "market holiday",
  overnight: "overnight",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketClockWidget() {
  // WHY `Date | null` initialised to null (NOT `new Date()`): the initial
  // state is part of the server render + first client render, which must be
  // identical (hydration contract). `null` → deterministic placeholder on
  // both; the effect below resolves the real time only after mount.
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    // Resolve immediately on mount (don't wait 1s for the first tick).
    setNow(new Date());
    // WHY 1000ms tick: the clock line shows seconds — a 60s tick would make
    // the readout look frozen. The countdown only changes per minute, but it
    // recomputes for free on the same tick. The interval lives and dies with
    // this widget (cleanup below), so navigating away leaks nothing.
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // Pure derivation — no memo needed: getMarketSession is O(1) string/number
  // math and the component re-renders exactly once per tick anyway.
  const session = now ? getMarketSession(now) : null;
  const state = session?.state ?? "closed";

  return (
    // WHY the widget owns its border (the page cell for this widget passes
    // no border class): the border COLOR is the session indicator and is only
    // known client-side after mount — a server-rendered page cell can't set it.
    // Round 4 (item 2): role="region" + aria-label landmark for SR panel nav.
    <div
      className={cn(
        "flex h-full flex-col border bg-background transition-colors",
        session ? BORDER_BY_STATE[state] : "border-border/40",
      )}
      role="region"
      aria-label="Market clock"
    >
      {/* ── Section header §0.9 pattern (h-5 like MarketSnapshot — Row 2's
             130px budget demands the compact header variant) ─────────────── */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET CLOCK
        </span>
        {/* Session dot — tiny colored square echoing the border color so the
            state is readable even where the border is cropped by neighbours.
            aria-hidden: decorative; the state label below is the readable one. */}
        {session && (
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5",
              state === "regular" && "bg-positive",
              (state === "pre" || state === "after") && "bg-warning",
              state === "closed" && "bg-muted-foreground/50",
            )}
          />
        )}
      </div>

      {/* ── Body — centered column: clock, state, countdown ─────────────────
          WHY justify-center: the widget is fixed at Row 2's 130px; with only
          3 lines of content, top-anchoring would leave a dead bottom band. */}
      <div className="flex flex-1 flex-col justify-center gap-0.5 px-2">
        {/* Eastern wall-clock readout. ADR-F-15: numerics font-mono +
            tabular-nums so the digits don't jitter horizontally each second. */}
        <span className="font-mono text-[18px] font-semibold tabular-nums text-foreground">
          {/* Deterministic SSR/first-render placeholder — see header WHY. */}
          {now ? formatNyClock(now) : "--:--:-- ET"}
        </span>

        {/* Session state label — the color IS the signal (matches border). */}
        <span
          className={cn(
            "text-[11px] font-medium uppercase tracking-[0.08em]",
            session ? TEXT_BY_STATE[state] : "text-muted-foreground",
          )}
        >
          {session ? SESSION_LABEL[state] : "—"}
        </span>

        {/* Countdown to next transition + closed-reason caption.
            Example lines: "closes in 1h 28m" · "pre-market opens in 9h 12m
            · weekend". WHY one muted line: it's context, not the signal. */}
        <span className="truncate font-mono text-[10px] tabular-nums text-muted-foreground">
          {session && now ? (
            <>
              {session.nextLabel} in{" "}
              {formatCountdown(session.nextTransition.getTime() - now.getTime())}
              {session.closedReason && (
                <span className="text-muted-foreground-dim">
                  {" "}
                  · {CLOSED_REASON_LABEL[session.closedReason]}
                </span>
              )}
            </>
          ) : (
            // Placeholder mirrors the loaded line's height so resolving the
            // clock on mount causes zero layout shift inside the 130px row.
            " "
          )}
        </span>
      </div>
    </div>
  );
}
