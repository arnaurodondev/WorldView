/**
 * components/portfolio/ManualPortfolioEmptyState.tsx — Onboarding empty state
 * for MANUAL portfolios with no holdings.
 *
 * WHY THIS EXISTS (FR-5 / G-5):
 * The most critical gap found in the 2026-06-20 investigation: a user who creates
 * a MANUAL portfolio and records their first BUY transaction sees an empty AG Grid
 * with no explanation. The generic empty state ("No rows to show") comes from
 * AG Grid's default overlay — it gives no hint that holdings are computed from
 * transactions, or that the user should be patient while the consumer processes
 * the event.
 *
 * This component replaces that default with a clear onboarding affordance:
 *   1. Headline that names the portfolio type ("Manual portfolio" — not generic).
 *   2. Body copy explaining the relationship between transactions and holdings.
 *   3. A primary CTA that opens the AddPositionDialog directly, reducing the
 *      friction of finding the button in the tab header.
 *
 * WHY shadcn/ui Button (not a custom styled element):
 * The Button component enforces consistent focus rings, disabled states, and
 * keyboard navigation — all required for A11y (PRD-0114 §2). A custom `<div>`
 * or `<a>` would require manual reimplementation of these behaviours.
 *
 * WHY onOpenAddPosition prop (not a router.push):
 * The AddPositionDialog is a modal rendered at the page level (lazy-loaded via
 * React.lazy). Opening it via a callback prop avoids coupling this component to
 * the page's dialog state or routing — easier to test (mock the callback) and
 * easier to reuse on other surfaces.
 *
 * WHO USES IT: HoldingsTab.tsx (only when portfolio.kind === "manual" && holdings.length === 0)
 * DATA SOURCE: none — static copy + one prop callback.
 * DESIGN REFERENCE: PRD-0114 §7.2
 */

// WHY no "use client": the Button from shadcn/ui works in RSC when onClick
// is a client-defined function. The parent (HoldingsTab) is already "use client"
// so this child inherits the client boundary. Adding "use client" here would
// unnecessarily force a separate client-component boundary.

import { Button } from "@/components/ui/button";

// ── Props ──────────────────────────────────────────────────────────────────────

export interface ManualPortfolioEmptyStateProps {
  /**
   * Callback to open the AddPositionDialog. Wired by HoldingsTab to the same
   * setAddPositionOpen(true) that the tab header button triggers — single source
   * of truth for dialog open state.
   */
  onOpenAddPosition: () => void;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function ManualPortfolioEmptyState({ onOpenAddPosition }: ManualPortfolioEmptyStateProps) {
  return (
    // WHY h-full flex-col items-center justify-center: this component fills the
    // AG Grid slot (flex-1 min-h-0) — centering vertically gives it the same
    // visual weight as AG Grid's own empty overlay, which users are familiar with.
    <div
      data-testid="manual-portfolio-empty-state"
      className="flex h-full flex-col items-center justify-center gap-4 bg-background"
    >
      {/* Headline block — explains the portfolio type + current state.
          WHY "No positions yet" (not "No holdings yet"):
          "Positions" is the Bloomberg-grade term for what you hold in a portfolio.
          "Holdings" is more generic and appears in the tab label; repeating it
          in the empty state would be redundant. "No positions yet" implies that
          positions are expected — it sets up the body copy that follows. */}
      <div className="text-center space-y-2 max-w-xs">
        <p
          data-testid="manual-empty-headline"
          className="font-mono text-[13px] text-foreground"
        >
          No positions yet
        </p>

        {/* Body copy: explains the manual → transaction → holdings relationship.
            WHY mention "within seconds": users who have already recorded a
            transaction but see this page need reassurance that the async
            computation (W1 consumer) is working, not that their data was lost.
            "within seconds" sets a correct expectation for the event-driven
            update path. */}
        <p className="font-mono text-[11px] text-muted-foreground leading-relaxed">
          Record a transaction to start tracking your portfolio.
          Holdings will appear within seconds of each trade.
        </p>

        {/* Secondary copy: clarifies that holdings are derived — not entered directly.
            This prevents the confusion of "why can't I just enter a holding
            amount directly?" which is a common new-user question. */}
        <p className="font-mono text-[11px] text-muted-foreground">
          Use the{" "}
          <span className="text-foreground">Record Transaction</span>{" "}
          button above or click below to add your first trade.
        </p>
      </div>

      {/* Primary CTA — same action as the "Add Position" button in the tab header.
          WHY variant="default" (not "outline"): this is the only action on the
          empty state; it should have the highest visual weight. Secondary actions
          (like "Connect a brokerage") would use "outline". */}
      <Button
        data-testid="manual-empty-cta"
        variant="default"
        size="sm"
        onClick={onOpenAddPosition}
        className="font-mono text-[11px] uppercase tracking-[0.06em]"
      >
        Record Transaction
      </Button>
    </div>
  );
}
