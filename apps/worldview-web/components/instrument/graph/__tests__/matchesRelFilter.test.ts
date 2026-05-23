/**
 * matchesRelFilter.test.ts — F-QA-015
 *
 * WHY THIS EXISTS: matchesRelFilter is the sole gate between a user's filter
 * pill selection and which edges sigma renders. Incorrect pattern matching
 * silently hides or shows wrong edges — no type-checker catches this.
 * Each case covers a real relation label variant seen in KG data.
 */

import { describe, it, expect } from "vitest";
import { matchesRelFilter } from "@/components/instrument/graph/graphFilterUtils";

describe("matchesRelFilter", () => {
  // ── "all" ─────────────────────────────────────────────────────────────────

  it('returns true for any label when filter is "all"', () => {
    expect(matchesRelFilter("RANDOM_LABEL", "all")).toBe(true);
    expect(matchesRelFilter("", "all")).toBe(true);
  });

  // ── "executive" ───────────────────────────────────────────────────────────

  it('matches CEO_OF, CFO_OF, CTO_OF, COO_OF for "executive"', () => {
    expect(matchesRelFilter("CEO_OF", "executive")).toBe(true);
    expect(matchesRelFilter("CFO_OF", "executive")).toBe(true);
    expect(matchesRelFilter("CTO_OF", "executive")).toBe(true);
    expect(matchesRelFilter("COO_OF", "executive")).toBe(true);
  });

  it('matches CHAIR, EXEC, OFFICER, DIRECTOR for "executive"', () => {
    expect(matchesRelFilter("EXECUTIVE_CHAIR", "executive")).toBe(true);
    expect(matchesRelFilter("CHIEF_EXEC", "executive")).toBe(true);
    expect(matchesRelFilter("CHIEF_OFFICER", "executive")).toBe(true);
    expect(matchesRelFilter("BOARD_DIRECTOR", "executive")).toBe(true);
  });

  it('does NOT match unrelated labels for "executive"', () => {
    expect(matchesRelFilter("COMPETES_WITH", "executive")).toBe(false);
    expect(matchesRelFilter("INVESTS_IN", "executive")).toBe(false);
  });

  // ── "investor" ────────────────────────────────────────────────────────────

  it('matches INVESTS_IN, SHAREHOLDER, HOLDS, OWNED for "investor"', () => {
    expect(matchesRelFilter("INVESTS_IN", "investor")).toBe(true);
    expect(matchesRelFilter("MAJOR_SHAREHOLDER", "investor")).toBe(true);
    expect(matchesRelFilter("HOLDS_STAKE", "investor")).toBe(true);
    expect(matchesRelFilter("OWNED_BY", "investor")).toBe(true);
  });

  it('does NOT match COMPETES_WITH for "investor"', () => {
    expect(matchesRelFilter("COMPETES_WITH", "investor")).toBe(false);
  });

  // ── "supplier" ────────────────────────────────────────────────────────────

  it('matches SUPPLIER_OF, MANUFACTURES, PRODUCES for "supplier"', () => {
    expect(matchesRelFilter("SUPPLIER_OF", "supplier")).toBe(true);
    expect(matchesRelFilter("MANUFACTURES", "supplier")).toBe(true);
    expect(matchesRelFilter("PRODUCES", "supplier")).toBe(true);
  });

  it('does NOT match CUSTOMER_OF for "supplier"', () => {
    expect(matchesRelFilter("CUSTOMER_OF", "supplier")).toBe(false);
  });

  // ── "customer" ────────────────────────────────────────────────────────────

  it('matches CUSTOMER_OF, CLIENT_OF, USES for "customer"', () => {
    expect(matchesRelFilter("CUSTOMER_OF", "customer")).toBe(true);
    expect(matchesRelFilter("CLIENT_OF", "customer")).toBe(true);
    expect(matchesRelFilter("USES", "customer")).toBe(true);
  });

  it('does NOT match SUPPLIER_OF for "customer"', () => {
    expect(matchesRelFilter("SUPPLIER_OF", "customer")).toBe(false);
  });

  // ── "competitor" ──────────────────────────────────────────────────────────

  it('matches COMPETES_WITH, RIVAL_OF for "competitor"', () => {
    expect(matchesRelFilter("COMPETES_WITH", "competitor")).toBe(true);
    expect(matchesRelFilter("RIVAL_OF", "competitor")).toBe(true);
  });

  it('does NOT match CEO_OF for "competitor"', () => {
    expect(matchesRelFilter("CEO_OF", "competitor")).toBe(false);
  });

  // ── case-insensitivity ───────────────────────────────────────────────────

  it("is case-insensitive (lowercase labels match correctly)", () => {
    expect(matchesRelFilter("ceo_of", "executive")).toBe(true);
    expect(matchesRelFilter("competes_with", "competitor")).toBe(true);
    expect(matchesRelFilter("invests_in", "investor")).toBe(true);
  });
});
