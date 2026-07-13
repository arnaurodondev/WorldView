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

  it("test_partial_close_quantity_editable_default_full: quantity editable, defaults to full holding", () => {
    // PLAN-0122 W-D §6.5: quantity is now EDITABLE (was read-only) so the user
    // can close a partial position. It still DEFAULTS to the full holding so a
    // full close stays one click.
    renderDialog();
    const qtyInput = screen.getByLabelText(/quantity/i);
    expect(qtyInput).not.toHaveAttribute("readonly");
    // Number input → default value is the full holding quantity (50).
    expect(qtyInput).toHaveValue(50);
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
    // FE-001 fix: the /api prefix is required for the Next.js → S9 rewrite rule.
    // A bare /v1/... URL is not rewritten and hits the 404 handler.
    expect(url).toBe("/api/v1/transactions");
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

  // ── PLAN-0122 W-D §6.5: partial close ────────────────────────────────────

  it("test_partial_close_full_still_one_click: leaving the default full quantity posts the full SELL", async () => {
    // Regression guard: the default (full holding) close must behave exactly as
    // before — a single click posts a SELL of the whole holding quantity.
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "tx-1",
          portfolio_id: "port-222",
          instrument_id: "inst-333",
          transaction_type: "TRADE",
          direction: "SELL",
          quantity: "50.00000000",
          price: "180.00000000",
          fees: "0.00000000",
          currency: "USD",
          executed_at: "2026-07-09T00:00:00Z",
          created_at: "2026-07-09T00:00:00Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    // Do NOT touch the quantity — click Close Position directly.
    await user.click(screen.getByRole("button", { name: /close position/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.quantity).toBe(50); // full holding
    expect(body.trade_side).toBe("SELL");
  });

  it("test_partial_close_blocks_over_and_zero: over-holding and zero quantities are blocked", async () => {
    const mockFetch = vi.fn();
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    const qtyInput = screen.getByLabelText(/quantity/i);

    // Over-holding (60 > 50) → blocked with the "You only hold N shares." message.
    await user.clear(qtyInput);
    await user.type(qtyInput, "60");
    await user.click(screen.getByRole("button", { name: /sell 60 of 50|close position|sell all/i }));
    expect(screen.getByText(/you only hold 50 shares/i)).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();

    // Zero → blocked with the "greater than 0" message.
    await user.clear(qtyInput);
    await user.type(qtyInput, "0");
    // With qty 0 the label reads "Close Position" (isPartial=false), so target it.
    await user.click(screen.getByRole("button", { name: /close position/i }));
    expect(screen.getByText(/quantity must be greater than 0/i)).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("test_partial_close_title_reflects_partial: partial qty updates the label; Sell all resets to full", async () => {
    const user = userEvent.setup();
    renderDialog();

    const qtyInput = screen.getByLabelText(/quantity/i);
    await user.clear(qtyInput);
    await user.type(qtyInput, "20");

    // The intent label reflects the partial close.
    expect(screen.getByTestId("close-mode-label")).toHaveTextContent("Sell 20 of 50");
    // The submit button label follows suit.
    expect(
      screen.getByRole("button", { name: /sell 20 of 50/i }),
    ).toBeInTheDocument();

    // "Sell all" resets the quantity back to the full holding.
    await user.click(screen.getByRole("button", { name: /sell all/i }));
    expect(qtyInput).toHaveValue(50);
    expect(screen.getByTestId("close-mode-label")).toHaveTextContent("Close Position");
  });

  it("posts the entered partial quantity on a partial close", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "tx-2",
          portfolio_id: "port-222",
          instrument_id: "inst-333",
          transaction_type: "TRADE",
          direction: "SELL",
          quantity: "20.00000000",
          price: "180.00000000",
          fees: "0.00000000",
          currency: "USD",
          executed_at: "2026-07-09T00:00:00Z",
          created_at: "2026-07-09T00:00:00Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    const qtyInput = screen.getByLabelText(/quantity/i);
    await user.clear(qtyInput);
    await user.type(qtyInput, "20");
    await user.click(screen.getByRole("button", { name: /sell 20 of 50/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.quantity).toBe(20);
  });
});
