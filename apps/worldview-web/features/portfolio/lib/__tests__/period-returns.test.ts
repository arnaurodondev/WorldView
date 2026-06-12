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
  windowReturnFromTwrGuarded,
  windowReturnFromCloses,
  computePeriodReturns,
  findFlowArtifactDates,
  isFlowArtifactInterval,
  PERIOD_WINDOWS,
} from "../period-returns";
import type { TwrPoint } from "@/types/api";
import type { DatedValue } from "../risk-metrics";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** 40 calendar days of TWR, ~+0.5pp/day cumulative (fractions).
 *
 * 2026-06-11 Wave 3: NAV tracks the TWR (was a constant 100_000 placeholder).
 * A frozen NAV with a moving TWR is the stale-snapshot flow-artifact
 * signature that windowReturnFromTwrGuarded now suppresses — this fixture
 * must read as an honest flow-free series. */
function twrSeries(days: number, lastDate = "2026-06-10"): TwrPoint[] {
  const out: TwrPoint[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const twr = (days - 1 - i) * 0.005;
    out.push({
      date: isoDaysBefore(lastDate, i),
      twr_cum: twr,
      nav: 100_000 * (1 + twr),
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

// ── Flow-artifact detection (2026-06-11 Wave 3) ──────────────────────────────
//
// The fixture below reproduces the SHAPE of the live demo series
// (portfolio 01900000-…-0100, /twr?days=95, audited 2026-06-11) that made
// the Performance panel show 1D +23.97% / 3M +278.64% on a −4.6% book day:
//
//   - a long clean stretch (TWR and NAV move together),
//   - a funding day where NAV more than doubles AND the TWR jumps with it
//     (live: 2026-05-11, navΔ = twrΔ = +116.07% — flow counted as return),
//   - a frozen-NAV stretch (snapshots stale at the same 8-dp value) during
//     which the TWR still moves on two days (live: 2026-06-01 +1.11%,
//     2026-06-08 −2.09% — flows applied against stale snapshots),
//   - a final-day +23.97% jump (live: 2026-06-10 — another unadjusted flow).

/** Live-shaped sparse series: dates relative to lastDate, weekend-style gaps. */
function liveShapedSeries(): TwrPoint[] {
  const last = "2026-06-10";
  /** point helper: n days before `last`, cumulative twr FRACTION, nav. */
  const pt = (n: number, twr: number, nav: number): TwrPoint => ({
    date: isoDaysBefore(last, n),
    twr_cum: twr,
    nav,
  });
  return [
    // Clean early history (TWR ≙ NAV, small daily moves).
    pt(40, 0.0, 25_000),
    pt(39, 0.01, 25_250),
    pt(36, 0.02, 25_502.5), // gap = weekend
    pt(35, 0.015, 25_376.49),
    // FUNDING DAY: NAV ~doubles and the TWR matches it 1:1 — the live
    // +116% artifact signature (flow NOT removed from the sub-period).
    pt(34, 1.1, 52_500),
    // Frozen-NAV stretch: snapshots stale at the exact same value…
    pt(33, 1.1, 52_500),
    pt(30, 1.1, 52_500),
    // …during which the TWR "moves" anyway (flow on stale snapshots).
    pt(9, 1.12, 52_500),
    pt(8, 1.12, 52_500),
    pt(2, 1.12, 52_500),
    // Final-day artifact: +24% NAV jump fully counted as return (live 06-10).
    pt(1, 1.12, 52_500),
    pt(0, 1.6288, 65_100), // (2.6288/2.12)−1 ≈ +24%
  ];
}

describe("findFlowArtifactDates / isFlowArtifactInterval", () => {
  it("flags the funding-day, frozen-NAV and final-day artifacts in the live-shaped series", () => {
    const dates = findFlowArtifactDates(liveShapedSeries());
    expect(dates).toEqual([
      isoDaysBefore("2026-06-10", 34), // +116%-style funding day
      isoDaysBefore("2026-06-10", 9), // TWR moved on frozen NAV
      isoDaysBefore("2026-06-10", 0), // final-day +24% jump
    ]);
  });

  it("does NOT flag a correctly flow-adjusted deposit day (large navΔ, small twrΔ)", () => {
    // A $25k deposit handled correctly: NAV doubles, TWR barely moves.
    // The divergence between navΔ and twrΔ is EXPECTED here — flagging it
    // would suppress exactly the windows TWR exists to cover.
    const prev: TwrPoint = { date: "2026-06-01", twr_cum: 0.05, nav: 25_000 };
    const curr: TwrPoint = { date: "2026-06-02", twr_cum: 0.0605, nav: 50_250 };
    expect(isFlowArtifactInterval(prev, curr)).toBe(false);
  });

  it("does NOT flag identical NAV with an unchanged TWR (market holiday repeat)", () => {
    const prev: TwrPoint = { date: "2026-06-01", twr_cum: 0.05, nav: 25_000 };
    const curr: TwrPoint = { date: "2026-06-02", twr_cum: 0.05, nav: 25_000 };
    expect(isFlowArtifactInterval(prev, curr)).toBe(false);
  });

  it("returns [] for a clean series", () => {
    expect(findFlowArtifactDates(twrSeries(40))).toEqual([]);
  });

  it("does NOT flag a large move across a LONG sparse interval (2-point 30-day window)", () => {
    // The Analytics table fetches per-window series that can be as sparse as
    // 2 points spanning a month — +20% over 30 days is plausible market move,
    // not a daily-scale flow artifact. Rule 1 is span-gated at 5 days.
    const prev: TwrPoint = { date: "2026-05-11", twr_cum: 0, nav: 100 };
    const curr: TwrPoint = { date: "2026-06-10", twr_cum: 0.2, nav: 120 };
    expect(isFlowArtifactInterval(prev, curr)).toBe(false);
  });

  it("DOES flag the same magnitude across a 1-day interval (the live 06-10 case)", () => {
    const prev: TwrPoint = { date: "2026-06-09", twr_cum: 0, nav: 100 };
    const curr: TwrPoint = { date: "2026-06-10", twr_cum: 0.2, nav: 120 };
    expect(isFlowArtifactInterval(prev, curr)).toBe(true);
  });
});

describe("windowReturnFromTwrGuarded", () => {
  it("suppresses every window that contains an artifact (live 1D/1W/1M/3M case)", () => {
    const pts = liveShapedSeries();
    // 1D window: the final +24% jump is inside it.
    expect(windowReturnFromTwrGuarded(pts, 1)).toEqual({
      value: null,
      flowArtifact: true,
    });
    // 1W / 1M: include the frozen-NAV flow day and/or the final jump.
    expect(windowReturnFromTwrGuarded(pts, 7).flowArtifact).toBe(true);
    expect(windowReturnFromTwrGuarded(pts, 30).flowArtifact).toBe(true);
    // The raw (unguarded) value would have been the absurd +24% — pin that
    // the guard is what stands between the user and that number.
    expect(windowReturnFromTwr(pts, 1)).toBeCloseTo(0.2399, 3);
  });

  it("passes through clean windows untouched (value matches unguarded math)", () => {
    const pts = twrSeries(40);
    const guarded = windowReturnFromTwrGuarded(pts, 7);
    expect(guarded.flowArtifact).toBe(false);
    expect(guarded.value).toBeCloseTo(windowReturnFromTwr(pts, 7)!, 12);
  });

  it("keeps the coverage-gap null distinct from artifact suppression", () => {
    // 5 days of history cannot cover 30 days — null, but NOT an artifact.
    expect(windowReturnFromTwrGuarded(twrSeries(5), 30)).toEqual({
      value: null,
      flowArtifact: false,
    });
  });
});

describe("computePeriodReturns — artifact flag plumbing", () => {
  it("carries portfolioFlowArtifact per row and nulls excess for suppressed rows", () => {
    const pts = liveShapedSeries();
    const spy: DatedValue[] = pts.map((p, i) => ({
      date: p.date,
      value: 500 + i,
    }));
    const rows = computePeriodReturns(pts, spy);
    const oneD = rows.find((r) => r.label === "1D")!;
    expect(oneD.portfolio).toBeNull();
    expect(oneD.portfolioFlowArtifact).toBe(true);
    // SPY side is computed independently — the benchmark survives.
    expect(oneD.benchmark).not.toBeNull();
    // Excess requires both sides — suppressed portfolio nulls it.
    expect(oneD.excess).toBeNull();
  });

  it("clean series rows report portfolioFlowArtifact: false", () => {
    const rows = computePeriodReturns(twrSeries(40), undefined);
    for (const row of rows) {
      expect(row.portfolioFlowArtifact).toBe(false);
    }
  });
});
