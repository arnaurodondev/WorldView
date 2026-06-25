/**
 * components/instrument/intelligence/useSkeletonTimeout.ts —
 * "an Intelligence-tab skeleton must not spin forever".
 *
 * WHY THIS EXISTS (DESIGN-QA 2026-06-18, finding I-1 "Instrument Intelligence
 * tab ~75% empty/black"): the DOSSIER and EVENTS rails gate their loading
 * skeleton purely on a TanStack Query `isLoading` flag. That flag is honest
 * while a request is in flight — but if the request hangs (S9/S6/KG slow or
 * wedged, a dropped socket that never errors, a retry chain that stays
 * `pending`), the flag stays `true` indefinitely and the rail shows a grey
 * skeleton FOREVER. On the Intelligence tab that left ~75% of the page as
 * perpetual loading blocks over black — exactly what the QA screenshot
 * captured (`1920-instrument-AAPL-intelligence`).
 *
 * THE FIX (DESIGN_SYSTEM §6.1): a skeleton must time out to a terminal state.
 * This hook returns `true` once a rail has been "loading" for longer than a
 * max-wait budget. Callers OR this into their settled-vs-loading decision so
 * that after the budget elapses the rail stops rendering the skeleton and
 * falls through to its existing empty/error branch (a *designed* terminal
 * state) instead of spinning. It does NOT cancel the query — if the data
 * eventually arrives TanStack flips `isLoading` to false, the timer is cleared,
 * and the real data renders. The timeout only governs what we SHOW while we
 * keep waiting.
 *
 * WHY A LOCAL COPY (not an import of components/dashboard/useSkeletonTimeout):
 * the dashboard tree is owned by a sibling agent this sprint; the instrument
 * tree duplicates the ~30 LOC rather than couple two concurrently-edited
 * directories (the same local-duplication convention used by RailHeader /
 * SectionHeader across this surface). The behaviour is identical and pinned by
 * its own test.
 *
 * USAGE:
 *   const timedOut = useSkeletonTimeout(query.isLoading);
 *   if (query.isLoading && !timedOut) return <Skeleton/>;
 *   // ...settled branches: error, empty, data...
 * After `timedOut` flips, the `isLoading && !timedOut` guard is false, so the
 * code naturally proceeds to the error/empty branch the rail already has.
 */

"use client";
// WHY "use client": uses useState + useEffect (timer) — client-only.

import { useEffect, useRef, useState } from "react";

/**
 * Default max-wait before an Intelligence-tab skeleton is considered "stuck".
 * 12s is long enough that a slow-but-working request (cold KG path expansion,
 * an entity-detail enrich on a fresh instrument) still resolves into real data
 * on a normal load, but short enough that a genuinely wedged request surfaces a
 * designed empty/error state well before the user concludes the page is broken.
 * Kept identical to the dashboard budget for cross-surface consistency.
 */
export const DEFAULT_SKELETON_TIMEOUT_MS = 12_000;

/**
 * useSkeletonTimeout — returns true once `loading` has stayed true for longer
 * than `timeoutMs`.
 *
 * @param loading  The rail's current loading flag (isLoading / isPending).
 * @param timeoutMs  Max-wait budget in ms (defaults to 12s).
 * @returns `true` when the loading state has exceeded the budget; otherwise
 *          `false`. Resets to `false` whenever `loading` goes back to false
 *          (e.g. a manual refetch puts the rail back into a fresh load, so the
 *          user gets the full budget again before we give up a second time).
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
    // Not loading → nothing to time out. Clear any stale "timed out" verdict so
    // a subsequent fresh load starts the clock again from zero.
    if (!loading) {
      setTimedOut(false);
      return;
    }
    // Loading → start (or restart) the max-wait clock. When it fires we flip
    // `timedOut`, which the caller ORs into its settled decision so the skeleton
    // yields to the terminal empty/error state.
    const id = setTimeout(() => setTimedOut(true), timeoutRef.current);
    return () => clearTimeout(id);
  }, [loading]);

  return timedOut;
}
