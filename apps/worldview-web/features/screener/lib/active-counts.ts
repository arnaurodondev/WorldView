/**
 * features/screener/lib/active-counts.ts — Pure helpers that count how many
 * filters are "active" per section so the Section sub-component can render
 * its badge without introspecting the FilterState shape.
 *
 * WHY EXTRACTED (PLAN-0059 E-4): the count math sat inline in
 * ScreenerFilterBar.tsx (~30 LOC of repeated isSet/rangeCount addition).
 * Pulling it out lets us cover every section's count rule with focused
 * unit tests (no need to mount the whole bar) AND lets future drill-down
 * panels show the same badge counts without duplicating the rules.
 */

import type { FilterState } from "./filter-state";

/**
 * isSet — a filter is "active" when defined AND not the all/empty sentinel.
 * The Section badges count active filters per group so the user sees state
 * at a glance.
 */
export function isSet(v: unknown): boolean {
  if (v === undefined || v === null) return false;
  if (typeof v === "string") return v !== "" && v !== "ALL";
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "boolean") return v === true;
  return true;
}

/** rangeCount — sum of how many sides of a min/max pair are set (0 / 1 / 2). */
export function rangeCount(
  min: number | undefined,
  max: number | undefined,
): number {
  return (isSet(min) ? 1 : 0) + (isSet(max) ? 1 : 0);
}

/**
 * Per-section badge counts. Each property mirrors a Section title in the
 * ScreenerFilterBar render tree.
 */
export interface SectionActiveCounts {
  valuation: number;
  profitability: number;
  growth: number;
  leverage: number;
  technical: number;
  // IB-L3 — Returns + 52W distance (SERVER_SIDE, backend shipped)
  performance: number;
  // IB-L4 — Analyst / Insider / Ownership (SERVER_SIDE, backend shipped)
  ownership: number;
  news: number;
  // IB-L5 — Intelligence rollup (SERVER_SIDE, backend shipped)
  intelligence: number;
}

/**
 * countActiveFiltersByGroup — single pass over FilterState producing the
 * 6 section-badge counts. Cheap (≤30 boolean checks) so the bar can call
 * this on every render without memoisation.
 *
 * Pinned by tests in `__tests__/active-counts.test.ts` so any future
 * FilterState field that adds a new "active" rule must update this helper
 * + its test fixture in one go.
 */
export function countActiveFiltersByGroup(
  form: FilterState,
): SectionActiveCounts {
  return {
    valuation:
      rangeCount(form.peMin, form.peMax) +
      rangeCount(form.pbMin, form.pbMax) +
      rangeCount(form.psMin, form.psMax) +
      rangeCount(form.divYieldMin, form.divYieldMax),

    profitability:
      rangeCount(form.roeMin, form.roeMax) +
      rangeCount(form.grossMarginMin, form.grossMarginMax) +
      rangeCount(form.netMarginMin, form.netMarginMax) +
      rangeCount(form.opMarginMin, form.opMarginMax),

    growth:
      rangeCount(form.revGrowthMin, form.revGrowthMax) +
      rangeCount(form.earningsGrowthMin, form.earningsGrowthMax),

    leverage:
      rangeCount(form.debtEquityMin, form.debtEquityMax) +
      rangeCount(form.currentRatioMin, form.currentRatioMax),

    technical:
      (form.above50dMa ? 1 : 0) +
      rangeCount(form.rsiMin, form.rsiMax) +
      (isSet(form.volumeRatioMin) ? 1 : 0) +
      (isSet(form.distFrom52wHighMax) ? 1 : 0) +
      (isSet(form.distFrom52wLowMin) ? 1 : 0),

    // IB-L3 — Returns + 52W distance (8 range pairs)
    performance:
      rangeCount(form.dist52wHighPctMin, form.dist52wHighPctMax) +
      rangeCount(form.dist52wLowPctMin, form.dist52wLowPctMax) +
      rangeCount(form.return1mMin, form.return1mMax) +
      rangeCount(form.return3mMin, form.return3mMax) +
      rangeCount(form.return6mMin, form.return6mMax) +
      rangeCount(form.returnYtdMin, form.returnYtdMax) +
      rangeCount(form.return1yMin, form.return1yMax) +
      rangeCount(form.return3yMin, form.return3yMax),

    // IB-L4 — Analyst / Insider / Ownership (5 range pairs)
    // WHY no ANALYST UPSIDE filter: it is client-side derived (target/price − 1);
    // v1 ships no server-side filter for it per spec §IB-L4 T-IB4-02 note.
    ownership:
      rangeCount(form.analystTargetPriceMin, form.analystTargetPriceMax) +
      rangeCount(form.analystConsensusMin, form.analystConsensusMax) +
      rangeCount(form.insiderNetBuy90dMin, form.insiderNetBuy90dMax) +
      rangeCount(form.instOwnPctMin, form.instOwnPctMax) +
      rangeCount(form.shortPctMin, form.shortPctMax),

    news:
      (isSet(form.newsVelocity7dMin) ? 1 : 0) +
      rangeCount(form.controversyMin, form.controversyMax) +
      (isSet(form.recentEarningsDays) ? 1 : 0) +
      (isSet(form.insiderActivity) ? 1 : 0),

    // IB-L5 — Intelligence rollup (6 range sides + 2 boolean toggles)
    // WHY boolean flags counted as 1 each: a single boolean "has active alert"
    // is a meaningful constraint worth showing in the section badge.
    intelligence:
      rangeCount(form.newsCount7dMin, form.newsCount7dMax) +
      rangeCount(form.llmRelevance7dMin, form.llmRelevance7dMax) +
      rangeCount(form.displayRelevance7dMin, form.displayRelevance7dMax) +
      rangeCount(form.contradictionsMin, form.contradictionsMax) +
      (form.hasAiBrief === true ? 1 : 0) +
      (form.hasActiveAlert === true ? 1 : 0),
  };
}
