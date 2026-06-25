/**
 * components/ui/ag-grid/__tests__/AgGridBase.test.tsx
 *
 * WHY THIS EXISTS (Round-2 cross-surface request, item 1): AgGridBase grew
 * optional `rowHeight` / `headerHeight` props so tables can adopt the
 * `--data-row-height: 22px` density token (DESIGN_SYSTEM.md §2.1 / §15.10).
 * These tests pin two contracts every surface owner relies on when adopting:
 *
 *   1. DEFAULT: omitting the props yields the historical 28/28 — guaranteeing
 *      zero visual change for the dozens of existing call sites.
 *   2. PASSTHROUGH: an explicit value reaches the underlying AgGridReact
 *      untouched (no clamping, no off-by-one "helpful" adjustments).
 *
 * MOCK STRATEGY: the global vitest.setup.ts mock renders a semantic <table>
 * but DROPS rowHeight/headerHeight (they are layout-only props with no jsdom
 * representation). We register a test-local vi.mock that overrides the global
 * one for THIS FILE ONLY, echoing the received props as data-* attributes so
 * the assertions can read exactly what AgGridReact was given. This is the
 * standard "spy component" pattern — we test OUR wrapper's prop plumbing, not
 * AG Grid's internal rendering (which needs real browser layout APIs).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Test-local override of the global ag-grid-react mock (vitest gives the
// test file's vi.mock precedence over setup-file mocks for the same module).
vi.mock("ag-grid-react", () => ({
  AgGridReact: (props: Record<string, unknown>) => (
    <div
      data-testid="ag-grid-spy"
      // String() because data-* attributes coerce numbers anyway; explicit
      // conversion keeps the assertion intent obvious.
      data-row-height={String(props.rowHeight)}
      data-header-height={String(props.headerHeight)}
      data-theme={String(props.theme)}
    />
  ),
}));

// Import AFTER the mock declaration (vi.mock is hoisted, but keeping the
// import below documents the dependency for human readers).
import { AgGridBase } from "@/components/ui/ag-grid/AgGridBase";

/** Minimal row shape — the grid generics only need *some* object type. */
interface Row {
  ticker: string;
}

const rows: Row[] = [{ ticker: "AAPL" }];
const cols = [{ field: "ticker" as const, headerName: "TICKER" }];

describe("AgGridBase row/header height props", () => {
  it("defaults to the historical 28px row and header heights when omitted", () => {
    render(<AgGridBase<Row> rowData={rows} columnDefs={cols} />);

    const grid = screen.getByTestId("ag-grid-spy");
    // WHY assert both: a regression that changes ONE default (e.g. a global
    // find-replace to 22) would silently reflow every non-adopting table.
    expect(grid).toHaveAttribute("data-row-height", "28");
    expect(grid).toHaveAttribute("data-header-height", "28");
  });

  it("passes explicit rowHeight/headerHeight through to AgGridReact unchanged", () => {
    // 22 = the --data-row-height token value (DESIGN_SYSTEM.md §2.1); 24 is an
    // arbitrary distinct header value proving the two props are independent.
    render(
      <AgGridBase<Row>
        rowData={rows}
        columnDefs={cols}
        rowHeight={22}
        headerHeight={24}
      />,
    );

    const grid = screen.getByTestId("ag-grid-spy");
    expect(grid).toHaveAttribute("data-row-height", "22");
    expect(grid).toHaveAttribute("data-header-height", "24");
  });

  it("keeps the legacy CSS theme pinned regardless of height overrides", () => {
    // WHY: P0-2 (PLAN-0088) — theme="legacy" is what makes the CSS-var theming
    // work at all. A refactor of the props plumbing must never drop it, or
    // every grid renders white-on-white in production while tests still pass.
    render(<AgGridBase<Row> rowData={rows} columnDefs={cols} rowHeight={22} />);

    expect(screen.getByTestId("ag-grid-spy")).toHaveAttribute("data-theme", "legacy");
  });
});
