/**
 * features/screener/lib/__tests__/slider-scale.test.ts — pure-math coverage
 * for the Round 2 range-slider scales.
 *
 * WHY THESE TESTS: the slider↔domain mapping is the part of the slider
 * feature that can be wrong silently — a broken log mapping still renders a
 * draggable slider, it just writes nonsense bounds into FilterState (which
 * the backend then happily applies, hiding instruments). Pinning the math as
 * pure functions means we don't need to simulate Radix drags in jsdom.
 */

import { describe, it, expect } from "vitest";
import {
  createLinearScale,
  createLogScale,
  rangeToSliderPositions,
  sliderPositionsToRange,
  roundToSignificant,
  formatCompactNumber,
} from "../slider-scale";

// ── Linear scale ─────────────────────────────────────────────────────────────

describe("createLinearScale", () => {
  const scale = createLinearScale(0, 100, 200);

  it("maps the domain ends to the slider ends", () => {
    expect(scale.toSlider(0)).toBe(0);
    expect(scale.toSlider(100)).toBe(200);
    expect(scale.fromSlider(0)).toBe(0);
    expect(scale.fromSlider(200)).toBe(100);
  });

  it("maps the midpoint linearly (arithmetic mean)", () => {
    expect(scale.fromSlider(100)).toBe(50);
    expect(scale.toSlider(50)).toBe(100);
  });

  it("round-trips interior values within one step of tolerance", () => {
    for (const v of [1, 12.5, 33, 50, 87.4, 99]) {
      const back = scale.fromSlider(scale.toSlider(v));
      // 200 steps over a 100-wide domain → resolution 0.5 per step.
      expect(Math.abs(back - v)).toBeLessThanOrEqual(0.5);
    }
  });

  it("clamps out-of-domain values to the nearest end", () => {
    expect(scale.toSlider(-50)).toBe(0);
    expect(scale.toSlider(1e9)).toBe(200);
    expect(scale.fromSlider(-10)).toBe(0);
    expect(scale.fromSlider(9999)).toBe(100);
  });

  it("supports zero-crossing domains (ROE −0.5…1.0)", () => {
    const roe = createLinearScale(-0.5, 1.0, 150);
    expect(roe.fromSlider(0)).toBe(-0.5);
    expect(roe.fromSlider(150)).toBe(1.0);
    // 0 sits at 1/3 of the track: (0 − (−0.5)) / 1.5 = 0.3333 → position 50.
    expect(roe.toSlider(0)).toBe(50);
  });

  it("throws when max does not exceed min", () => {
    expect(() => createLinearScale(5, 5)).toThrow();
    expect(() => createLinearScale(10, 1)).toThrow();
  });
});

// ── Log scale (the Market Cap / Volume math) ─────────────────────────────────

describe("createLogScale", () => {
  // The actual Market Cap configuration: $10M → $5T over 300 steps.
  const cap = createLogScale(10_000_000, 5_000_000_000_000, 300);

  it("maps the domain ends to the slider ends", () => {
    expect(cap.toSlider(10_000_000)).toBe(0);
    expect(cap.toSlider(5_000_000_000_000)).toBe(300);
    expect(cap.fromSlider(0)).toBeCloseTo(10_000_000, 0);
    expect(cap.fromSlider(300)).toBeCloseTo(5_000_000_000_000, 0);
  });

  it("places the slider midpoint at the GEOMETRIC mean (not arithmetic)", () => {
    // √(1e7 × 5e12) ≈ 7.07e9 — the small/large-cap divide. This is THE
    // property that makes the log scale useful: a linear slider's midpoint
    // would be ≈ $2.5T, wasting half the track on 30 mega-caps.
    const mid = cap.fromSlider(150);
    const geometricMean = Math.sqrt(10_000_000 * 5_000_000_000_000);
    expect(mid / geometricMean).toBeCloseTo(1, 6);
    // Sanity: nowhere near the arithmetic mean.
    expect(mid).toBeLessThan(1e10);
  });

  it("gives each order of magnitude equal track width", () => {
    // Equal multiplicative steps must produce equal position deltas:
    // $100M→$1B and $10B→$100B are both one decade apart.
    const d1 = cap.toSlider(1_000_000_000) - cap.toSlider(100_000_000);
    const d2 = cap.toSlider(100_000_000_000) - cap.toSlider(10_000_000_000);
    // Integer rounding allows ±1 step of difference.
    expect(Math.abs(d1 - d2)).toBeLessThanOrEqual(1);
  });

  it("round-trips values within one slider step of relative tolerance", () => {
    // One step on a 300-step / 5.7-decade scale ≈ ×1.045 — assert the
    // round-trip lands within that multiplicative resolution.
    const stepRatio = (5_000_000_000_000 / 10_000_000) ** (1 / 300);
    for (const v of [50_000_000, 2_000_000_000, 75_000_000_000, 1_000_000_000_000]) {
      const back = cap.fromSlider(cap.toSlider(v));
      expect(back / v).toBeGreaterThan(1 / stepRatio);
      expect(back / v).toBeLessThan(stepRatio);
    }
  });

  it("clamps zero/negative inputs instead of producing NaN (typed-input guard)", () => {
    // The numeric inputs accept any number; ln(0) = −Infinity must never
    // reach the thumb position.
    expect(cap.toSlider(0)).toBe(0);
    expect(cap.toSlider(-5)).toBe(0);
  });

  it("throws on a non-positive domainMin (ln undefined)", () => {
    expect(() => createLogScale(0, 100)).toThrow();
    expect(() => createLogScale(-1, 100)).toThrow();
  });
});

// ── Range ↔ positions (the unbounded-ends rule) ──────────────────────────────

describe("rangeToSliderPositions / sliderPositionsToRange", () => {
  const scale = createLinearScale(0, 100, 100);

  it("undefined sides park the thumbs at the track ends", () => {
    expect(rangeToSliderPositions(undefined, undefined, scale)).toEqual([0, 100]);
    expect(rangeToSliderPositions(20, undefined, scale)).toEqual([20, 100]);
    expect(rangeToSliderPositions(undefined, 80, scale)).toEqual([0, 80]);
  });

  it("thumbs at the track ends produce undefined (filter OFF), not domain bounds", () => {
    // CRITICAL UX rule: untouched slider = no filter. Writing domainMin/Max
    // would add hard server bounds that INNER-JOIN-exclude instruments with
    // missing metric data (BP-368 class of bug).
    expect(sliderPositionsToRange([0, 100], scale)).toEqual({ min: undefined, max: undefined });
    expect(sliderPositionsToRange([0, 60], scale)).toEqual({ min: undefined, max: 60 });
    expect(sliderPositionsToRange([30, 100], scale)).toEqual({ min: 30, max: undefined });
  });

  it("round-trips an interior range", () => {
    const [lo, hi] = rangeToSliderPositions(25, 75, scale);
    expect(sliderPositionsToRange([lo, hi], scale)).toEqual({ min: 25, max: 75 });
  });

  it("guards inverted typed ranges (min > max) by swapping positions", () => {
    // User typed min=80, max=20 into the free-form inputs: Radix requires
    // value[0] ≤ value[1], so positions come back ordered.
    const [lo, hi] = rangeToSliderPositions(80, 20, scale);
    expect(lo).toBeLessThanOrEqual(hi);
  });

  it("rounds log-scale outputs to significant digits for clean chips", () => {
    const cap = createLogScale(10_000_000, 5_000_000_000_000, 300);
    const { min } = sliderPositionsToRange([150, 300], cap, 3);
    // Geometric mean ≈ 7071067811.8…; 3 significant digits → 7.07e9 exactly.
    expect(min).toBe(7_070_000_000);
  });
});

// ── Rounding + formatting helpers ────────────────────────────────────────────

describe("roundToSignificant", () => {
  it("rounds to significant digits across magnitudes", () => {
    expect(roundToSignificant(1234567890, 3)).toBe(1230000000);
    expect(roundToSignificant(0.012345, 3)).toBe(0.0123);
    expect(roundToSignificant(98.76, 2)).toBe(99);
  });

  it("passes through zero and non-finite values unchanged", () => {
    expect(roundToSignificant(0)).toBe(0);
    expect(roundToSignificant(Infinity)).toBe(Infinity);
  });

  it("handles negatives symmetrically", () => {
    expect(roundToSignificant(-1234567, 3)).toBe(-1230000);
  });
});

describe("formatCompactNumber", () => {
  it("uses fixed K/M/B/T suffixes (locale-independent terminal convention)", () => {
    expect(formatCompactNumber(1_500_000)).toBe("1.5M");
    expect(formatCompactNumber(2_500_000_000_000)).toBe("2.5T");
    expect(formatCompactNumber(10_000_000_000)).toBe("10B");
    expect(formatCompactNumber(25_000)).toBe("25K");
    expect(formatCompactNumber(999)).toBe("999");
  });

  it("keeps negatives signed", () => {
    expect(formatCompactNumber(-3_000_000)).toBe("-3M");
  });
});
