/**
 * __tests__/screener-entity-id.test.ts — BP-326 regression: entity_id fallback
 *
 * WHY THIS EXISTS: BP-326 documented a bug where missing entity_id in the
 * backend response caused createScreenerApi.runScreener to synthesize a
 * "entity-{ticker-lc}" slug. That slug was never a real entity_id — the
 * backend emits UUIDv7 strings. Row-click navigation used entity_id as the
 * path segment so clicks led to /instruments/entity-aapl instead of
 * /instruments/<UUID>. The fix: fall back to String(instrument_id), not a slug.
 *
 * These tests lock in the corrected behaviour: when the backend response omits
 * entity_id, the transformer uses instrument_id as-is. When entity_id IS
 * present, it passes through unchanged. In neither case should a slug pattern
 * "entity-*" appear.
 *
 * DATA SOURCE: lib/api/screener.ts (createScreenerApi.runScreener)
 * DESIGN REFERENCE: PRD-0031 §7 screener, BP-326
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createScreenerApi } from "@/lib/api/screener";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeRawRow — minimal backend row shape. entity_id is optional to test the
 * fallback path.
 */
function makeRawRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    instrument_id: "01900000-0000-7000-8000-000000001001",
    ticker: "AAPL",
    name: "Apple Inc.",
    metrics: {},
    ...overrides,
  };
}

/**
 * mockFetch — replaces the global fetch so apiFetch returns our controlled
 * payload without hitting a real network endpoint.
 *
 * WHY global fetch mock (not MSW): these are pure unit tests for the
 * transformer logic in lib/api/screener.ts. MSW is heavier and tests the
 * network stack; we only care about the mapping function here.
 */
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

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("BP-326: entity_id fallback — never a slug, always a UUID or instrument_id string", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uses instrument_id when backend omits entity_id", async () => {
    const rawRow = makeRawRow();
    // entity_id is intentionally absent from the row
    mockFetch({ results: [rawRow], total: 1 });

    const api = createScreenerApi("test-token");
    const result = await api.runScreener({ filters: [], limit: 10, offset: 0 });

    expect(result.results).toHaveLength(1);
    // BP-326 fix: must equal the raw instrument_id string, NOT "entity-aapl"
    expect(result.results[0].entity_id).toBe("01900000-0000-7000-8000-000000001001");
    expect(result.results[0].entity_id).not.toMatch(/^entity-/);
  });

  it("passes through entity_id when the backend provides one", async () => {
    const entityId = "01900000-0000-7000-8000-000000009999";
    const rawRow = makeRawRow({ entity_id: entityId });
    mockFetch({ results: [rawRow], total: 1 });

    const api = createScreenerApi("test-token");
    const result = await api.runScreener({ filters: [], limit: 10, offset: 0 });

    expect(result.results[0].entity_id).toBe(entityId);
  });

  it("result entity_id never matches slug pattern entity-{ticker}", async () => {
    // Test with a variety of tickers to confirm no slug is ever synthesized
    const rows = [
      makeRawRow({ instrument_id: "uuid-001", ticker: "MSFT" }),
      makeRawRow({ instrument_id: "uuid-002", ticker: "GOOGL" }),
      makeRawRow({ instrument_id: "uuid-003", ticker: "TSLA" }),
    ];
    mockFetch({ results: rows, total: 3 });

    const api = createScreenerApi("test-token");
    const result = await api.runScreener({ filters: [], limit: 10, offset: 0 });

    for (const row of result.results) {
      expect(row.entity_id).not.toMatch(/^entity-/);
    }
  });
});
