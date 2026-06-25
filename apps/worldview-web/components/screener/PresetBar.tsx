/**
 * components/screener/PresetBar.tsx — Horizontal scrollable strip of preset chips
 * (PRD-0089 Wave I-A · Block A · T-IA-01)
 *
 * WHY THIS EXISTS:
 *   The screener "preset" chip strip used to be inlined inside `ScreenerHeader`.
 *   Extracting it into a dedicated component lets:
 *     1. The Workspace screener panel (PRD-0089 §9) reuse the exact same chip
 *        strip without copy-pasting the button rendering loop.
 *     2. Each chip's styling stay testable in isolation (active vs inactive
 *        pill, hover, click handler) without spinning up the full header.
 *     3. `ScreenerHeader` shed ~20 LOC and read top-to-bottom as a thin
 *        toolbar instead of mixing layout with chip rendering.
 *
 * VISUAL CONTRACT (per design 08-screener.md §6.4 + the OLD inline rendering):
 *   - Single horizontally-scrollable row (`overflow-x-auto whitespace-nowrap`).
 *   - Active pill: `bg-primary/10 border-primary text-primary`.
 *   - Inactive: `bg-card border-border text-muted-foreground`.
 *   - Hover (inactive): `text-foreground border-border/80`.
 *   - All chips: 22px tall, monospace 10px ALL-CAPS letters, `rounded-[2px]`
 *     (Terminal-Dark forbids any larger radius in `components/screener/`).
 *   - Optional trailing `[+ New preset]` button if `onSavePreset` is supplied.
 *
 * WHO USES IT:
 *   - `components/screener/ScreenerHeader.tsx` (Row 1 of the screener page).
 *   - Future: the Workspace screener panel.
 *
 * DESIGN REF: docs/designs/0089/08-screener.md §4 + §6.4
 * PLAN REF:   docs/plans/0089-pages/I-screener-plan.md §5.1 T-IA-01
 */

"use client";
// WHY "use client": the chip strip handles click events and applies dynamic
// `aria-pressed` state. No SSR-only logic; safe to render in the browser.

import { cn } from "@/lib/utils";
import type { ScreenerPreset } from "@/lib/screener/presets";

// ── Props ────────────────────────────────────────────────────────────────────

export interface PresetBarProps {
  /** Ordered list of presets to render as chips. */
  presets: readonly ScreenerPreset[];
  /**
   * Currently active preset id, or `null` when the user's filter state does
   * not deep-equal any preset. WHY `id` (not the preset object): id is a
   * stable primitive that survives memoisation; passing the object would
   * force callers to keep referential equality with `SCREENER_PRESETS[i]`.
   */
  activeId: string | null;
  /** Fires when the user clicks a chip. Parent decides how to merge filters. */
  onApply: (preset: ScreenerPreset) => void;
  /**
   * Optional — when supplied, renders a trailing `[+ New preset]` button so
   * the user can save their current screen as a new preset. Omitting it
   * hides the button entirely (per design: don't promise un-shipped UX).
   */
  onSavePreset?: () => void;
}

// ── Component ────────────────────────────────────────────────────────────────

export function PresetBar({ presets, activeId, onApply, onSavePreset }: PresetBarProps) {
  return (
    // WHY gap-0.5 (not gap-1): with 6+ chips on a 1440px viewport, a tighter
    // gap saves ~12px of horizontal space — matters when the strip is
    // co-mounted with the title, count, filter button, and tools on a 36px
    // toolbar row. Identical to the gap used in the previous inline rendering.
    <div
      className="flex items-center gap-0.5 overflow-x-auto whitespace-nowrap"
      role="group"
      aria-label="Quick screener presets"
    >
      {presets.map((preset) => {
        const isActive = activeId === preset.id;
        return (
          <button
            key={preset.id}
            type="button"
            aria-pressed={isActive}
            onClick={() => onApply(preset)}
            className={cn(
              // WHY explicit `text-[10px]` (not text-xs): the Terminal-Dark
              // architecture test forbids `text-(sm|base|lg|xl)` inside
              // `components/screener/` so every font-size lives in a pixel-
              // exact bracketed value the design system controls.
              // ROUND-3 item 6: chips get the shared focus-visible ring so
              // Tab-navigating the preset strip is visibly tracked.
              "h-[22px] px-2 text-[10px] font-mono uppercase tracking-[0.06em] rounded-[2px] border transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              isActive
                ? "bg-primary/10 border-primary text-primary"
                : "bg-card border-border text-muted-foreground hover:text-foreground hover:border-border/80",
            )}
          >
            {preset.label}
          </button>
        );
      })}
      {/*
       * Trailing "+ New preset" button — only rendered when the parent supplies
       * an `onSavePreset` callback. WHY a separate slot (not a chip in the list):
       * it's an *action* (save), not a *preset* (filter snapshot). Mixing them
       * in the same array would force a discriminated union just for one button.
       */}
      {onSavePreset && (
        <button
          type="button"
          onClick={onSavePreset}
          aria-label="Save current filters as a new preset"
          className="h-[22px] px-2 text-[10px] font-mono uppercase tracking-[0.06em] rounded-[2px] border border-dashed border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          + New preset
        </button>
      )}
    </div>
  );
}
