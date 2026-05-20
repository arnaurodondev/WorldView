/**
 * __tests__/instrument-detail.test.tsx — OBSOLETE after PLAN-0090 T-E-01.
 *
 * WHY THIS FILE IS A SKIP STUB: The original tests asserted behaviour of
 * the OLD instrument detail components (FundamentalsTab, IntelligenceTab,
 * InstrumentAISubheader) which were deleted in PLAN-0090 T-E-01.
 *
 * REPLACEMENT TESTS land in T-E-02 covering the new per-tab structure:
 *   - QuoteTab / OHLCVChart  (components/instrument/quote/)
 *   - FinancialsTab          (components/instrument/financials/)
 *   - IntelligenceTab        (components/instrument/intelligence/)
 *   - InstrumentHeader       (components/instrument/header/)
 *
 * WHY skip rather than delete: per R19 we never delete tests outright;
 * a placeholder describe.skip keeps the audit trail and lets T-E-02
 * replace the suite intentionally.
 */
import { describe, it, expect } from "vitest";

describe.skip("instrument-detail (obsolete — see PLAN-0090 T-E-02)", () => {
  it("placeholder", () => {
    expect(true).toBe(true);
  });
});
