/**
 * lib/screener/presets.ts — System screener presets (PLAN-0092 Wave D)
 *
 * WHY THIS EXISTS: Analysts frequently run the same screens (value, dividend,
 * profitable tech). Baking 6 common presets into a chip strip lets users jump
 * directly to a useful starting point without configuring filters manually.
 * This is the standard pattern on Finviz (predefined filters) and Bloomberg
 * (EQUITY SCREEN templates).
 *
 * WHY FilterState (not a separate Preset type): presets ARE filter states.
 * Applying a preset is identical to applying any user-built filter — it calls
 * onApply(preset.filters). No special code path, no extra state.
 *
 * PRESET SELECTION CRITERIA:
 *   The 6 presets cover the most common institutional screening strategies:
 *   1. All — clear all filters (default market universe)
 *   2. Large Cap — mega/large cap companies (>$10B mkt cap)
 *   3. Dividend — income investing screen (yield > 2%)
 *   4. Value — classic deep-value (P/E < 15, P/B < 2)
 *   5. Growth — high-growth screen (rev growth > 15% YoY)
 *   6. Profitable — quality filter (net margin > 10%, ROE > 10%)
 */

import { DEFAULT_FILTERS, type FilterState } from "@/features/screener/lib/filter-state";

export interface ScreenerPreset {
  /** Stable identifier — used as React key. */
  id: string;
  /** Display label shown in the PresetBar chip. */
  label: string;
  /** Full filter state to apply when the chip is clicked. */
  filters: FilterState;
}

export const SCREENER_PRESETS: readonly ScreenerPreset[] = Object.freeze([
  {
    id: "all",
    label: "All",
    filters: { ...DEFAULT_FILTERS },
  },
  {
    id: "large-cap",
    label: "Large Cap",
    filters: {
      ...DEFAULT_FILTERS,
      capTier: "LARGE",
    },
  },
  {
    id: "dividend",
    label: "Dividend",
    filters: {
      ...DEFAULT_FILTERS,
      // Annual dividend yield > 2% (stored as decimal: 0.02)
      divYieldMin: 0.02,
    },
  },
  {
    id: "value",
    label: "Value",
    filters: {
      ...DEFAULT_FILTERS,
      // Classic deep-value: P/E < 15 and P/B < 2
      peMax: 15,
      pbMax: 2,
    },
  },
  {
    id: "growth",
    label: "Growth",
    filters: {
      ...DEFAULT_FILTERS,
      // Revenue growth > 15% YoY (stored as decimal: 0.15)
      revGrowthMin: 0.15,
    },
  },
  {
    id: "profitable",
    label: "Profitable",
    filters: {
      ...DEFAULT_FILTERS,
      // Quality: net margin > 10% AND ROE > 10% (both decimal)
      netMarginMin: 0.10,
      roeMin: 0.10,
    },
  },
] as const);
