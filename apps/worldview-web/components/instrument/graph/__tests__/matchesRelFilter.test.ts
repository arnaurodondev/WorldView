/**
 * matchesRelFilter.test.ts — F-QA-015
 *
 * WHY THIS EXISTS: matchesRelFilter is the sole gate between a user's filter
 * pill selection and which edges sigma renders. Incorrect pattern matching
 * silently hides or shows wrong edges — no type-checker catches this.
 * Each case covers a real relation label variant seen in KG data.
 */

import { describe, it, expect } from "vitest";
import { matchesRelFilter, isEdgeVisible } from "@/components/instrument/graph/graphFilterUtils";

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

  // ── PLAN-0099 W4 regression: canonical KG labels seen LIVE on AAPL ─────────
  // These are the exact labels S7 emits (confirmed via the live graph endpoint
  // 2026-06-12). The pre-W4 patterns MISSED owns_stake_in / investment_in for
  // the "investor" pill — the headline "filters don't fully work" bug.

  it('matches the canonical OWNS_STAKE_IN + INVESTMENT_IN for "investor"', () => {
    expect(matchesRelFilter("OWNS_STAKE_IN", "investor")).toBe(true);
    expect(matchesRelFilter("INVESTMENT_IN", "investor")).toBe(true);
  });

  it('matches the canonical HAS_EXECUTIVE + EMPLOYS for "executive"', () => {
    expect(matchesRelFilter("HAS_EXECUTIVE", "executive")).toBe(true);
    expect(matchesRelFilter("EMPLOYS", "executive")).toBe(true);
  });

  it('matches the canonical SUPPLIER_OF + PARTNER_OF for "supplier"', () => {
    expect(matchesRelFilter("SUPPLIER_OF", "supplier")).toBe(true);
    expect(matchesRelFilter("PARTNER_OF", "supplier")).toBe(true);
  });

  it('matches the canonical COMPETES_WITH for "competitor"', () => {
    expect(matchesRelFilter("COMPETES_WITH", "competitor")).toBe(true);
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

// ── isEdgeVisible — shared edge-visibility predicate (KG filter bug fix) ──────
// WHY: extracted so the visible-edge-count badge, the sigma edgeReducer, and the
// orphan-node hiding logic all agree on which edges survive the filters.
describe("isEdgeVisible", () => {
  it('matches every relation type under the "all" filter', () => {
    expect(isEdgeVisible("RANDOM_LABEL", 0.9, "all", 0)).toBe(true);
    expect(isEdgeVisible("HAS_EXECUTIVE", 0.9, "all", 0)).toBe(true);
  });

  it("applies the strength floor (minWeight is in percent, weight in 0–1)", () => {
    // weight 0.2 vs minWeight 30% (=0.30) → below floor → hidden.
    expect(isEdgeVisible("HAS_EXECUTIVE", 0.2, "all", 30)).toBe(false);
    // weight 0.4 vs minWeight 30% → above floor → visible.
    expect(isEdgeVisible("HAS_EXECUTIVE", 0.4, "all", 30)).toBe(true);
  });

  it("combines the strength floor with the relation pill", () => {
    // Matches the executive pill AND clears the strength floor → visible.
    expect(isEdgeVisible("HAS_EXECUTIVE", 0.9, "executive", 30)).toBe(true);
    // Clears the floor but does NOT match the executive pill → hidden.
    expect(isEdgeVisible("SUPPLIER_OF", 0.9, "executive", 30)).toBe(false);
    // Matches the pill but BELOW the floor → hidden.
    expect(isEdgeVisible("HAS_EXECUTIVE", 0.1, "executive", 30)).toBe(false);
  });
});
