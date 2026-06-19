/**
 * components/dashboard/useSkeletonTimeout.ts — "skeleton must not spin forever"
 *
 * WHY THIS EXISTS (DESIGN-QA 2026-06-16, finding D-1 "Skeletons that never
 * resolve"): several dashboard widgets gate their loading skeleton purely on
 * a TanStack Query `isPending`/`isLoading` flag. That flag is honest while a
 * request is genuinely in flight — but if the underlying request hangs (S9 /
 * S8 / S6 slow or wedged, a dropped socket that never errors, a retry chain
 * that keeps the query `pending`), the flag stays `true` indefinitely and the
 * widget shows a grey skeleton FOREVER. On the dashboard hero row that reads
 * as "the whole product is broken", which is exactly what the QA screenshots
 * captured (Morning Briefing / Market Snapshot / News Momentum all skeleton).
 *
 * THE FIX (DESIGN_SYSTEM §6.1): a skeleton must time out to a terminal state.
 * This hook returns `true` once a widget has been "loading" for longer than a
 * max-wait budget. Callers OR this into their settled-vs-loading decision so
 * that after the budget elapses the widget stops rendering the skeleton and
 * falls through to its existing empty/error branch (a designed terminal state)
 * instead of spinning. It does NOT cancel the query — if the data eventually
 * arrives, TanStack flips `loading` to false, this hook's timer is cleared,
 * and the real data renders. The timeout only governs what we SHOW while we
 * keep waiting.
 *
 * WHY A HOOK (not a per-widget setTimeout): every dashboard widget had the
 * same gap, so centralising the timer keeps the budget consistent and the
 * call sites a one-liner. It also makes the behaviour trivially testable.
 *
 * USAGE:
 *   const timedOut = useSkeletonTimeout(isLoading);
 *   if (isLoading && !timedOut) return <Skeleton/>;
 *   // ...settled branches: error, empty, data...
 * After `timedOut` flips, the `isLoading && !timedOut` guard is false, so the
 * code naturally proceeds to the error/empty branch the widget already has.
 */

"use client";
// WHY "use client": uses useState + useEffect (timer) — client-only.

import { useEffect, useRef, useState } from "react";

/**
 * Default max-wait before a skeleton is considered "stuck". 12s is long enough
 * that a slow-but-working request (cold S8 brief generation, a fan-out of
 * per-ticker overview calls) still resolves into real data on a normal load,
 * but short enough that a genuinely wedged request surfaces a designed
 * empty/error state well before the user concludes the page is broken.
 */
export const DEFAULT_SKELETON_TIMEOUT_MS = 12_000;

/**
 * useSkeletonTimeout — returns true once `loading` has stayed true for longer
 * than `timeoutMs`.
 *
 * @param loading  The widget's current loading flag (isLoading / isPending).
 * @param timeoutMs  Max-wait budget in ms (defaults to 12s).
 * @returns `true` when the loading state has exceeded the budget; otherwise
 *          `false`. Resets to `false` whenever `loading` goes back to false
 *          (e.g. a manual refetch puts the widget back into a fresh load).
 */
export function useSkeletonTimeout(
  loading: boolean,
  timeoutMs: number = DEFAULT_SKELETON_TIMEOUT_MS,
): boolean {
  const [timedOut, setTimedOut] = useState(false);

  // Keep the latest timeout in a ref so changing it does not restart the timer
  // mid-load (the budget is a constant in practice; this just avoids surprises
  // if a caller passes an inline value).
  const timeoutRef = useRef(timeoutMs);
  timeoutRef.current = timeoutMs;

  useEffect(() => {
    // Not loading → there is nothing to time out. Clear any stale "timed out"
    // verdict so a subsequent fresh load starts the clock again from zero
    // (important for Retry: the user retries, loading flips true, and they get
    // the full budget once more before we give up a second time).
    if (!loading) {
      setTimedOut(false);
      return;
    }

    // Loading → start (or restart) the max-wait clock. When it fires we flip
    // `timedOut`, which the caller ORs into its settled decision so the
    // skeleton yields to the terminal empty/error state.
    const id = setTimeout(() => setTimedOut(true), timeoutRef.current);
    return () => clearTimeout(id);
  }, [loading]);

  return timedOut;
}
