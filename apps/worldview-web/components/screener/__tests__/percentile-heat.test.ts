/**
 * components/screener/__tests__/percentile-heat.test.ts
 *
 * WHY THIS FILE EXISTS (roadmap #5 / B3):
 *   Peer-percentile heat is a SILENT visual: a wrong percentile or an
 *   off-by-one in the alpha ramp would mis-rank a cell with no error and no
 *   obvious break — exactly the class of bug a unit test must catch. These tests
 *   pin the ranking maths, the visible-band floor, the peer-collection over the
 *   AG Grid API, and the toggle-store gating contract.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  percentileRank,
  peerHeatBackground,
  peerHeatStyle,
  collectColumnValues,
  setPeerHeatEnabled,
  isPeerHeatEnabled,
} from "@/components/screener/percentile-heat";

// ── percentileRank ─────────────────────────────────────────────────────────────

describe("percentileRank", () => {
  it("returns 0 for an empty or single-element cohort (no spread to rank)", () => {
    expect(percentileRank(5, [])).toBe(0);
    expect(percentileRank(5, [5])).toBe(0);
  });

  it("ranks the minimum at 0 and the maximum at 1", () => {
    const peers = [1, 2, 3, 4, 5];
    expect(percentileRank(1, peers)).toBe(0);
    expect(percentileRank(5, peers)).toBe(1);
  });

  it("ranks the median near 0.5", () => {
    const peers = [1, 2, 3, 4, 5];
    // 3 has 2 values below it of 4 others → 2/4 = 0.5
    expect(percentileRank(3, peers)).toBe(0.5);
  });

  it("uses strict-less so ties do not inflate rank", () => {
    // All equal: none is below any other → everyone ranks 0 (no standout).
    expect(percentileRank(7, [7, 7, 7, 7])).toBe(0);
  });
});

// ── peerHeatBackground ──────────────────────────────────────────────────────────

describe("peerHeatBackground", () => {
  it("paints nothing at or below the visible-band floor (top-half only)", () => {
    expect(peerHeatBackground(0)).toBeUndefined();
    expect(peerHeatBackground(0.5)).toBeUndefined();
  });

  it("paints an increasing alpha above the floor", () => {
    const mid = peerHeatBackground(0.75);
    const top = peerHeatBackground(1);
    expect(mid).toMatch(/^hsl\(240 5% 90% \/ /);
    expect(top).toMatch(/^hsl\(240 5% 90% \/ /);
    // Extract the alpha numbers and assert the ramp is monotonic increasing.
    const alpha = (s: string | undefined) => Number(s!.match(/\/ ([\d.]+)\)/)![1]);
    expect(alpha(top)).toBeGreaterThan(alpha(mid));
  });

  it("caps alpha at the documented ceiling (≈0.14) at the 100th percentile", () => {
    const alpha = Number(peerHeatBackground(1)!.match(/\/ ([\d.]+)\)/)![1]);
    expect(alpha).toBeLessThanOrEqual(0.14);
    expect(alpha).toBeGreaterThan(0.1);
  });
});

// ── toggle store + peerHeatStyle gating ────────────────────────────────────────

describe("peer-heat toggle store", () => {
  beforeEach(() => {
    setPeerHeatEnabled(false);
  });

  it("defaults the style to {} when heat is OFF (no wash unless opted in)", () => {
    setPeerHeatEnabled(false);
    expect(isPeerHeatEnabled()).toBe(false);
    // Even a top-percentile value gets no style while the toggle is off.
    expect(peerHeatStyle(100, [1, 2, 3, 100])).toEqual({});
  });

  it("emits a backgroundColor for a high-percentile value when heat is ON", () => {
    setPeerHeatEnabled(true);
    const style = peerHeatStyle(100, [1, 2, 3, 100]);
    expect(style.backgroundColor).toMatch(/^hsl\(240 5% 90% \//);
  });

  it("emits {} for a low-percentile value even when ON (top-half-only band)", () => {
    setPeerHeatEnabled(true);
    expect(peerHeatStyle(1, [1, 2, 3, 100])).toEqual({});
  });

  it("emits {} for a null/non-finite value when ON", () => {
    setPeerHeatEnabled(true);
    expect(peerHeatStyle(null, [1, 2, 3])).toEqual({});
    expect(peerHeatStyle(undefined, [1, 2, 3])).toEqual({});
    expect(peerHeatStyle(Number.NaN, [1, 2, 3])).toEqual({});
  });
});

// ── collectColumnValues ─────────────────────────────────────────────────────────

describe("collectColumnValues", () => {
  // Minimal fake of the bits of GridApi the function uses.
  type Row = { v: number | null };
  function fakeApi(rows: Row[]) {
    return {
      forEachNodeAfterFilter(cb: (node: { data: Row }) => void) {
        for (const r of rows) cb({ data: r });
      },
    } as unknown as Parameters<typeof collectColumnValues<Row>>[0];
  }

  it("returns [] when the api is null (renderer ran before grid-ready)", () => {
    expect(collectColumnValues<Row>(null, (r) => r.v)).toEqual([]);
  });

  it("collects only the finite, non-null values via the selector", () => {
    const api = fakeApi([{ v: 1 }, { v: null }, { v: 3 }, { v: Number.NaN }]);
    expect(collectColumnValues(api, (r) => r.v)).toEqual([1, 3]);
  });
});
