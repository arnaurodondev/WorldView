/**
 * components/data/InlineEmptyState.tsx — Compact inline empty state for data panels
 *
 * WHY THIS EXISTS: Terminal data panels must never show full-height centered empty
 * states (they waste vertical space and look consumer/friendly, not institutional).
 * This component provides a dense, single-line empty indicator that keeps the panel
 * height stable while communicating "no data available."
 *
 * WHY text-xs py-3 (not text-[14px] p-8): Bloomberg panels show a single muted line
 * at the bottom of a table when there are no rows — not a full-page centered
 * illustration. The padding reserves just enough space for the message to breathe
 * without inflating the panel.
 *
 * WHO USES IT: HoldingsTable, TransactionsTable, WatchlistTable, AlertsList,
 *             RecentAlerts, IntelligenceTab, any data panel with a no-data state.
 * DESIGN REFERENCE: PRD-0028 §6.5 Terminal Design Rules §4.5
 */

// WHY no "use client": pure presentational, no hooks or browser APIs.

import { cn } from "@/lib/utils";

interface InlineEmptyStateProps {
  /** The message to display, e.g. "No holdings yet." */
  message: string;
  /** Optional extra Tailwind classes (e.g. to adjust py-* or text alignment) */
  className?: string;
}

/**
 * InlineEmptyState — a single compact text line for empty data panels.
 *
 * Usage:
 *   <InlineEmptyState message="No holdings yet." />
 *   <InlineEmptyState message="No alerts." className="py-2" />
 */
export function InlineEmptyState({ message, className }: InlineEmptyStateProps) {
  return (
    // WHY py-3 text-xs: minimal height, stays within a terminal panel without
    // dominating the visual weight of the panel header above it.
    // WHY role="status" aria-live="polite": when the empty state appears after
    // a data fetch (e.g. filter returns 0 rows), AT users need to hear the change;
    // "polite" queues the announcement without interrupting ongoing speech.
    <p
      role="status"
      aria-live="polite"
      className={cn("py-3 text-xs text-muted-foreground", className)}
    >
      {message}
    </p>
  );
}
