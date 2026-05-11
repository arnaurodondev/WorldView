/**
 * components/shell/RefreshAllButton.tsx — global "refresh every query" trigger
 *
 * WHY THIS EXISTS (PLAN-0050 T-F-6-06, closes F-D-027): each widget on the
 * dashboard manages its own refetch cadence (15s for quotes, 60s for news,
 * etc.) but there are moments — opening the laptop after lunch, returning
 * from a meeting, the market just opened — when a trader wants to force
 * every panel to refresh NOW without waiting for the next scheduled tick.
 * A single TopBar button that invalidates the entire TanStack Query cache
 * gives them that one-click "wake up the dashboard" capability.
 *
 * WHY invalidateQueries (no filter): a partial invalidation requires the
 * caller to know which keys exist where, which leaks page-level concerns
 * into a shell-level component. Invalidating everything is conservative
 * but correct: TanStack Query is smart enough to only refetch queries
 * that are currently mounted (observers > 0), so this does NOT trigger a
 * stampede of background fetches for keys nobody is looking at.
 *
 * WHY a brief visual flash (animate-spin on click): without feedback the
 * user has no idea whether the click registered — the data refresh
 * happens behind the scenes and most queries finish in <1s. A 600ms spin
 * is the minimum confirmation gesture; longer would feel sluggish.
 *
 * WHO USES IT: components/shell/TopBar.tsx
 */

"use client";
// WHY "use client": uses useQueryClient (React context) and useState for
// the spinner-while-refreshing visual state.

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

/**
 * Denylist of query-key prefixes that this button MUST NOT invalidate.
 *
 * F-QA2-01 fix: the prior allowlist over-corrected F-QA-04 by silently
 * dropping ~10 dashboard widgets (sector heatmap, market snapshot, top
 * movers, index ticker, etc.) from the "Refresh All" gesture — those
 * panels stayed on stale data while the user thought they had refreshed
 * everything. We invert the model: invalidate everything *except* the
 * known-problematic streaming-bound observers, which is the small,
 * enumerable set:
 *   - alert-stream / chat-stream      → re-running setup duplicates
 *                                        the SSE/WebSocket connection
 *   - alert-ws-* / chat-ws-*           → same family of observers
 * Any future polling key automatically participates without an audit;
 * any future streaming key is added here when introduced.
 */
const REFRESH_DENIED_PREFIXES = [
  "alert-stream",
  "chat-stream",
  "alert-ws",  // catches alert-ws-token and similar variants
  "chat-ws",
];

function isRefreshAllowed(queryKey: readonly unknown[]): boolean {
  const head = queryKey[0];
  if (typeof head !== "string") return false;
  // Allow by default; deny only the streaming-bound observers.
  return !REFRESH_DENIED_PREFIXES.some((p) => head === p || head.startsWith(`${p}-`));
}

export function RefreshAllButton() {
  const queryClient = useQueryClient();
  const [spinning, setSpinning] = useState(false);
  // F-QA-02 fix: hold the spinner-reset timer in a ref so we can clear it on
  // unmount and on rapid re-clicks. The prior implementation leaked the timer
  // and React would log a "set state on unmounted component" warning when the
  // user clicked refresh and then navigated within the 600ms window.
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  function handleRefresh() {
    // F-QA-04 fix: predicate-filtered invalidation. Streaming-bound queries
    // (alert WebSocket, chat SSE) are NOT in the allowlist, so this button
    // cannot inadvertently re-trigger a stream connection.
    void queryClient.invalidateQueries({
      predicate: (q) => isRefreshAllowed(q.queryKey),
    });

    // Cancel any pre-existing reset timer before scheduling the new one
    // — guarantees rapid clicks don't compound multiple cleanup setStates.
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    setSpinning(true);
    // 600ms ≈ one full rotation at the default 1s spin animation, gives
    // visual confirmation without lingering after the data has refetched.
    timerRef.current = window.setTimeout(() => {
      setSpinning(false);
      timerRef.current = null;
    }, 600);
  }

  return (
    <button
      type="button"
      onClick={handleRefresh}
      // WHY p-1 + h-4/w-4 (matches the bell): the refresh affordance must
      // be visually equivalent to the bell (peer affordance, not a CTA).
      // Larger sizing would falsely promote it above the alert count badge.
      className="p-1 text-muted-foreground transition-colors hover:text-foreground"
      aria-label="Refresh all dashboard data"
      // F-QA2-02 fix: dropped the "(R)" hint — there is no global R-key
      // handler. Reinstate when the keybinding is wired.
      title="Refresh all"
    >
      <RotateCw
        className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`}
        aria-hidden="true"
      />
    </button>
  );
}
