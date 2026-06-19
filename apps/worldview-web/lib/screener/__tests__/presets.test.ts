/**
 * lib/screener/__tests__/presets.test.ts — system preset guards.
 *
 * WHY THIS FILE: presets are pure FilterState objects applied verbatim. A typo
 * in a preset's filter values silently ships a wrong screen. These tests pin the
 * strategically-important "Live Catalysts" intelligence preset (the EQS-beating
 * one) and the catalogue's structural invariants.
 */

import { describe, expect, it } from "vitest";
import { SCREENER_PRESETS } from "@/lib/screener/presets";

describe("SCREENER_PRESETS", () => {
  it("has unique preset ids", () => {
    const ids = SCREENER_PRESETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("includes the Live Catalysts intelligence-moat preset", () => {
    const live = SCREENER_PRESETS.find((p) => p.id === "live-catalysts");
    expect(live).toBeDefined();
    expect(live?.label).toBe("Live Catalysts");
  });

  it("Live Catalysts composes news ≥5 AND active alert AND ≥1 contradiction", () => {
    // These are the three IB-L5 signals a Bloomberg EQS terminal cannot express.
    const live = SCREENER_PRESETS.find((p) => p.id === "live-catalysts");
    expect(live?.filters.newsCount7dMin).toBe(5);
    expect(live?.filters.hasActiveAlert).toBe(true);
    expect(live?.filters.contradictionsMin).toBe(1);
  });
});
