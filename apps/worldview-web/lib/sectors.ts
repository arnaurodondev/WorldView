/**
 * lib/sectors.ts — Shared GICS sector pill labels and helpers
 *
 * WHY THIS EXISTS: Multiple widgets (PreMarketMoversWidget Wave F, the future
 * WatchlistMoversWidget Wave E, and the SectorHeatmapWidget) need a consistent
 * list of sector filter pills with stable display labels. Centralising the list
 * in one module guarantees the same abbreviations, ordering, and `value` strings
 * across all widgets so a user's mental model of "Tech" or "Cons. Disc" is
 * consistent everywhere.
 *
 * WHY a `value` separate from `label`:
 * - `value` is the canonical GICS sector name as returned by S9
 *   (e.g. `"Information Technology"`, `"Consumer Discretionary"`). Filter logic
 *   compares against `companyOverview.instrument.gics_sector` which uses these
 *   long-form names.
 * - `label` is the compressed pill text optimised for narrow horizontal space
 *   (`"Tech"`, `"Cons. Disc"`). Pills live in scrollable rows so we keep them
 *   short to fit ~6 pills before the user has to scroll.
 *
 * WHY a special `"all"` value: a sentinel that bypasses the filter. Using a
 * string sentinel (not `null`) keeps the prop type a simple `string` and avoids
 * `null`-handling branches in every consumer.
 *
 * DESIGN REFERENCE: PLAN-0048 Wave F task description.
 */

// ── Shared types ──────────────────────────────────────────────────────────────

/**
 * SectorPill — one entry in the horizontally-scrolling filter row.
 *
 * Note we expose this as a named type rather than inferring from the array so
 * downstream widget props can declare `selected: SectorPill["value"]` for
 * type-safety without re-deriving the union.
 */
export interface SectorPill {
  /** Canonical GICS sector value used to match `gics_sector` strings. The literal
   * `"all"` is the sentinel meaning "no filter". */
  value: string;
  /** Compressed pill label optimised for narrow widths. */
  label: string;
}

// ── Pill list ─────────────────────────────────────────────────────────────────

/**
 * SECTOR_PILLS — ordered pill list for the sector filter row.
 *
 * Order rationale: `All` first (default state), then the 11 GICS sectors in
 * the same order S&P Global publishes them. This matches the order that
 * traders are used to seeing in Bloomberg / FactSet sector menus, so the
 * pill row reads as a familiar reference rather than a random sort.
 *
 * WHY readonly `as const`: prevents accidental mutation at runtime and lets
 * TypeScript narrow the literal types of `value` for callers that want
 * exhaustive switch handling later.
 */
export const SECTOR_PILLS: readonly SectorPill[] = [
  { value: "all", label: "All" },
  // GICS canonical name = "Information Technology" — most users say "Tech".
  { value: "Information Technology", label: "Tech" },
  // GICS = "Health Care" (with a space) — pill abbreviates to "Health".
  { value: "Health Care", label: "Health" },
  { value: "Financials", label: "Financials" },
  { value: "Energy", label: "Energy" },
  // Two consumer sectors share "Cons." prefix — disambiguate with Disc / Stap
  // so the pills are scannable side-by-side.
  { value: "Consumer Discretionary", label: "Cons. Disc" },
  { value: "Consumer Staples", label: "Cons. Stap" },
  { value: "Industrials", label: "Industrials" },
  { value: "Materials", label: "Materials" },
  { value: "Utilities", label: "Utilities" },
  { value: "Real Estate", label: "Real Estate" },
  // GICS = "Communication Services" — abbreviated to "Comm Svcs" to fit pill width.
  { value: "Communication Services", label: "Comm Svcs" },
] as const;

/**
 * ALL_SECTORS_VALUE — sentinel pill value meaning "no sector filter".
 *
 * Exported as a named constant so consumers don't sprinkle string literals
 * around their code; switching the sentinel later requires editing only
 * this file.
 */
export const ALL_SECTORS_VALUE = "all" as const;

/**
 * matchesSectorFilter — predicate: does an instrument's gics_sector match the
 * currently-selected pill?
 *
 * WHY a helper instead of inline comparison: filtering logic is repeated in
 * F-1 (treemap popover) and F-2 (movers pill row). Centralising it here
 * keeps the "all = bypass" rule and `gics_sector` null-handling consistent.
 *
 * Returns `true` when:
 * - the user selected "all" (no filter), OR
 * - the instrument's `gics_sector` exactly equals the selected sector value.
 *
 * Returns `false` when the instrument has no `gics_sector` (null/undefined)
 * and the user has selected a specific sector — we cannot confirm a match,
 * so it must be excluded.
 */
export function matchesSectorFilter(
  instrumentSector: string | null | undefined,
  selectedSector: string,
): boolean {
  if (selectedSector === ALL_SECTORS_VALUE) return true;
  if (!instrumentSector) return false;
  return instrumentSector === selectedSector;
}
