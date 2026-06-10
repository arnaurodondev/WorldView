/**
 * features/screener/lib/__tests__/active-counts.test.ts — Unit tests for the
 * pure filter-counting helpers.
 *
 * WHY THESE TESTS EXIST: the inline counts in ScreenerFilterBar.tsx
 * previously had no test coverage — a future field rename would silently
 * miscount filters and the Section badge would show the wrong number.
 * These tests pin every section's rule so adding a new FilterState field
 * forces a corresponding test update.
 */

import { describe, it, expect } from "vitest";
import {
  isSet,
  rangeCount,
  countActiveFiltersByGroup,
} from "../active-counts";
import {
  DEFAULT_FILTERS,
  type FilterState,
} from "../filter-state";

// ── isSet ─────────────────────────────────────────────────────────────────

describe("isSet", () => {
  it("returns false for undefined and null", () => {
    expect(isSet(undefined)).toBe(false);
    expect(isSet(null)).toBe(false);
  });

  it("returns false for empty string and the 'ALL' sentinel", () => {
    expect(isSet("")).toBe(false);
    expect(isSet("ALL")).toBe(false);
  });

  it("returns true for non-empty / non-ALL strings", () => {
    expect(isSet("LARGE")).toBe(true);
    expect(isSet("Information Technology")).toBe(true);
  });

  it("returns true for finite numbers (including 0)", () => {
    expect(isSet(0)).toBe(true);
    expect(isSet(-5)).toBe(true);
    expect(isSet(1.5)).toBe(true);
  });

  it("returns false for NaN / Infinity (non-finite numbers)", () => {
    expect(isSet(NaN)).toBe(false);
    expect(isSet(Infinity)).toBe(false);
  });

  it("returns true ONLY for boolean true (not false)", () => {
    expect(isSet(true)).toBe(true);
    expect(isSet(false)).toBe(false);
  });
});

// ── rangeCount ────────────────────────────────────────────────────────────

describe("rangeCount", () => {
  it("returns 0 when both bounds are undefined", () => {
    expect(rangeCount(undefined, undefined)).toBe(0);
  });

  it("returns 1 when only one bound is set", () => {
    expect(rangeCount(10, undefined)).toBe(1);
    expect(rangeCount(undefined, 20)).toBe(1);
  });

  it("returns 2 when both bounds are set", () => {
    expect(rangeCount(10, 20)).toBe(2);
  });

  it("treats 0 as a real bound (not unset)", () => {
    expect(rangeCount(0, undefined)).toBe(1);
    expect(rangeCount(0, 0)).toBe(2);
  });
});

// ── countActiveFiltersByGroup ─────────────────────────────────────────────

describe("countActiveFiltersByGroup", () => {
  it("returns all zeros for DEFAULT_FILTERS", () => {
    const c = countActiveFiltersByGroup(DEFAULT_FILTERS);
    // WHY include all sections: IB-L3/L4/L5 each added a new section key.
    // An exhaustive equality check here means adding a new section without
    // updating both the helper AND this test will cause a visible failure.
    expect(c).toEqual({
      valuation: 0,
      profitability: 0,
      growth: 0,
      leverage: 0,
      technical: 0,
      performance: 0,
      ownership: 0,
      news: 0,
      intelligence: 0,
    });
  });

  it("counts each side of a min/max range independently", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, peMin: 10 };
    expect(countActiveFiltersByGroup(form).valuation).toBe(1);

    const form2: FilterState = { ...DEFAULT_FILTERS, peMin: 10, peMax: 20 };
    expect(countActiveFiltersByGroup(form2).valuation).toBe(2);
  });

  it("aggregates valuation across all 4 sub-filters (PE/PB/PS/Yield)", () => {
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      peMin: 5,
      peMax: 25, // 2
      pbMax: 5, // 1
      divYieldMin: 0.02, // 1
    };
    expect(countActiveFiltersByGroup(form).valuation).toBe(4);
  });

  it("technical: counts above50dMa boolean toggle independently", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, above50dMa: true };
    expect(countActiveFiltersByGroup(form).technical).toBe(1);

    const formFalse: FilterState = { ...DEFAULT_FILTERS, above50dMa: false };
    expect(countActiveFiltersByGroup(formFalse).technical).toBe(0);
  });

  it("technical: combines boolean + range + scalar fields correctly", () => {
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      above50dMa: true, // 1
      rsiMin: 30,
      rsiMax: 70, // 2
      volumeRatioMin: 1.5, // 1
      distFrom52wHighMax: 5, // 1
    };
    expect(countActiveFiltersByGroup(form).technical).toBe(5);
  });

  it("news: counts insiderActivity, recentEarningsDays, controversy, news velocity", () => {
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      newsVelocity7dMin: 3, // 1
      controversyMin: 0.5,
      controversyMax: 0.9, // 2
      recentEarningsDays: 7, // 1
      insiderActivity: "BUYING", // 1
    };
    expect(countActiveFiltersByGroup(form).news).toBe(5);
  });

  it("isolates section counts (a valuation filter does NOT bleed into other sections)", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, peMin: 10, peMax: 20 };
    const c = countActiveFiltersByGroup(form);
    expect(c.valuation).toBe(2);
    expect(c.profitability).toBe(0);
    expect(c.growth).toBe(0);
    expect(c.leverage).toBe(0);
    expect(c.technical).toBe(0);
    expect(c.performance).toBe(0);
    expect(c.ownership).toBe(0);
    expect(c.news).toBe(0);
    expect(c.intelligence).toBe(0);
  });

  it("does not count the search/sector/capTier top-row fields against any section", () => {
    // These sit OUTSIDE the collapsible section badges by design.
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      search: "AAPL",
      sector: "Information Technology",
      capTier: "LARGE",
    };
    const c = countActiveFiltersByGroup(form);
    // Include performance + ownership + intelligence in the sum (IB-L3/L4/L5).
    expect(
      c.valuation + c.profitability + c.growth + c.leverage + c.technical +
      c.performance + c.ownership + c.news + c.intelligence
    ).toBe(0);
  });

  // ── IB-L5 intelligence section ───────────────────────────────────────────

  it("intelligence: counts newsCount7d range sides independently", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, newsCount7dMin: 3 };
    expect(countActiveFiltersByGroup(form).intelligence).toBe(1);

    const form2: FilterState = { ...DEFAULT_FILTERS, newsCount7dMin: 3, newsCount7dMax: 20 };
    expect(countActiveFiltersByGroup(form2).intelligence).toBe(2);
  });

  it("intelligence: counts hasAiBrief boolean as 1 (true only)", () => {
    const formTrue: FilterState = { ...DEFAULT_FILTERS, hasAiBrief: true };
    expect(countActiveFiltersByGroup(formTrue).intelligence).toBe(1);

    const formFalse: FilterState = { ...DEFAULT_FILTERS, hasAiBrief: false };
    expect(countActiveFiltersByGroup(formFalse).intelligence).toBe(0);

    const formUndef: FilterState = { ...DEFAULT_FILTERS };
    expect(countActiveFiltersByGroup(formUndef).intelligence).toBe(0);
  });

  it("intelligence: counts hasActiveAlert boolean as 1 (true only)", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, hasActiveAlert: true };
    expect(countActiveFiltersByGroup(form).intelligence).toBe(1);
  });

  it("intelligence: aggregates all 6 active intelligence fields", () => {
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      newsCount7dMin: 2,        // +1
      newsCount7dMax: 50,       // +1
      contradictionsMin: 1,     // +1
      displayRelevance7dMin: 0.5, // +1
      hasAiBrief: true,         // +1
      hasActiveAlert: true,     // +1
    };
    expect(countActiveFiltersByGroup(form).intelligence).toBe(6);
  });

  it("intelligence: does not bleed into other section counts", () => {
    const form: FilterState = { ...DEFAULT_FILTERS, newsCount7dMin: 3, hasAiBrief: true };
    const c = countActiveFiltersByGroup(form);
    expect(c.intelligence).toBe(2);
    expect(c.news).toBe(0);
    expect(c.valuation).toBe(0);
  });
});

// ── Round 2: slider-backed filters feed the section badges ───────────────────

describe("countActiveFiltersByGroup — Round 2 slider fields", () => {
  it("technical: counts each side of the avg-volume 30d range", () => {
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      avgVolume30dMin: 500_000,
      avgVolume30dMax: 50_000_000,
    };
    expect(countActiveFiltersByGroup(form).technical).toBe(2);
  });

  it("valuation: counts the market-cap range (previously a latent badge gap)", () => {
    // marketCapMin/Max existed on FilterState (chip-strip entry) but were
    // never badge-counted; the Round 2 Market Cap slider in the Valuation
    // section makes the badge mandatory.
    const form: FilterState = {
      ...DEFAULT_FILTERS,
      marketCapMin: 1_000_000_000,
    };
    expect(countActiveFiltersByGroup(form).valuation).toBe(1);
  });
});
