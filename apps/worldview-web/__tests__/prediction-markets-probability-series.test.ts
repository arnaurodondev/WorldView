/**
 * __tests__/prediction-markets-probability-series.test.ts — pure transforms for
 * the ProbabilityChart (PLAN-0056 Wave E2).
 *
 * WHY unit-test the maths separately from the chart: recharts + jsdom can't
 * render SVG paths at zero container size, so the trustworthy way to prove the
 * chart plots the RIGHT numbers is to test the pivot + delta functions directly.
 */

import { describe, it, expect } from "vitest";
import {
  pivotPricePoints,
  computeYesDeltaPp,
  seriesKey,
} from "@/components/prediction-markets/probability-series";
import type { PredictionMarketPricePoint } from "@/types/api";

function pt(overrides: Partial<PredictionMarketPricePoint>): PredictionMarketPricePoint {
  return {
    window_start_ts: "2026-07-01T00:00:00Z",
    price: 0.5,
    interval: "1d",
    token_id: "tok-yes",
    outcome_name: "Yes",
    ...overrides,
  };
}

describe("pivotPricePoints", () => {
  it("pivots per-token points into wide rows with one column per outcome", () => {
    const points = [
      pt({ window_start_ts: "2026-07-01T00:00:00Z", outcome_name: "Yes", price: 0.6 }),
      pt({ window_start_ts: "2026-07-01T00:00:00Z", outcome_name: "No", token_id: "tok-no", price: 0.4 }),
      pt({ window_start_ts: "2026-07-02T00:00:00Z", outcome_name: "Yes", price: 0.7 }),
      pt({ window_start_ts: "2026-07-02T00:00:00Z", outcome_name: "No", token_id: "tok-no", price: 0.3 }),
    ];
    const { rows, series } = pivotPricePoints(points);

    expect(series).toEqual(["Yes", "No"]);
    expect(rows).toHaveLength(2);
    // Prices are converted to PERCENT (×100) for the 0–100 axis.
    expect(rows[0].Yes).toBe(60);
    expect(rows[0].No).toBe(40);
    expect(rows[1].Yes).toBe(70);
  });

  it("sorts rows ascending by timestamp regardless of input order", () => {
    const points = [
      pt({ window_start_ts: "2026-07-03T00:00:00Z", price: 0.8 }),
      pt({ window_start_ts: "2026-07-01T00:00:00Z", price: 0.5 }),
    ];
    const { rows } = pivotPricePoints(points);
    expect(rows[0].Yes).toBe(50);
    expect(rows[1].Yes).toBe(80);
  });

  it("clamps out-of-range prices into [0,100]", () => {
    const { rows } = pivotPricePoints([pt({ price: 1.4 }), pt({ window_start_ts: "2026-07-02T00:00:00Z", price: -0.2 })]);
    expect(rows[0].Yes).toBe(100);
    expect(rows[1].Yes).toBe(0);
  });

  it("falls back to a token-prefixed key when outcome_name is missing", () => {
    expect(seriesKey(pt({ outcome_name: null, token_id: "abcdef123456" }))).toBe("#abcdef");
  });
});

describe("computeYesDeltaPp", () => {
  it("returns the first→last YES change in percentage points", () => {
    const points = [
      pt({ window_start_ts: "2026-07-01T00:00:00Z", outcome_name: "Yes", price: 0.5 }),
      pt({ window_start_ts: "2026-07-02T00:00:00Z", outcome_name: "Yes", price: 0.65 }),
    ];
    // 65% - 50% = +15pp
    expect(computeYesDeltaPp(points)).toBeCloseTo(15);
  });

  it("returns null when there are fewer than two YES points", () => {
    expect(computeYesDeltaPp([pt({ outcome_name: "Yes" })])).toBeNull();
    expect(computeYesDeltaPp([pt({ outcome_name: "No", token_id: "n" })])).toBeNull();
  });
});
