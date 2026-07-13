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
 * segment. Click / Enter / Space select a segment.
 *
 * A11Y — KEYBOARD (WAI-ARIA radiogroup pattern): the group is a SINGLE tab stop
 * via **roving tabindex** — only the checked radio is `tabIndex=0`, the other is
 * `tabIndex=-1`, so Tab enters/leaves the group once instead of stopping on both
 * buttons. Inside the group, Arrow keys move the selection: ArrowRight/ArrowDown
 * → next segment, ArrowLeft/ArrowUp → previous, Home → first, End → last. Per the
 * radiogroup pattern the arrow key *immediately selects* the target radio (calls
 * `onModeChange`) and moves DOM focus to it, so selection and focus stay in sync.
 * (Reference: WAI-ARIA Authoring Practices "Radio Group Using Roving tabindex".)
 *
 * TOUR: carries `data-tour-target="mode-toggle"` so the W-F onboarding tour can
 * anchor a popover to it via `document.querySelector`.
 */

"use client";
// WHY "use client": binds onClick / onKeyDown handlers and manages focus refs;
// it is composed into a client-only header. No server render of an interactive
// control.

import { useRef, type KeyboardEvent } from "react";

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
  // Refs to each radio button so an arrow key can move DOM focus to the newly
  // selected segment (the radiogroup pattern keeps focus == selection). Keyed by
  // segment value; populated on mount by the `ref` callback below.
  const radioRefs = useRef<Partial<Record<PortfolioMode, HTMLButtonElement | null>>>({});

  // WHY handle keys at the group level (not per-button): arrow navigation is a
  // property of the group, and the currently focused radio is always the checked
  // one under roving tabindex, so we can derive "next"/"prev" purely from `mode`.
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const currentIndex = SEGMENTS.findIndex((s) => s.value === mode);
    if (currentIndex === -1) return;

    let nextIndex: number | null = null;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        // Wrap to the first segment after the last (radiogroup convention).
        nextIndex = (currentIndex + 1) % SEGMENTS.length;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        nextIndex = (currentIndex - 1 + SEGMENTS.length) % SEGMENTS.length;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = SEGMENTS.length - 1;
        break;
      default:
        // Leave Tab / Enter / Space / everything else to the browser + onClick.
        return;
    }

    // Prevent the arrow keys from ALSO scrolling the page (default behaviour).
    event.preventDefault();

    const nextSeg = SEGMENTS[nextIndex];
    if (nextSeg.value !== mode) {
      // Arrow immediately selects (per the pattern) — same contract as a click.
      onModeChange(nextSeg.value);
    }
    // Move focus to the target radio so focus follows selection. Because the
    // newly selected radio becomes the sole tabIndex=0 stop, focus and roving
    // state stay consistent even when selection didn't change (Home/End on the
    // already-selected end still re-focuses harmlessly).
    radioRefs.current[nextSeg.value]?.focus();
  };

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
      // Arrow / Home / End navigation for the radiogroup (roving tabindex below).
      onKeyDown={handleKeyDown}
      // Terminal-density segmented container: 24px tall, hairline border, 2px
      // radius — matches the header action buttons beside it.
      className="inline-flex h-6 items-center rounded-[2px] border border-border/60 p-px"
    >
      {SEGMENTS.map((seg) => {
        const active = seg.value === mode;
        return (
          <button
            key={seg.value}
            // Register the button so arrow navigation can focus it.
            ref={(el) => {
              radioRefs.current[seg.value] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            // ROVING TABINDEX: only the checked radio is a tab stop (0); the other
            // is removed from the tab order (-1). Tab therefore enters/leaves the
            // whole group once, and Arrow keys move within it (WAI-ARIA pattern).
            tabIndex={active ? 0 : -1}
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
