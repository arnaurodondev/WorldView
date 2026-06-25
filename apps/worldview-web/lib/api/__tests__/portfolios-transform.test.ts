/**
 * lib/api/__tests__/portfolios-transform.test.ts
 * (2026-06-10 sprint, Wave 2 — portfolio API boundary transforms.)
 *
 * WHY: three wire→display transforms changed this sprint and each has a
 * unit-trap baked in:
 *   - getTwr: `twr_cum_pct` arrives in PERCENT units (4.21 = +4.21%) and
 *     `nav` as an 8-dp Decimal string — both converted at the boundary so
 *     consumers stay on the codebase-wide fraction/number conventions.
 *   - getHoldings: `asset_class` (sprint gap #1) must pass through with
 *     strict null preservation (absent/null → null, never a default).
 *   - getExposure: `buying_power` (sprint gap #5) parses Decimal strings
 *     and preserves null for older S9 builds.
 *
 * MOCKED: apiFetch — these are pure transform tests, no HTTP.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

const mockApiFetch = vi.fn();
vi.mock("@/lib/api/_client", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
  GatewayError: class GatewayError extends Error {},
}));

import { createPortfoliosApi } from "@/lib/api/portfolios";

const api = createPortfoliosApi("test-token");

beforeEach(() => {
  mockApiFetch.mockReset();
});

describe("getTwr — flow-adjusted TWR transform", () => {
  it("converts twr_cum_pct (percent) → twr_cum (fraction) and parses nav strings", async () => {
    mockApiFetch.mockResolvedValue({
      portfolio_id: "p-1",
      from_date: "2026-05-12",
      to_date: "2026-06-10",
      points: [
        { date: "2026-05-12", twr_cum_pct: 0.0, nav: "56316.70000000" },
        { date: "2026-06-10", twr_cum_pct: 242.47871, nav: "69816.97000000" },
      ],
      flow_days: 5,
    });

    const out = await api.getTwr("p-1", 30);

    // Path + days param hit the right endpoint.
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/v1/portfolios/p-1/twr?days=30",
      expect.objectContaining({ token: "test-token" }),
    );

    expect(out.flow_days).toBe(5);
    expect(out.points[0].twr_cum).toBe(0); // first point rebased to 0
    // PERCENT → FRACTION: 242.47871% → 2.4247871 (NOT 242.47871).
    expect(out.points[1].twr_cum).toBeCloseTo(2.4247871, 10);
    expect(out.points[1].nav).toBeCloseTo(69_816.97, 6);
  });

  it("omits the days param when not supplied (server default window)", async () => {
    mockApiFetch.mockResolvedValue({
      portfolio_id: "p-1",
      from_date: "x",
      to_date: "y",
      points: [],
      flow_days: 0,
    });
    await api.getTwr("p-1");
    expect(mockApiFetch).toHaveBeenCalledWith(
      "/v1/portfolios/p-1/twr",
      expect.anything(),
    );
  });

  it("defaults points to [] only when the server omitted the field", async () => {
    mockApiFetch.mockResolvedValue({
      portfolio_id: "p-1",
      from_date: "x",
      to_date: "y",
      flow_days: 0,
    });
    const out = await api.getTwr("p-1", 7);
    expect(out.points).toEqual([]);
  });
});

describe("getHoldings — asset_class pass-through (sprint gap #1)", () => {
  const RAW_HOLDING = {
    id: "h-1",
    portfolio_id: "p-1",
    instrument_id: "i-1",
    quantity: "10.00000000",
    average_cost: "170.00000000",
    currency: "USD",
    ticker: "AAPL",
    name: "Apple Inc.",
    entity_id: "e-1",
  };

  it("forwards the server-side asset_class", async () => {
    mockApiFetch.mockResolvedValue({
      items: [{ ...RAW_HOLDING, asset_class: "equity" }],
      total: 1,
      limit: 100,
      offset: 0,
    });
    const out = await api.getHoldings("p-1");
    expect(out.holdings[0].asset_class).toBe("equity");
  });

  it("preserves null/absent asset_class as null (renders '—', never a default)", async () => {
    mockApiFetch.mockResolvedValue({
      items: [RAW_HOLDING, { ...RAW_HOLDING, id: "h-2", asset_class: null }],
      total: 2,
      limit: 100,
      offset: 0,
    });
    const out = await api.getHoldings("p-1");
    expect(out.holdings[0].asset_class).toBeNull(); // absent on the wire
    expect(out.holdings[1].asset_class).toBeNull(); // explicit null
  });
});

describe("getExposure — buying_power parse (sprint gap #5)", () => {
  const RAW_EXPOSURE = {
    invested: "73302.53000000",
    cash: "1500.00000000",
    gross_exposure_pct: "1.00000000",
    net_exposure_pct: "1.00000000",
    leverage: "1.30161267",
  };

  it("parses the Decimal-string buying_power to a number", async () => {
    mockApiFetch.mockResolvedValue({
      ...RAW_EXPOSURE,
      buying_power: "1500.00000000",
    });
    const out = await api.getExposure("p-1");
    expect(out.buying_power).toBeCloseTo(1500, 8);
    expect(out.invested).toBeCloseTo(73_302.53, 6);
  });

  it("preserves null buying_power for older S9 builds (cash fallback is the caller's)", async () => {
    mockApiFetch.mockResolvedValue(RAW_EXPOSURE);
    const out = await api.getExposure("p-1");
    expect(out.buying_power).toBeNull();
  });
});
