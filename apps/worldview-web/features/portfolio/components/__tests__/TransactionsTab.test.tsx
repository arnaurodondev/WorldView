/**
 * features/portfolio/components/__tests__/TransactionsTab.test.tsx
 *
 * WHY THIS EXISTS (R1 sprint): TransactionsTab gained a server-side pager
 * (Prev/Next + "X–Y of Z" range) and the onAddPosition pass-through for the
 * empty-state CTA. These tests pin:
 *   - pager visibility rules (only when total > limit AND a callback exists)
 *   - offset arithmetic on Prev/Next clicks
 *   - boundary disabling (Prev on first page, Next on last page)
 *
 * MOCKED: ConnectedBrokeragesList — it fires its own useQuery against the
 * gateway; irrelevant to pager behaviour and would require a QueryClient +
 * gateway mock. A stub keeps the test focused and provider-free.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
import type { TransactionsResponse, Transaction } from "@/types/api";

// ── Mock the brokerage list (network-bound child) ────────────────────────────
vi.mock("@/components/brokerage/ConnectedBrokeragesList", () => ({
  ConnectedBrokeragesList: () => <div data-testid="brokerages-stub" />,
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

function tx(overrides: Partial<Transaction>): Transaction {
  return {
    transaction_id: "tx-x",
    portfolio_id: "p1",
    instrument_id: "ins-x",
    ticker: "AAPL",
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

/** Paginated response builder — total/offset/limit drive the pager. */
function resp(
  total: number,
  offset: number,
  limit = 100,
): TransactionsResponse {
  return {
    transactions: [tx({ transaction_id: `tx-${offset}` })],
    total,
    offset,
    limit,
  };
}

function renderTab(
  transactionsResp: TransactionsResponse,
  onTxOffsetChange?: (offset: number) => void,
) {
  return render(
    <TransactionsTab
      activePortfolioId="port-1"
      txLoading={false}
      transactionsResp={transactionsResp}
      holdingOverviews={undefined}
      onConnect={vi.fn()}
      onTxOffsetChange={onTxOffsetChange}
    />,
  );
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("TransactionsTab — server-side pager (R1 sprint)", () => {
  it("hides the pager when total fits in one page", () => {
    renderTab(resp(50, 0), vi.fn());
    expect(screen.queryByTestId("transactions-pager")).not.toBeInTheDocument();
  });

  it("hides the pager when no onTxOffsetChange callback is wired", () => {
    // WHY: without a callback the buttons would be dead chrome — a pager that
    // cannot page is worse than no pager.
    renderTab(resp(250, 0), undefined);
    expect(screen.queryByTestId("transactions-pager")).not.toBeInTheDocument();
  });

  it("shows the pager with a 1-based row range when total > limit", () => {
    renderTab(resp(250, 0), vi.fn());
    const pager = screen.getByTestId("transactions-pager");
    expect(pager).toHaveTextContent("1–100 of 250");
  });

  it("Next advances the offset by one page", async () => {
    const user = userEvent.setup();
    const onOffsetChange = vi.fn();
    renderTab(resp(250, 0), onOffsetChange);

    await user.click(
      screen.getByRole("button", { name: "Next transactions page" }),
    );
    expect(onOffsetChange).toHaveBeenCalledWith(100);
  });

  it("Prev steps back one page and clamps at zero", async () => {
    const user = userEvent.setup();
    const onOffsetChange = vi.fn();
    renderTab(resp(250, 100), onOffsetChange);

    expect(screen.getByTestId("transactions-pager")).toHaveTextContent(
      "101–200 of 250",
    );
    await user.click(
      screen.getByRole("button", { name: "Previous transactions page" }),
    );
    expect(onOffsetChange).toHaveBeenCalledWith(0);
  });

  it("disables Prev on the first page and Next on the last page", () => {
    // First page: Prev must be disabled (no page -1).
    const { unmount } = renderTab(resp(250, 0), vi.fn());
    expect(
      screen.getByRole("button", { name: "Previous transactions page" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Next transactions page" }),
    ).toBeEnabled();
    unmount();

    // Last page (201–250 of 250): Next must be disabled.
    renderTab(resp(250, 200), vi.fn());
    expect(
      screen.getByTestId("transactions-pager"),
    ).toHaveTextContent("201–250 of 250");
    expect(
      screen.getByRole("button", { name: "Next transactions page" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Previous transactions page" }),
    ).toBeEnabled();
  });
});
