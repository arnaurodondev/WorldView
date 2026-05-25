/**
 * components/portfolio/__tests__/transaction-columns.test.ts
 *
 * WHY: Unit tests for makeTransactionColumns + exported helper functions.
 * These run as pure unit tests (no DOM mount) so they're fast and resilient
 * to layout changes. They pin the contracts that TransactionsTable depends on.
 *
 * PLAN-0059 F-1 — DataTable migration tests (≥3 per migrated table).
 */

import { describe, it, expect } from "vitest";
import {
  makeTransactionColumns,
  typeBadgeClass,
  assetClassAbbrev,
  assetClassBadgeClass,
  rowTotal,
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
