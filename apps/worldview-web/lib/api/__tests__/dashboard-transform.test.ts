/**
 * lib/api/__tests__/dashboard-transform.test.ts — transformTopMoversResponse
 *
 * WHY THIS EXISTS (Round 1 foundation): the top-movers wire→display transform
 * was previously inlined in getTopMovers() and untestable without mocking
 * apiFetch. It is now a pure exported function shared by getTopMovers AND
 * DashboardBundleHydrator — these tests pin the field mappings that broke
 * the dashboard before:
 *   - S3 period-movers rows carry `period_return_pct` at the TOP level
 *     (already percent units — must NOT be multiplied by 100).
 *   - Legacy screener rows carry `metrics.daily_return` as a DECIMAL fraction
 *     (MUST be multiplied by 100).
 *   - Directional filtering: gainers > 0, losers < 0, regardless of upstream.
 *   - Already-shaped `{movers}` responses pass through untouched.
 */

import { describe, it, expect } from "vitest";
import {
  transformTopMoversResponse,
  type RawTopMoversResponse,
} from "@/lib/api/dashboard";

describe("transformTopMoversResponse", () => {
  it("maps S3 period-movers rows (top-level period_return_pct, percent units)", () => {
    const raw: RawTopMoversResponse = {
      results: [
        {
          instrument_id: "ins-1",
          ticker: "NVDA",
          name: "NVIDIA Corp",
          period_return_pct: 5.2,
        },
      ],
      type: "gainers",
    };

    const out = transformTopMoversResponse(raw, "gainers");

    expect(out.type).toBe("gainers");
    expect(out.movers).toHaveLength(1);
    expect(out.movers[0].ticker).toBe("NVDA");
    expect(out.movers[0].name).toBe("NVIDIA Corp");
    // period_return_pct is ALREADY percent — 5.2 must stay 5.2, not 520.
    expect(out.movers[0].change_pct).toBe(5.2);
    // The movers feed has no price field — transform defaults to 0 and the
    // widgets patch a real price from the overview batch (never $0.00 in UI).
    expect(out.movers[0].price).toBe(0);
  });

  it("multiplies legacy screener metrics.daily_return fractions by 100", () => {
    const raw: RawTopMoversResponse = {
      results: [
        {
          instrument_id: "ins-2",
          ticker: "AAPL",
          name: "Apple Inc",
          // Legacy screener shape: decimal fraction nested under metrics.
          metrics: { daily_return: 0.031, close: 185.5 },
        },
      ],
    };

    const out = transformTopMoversResponse(raw, "gainers");

    expect(out.movers[0].change_pct).toBeCloseTo(3.1);
    // metrics.close is probed for price on the legacy path.
    expect(out.movers[0].price).toBe(185.5);
  });

  it("strictly filters wrong-direction rows per side (F-304 regression)", () => {
    const raw: RawTopMoversResponse = {
      results: [
        { instrument_id: "a", ticker: "UP", name: "Up", period_return_pct: 2.0 },
        { instrument_id: "b", ticker: "DN", name: "Down", period_return_pct: -1.5 },
        // Flat rows (0%) belong to NEITHER side.
        { instrument_id: "c", ticker: "FLAT", name: "Flat", period_return_pct: 0 },
      ],
    };

    const gainers = transformTopMoversResponse(raw, "gainers");
    const losers = transformTopMoversResponse(raw, "losers");

    expect(gainers.movers.map((m) => m.ticker)).toEqual(["UP"]);
    expect(losers.movers.map((m) => m.ticker)).toEqual(["DN"]);
  });

  it("passes through an already-shaped {movers} response untouched", () => {
    const shaped: RawTopMoversResponse = {
      movers: [
        {
          instrument_id: "ins-9",
          ticker: "TSLA",
          name: "Tesla Inc",
          price: 172.5,
          change_pct: -3.1,
          volume: null,
        },
      ],
      type: "losers",
    };

    const out = transformTopMoversResponse(shaped, "losers");

    // No re-filtering / re-mapping on the shaped path — S9 owns the contract.
    expect(out.movers).toEqual(shaped.movers);
    expect(out.type).toBe("losers");
  });

  it("returns an empty movers list for an empty/absent results array", () => {
    expect(transformTopMoversResponse({}, "gainers").movers).toEqual([]);
    expect(transformTopMoversResponse({ results: [] }, "losers").movers).toEqual([]);
  });
});
