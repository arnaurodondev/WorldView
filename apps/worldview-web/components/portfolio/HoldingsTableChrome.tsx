/**
 * HoldingsTableChrome — 22px header row above the AG Grid holdings table.
 *
 * WHY THIS EXISTS: The holdings table needs a thin chrome row showing position
 * count, active sort, and a Ctrl+F filter shortcut hint. Bloomberg terminal uses
 * an identical pattern (filter input in the table chrome, not inline in the grid).
 * WHO USES IT: portfolio overview page, immediately above SemanticHoldingsTable.
 * DATA SOURCE: sort state from AG Grid column state; position count from holdings array.
 * DESIGN REFERENCE: PRD-0089 W2 §4.7
 */
"use client";
// WHY "use client": useEffect attaches document keydown listener; useRef for input focus.

import { useEffect, useRef, type ReactNode } from "react";

interface HoldingsTableChromeProps {
  positionCount: number;
  /** Callback when Ctrl+F fires externally (not via button) — parent can use for AG Grid focus. */
  onFilterFocus: () => void;
  /** Current filter text — shown in the filter input. */
  filterText: string;
  onFilterChange: (v: string) => void;
  filterVisible: boolean;
  onFilterVisibleChange: (v: boolean) => void;
  /**
   * PLAN-0122 W-E: optional trailing control rendered at the right of the chrome
   * row (the ⚙ HoldingsColumnGroupToggle). Optional + additive so every existing
   * caller/snapshot that omits it is byte-identical. Sits left of the filter hint.
   */
  columnToggle?: ReactNode;
}

export function HoldingsTableChrome({
  positionCount,
  onFilterFocus,
  filterText,
  onFilterChange,
  filterVisible,
  onFilterVisibleChange,
  columnToggle,
}: HoldingsTableChromeProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  // Ctrl+F / Cmd+F: reveal filter bar and focus the input.
  // WHY capture at document level: the hotkey must work regardless of which
  // element has focus (the grid absorbs keyboard events when a cell is selected).
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault(); // prevent browser find-in-page
        onFilterVisibleChange(true);
        onFilterFocus();
        setTimeout(() => inputRef.current?.focus(), 0);
      }
      if (e.key === "Escape" && filterVisible) {
        onFilterChange("");
        onFilterVisibleChange(false);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterVisible]);

  return (
    <div className="shrink-0 bg-card border-b border-border">
      {/* Chrome row: label + count + filter hint */}
      <div className="flex h-[22px] items-center px-3 gap-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Positions</span>
        <span className="font-mono text-[11px] tabular-nums text-foreground">{positionCount}</span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              onFilterVisibleChange(!filterVisible);
              if (!filterVisible) setTimeout(() => inputRef.current?.focus(), 0);
            }}
            className="text-[10px] font-mono text-muted-foreground hover:text-foreground"
          >
            ⎵ filter (Ctrl+F)
          </button>
          {/* W-E: ⚙ column-group toggle (Advanced only — the parent passes it as
              null in Simple). Kept last so it anchors the row's right edge. */}
          {columnToggle}
        </div>
      </div>

      {/* Filter input — only visible when filterVisible=true.
          WHY second row (not inline in chrome): keeps the 22px chrome row height
          fixed. AG Grid re-measures row heights on DOM changes; a growing chrome
          row would trigger unnecessary relayout. A separate 22px sub-row is stable. */}
      {filterVisible && (
        <div className="flex items-center h-[22px] border-t border-border px-3 gap-2">
          <span className="text-[10px] text-muted-foreground">Filter:</span>
          <input
            ref={inputRef}
            type="text"
            value={filterText}
            onChange={(e) => onFilterChange(e.target.value)}
            className="flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground"
            placeholder="ticker, name, sector..."
            aria-label="Filter holdings"
          />
          {filterText && (
            <button
              type="button"
              onClick={() => {
                onFilterChange("");
                inputRef.current?.focus();
              }}
              // R4 hardening (a11y): the bare "×" glyph gave this button the
              // accessible name "×" — meaningless to a screen reader. The
              // explicit label names the action; the glyph stays the visual.
              aria-label="Clear holdings filter"
              className="text-[10px] text-muted-foreground hover:text-foreground"
            >
              ×
            </button>
          )}
        </div>
      )}
    </div>
  );
}
