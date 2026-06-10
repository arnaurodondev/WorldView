/**
 * features/portfolio/lib/__tests__/risk-metrics.test.ts (R2 sprint)
 *
 * WHY: the risk-metrics lib backs the MONEY-FACING numbers on the analytics
 * surface (Sharpe / MaxDD / Vol / Beta + TWR + drawdown + benchmark
 * normalization). Every expected value below is HAND-COMPUTED from the
 * documented formulas — never derived by re-running the implementation —
 * so a formula regression cannot silently "pass against itself".
 */

import { describe, it, expect } from "vitest";

import {
  MIN_OBSERVATIONS,
  TRADING_DAYS_PER_YEAR,
  mean,
  sampleStdDev,
  dailyReturns,
  cumulativeReturnSeries,
  drawdownSeries,
  maxDrawdown,
  annualizedVolatility,
  annualizedSharpe,
  betaVsBenchmark,
  alignBenchmarkToDates,
  benchmarkCumulativeReturns,
  computeRiskMetrics,
  type DatedValue,
} from "../risk-metrics";

// ── Fixture builders ──────────────────────────────────────────────────────────

/** Sequential dated values starting 2026-01-01 (ISO dates sort correctly). */
function dated(values: number[]): DatedValue[] {
  return values.map((value, i) => {
    const d = new Date(Date.UTC(2026, 0, 1 + i));
    return { date: d.toISOString().slice(0, 10), value };
  });
}

/** Exactly 20 alternating ±1% returns — mean 0, hand-computable stdev. */
const ALT_RETURNS = Array.from({ length: 20 }, (_, i) =>
  i % 2 === 0 ? 0.01 : -0.01,
);

// ── Basic statistics ──────────────────────────────────────────────────────────

describe("mean / sampleStdDev", () => {
  it("mean of [1,2,3] is 2; empty input is null (never NaN)", () => {
    expect(mean([1, 2, 3])).toBe(2);
    expect(mean([])).toBeNull();
  });

  it("sample stdev of [2,4,4,4,5,5,7,9] is √(32/7) ≈ 2.138090", () => {
    // Hand computation: mean = 40/8 = 5. Squared deviations:
    // 9+1+1+1+0+0+4+16 = 32. Sample variance = 32/7. stdev = √(32/7).
    expect(sampleStdDev([2, 4, 4, 4, 5, 5, 7, 9])).toBeCloseTo(
      Math.sqrt(32 / 7),
      12,
    );
  });

  it("sample stdev needs ≥2 observations", () => {
    expect(sampleStdDev([])).toBeNull();
    expect(sampleStdDev([5])).toBeNull();
  });
});

// ── dailyReturns ──────────────────────────────────────────────────────────────

describe("dailyReturns", () => {
  it("computes simple returns: [100,110,99] → [+10%, -10%]", () => {
    const r = dailyReturns([100, 110, 99]);
    expect(r).toHaveLength(2);
    expect(r[0]).toBeCloseTo(0.1, 12);
    expect(r[1]).toBeCloseTo(-0.1, 12);
  });

  it("skips pairs with a non-positive base (no ±Infinity poisoning)", () => {
    // (100→0) is a valid -100% return; (0→50) has base 0 and is SKIPPED.
    expect(dailyReturns([100, 0, 50])).toEqual([-1]);
  });

  it("returns [] for empty / single-point series", () => {
    expect(dailyReturns([])).toEqual([]);
    expect(dailyReturns([100])).toEqual([]);
  });
});

// ── cumulativeReturnSeries (TWR-chart rebase) ─────────────────────────────────

describe("cumulativeReturnSeries", () => {
  it("rebases to 0% at the first point: [100,110,121] → [0, 0.10, 0.21]", () => {
    const out = cumulativeReturnSeries(dated([100, 110, 121]));
    expect(out.map((p) => p.ret)).toEqual([
      0,
      expect.closeTo(0.1, 12),
      expect.closeTo(0.21, 12),
    ]);
    // Dates pass through unchanged (chart x-axis contract).
    expect(out[0].date).toBe("2026-01-01");
  });

  it("refuses to rebase on a non-positive base (would fabricate returns)", () => {
    expect(cumulativeReturnSeries(dated([0, 110]))).toEqual([]);
    expect(cumulativeReturnSeries([])).toEqual([]);
  });
});

// ── drawdownSeries ────────────────────────────────────────────────────────────

describe("drawdownSeries", () => {
  it("computes dd_t = V_t/max(V_0..t) − 1: [100,120,90,95,130]", () => {
    // Running peaks: 100, 120, 120, 120, 130.
    // dd: 0, 0, 90/120−1 = −0.25, 95/120−1 = −5/24 ≈ −0.208333, 0 (new high).
    const out = drawdownSeries(dated([100, 120, 90, 95, 130]));
    expect(out.map((p) => p.drawdown)).toEqual([
      0,
      0,
      expect.closeTo(-0.25, 12),
      expect.closeTo(-5 / 24, 12),
      0,
    ]);
  });

  it("is 0 at every new high and never positive", () => {
    const out = drawdownSeries(dated([50, 60, 70]));
    expect(out.every((p) => p.drawdown === 0)).toBe(true);
  });
});

// ── maxDrawdown ───────────────────────────────────────────────────────────────

describe("maxDrawdown", () => {
  it("finds the deepest trough on a 22-point series (−25%)", () => {
    // Peak 200 (index 3) → trough 150 (index 6) ⇒ maxDD = 150/200 − 1 = −0.25.
    // The later recovery climb never dips below that. 22 points ≥ 21 gate.
    const values = [
      100, 120, 150, 200, 180, 160, 150, 155, 160, 165, 170,
      175, 180, 185, 190, 195, 200, 205, 210, 215, 220, 225,
    ];
    expect(maxDrawdown(dated(values))).toBeCloseTo(-0.25, 12);
  });

  it("returns null below the observation gate (avoids 'this never loses')", () => {
    // 20 points = 19 returns < MIN_OBSERVATIONS ⇒ null.
    const short = dated(Array.from({ length: MIN_OBSERVATIONS }, (_, i) => 100 + i));
    expect(maxDrawdown(short)).toBeNull();
  });
});

// ── annualizedVolatility ──────────────────────────────────────────────────────

describe("annualizedVolatility", () => {
  it("alternating ±1% (20 obs): σ_ann = 0.01·√(20/19)·√252 ≈ 0.162868", () => {
    // Hand computation: mean = 0, squared deviations all 0.0001,
    // sample variance = 20·0.0001/19 ⇒ stdev = 0.01·√(20/19) ≈ 0.01025978.
    // Annualized: × √252 ≈ × 15.8745079 ⇒ ≈ 0.1628685.
    expect(annualizedVolatility(ALT_RETURNS)).toBeCloseTo(0.162868, 4);
  });

  it("returns null below MIN_OBSERVATIONS (19 obs)", () => {
    expect(annualizedVolatility(ALT_RETURNS.slice(0, 19))).toBeNull();
  });
});

// ── annualizedSharpe ──────────────────────────────────────────────────────────

describe("annualizedSharpe", () => {
  it("alternating +2%/0% (20 obs): Sharpe ≈ 15.4725", () => {
    // Hand computation: mean = 0.01. Deviations ±0.01 ⇒ stdev = 0.01·√(20/19)
    // ≈ 0.01025978. Daily ratio = 0.01/0.01025978 ≈ 0.9746794.
    // Annualized: × √252 ≈ 0.9746794 × 15.8745079 ≈ 15.47254.
    const returns = Array.from({ length: 20 }, (_, i) =>
      i % 2 === 0 ? 0.02 : 0,
    );
    expect(annualizedSharpe(returns)).toBeCloseTo(15.4725, 3);
  });

  it("mean 0 series has Sharpe 0 (not null) — losing AND winning equally", () => {
    expect(annualizedSharpe(ALT_RETURNS)).toBeCloseTo(0, 12);
  });

  it("returns null for a flat series (stdev 0 — undefined ratio)", () => {
    expect(annualizedSharpe(Array(20).fill(0.0))).toBeNull();
  });

  it("returns null below MIN_OBSERVATIONS", () => {
    expect(annualizedSharpe(ALT_RETURNS.slice(0, 19))).toBeNull();
  });

  it("annualization factor is √252 (sanity-pin the constant)", () => {
    expect(TRADING_DAYS_PER_YEAR).toBe(252);
  });
});

// ── betaVsBenchmark ───────────────────────────────────────────────────────────

describe("betaVsBenchmark", () => {
  // 20 varied benchmark returns (non-degenerate variance).
  const bench = Array.from({ length: 20 }, (_, i) =>
    (i % 5 - 2) * 0.01, // cycles -0.02,-0.01,0,0.01,0.02
  );

  it("portfolio = 1.5 × benchmark ⇒ beta exactly 1.5", () => {
    // cov(1.5b, b)/var(b) = 1.5·var(b)/var(b) = 1.5 by linearity.
    const port = bench.map((r) => r * 1.5);
    expect(betaVsBenchmark(port, bench)).toBeCloseTo(1.5, 12);
  });

  it("portfolio = benchmark + constant ⇒ beta exactly 1.0", () => {
    // Adding a constant shifts the mean but not deviations ⇒ cov unchanged.
    const port = bench.map((r) => r + 0.003);
    expect(betaVsBenchmark(port, bench)).toBeCloseTo(1.0, 12);
  });

  it("returns null on length mismatch (silent truncation forbidden)", () => {
    expect(betaVsBenchmark(bench.slice(0, 19), bench)).toBeNull();
  });

  it("returns null below MIN_OBSERVATIONS pairs", () => {
    expect(
      betaVsBenchmark(bench.slice(0, 19), bench.slice(0, 19)),
    ).toBeNull();
  });

  it("returns null when benchmark variance is 0 (division by zero)", () => {
    const flat = Array(20).fill(0.01);
    expect(betaVsBenchmark(bench, flat)).toBeNull();
  });
});

// ── alignBenchmarkToDates ─────────────────────────────────────────────────────

describe("alignBenchmarkToDates", () => {
  it("carries the last close forward over weekend gaps", () => {
    // Portfolio snapshots run daily (incl. Sat 03 / Sun 04); SPY only has
    // closes on trading days 01, 02, 05. Sat/Sun reuse Friday's close.
    const dates = ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"];
    const closes: DatedValue[] = [
      { date: "2026-01-01", value: 100 },
      { date: "2026-01-02", value: 102 },
      { date: "2026-01-05", value: 105 },
    ];
    expect(alignBenchmarkToDates(dates, closes)).toEqual([100, 102, 102, 102, 105]);
  });

  it("yields null BEFORE the first close (never carries backward)", () => {
    const dates = ["2026-01-01", "2026-01-02", "2026-01-03"];
    const closes: DatedValue[] = [{ date: "2026-01-02", value: 50 }];
    expect(alignBenchmarkToDates(dates, closes)).toEqual([null, 50, 50]);
  });
});

// ── benchmarkCumulativeReturns ────────────────────────────────────────────────

describe("benchmarkCumulativeReturns", () => {
  it("rebases at the FIRST NON-NULL close: [null,100,110] → [null,0,0.1]", () => {
    const out = benchmarkCumulativeReturns([null, 100, 110]);
    expect(out[0]).toBeNull();
    expect(out[1]).toBe(0);
    expect(out[2]).toBeCloseTo(0.1, 12);
  });
});

// ── computeRiskMetrics bundle ─────────────────────────────────────────────────

describe("computeRiskMetrics", () => {
  it("portfolio tracking the benchmark 1:1 ⇒ beta 1.0; counts observations", () => {
    // 22 points: portfolio NAV = 1000 × SPY close on the SAME dates. Closes
    // are INTEGERS with real variance (zig-zag up) so each paired daily
    // return is bit-identical (102000/100000 and 102/100 round to the same
    // double) and the benchmark variance is non-degenerate ⇒ beta = 1.
    const closeValues = Array.from({ length: 22 }, (_, i) =>
      100 + 2 * i + (i % 2), // 100,103,104,107,108,… up with wiggle
    );
    const closes = dated(closeValues);
    const portfolio = closes.map((c) => ({ date: c.date, value: c.value * 1000 }));

    const m = computeRiskMetrics(portfolio, closes);
    expect(m.nObservations).toBe(21);
    expect(m.beta).toBeCloseTo(1.0, 10);
    // Strictly-rising series never draws down.
    expect(m.maxDrawdown).toBe(0);
    // Returns vary ⇒ Sharpe and vol are real numbers, not null.
    expect(m.sharpe).not.toBeNull();
    expect(m.volatilityAnnualized).toBeGreaterThan(0);
  });

  it("beta is null without a benchmark; other metrics still compute", () => {
    const portfolio = dated(
      Array.from({ length: 25 }, (_, i) => 100 + (i % 3)), // wiggly series
    );
    const m = computeRiskMetrics(portfolio);
    expect(m.beta).toBeNull();
    expect(m.sharpe).not.toBeNull();
    expect(m.volatilityAnnualized).not.toBeNull();
  });

  it("everything is null on a tiny series (insufficient data is honest)", () => {
    const m = computeRiskMetrics(dated([100, 101, 102]));
    expect(m.sharpe).toBeNull();
    expect(m.volatilityAnnualized).toBeNull();
    expect(m.maxDrawdown).toBeNull();
    expect(m.beta).toBeNull();
    expect(m.nObservations).toBe(2);
  });
});
