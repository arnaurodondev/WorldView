/**
 * components/portfolio/detail/__tests__/TransactionsLedger.test.tsx
 *
 * WHY THIS EXISTS: Wave G requirement — "Write Vitest unit test for
 * TransactionsLedger column rendering (mock 3 rows of data)."
 *
 * Tests:
 *   1. Renders all 3 mock transactions as table rows.
 *   2. DATE column shows YYYY-MM-DD.
 *   3. TYPE badge shows "BUY", "SELL", "DIV" correctly.
 *   4. TICKER column shows the correct ticker symbol.
 *   5. GROSS column shows correct quantity × price for BUY/SELL.
 *   6. GROSS column shows amount for DIVIDEND rows.
 *   7. FEE column shows negative fees correctly.
 *   8. CASH IMPACT column is positive for SELL, negative for BUY.
 *   9. Empty state renders when transactions is [].
 *  10. Filter-empty state renders when tickerFilter produces no matches.
 *  11. Totals row renders in <tfoot>.
 *  12. Column sort: clicking DATE header reverses the row order.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TransactionsLedger } from "../TransactionsLedger";
import type { Transaction } from "@/types/api";

// ── Fixture factory ────────────────────────────────────────────────────────────

function makeTx(overrides: Partial<Transaction>): Transaction {
  return {
    transaction_id: `tx-${Math.random().toString(36).slice(2, 9)}`,
    portfolio_id: "p-1",
    instrument_id: "ins-1",
    ticker: "AAPL",
    asset_class: "equity",
    type: "BUY",
    quantity: 10,
    price: 100.0,
    fee: 0.99,
    amount: null,
    currency: "USD",
    executed_at: "2026-05-19T14:32:00Z",
    notes: null,
    ...overrides,
  };
}

// ── Test rows (3 rows as required by the spec) ────────────────────────────────

const TX_BUY = makeTx({
  transaction_id: "tx-buy-1",
  ticker: "AAPL",
  type: "BUY",
  quantity: 100,
  price: 187.32,
  fee: 0.99,
  amount: null,
  executed_at: "2026-05-19T14:32:00Z",
});

const TX_SELL = makeTx({
  transaction_id: "tx-sell-1",
  ticker: "NVDA",
  instrument_id: "ins-nvda",
  type: "SELL",
  quantity: 30,
  price: 895.12,
  fee: 0.99,
  amount: null,
  executed_at: "2026-05-18T15:45:00Z",
});

const TX_DIV = makeTx({
  transaction_id: "tx-div-1",
  ticker: "MSFT",
  instrument_id: "ins-msft",
  type: "DIVIDEND",
  quantity: 0,
  price: 0,
  fee: 0,
  amount: 98.0,
  executed_at: "2026-05-19T09:01:00Z",
});

const THREE_ROWS = [TX_BUY, TX_SELL, TX_DIV];

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("TransactionsLedger", () => {

  // 1. Renders all 3 rows
  it("renders all 3 mock transaction rows", () => {
    render(<TransactionsLedger transactions={THREE_ROWS} />);
    // Each row is identified by data-testid="ledger-row-{id}"
    expect(screen.getByTestId("ledger-row-tx-buy-1")).toBeDefined();
    expect(screen.getByTestId("ledger-row-tx-sell-1")).toBeDefined();
    expect(screen.getByTestId("ledger-row-tx-div-1")).toBeDefined();
  });

  // 2. DATE column shows YYYY-MM-DD
  it("shows YYYY-MM-DD date in the DATE column", () => {
    render(<TransactionsLedger transactions={[TX_BUY]} />);
    // TX_BUY.executed_at = "2026-05-19T14:32:00Z"
    // Date column should show "2026-05-19"
    expect(screen.getByTestId("ledger-row-tx-buy-1").textContent).toContain(
      "2026-05-19",
    );
  });

  // 3. TYPE badges
  it("shows BUY badge for a BUY transaction", () => {
    render(<TransactionsLedger transactions={[TX_BUY]} />);
    const row = screen.getByTestId("ledger-row-tx-buy-1");
    expect(row.textContent).toContain("BUY");
  });

  it("shows SELL badge for a SELL transaction", () => {
    render(<TransactionsLedger transactions={[TX_SELL]} />);
    const row = screen.getByTestId("ledger-row-tx-sell-1");
    expect(row.textContent).toContain("SELL");
  });

  it("shows DIV badge for a DIVIDEND transaction", () => {
    render(<TransactionsLedger transactions={[TX_DIV]} />);
    const row = screen.getByTestId("ledger-row-tx-div-1");
    expect(row.textContent).toContain("DIV");
  });

  // 4. TICKER column
  it("shows ticker symbol in each row", () => {
    render(<TransactionsLedger transactions={THREE_ROWS} />);
    const buyRow = screen.getByTestId("ledger-row-tx-buy-1");
    expect(buyRow.textContent).toContain("AAPL");

    const sellRow = screen.getByTestId("ledger-row-tx-sell-1");
    expect(sellRow.textContent).toContain("NVDA");

    const divRow = screen.getByTestId("ledger-row-tx-div-1");
    expect(divRow.textContent).toContain("MSFT");
  });

  // 5. GROSS column for BUY/SELL (qty × price)
  it("shows correct gross amount for BUY (qty × price)", () => {
    render(<TransactionsLedger transactions={[TX_BUY]} />);
    const row = screen.getByTestId("ledger-row-tx-buy-1");
    // 100 × $187.32 = $18,732.00
    expect(row.textContent).toContain("18,732.00");
  });

  it("shows correct gross amount for SELL (qty × price)", () => {
    render(<TransactionsLedger transactions={[TX_SELL]} />);
    const row = screen.getByTestId("ledger-row-tx-sell-1");
    // 30 × $895.12 = $26,853.60
    expect(row.textContent).toContain("26,853.60");
  });

  // 6. GROSS column for DIVIDEND (amount)
  it("shows tx.amount as gross for DIVIDEND rows", () => {
    render(<TransactionsLedger transactions={[TX_DIV]} />);
    const row = screen.getByTestId("ledger-row-tx-div-1");
    // amount = $98.00
    expect(row.textContent).toContain("98.00");
  });

  // 7. FEE column
  it("shows fee for BUY rows", () => {
    render(<TransactionsLedger transactions={[TX_BUY]} />);
    const row = screen.getByTestId("ledger-row-tx-buy-1");
    // fee = $0.99
    expect(row.textContent).toContain("0.99");
  });

  it("shows — for DIVIDEND rows with 0 fee", () => {
    render(<TransactionsLedger transactions={[TX_DIV]} />);
    const row = screen.getByTestId("ledger-row-tx-div-1");
    // fee = 0 → shows "—"
    expect(row.textContent).toContain("—");
  });

  // 8. CASH IMPACT column sign
  it("shows negative cash impact for BUY", () => {
    render(<TransactionsLedger transactions={[TX_BUY]} />);
    const row = screen.getByTestId("ledger-row-tx-buy-1");
    // BUY cash impact = -(qty × price + fee) = -(18732 + 0.99) = -18732.99
    expect(row.textContent).toContain("-");
    expect(row.textContent).toContain("18,732.99");
  });

  it("shows positive cash impact for SELL", () => {
    render(<TransactionsLedger transactions={[TX_SELL]} />);
    const row = screen.getByTestId("ledger-row-tx-sell-1");
    // SELL cash impact = qty × price - fee = 26853.60 - 0.99 = 26852.61
    expect(row.textContent).toContain("+");
    expect(row.textContent).toContain("26,852.61");
  });

  it("shows positive cash impact for DIVIDEND", () => {
    render(<TransactionsLedger transactions={[TX_DIV]} />);
    const row = screen.getByTestId("ledger-row-tx-div-1");
    // DIV cash impact = amount = +$98.00
    expect(row.textContent).toContain("+");
    expect(row.textContent).toContain("98.00");
  });

  // 9. Empty state
  it("renders empty state when transactions is empty", () => {
    render(<TransactionsLedger transactions={[]} />);
    // No table should render; instead an empty state message appears.
    expect(screen.queryByTestId("transactions-ledger")).toBeNull();
    expect(screen.getByText(/No transactions yet/i)).toBeDefined();
  });

  // 10. Filter-empty state
  it("renders filter-empty state when tickerFilter produces no matches", () => {
    render(
      <TransactionsLedger transactions={THREE_ROWS} tickerFilter="ZZZZ" />,
    );
    // None of our 3 rows have ticker "ZZZZ"
    expect(screen.getByText(/No transactions match the current filters/i)).toBeDefined();
  });

  // 11. Totals row in <tfoot>
  it("renders a totals row in a <tfoot> element", () => {
    const { container } = render(<TransactionsLedger transactions={THREE_ROWS} />);
    // The <tfoot> element must exist for screen-reader accessibility (spec §7)
    const tfoot = container.querySelector("tfoot");
    expect(tfoot).not.toBeNull();
    // Totals row shows the row count
    expect(tfoot?.textContent).toContain("TOTALS");
    expect(tfoot?.textContent).toContain("3"); // 3 transactions
  });

  // 12. Column sort: clicking DATE header twice reverses order
  it("reverses row order when DATE column is clicked twice (asc → desc)", () => {
    render(<TransactionsLedger transactions={THREE_ROWS} />);

    // Find the DATE column header button by text
    const dateHeader = screen.getByText("DATE");
    expect(dateHeader).toBeDefined();

    // Click once → ascending (oldest first). TX_SELL is 2026-05-18, TX_BUY/DIV 2026-05-19.
    fireEvent.click(dateHeader);

    let rows = screen.getAllByTestId(/^ledger-row-/);
    // Ascending by date: TX_SELL (May 18) comes first
    expect(rows[0].getAttribute("data-testid")).toBe("ledger-row-tx-sell-1");

    // Click twice → descending (newest first). TX_BUY/DIV (May 19) come before TX_SELL.
    fireEvent.click(dateHeader);

    rows = screen.getAllByTestId(/^ledger-row-/);
    // Descending: TX_BUY or TX_DIV (both May 19) come before TX_SELL (May 18)
    // We just assert TX_SELL is no longer first
    expect(rows[0].getAttribute("data-testid")).not.toBe("ledger-row-tx-sell-1");
  });
});
