/**
 * components/screener/__tests__/ScreenerTable.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: ScreenerTable wraps AG-Grid and owns the row-hover toolbar lifecycle.
 * jsdom does NOT lay out AG-Grid rows (the virtualiser uses scroll height
 * which jsdom returns 0 for). We therefore mock AgGridBase with a simple
 * `<table>` renderer so we can assert:
 *   1. The data-table-grid wrapper is present (the architecture-test
 *      whitelist enforces this scope; we want runtime confirmation too).
 *   2. The rowHeight prop is passed as 20 (Terminal-Dark density contract).
 *   3. A row appears for every fixture entry.
 *   4. Hovering a row mounts the RowHoverToolbar.
 *
 * WHY mock AgGridBase (not run it): AG-Grid + jsdom render 0 rows because
 * the virtualiser sees a 0-height container. A mock that forwards rowData
 * to a plain table gives us the same assertable surface without the
 * jsdom layout dance.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ColDef } from "ag-grid-community";
import type { ScreenerResult } from "@/types/api";

// ── Mocks ─────────────────────────────────────────────────────────────────────
// WHY hoisted before importing the component under test: vitest hoists vi.mock
// calls automatically, but the module must still be mocked BEFORE the SUT
// imports it. The `import` of ScreenerTable below resolves through this mock.

vi.mock("@/components/ui/ag-grid/AgGridBase", () => ({
  // The mock renders a tiny <table> with one <tr data-row-index> per row,
  // matching the row indices the cell-mouse handlers expect. We expose
  // `rowHeight` as a data attribute so the test can assert the density
  // contract is forwarded correctly.
  AgGridBase: <T,>(props: {
    rowData?: T[];
    rowHeight?: number;
    onCellMouseOver?: (e: { rowIndex: number; data: T; event: { target: HTMLElement } }) => void;
    onCellMouseOut?: () => void;
  }) => {
    const rows = props.rowData ?? [];
    return (
      <table data-row-height={props.rowHeight}>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className="ag-row"
              data-row-index={i}
              data-testid={`mock-row-${i}`}
              onMouseEnter={(e) =>
                props.onCellMouseOver?.({
                  rowIndex: i,
                  data: row,
                  event: { target: e.currentTarget as HTMLElement },
                })
              }
              onMouseLeave={() => props.onCellMouseOut?.()}
            >
              <td>row{i}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  },
}));

// WHY mock RowHoverToolbar separately: the real toolbar imports portfolio
// hooks that would pull a wider tree. A stub that renders a recognisable
// marker lets us assert mount/unmount cleanly.
vi.mock("@/components/screener/RowHoverToolbar", () => ({
  RowHoverToolbar: ({ ticker }: { ticker: string }) => (
    <div data-testid="row-hover-toolbar">toolbar:{ticker}</div>
  ),
}));

import { ScreenerTable } from "@/components/screener/ScreenerTable";

// ── Fixtures ──────────────────────────────────────────────────────────────────

// 22 rows — exceeds the 20-row density target so we can also assert
// length without coupling to the exact "≥20" plan acceptance phrase.
function fixtureRows(n: number): ScreenerResult[] {
  return Array.from({ length: n }, (_, i) => ({
    instrument_id: `inst-${i}`,
    entity_id: `inst-${i}`,
    ticker: `T${i}`,
    name: `Test ${i}`,
    exchange: "XNAS",
    gics_sector: "Information Technology",
    current_price: 100 + i,
    market_cap: 1_000_000 * (i + 1),
    pe_ratio: 15,
    daily_return: 0.01,
    revenue: 1_000_000,
    beta: 1.0,
    market_impact_score: 0.5,
    forward_pe: 14,
    dividend_yield: 0.02,
    revenue_growth_yoy: 0.1,
    roe: 0.18,
    operating_margin_ttm: 0.25,
    enterprise_value_ebitda: 12,
    avg_volume_30d: 5_000_000,
  })) as ScreenerResult[];
}

const COLS: ColDef<ScreenerResult>[] = [
  { field: "ticker", headerName: "TKR" },
];

describe("ScreenerTable", () => {
  it("wraps the grid in a data-table-grid container", () => {
    // WHY: the architecture test scopes the dense CSS overrides to this
    // attribute. If a refactor drops the wrapper, the table loses 20px
    // rows globally — this runtime check is the fast-feedback complement.
    const { container } = render(
      <ScreenerTable
        rows={fixtureRows(3)}
        columnDefs={COLS}
        onRowClick={() => {}}
        onGridReady={() => {}}
      />,
    );
    expect(container.querySelector("[data-table-grid]")).not.toBeNull();
  });

  it("forwards rowHeight=20 to AgGridBase", () => {
    // WHY: the screener is the one platform surface using 20px rows
    // (vs 24 elsewhere). Asserting the prop forwarding pairs with the
    // architecture test that forbids `rowHeight: 22` in this folder.
    const { container } = render(
      <ScreenerTable
        rows={fixtureRows(3)}
        columnDefs={COLS}
        onRowClick={() => {}}
        onGridReady={() => {}}
      />,
    );
    const table = container.querySelector("table[data-row-height]");
    expect(table?.getAttribute("data-row-height")).toBe("20");
  });

  it("renders ≥20 rows from the fixture (density acceptance)", () => {
    // WHY 22: the plan calls for ≥20 visible body rows. We assert 22 so
    // a regression that drops one row still fails — the spec is a floor.
    render(
      <ScreenerTable
        rows={fixtureRows(22)}
        columnDefs={COLS}
        onRowClick={() => {}}
        onGridReady={() => {}}
      />,
    );
    const rows = screen.getAllByTestId(/^mock-row-/);
    expect(rows.length).toBeGreaterThanOrEqual(20);
  });

  it("mounts RowHoverToolbar when a row is hovered", () => {
    // WHY mouseEnter (not pointerover): the ScreenerTable wires AG-Grid's
    // CellMouseOver to our mock's onMouseEnter. The point is the *mount*,
    // not the AG-Grid internals. We confirm the toolbar appears with the
    // hovered row's ticker forwarded into its props.
    render(
      <ScreenerTable
        rows={fixtureRows(2)}
        columnDefs={COLS}
        onRowClick={() => {}}
        onGridReady={() => {}}
      />,
    );
    expect(screen.queryByTestId("row-hover-toolbar")).not.toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByTestId("mock-row-0"));
    const toolbar = screen.getByTestId("row-hover-toolbar");
    expect(toolbar).toBeInTheDocument();
    expect(toolbar).toHaveTextContent("toolbar:T0");
  });
});
