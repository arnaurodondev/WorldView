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
  news: number;
  // PRD-0089 Wave I-B Block IB-L2: two new section badges. The "Cash Flow"
  // section hosts the FCF + FCF margin ranges; "Risk" hosts the leverage /
  // coverage / credit-rating filters (interest coverage, net debt/EBITDA,
  // credit ratings multi-select). Added here rather than folded into
  // "profitability" so the badge counts match the section the user sees.
  cashFlow: number;
  risk: number;
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
      rangeCount(form.opMarginMin, form.opMarginMax) +
      // PRD-0089 IB-L2: EPS (TTM) is an earnings-quality signal that belongs
      // with the other profitability ranges in the Profitability section.
      rangeCount(form.epsTtmMin, form.epsTtmMax),

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
      (isSet(form.distFrom52wLowMin) ? 1 : 0) +
      // PRD-0089 IB-L2: AVG VOL (30d) is a liquidity / volume signal
      // and lives in the Technical section.
      rangeCount(form.avgVolume30dMin, form.avgVolume30dMax),

    news:
      (isSet(form.newsVelocity7dMin) ? 1 : 0) +
      rangeCount(form.controversyMin, form.controversyMax) +
      (isSet(form.recentEarningsDays) ? 1 : 0) +
      (isSet(form.insiderActivity) ? 1 : 0),

    // ── PRD-0089 Wave I-B Block IB-L2 — Cash Flow section ────────────────
    // FCF (absolute USD range) + FCF margin (% range). AVG VOL lives in the
    // Technical section (it's a liquidity / volume signal) — NOT here.
    cashFlow:
      rangeCount(form.freeCashFlowMin, form.freeCashFlowMax) +
      rangeCount(form.fcfMarginMin, form.fcfMarginMax),

    // ── PRD-0089 Wave I-B Block IB-L2 — Risk section ─────────────────────
    // Interest coverage, net debt / EBITDA, and credit-rating multi-select.
    // The credit-rating chip counts once if any rating is selected (not
    // once per rating); that matches how the chip strip renders it.
    risk:
      rangeCount(form.interestCoverageMin, form.interestCoverageMax) +
      rangeCount(form.netDebtToEbitdaMin, form.netDebtToEbitdaMax) +
      (form.creditRatings && form.creditRatings.length > 0 ? 1 : 0),
  };
}
