/**
 * hooks/useInterval.ts — Stale-closure-safe setInterval (Abramov pattern)
 *
 * WHY THIS EXISTS: A naive `setInterval(callback, delay)` inside `useEffect`
 * captures `callback` from the render where the effect ran. If `callback`
 * reads state, it reads STALE state forever — every tick uses the closure
 * from the first render. This bug is invisible until you debug why a clock
 * "freezes" or a P&L card "stops updating" — actually the timer is firing,
 * but it is calling a stale function that reads stale state.
 *
 * Dan Abramov's pattern (https://overreacted.io/making-setinterval-declarative-with-react-hooks/):
 *  1. Keep `savedCallback` in a ref so the LATEST function is always available.
 *  2. Update the ref on every render (cheap — just an assignment).
 *  3. Inside the interval tick, call `savedCallback.current()` — guaranteed
 *     to use the most recent closure, never stale.
 *
 * BEHAVIOUR:
 *  - delay = null  → interval is paused (effect skips setInterval).
 *  - delay = 0     → fires on every tick (use sparingly; rAF is usually better).
 *  - delay > 0     → fires every `delay` ms.
 *
 * USAGE:
 *   useInterval(() => setNow(Date.now()), 1000);
 *   useInterval(() => maybeRefresh(), isVisible ? 30_000 : null);
 *
 * MIGRATION (PLAN-0059-C C-4): replaces 6 raw `setInterval(...)` call sites:
 *   components/ui/data-timestamp.tsx, components/shell/UtcClock.tsx,
 *   components/shell/FlashOverlay.tsx, components/shell/MarketStatusPill.tsx,
 *   hooks/useMarketStatus.ts, hooks/usePortfolioMetrics.ts.
 */

"use client";

import { useEffect, useRef } from "react";

export function useInterval(
  callback: () => void,
  delay: number | null,
): void {
  // WHY a ref (not state): updating the ref doesn't trigger a re-render.
  // The effect that schedules setInterval should not re-run just because the
  // callback identity changed — that would cancel & re-create the timer on
  // every parent re-render and reset the interval phase, which is exactly
  // the bug we're avoiding.
  const savedCallback = useRef<() => void>(callback);

  // Refresh the saved callback on every render. This is cheap (one assignment)
  // and runs synchronously after render, so the interval tick always reads
  // the latest closure when it fires.
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    // null is the documented "pause" signal — let callers turn the timer off
    // (e.g., when the page is hidden) without unmounting the component.
    if (delay === null) return;

    // WHY arrow wrapper around the ref: setInterval needs a stable function;
    // we want it to forward to whatever savedCallback.current is AT TICK TIME,
    // not at scheduling time. The wrapper accomplishes that.
    const id = setInterval(() => {
      savedCallback.current();
    }, delay);

    return () => clearInterval(id);
  }, [delay]);
}
