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

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

export function RefreshAllButton() {
  const queryClient = useQueryClient();
  const [spinning, setSpinning] = useState(false);

  function handleRefresh() {
    // Fire-and-forget: invalidateQueries returns a promise but we don't
    // need to await it (the spinner is purely UX feedback).
    void queryClient.invalidateQueries();
    setSpinning(true);
    // 600ms ≈ one full rotation at the default 1s spin animation, gives
    // visual confirmation without lingering after the data has refetched.
    window.setTimeout(() => setSpinning(false), 600);
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
      title="Refresh all (R)"
    >
      <RotateCw
        className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`}
        aria-hidden="true"
      />
    </button>
  );
}
