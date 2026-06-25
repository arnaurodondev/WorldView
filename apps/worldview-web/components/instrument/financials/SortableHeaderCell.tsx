/**
 * components/instrument/financials/SortableHeaderCell.tsx — clickable `<th>`
 * for the Financials-tab sortable tables (Wave-4 enhancement).
 *
 * WHY THIS EXISTS: pairs with useSortableRows. A sortable column header needs
 * three things the plain `<th>`s did not have:
 *   1. a button affordance (cursor, hover, focus ring) so it reads as clickable;
 *   2. a direction arrow (▲/▼) on the ACTIVE column so the user can see at a
 *      glance which column drives the order and which way;
 *   3. correct ARIA (`aria-sort` on the cell) so screen readers announce
 *      "sorted ascending/descending" — a hard accessibility requirement for
 *      interactive tables (WAI-ARIA grid pattern).
 *
 * WHY A `<th>` WRAPPER (not a bare button): the holder tables are real
 * `<table>`s — the sortable cell must stay a `<th scope="col">` so the table
 * semantics (and `aria-sort`, which is only valid on a header cell) are
 * preserved. The PEER table is a CSS-grid of `<div>`s, so this component also
 * supports an `as="div"` mode for that layout (same visuals, role="columnheader").
 *
 * DESIGN: matches the existing 10px mono uppercase 0.08em header treatment so
 * it drops in without changing the visual rhythm — only the arrow + hover are
 * added. Active column label brightens to text-foreground so the eye locks
 * onto the sort key.
 */

"use client";
// WHY "use client": onClick handler + the arrow reflects interactive state.

import { cn } from "@/lib/utils";
import type { SortDirection } from "./useSortableRows";

export interface SortableHeaderCellProps {
  /** Visible label, e.g. "% Held". Kept short — these are dense columns. */
  readonly label: string;
  /** True when THIS column currently drives the sort (shows the arrow). */
  readonly active: boolean;
  /** Current direction — only meaningful when `active`. */
  readonly direction: SortDirection;
  /** Fired on click / Enter — the table re-sorts on this column. */
  readonly onSort: () => void;
  /** Text alignment; numeric columns are right-aligned like their cells. */
  readonly align?: "left" | "right" | "center";
  /**
   * Render element. "th" for real `<table>`s (default), "div" for the
   * CSS-grid peer board. Keeps both layouts using the same component.
   */
  readonly as?: "th" | "div";
  /** Extra classes the caller needs (grid alignment / nowrap / width). */
  readonly className?: string;
}

export function SortableHeaderCell({
  label,
  active,
  direction,
  onSort,
  align = "left",
  as = "th",
  className,
}: SortableHeaderCellProps) {
  // The inner button carries the click target + focus ring. We keep the label
  // and arrow in a flex row so the arrow hugs the label regardless of align.
  const justify =
    align === "right" ? "justify-end" : align === "center" ? "justify-center" : "justify-start";

  // Arrow glyphs: ▲ ascending (smallest→largest reading down), ▼ descending.
  // Inactive columns show a dimmed neutral ⇅ so the user knows the column is
  // sortable WITHOUT a click — discoverability over minimalism on a dense
  // terminal where affordances must be explicit.
  const arrow = active ? (direction === "asc" ? "▲" : "▼") : "⇅";

  const button = (
    <button
      type="button"
      onClick={onSort}
      // aria-pressed communicates the active state to AT in addition to the
      // cell-level aria-sort below (belt-and-braces; some SRs only read one).
      aria-pressed={active}
      className={cn(
        "group flex w-full items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] transition-colors",
        justify,
        // Active label brightens; inactive stays muted but hover-lifts so the
        // column reads as interactive on pointer-over.
        active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[1px]",
      )}
    >
      <span className="whitespace-nowrap">{label}</span>
      <span
        // The arrow is decorative — aria-sort on the cell already conveys
        // order to screen readers, so hide the glyph from the a11y tree.
        aria-hidden
        className={cn(
          "text-[8px] leading-none transition-opacity",
          active
            ? "text-primary opacity-100"
            : // Inactive ⇅ is faint until hover so it doesn't add visual noise
              // to 5–7 columns at once, but still hints sortability.
              "text-muted-foreground/40 opacity-0 group-hover:opacity-100",
        )}
      >
        {arrow}
      </span>
    </button>
  );

  // aria-sort is only valid on a header cell; map our direction → the ARIA token.
  const ariaSort: "ascending" | "descending" | "none" = active
    ? direction === "asc"
      ? "ascending"
      : "descending"
    : "none";

  if (as === "div") {
    return (
      <div
        role="columnheader"
        aria-sort={ariaSort}
        className={cn("flex h-[22px] items-center px-2", className)}
      >
        {button}
      </div>
    );
  }

  return (
    <th scope="col" aria-sort={ariaSort} className={cn("px-2 font-normal", className)}>
      {button}
    </th>
  );
}
