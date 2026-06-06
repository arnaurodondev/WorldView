/**
 * components/primitives/FreshnessDot.tsx — 6px live/stale/closed indicator
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — every ticker/price surface needs an
 * unambiguous freshness indicator so analysts trust (or distrust) values.
 * Pre-F1 multiple surfaces re-rendered their own dot. The single primitive
 * keeps color + size + accessibility consistent across pages.
 * WHO USES IT: Watchlist row, ticker chip in Quote header, Dashboard
 *   top-stats, Workspace data panels.
 * DATA SOURCE: Reads `freshness_status` directly from
 *   /v1/quotes/batch.freshness_status (no client-side timers, per FU-3.6).
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (FreshnessDot row).
 */

import type { ReactNode } from "react";

type FreshnessStatus = "live" | "stale" | "closed" | "after-hours";

interface FreshnessDotProps {
  readonly status: FreshnessStatus;
}

const COLOR_CLASS: Record<FreshnessStatus, string> = {
  live: "bg-positive",
  stale: "bg-warning",
  closed: "bg-muted-foreground",
  // After-hours = trading is open but not the regular session.  Use
  // accent-ai violet (consistent with FU-3.6) — instantly distinguishable
  // from the live green / closed grey states.
  "after-hours": "bg-[hsl(var(--accent-ai))]",
};

const LABEL: Record<FreshnessStatus, string> = {
  live: "live data",
  stale: "stale data",
  closed: "market closed",
  "after-hours": "after-hours session",
};

export function FreshnessDot({ status }: FreshnessDotProps): ReactNode {
  return (
    <span
      role="img"
      aria-label={LABEL[status]}
      // WHY rounded-full: the only intentional-radius primitive in the F1
      // scope. Dots and avatars are the lone allowlist for `rounded-full`
      // in the sharp-corners contract (plan §4 row 1).
      className={`inline-block h-[6px] w-[6px] rounded-full ${COLOR_CLASS[status]}`}
    />
  );
}
