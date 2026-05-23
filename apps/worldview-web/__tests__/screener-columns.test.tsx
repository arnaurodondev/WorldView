/**
 * __tests__/screener-columns.test.tsx — Unit tests for createScreenerColumns factory
 *
 * WHY THIS EXISTS: The column factory is the rendering core of the screener table.
 * Bugs here show up as wrong number formats (34.62 instead of 34.6), missing "—"
 * for null values, or wrong directional classes on the CHG% cell. All three
 * classes of bugs are invisible until a trader screams at the terminal.
 *
 * Tested invariants:
 *   1. Correct column count (13 columns defined)
 *   2. P/E renders "—" for null and "34.6" for 34.6223 (one-decimal format)
 *   3. CHG% cell has bg-positive class when positive, bg-negative when negative
 *
 * WHY renderHook + flexRender: ColumnDef.cell is a function that TanStack calls
 * with a CellContext argument. We bypass the full table instantiation by calling
 * the cell function directly with a minimal mock context.
 *
 * DATA SOURCE: components/screener/screener-columns.tsx
 * DESIGN REFERENCE: PRD-0031 §7 Screener columns
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { createScreenerColumns } from "@/components/screener/screener-columns";
import type { ScreenerResult } from "@/types/api";
import type { CellContext } from "@tanstack/react-table";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * makeRow — minimal ScreenerResult with all nullable fields set to null.
 * Tests override specific fields to isolate each scenario.
 */
function makeRow(overrides: Partial<ScreenerResult> = {}): ScreenerResult {
  return {
    instrument_id: "uuid-001",
    entity_id: "uuid-001",
    ticker: "TEST",
    name: "Test Corp",
    exchange: null,
    gics_sector: null,
    current_price: null,
    market_cap: null,
    pe_ratio: null,
    daily_return: null,
    revenue: null,
    beta: null,
    market_impact_score: null,
    ...overrides,
  } as ScreenerResult;
}

/**
 * makeCellContext — minimal TanStack CellContext stub.
 * Only `row.original` is used by our cell renderers. Cast via unknown to avoid
 * satisfying the full generic CellContext shape in tests.
 */
function makeCellContext(row: ScreenerResult): CellContext<ScreenerResult, unknown> {
  return {
    row: { original: row } as unknown as CellContext<ScreenerResult, unknown>["row"],
    cell: {} as CellContext<ScreenerResult, unknown>["cell"],
    column: {} as CellContext<ScreenerResult, unknown>["column"],
    getValue: (() => undefined) as CellContext<ScreenerResult, unknown>["getValue"],
    renderValue: (() => undefined) as CellContext<ScreenerResult, unknown>["renderValue"],
    table: {} as CellContext<ScreenerResult, unknown>["table"],
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("createScreenerColumns — column count", () => {
  it("creates exactly 18 column definitions", () => {
    const cols = createScreenerColumns({});
    // WHY 18 (PLAN-0092 Wave C): 15 default-visible (ticker, name, sector, price,
    // change, marketCap, pe, revenueGrowth, forwardPe, divYield, roe, beta, score,
    // range52w, sparkline) + 3 opt-in hidden (opMargin, evEbitda, avgVol).
    // A count mismatch means a column was accidentally removed or added — both
    // break the terminal-density layout and trigger a QA alert.
    expect(cols).toHaveLength(18);
  });

  it("includes all expected column IDs", () => {
    const cols = createScreenerColumns({});
    const ids = cols.map((c) => c.id);
    expect(ids).toContain("ticker");
    expect(ids).toContain("pe");
    expect(ids).toContain("change");
    expect(ids).toContain("sparkline");
    expect(ids).toContain("range52w");
  });
});

describe("createScreenerColumns — P/E cell rendering", () => {
  const cols = createScreenerColumns({});
  const peCol = cols.find((c) => c.id === "pe")!;
  // TypeScript: cell is a function if defined, otherwise string | undefined
  const cellFn = typeof peCol.cell === "function" ? peCol.cell : null;

  it("renders '—' (em-dash) for null P/E", () => {
    if (!cellFn) throw new Error("pe cell is not a function");
    const row = makeRow({ pe_ratio: null });
    const { container } = render(<>{cellFn(makeCellContext(row))}</>);
    expect(container.textContent).toBe("—");
  });

  it("renders one-decimal string for 34.6223", () => {
    if (!cellFn) throw new Error("pe cell is not a function");
    const row = makeRow({ pe_ratio: 34.6223 });
    const { container } = render(<>{cellFn(makeCellContext(row))}</>);
    // WHY .toFixed(1): P/E is displayed to one decimal. 34.6223 → "34.6".
    // Two decimals (34.62) would clutter the compact 60px column.
    expect(container.textContent).toBe("34.6");
  });
});

describe("createScreenerColumns — CHG% cell rendering", () => {
  const cols = createScreenerColumns({});
  const changeCol = cols.find((c) => c.id === "change")!;
  const cellFn = typeof changeCol.cell === "function" ? changeCol.cell : null;

  it("applies positive class when daily_return > 0", () => {
    if (!cellFn) throw new Error("change cell is not a function");
    const row = makeRow({ daily_return: 0.023 }); // +2.30%
    const { container } = render(<>{cellFn(makeCellContext(row))}</>);
    const span = container.querySelector("span");
    // WHY bg-positive/10: institutional convention for up moves (green tint bg)
    expect(span?.className).toContain("bg-positive");
    expect(span?.className).not.toContain("bg-negative");
    expect(span?.textContent).toBe("+2.30%");
  });

  it("applies negative class when daily_return < 0", () => {
    if (!cellFn) throw new Error("change cell is not a function");
    const row = makeRow({ daily_return: -0.0147 }); // -1.47%
    const { container } = render(<>{cellFn(makeCellContext(row))}</>);
    const span = container.querySelector("span");
    // WHY bg-negative/10: red tint bg for down moves
    expect(span?.className).toContain("bg-negative");
    expect(span?.className).not.toContain("bg-positive");
    expect(span?.textContent).toBe("-1.47%");
  });

  it("renders '—' for null daily_return", () => {
    if (!cellFn) throw new Error("change cell is not a function");
    const row = makeRow({ daily_return: null });
    const { container } = render(<>{cellFn(makeCellContext(row))}</>);
    expect(container.textContent).toBe("—");
  });
});
