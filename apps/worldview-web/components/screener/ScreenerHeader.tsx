/**
 * components/screener/ScreenerHeader.tsx — 36px screener toolbar (PLAN-0092 Wave D)
 *
 * WHY THIS EXISTS: The original screener page.tsx inlined the toolbar HTML
 * (~30 lines) in the page component, making the page hard to read and the
 * toolbar hard to test independently. Extracting it into ScreenerHeader:
 *   - Reduces page.tsx by ~30 lines (part of the 410→~250 target)
 *   - Puts the PresetBar in a clearly named component
 *   - Makes the toolbar unit-testable (children pattern)
 *
 * LAYOUT (36px height):
 *   [SCREENER · count] [All][Large Cap][Dividend][Value][Growth][Profitable]
 *   ─────────────────────────────────────── [Filters▼] [Saved] [⚙] [↓]
 *
 * WHY PresetBar is embedded (not a separate component import):
 *   The preset chips are so simple (6 buttons sharing one onClick handler)
 *   that a separate file would add more indirection than value. The chip strip
 *   is co-located here where it's used.
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 * DESIGN REF: docs/designs/0089/08-screener.md §3.1
 */

"use client";

import { SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FilterState } from "@/features/screener/lib/filter-state";
import { SCREENER_PRESETS } from "@/lib/screener/presets";
// PRD-0089 Wave I-A · T-IA-01: the inline preset chip rendering was extracted
// into a dedicated `<PresetBar>` so the Workspace screener panel can reuse it.
import { PresetBar } from "@/components/screener/PresetBar";

// ── Props ────────────────────────────────────────────────────────────────────

export interface ScreenerHeaderProps {
  /** Total result count from the backend (response.total). */
  totalResults: number;
  /** Whether the initial fetch is in progress. */
  isLoading: boolean;
  /** Whether a background refetch is in progress. */
  isFetching: boolean;
  /** Whether the filter panel is currently open. */
  filtersOpen: boolean;
  /** Toggle the filter panel. */
  onToggleFilters: () => void;
  /** Called when the user selects a preset chip. */
  onApplyPreset: (filters: FilterState) => void;
  /** Active preset id (or null if no preset matches current filters). */
  activePresetId: string | null;
  /** Right-side action buttons (Saved Screens, ColumnSettings, Export). */
  toolbarActions: React.ReactNode;
}

// ── Component ────────────────────────────────────────────────────────────────

export function ScreenerHeader({
  totalResults,
  isLoading,
  isFetching,
  filtersOpen,
  onToggleFilters,
  onApplyPreset,
  activePresetId,
  toolbarActions,
}: ScreenerHeaderProps) {
  return (
    <div className="flex h-[36px] shrink-0 items-center border-b border-border px-3 gap-2 bg-background">
      {/* ── Title + count ─────────────────────────────────────────────── */}
      <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-mono shrink-0">
        Instrument Screener
      </h1>
      <span
        className="font-mono text-[10px] tabular-nums uppercase tracking-[0.06em] text-muted-foreground shrink-0"
        aria-label="Total results"
      >
        {isLoading ? "…" : `${totalResults.toLocaleString()}`}
      </span>
      {/* Background-fetch spinner dot */}
      {isFetching && !isLoading && (
        <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" aria-label="Loading" />
      )}

      {/* ── Preset chip strip ──────────────────────────────────────────── */}
      {/* T-IA-01: extracted to <PresetBar>. WHY the wrapper passes the
       *  `preset` object to `onApply` but ScreenerHeaderProps expects
       *  `(filters: FilterState) => void`: we unwrap `preset.filters` here so
       *  call-sites of ScreenerHeader (page.tsx) keep their original signature
       *  unchanged — pure refactor, zero behaviour drift. */}
      <PresetBar
        presets={SCREENER_PRESETS}
        activeId={activePresetId}
        onApply={(preset) => onApplyPreset(preset.filters)}
      />

      {/* ── Spacer ─────────────────────────────────────────────────────── */}
      <div className="ml-auto flex items-center gap-1">
        {/* Filters toggle button */}
        <button
          type="button"
          aria-label="Toggle screener filters"
          aria-expanded={filtersOpen}
          onClick={onToggleFilters}
          className={cn(
            // ROUND-3 item 6: focus-visible ring (shared --ring yellow) so the
            // keyboard path to the filter panel is as visible as the hover one.
            "flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            filtersOpen
              ? "bg-primary/10 border-primary/60 text-primary"
              : "bg-background border-border text-muted-foreground hover:text-foreground hover:border-border/80",
          )}
        >
          <SlidersHorizontal className="h-3 w-3 shrink-0" aria-hidden strokeWidth={1.5} />
          Filters
        </button>
        {/* Caller-provided tool buttons (Saved, ⚙, export) */}
        {toolbarActions}
      </div>
    </div>
  );
}
