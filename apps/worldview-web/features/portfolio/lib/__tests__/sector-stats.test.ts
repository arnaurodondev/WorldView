/**
 * features/portfolio/lib/__tests__/sector-stats.test.ts
 * (2026-06-10 sprint, Wave 2 — SectorExposurePanel day-change join.)
 *
 * WHY: computeSectorStats joins server segments to live quotes by exact
 * instrument UUID (sprint gap #2). The critical contracts are the null
 * paths — "we don't know" must surface as null (rendered "—"), never as a
 * fabricated $0.00.
 */

import { describe, it, expect } from "vitest";

import { computeSectorStats, sectorIdMapFromSegments } from "../sector-stats";
import type { Holding, SectorBreakdownSegment } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function holding(id: string, qty: number): Holding {
  return {
    holding_id: `h-${id}`,
    portfolio_id: "p1",
    instrument_id: id,
    entity_id: `e-${id}`,
    ticker: id.toUpperCase(),
    name: id,
    quantity: qty,
    average_cost: 100,
  };
}

const SEGMENTS: SectorBreakdownSegment[] = [
  {
    sector: "Technology",
    weight: 0.6,
    count: 2,
    market_value: 60_000,
    instrument_ids: ["aapl", "msft"],
  },
  {
    sector: "Financial Services",
    weight: 0.4,
    count: 1,
    market_value: 40_000,
    instrument_ids: ["jpm"],
  },
];

const HOLDINGS = [holding("aapl", 10), holding("msft", 5), holding("jpm", 20)];

describe("computeSectorStats", () => {
  it("sums quote.change × quantity per segment by exact instrument ID", () => {
    const rows = computeSectorStats(SEGMENTS, HOLDINGS, {
      aapl: { change: 2 }, // +$20
      msft: { change: -1 }, // -$5
      jpm: { change: 0.5 }, // +$10
    });

    expect(rows).toHaveLength(2);
    expect(rows[0].sector).toBe("Technology");
    expect(rows[0].dayChangeValue).toBeCloseTo(15, 12); // 20 − 5
    expect(rows[1].dayChangeValue).toBeCloseTo(10, 12);

    // Day % uses yesterday's base: 15 / (60000 − 15).
    expect(rows[0].dayChangePct).toBeCloseTo(15 / 59_985, 12);

    // Server fields pass through untouched.
    expect(rows[0].weight).toBe(0.6);
    expect(rows[0].marketValue).toBe(60_000);
  });

  it("returns null day change when the segment has NO instrument_ids (old S9 build)", () => {
    const legacySegments: SectorBreakdownSegment[] = [
      { sector: "Technology", weight: 1, count: 2, market_value: 100_000 },
    ];
    const rows = computeSectorStats(legacySegments, HOLDINGS, {
      aapl: { change: 2 },
    });
    expect(rows[0].dayChangeValue).toBeNull();
    expect(rows[0].dayChangePct).toBeNull();
  });

  it("returns null when no quote in the segment has a change yet (pre-open)", () => {
    const rows = computeSectorStats(SEGMENTS, HOLDINGS, {
      aapl: { change: null },
      msft: { change: undefined },
    });
    expect(rows[0].dayChangeValue).toBeNull();
  });

  it("a genuine $0.00 flat day stays 0 (NOT null) when a real change exists", () => {
    const rows = computeSectorStats(SEGMENTS, HOLDINGS, {
      aapl: { change: 0 },
    });
    expect(rows[0].dayChangeValue).toBe(0);
  });

  it("ignores segment IDs with no matching holding row (sold position, stale cache)", () => {
    const rows = computeSectorStats(SEGMENTS, [holding("aapl", 10)], {
      aapl: { change: 2 },
      msft: { change: 100 }, // no holding row — must not contribute
    });
    expect(rows[0].dayChangeValue).toBeCloseTo(20, 12);
  });
});

describe("sectorIdMapFromSegments", () => {
  it("maps sector → instrument_ids, skipping ID-less segments", () => {
    const map = sectorIdMapFromSegments([
      ...SEGMENTS,
      { sector: "Unknown", weight: 0, count: 0, market_value: 0 },
    ]);
    expect(map["Technology"]).toEqual(["aapl", "msft"]);
    expect(map["Financial Services"]).toEqual(["jpm"]);
    expect(map["Unknown"]).toBeUndefined();
  });

  it("returns {} for undefined segments (breakdown still loading)", () => {
    expect(sectorIdMapFromSegments(undefined)).toEqual({});
  });
});
