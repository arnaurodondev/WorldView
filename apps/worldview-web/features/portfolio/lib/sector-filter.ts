/**
 * features/portfolio/lib/sector-filter.ts — PURE sector-filter matching.
 *
 * WHY THIS EXISTS (R2 enhancement sprint): the new allocation donut filters
 * the holdings table by sector. The donut's sectors come from the S9
 * sector-breakdown endpoint (reads `instruments.sector`), while each
 * holding's sector in the table comes from the holding-overview map
 * (instrument fundamentals). Both ultimately derive from the same EODHD
 * sector field, but the two paths can disagree on CASE and on the
 * "no sector" representation (null vs "Unknown"). Centralizing the match
 * rule in one pure function — instead of an inline `===` in HoldingsTab —
 * makes the contract explicit and unit-testable.
 *
 * MATCH RULES:
 *   1. Case-insensitive, whitespace-trimmed comparison (defends against
 *      "Health Care" vs "health care" drift between the two data paths).
 *   2. EODHD↔GICS taxonomy aliasing (see SECTOR_ALIASES). VERIFIED LIVE on
 *      the dev stack (2026-06-10): sector-breakdown returns EODHD names
 *      ("Technology", "Consumer Cyclical", "Financial Services") while the
 *      overview batch returns GICS names ("Information Technology",
 *      "Consumer Discretionary"). Without aliasing, clicking the
 *      "Technology" slice would match ZERO holdings — a silently broken
 *      filter. Both names canonicalize to one token before comparison.
 *   3. A holding with NO sector (null/undefined/empty) matches ONLY the
 *      "Unknown" bucket — the same label the S9 sector-breakdown endpoint
 *      emits for holdings it couldn't classify. This keeps "click the
 *      Unknown slice" working: it shows exactly the unclassified rows.
 *
 * BACKEND GAP (flagged in the R2 report): the exact fix is for
 * /sector-breakdown segments to include their instrument_ids so the
 * frontend can join by ID instead of by name. Until then this alias table
 * is the honest best-effort, and unmapped names fall back to rule 1.
 *
 * WHO USES IT: HoldingsTab (table filtering), SectorAllocationDonut tests.
 */

import type { Holding } from "@/types/api";

/**
 * SECTOR_ALIASES — EODHD sector names → canonical GICS sector (lowercase).
 *
 * Source taxonomies:
 *   EODHD `General.Sector` (what `instruments.sector` stores, hence what
 *   /sector-breakdown emits): Technology, Consumer Cyclical, Consumer
 *   Defensive, Financial Services, Healthcare, Basic Materials, ...
 *   GICS (what company-overview `gics_sector` emits): Information
 *   Technology, Consumer Discretionary, Consumer Staples, Financials,
 *   Health Care, Materials, ...
 * Identical-in-both names (Energy, Industrials, Utilities, Real Estate,
 * Communication Services) need no entry — rule-1 equality covers them.
 */
const SECTOR_ALIASES: Record<string, string> = {
  // EODHD name (lowercased) → canonical GICS name (lowercased)
  "technology": "information technology",
  "consumer cyclical": "consumer discretionary",
  "consumer defensive": "consumer staples",
  "financial services": "financials",
  "financial": "financials", // older EODHD payloads use the singular form
  "healthcare": "health care",
  "basic materials": "materials",
};

/**
 * UNKNOWN_SECTOR — canonical label for unclassified holdings.
 * MUST stay in sync with the S9 sector-breakdown endpoint, which buckets
 * holdings without an `instruments.sector` value under "Unknown".
 */
export const UNKNOWN_SECTOR = "Unknown";

/**
 * Normalize a sector label for comparison: trim + lowercase + resolve
 * EODHD aliases to the canonical GICS name (match rule 2).
 */
function norm(s: string): string {
  const lowered = s.trim().toLowerCase();
  return SECTOR_ALIASES[lowered] ?? lowered;
}

/**
 * holdingMatchesSector — does a holding's sector match the active filter?
 *
 * @param holdingSector  the holding's sector from the overview map
 *                       (null/undefined/"" = unclassified)
 * @param filter         the active sector filter (a donut segment label)
 */
export function holdingMatchesSector(
  holdingSector: string | null | undefined,
  filter: string,
): boolean {
  // Unclassified holdings live in the "Unknown" bucket (rule 2 above).
  if (holdingSector == null || holdingSector.trim() === "") {
    return norm(filter) === norm(UNKNOWN_SECTOR);
  }
  return norm(holdingSector) === norm(filter);
}

/**
 * filterHoldingsBySector — filter a holdings array by the active sector.
 *
 * @param holdings  enriched holdings from usePortfolioData
 * @param sectors   instrument_id → sector map (from holdingOverviews)
 * @param filter    active sector filter; null/"" = no filter (all rows)
 *
 * WHY return the SAME array reference when no filter: avoids breaking
 * referential equality for memoized consumers (AG Grid row identity,
 * useMemo deps) on the overwhelmingly common unfiltered path.
 */
export function filterHoldingsBySector(
  holdings: Holding[],
  sectors: Record<string, string | null>,
  filter: string | null,
): Holding[] {
  if (!filter || filter.trim() === "") return holdings;
  return holdings.filter((h) =>
    holdingMatchesSector(sectors[h.instrument_id] ?? null, filter),
  );
}
