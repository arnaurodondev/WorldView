/**
 * Tests for the entity-type design tokens (PLAN-0057 Wave F-1).
 *
 * Anchors the contract that the 9 entity types added by Wave A-3 seeds
 * (currency, regulatory_body, government_body, location, person,
 * financial_institution, commodity, macroeconomic_indicator, index) all
 * have explicit (non-fallback) tokens — without this assertion a typo or a
 * missing entry would silently render in default grey and the bug would
 * only surface in production traffic.
 */

import { describe, it, expect } from "vitest";

import {
  entityTypeToken,
  KNOWN_ENTITY_TYPES,
  ENTITY_TYPE_COLOR_MAP,
} from "@/lib/entity-types";

describe("entityTypeToken", () => {
  it("returns explicit tokens for every PLAN-0057 A-3 seed type", () => {
    const required = [
      "currency",
      "regulatory_body",
      "government_body",
      "location",
      "person",
      "financial_institution",
      "commodity",
      "macroeconomic_indicator",
      "index",
    ];
    for (const type of required) {
      const token = entityTypeToken(type);
      expect(token.label, `missing label for ${type}`).not.toBe("Entity");
      expect(token.color, `missing colour for ${type}`).not.toBe("#6B7585");
      // Layout variant must be a known string (not the generic default).
      expect(token.layout, `missing layout for ${type}`).not.toBe(undefined);
    }
  });

  it("returns the same explicit token for legacy 'company'", () => {
    const token = entityTypeToken("company");
    expect(token.label).toBe("Company");
    expect(token.layout).toBe("instrument");
  });

  it("falls back gracefully for unknown types", () => {
    const token = entityTypeToken("unknown_future_type");
    expect(token.label).toBe("Entity");
    expect(token.color).toBe("#6B7585");
    expect(token.layout).toBe("default");
  });

  it("falls back for null/undefined entity_type", () => {
    expect(entityTypeToken(null).label).toBe("Entity");
    expect(entityTypeToken(undefined).label).toBe("Entity");
    expect(entityTypeToken("").label).toBe("Entity");
  });

  it("KNOWN_ENTITY_TYPES contains all required types", () => {
    expect(KNOWN_ENTITY_TYPES).toContain("financial_instrument");
    expect(KNOWN_ENTITY_TYPES).toContain("currency");
    expect(KNOWN_ENTITY_TYPES).toContain("regulatory_body");
    expect(KNOWN_ENTITY_TYPES).toContain("macroeconomic_indicator");
  });

  it("ENTITY_TYPE_COLOR_MAP exports a hex per known type", () => {
    for (const type of KNOWN_ENTITY_TYPES) {
      expect(ENTITY_TYPE_COLOR_MAP[type]).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("financial_instrument is Bloomberg yellow (palette anchor)", () => {
    expect(entityTypeToken("financial_instrument").color).toBe("#FFD60A");
  });
});
