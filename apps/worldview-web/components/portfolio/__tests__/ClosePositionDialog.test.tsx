/**
 * components/portfolio/__tests__/ClosePositionDialog.test.tsx
 *
 * WHY THIS EXISTS: Guards the ClosePositionDialog's key behaviours:
 *  1. Ticker field is read-only and pre-filled from the holding.
 *  2. Quantity field is read-only and pre-filled from the holding.
 *  3. Confirming dispatches the correct payload (TRADE, SELL, holding quantity).
 *  4. Error response from the API renders an error toast.
 *  5. Success path: calls onSuccess and onClose.
 *
 * WHY we stub global.fetch: ClosePositionDialog uses raw fetch (not apiFetch)
 * for precise header control. Stubbing global.fetch is the lightest approach
 * that lets us assert on the request body and simulate both success and error.
 *
 * WHY Dialog must be wrapped in a DOM context: shadcn/ui Dialog uses Radix
 * UI Portal which appends content to document.body. React Testing Library's
 * render() provides the required DOM environment.
 *
 * PRD-0114 W5-T09
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { ClosePositionDialog } from "../ClosePositionDialog";
import type { Holding } from "@/types/api";

// ── Shared mocks ─────────────────────────────────────────────────────────────

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockHolding: Holding = {
  holding_id: "h-111",
  portfolio_id: "port-222",
  instrument_id: "inst-333",
  entity_id: "ent-444",
  ticker: "AAPL",
  name: "Apple Inc.",
  quantity: 50,
  average_cost: 175.50,
};

function renderDialog(overrides: Partial<React.ComponentProps<typeof ClosePositionDialog>> = {}) {
  const onSuccess = vi.fn();
  const onClose = vi.fn();

  render(
    <ClosePositionDialog
      holding={mockHolding}
      portfolioId="port-222"
      onSuccess={onSuccess}
      onClose={onClose}
      accessToken="tok-test"
      {...overrides}
    />,
  );

  return { onSuccess, onClose };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ClosePositionDialog", () => {
  it("renders the dialog with the correct title", () => {
    renderDialog();
    // The title should include the ticker symbol so the user knows which
    // position they are closing.
    expect(screen.getByText(/Close Position.*AAPL/i)).toBeInTheDocument();
  });

  it("renders the ticker field as read-only and pre-filled", () => {
    renderDialog();
    const tickerInput = screen.getByLabelText(/ticker/i);
    // WHY: the ticker field is read-only — the user cannot change which
    // position they're closing from within this dialog.
    expect(tickerInput).toHaveAttribute("readonly");
    expect(tickerInput).toHaveValue("AAPL");
  });

  it("renders the quantity field as read-only and pre-filled from holding", () => {
    renderDialog();
    const qtyInput = screen.getByLabelText(/quantity/i);
    // WHY: the quantity is the FULL holding quantity (full close only).
    // The field is read-only so the user cannot accidentally enter a partial qty.
    expect(qtyInput).toHaveAttribute("readonly");
    // The holding.quantity is 50; rendered as "50" via toLocaleString().
    expect(qtyInput).toHaveValue("50");
  });

  it("renders Cancel and Close Position buttons", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close position/i })).toBeInTheDocument();
  });

  it("calls onClose when Cancel is clicked", async () => {
    const { onClose } = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("dispatches correct payload on confirm: TRADE + SELL + holding quantity", async () => {
    // Stub fetch to return a successful transaction creation.
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "tx-999",
          portfolio_id: "port-222",
          instrument_id: "inst-333",
          transaction_type: "TRADE",
          direction: "SELL",
          quantity: "50.00000000",
          price: "175.50000000",
          fees: "0.00000000",
          currency: "USD",
          executed_at: "2026-06-20T00:00:00Z",
          created_at: "2026-06-20T00:00:00Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderDialog();

    // The sale price input should be pre-filled with average_cost as a suggestion.
    // We clear it and type a new price to simulate the user entering the market price.
    const priceInput = screen.getByLabelText(/sale price/i);
    await user.clear(priceInput);
    await user.type(priceInput, "200.00");

    // Click "Close Position" to trigger the POST.
    await user.click(screen.getByRole("button", { name: /close position/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledOnce();
    });

    // Verify the request body.
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/transactions");
    expect(init.method).toBe("POST");

    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    // WHY TRADE + trade_side SELL: S1 uses two-field model for transactions.
    expect(body.transaction_type).toBe("TRADE");
    expect(body.trade_side).toBe("SELL");
    // The full holding quantity must be used for a full position close.
    expect(body.quantity).toBe(50);
    // The price should reflect what the user typed.
    expect(body.price).toBe(200);
    // instrument_id must come from the holding.
    expect(body.instrument_id).toBe("inst-333");
    // portfolio_id must come from the prop.
    expect(body.portfolio_id).toBe("port-222");
  });

  it("calls onSuccess and onClose after a successful close", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "tx-888",
          portfolio_id: "port-222",
          instrument_id: "inst-333",
          transaction_type: "TRADE",
          direction: "SELL",
          quantity: "50.00000000",
          price: "180.00000000",
          fees: "0.00000000",
          currency: "USD",
          executed_at: "2026-06-20T00:00:00Z",
          created_at: "2026-06-20T00:00:00Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { onSuccess, onClose } = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /close position/i }));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledOnce();
      expect(onClose).toHaveBeenCalledOnce();
    });
  });

  it("shows error toast when API returns a non-OK response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "Cannot record transaction on root portfolio" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderDialog();

    await user.click(screen.getByRole("button", { name: /close position/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Close position failed",
        expect.objectContaining({
          description: "Cannot record transaction on root portfolio",
        }),
      );
    });
  });

  it("shows validation error when sale price is empty", async () => {
    const user = userEvent.setup();
    renderDialog();

    // Clear the pre-filled price so it's empty.
    const priceInput = screen.getByLabelText(/sale price/i);
    await user.clear(priceInput);

    await user.click(screen.getByRole("button", { name: /close position/i }));

    // A validation error message should appear below the price field.
    expect(
      screen.getByText(/valid sale price greater than 0/i),
    ).toBeInTheDocument();
  });

  it("shows validation error when sale price is zero or negative", async () => {
    const user = userEvent.setup();
    renderDialog();

    const priceInput = screen.getByLabelText(/sale price/i);
    await user.clear(priceInput);
    await user.type(priceInput, "0");

    await user.click(screen.getByRole("button", { name: /close position/i }));

    expect(
      screen.getByText(/valid sale price greater than 0/i),
    ).toBeInTheDocument();
  });
});
