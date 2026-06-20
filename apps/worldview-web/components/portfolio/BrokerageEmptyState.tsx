/**
 * BrokerageEmptyState — empty state for brokerage portfolios and no-connection pages.
 *
 * WHY THIS EXISTS (PRD-0114 W4 / FR-5 / G-5):
 * Updated to support two roles via the `variant` prop:
 *
 * 1. `variant="awaiting-sync"` (default): Shown when a BROKERAGE portfolio has
 *    been created (SnapTrade OAuth) but has no holdings yet. Reassures the user
 *    that their connection is active and positions are on the way.
 *
 * 2. `variant="no-connection"`: Original copy for the general case where the user
 *    has no brokerage connection at all. Preserved for backward compatibility —
 *    existing call sites with no variant prop still render the original UI.
 *
 * WHY a variant prop instead of two separate components: both states share the
 * same visual skeleton (centered copy + optional CTA) and are logically related
 * (same journey, different stage). A prop keeps the diff minimal and test coverage
 * concentrated.
 *
 * WHO USES IT:
 *   - HoldingsTab.tsx (variant="awaiting-sync", when kind="brokerage" + empty holdings)
 *   - Legacy no-brokerage surfaces (variant="no-connection" or no prop)
 *
 * DATA SOURCE: none — static copy.
 * DESIGN REFERENCE: PRD-0089 W2 §4.15, PRD-0114 §7.2
 */
import Link from "next/link";

export interface BrokerageEmptyStateProps {
  /**
   * "awaiting-sync": BROKERAGE portfolio exists but no holdings yet (default).
   * "no-connection": User has no brokerage connection at all.
   */
  variant?: "awaiting-sync" | "no-connection";
}

export function BrokerageEmptyState({ variant = "awaiting-sync" }: BrokerageEmptyStateProps) {
  if (variant === "awaiting-sync") {
    return (
      <div
        data-testid="brokerage-empty-state-awaiting"
        className="flex h-full flex-col items-center justify-center gap-4 bg-background"
      >
        <div className="text-center space-y-2 max-w-xs">
          <p className="font-mono text-[13px] text-foreground">
            Awaiting first sync
          </p>
          <p className="font-mono text-[11px] text-muted-foreground leading-relaxed">
            Your brokerage connection is active. Holdings will appear here
            once the first sync completes — check back in a few minutes.
          </p>
          <p className="font-mono text-[11px] text-muted-foreground">
            Check the connection status in the{" "}
            <Link
              href="/portfolio/brokerage"
              className="text-primary hover:underline"
            >
              Brokerage settings
            </Link>
            .
          </p>
        </div>
      </div>
    );
  }

  // variant === "no-connection" — original copy from PRD-0089 W2
  return (
    <div
      data-testid="brokerage-empty-state-no-connection"
      className="flex flex-1 flex-col items-center justify-center gap-5 bg-background"
    >
      <div className="text-center">
        <p className="font-mono text-[13px] text-foreground">No positions tracked yet</p>
        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
          Connect a brokerage to sync your holdings automatically,
        </p>
        <p className="font-mono text-[11px] text-muted-foreground">
          or add a portfolio manually.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Link
          href="/portfolio/brokerage"
          className="h-8 px-4 font-mono text-[11px] uppercase tracking-[0.06em] border border-primary text-primary hover:bg-primary/10 flex items-center"
        >
          Connect Brokerage
        </Link>
      </div>
    </div>
  );
}
