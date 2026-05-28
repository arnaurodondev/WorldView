/**
 * __tests__/screener/presets.test.ts
 * (PRD-0089 Wave I-B Block IB-L1 · T-IB-04)
 *
 * WHY: pin the SCREENER_PRESETS contract. The "US Equities Only" preset
 * is canonical for the analyst's first-screen-on-open gesture; getting
 * its filter set wrong would silently break a daily workflow.
 *
 * Also assert prior presets stay intact — adding a preset must NEVER
 * regress an existing one.
 */

import { describe, expect, it } from "vitest";
import { SCREENER_PRESETS } from "@/lib/screener/presets";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

describe("SCREENER_PRESETS — registry", () => {
  it("contains the seven canonical presets in stable order", () => {
    // WHY order matters: PresetBar renders chips horizontally; reordering
    // would shift the user's mental shortcuts (the "third chip" they used
    // to click). Lock the order here so any future insertion is conscious.
    expect(SCREENER_PRESETS.map((p) => p.id)).toEqual([
      "all",
      "large-cap",
      "dividend",
      "value",
      "growth",
      "profitable",
      "us-equities-only",
    ]);
  });

  it("preset IDs are unique (no duplicate React keys)", () => {
    // WHY: PresetBar uses preset.id as a React key — duplicate IDs cause
    // silent render bugs (wrong chip activated).
    const ids = SCREENER_PRESETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("SCREENER_PRESETS — 'us-equities-only' (T-IB-04)", () => {
  const preset = SCREENER_PRESETS.find((p) => p.id === "us-equities-only");

  it("exists and has the expected label", () => {
    expect(preset).toBeDefined();
    expect(preset!.label).toBe("US Equities Only");
  });

  it("sets countries=['USA'] (single ISO3 code, not a list of US exchanges)", () => {
    // WHY country-based, not exchange-based: many US issuers list on
    // multiple US venues (dual-class shares trade NYSE/NASDAQ); the
    // country field is the cleaner restriction. See preset comment.
    expect(preset!.filters.countries).toEqual(["USA"]);
  });

  it("sets hasFundamentals=true so follow-on P/E / ROE filters have data", () => {
    expect(preset!.filters.hasFundamentals).toBe(true);
  });

  it("does NOT set hasOhlcv (analysts may want pre-IPO / synthetic with prices)", () => {
    // WHY explicit: a future edit that adds hasOhlcv=true would narrow
    // the result set without justification — pin the absence so the
    // change requires a deliberate edit + test update.
    expect(preset!.filters.hasOhlcv).toBeUndefined();
  });

  it("inherits the DEFAULT_FILTERS baseline (search/sector/capTier untouched)", () => {
    // WHY: the preset is an OVERLAY on the defaults — clicking it must
    // not silently reset capTier or sector to anything other than the
    // baseline. This guards against spread-order bugs.
    expect(preset!.filters.search).toBe(DEFAULT_FILTERS.search);
    expect(preset!.filters.sector).toBe(DEFAULT_FILTERS.sector);
    expect(preset!.filters.capTier).toBe(DEFAULT_FILTERS.capTier);
  });
});
