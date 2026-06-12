/**
 * StatementTable.test.tsx — presentational contracts for one statement table
 * (Wave-2 redesign; absorbs the render-level assertions of the deleted
 * IncomeStatementTable suite and the StatementMiniTable behaviours that were
 * previously only pinned indirectly through FinancialStatementsPanel).
 *
 * CONTRACTS:
 *   1. One <th> per period column (the old "4 FY headers for 4 ANNUAL
 *      records" contract, generalised) + YoY + trend headers.
 *   2. Row labels render for every configured line item.
 *   3. Values are scaled by the SHARED unit and the unit label renders once
 *      in the table caption (scope item 2).
 *   4. Null values render the em-dash (absence, not zero).
 *   5. YoY cells colour-code by direction; suppressed YoY renders "—".
 *   6. Sparkline microcharts render only on flagged rows (scope item 3).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { StatementTable } from "@/components/instrument/financials/statements/StatementTable";
import type { StatementTableView } from "@/components/instrument/financials/statements/statementData";

// ── Fixture ──────────────────────────────────────────────────────────────────

/** Hand-built view: 4 FY columns, USD-billions unit, mixed rows. */
const VIEW: StatementTableView = {
  columns: [
    { key: "2022-09-30", label: "FY22" },
    { key: "2023-09-30", label: "FY23" },
    { key: "2024-09-30", label: "FY24" },
    { key: "2025-09-30", label: "FY25" },
  ],
  unit: { label: "USD B", divisor: 1e9 },
  rows: [
    {
      label: "Revenue",
      values: [300e9, 350e9, 380e9, 394.3e9],
      yoyPct: 0.0376,
      spark: [90e9, 95e9, 100e9, 109.3e9],
    },
    {
      label: "Net Income",
      values: [80e9, 90e9, 100e9, 75e9],
      yoyPct: -0.25,
      spark: null,
    },
    {
      // Absent line item: all nulls + suppressed YoY.
      label: "EBITDA",
      values: [null, null, null, null],
      yoyPct: null,
      spark: null,
    },
  ],
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("StatementTable", () => {
  it("renders one column header per period (FY22..FY25) plus YoY and trend", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    for (const label of ["FY22", "FY23", "FY24", "FY25"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("YOY Δ")).toBeInTheDocument();
    expect(screen.getByText("Quarterly trend")).toBeInTheDocument(); // sr-only
  });

  it("renders every row label", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Net Income")).toBeInTheDocument();
    expect(screen.getByText("EBITDA")).toBeInTheDocument();
  });

  it("scales values by the shared unit and renders the unit label once", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    // 394.3e9 / 1e9 → "394.3" (bare scaled number, no per-cell "$…B").
    expect(screen.getByText("394.3")).toBeInTheDocument();
    expect(screen.queryByText("$394.3B")).not.toBeInTheDocument();
    // The shared unit caption.
    expect(screen.getByTestId("statement-unit-income-statement")).toHaveTextContent("USD B");
  });

  it("renders em-dashes for null values and suppressed YoY", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    // EBITDA row: 4 value dashes + 1 YoY dash = 5 em-dashes minimum.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
  });

  it("colour-codes YoY deltas by direction", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    expect(screen.getByText("+3.8%").className).toContain("text-positive");
    expect(screen.getByText("-25.0%").className).toContain("text-negative");
  });

  it("renders a sparkline only on flagged rows", () => {
    render(<StatementTable title="INCOME STATEMENT" view={VIEW} />);
    // Exactly one row carries a spark series → exactly one trend SVG.
    expect(screen.getAllByRole("img", { name: /quarterly trend/i })).toHaveLength(1);
  });
});
