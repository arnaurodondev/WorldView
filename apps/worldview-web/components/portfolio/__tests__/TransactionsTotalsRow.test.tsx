/**
 * components/portfolio/__tests__/TransactionsTotalsRow.test.tsx
 *
 * WHY: Unit tests for TransactionsTotalsRow aggregate calculations.
 * We test that:
 *   1. BUY COST aggregates quantity × price correctly for BUY rows
 *   2. SELL PROCEEDS aggregates correctly for SELL rows
 *   3. DIV INCOME uses tx.amount (not qty×price) for DIVIDEND rows
 *   4. FEES sums tx.fee across all row types
 *   5. NET = SELL + DIV - BUY_COST - FEES is computed correctly
 *   6. Edge case: empty list shows $0.00 for all aggregates
 *
 * PRD-0089 SA-C Task 5.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TransactionsTotalsRow } from "../TransactionsTotalsRow";
import type { Transaction } from "@/types/api";

// ── Fixture factory ────────────────────────────────────────────────────────────

function makeTx(overrides: Partial<Transaction> = {}): Transaction {
  return {
    transaction_id: `tx-${Math.random().toString(36).slice(2, 8)}`,
    portfolio_id: "p-1",
    instrument_id: "ins-1",
    ticker: "AAPL",
    asset_class: "equity",
    type: "BUY",
    quantity: 10,
    price: 100,
    fee: 1.0,
    amount: null,
    currency: "USD",
    executed_at: "2026-01-01T10:00:00Z",
    notes: null,
    ...overrides,
  } as Transaction;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * getNumericText — strips the sign + dollar sign from a testid element's text
 * and returns the numeric value, so assertions can use plain numbers.
 *
 * Example: "+$1,234.56" → 1234.56, "-$500.00" → -500, "$0.00" → 0
 */
function getNumericValue(testId: string): number {
  const el = screen.getByTestId(testId);
  const raw = el.textContent ?? "";
  // Remove $, commas, leading +; keep "-" for negatives.
  const stripped = raw.replace(/\$|,|\+/g, "").trim();
  return parseFloat(stripped);
}

// ── Test data ──────────────────────────────────────────────────────────────────
//
// 3 BUY: 10×$100=$1,000, 5×$200=$1,000, 2×$50=$100  → total BUY COST = $2,100
// 2 SELL: 10×$150=$1,500, 5×$120=$600                 → total SELL PROCEEDS = $2,100
// 1 DIV: amount=$75.00                                 → total DIV INCOME = $75
// FEES: 1.00 + 1.50 + 0.50 + 2.00 + 1.00 + 0.00 = $6.00
// NET = 2100 + 75 - 2100 - 6 = $69

const BUY_1 = makeTx({ type: "BUY", quantity: 10, price: 100, fee: 1.0 });   // $1,000
const BUY_2 = makeTx({ type: "BUY", quantity: 5, price: 200, fee: 1.5 });    // $1,000
const BUY_3 = makeTx({ type: "BUY", quantity: 2, price: 50, fee: 0.5 });     // $100
const SELL_1 = makeTx({ type: "SELL", quantity: 10, price: 150, fee: 2.0 }); // $1,500
const SELL_2 = makeTx({ type: "SELL", quantity: 5, price: 120, fee: 1.0 });  // $600
const DIV_1 = makeTx({ type: "DIVIDEND", quantity: 0, price: 0, fee: 0.0, amount: 75.0 });

const ALL_ROWS = [BUY_1, BUY_2, BUY_3, SELL_1, SELL_2, DIV_1];

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("TransactionsTotalsRow", () => {
  // ── Rendering ──────────────────────────────────────────────────────────────

  it("renders the totals strip with all five testids", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    expect(screen.getByTestId("transactions-totals-row")).toBeDefined();
    expect(screen.getByTestId("totals-row-buy")).toBeDefined();
    expect(screen.getByTestId("totals-row-sell")).toBeDefined();
    expect(screen.getByTestId("totals-row-div")).toBeDefined();
    expect(screen.getByTestId("totals-row-fees")).toBeDefined();
    expect(screen.getByTestId("totals-row-net")).toBeDefined();
  });

  // ── BUY COST ───────────────────────────────────────────────────────────────

  it("sums BUY cost as quantity × price for all BUY rows", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    // 10×100 + 5×200 + 2×50 = 1000 + 1000 + 100 = 2100
    const buyCost = getNumericValue("totals-row-buy");
    expect(buyCost).toBeCloseTo(2100, 1);
  });

  it("BUY COST is $0 when no BUY transactions in the filtered set", () => {
    const noBuys = [SELL_1, SELL_2, DIV_1];
    render(<TransactionsTotalsRow filtered={noBuys} />);
    const buyCost = getNumericValue("totals-row-buy");
    expect(buyCost).toBeCloseTo(0, 1);
  });

  // ── SELL PROCEEDS ──────────────────────────────────────────────────────────

  it("sums SELL proceeds as quantity × price for all SELL rows", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    // 10×150 + 5×120 = 1500 + 600 = 2100
    const sellProceeds = getNumericValue("totals-row-sell");
    expect(sellProceeds).toBeCloseTo(2100, 1);
  });

  // ── DIV INCOME ─────────────────────────────────────────────────────────────

  it("sums DIV income from tx.amount (not quantity × price)", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    // Only DIV_1: amount = $75.00
    const divIncome = getNumericValue("totals-row-div");
    expect(divIncome).toBeCloseTo(75, 1);
  });

  it("treats DIVIDEND with null amount as $0 contribution", () => {
    const divNull = makeTx({ type: "DIVIDEND", quantity: 0, price: 0, amount: null, fee: 0 });
    render(<TransactionsTotalsRow filtered={[divNull]} />);
    const divIncome = getNumericValue("totals-row-div");
    expect(divIncome).toBeCloseTo(0, 1);
  });

  // ── FEES ───────────────────────────────────────────────────────────────────

  it("sums fees across all transaction types", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    // BUY: 1.0 + 1.5 + 0.5 = 3.0; SELL: 2.0 + 1.0 = 3.0; DIV: 0.0 → total = 6.0
    const fees = getNumericValue("totals-row-fees");
    expect(fees).toBeCloseTo(6.0, 1);
  });

  // ── NET ────────────────────────────────────────────────────────────────────

  it("computes NET = SELL + DIV − BUY_COST − FEES", () => {
    render(<TransactionsTotalsRow filtered={ALL_ROWS} />);
    // 2100 + 75 - 2100 - 6 = 69
    const net = getNumericValue("totals-row-net");
    expect(net).toBeCloseTo(69, 1);
  });

  it("shows positive NET with a + prefix when SELL+DIV outweigh BUY+FEES", () => {
    // Single SELL with large proceeds to guarantee positive NET.
    const bigSell = makeTx({ type: "SELL", quantity: 100, price: 500, fee: 1.0 });
    render(<TransactionsTotalsRow filtered={[bigSell]} />);
    const netEl = screen.getByTestId("totals-row-net");
    // net = 50000 - 0 - 0 - 1 = 49999 → should have "+" prefix
    expect(netEl.textContent).toContain("+");
  });

  it("shows negative NET when BUY cost exceeds all inflows", () => {
    // Single BUY — no sells, no dividends. NET = 0 + 0 - (10×100) - 1 = -1001
    render(<TransactionsTotalsRow filtered={[BUY_1]} />);
    const netEl = screen.getByTestId("totals-row-net");
    expect(netEl.textContent).toContain("-");
  });

  // ── Edge cases ─────────────────────────────────────────────────────────────

  it("renders all $0.00 with empty filtered list", () => {
    render(<TransactionsTotalsRow filtered={[]} />);
    // All values should be zero.
    expect(getNumericValue("totals-row-buy")).toBe(0);
    expect(getNumericValue("totals-row-sell")).toBe(0);
    expect(getNumericValue("totals-row-div")).toBe(0);
    expect(getNumericValue("totals-row-fees")).toBe(0);
    // NET with all zeros: 0 + 0 - 0 - 0 = 0 → no +/- prefix (formatPrice("$0.00"))
    const netEl = screen.getByTestId("totals-row-net");
    // When net === 0, component renders no sign ("$0.00")
    expect(netEl.textContent).toContain("0");
  });
});
