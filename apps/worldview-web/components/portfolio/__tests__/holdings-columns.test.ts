/**
 * components/portfolio/__tests__/holdings-columns.test.ts
 *
 * WHY: Unit tests for holdingsColumns + exported helpers.
 * These are pure unit tests (no DOM mount) that pin the contracts
 * SemanticHoldingsTable depends on after the PLAN-0059 F-1 migration.
 *
 * PLAN-0059 F-1 — DataTable migration tests (≥3 per migrated table).
 * PLAN-0114 W6 — Updated for divYld column addition.
 */

import { describe, it, expect } from "vitest";
import { holdingsColumns, fmtPnl, formatStalenessAwarePrice } from "../holdings-columns";

// ── holdingsColumns ──────────────────────────────────────────────────────────

describe("holdingsColumns", () => {
  it("has exactly 13 columns", () => {
    // PLAN-0114 W6: added divYld column (was 12)
    expect(holdingsColumns).toHaveLength(13);
  });

  it("column ids match expected order", () => {
    const ids = holdingsColumns.map((c) => c.id);
    expect(ids).toEqual([
      "ticker",
      "name",
      "qty",
      "avg_cost",
      "current",
      "dayChange",
      "dayChangePct",
      "pnl",
      "pnlPct",
      "value",
      "weight",
      "sector",
      // PLAN-0114 W6: dividend yield column added at end
      "divYld",
    ]);
  });

  it("sortable columns have accessorFn defined", () => {
    const sortableCols = ["qty", "dayChange", "dayChangePct", "pnl", "pnlPct", "value", "weight"];
    const byId = Object.fromEntries(holdingsColumns.map((c) => [c.id!, c]));
    for (const id of sortableCols) {
      expect(
        (byId[id] as { accessorFn?: unknown }).accessorFn,
        `column "${id}" should have accessorFn`,
      ).toBeDefined();
    }
  });

  it("non-sortable columns have enableSorting=false", () => {
    // PLAN-0114 W6: divYld is also non-sortable (instrument property, not a position metric)
    const nonSortable = ["ticker", "name", "avg_cost", "current", "sector", "divYld"];
    const byId = Object.fromEntries(holdingsColumns.map((c) => [c.id!, c]));
    for (const id of nonSortable) {
      expect(byId[id].enableSorting, `column "${id}" should have enableSorting=false`).toBe(false);
    }
  });

  it("divYld column has correct header and size", () => {
    // PLAN-0114 W6: pin the divYld contract so accidental renames are caught.
    const byId = Object.fromEntries(holdingsColumns.map((c) => [c.id!, c]));
    const divYldCol = byId["divYld"] as { header: string; size: number; enableSorting: boolean };
    expect(divYldCol.header).toBe("DIV YLD");
    expect(divYldCol.size).toBe(80);
    expect(divYldCol.enableSorting).toBe(false);
  });
});

// ── fmtPnl ───────────────────────────────────────────────────────────────────

describe("fmtPnl", () => {
  it("prefixes '+' for positive values", () => {
    expect(fmtPnl(1234.5)).toContain("+");
  });

  it("does not prefix '+' for negative values (sign is in the number)", () => {
    const result = fmtPnl(-500);
    expect(result).not.toMatch(/^\+/);
    // The negative value should still be formatted as a price.
    expect(result).toContain("500");
  });

  it("returns '+$0.00' for zero", () => {
    // Zero is non-negative, so it gets the '+' prefix.
    expect(fmtPnl(0)).toContain("+");
  });
});

// ── formatStalenessAwarePrice ─────────────────────────────────────────────────

describe("formatStalenessAwarePrice", () => {
  it("returns a formatted price with no prefix for live quotes", () => {
    const result = formatStalenessAwarePrice(150.5, "live");
    expect(result).not.toMatch(/^~/);
    expect(result).toContain("150");
  });

  it("prefixes '~' when freshness is 'delayed'", () => {
    expect(formatStalenessAwarePrice(150, "delayed")).toMatch(/^~/);
  });

  it("prefixes '~' when freshness is any non-'live' string", () => {
    expect(formatStalenessAwarePrice(100, "eod")).toMatch(/^~/);
  });

  it("returns a plain price when freshness is undefined", () => {
    // No freshness = quote freshness unknown, not stale — render without tilde.
    const result = formatStalenessAwarePrice(200, undefined);
    expect(result).not.toMatch(/^~/);
  });
});
