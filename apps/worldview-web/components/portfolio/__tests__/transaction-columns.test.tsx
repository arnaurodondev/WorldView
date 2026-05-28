/**
 * components/portfolio/__tests__/transaction-columns.test.ts
 *
 * WHY: Unit tests for makeTransactionColumns + exported helper functions.
 * These run as pure unit tests (no DOM mount) so they're fast and resilient
 * to layout changes. They pin the contracts that TransactionsTable depends on.
 *
 * PLAN-0059 F-1 — DataTable migration tests (≥3 per migrated table).
 */

import type React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import type { CellContext, ColumnDef } from "@tanstack/react-table";
import {
  makeTransactionColumns,
  typeBadgeClass,
  assetClassAbbrev,
  assetClassBadgeClass,
  rowTotal,
  type TransactionRow,
} from "../transaction-columns";
import type { Transaction } from "@/types/api";

function makeTx(overrides: Partial<Transaction> = {}): Transaction {
  return {
    transaction_id: "tx-1",
    portfolio_id: "p-1",
    instrument_id: "ins-1",
    ticker: "AAPL",
    asset_class: null,
    type: "BUY",
    quantity: 10,
    price: 150,
    fee: 1.5,
    amount: null,
    currency: "USD",
    executed_at: "2026-05-01T10:00:00Z",
    notes: null,
    ...overrides,
  } as Transaction;
}

/**
 * Render a column's cell function with a minimal CellContext stub.
 *
 * WHY: TanStack's CellContext carries internal table state we don't need.
 * The ticker column's cell renderer only touches `row.original`, so we
 * stub just that and cast through `unknown` to satisfy TS.
 */
function renderCell(col: ColumnDef<TransactionRow>, row: TransactionRow) {
  const cell = col.cell as (ctx: CellContext<TransactionRow, unknown>) => unknown;
  const ctx = { row: { original: row } } as unknown as CellContext<
    TransactionRow,
    unknown
  >;
  return render(<>{cell(ctx) as React.ReactNode}</>);
}

/** Build a TransactionRow (Transaction + runningBalance) for cell rendering. */
function makeRow(overrides: Partial<TransactionRow> = {}): TransactionRow {
  return {
    ...makeTx(),
    runningBalance: 0,
    ...overrides,
  } as TransactionRow;
}

/** Find the ticker column from the factory output. */
function getTickerColumn() {
  const cols = makeTransactionColumns();
  const col = cols.find((c) => c.id === "ticker");
  if (!col) throw new Error("ticker column not found");
  return col;
}

// ── makeTransactionColumns ───────────────────────────────────────────────────

describe("makeTransactionColumns", () => {
  it("returns exactly 13 columns (8 original + 5 new from PRD-0089 SA-C)", () => {
    // WHY 13: PRD-0089 SA-C added TIME, NAME, FX, CASH_IMPACT, BAL to the
    // original 8 columns (DATE, TYPE, CLASS, TICKER, QTY, PRICE, TOTAL, FEE).
    const cols = makeTransactionColumns();
    expect(cols).toHaveLength(13);
  });

  it("column ids match the expected order (8 original + 5 new)", () => {
    const cols = makeTransactionColumns();
    const ids = cols.map((c) => c.id);
    expect(ids).toEqual([
      // Original 8 (PLAN-0059 F-1 contract preserved)
      "executed_at",
      "type",
      "asset_class",
      "ticker",
      "quantity",
      "price",
      "total",
      "fee",
      // 5 new columns (PRD-0089 SA-C)
      "time",
      "name",
      "fx",
      "cash_impact",
      "bal",
    ]);
  });

  it("accessorKey is set on all direct-field columns", () => {
    const cols = makeTransactionColumns();
    const byId = Object.fromEntries(cols.map((c) => [c.id, c]));
    // Direct field columns must have accessorKey.
    expect((byId["executed_at"] as { accessorKey?: string }).accessorKey).toBe("executed_at");
    expect((byId["type"] as { accessorKey?: string }).accessorKey).toBe("type");
    expect((byId["asset_class"] as { accessorKey?: string }).accessorKey).toBe("asset_class");
    expect((byId["quantity"] as { accessorKey?: string }).accessorKey).toBe("quantity");
    expect((byId["price"] as { accessorKey?: string }).accessorKey).toBe("price");
    expect((byId["fee"] as { accessorKey?: string }).accessorKey).toBe("fee");
  });

  it("ticker and total columns have no accessorKey (computed fields)", () => {
    const cols = makeTransactionColumns();
    const byId = Object.fromEntries(cols.map((c) => [c.id, c]));
    expect((byId["ticker"] as { accessorKey?: string }).accessorKey).toBeUndefined();
    expect((byId["total"] as { accessorKey?: string }).accessorKey).toBeUndefined();
  });

  it("ticker and total columns disable sorting (no stable sort key)", () => {
    const cols = makeTransactionColumns();
    const byId = Object.fromEntries(cols.map((c) => [c.id, c]));
    expect(byId["ticker"].enableSorting).toBe(false);
    expect(byId["total"].enableSorting).toBe(false);
  });
});

// ── typeBadgeClass ───────────────────────────────────────────────────────────

describe("typeBadgeClass", () => {
  it("BUY uses the positive (green) palette", () => {
    expect(typeBadgeClass("BUY")).toContain("text-positive");
  });

  it("SELL uses the negative (red) palette", () => {
    expect(typeBadgeClass("SELL")).toContain("text-negative");
  });

  it("DIVIDEND uses the primary (blue) palette", () => {
    expect(typeBadgeClass("DIVIDEND")).toContain("text-primary");
  });
});

// ── assetClassAbbrev ─────────────────────────────────────────────────────────

describe("assetClassAbbrev", () => {
  it("returns EQ for equity", () => {
    expect(assetClassAbbrev("equity")).toBe("EQ");
    expect(assetClassAbbrev("EQUITY")).toBe("EQ"); // case-insensitive
  });

  it("returns OPT for option", () => {
    expect(assetClassAbbrev("option")).toBe("OPT");
  });

  it("returns — for null/undefined/unknown", () => {
    expect(assetClassAbbrev(null)).toBe("—");
    expect(assetClassAbbrev(undefined)).toBe("—");
    expect(assetClassAbbrev("unknown")).toBe("—");
  });
});

// ── assetClassBadgeClass ─────────────────────────────────────────────────────

describe("assetClassBadgeClass", () => {
  it("equity uses the positive palette", () => {
    expect(assetClassBadgeClass("equity")).toContain("text-positive");
  });

  it("option uses the negative palette (red — high-risk instrument)", () => {
    expect(assetClassBadgeClass("option")).toContain("text-negative");
  });

  it("null/unknown renders muted (not alarming)", () => {
    expect(assetClassBadgeClass(null)).toContain("text-muted-foreground");
    expect(assetClassBadgeClass("unknown")).toContain("text-muted-foreground");
  });

  it("all six known classes return truthy class strings", () => {
    const classes = ["equity", "etf", "option", "future", "bond", "crypto"] as const;
    for (const cls of classes) {
      expect(assetClassBadgeClass(cls)).toBeTruthy();
    }
  });
});

// ── rowTotal ─────────────────────────────────────────────────────────────────

describe("rowTotal", () => {
  it("returns quantity × price for BUY", () => {
    const tx = makeTx({ type: "BUY", quantity: 10, price: 150 });
    expect(rowTotal(tx)).toBe(1500);
  });

  it("returns quantity × price for SELL", () => {
    const tx = makeTx({ type: "SELL", quantity: 5, price: 400 });
    expect(rowTotal(tx)).toBe(2000);
  });

  it("returns tx.amount for DIVIDEND (not qty×price)", () => {
    const tx = makeTx({ type: "DIVIDEND", quantity: 0, price: 0, amount: 25 });
    expect(rowTotal(tx)).toBe(25);
  });

  it("returns 0 for DIVIDEND with null amount", () => {
    const tx = makeTx({ type: "DIVIDEND", quantity: 0, price: 0, amount: null });
    expect(rowTotal(tx)).toBe(0);
  });
});

// ── ticker column cell — description subline (F-004a) ────────────────────────
//
// WHY these tests: the description field (broker-supplied narrative) is
// rendered as a 9px subline under the ticker. Coverage was missing for the
// branch where description is populated — F-004a in the QA report.

describe("ticker column — description subline", () => {
  it("renders description as 9px subline when present", () => {
    const col = getTickerColumn();
    const row = makeRow({ description: "Dividend Payment - AAPL" });
    const { getByText, getByTitle } = renderCell(col, row);
    expect(getByText("Dividend Payment - AAPL")).toBeInTheDocument();
    // The title= attribute is set on the subline wrapper for accessibility
    // (hover tooltip when the text is truncated by the max-w-[160px] clamp).
    expect(getByTitle("Dividend Payment - AAPL")).toBeInTheDocument();
  });

  it("does not render description subline when null", () => {
    const col = getTickerColumn();
    const row = makeRow({ description: null });
    const { queryByText } = renderCell(col, row);
    expect(queryByText(/Dividend Payment/)).not.toBeInTheDocument();
  });

  it("truncates the title= attribute to 500 chars (defense-in-depth, M-004)", () => {
    // WHY: server-side Pydantic enforces max_length=500; this client-side
    // slice is belt-and-braces against any unexpected backfill row that
    // could otherwise bloat the DOM with a multi-KB title attribute.
    const longDesc = "A".repeat(1000);
    const col = getTickerColumn();
    const row = makeRow({ description: longDesc });
    const { getByTitle } = renderCell(col, row);
    expect(getByTitle("A".repeat(500))).toBeInTheDocument();
  });
});
