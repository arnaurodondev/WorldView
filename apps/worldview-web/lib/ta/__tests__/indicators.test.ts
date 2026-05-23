/**
 * lib/ta/__tests__/indicators.test.ts — Unit tests for TA indicator functions.
 *
 * WHY THESE TESTS EXIST (PLAN-0091 Wave F-1):
 * TA computations are pure math — off-by-one seeding errors or sign flips
 * produce plausible-but-wrong values that look fine on the chart but mislead
 * analysts. These tests pin the algorithm against known-good reference values
 * so regressions are caught immediately on CI.
 *
 * FIXTURE STRATEGY:
 *   barFromClose() — minimal OHLCVBar where H=L=O=Close=volume=0.
 *     Used for tests that only depend on the close column (EMA, SMA, RSI).
 *   makeFHLCV()   — full OHLCV bar with explicit H/L/V for VWAP and Bollinger tests.
 *
 * COVERAGE:
 *   EMA  — 10-bar period-3, all-same closes, insufficient history
 *   SMA  — rolling window, insufficient history
 *   RSI  — NaN warm-up, [0,100] range, div-by-zero (all-gains → 100)
 *   MACD — length contract, NaN propagation during warm-up
 *   Bollinger — upper > middle > lower, NaN during warm-up
 *   VWAP — HLC/3 × volume weighting, zero-volume guard
 */

import { describe, it, expect } from "vitest";
import { ema, sma, rsi, macd, bollingerBands, vwap } from "../indicators";
import type { OHLCVBar } from "@/types/api";

// ── Test helpers ──────────────────────────────────────────────────────────────

/** Minimal bar where only close (and implicitly O/H/L) matters. */
function barFromClose(close: number): OHLCVBar {
  return { timestamp: "2026-01-01T00:00:00Z", open: close, high: close, low: close, close, volume: 1 };
}

/** Full OHLCV bar for tests that depend on high/low/volume. */
function makeBar(open: number, high: number, low: number, close: number, volume: number): OHLCVBar {
  return { timestamp: "2026-01-01T00:00:00Z", open, high, low, close, volume };
}

// ── EMA ───────────────────────────────────────────────────────────────────────

describe("ema", () => {
  it("returns all NaN when bars length < period", () => {
    // 2 bars with period=3: not enough to seed the SMA.
    const bars = [barFromClose(10), barFromClose(11)];
    const result = ema(bars, 3);
    expect(result).toHaveLength(2);
    result.forEach((v) => expect(isNaN(v)).toBe(true));
  });

  it("first period-1 values are NaN, index period-1 is the seed SMA", () => {
    // period=3, bars: [10, 11, 12, ...]. Seed SMA = (10+11+12)/3 = 11.
    const bars = [barFromClose(10), barFromClose(11), barFromClose(12), barFromClose(13)];
    const result = ema(bars, 3);
    // Index 0 and 1 must be NaN (warm-up).
    expect(isNaN(result[0])).toBe(true);
    expect(isNaN(result[1])).toBe(true);
    // Index 2 = seed SMA = (10+11+12)/3 = 11.
    expect(result[2]).toBeCloseTo(11, 8);
    // Index 3: k=2/(3+1)=0.5 → EMA = 13*0.5 + 11*0.5 = 12.
    expect(result[3]).toBeCloseTo(12, 8);
  });

  it("computes correct EMA on 10 bars with period 3", () => {
    // closes: [1,2,3,4,5,6,7,8,9,10], period=3, k=0.5
    // Seed at index 2: (1+2+3)/3 = 2.0
    // index 3: 4*0.5 + 2*0.5 = 3.0
    // index 4: 5*0.5 + 3*0.5 = 4.0
    // index 5: 6*0.5 + 4*0.5 = 5.0
    // ...pattern: EMA[i] = i-1 (for i >= 3 with this specific series)
    const bars = Array.from({ length: 10 }, (_, i) => barFromClose(i + 1));
    const result = ema(bars, 3);
    expect(isNaN(result[0])).toBe(true);
    expect(isNaN(result[1])).toBe(true);
    expect(result[2]).toBeCloseTo(2.0, 6);
    expect(result[3]).toBeCloseTo(3.0, 6);
    expect(result[4]).toBeCloseTo(4.0, 6);
    expect(result[9]).toBeCloseTo(9.0, 6);
  });

  it("returns same value for all bars when all closes are equal", () => {
    // Flat series: EMA = the constant value everywhere (after seed).
    const bars = Array.from({ length: 10 }, () => barFromClose(42));
    const result = ema(bars, 3);
    for (let i = 2; i < result.length; i++) {
      expect(result[i]).toBeCloseTo(42, 8);
    }
  });

  it("returns all NaN for period < 1", () => {
    const bars = [barFromClose(10), barFromClose(20)];
    const result = ema(bars, 0);
    result.forEach((v) => expect(isNaN(v)).toBe(true));
  });
});

// ── SMA ───────────────────────────────────────────────────────────────────────

describe("sma", () => {
  it("returns all NaN when bars length < period", () => {
    const bars = [barFromClose(5), barFromClose(10)];
    const result = sma(bars, 5);
    expect(result).toHaveLength(2);
    result.forEach((v) => expect(isNaN(v)).toBe(true));
  });

  it("first period-1 indices are NaN, rest are rolling means", () => {
    // period=3, closes=[10,20,30,40], SMA[2]=(10+20+30)/3=20, SMA[3]=(20+30+40)/3=30
    const bars = [barFromClose(10), barFromClose(20), barFromClose(30), barFromClose(40)];
    const result = sma(bars, 3);
    expect(isNaN(result[0])).toBe(true);
    expect(isNaN(result[1])).toBe(true);
    expect(result[2]).toBeCloseTo(20, 8);
    expect(result[3]).toBeCloseTo(30, 8);
  });

  it("SMA of a constant series equals the constant", () => {
    const bars = Array.from({ length: 20 }, () => barFromClose(100));
    const result = sma(bars, 5);
    for (let i = 4; i < result.length; i++) {
      expect(result[i]).toBeCloseTo(100, 8);
    }
  });
});

// ── RSI ───────────────────────────────────────────────────────────────────────

describe("rsi", () => {
  it("returns NaN for the first `period` indices (warm-up)", () => {
    // 20 bars, period=14: first 14 values must be NaN, index 14 is first RSI.
    const bars = Array.from({ length: 20 }, (_, i) => barFromClose(100 + i));
    const result = rsi(bars, 14);
    expect(result).toHaveLength(20);
    for (let i = 0; i < 14; i++) {
      expect(isNaN(result[i])).toBe(true);
    }
    // Index 14 must be a valid number in [0,100].
    expect(isNaN(result[14])).toBe(false);
    expect(result[14]).toBeGreaterThanOrEqual(0);
    expect(result[14]).toBeLessThanOrEqual(100);
  });

  it("all-gains series produces RSI = 100 (div-by-zero branch)", () => {
    // Strictly rising closes → avgLoss = 0 → Wilder convention RSI = 100.
    const bars = Array.from({ length: 20 }, (_, i) => barFromClose(100 + i));
    const result = rsi(bars, 14);
    // All defined values should be 100 because there are no losses.
    for (let i = 14; i < result.length; i++) {
      expect(result[i]).toBe(100);
    }
  });

  it("returns all NaN when bars.length < period+1", () => {
    // 14 bars, period=14: need 15 minimum (period+1) — return all NaN.
    const bars = Array.from({ length: 14 }, (_, i) => barFromClose(100 + i));
    const result = rsi(bars, 14);
    result.forEach((v) => expect(isNaN(v)).toBe(true));
  });

  it("defined RSI values stay in [0, 100] range on mixed series", () => {
    // Alternating up/down pattern.
    const closes = [10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17, 16, 15, 17, 18, 19];
    const bars = closes.map(barFromClose);
    const result = rsi(bars, 14);
    for (let i = 0; i < result.length; i++) {
      if (!isNaN(result[i])) {
        expect(result[i]).toBeGreaterThanOrEqual(0);
        expect(result[i]).toBeLessThanOrEqual(100);
      }
    }
  });
});

// ── MACD ─────────────────────────────────────────────────────────────────────

describe("macd", () => {
  it("returns three arrays each with length equal to bars.length", () => {
    const bars = Array.from({ length: 50 }, (_, i) => barFromClose(100 + i));
    const result = macd(bars);
    expect(result.macd).toHaveLength(50);
    expect(result.signal).toHaveLength(50);
    expect(result.histogram).toHaveLength(50);
  });

  it("early bars (index < 25) have NaN in the macd line (EMA26 warm-up)", () => {
    // EMA26 needs 25 bars to seed (index 25). Before that, MACD line is NaN.
    const bars = Array.from({ length: 50 }, (_, i) => barFromClose(100 + i));
    const result = macd(bars);
    // First 25 indices: EMA26 is NaN → MACD line is NaN.
    for (let i = 0; i < 25; i++) {
      expect(isNaN(result.macd[i])).toBe(true);
    }
    // Index 25 onwards: MACD line should be defined.
    expect(isNaN(result.macd[25])).toBe(false);
  });

  it("histogram = macd - signal (accounting for NaN)", () => {
    const bars = Array.from({ length: 50 }, (_, i) => barFromClose(100 + Math.sin(i) * 5));
    const result = macd(bars);
    for (let i = 0; i < bars.length; i++) {
      if (!isNaN(result.macd[i]) && !isNaN(result.signal[i])) {
        expect(result.histogram[i]).toBeCloseTo(result.macd[i] - result.signal[i], 8);
      }
    }
  });
});

// ── Bollinger Bands ───────────────────────────────────────────────────────────

describe("bollingerBands", () => {
  it("returns three arrays of same length as bars", () => {
    const bars = Array.from({ length: 30 }, (_, i) => barFromClose(100 + i));
    const result = bollingerBands(bars, 20, 2);
    expect(result.upper).toHaveLength(30);
    expect(result.middle).toHaveLength(30);
    expect(result.lower).toHaveLength(30);
  });

  it("first period-1 values are NaN", () => {
    const bars = Array.from({ length: 30 }, (_, i) => barFromClose(100 + i));
    const result = bollingerBands(bars, 20, 2);
    for (let i = 0; i < 19; i++) {
      expect(isNaN(result.upper[i])).toBe(true);
      expect(isNaN(result.lower[i])).toBe(true);
    }
  });

  it("upper > middle > lower on a volatile series", () => {
    // Sinusoidal series to guarantee non-zero variance (otherwise bands collapse).
    const bars = Array.from({ length: 30 }, (_, i) => barFromClose(100 + Math.sin(i) * 10));
    const result = bollingerBands(bars, 20, 2);
    for (let i = 19; i < bars.length; i++) {
      expect(result.upper[i]).toBeGreaterThan(result.middle[i]);
      expect(result.middle[i]).toBeGreaterThan(result.lower[i]);
    }
  });

  it("bands collapse to middle on a perfectly flat series (zero std-dev)", () => {
    // All closes identical → std-dev = 0 → upper = middle = lower.
    const bars = Array.from({ length: 25 }, () => barFromClose(50));
    const result = bollingerBands(bars, 20, 2);
    for (let i = 19; i < bars.length; i++) {
      expect(result.upper[i]).toBeCloseTo(result.middle[i], 8);
      expect(result.lower[i]).toBeCloseTo(result.middle[i], 8);
    }
  });

  it("middle equals SMA(period) for each defined index", () => {
    const bars = Array.from({ length: 25 }, (_, i) => barFromClose(i + 1));
    const result = bollingerBands(bars, 5, 2);
    const smaResult = sma(bars, 5);
    for (let i = 4; i < bars.length; i++) {
      expect(result.middle[i]).toBeCloseTo(smaResult[i], 8);
    }
  });
});

// ── VWAP ─────────────────────────────────────────────────────────────────────

describe("vwap", () => {
  it("returns array of same length as bars", () => {
    const bars = Array.from({ length: 10 }, (_, i) => makeBar(i, i + 1, i - 1, i, 100));
    expect(vwap(bars)).toHaveLength(10);
  });

  it("single bar: VWAP = (H+L+C)/3", () => {
    // One bar: H=12, L=8, C=10 → TP=10, volume=100 → VWAP=10.
    const bars = [makeBar(10, 12, 8, 10, 100)];
    const result = vwap(bars);
    expect(result[0]).toBeCloseTo(10, 8);
  });

  it("computes weighted average: high-volume bar dominates", () => {
    // Bar 0: TP=10, volume=10    → contribution=100
    // Bar 1: TP=20, volume=1000  → contribution=20000
    // Expected VWAP after bar 1 = (100+20000)/(10+1000) = 20100/1010 ≈ 19.9009...
    const bars = [
      makeBar(10, 10, 10, 10, 10),
      makeBar(20, 20, 20, 20, 1000),
    ];
    const result = vwap(bars);
    expect(result[0]).toBeCloseTo(10, 6);
    expect(result[1]).toBeCloseTo(20100 / 1010, 6);
  });

  it("equal volumes: VWAP = running average of typical prices", () => {
    // volume=1 everywhere → VWAP[i] = mean(TP[0..i])
    const bars = [
      makeBar(10, 12, 8, 10, 1),   // TP=10
      makeBar(20, 22, 18, 20, 1),  // TP=20
      makeBar(30, 32, 28, 30, 1),  // TP=30
    ];
    const result = vwap(bars);
    expect(result[0]).toBeCloseTo(10, 8);
    expect(result[1]).toBeCloseTo(15, 8); // (10+20)/2
    expect(result[2]).toBeCloseTo(20, 8); // (10+20+30)/3
  });

  it("returns NaN when all volumes are 0 (zero-division guard)", () => {
    // volume=0 for all bars → cumVol stays 0 → NaN.
    const bars = Array.from({ length: 5 }, (_, i) => makeBar(i, i, i, i, 0));
    const result = vwap(bars);
    result.forEach((v) => expect(isNaN(v)).toBe(true));
  });
});
