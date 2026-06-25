/**
 * components/portfolio/SyncErrorBadge.tsx — Persistent brokerage sync error
 * indicator badge.
 *
 * WHY THIS EXISTS (FR-7 / G-7):
 * Brokerage sync errors were hidden inside a collapsible `BrokerageStatusBanner`
 * that users rarely expanded. When SnapTrade fails to sync, the user only sees
 * stale holdings data with no indication that something went wrong. A persistent
 * red dot in the Holdings tab header is a Bloomberg-style affordance that makes
 * error state impossible to miss without being modal/blocking.
 *
 * PLACEMENT RATIONALE:
 * The badge lives in the Holdings tab header (rendered by HoldingsTab) next to
 * the last-synced timestamp. On Bloomberg Terminal, status indicators for data
 * feeds always appear adjacent to the data they describe — "red dot here means
 * THIS table's data may be stale". Not in a sidebar, not in a notification centre.
 *
 * COLOR:
 * Red `●` (text-destructive) is the platform's universal error color (DS §8.1).
 * The circle is a filled dot (●, U+25CF) rather than a border-only circle to
 * maximise contrast at small text sizes (10px mono) — a thin ring at 10px is
 * visually indistinguishable from the surrounding text.
 *
 * WHY onClick (not a link):
 * The click handler scrolls to or expands the BrokerageStatusBanner already on
 * the page (passed as `onClickScrollToErrors`). A full-page navigation would
 * lose the Holdings tab context; an inline expand is less disruptive. The parent
 * (HoldingsTab) owns the banner ref and handles the scroll imperatively.
 *
 * WHO USES IT: HoldingsTab.tsx (only when portfolio.kind === "brokerage" && errorCount > 0)
 * DATA SOURCE: HoldingsResponse.brokerage_sync_error_count (added in W3)
 */

// WHY no "use client" directive: this component has no hooks; the onClick is a
// plain event handler that does not require client-side React state. Next.js 15
// server components support event handlers only when they are serialisable, which
// an inline arrow function is not — but since the parent (HoldingsTab) is already
// "use client", this child inherits the client boundary automatically.
// If this component is ever used inside a server component directly, add "use client".

// ── Props ──────────────────────────────────────────────────────────────────────

export interface SyncErrorBadgeProps {
  /**
   * Number of unresolved brokerage sync errors from brokerage_sync_errors table.
   * 0 → renders nothing (component is a no-op).
   */
  errorCount: number;
  /**
   * Callback to scroll to / expand the BrokerageStatusBanner already present on
   * the Holdings tab. The parent owns the banner ref; this badge just triggers it.
   */
  onClickScrollToErrors: () => void;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function SyncErrorBadge({ errorCount, onClickScrollToErrors }: SyncErrorBadgeProps) {
  // WHY early return (not conditional className): rendering nothing at all means
  // no DOM node — no accessibility tree entry, no layout space, no stale aria-hidden
  // attributes to manage. The parent conditionally renders this component, so this
  // guard is a belt-and-suspenders safety net for direct call sites.
  if (errorCount === 0) return null;

  return (
    <button
      type="button"
      data-testid="sync-error-badge"
      onClick={onClickScrollToErrors}
      // WHY aria-label with count: screen readers read "3 brokerage sync errors"
      // directly from the button label — they won't interpret the visual ● dot.
      aria-label={`${errorCount} brokerage sync ${errorCount === 1 ? "error" : "errors"} — click to view`}
      // WHY no border/background on the button: the ● dot IS the badge.
      // Adding a bordered pill would clash with the tab header's h-[22px] density.
      // The text-destructive color provides sufficient affordance that this is
      // an actionable warning, not static content. hover:opacity-80 provides
      // the hover affordance without a background flash.
      className="flex items-center gap-1 font-mono text-[10px] text-destructive hover:opacity-80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-opacity"
    >
      {/* ● U+25CF BLACK CIRCLE — the "red dot" indicator.
          WHY not a Lucide icon: AlertCircle at 10px is too detailed to read;
          a plain unicode dot is crisper at this scale. */}
      <span aria-hidden="true">●</span>
      <span>
        {errorCount} sync {errorCount === 1 ? "error" : "errors"}
      </span>
    </button>
  );
}
