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
        Screener
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
      {/* WHY gap-0.5 (not gap-1): 6 chips at 1440px; tighter gap saves ~12px. */}
      <div className="flex items-center gap-0.5 overflow-x-auto" role="group" aria-label="Quick screener presets">
        {SCREENER_PRESETS.map((preset) => {
          const isActive = activePresetId === preset.id;
          return (
            <button
              key={preset.id}
              type="button"
              aria-pressed={isActive}
              onClick={() => onApplyPreset(preset.filters)}
              className={cn(
                "h-[22px] px-2 text-[10px] font-mono uppercase tracking-[0.06em] rounded-[2px] border transition-colors shrink-0",
                isActive
                  ? "bg-primary/15 border-primary/60 text-primary"
                  : "bg-transparent border-border/50 text-muted-foreground hover:text-foreground hover:border-border",
              )}
            >
              {preset.label}
            </button>
          );
        })}
      </div>

      {/* ── Spacer ─────────────────────────────────────────────────────── */}
      <div className="ml-auto flex items-center gap-1">
        {/* Filters toggle button */}
        <button
          type="button"
          aria-label="Toggle screener filters"
          aria-expanded={filtersOpen}
          onClick={onToggleFilters}
          className={cn(
            "flex h-7 items-center gap-1 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
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
