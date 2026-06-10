/**
 * features/portfolio/components/__tests__/AnalyticsTwrChart.test.tsx (R2)
 *
 * WHY: buildChartRows is the merge point where the portfolio cumulative
 * return and the rebased benchmark overlays meet — the math each chart
 * pixel is drawn from. The lib primitives are unit-tested in
 * risk-metrics.test.ts; these tests pin the WIRING: toggles gate the
 * overlays, both series rebase to 0% at period start, and weekend gaps
 * carry forward.
 */

import { describe, it, expect } from "vitest";

import { buildChartRows } from "../AnalyticsTwrChart";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";

// ── Fixtures ──────────────────────────────────────────────────────────────────

// Portfolio: +10% then +21% cumulative.
const PORTFOLIO: DatedValue[] = [
  { date: "2026-01-01", value: 100_000 },
  { date: "2026-01-02", value: 110_000 },
  { date: "2026-01-03", value: 121_000 },
];

// SPY closes for the same window: +2% then +4% cumulative.
const SPY: DatedValue[] = [
  { date: "2026-01-01", value: 500 },
  { date: "2026-01-02", value: 510 },
  { date: "2026-01-03", value: 520 },
];

describe("buildChartRows", () => {
  it("rebases portfolio AND benchmark to 0% at period start", () => {
    const rows = buildChartRows(PORTFOLIO, { SPY: true, QQQ: false }, { SPY });

    // Both series start at exactly 0% — the comparability invariant.
    expect(rows[0].portfolio).toBe(0);
    expect(rows[0].spy).toBe(0);

    // Portfolio: 110/100−1 = +10%; 121/100−1 = +21%.
    expect(rows[1].portfolio).toBeCloseTo(0.1, 12);
    expect(rows[2].portfolio).toBeCloseTo(0.21, 12);

    // SPY: 510/500−1 = +2%; 520/500−1 = +4%.
    expect(rows[1].spy).toBeCloseTo(0.02, 12);
    expect(rows[2].spy).toBeCloseTo(0.04, 12);

    // QQQ overlay is off → null on every row (recharts simply omits it).
    expect(rows.every((r) => r.qqq === null)).toBe(true);
  });

  it("omits the overlay when the toggle is off EVEN IF closes exist", () => {
    const rows = buildChartRows(PORTFOLIO, { SPY: false, QQQ: false }, { SPY });
    expect(rows.every((r) => r.spy === null)).toBe(true);
  });

  it("renders null overlay (never fake values) when closes are missing", () => {
    // Toggle ON but no QQQ data fetched yet / unavailable.
    const rows = buildChartRows(PORTFOLIO, { SPY: true, QQQ: true }, { SPY });
    expect(rows.every((r) => r.qqq === null)).toBe(true);
  });

  it("carries benchmark closes forward across non-trading-day snapshots", () => {
    // Portfolio snapshot exists on the 03rd (Sat) but SPY has no close —
    // the overlay reuses Friday's close, so spy cum-return stays +2%.
    const spyWithGap: DatedValue[] = [
      { date: "2026-01-01", value: 500 },
      { date: "2026-01-02", value: 510 },
      // no close on 2026-01-03
    ];
    const rows = buildChartRows(PORTFOLIO, { SPY: true, QQQ: false }, { SPY: spyWithGap });
    expect(rows[2].spy).toBeCloseTo(0.02, 12);
  });

  it("returns [] for an empty/un-rebasable portfolio series", () => {
    expect(buildChartRows([], { SPY: true, QQQ: false }, { SPY })).toEqual([]);
    expect(
      buildChartRows(
        [{ date: "2026-01-01", value: 0 }], // base 0 — cannot rebase
        { SPY: true, QQQ: false },
        { SPY },
      ),
    ).toEqual([]);
  });
});
