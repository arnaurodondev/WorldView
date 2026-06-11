/**
 * features/portfolio/lib/__tests__/period-returns.test.ts
 * (2026-06-10 sprint, Wave 2 — Performance panel window math.)
 *
 * WHY: computePeriodReturns drives the overview's "1D/1W/1M/3M vs SPY"
 * rows. The two failure modes these tests guard against are both
 * money-misleading: (a) labelling a since-inception return as a "1M
 * return" when the series doesn't cover the window, and (b) subtracting
 * cumulative TWR values instead of geometrically linking them.
 */

import { describe, it, expect } from "vitest";

import {
  isoDaysBefore,
  windowReturnFromTwr,
  windowReturnFromCloses,
  computePeriodReturns,
  PERIOD_WINDOWS,
} from "../period-returns";
import type { TwrPoint } from "@/types/api";
import type { DatedValue } from "../risk-metrics";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** 40 calendar days of TWR, ~+0.5pp/day cumulative (fractions). */
function twrSeries(days: number, lastDate = "2026-06-10"): TwrPoint[] {
  const out: TwrPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    out.push({
      date: isoDaysBefore(lastDate, i),
      twr_cum: (days - 1 - i) * 0.005,
      nav: 100_000,
    });
  }
  return out;
}

describe("isoDaysBefore", () => {
  it("subtracts days in UTC across month boundaries", () => {
    expect(isoDaysBefore("2026-06-10", 1)).toBe("2026-06-09");
    expect(isoDaysBefore("2026-06-01", 1)).toBe("2026-05-31");
    expect(isoDaysBefore("2026-03-01", 1)).toBe("2026-02-28"); // non-leap
  });
});

describe("windowReturnFromTwr", () => {
  it("geometrically links cumulative TWR (NOT naive subtraction)", () => {
    // twr at start = +10%, at end = +21% → window return = 1.21/1.10 − 1 = +10%.
    const pts: TwrPoint[] = [
      { date: "2026-06-01", twr_cum: 0.1, nav: 1 },
      { date: "2026-06-08", twr_cum: 0.21, nav: 1 },
    ];
    const r = windowReturnFromTwr(pts, 7);
    expect(r).toBeCloseTo(0.1, 12);
    // The naive subtraction would have said 11% — pin the distinction.
    expect(r).not.toBeCloseTo(0.11, 3);
  });

  it("uses the LAST point at-or-before the cutoff (weekend carry-forward)", () => {
    // Cutoff for 1D from Mon 06-08 is Sun 06-07 — no Sunday point, so the
    // start is Friday 06-05 (last ≤ cutoff), not a dropped window.
    const pts: TwrPoint[] = [
      { date: "2026-06-05", twr_cum: 0.0, nav: 1 },
      { date: "2026-06-08", twr_cum: 0.02, nav: 1 },
    ];
    expect(windowReturnFromTwr(pts, 1)).toBeCloseTo(0.02, 12);
  });

  it("returns null when the series does not cover the window", () => {
    // 5 calendar days of history cannot honestly produce a 30-day return.
    expect(windowReturnFromTwr(twrSeries(5), 30)).toBeNull();
  });

  it("returns null for fewer than 2 points", () => {
    expect(windowReturnFromTwr([], 7)).toBeNull();
    expect(
      windowReturnFromTwr([{ date: "2026-06-10", twr_cum: 0, nav: 1 }], 7),
    ).toBeNull();
  });

  it("returns null for a degenerate −100% start factor (no fabricated number)", () => {
    const pts: TwrPoint[] = [
      { date: "2026-06-01", twr_cum: -1, nav: 0 },
      { date: "2026-06-08", twr_cum: 0.5, nav: 1 },
    ];
    expect(windowReturnFromTwr(pts, 7)).toBeNull();
  });
});

describe("windowReturnFromCloses", () => {
  it("computes close_last / close_start − 1 over the window", () => {
    const closes: DatedValue[] = [
      { date: "2026-06-01", value: 500 },
      { date: "2026-06-08", value: 510 },
    ];
    expect(windowReturnFromCloses(closes, 7)).toBeCloseTo(0.02, 12);
  });

  it("returns null when the window is not covered", () => {
    const closes: DatedValue[] = [
      { date: "2026-06-07", value: 500 },
      { date: "2026-06-08", value: 510 },
    ];
    expect(windowReturnFromCloses(closes, 30)).toBeNull();
  });
});

describe("computePeriodReturns", () => {
  it("produces all four rows with portfolio, benchmark and excess", () => {
    const twr = twrSeries(40);
    const spy: DatedValue[] = twr.map((p, i) => ({
      date: p.date,
      value: 500 * (1 + i * 0.001),
    }));

    const rows = computePeriodReturns(twr, spy);
    expect(rows.map((r) => r.label)).toEqual(["1D", "1W", "1M", "3M"]);

    const oneW = rows.find((r) => r.label === "1W")!;
    expect(oneW.portfolio).not.toBeNull();
    expect(oneW.benchmark).not.toBeNull();
    // Excess = portfolio − benchmark, exactly.
    expect(oneW.excess).toBeCloseTo(oneW.portfolio! - oneW.benchmark!, 12);

    // 40 days of history cannot cover 3M → null on both sides + excess.
    const threeM = rows.find((r) => r.label === "3M")!;
    expect(threeM.portfolio).toBeNull();
    expect(threeM.excess).toBeNull();
  });

  it("missing benchmark nulls only the benchmark/excess side (portfolio survives)", () => {
    const rows = computePeriodReturns(twrSeries(40), undefined);
    const oneW = rows.find((r) => r.label === "1W")!;
    expect(oneW.portfolio).not.toBeNull();
    expect(oneW.benchmark).toBeNull();
    expect(oneW.excess).toBeNull();
  });

  it("PERIOD_WINDOWS stays the canonical 4-window set (panel layout contract)", () => {
    expect(PERIOD_WINDOWS.map((w) => w.days)).toEqual([1, 7, 30, 91]);
  });
});
