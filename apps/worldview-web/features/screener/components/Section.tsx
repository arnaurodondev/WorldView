"use client";

/**
 * features/screener/components/Section.tsx — Collapsible group of filter inputs.
 *
 * WHY EXTRACTED (PLAN-0059 E-4): every section in the screener filter bar
 * (Valuation, Profitability, Growth, Leverage, Technical, News & Signals)
 * has the same chrome — header with name + active-count badge + chevron,
 * then a grid of inputs underneath. Putting it in its own file keeps the
 * parent JSX scannable and pins the expand/collapse a11y semantics in one
 * place.
 *
 * WHY children pattern (not a config object): inputs vary per section
 * (pairs of min/max numbers, a checkbox, a select). Children give us full
 * flexibility without inventing a 7th DSL.
 *
 * WHY grid-template-rows ANIMATION (not max-height): the design system's
 * §0.5 bans animating `height` or `max-height` directly — these trigger
 * browser layout recalculation on every animation frame. The
 * `grid-template-rows: 0fr → 1fr` swap collapses/expands cleanly with a
 * pure CSS transition, no JS animation, no reflow cost.
 */

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SectionProps {
  title: string;
  /** Number of active filters in this section — shown as a small badge. */
  activeCount: number;
  /** Whether the section is open by default — true for sections users hit most. */
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export function Section({
  title,
  activeCount,
  defaultOpen = false,
  children,
}: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const sectionId = `screener-section-${title.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <div className="border-b border-border/60">
      {/* Section header — clickable row */}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={sectionId}
        onClick={() => setOpen((v) => !v)}
        // ROUND-3 item 6: focus-visible ring (inset so it isn't clipped by the
        // parent's overflow-hidden) — the section headers are the primary
        // keyboard path through the filter panel.
        className="flex w-full h-7 items-center justify-between px-2 hover:bg-white/[0.03] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <div className="flex items-center gap-2">
          {/* WHY 10px ALL CAPS font-mono: ROUND-3 typography audit (item 2) —
              this was the ONE section-label in the screener set in font-sans;
              every sibling header (the "SCREENER" bar label, ScreenerHeader's
              h1, preset chips) uses IBM Plex Mono per the filter bar's own
              "section labels use IBM Plex Mono" rule. Aligned for consistency. */}
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
            {title}
          </span>
          {activeCount > 0 && (
            // Badge — primary tint pill showing active filter count.
            // WHY only when >0: empty badges add noise; the absence itself
            // communicates "no filters set".
            <span
              className="inline-flex items-center justify-center min-w-[14px] h-[14px] px-1 text-[9px] font-mono tabular-nums bg-primary/15 text-primary rounded-[2px]"
              aria-label={`${activeCount} active filter${activeCount === 1 ? "" : "s"} in ${title}`}
            >
              {activeCount}
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-3 w-3 text-muted-foreground transition-transform duration-150",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {/* Section body — uses the §0.5 grid-rows trick for cheap collapse animation */}
      <div
        id={sectionId}
        role="region"
        aria-label={title}
        // ROUND-3 item 7: duration 200→150ms — collapse/expand capped at
        // ≤150ms ease-out per the polish spec (matches the outer panel).
        className="grid overflow-hidden transition-[grid-template-rows] duration-150 ease-out"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden min-h-0">
          <div className="px-2 py-2">{children}</div>
        </div>
      </div>
    </div>
  );
}
