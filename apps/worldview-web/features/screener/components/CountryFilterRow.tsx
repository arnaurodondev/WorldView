"use client";

/**
 * features/screener/components/CountryFilterRow.tsx — Country filter row
 * (PRD-0089 Wave I-B Block IB-L1, T-IB-01).
 *
 * WHY THIS EXISTS: The Wave L-1 backend (commit 3541ad86) added a
 * `country` predicate to `screen_field_metadata` / `ScreenFilter`. This row
 * is the UI surface — multi-select combobox over ISO 3-letter codes plus
 * four regional shortcut chips (NA / EU / APAC / EM per OQ-9) that expand
 * into the full ISO3 set with one click.
 *
 * WHY a dedicated component (not inline in ScreenerFilterBar): the bar is
 * already 766 LOC. Extracting Country / Exchange / Coverage rows keeps
 * the popover JSX scannable, lets Vitest exercise each row in isolation,
 * and matches the extraction pattern Wave I-A used for IntelligenceFilterGroup.
 *
 * WHY a "Categorical" sub-section (not just another collapsible Section):
 * the design doc (docs/designs/0089/08-screener.md §Coverage) groups
 * country + exchange + coverage as a single row of inputs labelled
 * "Categorical". A full collapsible section would over-chrome three short
 * rows. Caller renders this inline inside a single `<div>` with a 10px
 * label, matching the existing top-row (Search / Sector / Cap) treatment.
 *
 * NO BackendPendingBadge — Wave L-1 shipped the backend on 2026-05-25,
 * so this row is live. The instruction set explicitly says to omit the
 * badge on the four IB-L1 rows.
 *
 * REGIONAL PRESET CHIP behaviour: clicking a chip REPLACES the current
 * selection with the chip's ISO3 set (not additive). This matches the
 * "single decisive click" finance-terminal pattern; additive behaviour
 * confuses users when the selection already contains overlapping codes
 * (e.g. EM + APAC both include CHN / IND).
 */

import { MultiCombobox, type MultiComboboxItem } from "@/components/ui/multi-combobox";
import { cn } from "@/lib/utils";
import {
  COUNTRY_REGIONS,
  COMMON_COUNTRY_ISO3,
} from "@/lib/screener/country-regions";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface CountryFilterRowProps {
  /** Current selection — ISO3 codes. Empty array = no filter. */
  value: readonly string[];
  /** Called with the new selection (ISO3 codes). */
  onChange: (countries: string[]) => void;
}

// ── Static option list ────────────────────────────────────────────────────────

/**
 * MultiCombobox expects `{id, label}` items. We pre-compute once because
 * the static list never changes during a session and React.useMemo would
 * just trade a closure allocation for a Map allocation.
 */
const COUNTRY_OPTIONS: MultiComboboxItem[] = COMMON_COUNTRY_ISO3.map((iso) => ({
  id: iso,
  label: iso,
}));

// ── Component ─────────────────────────────────────────────────────────────────

export function CountryFilterRow({ value, onChange }: CountryFilterRowProps) {
  // WHY equality-by-set: chip "pressed" state shows true when the CURRENT
  // selection EXACTLY equals the chip's ISO3 list (order-independent).
  // This is the only honest definition — partial overlap would either
  // light up the chip when it shouldn't (misleading) or never (useless).
  function isRegionActive(regionIso3: readonly string[]): boolean {
    if (value.length !== regionIso3.length) return false;
    const a = new Set(value);
    for (const code of regionIso3) {
      if (!a.has(code)) return false;
    }
    return true;
  }

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <label className="text-[10px] font-mono uppercase tracking-[0.06em] text-muted-foreground w-20 shrink-0">
        Country
      </label>

      {/* ── Regional preset chips (NA / EU / APAC / EM) ─────────────── */}
      <div
        className="flex items-center gap-1"
        role="group"
        aria-label="Country region presets"
      >
        {COUNTRY_REGIONS.map((region) => {
          const active = isRegionActive(region.iso3);
          return (
            <button
              key={region.id}
              type="button"
              aria-label={`Select ${region.label} region (${region.iso3.length} countries)`}
              aria-pressed={active}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
                active
                  ? "bg-primary/10 border-primary text-primary"
                  : "bg-background border-border text-muted-foreground hover:text-foreground hover:border-border/80",
              )}
              onClick={() => onChange([...region.iso3])}
            >
              {region.label}
            </button>
          );
        })}
      </div>

      {/* ── Multi-select combobox over ISO3 ─────────────────────────── */}
      <MultiCombobox
        items={COUNTRY_OPTIONS}
        selectedIds={[...value]}
        onChange={onChange}
        placeholder="All countries"
        emptyMessage="No matching ISO codes."
        className="h-7 w-44"
      />
    </div>
  );
}
