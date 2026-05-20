/**
 * lib/__tests__/technicals.test.ts — Unit tests for computeRSI() and computeATR().
 *
 * WHY THESE TESTS EXIST (PLAN-0090 T-A-01):
 * computeRSI / computeATR feed the TECHNICALS group of the redesigned instrument
 * detail page. The formulas are Wilder's smoothed averages, NOT simple means —
 * a sign-flip in the smoothing or an off-by-one in the seed window silently
 * produces a plausible-but-wrong RSI value. These tests pin the algorithm:
 *   1. Insufficient-data guard returns null (must not crash on cold-cache renders).
 *   2. Known fixture verifies seed + smoothing + RSI formula together.
 *   3. All-gains edge case verifies the div-by-zero branch returns 100 (per Wilder).
 *   4. ATR same insufficient-data guard.
 *   5. ATR on flat OHLC returns 0 (True Range collapses to zero when H==L==prevClose).
 */

import { describe, it, expect } from "vitest";
import { computeRSI, computeATR } from "../technicals";
import type { OHLCVBar } from "@/types/api";

// barFromClose — minimal OHLCVBar where H=L=O=Close (used for RSI tests that
// only depend on the close column).
function barFromClose(close: number): OHLCVBar {
  return {
    timestamp: "2026-01-01T00:00:00Z",
    open: close,
    high: close,
    low: close,
    close,
    volume: 0,
  };
}

describe("computeRSI", () => {
  it("returns null when fewer than period+1 bars are available", () => {
    // 14 bars only → need 15 minimum (14 deltas to seed the smoothed average).
    const bars = Array.from({ length: 14 }, (_, i) => barFromClose(100 + i));
    expect(computeRSI(bars, 14)).toBeNull();
  });

  it("matches the pre-computed Wilder value for a 20-bar synthetic series", () => {
    // Closes: monotonic +1 for the first 14 deltas (seed all gains), then -1 for 5
    // smoothed updates. Hand-verified expected RSI ≈ 69.036 (Wilder, 14-period).
    const closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 23, 22, 21, 20, 19];
    const bars = closes.map(barFromClose);
    expect(computeRSI(bars, 14)).toBeCloseTo(69.036, 2);
  });

  it("returns 100 when every bar is a gain (div-by-zero branch)", () => {
    // Strictly rising closes → avgLoss = 0 forever → Wilder convention: RSI = 100.
    const bars = Array.from({ length: 20 }, (_, i) => barFromClose(100 + i));
    expect(computeRSI(bars, 14)).toBe(100);
  });
});

describe("computeATR", () => {
  it("returns null when fewer than period+1 bars are available", () => {
    const bars = Array.from({ length: 14 }, (_, i) => barFromClose(100 + i));
    expect(computeATR(bars, 14)).toBeNull();
  });

  it("returns 0 for a flat OHLC series (zero true range every bar)", () => {
    // H==L==prevClose for every bar → TR = 0 for every bar → ATR = 0.
    const bars = Array.from({ length: 20 }, () => barFromClose(100));
    expect(computeATR(bars, 14)).toBe(0);
  });
});
