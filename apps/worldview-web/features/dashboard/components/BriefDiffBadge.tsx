/**
 * features/dashboard/components/BriefDiffBadge.tsx — "What's new" diff pill
 * for the MorningBriefCard header (PLAN-0066 Wave F T-W10-F-01).
 *
 * WHY THIS EXISTS: When a new morning brief is generated, some bullets change
 * relative to yesterday. The diff badge surfaces this at-a-glance so the trader
 * knows immediately whether today's brief has meaningful new information, without
 * having to read the full brief first.
 *
 * BEHAVIOUR:
 * - Shows an amber pill "N new" when new_bullets exist.
 * - Shows nothing when status is "no_diff_available" (first brief ever, or only
 *   one brief exists in the archive).
 * - Clicking the pill toggles BriefDiffPanel inline below the badge.
 *
 * WHY TOKEN PROP: getBriefDiff needs an auth token for the S8 call (protected by
 * InternalJWTMiddleware). The token is passed in from MorningBriefCard (which
 * already has it from useAuth()) rather than calling useAuth() again inside here
 * — keeps the component pure/testable without AuthContext.
 *
 * WHO USES IT: MorningBriefCard header row.
 * DATA SOURCE: GET /api/v1/briefings/morning/diff (S8 via S9 proxy)
 */

"use client";
// WHY "use client": useState for open/close toggle, useQuery for data fetching.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getBriefDiff } from "@/lib/api/briefing";
import { qk } from "@/lib/query/keys";
import { BriefDiffPanel } from "./BriefDiffPanel";

// ── Props ─────────────────────────────────────────────────────────────────────

interface BriefDiffBadgeProps {
  /**
   * Auth token — passed from MorningBriefCard (which owns the useAuth() call).
   * Required for the diff endpoint which is protected by InternalJWTMiddleware.
   */
  token: string | undefined;
  /**
   * The ID of the current brief. Used as part of the query key so the diff
   * cache is invalidated when a new brief is generated (different ID).
   * WHY briefId in queryKey: without it, the old diff from yesterday's key
   * would be served even after a fresh brief lands in the same session.
   */
  briefId: string | undefined;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function BriefDiffBadge({ token, briefId }: BriefDiffBadgeProps) {
  // WHY local state (not URL params): the diff panel is transient/exploratory —
  // it doesn't need to survive a page reload or browser back navigation.
  const [open, setOpen] = useState(false);

  // WHY useQuery with stable key including briefId: when a new brief is generated
  // (new briefId), TanStack Query treats it as a new query and fetches fresh diff
  // data rather than serving the previous brief's diff from cache.
  const { data } = useQuery({
    queryKey: qk.briefing.diff(briefId),
    queryFn: () => getBriefDiff(token),
    // WHY staleTime=5min: diffs are stable for the life of the brief. We allow
    // up to 5 minutes of cache rather than fetching on every card render.
    staleTime: 5 * 60 * 1000,
    // WHY enabled: don't try to fetch if we don't have auth yet.
    enabled: !!token,
  });

  // WHY early return: the badge is hidden when:
  // 1. No data yet (loading or error) — no flash of empty badge.
  // 2. status === "no_diff_available" — first brief ever; nothing to compare.
  if (!data || data.status === "no_diff_available") return null;

  const newCount = data.new_bullets.length;

  return (
    // WHY relative: positions the BriefDiffPanel absolutely below the badge
    // so it doesn't push the header layout when it opens.
    <span className="relative inline-flex flex-col items-start">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`${newCount} new bullets in today's brief. Click to see what changed.`}
        // WHY bg-warning/10 + text-warning (was off-palette amber-400/500):
        // --warning is the design system attention token (Bloomberg amber);
        // mapping to it keeps a single source for "needs attention" badges
        // and makes the change automatically pick up future palette tweaks.
        className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning hover:bg-warning/20 transition-colors"
      >
        {/* WHY show count: traders want the exact number; "3 new" is more actionable
            than just "changes". Zero new bullets (only removals) shows "changes". */}
        {newCount > 0 ? `${newCount} new` : "changes"}
      </button>

      {/* WHY conditional render (not CSS visibility): avoids mounting BriefDiffPanel
          before the user requests it, which would trigger an extra re-render cycle. */}
      {open && (
        <BriefDiffPanel diff={data} onClose={() => setOpen(false)} />
      )}
    </span>
  );
}
