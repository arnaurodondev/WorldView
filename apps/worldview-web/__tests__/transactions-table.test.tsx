/**
 * __tests__/transactions-table.test.tsx — Unit tests for TransactionsTable
 *
 * WHY THIS EXISTS (PLAN-0051 T-A-1-07): Wave A enhanced TransactionsTable
 * with eight new filters (date range, ticker autocomplete, currency, min/max
 * amount, free-text search), CSV export, virtualisation > 200 rows, and a
 * totals row. The behavioural surface is now wide enough that a regression
 * in any single piece would silently break a trader workflow. These tests
 * pin each filter, the export, and the totals math.
 *
 * MOCKED MODULES:
 *   - @/lib/csv-export: we assert the export button calls exportToCsv with
 *     the *currently filtered* rows. The actual CSV string is unit-tested
 *     by papaparse upstream — we don't re-test that here.
 *   - react-window FixedSizeList: in jsdom the ResizeObserver/measure-cell
 *     pipeline isn't fully implemented, so we replace the list with a
 *     deterministic stub that simply renders all rows. This keeps the
 *     virtualisation integration *renderable* in tests while letting us
 *     assert the threshold trigger via the data-testid wrapper.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Mock CSV export ───────────────────────────────────────────────────────────
// Hoisted so the spy is captured before TransactionsTable's module-load.
vi.mock("@/lib/csv-export", () => ({
  exportToCsv: vi.fn(),
  // The component reads todayDateStamp via ../lib/csv-export to build the
  // filename — return a deterministic value so we can assert it.
  todayDateStamp: vi.fn(() => "2026-04-29"),
}));

// ── Mock react-window ─────────────────────────────────────────────────────────
// jsdom's layout engine is incomplete; FixedSizeList renders nothing without
// a working ResizeObserver. The stub renders every row in the visible window
// so the table renders deterministically in tests.
vi.mock("react-window", () => ({
  FixedSizeList: ({
    itemCount,
    children,
  }: {
    itemCount: number;
    children: (props: { index: number; style: React.CSSProperties }) => React.ReactNode;
  }) => {
    const items = [];
    for (let i = 0; i < itemCount; i++) {
      // WHY wrapping each child in a keyed fragment: the children render
      // function returns a <table> with no key, which React would
      // otherwise warn about during the loop.
      items.push(
        <div key={i} data-virtual-row={i}>
          {children({ index: i, style: {} })}
        </div>,
      );
    }
    return <div data-testid="virtual-mock">{items}</div>;
  },
}));

import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { exportToCsv } from "@/lib/csv-export";
import type { Transaction } from "@/types/api";

// ── Sample data ───────────────────────────────────────────────────────────────

function tx(overrides: Partial<Transaction>): Transaction {
  return {
    transaction_id: "tx-x",
    portfolio_id: "p1",
    instrument_id: "ins-x",
    ticker: "AAPL",
    // PLAN-0053 T-D-4-02: required field on the Transaction type. Tests
    // that don't care about the badge can leave it null (renders as "—").
    asset_class: null,
    type: "BUY",
    quantity: 10,
    price: 100,
    fee: 1,
    amount: null,
    currency: "USD",
    executed_at: "2026-04-01T15:30:00Z",
    notes: null,
    ...overrides,
  };
}

const sampleData: Transaction[] = [
  tx({ transaction_id: "tx-1", ticker: "AAPL", type: "BUY", quantity: 10, price: 150, executed_at: "2026-01-15T15:30:00Z" }),
  tx({ transaction_id: "tx-2", ticker: "MSFT", type: "SELL", quantity: 5, price: 400, executed_at: "2026-02-10T15:30:00Z" }),
  tx({ transaction_id: "tx-3", ticker: "AAPL", type: "DIVIDEND", quantity: 0, price: 0, amount: 25, executed_at: "2026-03-01T10:00:00Z" }),
  tx({ transaction_id: "tx-4", ticker: "GOOG", type: "BUY", quantity: 2, price: 2500, executed_at: "2026-03-15T15:30:00Z", currency: "EUR" }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — base rendering", () => {
  it("renders the filter bar and all rows", () => {
    render(<TransactionsTable transactions={sampleData} />);
    // Each row's BUY/SELL/DIV badge is data-testid-tagged. Four rows = four badges.
    expect(screen.getByTestId("tx-type-tx-1")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-3")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-4")).toBeInTheDocument();
    // Filter bar present
    expect(screen.getByLabelText("Search transactions")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter from date")).toBeInTheDocument();
  });

  it("shows InlineEmptyState when transactions is empty", () => {
    render(<TransactionsTable transactions={[]} />);
    // F-P-016 (PLAN-0051 W6): the empty-state copy now includes a Body
    // explanation alongside the Title, so we match the leading "No
    // transactions yet." substring instead of the whole string.
    expect(screen.getByText(/No transactions yet\./)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — filters", () => {
  it("date range filter excludes rows outside the window", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    // From=2026-02-01 → should drop tx-1 (Jan)
    const from = screen.getByLabelText("Filter from date") as HTMLInputElement;
    // userEvent.type does not work with type=date; fireEvent.change is the
    // standard jsdom-friendly way to set a controlled date input.
    fireEvent.change(from, { target: { value: "2026-02-01" } });

    expect(screen.queryByTestId("tx-type-tx-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();

    // To=2026-02-28 → also drops tx-3 and tx-4 (March)
    const to = screen.getByLabelText("Filter to date") as HTMLInputElement;
    fireEvent.change(to, { target: { value: "2026-02-28" } });
    expect(screen.queryByTestId("tx-type-tx-3")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-4")).not.toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();

    // Suppress unused
    void user;
  });

  it("ticker autocomplete: substring + case-insensitive match", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    const tickerInput = screen.getByLabelText("Filter by ticker");
    await user.type(tickerInput, "aap"); // lowercase substring of AAPL

    // Only AAPL rows should remain (tx-1 BUY + tx-3 DIVIDEND)
    expect(screen.getByTestId("tx-type-tx-1")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-3")).toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-4")).not.toBeInTheDocument();
  });

  it("currency filter limits rows to the selected currency", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    const currency = screen.getByLabelText("Filter by currency");
    await user.selectOptions(currency, "EUR");

    // Only the GOOG (EUR) row remains
    expect(screen.getByTestId("tx-type-tx-4")).toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-2")).not.toBeInTheDocument();
  });

  it("min amount filter drops rows below the threshold", async () => {
    render(<TransactionsTable transactions={sampleData} />);

    // tx-1 total = 1500, tx-2 total = 2000, tx-3 total = 25 (DIV), tx-4 total = 5000
    const min = screen.getByLabelText("Minimum amount") as HTMLInputElement;
    fireEvent.change(min, { target: { value: "1000" } });

    // dividend (25) and any < 1000 dropped
    expect(screen.queryByTestId("tx-type-tx-3")).not.toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-1")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();
    expect(screen.getByTestId("tx-type-tx-4")).toBeInTheDocument();
  });

  it("search matches type or ticker (debounced)", async () => {
    // WHY no fake timers: userEvent.setup() in other tests requires real
    // timers, and module-level fake timer enablement leaks across tests
    // even after useRealTimers(). We instead wait the natural 200 ms.
    render(<TransactionsTable transactions={sampleData} />);

    const search = screen.getByLabelText("Search transactions") as HTMLInputElement;
    fireEvent.change(search, { target: { value: "MSFT" } });

    // Wait for the debounce (200 ms) to flush. 250 ms is a comfortable
    // margin without slowing the suite measurably.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });

    // Only tx-2 (MSFT) matches the search
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tx-type-tx-3")).not.toBeInTheDocument();
  });

  it("Clear filters button resets all filter state and is hidden when nothing is filtered", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    // Initially: no Clear filters button visible.
    expect(screen.queryByText("Clear filters")).not.toBeInTheDocument();

    // Apply a filter
    await user.type(screen.getByLabelText("Filter by ticker"), "AAPL");
    const clearBtn = await screen.findByText("Clear filters");
    expect(clearBtn).toBeInTheDocument();

    // Click clear → all rows visible again, button hides.
    await user.click(clearBtn);
    expect(screen.getByTestId("tx-type-tx-2")).toBeInTheDocument();
    expect(screen.queryByText("Clear filters")).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — CSV export", () => {
  it("clicking Export CSV invokes exportToCsv with the filtered rows", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    await user.click(screen.getByLabelText("Export transactions as CSV"));

    expect(exportToCsv).toHaveBeenCalledTimes(1);
    // The generic on exportToCsv erases through vi.mocked (rows becomes
    // readonly unknown[]). Cast through `unknown` to widen back to the
    // concrete shape we want to assert on in this test.
    const callArg = vi.mocked(exportToCsv).mock.calls[0][0] as unknown as {
      filenameStem: string;
      rows: Transaction[];
      columns: { header: string }[];
    };
    expect(callArg.filenameStem).toBe("transactions-2026-04-29");
    expect(callArg.rows).toHaveLength(4); // unfiltered → all 4 rows
    // Columns include Date, Type, Ticker, Quantity, Price, Total, Fee, Currency
    expect(callArg.columns.map((c) => c.header)).toEqual([
      "Date",
      "Type",
      "Ticker",
      "Quantity",
      "Price",
      "Total",
      "Fee",
      "Currency",
    ]);
  });

  it("CSV export only emits currently-filtered rows", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    await user.type(screen.getByLabelText("Filter by ticker"), "MSFT");
    await user.click(screen.getByLabelText("Export transactions as CSV"));

    // The generic on exportToCsv erases through vi.mocked (rows becomes
    // readonly unknown[]). Cast through `unknown` to widen back to the
    // concrete shape we want to assert on in this test.
    const callArg = vi.mocked(exportToCsv).mock.calls[0][0] as unknown as {
      filenameStem: string;
      rows: Transaction[];
      columns: { header: string }[];
    };
    expect(callArg.rows).toHaveLength(1);
    expect(callArg.rows[0].transaction_id).toBe("tx-2");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — totals row", () => {
  it("computes BUY cost / SELL proceeds / DIV income from filtered rows", () => {
    render(<TransactionsTable transactions={sampleData} />);

    const totals = screen.getByTestId("transactions-totals");
    // BUY: tx-1 (10*150=1500) + tx-4 (2*2500=5000) = 6500
    expect(within(totals).getByTestId("totals-buy").textContent).toContain("6,500");
    // SELL: tx-2 (5*400=2000)
    expect(within(totals).getByTestId("totals-sell").textContent).toContain("2,000");
    // DIV: tx-3 amount=25
    expect(within(totals).getByTestId("totals-div").textContent).toContain("25");
  });

  it("totals update when a filter narrows the row set", async () => {
    const user = userEvent.setup();
    render(<TransactionsTable transactions={sampleData} />);

    const totals = screen.getByTestId("transactions-totals");
    await user.type(screen.getByLabelText("Filter by ticker"), "MSFT");

    // Only tx-2 remains: BUY=0, SELL=2000, DIV=0
    expect(within(totals).getByTestId("totals-buy").textContent).toContain("0");
    expect(within(totals).getByTestId("totals-sell").textContent).toContain("2,000");
    expect(within(totals).getByTestId("totals-div").textContent).toContain("0");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — dividend amount rendering", () => {
  // Regression for SA-5 beta-hardening (2026-05-10):
  // The TOTAL cell previously used `total > 0 ? formatPrice(total) : "—"`.
  // For negative-amount dividends (tax withholdings like -$0.76) this
  // silently showed "—" instead of the real amount, hiding the value.

  it("shows positive dividend amount in the TOTAL cell", () => {
    // A standard quarterly dividend payment — amount is positive.
    const divTx = tx({
      transaction_id: "div-pos",
      type: "DIVIDEND",
      quantity: 0,
      price: 0,
      amount: 7.81,
      ticker: "AAPL",
    });
    render(<TransactionsTable transactions={[divTx]} />);
    // The TOTAL cell should show the formatted amount, not "—".
    // The value also appears in the totals-div strip, so we look for all
    // occurrences and verify at least one is present.
    // formatPrice(7.81) → "$7.81"
    expect(screen.getAllByText("$7.81")).toHaveLength(2); // TOTAL cell + totals strip
    // QTY and PRICE cells show "—" for DIVIDEND rows (no share quantity/price).
    const row = screen.getByTestId("tx-type-div-pos").closest("tr");
    expect(row).toBeTruthy();
  });

  it("shows negative dividend amount (withholding) in the TOTAL cell — not em-dash", () => {
    // Tax withholding rows have a negative amount. Before this fix they
    // rendered "—" because the `total > 0` guard failed.
    const withholdTx = tx({
      transaction_id: "div-neg",
      type: "DIVIDEND",
      quantity: 0,
      price: 0,
      amount: -0.76,
      ticker: "AAPL",
    });
    render(<TransactionsTable transactions={[withholdTx]} />);
    // Should show "-$0.76", not "—".
    // formatPrice accepts negative values and renders with a leading minus.
    // WHY getAllByText: the negative amount also feeds divIncome in the totals
    // strip (bottom row), so the formatted text appears in both places.
    const formatted = screen.getAllByText("-$0.76");
    expect(formatted.length).toBeGreaterThanOrEqual(1);
  });

  it("shows em-dash in TOTAL cell when dividend amount is null (unknown)", () => {
    // Historical rows that pre-date Alembic migration 0009 have amount=null.
    // The row data cell should render "—", not "$0.00".
    const nullAmountTx = tx({
      transaction_id: "div-null",
      type: "DIVIDEND",
      quantity: 0,
      price: 0,
      amount: null,
      ticker: "AAPL",
    });
    render(<TransactionsTable transactions={[nullAmountTx]} />);
    // The row must be present (not empty-state).
    const badge = screen.getByTestId("tx-type-div-null");
    expect(badge).toBeInTheDocument();
    // Find the data row's TOTAL cell (7th <td> in the row — index 6).
    // We check the cell directly rather than querying for text to avoid the
    // totals-strip "$0.00" confounding the assertion.
    const row = badge.closest("tr");
    expect(row).toBeTruthy();
    const cells = row!.querySelectorAll("td");
    // TOTAL is the 7th cell (index 6: DATE=0, TYPE=1, CLASS=2, TICKER=3, QTY=4, PRICE=5, TOTAL=6)
    const totalCell = cells[6];
    expect(totalCell?.textContent).toBe("—");
  });
});

// ─────────────────────────────────────────────────────────────────────────────

describe("TransactionsTable — virtualisation", () => {
  it("does NOT virtualise below the 200-row threshold", () => {
    render(<TransactionsTable transactions={sampleData} />);
    // The mocked FixedSizeList container is only present when threshold exceeded
    expect(screen.queryByTestId("transactions-virtualised")).not.toBeInTheDocument();
  });

  it("virtualises when filtered length > 200", () => {
    // Generate 250 rows
    const many: Transaction[] = Array.from({ length: 250 }, (_, i) =>
      tx({ transaction_id: `tx-${i}`, ticker: `T${i}`, executed_at: `2026-04-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z` }),
    );

    render(<TransactionsTable transactions={many} />);
    expect(screen.getByTestId("transactions-virtualised")).toBeInTheDocument();
    // Mocked FixedSizeList synchronously renders all rows
    expect(screen.getByTestId("virtual-mock")).toBeInTheDocument();
  });

  it("virtualised row uses identical column widths to the header (QA-iter1 MAJ-4)", () => {
    // QA-iter1 MAJ-4 regression: with > VIRTUALISATION_THRESHOLD rows the
    // virtualised mini-tables previously had an empty <colgroup>, so columns
    // sized to content per-row and right-aligned numerics misaligned with
    // the header. We pin the contract by asserting both tables render the
    // same <col style="width: …%"> sequence.
    const many: Transaction[] = Array.from({ length: 250 }, (_, i) =>
      tx({ transaction_id: `tx-${i}`, ticker: `T${i}`, executed_at: `2026-04-${String((i % 28) + 1).padStart(2, "0")}T00:00:00Z` }),
    );
    render(<TransactionsTable transactions={many} />);

    const header = screen.getByTestId("transactions-header") as HTMLTableElement;
    const virtualRows = screen.getAllByTestId("transactions-virtual-row") as HTMLTableElement[];
    expect(virtualRows.length).toBeGreaterThan(0);

    // Extract the widths from the header's <col> elements.
    const headerCols = Array.from(header.querySelectorAll("colgroup > col"));
    expect(headerCols.length).toBeGreaterThan(0);
    const headerWidths = headerCols.map((c) => (c as HTMLElement).style.width);

    // Sample the first virtual row and compare widths element-by-element.
    const sampleRow = virtualRows[0];
    const rowCols = Array.from(sampleRow.querySelectorAll("colgroup > col"));
    const rowWidths = rowCols.map((c) => (c as HTMLElement).style.width);

    expect(rowWidths).toEqual(headerWidths);
    // Sanity: ensure no width is empty — that would mean we forgot to set them.
    headerWidths.forEach((w) => expect(w).not.toBe(""));
  });
});
