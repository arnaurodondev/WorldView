/**
 * __tests__/qa-plan-0050-iter1-frontend.test.tsx — OBSOLETE after PLAN-0090 T-E-01.
 *
 * WHY THIS FILE IS A SKIP STUB: The original regression tests covered the
 * PLAN-0050 iter-1 instrument page (FundamentalsTab duplicate-row check,
 * DrawingPalette annotation badge, DrawingCanvas inline TEXT input). All of
 * those components are deleted by PLAN-0090 T-E-01 since PRD-0088 removed
 * the drawing-tools workflow and replaced FundamentalsTab with FinancialsTab.
 *
 * REPLACEMENT REGRESSION TESTS will be authored in T-E-02 to cover the new
 * FinancialsTab + QuoteTab surfaces.
 *
 * WHY skip rather than delete: per R19 we never delete tests outright.
 */
import { describe, it, expect } from "vitest";

describe.skip("qa-plan-0050-iter1-frontend (obsolete — see PLAN-0090 T-E-02)", () => {
  it("placeholder", () => {
    expect(true).toBe(true);
  });
});
