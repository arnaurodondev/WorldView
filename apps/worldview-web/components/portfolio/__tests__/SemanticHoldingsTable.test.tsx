/**
 * components/portfolio/__tests__/SemanticHoldingsTable.test.tsx
 *
 * WHY THIS EXISTS: Verifies the 15-column spec introduced in PLAN-0108 W4-T401
 * and updated in PLAN-0114 W6 (divYld column added via FR-12).
 * The tests guard against:
 *   - Accidental column removal (holdingsAgColumns.length must be 15)
 *   - SPARK column missing its colId (regression: colId "spark" added in W4-T401)
 *   - ASSET column missing its colId (regression: colId "asset" added in W4-T401)
 *   - Header label regressions for the new columns
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
 * PLAN-0108 W4-T401 | PLAN-0114 W6 divYld (FR-12)
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render } from "@testing-library/react";
import { holdingsAgColumns, HOLDINGS_AG_COL_WIDTHS } from "../ag-holdings-columns";
import { SemanticHoldingsTable } from "../SemanticHoldingsTable";
import type { Holding } from "@/types/api";

// ── PLAN-0122 W-E (T-A-E-02): grid-ready ordering harness ────────────────────
// WHY a LOCAL enriched ag-grid mock (overrides the global vitest.setup stub for
// THIS file): the global stub has no `setColumnsVisible`, so the group layer
// no-ops under it. Here we record every applyColumnState + setColumnsVisible call
// IN ORDER so we can prove the group-visibility layer runs AFTER the state restore
// and with the right colIds. `ops` is hoisted so the mock factory can push to it.
const ops = vi.hoisted(
  () => [] as Array<{ method: string; ids?: string[]; visible?: boolean }>,
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/portfolio",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("ag-grid-react", async () => {
  const React = await import("react");
  function AgGridReact(props: Record<string, unknown>) {
    const onGridReady = props.onGridReady as ((e: unknown) => void) | undefined;
    const api = React.useRef({
      // Record restore/sort applyColumnState calls (order-sensitive).
      applyColumnState: () => ops.push({ method: "applyColumnState" }),
      // Record the group-visibility layer's calls with their colIds + visibility.
      setColumnsVisible: (ids: string[], visible: boolean) =>
        ops.push({ method: "setColumnsVisible", ids, visible }),
      getColumnState: () => [],
      flashCells: () => {},
      forEachNode: () => {},
    });
    React.useEffect(() => {
      onGridReady?.({ api: api.current });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return React.createElement("div", { "data-testid": "ag-grid-mock" });
  }
  return { AgGridReact };
});

const H: Holding = {
  holding_id: "h-1",
  portfolio_id: "p-1",
  instrument_id: "ins-1",
  entity_id: "ent-1",
  ticker: "AAPL",
  name: "Apple",
  quantity: 10,
  average_cost: 100,
  current_price: 150,
  unrealised_pnl: 500,
  unrealised_pnl_pct: 0.5,
};

// The last setColumnsVisible op tagged visible=false (the group "hide" list) and
// the last tagged visible=true excluding the locked-anchor call.
function hideIds(): string[] {
  const op = [...ops].reverse().find((o) => o.method === "setColumnsVisible" && o.visible === false);
  return op?.ids ?? [];
}
function showIds(): string[] {
  // The first visible=true call is the group "show" list; the final one is the
  // locked anchors (ticker/actions). We want the group show list.
  const op = ops.find((o) => o.method === "setColumnsVisible" && o.visible === true);
  return op?.ids ?? [];
}

// ── holdingsAgColumns — 15-column spec ───────────────────────────────────────

describe("holdingsAgColumns (16-column spec — PLAN-0122 W-D actions added)", () => {
  it("SemanticHoldingsTable has 16 columns", () => {
    // WHY 16: PLAN-0108 W4-T401 added SPARK (col 8) and ASSET (col 14) to the
    // original 12-column table (14 total). PLAN-0114 W6 FR-12 added divYld
    // (col 15). PLAN-0122 W-D added the pinned-right ACTIONS kebab (col 16). Any
    // deviation means a column was accidentally dropped or added without updating
    // this test.
    expect(holdingsAgColumns).toHaveLength(16);
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

  it("column order matches the 16-column spec — PLAN-0122 W-D actions added", () => {
    // WHY explicit order check: order matters for the trader's eye-scan path.
    // SPARK must come after DAY Δ% (col 7) and before MKT VALUE (col 9).
    // ASSET must be col 14; DIV YLD col 15; ACTIONS is last (col 16, pinned right).
    const ids = holdingsAgColumns.map((c) => c.colId);
    expect(ids).toEqual([
      "ticker",      // 1
      "name",        // 2
      "qty",         // 3
      "avg_cost",    // 4
      "current",     // 5  — header: LAST
      "dayChange",   // 6  — header: DAY Δ$
      "dayChangePct",// 7  — header: DAY Δ%
      "spark",       // 8  — SPARK
      "value",       // 9  — header: MKT VALUE
      "pnl",         // 10 — header: UNREAL $
      "pnlPct",      // 11 — header: UNREAL %
      "weight",      // 12
      "sector",      // 13
      "asset",       // 14 — ASSET
      "divYld",      // 15 — DIV YLD (PLAN-0114 W6 FR-12)
      "actions",     // 16 — NEW: ACTIONS kebab (PLAN-0122 W-D, pinned right)
    ]);
  });

  // ── PLAN-0122 W-D: ACTIONS column ─────────────────────────────────────────
  it("ACTIONS column is pinned right, locked, non-movable, non-sortable, group=core", () => {
    const actions = holdingsAgColumns.find((c) => c.colId === "actions");
    expect(actions, "actions column must exist").toBeDefined();
    // Pinned right + lockPinned true (AG Grid: `pinned` = side, `lockPinned`
    // boolean = user can't unpin) so the kebab anchors the row's right edge.
    expect(actions?.pinned).toBe("right");
    expect(actions?.lockPinned).toBe(true);
    expect(actions?.suppressMovable).toBe(true);
    expect(actions?.sortable).toBe(false);
    expect(actions?.width).toBe(40);
    // group "core" (W-E) → always present, never hideable by the column toggle.
    expect(actions?.group).toBe("core");
    expect(typeof actions?.cellRenderer).toBe("function");
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

  // ── P-1 regression: row-overlap guard (2026-06-18 design QA) ──────────────
  // The DESIGN-QA found rows 4–6 visually overlapping/double-drawing in the
  // deployed 22px-row table. Root cause: cell content was not height-clamped /
  // overflow-clipped, so a cell taller than the 22px row painted over the row
  // below. The fix attaches an overflow-hidden + fixed-height cellClass to
  // EVERY column. These tests pin that contract so a future column edit cannot
  // silently drop the clamp and reintroduce the overlap.
  describe("P-1 row-overlap guard — every cell is height-clamped + overflow-clipped", () => {
    // Helper: AG Grid cellClass may be a string, an array, or a function. For
    // this surface every clamp is a static string, so we normalise to a string.
    function cellClassString(col: (typeof holdingsAgColumns)[number]): string {
      const cc = col.cellClass;
      if (typeof cc === "string") return cc;
      if (Array.isArray(cc)) return cc.join(" ");
      return "";
    }

    it("every column defines a cellClass", () => {
      for (const col of holdingsAgColumns) {
        expect(
          col.cellClass,
          `column "${col.colId}" must set cellClass (P-1 overlap guard)`,
        ).toBeDefined();
      }
    });

    it("every column's cellClass clips overflow and pins row height", () => {
      // overflow-hidden = no child can bleed into the next row.
      // h-full = the cell box is exactly the (fixed) row height.
      for (const col of holdingsAgColumns) {
        const cls = cellClassString(col);
        expect(cls, `column "${col.colId}" must clip overflow`).toContain(
          "overflow-hidden",
        );
        expect(cls, `column "${col.colId}" must pin to the row height`).toContain(
          "h-full",
        );
      }
    });

    it("text columns drop the inherited 1.5x line-height (leading-none)", () => {
      // The >22px line box on the text cells (NAME, SECTOR) was the primary
      // source of the double-draw. leading-none collapses it so the line box
      // can never exceed the 22px row.
      for (const colId of ["name", "sector"]) {
        const col = holdingsAgColumns.find((c) => c.colId === colId)!;
        expect(cellClassString(col)).toContain("leading-none");
      }
    });
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

// ── PLAN-0122 W-E (T-A-E-02): group-visibility applied after restore ─────────
describe("SemanticHoldingsTable · column-group visibility layer (R-25/R-26)", () => {
  beforeEach(() => {
    ops.length = 0;
    window.localStorage.clear();
  });

  it("test_group_visibility_applied_after_restore: setColumnsVisible runs after applyColumnState", () => {
    render(<SemanticHoldingsTable holdings={[H]} quotes={{}} totalValue={1500} mode="advanced" />);
    const firstVisible = ops.findIndex((o) => o.method === "setColumnsVisible");
    const lastRestore = ops.map((o) => o.method).lastIndexOf("applyColumnState");
    // Group visibility must be the LAST layer — every applyColumnState (restore +
    // sort) precedes the first setColumnsVisible so the group layer wins.
    expect(firstVisible).toBeGreaterThan(-1);
    expect(lastRestore).toBeGreaterThan(-1);
    expect(firstVisible).toBeGreaterThan(lastRestore);
    // Advanced default shows the portfolio/advanced columns (not divYld).
    expect(showIds()).toEqual(expect.arrayContaining(["name", "spark", "sector"]));
    expect(showIds()).not.toContain("divYld");
  });

  it("test_simple_forces_core_only: mode=simple hides all non-Core columns", () => {
    render(<SemanticHoldingsTable holdings={[H]} quotes={{}} totalValue={1500} mode="simple" />);
    const hidden = hideIds();
    // Portfolio + Advanced groups are all hidden in Simple.
    for (const id of ["name", "dayChange", "dayChangePct", "pnlPct", "weight", "spark", "sector", "asset", "divYld"]) {
      expect(hidden).toContain(id);
    }
    // Only Core-data columns are force-shown (anchors handled by a separate call).
    expect(showIds().sort()).toEqual(["avg_cost", "current", "pnl", "qty", "value"].sort());
  });

  it("test_advanced_uses_saved_group_state: portfolio:false hides Portfolio columns", () => {
    render(
      <SemanticHoldingsTable
        holdings={[H]}
        quotes={{}}
        totalValue={1500}
        mode="advanced"
        columnGroups={{ core: true, portfolio: false, advanced: true }}
      />,
    );
    const hidden = hideIds();
    for (const id of ["name", "dayChange", "dayChangePct", "pnlPct", "weight"]) {
      expect(hidden).toContain(id);
    }
    // Advanced group still shown.
    expect(showIds()).toEqual(expect.arrayContaining(["spark", "sector", "asset"]));
  });
});
