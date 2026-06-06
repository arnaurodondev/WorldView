/**
 * __tests__/lib/eohdUtils.test.ts
 *
 * WHY THIS EXISTS: Pins the isDictOfDicts contract across all edge cases that
 * EODHD can return for holder/transaction endpoints. The previous per-component
 * copies mishandled {"0": {}} (empty-object first value) — this test suite
 * ensures the shared implementation rejects every malformed input.
 */

import { describe, it, expect } from "vitest";
import { isDictOfDicts } from "@/lib/eohdUtils";

describe("isDictOfDicts", () => {
  // ── Falsy / non-object inputs ────────────────────────────────────────────

  it("returns false for null", () => expect(isDictOfDicts(null)).toBe(false));
  it("returns false for undefined", () => expect(isDictOfDicts(undefined)).toBe(false));
  it("returns false for a string", () => expect(isDictOfDicts("hello")).toBe(false));
  it("returns false for a number", () => expect(isDictOfDicts(42)).toBe(false));
  it("returns false for a boolean", () => expect(isDictOfDicts(true)).toBe(false));
  it("returns false for an array", () => expect(isDictOfDicts([])).toBe(false));
  it("returns false for a non-empty array", () => expect(isDictOfDicts([{ name: "X" }])).toBe(false));

  // ── Empty / degenerate object inputs ────────────────────────────────────

  it("returns false for {} (empty dict)", () => {
    // EODHD returns {} when no filings are available for the ticker.
    expect(isDictOfDicts({})).toBe(false);
  });

  it("returns false for {\"0\": null} (null first value)", () => {
    // EODHD occasionally returns null placeholders in sparse sections.
    expect(isDictOfDicts({ "0": null })).toBe(false);
  });

  it("returns false for {\"0\": {}} (empty-object first value)", () => {
    // KEY edge case: filter(Boolean) would retain {} (truthy), producing an
    // all-dash row. isDictOfDicts must reject this so the component falls
    // through to the empty-state branch.
    expect(isDictOfDicts({ "0": {} })).toBe(false);
  });

  it("returns false for {\"0\": \"string\"} (scalar first value)", () => {
    expect(isDictOfDicts({ "0": "string" })).toBe(false);
  });

  it("returns false for {\"0\": 123} (numeric first value)", () => {
    expect(isDictOfDicts({ "0": 123 })).toBe(false);
  });

  it("returns false for {\"result\": false} (boolean first value)", () => {
    expect(isDictOfDicts({ result: false })).toBe(false);
  });

  // ── Valid dict-of-dicts inputs ────────────────────────────────────────────

  it("returns true for a single-entry dict with a populated object value", () => {
    expect(isDictOfDicts({ "0": { name: "Vanguard" } })).toBe(true);
  });

  it("returns true for a multi-entry dict (EODHD standard format)", () => {
    const input = {
      "0": { ownerName: "Tim Cook", transactionCode: "S" },
      "1": { ownerName: "Luca Maestri", transactionCode: "P" },
    };
    expect(isDictOfDicts(input)).toBe(true);
  });

  it("returns true even when later values are empty if first is populated", () => {
    // Only the first value is checked (fast path for real EODHD data).
    expect(isDictOfDicts({ "0": { name: "X" }, "1": {} })).toBe(true);
  });
});
