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

import { buildChartRows, buildTwrChartRows } from "../AnalyticsTwrChart";
import type { DatedValue } from "@/features/portfolio/lib/risk-metrics";
import type { TwrPoint } from "@/types/api";

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

// ── buildTwrChartRows (2026-06-10 sprint gap #3 — flow-adjusted upgrade) ─────

describe("buildTwrChartRows", () => {
  // Server TWR series: already rebased (first point 0) — fractions.
  const TWR: TwrPoint[] = [
    { date: "2026-01-01", twr_cum: 0, nav: 100_000 },
    { date: "2026-01-02", twr_cum: 0.05, nav: 110_000 },
    { date: "2026-01-03", twr_cum: 0.05, nav: 121_000 }, // NAV moved on a flow day, TWR flat
  ];

  it("plots twr_cum AS-IS (no client-side re-rebase of an already-rebased series)", () => {
    const rows = buildTwrChartRows(TWR, false, { SPY: false, QQQ: false }, {});
    expect(rows.map((r) => r.portfolio)).toEqual([0, 0.05, 0.05]);
  });

  it("NAV toggle OFF → nav is null on every row (no hidden series in tooltips)", () => {
    const rows = buildTwrChartRows(TWR, false, { SPY: false, QQQ: false }, {});
    expect(rows.every((r) => r.nav === null)).toBe(true);
  });

  it("NAV toggle ON → nav line is the legacy V_t/V_0−1 approximation", () => {
    const rows = buildTwrChartRows(TWR, true, { SPY: false, QQQ: false }, {});
    expect(rows[0].nav).toBe(0);
    expect(rows[1].nav).toBeCloseTo(0.1, 12); // 110/100 − 1
    expect(rows[2].nav).toBeCloseTo(0.21, 12); // 121/100 − 1 — diverges from TWR (flows)
    // The divergence IS the point: TWR stays 0.05 while NAV says 0.21.
    expect(rows[2].portfolio).toBeCloseTo(0.05, 12);
  });

  it("benchmark overlays rebase on the TWR date grid (same rules as the legacy builder)", () => {
    const rows = buildTwrChartRows(TWR, false, { SPY: true, QQQ: false }, { SPY });
    expect(rows[0].spy).toBe(0);
    expect(rows[1].spy).toBeCloseTo(0.02, 12);
    expect(rows[2].spy).toBeCloseTo(0.04, 12);
    expect(rows.every((r) => r.qqq === null)).toBe(true);
  });

  it("returns [] for an empty TWR series (named empty state upstream)", () => {
    expect(buildTwrChartRows([], true, { SPY: true, QQQ: false }, { SPY })).toEqual([]);
  });
});
