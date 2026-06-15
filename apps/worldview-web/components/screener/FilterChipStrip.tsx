/**
 * components/screener/FilterChipStrip.tsx — Row of active filter chips + Add filter combobox
 * (PRD-0089 Wave I — FilterChipStrip)
 *
 * WHY THIS EXISTS: Replaces the always-open ScreenerFilterBar header row with a chip strip
 * that is zero-cost when no filters are set (just the "+ Add filter" button), and shows one
 * chip per active filter when filters are set. Inspired by Stockanalysis.com's filter chip
 * pattern (docs/designs/0089/08-screener.md §1, §4, §5).
 *
 * VISUAL CONTRACT:
 *   Each chip shows: `<field> <operator> <value> ×`
 *   e.g. "P/E < 15 ×", "DIV Y% > 2.0 ×", "ROE% > 15.0 ×"
 *   Clicking × removes that filter from state.
 *   Rightmost control: "+ Add filter" — opens a Popover+Command (shadcn/ui) for field
 *   selection, then operator, then value entry.
 *
 * FILTER STATE INTEGRATION:
 *   FilterChipStrip reads `appliedFilters` and calls `onApply` with the modified state
 *   (same signature as ScreenerFilterBar.onApply) so the screener page re-fetches on change.
 *   A 250 ms debounce prevents double-fires when multiple chips are removed quickly.
 *
 * WHO USES IT: app/(app)/screener/page.tsx (Row 3)
 * DESIGN REF: docs/designs/0089/08-screener.md §4 (Row 3), §5 (FilterChipStrip), §6.4
 */

"use client";
// WHY "use client": chip click handlers and the Popover/Command combobox need browser events.

import { useCallback, useEffect, useRef, useState } from "react";
import { X, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { type FilterState } from "@/features/screener/lib/filter-state";

// ── Filter field descriptors ───────────────────────────────────────────────────

/**
 * FILTER_FIELDS — the set of fields the "+ Add filter" combobox presents.
 * Each entry maps to one or two FilterState keys (min/max pair).
 *
 * WHY only 8 fields here (not all ~20): the combobox shows the most-used
 * analyst fields. Bulk advanced filters still live in ScreenerFilterBar
 * (accessible via the Filters toggle). The chip strip is the "quick access"
 * layer; the panel is the "power user" layer.
 */
const FILTER_FIELDS = [
  {
    id: "marketCap",
    label: "Market Cap",
    unit: "B USD",
    minKey: "marketCapMin" as const,
    maxKey: "marketCapMax" as const,
    toDisplay: (v: number) => `$${v}B`,
    // market cap stored as raw USD — user types in billions, we multiply
    toStore: (v: number) => v * 1_000_000_000,
    toForm: (v: number) => v / 1_000_000_000,
  },
  {
    id: "pe",
    label: "P/E",
    unit: "ratio",
    minKey: "peMin" as const,
    maxKey: "peMax" as const,
    toDisplay: (v: number) => `${v}`,
    toStore: (v: number) => v,
    toForm: (v: number) => v,
  },
  {
    id: "pb",
    label: "P/B",
    unit: "ratio",
    minKey: "pbMin" as const,
    maxKey: "pbMax" as const,
    toDisplay: (v: number) => `${v}`,
    toStore: (v: number) => v,
    toForm: (v: number) => v,
  },
  {
    id: "divYield",
    label: "DIV Y%",
    unit: "% yield",
    minKey: "divYieldMin" as const,
    maxKey: "divYieldMax" as const,
    // div yield stored as decimal (0.015 = 1.5%); user types "1.5"
    toDisplay: (v: number) => `${(v * 100).toFixed(1)}%`,
    toStore: (v: number) => v / 100,
    toForm: (v: number) => v * 100,
  },
  {
    id: "forwardPe",
    label: "FWD P/E",
    unit: "ratio",
    minKey: "forwardPeMin" as const,
    maxKey: "forwardPeMax" as const,
    toDisplay: (v: number) => `${v}`,
    toStore: (v: number) => v,
    toForm: (v: number) => v,
  },
  {
    id: "roe",
    label: "ROE%",
    unit: "% return",
    minKey: "roeMin" as const,
    maxKey: "roeMax" as const,
    // roe stored as decimal (0.15 = 15%); user types "15"
    toDisplay: (v: number) => `${(v * 100).toFixed(1)}%`,
    toStore: (v: number) => v / 100,
    toForm: (v: number) => v * 100,
  },
  {
    id: "revGrowth",
    label: "REV YoY%",
    unit: "% growth",
    minKey: "revGrowthMin" as const,
    maxKey: "revGrowthMax" as const,
    // rev growth stored as decimal (0.1 = 10%); user types "10"
    toDisplay: (v: number) => `${(v * 100).toFixed(1)}%`,
    toStore: (v: number) => v / 100,
    toForm: (v: number) => v * 100,
  },
  {
    id: "opMargin",
    label: "OP MGN%",
    unit: "% margin",
    minKey: "opMarginMin" as const,
    maxKey: "opMarginMax" as const,
    // op margin stored as decimal; user types "20"
    toDisplay: (v: number) => `${(v * 100).toFixed(1)}%`,
    toStore: (v: number) => v / 100,
    toForm: (v: number) => v * 100,
  },
  {
    // Round 2 — absolute 30d-avg-volume (SERVER_SIDE). Registering the field
    // here is what makes slider-set volume filters appear as dismissible
    // chips: deriveChips() walks FILTER_FIELDS, so any FilterState key pair
    // listed here gets chips for free (this is also true for the slider-set
    // marketCap/pe/divYield/roe values — those fields were already listed).
    id: "avgVol",
    label: "AVG VOL",
    unit: "M shares",
    minKey: "avgVolume30dMin" as const,
    maxKey: "avgVolume30dMax" as const,
    // Stored as raw shares; the chip shows compact notation ("1.5M") and the
    // "+ Add filter" input accepts millions (typing "1.5" = 1.5M shares) to
    // match the unit hint above.
    toDisplay: (v: number) =>
      v >= 1_000_000_000
        ? `${(v / 1_000_000_000).toFixed(1).replace(/\.0$/, "")}B`
        : v >= 1_000_000
          ? `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`
          : `${(v / 1_000).toFixed(0)}K`,
    toStore: (v: number) => v * 1_000_000,
    toForm: (v: number) => v / 1_000_000,
  },
] as const;

// Key union for type safety when reading/writing FilterState
type FilterFieldId = typeof FILTER_FIELDS[number]["id"];

// ── Chip-only descriptors (BUGFIX 2026-06-15 — usability) ────────────────────
//
// WHY A SEPARATE LIST (not added to FILTER_FIELDS): before this, deriveChips
// walked ONLY the 10 FILTER_FIELDS entries — so a filter set via the
// ScreenerFilterBar panel for ANY Performance (returns / 52W distance) or
// Ownership (analyst / insider / institutional / short) field produced NO chip
// in the always-visible strip. The user got a section count badge but no
// dismissible "what's active" indication, and the chip strip's contextual
// Reset button (gated on chips.length > 0) never appeared when only those
// filters were set. That made the most powerful filters the LEAST visible.
//
// These descriptors are consumed by deriveChips ONLY — they are deliberately
// NOT added to FILTER_FIELDS so the "+ Add filter" quick-add combobox stays a
// short, curated menu (the panel remains the power-user entry point). Each
// chip is still individually dismissible because the min/max keys are real
// FilterState keys handled by the same generic remove() closure below.
//
// Unit conventions mirror the panel inputs (decimals for fractions, raw USD
// for prices) so chip labels read the same as the values the user typed.
const CHIP_ONLY_FIELDS = [
  // ── Performance (decimals: 0.124 = +12.4%) ──────────────────────────────
  { label: "52W↓HIGH", minKey: "dist52wHighPctMin", maxKey: "dist52wHighPctMax", pct: true },
  { label: "52W↑LOW", minKey: "dist52wLowPctMin", maxKey: "dist52wLowPctMax", pct: true },
  { label: "1M RTN", minKey: "return1mMin", maxKey: "return1mMax", pct: true },
  { label: "3M RTN", minKey: "return3mMin", maxKey: "return3mMax", pct: true },
  { label: "6M RTN", minKey: "return6mMin", maxKey: "return6mMax", pct: true },
  { label: "YTD RTN", minKey: "returnYtdMin", maxKey: "returnYtdMax", pct: true },
  { label: "1Y RTN", minKey: "return1yMin", maxKey: "return1yMax", pct: true },
  { label: "3Y RTN", minKey: "return3yMin", maxKey: "return3yMax", pct: true },
  // ── Ownership (the section whose filters were silently broken until the
  //    build-filters.ts named-field fix; chips make the fix observable) ─────
  { label: "ANALYST TGT", minKey: "analystTargetPriceMin", maxKey: "analystTargetPriceMax", usd: true },
  { label: "CONSENSUS", minKey: "analystConsensusMin", maxKey: "analystConsensusMax" },
  { label: "INSIDER 90D", minKey: "insiderNetBuy90dMin", maxKey: "insiderNetBuy90dMax", usd: true },
  { label: "INST OWN%", minKey: "instOwnPctMin", maxKey: "instOwnPctMax", pct: true },
  { label: "SHORT%", minKey: "shortPctMin", maxKey: "shortPctMax", pct: true },
] as const;

/** Format a chip value per its descriptor's unit hint. */
function formatChipValue(
  v: number,
  opts: { pct?: boolean; usd?: boolean },
): string {
  if (opts.pct) return `${(v * 100).toFixed(1)}%`;
  if (opts.usd) {
    // Compact USD so a $5,000,000 insider flow reads "$5.0M", not a wall of digits.
    const abs = Math.abs(v);
    if (abs >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
    if (abs >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
    return `$${v}`;
  }
  return `${v}`;
}

// ── Chip derivation ─────────────────────────────────────────────────────────

/**
 * ActiveChip — a single derived chip from the current FilterState.
 * We materialise chips so the render loop is simple (map over chips).
 */
interface ActiveChip {
  /** Stable key for React reconciliation */
  key: string;
  /** Display text, e.g. "P/E < 15" */
  label: string;
  /** Remove this chip — returns the updated FilterState to apply */
  remove: (prev: FilterState) => FilterState;
}

/**
 * deriveChips — converts a FilterState into a flat list of chips to render.
 * Each numeric range that is set produces up to 2 chips (min, max).
 *
 * WHY two separate chips per range (not one "P/E 10–20"):
 * Removing one side of a range (e.g. the max) is the most common operation.
 * Two separate chips with individual × buttons matches Stockanalysis.com's
 * UX and avoids an awkward "which side are you removing?" interaction.
 */
function deriveChips(filters: FilterState): ActiveChip[] {
  const chips: ActiveChip[] = [];

  for (const field of FILTER_FIELDS) {
    // Check if both keys exist on FilterState — they are optional, so we must
    // handle undefined gracefully.
    // WHY double-cast through unknown: FilterState doesn't have an index
    // signature (it's a named-field interface). We know the keys exist as
    // optional fields, so the cast is safe — we check undefined after.
    const minVal = (filters as unknown as Record<string, unknown>)[field.minKey] as number | undefined;
    const maxVal = (filters as unknown as Record<string, unknown>)[field.maxKey] as number | undefined;

    if (minVal !== undefined && minVal !== null) {
      chips.push({
        key: `${field.id}-min`,
        label: `${field.label} > ${field.toDisplay(minVal)}`,
        remove: (prev) => {
          const next = { ...prev };
          delete (next as Record<string, unknown>)[field.minKey];
          return next;
        },
      });
    }

    if (maxVal !== undefined && maxVal !== null) {
      chips.push({
        key: `${field.id}-max`,
        label: `${field.label} < ${field.toDisplay(maxVal)}`,
        remove: (prev) => {
          const next = { ...prev };
          delete (next as Record<string, unknown>)[field.maxKey];
          return next;
        },
      });
    }
  }

  // ── Chip-only fields (Performance + Ownership) ─────────────────────────────
  // Same min/max → two-chip pattern as above, but driven by CHIP_ONLY_FIELDS so
  // panel-set Performance/Ownership filters become visible + dismissible without
  // adding them to the "+ Add filter" combobox. Each remove() deletes the real
  // FilterState key, so dismissing a chip re-fires the query through onApply.
  for (const field of CHIP_ONLY_FIELDS) {
    const minVal = (filters as unknown as Record<string, unknown>)[field.minKey] as number | undefined;
    const maxVal = (filters as unknown as Record<string, unknown>)[field.maxKey] as number | undefined;

    if (minVal !== undefined && minVal !== null) {
      chips.push({
        key: `${field.minKey}`,
        label: `${field.label} > ${formatChipValue(minVal, { pct: "pct" in field, usd: "usd" in field })}`,
        remove: (prev) => {
          const next = { ...prev };
          delete (next as Record<string, unknown>)[field.minKey];
          return next;
        },
      });
    }

    if (maxVal !== undefined && maxVal !== null) {
      chips.push({
        key: `${field.maxKey}`,
        label: `${field.label} < ${formatChipValue(maxVal, { pct: "pct" in field, usd: "usd" in field })}`,
        remove: (prev) => {
          const next = { ...prev };
          delete (next as Record<string, unknown>)[field.maxKey];
          return next;
        },
      });
    }
  }

  return chips;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface FilterChipStripProps {
  /** Currently applied (committed) filter state from the screener page. */
  appliedFilters: FilterState;
  /**
   * Called with the updated filter state after a chip removal or new filter.
   * Fires debounced 250 ms after the last change so rapid chip removals batch
   * into one API call (Bloomberg live-count debounce pattern, §7.5).
   */
  onApply: (filters: FilterState) => void;
  /** Optional — opens the SavedScreensDialog so user can persist current filters. */
  onSave?: () => void;
  /** Optional — resets all filters to DEFAULT_FILTERS. */
  onReset?: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FilterChipStrip({
  appliedFilters,
  onApply,
  onSave,
  onReset,
}: FilterChipStripProps) {
  // ── Add-filter popover state ──────────────────────────────────────────────
  const [addOpen, setAddOpen] = useState(false);
  // Step 1: user picks a field; step 2: user sets operator + value.
  const [selectedField, setSelectedField] = useState<FilterFieldId | null>(null);
  const [operator, setOperator] = useState<"gt" | "lt">("lt");
  const [valueInput, setValueInput] = useState("");

  // ── Debounced apply ───────────────────────────────────────────────────────
  // WHY debounce 250ms: Bloomberg EQS pattern — fire the API request 250ms
  // after the last user action to batch rapid chip removals (design §7.5).
  const pendingRef = useRef<FilterState | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleApply = useCallback(
    (next: FilterState) => {
      // Store most-recent state so the timer always fires the latest version
      pendingRef.current = next;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        if (pendingRef.current) {
          onApply(pendingRef.current);
          pendingRef.current = null;
        }
      }, 250);
    },
    [onApply],
  );

  // Flush pending on unmount so we don't leak the timer.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // ── Derive chips from current applied filters ─────────────────────────────
  const chips = deriveChips(appliedFilters);

  // ── Handlers ──────────────────────────────────────────────────────────────

  function handleRemoveChip(chip: ActiveChip) {
    const updated = chip.remove(appliedFilters);
    // Debounce: rapid double-click on × doesn't double-fire
    scheduleApply(updated);
  }

  function handleFieldSelect(fieldId: FilterFieldId) {
    setSelectedField(fieldId);
    setOperator("lt");
    setValueInput("");
  }

  function handleAddFilterConfirm() {
    if (!selectedField || !valueInput) return;
    const fieldDef = FILTER_FIELDS.find((f) => f.id === selectedField);
    if (!fieldDef) return;

    const numericValue = parseFloat(valueInput);
    if (isNaN(numericValue)) return;

    const stored = fieldDef.toStore(numericValue);
    const key = operator === "gt" ? fieldDef.minKey : fieldDef.maxKey;

    const updated: FilterState = {
      ...appliedFilters,
      [key]: stored,
    };

    scheduleApply(updated);

    // Reset the add-filter wizard state
    setSelectedField(null);
    setValueInput("");
    setAddOpen(false);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    // WHY min-h-[28px]: the strip has a fixed 28px baseline per design §4.2
    // (Row 3). When there are no chips, the row still occupies its reserved
    // space so the table doesn't jump up when filters are cleared.
    <div
      className="flex flex-wrap items-center gap-1.5 px-3 py-1 min-h-[28px] shrink-0 bg-card border-b border-border"
      aria-label="Active filters"
    >
      {/* ── Active filter chips ────────────────────────────────────────── */}
      {chips.map((chip) => (
        <span
          key={chip.key}
          className={cn(
            // Design §6.4: active chip is bg-primary/10 border-primary/60 text-primary
            "inline-flex items-center gap-1 h-[20px] px-2 text-[10px] font-mono",
            "rounded-[2px] border bg-primary/10 border-primary/60 text-primary",
            "whitespace-nowrap shrink-0",
          )}
        >
          {chip.label}
          <button
            type="button"
            aria-label={`Remove filter: ${chip.label}`}
            onClick={() => handleRemoveChip(chip)}
            // ROUND-3 item 6: rounded-[1px] + focus-visible ring so keyboard
            // users can SEE which chip's × currently has focus before Enter.
            className="rounded-[1px] text-muted-foreground hover:text-foreground transition-colors ml-0.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {/* WHY inline SVG (not lucide X): avoids a 16px icon in a 10px label.
                Hand-sized 8px cross is proportional to the chip height. */}
            <X className="h-2.5 w-2.5" strokeWidth={2} />
          </button>
        </span>
      ))}

      {/* ── Add filter combobox ────────────────────────────────────────── */}
      <Popover open={addOpen} onOpenChange={setAddOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label="Add a filter"
            className={cn(
              "inline-flex items-center gap-1 h-[20px] px-2 text-[10px] font-mono",
              "rounded-[2px] border border-dashed border-border/60 text-muted-foreground",
              "hover:text-foreground hover:border-border transition-colors shrink-0",
              // ROUND-3 item 6: shared focus-visible ring.
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            )}
          >
            <Plus className="h-2.5 w-2.5" strokeWidth={2} />
            Add filter
          </button>
        </PopoverTrigger>

        <PopoverContent
          className="w-64 p-0 bg-card border-border"
          align="start"
          side="bottom"
        >
          {/* WHY two-step wizard (field → value) inside one popover:
              Collapsing into one panel matches Stockanalysis.com's combobox UX.
              Step 1: pick the field. Step 2: set operator + numeric value.
              The popover stays open between steps so focus doesn't leave. */}
          {selectedField === null ? (
            // Step 1: field picker
            <Command>
              <CommandInput
                placeholder="Search fields…"
                className="text-[10px] font-mono h-7"
              />
              <CommandList>
                <CommandEmpty className="py-2 text-center text-[10px] font-mono text-muted-foreground">
                  No fields found
                </CommandEmpty>
                <CommandGroup heading="Metric fields">
                  {FILTER_FIELDS.map((field) => (
                    <CommandItem
                      key={field.id}
                      value={field.label}
                      onSelect={() => handleFieldSelect(field.id)}
                      className="text-[10px] font-mono cursor-pointer"
                    >
                      {field.label}
                      <span className="ml-auto text-[9px] text-muted-foreground">
                        {field.unit}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          ) : (
            // Step 2: operator + value entry
            <div className="p-3 flex flex-col gap-2">
              {/* Field label + back */}
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-primary uppercase tracking-[0.06em]">
                  {FILTER_FIELDS.find((f) => f.id === selectedField)?.label}
                </span>
                <button
                  type="button"
                  onClick={() => setSelectedField(null)}
                  className="rounded-[1px] text-[9px] font-mono text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  ← back
                </button>
              </div>

              {/* Operator toggle: > or < */}
              <div className="flex gap-1">
                {(["gt", "lt"] as const).map((op) => (
                  <button
                    key={op}
                    type="button"
                    onClick={() => setOperator(op)}
                    className={cn(
                      "h-6 flex-1 text-[10px] font-mono rounded-[2px] border transition-colors",
                      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                      operator === op
                        ? "bg-primary/10 border-primary text-primary"
                        : "border-border text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {op === "gt" ? ">" : "<"}
                  </button>
                ))}
              </div>

              {/* Value input */}
              <input
                type="number"
                value={valueInput}
                onChange={(e) => setValueInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddFilterConfirm();
                }}
                placeholder="Value"
                className={cn(
                  "h-6 w-full px-2 text-[10px] font-mono tabular-nums",
                  "bg-background border border-border rounded-[2px]",
                  "text-foreground placeholder:text-muted-foreground",
                  "focus:outline-none focus:border-primary/60",
                )}
                // WHY step=any: prevents the browser from rounding to integers on
                // inputs like "1.5" for dividend yield percentage inputs.
                step="any"
                autoFocus
              />

              {/* Confirm */}
              <button
                type="button"
                onClick={handleAddFilterConfirm}
                disabled={!valueInput || isNaN(parseFloat(valueInput))}
                className={cn(
                  "h-6 w-full text-[10px] font-mono uppercase tracking-[0.06em]",
                  "rounded-[2px] border border-primary/60 bg-primary/10 text-primary",
                  "hover:bg-primary/20 transition-colors",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                )}
              >
                Apply
              </button>
            </div>
          )}
        </PopoverContent>
      </Popover>

      {/* ── Right actions: Save + Reset ───────────────────────────────── */}
      {(onSave ?? onReset) && (
        <div className="ml-auto flex items-center gap-1">
          {onSave && (
            <button
              type="button"
              onClick={onSave}
              className="h-[20px] px-2 text-[10px] font-mono rounded-[2px] border border-border text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              Save…
            </button>
          )}
          {onReset && chips.length > 0 && (
            <button
              type="button"
              onClick={onReset}
              className="h-[20px] px-2 text-[10px] font-mono rounded-[2px] border border-border text-muted-foreground hover:text-negative hover:border-negative/40 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              Reset
            </button>
          )}
        </div>
      )}
    </div>
  );
}
