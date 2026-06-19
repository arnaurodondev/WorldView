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
  {
    // PRD-0089 Wave I-B Block IB-L1 · T-IB-04.
    // The "US Equities Only" preset is the canonical first-screen for
    // analysts working the US universe with reliable fundamentals data —
    // it strips out ADRs from foreign issuers, instruments domiciled
    // elsewhere, and synthetic instruments without earnings reports.
    // WHY countries=["USA"] not exchanges=["NYSE","NASDAQ"]: many US-listed
    // companies trade dual-class on multiple US venues; the country code
    // is the cleaner predicate. The Wave L-1 backend column reads from
    // instruments.country which is the EODHD CountryISO ("USA" for any
    // US-domiciled issuer regardless of listing exchange).
    // WHY hasFundamentals=true: pairs naturally with US Equities — the
    // most common follow-on filter (price-to-earnings, revenue) requires
    // fundamentals to be populated.
    id: "us-equities-only",
    label: "US Equities Only",
    filters: {
      ...DEFAULT_FILTERS,
      countries: ["USA"],
      hasFundamentals: true,
    },
  },
  {
    // ── "Live Catalysts" — the intelligence-moat preset (2026-06-18) ──────────
    // WHY THIS PRESET IS STRATEGIC: it composes three IB-L5 intelligence signals
    // that a Bloomberg EQS terminal structurally CANNOT express, because EQS has
    // no news-velocity, no live-alert, and no knowledge-graph-contradiction
    // fields. This single chip surfaces exactly the names that are "in play right
    // now": heavy recent coverage + an active alert + a narrative conflict.
    //   - news_count_7d ≥ 5          → active media coverage in the past week
    //   - has_active_alert = true    → the platform is already watching it (S10)
    //   - recent_contradiction_count ≥ 1 → the knowledge graph found conflicting
    //                                  narratives/claims (a volatility tell)
    // All three map to live IB-L5 server-side filters (see build-filters.ts), so
    // the preset is a pure FilterState — applying it is identical to any other
    // preset (onApply(preset.filters), no special code path).
    //
    // DATA NOTE: these columns are gated on the L-5b rollup worker; until it
    // populates the snapshot universe-wide, the preset returns few/zero rows.
    // That is the honest output — it does not erode trust because the user
    // explicitly opted into an intelligence screen (vs a default view full of "—").
    id: "live-catalysts",
    label: "Live Catalysts",
    filters: {
      ...DEFAULT_FILTERS,
      newsCount7dMin: 5,
      hasActiveAlert: true,
      contradictionsMin: 1,
    },
  },
] as const);
