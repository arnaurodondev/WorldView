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
  // Wave-2 (2026-06-10): + volume, high_52w, low_52w (new flat backend fields)
  // — they must obey the same null contract as every other metric.
  const METRIC_FIELDS = [
    "current_price", "market_cap", "pe_ratio", "daily_return", "revenue",
    "beta", "market_impact_score", "avg_volume_30d", "forward_pe",
    "dividend_yield", "roe", "operating_margin", "revenue_growth_yoy",
    "dist_from_52w_high_pct", "dist_from_52w_low_pct", "return_1m",
    "return_3m", "return_6m", "return_ytd", "return_1y", "return_3y",
    "analyst_target_price", "analyst_consensus_rating", "insider_net_buy_90d",
    "institutional_ownership_pct", "short_percent", "news_count_7d",
    "llm_relevance_7d_max", "display_relevance_7d_weighted",
    "recent_contradiction_count", "volume", "high_52w", "low_52w",
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

// ── Wave-2 (2026-06-10): flat backend payload — new fields + POST-always ─────
//
// WHY THIS BLOCK: the Wave-1 backend rework changed the screener contract in
// three load-bearing ways the transformer must consume:
//   1. Rows are FLAT (no nested `metrics` dict) — the row[...] ?? metrics[...]
//      chains must resolve flat keys.
//   2. Three new fields ship on every row: `volume` (latest 1d bar volume),
//      `high_52w` / `low_52w` (absolute 52-week range prices).
//   3. GET /v1/fundamentals/screen was REMOVED from the gateway (the path now
//      falls into /{instrument_id} and 422s) — runScreener must POST for
//      EVERY request shape, including the legacy "default filter" shape that
//      used to trigger the GET branch.

describe("Wave-2: flat payload mapping (volume / high_52w / low_52w)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  /** A realistic Wave-1 backend row: flat, no `metrics` dict at all. */
  function flatRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    const row = baseRow(overrides);
    delete (row as Record<string, unknown>).metrics;
    return row;
  }

  it("maps the flat `volume` field (latest 1d bar volume)", async () => {
    mockFetch({ results: [flatRow({ volume: 62_969 })], total: 1 });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].volume).toBe(62_969);
  });

  it("maps flat high_52w / low_52w (absolute 52-week range prices)", async () => {
    mockFetch({
      results: [flatRow({ high_52w: 236.2647, low_52w: 140.6677 })],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].high_52w).toBe(236.2647);
    expect(result.results[0].low_52w).toBe(140.6677);
  });

  it("keeps volume and avg_volume_30d as DISTINCT fields (brightness ratio inputs)", async () => {
    // The VOLUME column displays `volume` and dims/brightens on the
    // volume / avg_volume_30d ratio — a transformer that collapsed the two
    // keys would silently break the brightness signal.
    mockFetch({
      results: [flatRow({ volume: 50_000, avg_volume_30d: 1_000_000 })],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({ filters: [], limit: 1, offset: 0 });

    expect(result.results[0].volume).toBe(50_000);
    expect(result.results[0].avg_volume_30d).toBe(1_000_000);
  });

  it("maps the full key-metrics set on a FILTERED-view-shaped flat row", async () => {
    // Wave-1's headline fix: filtered responses now carry the FULL key-metrics
    // set, not just the filtered metric. Simulate a row as returned for a
    // pe_ratio filter (live-verified shape, 2026-06-10) and assert every
    // column-backing field lands flattened — this is the regression test for
    // "apply a P/E filter and every other column blanks to —".
    mockFetch({
      results: [
        flatRow({
          pe_ratio: 39.8889,           // the filtered metric…
          market_cap: 176_661_676_032, // …plus everything else:
          revenue: 25_903_800_320,
          beta: 1.275,
          roe: 0.3683,
          operating_margin: 0.2731,
          revenue_growth_yoy: 0.584,
          dividend_yield: 0.006,
          forward_pe: 27.933,
          dist_from_52w_high_pct: -0.228373,
          dist_from_52w_low_pct: 0.526596,
          high_52w: 166.7105,
          low_52w: 90.9661,
          volume: 4_987,
          avg_volume_30d: 7_897_136,
          analyst_target_price: 182.2778,
          news_count_7d: 1,
        }),
      ],
      total: 1,
    });

    const api = createScreenerApi("token");
    const result = await api.runScreener({
      filters: [{ metric: "pe_ratio", min_value: 5, max_value: 40 }],
      limit: 1,
      offset: 0,
    });

    const row = result.results[0];
    expect(row.pe_ratio).toBe(39.8889);
    expect(row.market_cap).toBe(176_661_676_032);
    expect(row.revenue).toBe(25_903_800_320);
    expect(row.beta).toBe(1.275);
    expect(row.roe).toBe(0.3683);
    expect(row.operating_margin).toBe(0.2731);
    expect(row.revenue_growth_yoy).toBe(0.584);
    expect(row.dividend_yield).toBe(0.006);
    expect(row.forward_pe).toBe(27.933);
    expect(row.dist_from_52w_high_pct).toBe(-0.228373);
    expect(row.dist_from_52w_low_pct).toBe(0.526596);
    expect(row.high_52w).toBe(166.7105);
    expect(row.low_52w).toBe(90.9661);
    expect(row.volume).toBe(4_987);
    expect(row.avg_volume_30d).toBe(7_897_136);
    expect(row.analyst_target_price).toBe(182.2778);
    expect(row.news_count_7d).toBe(1);
  });
});

describe("Wave-2: runScreener ALWAYS POSTs (GET route removed from gateway)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs even for the legacy default-filter shape that used to take the GET branch", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ results: [], total: 0 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const api = createScreenerApi("token");
    // EXACTLY the shape the old isDefaultFilter check matched:
    // one market_capitalization filter, min 0, no max, no sector.
    await api.runScreener({
      filters: [{ metric: "market_capitalization", min_value: 0 }],
      limit: 50,
      offset: 0,
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    // POST to the bare /screen path — never the old GET querystring form
    // (which now 422s against GET /v1/fundamentals/{instrument_id}).
    expect(init.method).toBe("POST");
    expect(url).toContain("/v1/fundamentals/screen");
    expect(url).not.toContain("/screen?");
  });

  it("POSTs for the empty-filters default view (filters: [])", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ results: [], total: 0 }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    const api = createScreenerApi("token");
    await api.runScreener({ filters: [], limit: 50, offset: 0 });

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    // The request body must carry filters: [] — the backend's optimised
    // no-filter path keys off it.
    expect(JSON.parse(String(init.body))).toMatchObject({ filters: [] });
  });
});
