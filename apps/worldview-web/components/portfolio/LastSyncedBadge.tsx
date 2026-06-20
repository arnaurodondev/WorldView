/**
 * components/portfolio/LastSyncedBadge.tsx — Last-synced timestamp badge for
 * brokerage portfolios.
 *
 * WHY THIS EXISTS (FR-4 / G-4):
 * The `brokerage_connections.last_synced_at` field has always existed in S1's
 * database, but was never surfaced in any holdings response. Power users had no
 * way to know whether the positions shown were 5 minutes old or 5 hours old —
 * critical information when SnapTrade sync may be delayed or throttled.
 *
 * WHY caller-controlled visibility:
 * This badge should only appear for BROKERAGE portfolios. Rather than
 * checking `portfolio.kind` inside the component (coupling it to the Portfolio
 * type), we let the parent (HoldingsTab) decide when to render it. This keeps
 * the component a pure presenter for a timestamp value — easier to test, easier
 * to reuse in other surfaces.
 *
 * WHO USES IT: HoldingsTab.tsx (only when portfolio.kind === "brokerage")
 * DATA SOURCE: HoldingsResponse.brokerage_last_synced_at (added in W3)
 */

"use client";
// WHY "use client": uses useFormattedTimestamp which is a client hook.
// Even though the hook is currently pure (no subscriptions), it is marked
// "use client" to allow future live-update behaviour without a cascade refactor.

import { useFormattedTimestamp } from "@/lib/hooks/useFormattedTimestamp";

// ── Props ──────────────────────────────────────────────────────────────────────

export interface LastSyncedBadgeProps {
  /**
   * ISO 8601 UTC string from brokerage_connections.last_synced_at.
   * null means the connection exists but has never successfully synced.
   */
  lastSyncedAt: string | null;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function LastSyncedBadge({ lastSyncedAt }: LastSyncedBadgeProps) {
  // useFormattedTimestamp returns "—" for null/invalid inputs.
  // We use "relative" format so users see "2h ago" rather than a raw UTC
  // timestamp — relative time is more actionable ("is this stale?").
  // WHY not "short": "short" gives "May 19, 2026" — for sync recency, relative
  // time ("2h ago", "just now") is a better signal than a calendar date.
  const relativeTime = useFormattedTimestamp(lastSyncedAt, "relative");

  // null lastSyncedAt → the connection exists but no sync has occurred yet.
  // We show "Never synced" in muted text so the user knows the integration
  // exists but hasn't produced data yet.
  if (!lastSyncedAt) {
    return (
      <span
        data-testid="last-synced-badge-never"
        className="font-mono text-[10px] text-muted-foreground"
      >
        Never synced
      </span>
    );
  }

  return (
    <span
      data-testid="last-synced-badge"
      className="font-mono text-[10px] text-muted-foreground"
      // WHY title: on hover, show the exact ISO timestamp so users can
      // cross-check with their brokerage's activity log if needed.
      title={`Last synced: ${lastSyncedAt}`}
    >
      Last synced: {relativeTime}
    </span>
  );
}
