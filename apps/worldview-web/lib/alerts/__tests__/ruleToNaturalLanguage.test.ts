/**
 * lib/alerts/__tests__/ruleToNaturalLanguage.test.ts — per-type NL summary
 * (PLAN-0113 W4 T-4-03).
 *
 * Pins the human "Alert me when …" string for each of the 5 rule types + the
 * incomplete-condition fallback. Pure function, so no mocks needed.
 */

import { describe, it, expect } from "vitest";
import { ruleToNaturalLanguage } from "@/lib/alerts/format";

describe("ruleToNaturalLanguage", () => {
  it("returns a prompt when the condition is null (incomplete form)", () => {
    expect(ruleToNaturalLanguage({ rule_type: "PRICE_CROSS", condition: null })).toMatch(
      /complete the fields/i,
    );
  });

  it("PRICE_CROSS reads price crosses above/below value", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "PRICE_CROSS",
      condition: { instrument_id: "i-aapl", operator: "above", value: 250 },
      names: { "i-aapl": "AAPL" },
    });
    expect(s).toBe("Alert me when AAPL price crosses above 250.");
  });

  it("FUNDAMENTAL_CROSS includes the metric_key + threshold", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "FUNDAMENTAL_CROSS",
      condition: { instrument_id: "i-aapl", metric_key: "pe_ratio", operator: "below", value: 25 },
      names: { "i-aapl": "AAPL" },
    });
    expect(s).toBe("Alert me when AAPL pe_ratio crosses below 25.");
  });

  it("NEWS_COUNT reads article count over a window (with keyword)", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "NEWS_COUNT",
      condition: { entity_id: "e-nvda", window: "24h", threshold: 5, keyword: "earnings" },
      names: { "e-nvda": "NVDA" },
    });
    expect(s).toContain("≥ 5 articles");
    expect(s).toContain('"earnings"');
    expect(s).toContain("NVDA");
    expect(s).toContain("24h");
  });

  it("NEWS_MOMENTUM includes delta_pct, window_hours and min_count", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "NEWS_MOMENTUM",
      condition: { entity_id: "e-tsla", window_hours: 72, delta_pct: 50, min_count: 3 },
      names: { "e-tsla": "TSLA" },
    });
    expect(s).toContain("TSLA");
    expect(s).toContain("≥ 50%");
    expect(s).toContain("72h");
    expect(s).toContain("≥ 3 articles");
  });

  it("KG_CONNECTION reads two entities + max_hops (and relation_type)", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "KG_CONNECTION",
      condition: {
        source_entity_id: "a",
        target_entity_id: "b",
        max_hops: 3,
        relation_type: "SUPPLIES",
      },
      names: { a: "Apple", b: "Anthropic" },
    });
    expect(s).toBe(
      "Alert me when Apple connects to Anthropic within 3 hops via a SUPPLIES link.",
    );
  });

  it("falls back to the raw id when no display name is provided", () => {
    const s = ruleToNaturalLanguage({
      rule_type: "PRICE_CROSS",
      condition: { instrument_id: "i-xyz", operator: "below", value: 10 },
    });
    expect(s).toContain("i-xyz");
  });
});
