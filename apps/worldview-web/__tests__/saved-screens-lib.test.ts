/**
 * __tests__/saved-screens-lib.test.ts — CRUD + edge cases for lib/saved-screens.ts
 *
 * WHY THIS EXISTS: lib/saved-screens.ts is the only persistence layer for the
 * screener's "Save current filters" feature. localStorage failures (quota
 * exceeded, private mode, malformed JSON) are silent in production — these
 * tests are how we know the helpers degrade gracefully.
 *
 * WHY a per-test localStorage reset: each test creates/deletes records.
 * Without resetting, ordering would couple tests together (test #5 depends on
 * test #3's leftover state). Reset in beforeEach keeps tests independent.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  listSavedScreens,
  saveScreen,
  updateScreen,
  deleteScreen,
  loadScreen,
  SAVED_SCREENS_KEY,
} from "@/lib/saved-screens";
import type { FilterState } from "@/components/screener/ScreenerFilterBar";

const MOCK_FILTERS: FilterState = { search: "AAPL", sector: "Information Technology", capTier: "LARGE" };

describe("saved-screens lib — CRUD", () => {
  beforeEach(() => {
    // WHY clear before each: see file-level "WHY a per-test localStorage reset".
    window.localStorage.clear();
  });

  it("listSavedScreens returns empty array when localStorage is empty", () => {
    expect(listSavedScreens()).toEqual([]);
  });

  it("saveScreen persists a record and returns it", () => {
    const screen = saveScreen("My screen", MOCK_FILTERS);
    expect(screen.id).toBeDefined();
    expect(screen.name).toBe("My screen");
    expect(screen.filters).toEqual(MOCK_FILTERS);
    expect(screen.createdAt).toBeDefined();
    expect(screen.updatedAt).toBe(screen.createdAt);
  });

  it("listSavedScreens returns saved screens, newest first", () => {
    saveScreen("First", MOCK_FILTERS);
    // Force a tick so updatedAt differs.
    vi.useFakeTimers();
    vi.advanceTimersByTime(10);
    const second = saveScreen("Second", MOCK_FILTERS);
    vi.useRealTimers();
    const list = listSavedScreens();
    // WHY length=2 and "Second" first: save order is insertion; list sorts
    // by updatedAt desc so the most recent save shows up first.
    expect(list.length).toBe(2);
    expect(list[0].id).toBe(second.id);
  });

  it("loadScreen returns the matching record", () => {
    const created = saveScreen("Lookup", MOCK_FILTERS);
    const found = loadScreen(created.id);
    expect(found?.id).toBe(created.id);
    expect(found?.name).toBe("Lookup");
  });

  it("loadScreen returns null when id is missing", () => {
    expect(loadScreen("nonexistent-id")).toBeNull();
  });

  it("updateScreen patches name and filters", () => {
    const created = saveScreen("Old name", MOCK_FILTERS);
    const newFilters: FilterState = { search: "TSLA", sector: "", capTier: "ALL" };
    const updated = updateScreen(created.id, { name: "New name", filters: newFilters });
    expect(updated?.name).toBe("New name");
    expect(updated?.filters).toEqual(newFilters);
    // WHY id and createdAt must NOT change: lib/saved-screens.ts strips them
    // from the patch on purpose to prevent orphaned records.
    expect(updated?.id).toBe(created.id);
    expect(updated?.createdAt).toBe(created.createdAt);
  });

  it("updateScreen returns null when id is missing", () => {
    expect(updateScreen("nonexistent-id", { name: "X" })).toBeNull();
  });

  it("deleteScreen removes the record and returns true", () => {
    const created = saveScreen("To delete", MOCK_FILTERS);
    expect(deleteScreen(created.id)).toBe(true);
    expect(loadScreen(created.id)).toBeNull();
  });

  it("deleteScreen returns false when id is missing", () => {
    expect(deleteScreen("nonexistent-id")).toBe(false);
  });
});

describe("saved-screens lib — edge cases", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("listSavedScreens returns [] when localStorage value is malformed JSON", () => {
    // WHY simulate: if a buggy older version corrupted the key, the helper
    // must not crash the screener. Returning [] is the documented contract.
    window.localStorage.setItem(SAVED_SCREENS_KEY, "{not-valid-json");
    expect(listSavedScreens()).toEqual([]);
  });

  it("listSavedScreens returns [] when localStorage value is an object (not array)", () => {
    window.localStorage.setItem(SAVED_SCREENS_KEY, JSON.stringify({ foo: "bar" }));
    expect(listSavedScreens()).toEqual([]);
  });

  it("listSavedScreens filters out malformed records", () => {
    // Mix of valid + invalid.
    const mixed = [
      { id: "valid", name: "OK", filters: MOCK_FILTERS, createdAt: "2026-04-29T00:00:00Z", updatedAt: "2026-04-29T00:00:00Z" },
      { name: "missing-id" }, // invalid
      null, // invalid
    ];
    window.localStorage.setItem(SAVED_SCREENS_KEY, JSON.stringify(mixed));
    const list = listSavedScreens();
    expect(list.length).toBe(1);
    expect(list[0].id).toBe("valid");
  });

  it("saveScreen with empty name falls back to 'Untitled screen'", () => {
    const screen = saveScreen("", MOCK_FILTERS);
    expect(screen.name).toBe("Untitled screen");
  });

  it("saveScreen trims whitespace from name", () => {
    const screen = saveScreen("  spaces  ", MOCK_FILTERS);
    expect(screen.name).toBe("spaces");
  });

  it("saveScreen deep-clones filters so caller mutations don't bleed in", () => {
    const filters: FilterState = { search: "X", sector: "", capTier: "ALL" };
    const screen = saveScreen("Mutate me", filters);
    // Mutate caller's object.
    filters.search = "Y";
    expect(screen.filters.search).toBe("X");
  });

  it("listSavedScreens degrades gracefully if window.localStorage throws", () => {
    // Simulate Safari Private mode which throws SecurityError on getItem.
    const original = window.localStorage.getItem;
    window.localStorage.getItem = vi.fn(() => {
      throw new Error("SecurityError");
    });
    expect(listSavedScreens()).toEqual([]);
    window.localStorage.getItem = original;
  });
});

describe("saved-screens lib — name collisions", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("two saves with the same name produce different ids (no dedup)", () => {
    const a = saveScreen("Same", MOCK_FILTERS);
    const b = saveScreen("Same", MOCK_FILTERS);
    expect(a.id).not.toBe(b.id);
    expect(listSavedScreens().length).toBe(2);
  });
});
