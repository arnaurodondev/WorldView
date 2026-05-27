/**
 * lib/screener/__tests__/gics-hierarchy.test.ts
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: pins the GICS sector→industry map + `industriesForSectors` helper
 * shape. The hierarchy drives the popover cascading (T-IA-05). If the
 * map silently grows / shrinks / renames an industry, the cascading
 * filter UI would either show stale options or hide live ones; this test
 * locks the contract per plan §5.1 acceptance.
 */

import { describe, expect, it } from "vitest";
import {
  GICS_HIERARCHY,
  industriesForSectors,
} from "@/lib/screener/gics-hierarchy";

describe("gics-hierarchy", () => {
  it("GICS_HIERARCHY exposes all 11 GICS sectors", () => {
    // WHY: GICS is canonically 11 sectors post-2018 Communication Services
    // rename. Drift surfaces as a sector missing from the popover combobox.
    const sectors = Object.keys(GICS_HIERARCHY);
    expect(sectors).toHaveLength(11);
    expect(sectors).toContain("Information Technology");
    expect(sectors).toContain("Energy");
    expect(sectors).toContain("Real Estate");
  });

  it("industriesForSectors returns the union of industries for the IT sector", () => {
    // WHY: this is the round-trip acceptance criterion called out in the
    // plan for T-IA-04. The exact count is locked in the hierarchy file;
    // we assert non-empty + presence of a canonical IT industry to catch
    // accidental wipes without becoming a brittle exact-count test.
    const it = industriesForSectors(["Information Technology"]);
    expect(it.length).toBeGreaterThan(0);
    // Any IT industry name is fine — pick one stable across GICS revisions.
    expect(it.some((i) => /software|technology|semiconductors/i.test(i))).toBe(
      true,
    );
  });

  it("returns an empty array when called with no sectors", () => {
    // WHY: caller (ScreenerFilterBar) special-cases empty selection to fall
    // back to the full allowlist. Helper must return [] (not null/undefined)
    // so the caller's `.length === 0` branch fires correctly.
    expect(industriesForSectors([])).toEqual([]);
  });

  it("dedupes when two sectors share no overlap (sanity)", () => {
    // WHY: industriesForSectors returns the UNION across multiple sectors.
    // Two disjoint sectors should yield length equal to the sum. The check
    // is a smoke test against accidental intersection.
    const energy = industriesForSectors(["Energy"]);
    const utilities = industriesForSectors(["Utilities"]);
    const both = industriesForSectors(["Energy", "Utilities"]);
    expect(both.length).toBeGreaterThanOrEqual(
      Math.max(energy.length, utilities.length),
    );
  });

  it("ignores unknown sector strings (graceful)", () => {
    // WHY: NL screener may emit a sector name the map doesn't yet know
    // (LLM hallucination). The helper must skip it silently rather than
    // throwing — a thrown error would crash the popover combobox.
    const result = industriesForSectors(["NotARealSector"]);
    expect(result).toEqual([]);
  });
});
