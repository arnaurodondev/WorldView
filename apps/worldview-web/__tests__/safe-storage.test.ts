/**
 * __tests__/safe-storage.test.ts — PLAN-0059-C C-4 corruption-safe storage.
 *
 * COVERS the C-4 critical test:
 *   - test_safe_storage_zod_validates_on_read
 *     → corrupted JSON returns the default value instead of throwing.
 *     → invalid shape (validator returns null) returns the default.
 *     → valid stored value round-trips.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  safeStorage,
  isBoolean,
  isFiniteNumber,
  isString,
  isStringEnum,
} from "@/lib/storage/safe-storage";

beforeEach(() => {
  // jsdom's localStorage is shared across tests; clear before each.
  window.localStorage.clear();
});

describe("safeStorage.get", () => {
  it("returns default when key is missing", () => {
    expect(safeStorage.get("missing", isBoolean, true)).toBe(true);
    expect(safeStorage.get("missing", isFiniteNumber, 42)).toBe(42);
  });

  it("returns the stored value after a round trip", () => {
    safeStorage.set("k.bool", false);
    expect(safeStorage.get("k.bool", isBoolean, true)).toBe(false);

    safeStorage.set("k.num", 280);
    expect(safeStorage.get("k.num", isFiniteNumber, 0)).toBe(280);
  });

  it("returns default when JSON is corrupt (does not throw)", () => {
    // Simulate a DevTools edit that left non-JSON garbage in the slot.
    window.localStorage.setItem("k.corrupt", "{not json[");
    const out = safeStorage.get("k.corrupt", isString, "fallback");
    expect(out).toBe("fallback");
  });

  it("returns default when validator rejects the parsed shape", () => {
    // Stored value parses as JSON but is the wrong type for the validator.
    window.localStorage.setItem("k.shape", JSON.stringify({ x: 1 }));
    const out = safeStorage.get("k.shape", isFiniteNumber, 99);
    expect(out).toBe(99);
  });

  it("rejects NaN and Infinity via isFiniteNumber", () => {
    // A naive parseFloat would let NaN through and produce a zero-width sidebar.
    window.localStorage.setItem("k.nan", JSON.stringify("abc"));
    expect(safeStorage.get("k.nan", isFiniteNumber, 220)).toBe(220);
  });

  it("isStringEnum accepts only known values", () => {
    const validate = isStringEnum(["1D", "1W", "1M"] as const);
    safeStorage.set("k.period", "1W");
    expect(safeStorage.get("k.period", validate, "1D")).toBe("1W");

    safeStorage.set("k.period", "9X");
    expect(safeStorage.get("k.period", validate, "1D")).toBe("1D");
  });
});

describe("safeStorage.set / remove", () => {
  it("set returns true on success and writes JSON", () => {
    expect(safeStorage.set("k", { a: 1 })).toBe(true);
    expect(window.localStorage.getItem("k")).toBe('{"a":1}');
  });

  it("remove deletes the key", () => {
    safeStorage.set("k", "v");
    safeStorage.remove("k");
    expect(window.localStorage.getItem("k")).toBeNull();
  });
});
