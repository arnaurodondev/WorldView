/**
 * lib/api/__tests__/screener-fields.test.ts — regression tests for
 * createScreenerApi().getScreenerFields() (PLAN-0113 alerts QA, 2026-06-20).
 *
 * WHY THESE TESTS EXIST:
 * The live S3 endpoint `/v1/fundamentals/screen/fields` returns a WRAPPED
 * envelope `{ "fields": [...] }` and each field uses `"type": "numeric"` (not
 * `"number"`). The frontend `ScreenerField` contract — and the alert wizard's
 * `MetricPicker`, the sole consumer — expects a FLAT `ScreenerField[]` whose
 * numeric fields are `type === "number"`. Before the unwrap+normalise fix,
 * `getScreenerFields` returned the raw object, so `MetricPicker`'s
 * `(data ?? []).filter(f => f.type === "number")` ran on a dict and produced
 * ZERO options → FUNDAMENTAL_CROSS alert rules could never be created.
 *
 * These tests pin: (1) the envelope is unwrapped, (2) "numeric" → "number",
 * (3) a bare-array backend response still works (forward-compat).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createScreenerApi } from "../screener";

/** Replace global fetch with a spy returning the given JSON body at 200. */
function mockFetch(body: unknown) {
  const mockResponse = {
    ok: true,
    status: 200,
    statusText: "OK",
    json: () => Promise.resolve(body),
    body: null,
  };
  return vi
    .spyOn(global, "fetch")
    .mockResolvedValue(mockResponse as unknown as Response);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("getScreenerFields() — envelope + type normalisation", () => {
  it("unwraps the {fields:[...]} envelope and maps 'numeric' → 'number'", async () => {
    // Shape mirrors the LIVE backend response (verified 2026-06-20).
    mockFetch({
      fields: [
        {
          name: "pe_ratio",
          label: "P/E Ratio",
          type: "numeric",
          unit: "x",
          description: "Trailing P/E (TTM)",
        },
        {
          name: "gics_sector",
          label: "Sector",
          type: "string",
          description: null,
        },
      ],
    });

    const api = createScreenerApi("t");
    const fields = await api.getScreenerFields();

    expect(Array.isArray(fields)).toBe(true);
    expect(fields).toHaveLength(2);
    // The numeric field must surface as "number" so MetricPicker keeps it.
    const pe = fields.find((f) => f.name === "pe_ratio");
    expect(pe?.type).toBe("number");
    expect(pe?.label).toBe("P/E Ratio");
    // String fields pass through unchanged (MetricPicker filters them out).
    expect(fields.find((f) => f.name === "gics_sector")?.type).toBe("string");
  });

  it("yields at least one 'number' field MetricPicker can render from live shape", async () => {
    mockFetch({
      fields: [{ name: "pe_ratio", label: "P/E", type: "numeric", description: null }],
    });
    const fields = await createScreenerApi("t").getScreenerFields();
    // This is exactly MetricPicker's filter — it must be non-empty.
    expect(fields.filter((f) => f.type === "number").length).toBeGreaterThan(0);
  });

  it("tolerates a bare-array response (forward-compat, no envelope)", async () => {
    mockFetch([
      { name: "roe", label: "ROE", type: "numeric", description: null },
    ]);
    const fields = await createScreenerApi("t").getScreenerFields();
    expect(fields).toHaveLength(1);
    expect(fields[0]?.type).toBe("number");
  });

  it("defaults operators to [] when the backend omits them", async () => {
    mockFetch({ fields: [{ name: "pe_ratio", label: "P/E", type: "numeric" }] });
    const fields = await createScreenerApi("t").getScreenerFields();
    expect(fields[0]?.operators).toEqual([]);
  });
});
