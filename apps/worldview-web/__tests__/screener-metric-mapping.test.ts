/**
 * __tests__/screener-metric-mapping.test.ts — BP-327 + metric fallbacks
 *
 * WHY THIS EXISTS: The backend API response shape has evolved over time:
 *   - BP-327: revenue is nested as metrics.revenue_usd, not top-level revenue
 *   - Sector field is named "sector" on the backend but "gics_sector" on ScreenerResult
 *   - Multiple fallback keys must be tried in the right priority order
 *
 * Without these tests, a backend rename silently breaks the column renderer —
 * the UI shows "—" for every row and no error is thrown. These tests lock in
 * the priority order and fallback chain for each mapped field.
 *
 * DATA SOURCE: lib/api/screener.ts (createScreenerApi.runScreener transformer)
 * DESIGN REFERENCE: PRD-0031 §7, BP-327
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createScreenerApi } from "@/lib/api/screener";

// ── Helpers ───────────────────────────────────────────────────────────────────

function mockFetch(payload: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
  );
}

function baseRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    instrument_id: "01900000-0000-7000-8000-000000001001",
    entity_id: "01900000-0000-7000-8000-000000001001",
    ticker: "AAPL",
    name: "Apple Inc.",
    metrics: {},
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("BP-327: revenue_usd metric key takes priority over generic revenue fallback", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("maps metrics.revenue_usd to the revenue field (primary key)", async () => {
    mockFetch({
      results: [
        baseRow({
          metrics: { revenue_usd: 394_330_000_000 },
        }),
      ],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].revenue).toBe(394_330_000_000);
  });

  it("falls back to metrics.revenue when revenue_usd is absent", async () => {
    mockFetch({
      results: [
        baseRow({
          metrics: { revenue: 150_000_000_000 },
        }),
      ],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].revenue).toBe(150_000_000_000);
  });

  it("falls back to top-level row.revenue when neither metric key exists", async () => {
    mockFetch({
      results: [
        baseRow({
          revenue: 75_000_000_000,
          metrics: {},
        }),
      ],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].revenue).toBe(75_000_000_000);
  });

  it("returns null when all revenue keys are absent", async () => {
    mockFetch({ results: [baseRow({ metrics: {} })], total: 1 });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].revenue).toBeNull();
  });
});

describe("Sector field: backend 'sector' maps to frontend gics_sector", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uses gics_sector when the backend provides it (preferred key)", async () => {
    mockFetch({
      results: [
        baseRow({ gics_sector: "Information Technology", sector: "Technology" }),
      ],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].gics_sector).toBe("Information Technology");
  });

  it("falls back to sector when gics_sector is absent", async () => {
    mockFetch({
      results: [baseRow({ sector: "Technology" })],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].gics_sector).toBe("Technology");
  });

  it("returns null when both sector keys are absent", async () => {
    mockFetch({ results: [baseRow()], total: 1 });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].gics_sector).toBeNull();
  });
});
