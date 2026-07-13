/**
 * lib/portfolio/__tests__/adjusting-transaction.test.ts — PLAN-0122 W-D (T-A-D-01).
 *
 * WHY THIS EXISTS: computeAdjustment is the single load-bearing rule behind the
 * honest-ledger Edit Position mechanism (PRD-0122 §6.4). These tests pin every
 * branch of the delta maths — BUY (+), SELL (−), no-op (0), full-exit (target 0),
 * and the invalid-input guards — so a future refactor cannot silently flip a
 * side, drop a quantity, or turn a real edit into a no-op.
 */

import { describe, it, expect } from "vitest";
import { computeAdjustment } from "../adjusting-transaction";

describe("computeAdjustment (PLAN-0122 W-D honest-ledger delta)", () => {
  it("test_adjusting_transaction_delta_buy: target > current → BUY of delta", () => {
    // Hold 50, want 80 → BUY the 30-share difference.
    expect(computeAdjustment(50, 80)).toEqual({ side: "BUY", quantity: 30 });
  });

  it("test_adjusting_transaction_delta_sell: target < current → SELL of abs(delta)", () => {
    // Hold 50, want 20 → SELL the 30-share difference.
    expect(computeAdjustment(50, 20)).toEqual({ side: "SELL", quantity: 30 });
  });

  it("test_adjusting_transaction_delta_zero_null: target === current → null (no-op)", () => {
    // Nothing to record → null → the dialog disables Submit.
    expect(computeAdjustment(50, 50)).toBeNull();
  });

  it("test_adjusting_transaction_target_zero_full_sell: target 0 with current N → SELL of N", () => {
    // Target 0 means "close entirely" → a full SELL of the whole position.
    expect(computeAdjustment(50, 0)).toEqual({ side: "SELL", quantity: 50 });
  });

  it("handles fractional quantities without rounding drift", () => {
    // Fractional shares are legal (S1 stores Decimal); the delta must be exact.
    expect(computeAdjustment(1.5, 4)).toEqual({ side: "BUY", quantity: 2.5 });
  });

  it("throws RangeError on a negative target quantity", () => {
    // A negative target can never map to a valid trade — distinct from the
    // meaningful `null` (no-op) return, so it must throw (not return null).
    expect(() => computeAdjustment(50, -5)).toThrow(RangeError);
  });

  it("throws RangeError on a non-finite input (NaN)", () => {
    expect(() => computeAdjustment(Number.NaN, 10)).toThrow(RangeError);
    expect(() => computeAdjustment(10, Number.NaN)).toThrow(RangeError);
  });
});
