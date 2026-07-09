/**
 * components/portfolio/PortfolioModeToggle.tsx — Simple | Advanced segmented
 * control (PLAN-0122 W-A, PRD-0122 §6.1 "Mode toggle control").
 *
 * WHY THIS EXISTS: the portfolio page renders in two detail levels (Simple for
 * casual users, Advanced for the full analytics layout). This is the visible
 * affordance that switches between them. It is intentionally **presentational** —
 * it takes the current `mode` and an `onModeChange` callback; the page header
 * owns the `usePortfolioMode` hook. Keeping the hook out of this component lets
 * us unit-test the control in isolation (no nuqs/router needed).
 *
 * A11Y: rendered as a `role="radiogroup"` with two `role="radio"` segments —
 * that is the correct ARIA pattern for "pick exactly one of a small set". Screen
 * readers announce "Portfolio detail level, radio group" and the checked
 * segment. Click / Enter / Space select a segment; arrow-key roving is a nice-to-
 * have not required for the MVP (the plan lists it as optional).
 *
 * TOUR: carries `data-tour-target="mode-toggle"` so the W-F onboarding tour can
 * anchor a popover to it via `document.querySelector`.
 */

"use client";
// WHY "use client": binds onClick handlers and is composed into a client-only
// header. No server render of an interactive control.

import { cn } from "@/lib/utils";
import type { PortfolioMode } from "@/hooks/usePortfolioMode";

interface PortfolioModeToggleProps {
  /** The currently active mode — drives which segment reads as checked. */
  mode: PortfolioMode;
  /** Called with the newly selected mode when a segment is clicked. */
  onModeChange: (mode: PortfolioMode) => void;
}

// WHY a data-driven segment list (not two hand-written buttons): guarantees both
// segments share identical density/interaction styling, so they can never drift.
// `label` is the exact copy the PRD pins ("Simple" / "Advanced").
const SEGMENTS: ReadonlyArray<{ value: PortfolioMode; label: string }> = [
  { value: "simple", label: "Simple" },
  { value: "advanced", label: "Advanced" },
];

export function PortfolioModeToggle({ mode, onModeChange }: PortfolioModeToggleProps) {
  return (
    <div
      // role="radiogroup" + per-segment role="radio" is the semantic contract the
      // W-A test pins; it is also what makes the control announce correctly.
      role="radiogroup"
      aria-label="Portfolio detail level"
      // title = hover tooltip explaining the two modes (PRD copy).
      title="Switch between a simple overview and the full analytics layout"
      // W-F tour anchor — resolved by document.querySelector("[data-tour-target]").
      data-tour-target="mode-toggle"
      // Terminal-density segmented container: 24px tall, hairline border, 2px
      // radius — matches the header action buttons beside it.
      className="inline-flex h-6 items-center rounded-[2px] border border-border/60 p-px"
    >
      {SEGMENTS.map((seg) => {
        const active = seg.value === mode;
        return (
          <button
            key={seg.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onModeChange(seg.value)}
            className={cn(
              // Base: mono uppercase micro-label, equal padding so the two
              // segments are visually balanced.
              "h-full rounded-[1px] px-2 text-[10px] font-mono uppercase tracking-[0.06em] transition-colors",
              // WHY explicit bg on the active segment (semantic tokens, not a
              // transparent tint): guards against the `hsl(var())` "no-paint"
              // class of bug — the active state must visibly fill in dark theme.
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {seg.label}
          </button>
        );
      })}
    </div>
  );
}
