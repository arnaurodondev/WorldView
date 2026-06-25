/**
 * hooks/useAboveFoldReady.ts — Defer below-fold network requests one frame
 *
 * WHY THIS EXISTS (F-4, /investigate report):
 * The dashboard mounts ~12 widgets simultaneously and each fires its own
 * TanStack query on first render. In dev mode the browser is capped at 6
 * concurrent HTTP/1.1 connections to /api, so the request waterfall stalls
 * — below-fold widgets (Econ Calendar, Earnings, Portfolio News, Recent
 * Alerts) compete for sockets with the above-fold widgets the user actually
 * sees first.
 *
 * WHY rAF×2 (not IntersectionObserver):
 * The 4th row of the dashboard is *technically* above the fold on tall
 * monitors but below on laptops. Rather than instrumenting each cell with
 * an observer, we simply delay below-fold queries by two animation frames
 * — long enough for the above-fold widgets to enqueue their fetches first
 * (the browser then serves them ahead in its connection queue) but short
 * enough that the user never perceives a stall. Two rAF calls (~33ms at
 * 60Hz) is the well-known "wait for first paint commit" idiom.
 *
 * WHY THIS HOOK INSTEAD OF `enabled: useIsMounted()`:
 * `useIsMounted` flips after the first commit synchronously inside the
 * same React batch, so above-fold and below-fold queries still fire in
 * the same microtask. The rAF×2 gap gives the network stack a chance to
 * see the above-fold sockets first.
 *
 * USAGE:
 *   const aboveFoldReady = useAboveFoldReady();
 *   const { data } = useQuery({
 *     queryKey: [...],
 *     queryFn: ...,
 *     enabled: !!accessToken && aboveFoldReady,
 *   });
 *
 * DESIGN REFERENCE: /investigate F-3/F-4 report (network waterfall fix).
 */

"use client";

import { useEffect, useState } from "react";

export function useAboveFoldReady(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Two requestAnimationFrame calls: the first runs before the next paint,
    // the second runs after that paint has committed. By the time the second
    // callback fires, above-fold widgets have already enqueued their fetches.
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setReady(true));
    });
    return () => {
      cancelAnimationFrame(outer);
      if (inner) cancelAnimationFrame(inner);
    };
  }, []);

  return ready;
}
