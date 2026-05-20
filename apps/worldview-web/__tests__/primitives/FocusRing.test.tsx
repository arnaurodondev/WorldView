/**
 * __tests__/primitives/FocusRing.test.tsx
 *
 * PRD-0089 F1: pins the 3-tier focus-ring constants so the per-page agents
 * can grep for FocusRing.* and know which tier they should be using.
 */
import { describe, it, expect } from "vitest";
import { FocusRing } from "@/components/primitives/FocusRing";

describe("FocusRing", () => {
  it("exposes three tiers with the documented class strings", () => {
    expect(FocusRing.T1_TABLE_ROW).toContain("focus:outline-1");
    expect(FocusRing.T2_INPUT).toContain("focus:ring-1");
    expect(FocusRing.T3_CHROME_CTA).toContain("focus:ring-2");
    expect(FocusRing.T3_CHROME_CTA).toContain("ring-offset-2");
  });
});
