/**
 * components/screener/__tests__/number-hygiene.test.ts
 *
 * WHY THIS FILE EXISTS (roadmap #6 / A2):
 *   signedZeroPct is the number-hygiene helper for the directional CHG% and
 *   REV-YoY columns. Its whole reason to exist is to NOT print "+0.00%" or the
 *   meaningless negative-zero "-0.00%". These tests pin that contract — they are
 *   the regression guard for the exact tells the audit called out.
 */

import { describe, it, expect } from "vitest";
import { signedZeroPct } from "@/components/screener/ag-screener-columns";

describe("signedZeroPct — directional percent with neutral zero", () => {
  it("neutralises an exact zero (no sign, flat direction)", () => {
    expect(signedZeroPct(0, 2)).toEqual({ text: "0.00%", direction: "flat" });
  });

  it("neutralises a tiny negative that rounds to zero (the -0.00% bug)", () => {
    // -0.0001 → -0.01% × ... rounds to 0.00 at 2dp → must be flat, never "-0.00%".
    expect(signedZeroPct(-0.0000001, 2)).toEqual({ text: "0.00%", direction: "flat" });
  });

  it("neutralises a tiny positive that rounds to zero", () => {
    expect(signedZeroPct(0.0000001, 2)).toEqual({ text: "0.00%", direction: "flat" });
  });

  it("signs a genuine positive move with '+'", () => {
    expect(signedZeroPct(0.0123, 2)).toEqual({ text: "+1.23%", direction: "up" });
  });

  it("signs a genuine negative move with a hyphen-minus", () => {
    expect(signedZeroPct(-0.0123, 2)).toEqual({ text: "-1.23%", direction: "down" });
  });

  it("honours a custom decimal precision (REV YoY uses 1dp)", () => {
    expect(signedZeroPct(0.124, 1)).toEqual({ text: "+12.4%", direction: "up" });
    expect(signedZeroPct(0, 1)).toEqual({ text: "0.0%", direction: "flat" });
  });
});
