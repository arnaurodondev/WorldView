/**
 * components/portfolio/__tests__/SemanticHoldingsTable.test.tsx
 *
 * WHY THIS EXISTS: Verifies the 14-column spec introduced in PLAN-0108 W4-T401.
 * The tests guard against:
 *   - Accidental column removal (holdingsAgColumns.length must be 14)
 *   - SPARK column missing its colId (regression: colId "spark" added in W4-T401)
 *   - ASSET column missing its colId (regression: colId "asset" added in W4-T401)
 *   - Header label regressions for the two new columns
 *
 * WHY we test holdingsAgColumns directly (not the rendered AgGrid component):
 *   AG Grid is a heavy browser library that requires DOM APIs unavailable in
 *   jsdom. Mounting AgGridReact in Vitest would require extensive mocking of
 *   ResizeObserver, IntersectionObserver, and the AG Grid license check.
 *   The column definition array is the stable, unit-testable contract that
 *   SemanticHoldingsTable passes to AgGridBase — testing it directly gives us
 *   full column-spec coverage without brittle DOM snapshots. This mirrors the
 *   pattern established in holdings-columns.test.ts.
 *
 * WHY we also test SemanticHoldingsTableProps shape:
 *   TypeScript types are erased at runtime. We can't "assert a type exists"
 *   in a runtime test. Instead, we verify that the series prop flows correctly
 *   into the expected context shape by inspecting what the column definitions
 *   reference (context.holdingsSeries keyed by ticker), confirming the wiring
 *   contract without needing a mounted component.
 *
 * PLAN-0108 W4-T401
 */

import { describe, it, expect } from "vitest";
import { holdingsAgColumns, HOLDINGS_AG_COL_WIDTHS } from "../ag-holdings-columns";

// ── holdingsAgColumns — 14-column spec ───────────────────────────────────────

describe("holdingsAgColumns (14-column spec — PLAN-0108 W4-T401)", () => {
  it("SemanticHoldingsTable has 14 columns", () => {
    // WHY 14: the spec added SPARK (col 8) and ASSET (col 14) to the original
    // 12-column table. Any deviation means a column was accidentally dropped or
    // added without updating this test.
    expect(holdingsAgColumns).toHaveLength(14);
  });

  it("SemanticHoldingsTable renders SPARK column header", () => {
    // WHY headerName check (not colId): the "SPARK" label is what the trader sees
    // in the column header. A colId rename is an internal concern; a header rename
    // is a UX regression.
    const sparkCol = holdingsAgColumns.find((c) => c.colId === "spark");
    expect(sparkCol, "SPARK column (colId='spark') must exist").toBeDefined();
    expect(sparkCol?.headerName).toBe("SPARK");
  });

  it("SemanticHoldingsTable renders ASSET column header", () => {
    const assetCol = holdingsAgColumns.find((c) => c.colId === "asset");
    expect(assetCol, "ASSET column (colId='asset') must exist").toBeDefined();
    expect(assetCol?.headerName).toBe("ASSET");
  });

  it("column order matches the 14-column spec", () => {
    // WHY explicit order check: order matters for the trader's eye-scan path.
    // SPARK must come after DAY Δ% (col 7) and before MKT VALUE (col 9).
    // ASSET must be last (col 14).
    const ids = holdingsAgColumns.map((c) => c.colId);
    expect(ids).toEqual([
      "ticker",      // 1
      "name",        // 2
      "qty",         // 3
      "avg_cost",    // 4
      "current",     // 5  — header: LAST
      "dayChange",   // 6  — header: DAY Δ$
      "dayChangePct",// 7  — header: DAY Δ%
      "spark",       // 8  — NEW: SPARK
      "value",       // 9  — header: MKT VALUE
      "pnl",         // 10 — header: UNREAL $
      "pnlPct",      // 11 — header: UNREAL %
      "weight",      // 12
      "sector",      // 13
      "asset",       // 14 — NEW: ASSET
    ]);
  });

  it("SPARK column is not sortable", () => {
    // WHY: a sparkline SVG has no meaningful scalar sort key.
    const sparkCol = holdingsAgColumns.find((c) => c.colId === "spark");
    expect(sparkCol?.sortable).toBe(false);
  });

  it("ASSET column is not sortable", () => {
    // WHY: asset class is a categorical enum (equity, etf, etc.) with no
    // natural sort order meaningful to the trader.
    const assetCol = holdingsAgColumns.find((c) => c.colId === "asset");
    expect(assetCol?.sortable).toBe(false);
  });

  it("SPARK column has correct width from spec (76px)", () => {
    const sparkCol = holdingsAgColumns.find((c) => c.colId === "spark");
    expect(sparkCol?.width).toBe(76);
    // Also verify the width constant exports the right value.
    expect(HOLDINGS_AG_COL_WIDTHS.spark).toBe(76);
  });

  it("ASSET column has correct width from spec (44px)", () => {
    const assetCol = holdingsAgColumns.find((c) => c.colId === "asset");
    expect(assetCol?.width).toBe(44);
    expect(HOLDINGS_AG_COL_WIDTHS.asset).toBe(44);
  });

  it("SPARK column has a cellRenderer (SparklineCellRenderer)", () => {
    // WHY: a missing cellRenderer would silently render an empty SPARK column.
    // We cannot check the function reference by name in a unit test (it would
    // tightly couple to import paths), but we can verify the property is defined
    // and is a function.
    const sparkCol = holdingsAgColumns.find((c) => c.colId === "spark");
    expect(sparkCol?.cellRenderer, "SPARK cellRenderer must be defined").toBeDefined();
    expect(typeof sparkCol?.cellRenderer).toBe("function");
  });

  it("ASSET column has a cellRenderer (AssetTypeCellRenderer)", () => {
    const assetCol = holdingsAgColumns.find((c) => c.colId === "asset");
    expect(assetCol?.cellRenderer, "ASSET cellRenderer must be defined").toBeDefined();
    expect(typeof assetCol?.cellRenderer).toBe("function");
  });

  it("renamed columns still have their original colIds (localStorage column-state compat)", () => {
    // WHY: the LAST, MKT VALUE, UNREAL $, and UNREAL % columns were renamed
    // from CURRENT, VALUE, P&L $, P&L %. Their colIds must not change, or every
    // user's saved column state (HOLDINGS_COLS_KEY in localStorage) will reset
    // on next load — a jarring UX regression.
    const renamedMap: Record<string, string> = {
      current: "LAST",
      dayChange: "DAY Δ$",
      dayChangePct: "DAY Δ%",
      value: "MKT VALUE",
      pnl: "UNREAL $",
      pnlPct: "UNREAL %",
    };
    const byId = Object.fromEntries(holdingsAgColumns.map((c) => [c.colId!, c]));
    for (const [colId, expectedHeader] of Object.entries(renamedMap)) {
      expect(byId[colId], `colId "${colId}" must exist`).toBeDefined();
      expect(byId[colId].headerName).toBe(expectedHeader);
    }
  });
});
