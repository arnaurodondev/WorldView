/**
 * components/portfolio/RootPortfolioPopover.tsx — "All Accounts" explanation
 * popover for the ROOT portfolio (PRD-0114 W5-T07).
 *
 * WHY THIS EXISTS: EnsureRootPortfolioUseCase provisions an "All Accounts"
 * portfolio for every user, but the frontend used to treat it identically to
 * a normal named portfolio. First-time users see "All Accounts" with an "ALL"
 * badge but no explanation of what it means or why they can't add positions to
 * it. This popover bridges that knowledge gap.
 *
 * BEHAVIOUR:
 *   - Renders an ℹ icon button next to the "All Accounts" selector entry.
 *   - Clicking the ℹ opens a shadcn/ui Popover with explanatory copy.
 *   - Dismissing the popover (via the "Got it" button or clicking away) sets
 *     `localStorage["worldview:root_portfolio_popover_dismissed"] = "1"`.
 *   - On subsequent page loads, the icon still renders (for discoverability)
 *     but the popover does NOT auto-open (the dismissed state is checked on
 *     first render via useEffect).
 *   - Renders nothing when `portfolio.kind !== "root"` (caller checks this).
 *
 * WHY localStorage (not a cookie or server-side preference):
 *   - This is a one-time tooltip — it has no impact on data or security.
 *   - localStorage survives page refreshes without a server round-trip.
 *   - It is per-device, which is appropriate: the user on a new device should
 *     see the tooltip again until they dismiss it there too.
 *   - If localStorage is unavailable (private browsing, quota exceeded) we
 *     degrade gracefully by always showing the popover on mount — no crash.
 *
 * WHY the icon remains after dismissal:
 *   Hiding the ℹ after dismissal makes the explanation permanently
 *   inaccessible. A user who forgets what "All Accounts" means after a month
 *   should still be able to click the ℹ to remind themselves.
 *
 * WHO USES IT: features/portfolio/components/PortfolioPageHeader.tsx
 */

"use client";
// WHY "use client": Popover uses browser events, localStorage is browser-only,
// and we use useState/useEffect for the dismissed-state check.

import { useState, useEffect } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { Info } from "lucide-react";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * DISMISSED_KEY — localStorage key used to remember that the user has read
 * and dismissed the "All Accounts" popover.
 *
 * WHY a scoped prefix ("worldview:"): prevents key collisions with other
 * libraries or user scripts that might use the same localStorage namespace.
 * The "root_portfolio_popover_dismissed" suffix is descriptive enough that
 * a dev inspecting localStorage instantly knows what this key is for.
 */
export const DISMISSED_KEY = "worldview:root_portfolio_popover_dismissed";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface RootPortfolioPopoverProps {
  /**
   * The kind of the currently active portfolio. The component is a no-op
   * when kind is not "root" — the caller can render it unconditionally and
   * let it decide whether to show anything.
   *
   * WHY optional: callers that have already checked kind before rendering
   * don't need to pass it; omitting it gives "root" behaviour (safe default
   * for the primary use-case of rendering this next to the "All Accounts"
   * entry in the selector).
   */
  portfolioKind?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RootPortfolioPopover({
  portfolioKind = "root",
}: RootPortfolioPopoverProps) {
  // ── Dismissed state ────────────────────────────────────────────────────────
  // WHY useState + useEffect (not direct localStorage.getItem in render):
  //   localStorage.getItem is a browser-only API — calling it during server-side
  //   rendering (Next.js) would throw. Using useEffect defers the read to after
  //   hydration when we're guaranteed to be in the browser.
  const [isDismissed, setIsDismissed] = useState(false);

  useEffect(() => {
    try {
      const val = localStorage.getItem(DISMISSED_KEY);
      // Any truthy stored value (we write "1") means dismissed.
      if (val) setIsDismissed(true);
    } catch {
      // localStorage unavailable (private browsing, quota exceeded) —
      // degrade gracefully by never setting dismissed.
    }
  }, []);

  // ── Popover open state ─────────────────────────────────────────────────────
  // WHY separate open state (not rely on Radix controlled mode alone):
  //   We want to auto-open the popover on first visit (isDismissed === false)
  //   but NOT auto-open on subsequent visits. A controlled `open` prop lets us
  //   express "open when not dismissed AND not manually closed" cleanly.
  //
  // Design decision: after the first manual close (via "Got it" or click-away),
  // the popover stays closed unless the user explicitly clicks the ℹ again —
  // we achieve this by setting dismissed=true on close, which prevents
  // the auto-open logic from re-triggering.
  const [isOpen, setIsOpen] = useState(false);

  // Auto-open on first render after we confirm the user hasn't dismissed it.
  // WHY a separate useEffect from the localStorage read: the dismissed state
  // must be read BEFORE we decide to auto-open, so we depend on isDismissed.
  useEffect(() => {
    if (!isDismissed) {
      // Auto-open so first-time visitors see the explanation without having
      // to discover the ℹ button. setIsOpen deferred to ensure the DOM is
      // fully painted (avoids Radix animation flicker on mount).
      const timer = setTimeout(() => setIsOpen(true), 300);
      return () => clearTimeout(timer);
    }
  }, [isDismissed]);

  // ── Early exit AFTER all hooks (Rules of Hooks) ───────────────────────────
  // WHY here (not at the top): React requires hooks to run on every render,
  // so the early return must come after the four useState/useEffect calls above.
  // The hooks are cheap no-ops when portfolioKind !== "root"; the only cost is
  // four tiny state slots that are never updated.
  if (portfolioKind !== "root") return null;

  // ── Dismiss handler ────────────────────────────────────────────────────────

  function handleDismiss() {
    setIsOpen(false);
    setIsDismissed(true);
    try {
      // Write the dismissed flag to localStorage so it persists across page
      // refreshes. "1" is the canonical truthy value for this key.
      localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // localStorage write failure (quota exceeded, private browsing) —
      // the UI still closes; the state just won't persist to next visit.
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <Popover
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          // The popover was closed (by Escape key, outside click, or "Got it").
          // Record the dismissal so it doesn't auto-open on the next page load.
          handleDismiss();
        }
        setIsOpen(open);
      }}
    >
      <PopoverTrigger asChild>
        {/* WHY aria-label: the ℹ symbol alone is not meaningful to screen
            readers. The aria-label provides the full semantic intent. */}
        <button
          type="button"
          aria-label="Learn about All Accounts portfolio"
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {/* WHY strokeWidth={1.5}: Lucide default 2 reads as too heavy for
              a small informational icon in terminal chrome. */}
          <Info className="h-3 w-3" strokeWidth={1.5} />
        </button>
      </PopoverTrigger>

      <PopoverContent
        // WHY w-72: 288px is wide enough for the explanatory copy to read
        // comfortably (3-4 words per line at 11px font) without being so wide
        // that it overflows the viewport on smaller screens.
        className="w-72"
        // WHY align="start": aligns the popover to the leading edge of the
        // trigger. The ℹ icon is typically at the start of a selector entry;
        // "start" alignment means the popover opens below-left rather than
        // centred, which avoids covering the portfolio selector dropdown.
        align="start"
        // Slight downward offset so the popover doesn't overlap the trigger.
        sideOffset={6}
      >
        <div className="flex flex-col gap-3">
          {/* ── Heading ─────────────────────────────────────────────────── */}
          <div>
            <p className="font-mono text-[12px] font-semibold text-foreground">
              All Accounts (Aggregate View)
            </p>
          </div>

          {/* ── Explanatory copy (PRD §4 FR-9) ──────────────────────────── */}
          <div className="flex flex-col gap-1.5 text-[11px] text-muted-foreground leading-relaxed">
            <p>
              <strong className="text-foreground">All Accounts</strong> is an
              automatically created, read-only view that combines holdings and
              performance across ALL of your portfolios (manual + brokerage).
            </p>
            <p>
              You cannot add or remove positions here — switch to a specific
              portfolio to record trades.
            </p>
            <p>
              Holdings update automatically whenever any sub-portfolio changes.
            </p>
          </div>

          {/* ── Dismiss button ────────────────────────────────────────────── */}
          <div className="flex justify-end">
            <Button
              variant="outline"
              size="sm"
              // WHY h-6: matches the terminal chrome's 24px control height so
              // the button integrates without introducing height inconsistency.
              className="h-6 px-3 text-[10px] font-mono"
              onClick={handleDismiss}
            >
              Got it
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
