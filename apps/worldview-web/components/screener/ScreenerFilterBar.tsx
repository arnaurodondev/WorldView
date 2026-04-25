/**
 * components/screener/ScreenerFilterBar.tsx — Collapsible screener filter panel
 *
 * WHY THIS EXISTS: The screener filter bar is secondary chrome — users need it
 * when setting up a new screen, but it should stay out of the way during analysis.
 * A collapsible panel (default: collapsed) maximizes visible data rows on first
 * load, consistent with Bloomberg's screener UX where filters open on demand.
 *
 * WHY grid-template-rows ANIMATION (not max-height):
 * §0.5 of the design system bans animating `height` or `max-height` directly —
 * these trigger browser layout recalculation on every animation frame (expensive).
 * `grid-template-rows: 0fr → 1fr` is the approved pattern: it collapses/expands
 * cleanly with a CSS transition, no JS animation, no reflow cost.
 *
 * WHY APPLY BUTTON (not live filter):
 * The screener POST /v1/fundamentals/screen is a database query. Firing it on
 * every keystroke would hammer S9 unnecessarily. An explicit "Apply" button
 * gives the user control and batches the request.
 *
 * WHO USES IT: app/(app)/screener/page.tsx
 * DATA SOURCE: Controlled form state passed up to parent via onApply callback
 * DESIGN REFERENCE: PRD-0031 §7 Screener filter bar, §0.5 approved animations
 */

"use client";
// WHY "use client": uses useState for controlled inputs and open/close state

import { useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * GICS sectors — 11 official sectors. Showing them as a dropdown matches
 * Bloomberg EQUITY SCREEN and Finviz sector filter conventions.
 */
const GICS_SECTORS = [
  "Information Technology",
  "Health Care",
  "Financials",
  "Consumer Discretionary",
  "Consumer Staples",
  "Communication Services",
  "Industrials",
  "Materials",
  "Real Estate",
  "Utilities",
  "Energy",
] as const;

/** CapTier — market cap filter tiers matching S9 screener backend expectations */
type CapTier = "ALL" | "LARGE" | "MID" | "SMALL";

const CAP_TIERS: Array<{ value: CapTier; label: string; description: string }> = [
  { value: "ALL",   label: "All",   description: "No market cap filter" },
  { value: "LARGE", label: "Large", description: "> $10B" },
  { value: "MID",   label: "Mid",   description: "$2B–$10B" },
  { value: "SMALL", label: "Small", description: "< $2B" },
];

// ── Types ─────────────────────────────────────────────────────────────────────

export interface FilterState {
  search: string;
  sector: string;    // "" = all sectors
  capTier: CapTier;
}

const DEFAULT_FILTERS: FilterState = { search: "", sector: "", capTier: "ALL" };

interface ScreenerFilterBarProps {
  /** Current open/collapsed state — controlled by parent to allow external toggle */
  isOpen: boolean;
  /** Toggle open/collapsed state */
  onToggle: () => void;
  /** Called when user clicks "Apply" — parent fires the API query */
  onApply: (filters: FilterState) => void;
  /** Total result count for display in the header row */
  totalResults: number;
  /** Whether the query is currently loading (isFetching) */
  isLoading: boolean;
}

// ── ScreenerFilterBar ─────────────────────────────────────────────────────────

export function ScreenerFilterBar({
  isOpen,
  onToggle,
  onApply,
  totalResults,
  isLoading,
}: ScreenerFilterBarProps) {
  // WHY local form state: filter values are pending until the user clicks Apply.
  // Storing them locally prevents partial filters from triggering API calls while
  // the user is still typing. Only onApply commits them to the parent.
  const [form, setForm] = useState<FilterState>(DEFAULT_FILTERS);

  function handleApply() {
    onApply(form);
  }

  function handleReset() {
    const reset = DEFAULT_FILTERS;
    setForm(reset);
    onApply(reset);
  }

  return (
    <div className="shrink-0">
      {/* ── Header row with result count + filter toggle ───────────────── */}
      <div className="flex h-9 items-center justify-between border-b border-border px-2">
        <div className="flex items-center gap-2">
          {/* Section label */}
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
            SCREENER
          </span>
          {/* Result count — monospace tabular-nums for consistent width */}
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {isLoading ? "…" : `${totalResults.toLocaleString()} results`}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Filter toggle button
            * WHY aria-label "Toggle screener filters": must be unique from the
            * Apply/Reset buttons which also contain "filters" in their labels.
            * Using a distinct prefix avoids ambiguity in both a11y trees and tests.
            */}
          <button
            aria-label="Toggle screener filters"
            aria-expanded={isOpen}
            aria-controls="screener-filter-panel"
            className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground font-mono uppercase tracking-[0.06em]"
            onClick={onToggle}
          >
            Filters
            <ChevronDown
              className={cn(
                "h-3 w-3 transition-transform duration-150",
                isOpen && "rotate-180",
              )}
              aria-hidden
            />
          </button>
          {/* Reset — visible only in header to allow quick reset without opening panel */}
          <button
            aria-label="Reset all filters"
            className="text-[10px] text-muted-foreground hover:text-foreground font-mono uppercase tracking-[0.06em]"
            onClick={handleReset}
          >
            Reset
          </button>
        </div>
      </div>

      {/* ── Collapsible filter form ─────────────────────────────────────── */}
      {/*
       * WHY grid overflow pattern: gridTemplateRows: "0fr"→"1fr" + overflow-hidden
       * on the outer, min-h-0 on inner. This is the §0.5 approved animation pattern.
       * The outer grid sets the visible height; the inner min-h-0 allows collapse to 0.
       */}
      <div
        id="screener-filter-panel"
        role="region"
        aria-label="Screener filters"
        className="grid overflow-hidden border-b border-border transition-[grid-template-rows] duration-200 ease-out"
        style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden min-h-0">
          <div className="flex h-9 items-center gap-2 px-2 bg-background">
            {/* Search input — free-text name/ticker search */}
            <label htmlFor="screener-search" className="sr-only">
              Search instruments by name or ticker
            </label>
            <input
              id="screener-search"
              aria-label="Search instruments by name or ticker"
              type="text"
              placeholder="Ticker / name…"
              value={form.search}
              onChange={(e) => setForm((f) => ({ ...f, search: e.target.value }))}
              // WHY h-7: filter controls are 7px shorter than the standard 8px
              // input — they live in a compact 36px header bar that needs to fit
              // multiple controls side by side without feeling cramped.
              className="h-7 w-32 px-2 text-[11px] font-mono bg-background border border-border rounded-[2px] text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary focus-visible:ring-offset-0"
              onKeyDown={(e) => e.key === "Enter" && handleApply()}
            />

            {/* Sector dropdown */}
            <label htmlFor="screener-sector" className="sr-only">
              Filter by GICS sector
            </label>
            <Select
              value={form.sector || "__all__"}
              onValueChange={(v) => setForm((f) => ({ ...f, sector: v === "__all__" ? "" : v }))}
            >
              <SelectTrigger
                id="screener-sector"
                aria-label="Filter by GICS sector"
                className="h-7 w-40 text-[11px] rounded-[2px] border-border bg-background focus:ring-1 focus:ring-primary"
              >
                <SelectValue placeholder="All sectors" />
              </SelectTrigger>
              <SelectContent className="text-[11px]">
                <SelectItem value="__all__">All sectors</SelectItem>
                {GICS_SECTORS.map((s) => (
                  <SelectItem key={s} value={s}>{s}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Market cap tier buttons */}
            <div className="flex items-center gap-1" role="group" aria-label="Market cap tier">
              {CAP_TIERS.map(({ value, label, description }) => (
                <button
                  key={value}
                  aria-label={`${label} cap: ${description}`}
                  aria-pressed={form.capTier === value}
                  className={cn(
                    "h-7 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
                    form.capTier === value
                      ? "bg-primary/10 border-primary text-primary"
                      : "bg-background border-border text-muted-foreground hover:text-foreground hover:border-border/80",
                  )}
                  onClick={() => setForm((f) => ({ ...f, capTier: value }))}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Apply button */}
            <button
              aria-label="Apply filters"
              className="h-7 px-3 text-[10px] font-mono uppercase tracking-[0.06em] bg-primary/10 border border-primary/60 text-primary rounded-[2px] hover:bg-primary/20 transition-colors ml-auto"
              onClick={handleApply}
            >
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
