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

// ── Round-4 item 1: malformed/partial rows — API-layer null contract ──────────
//
// WHY THIS BLOCK: the page-level test (screener-null-safety.test.tsx) proves
// the RENDERERS tolerate null metric fields; this block proves the API layer
// actually PRODUCES nulls (never undefined-vs-NaN surprises) for the two
// malformed shapes the backend can emit: `metrics: {}` and a missing metrics
// key entirely. Together they guarantee "metrics:{} renders dashes, not
// throws" end-to-end.

describe("Round-4: empty/missing metrics dict maps every metric field to null", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // Every numeric ScreenerResult field the transformer derives from `metrics`.
  const METRIC_FIELDS = [
    "current_price", "market_cap", "pe_ratio", "daily_return", "revenue",
    "beta", "market_impact_score", "avg_volume_30d", "forward_pe",
    "dividend_yield", "roe", "operating_margin", "revenue_growth_yoy",
    "dist_from_52w_high_pct", "dist_from_52w_low_pct", "return_1m",
    "return_3m", "return_6m", "return_ytd", "return_1y", "return_3y",
    "analyst_target_price", "analyst_consensus_rating", "insider_net_buy_90d",
    "institutional_ownership_pct", "short_percent", "news_count_7d",
    "llm_relevance_7d_max", "display_relevance_7d_weighted",
    "recent_contradiction_count",
  ] as const;

  it("metrics:{} → null on every metric field (renderers then show dashes)", async () => {
    mockFetch({ results: [baseRow({ metrics: {} })], total: 1 });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });
    const row = result.results[0] as unknown as Record<string, unknown>;

    for (const field of METRIC_FIELDS) {
      // toBeNull (not toBeUndefined/NaN): the renderers' `v == null` guards
      // cover null AND undefined, but the num() contract is explicit null —
      // NaN would leak "NaN%" strings into toFixed() outputs.
      expect(row[field], `field ${field} should be null`).toBeNull();
    }
    // Identity fields stay intact so the row is still navigable/renderable.
    expect(row.ticker).toBe("AAPL");
    expect(row.instrument_id).toBe("01900000-0000-7000-8000-000000001001");
  });

  it("missing metrics key entirely → still null on every metric field (no throw)", async () => {
    const rowWithoutMetrics = baseRow();
    delete (rowWithoutMetrics as Record<string, unknown>).metrics;
    mockFetch({ results: [rowWithoutMetrics], total: 1 });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });
    const row = result.results[0] as unknown as Record<string, unknown>;

    for (const field of METRIC_FIELDS) {
      expect(row[field], `field ${field} should be null`).toBeNull();
    }
  });

  it("non-numeric metric garbage ('N/A', '') coerces to null, not NaN", async () => {
    // Backend bugs occasionally emit placeholder strings; num() must reject
    // them (Number('N/A') is NaN; Number('') is 0 — both wrong as data).
    mockFetch({
      results: [baseRow({ metrics: { pe_ratio: "N/A", market_cap: "" } })],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].pe_ratio).toBeNull();
    expect(result.results[0].market_cap).toBeNull();
  });
});
