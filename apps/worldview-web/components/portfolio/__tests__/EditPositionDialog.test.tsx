/**
 * components/portfolio/__tests__/EditPositionDialog.test.tsx — PLAN-0122 W-D.
 *
 * WHY THIS EXISTS: guards the honest-ledger Edit Position mechanism (PRD-0122
 * §6.4). It pins that:
 *   1. Raising the target posts a BUY of the delta (correct body).
 *   2. Lowering the target posts a SELL of the delta.
 *   3. A zero delta (target === current) disables Submit — nothing to record.
 *   4. The "adjusting trade, not a rewrite" note is present.
 *   5. A failed POST shows an error toast AND keeps the dialog open.
 *
 * WHY stub global.fetch: EditPositionDialog uses raw fetch (like
 * ClosePositionDialog) for the Idempotency-Key header. Stubbing fetch lets us
 * assert the request body and simulate success/error.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { EditPositionDialog } from "../EditPositionDialog";
import type { Holding } from "@/types/api";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

const mockHolding: Holding = {
  holding_id: "h-1",
  portfolio_id: "port-1",
  instrument_id: "inst-1",
  entity_id: "ent-1",
  ticker: "AAPL",
  name: "Apple Inc.",
  quantity: 50,
  average_cost: 175.5,
};

function okResponse() {
  return new Response(
    JSON.stringify({
      id: "tx-1",
      portfolio_id: "port-1",
      instrument_id: "inst-1",
      transaction_type: "TRADE",
      direction: "BUY",
      quantity: "30.00000000",
      price: "200.00000000",
      fees: "0.00000000",
      currency: "USD",
      executed_at: "2026-07-09T00:00:00Z",
      created_at: "2026-07-09T00:00:00Z",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof EditPositionDialog>> = {},
) {
  const onSuccess = vi.fn();
  const onClose = vi.fn();
  render(
    <EditPositionDialog
      holding={mockHolding}
      portfolioId="port-1"
      currentPrice={200}
      onSuccess={onSuccess}
      onClose={onClose}
      accessToken="tok"
      {...overrides}
    />,
  );
  return { onSuccess, onClose };
}

describe("EditPositionDialog (PLAN-0122 W-D)", () => {
  it("renders the dialog title with the ticker", () => {
    renderDialog();
    expect(screen.getByText(/Edit Position.*AAPL/i)).toBeInTheDocument();
  });

  it("test_edit_position_ledger_note_present: the adjusting-trade note renders", () => {
    renderDialog();
    const note = screen.getByTestId("edit-position-ledger-note");
    expect(note).toBeInTheDocument();
    // WHY assert the key phrase: the note is the mitigation for the "editing =
    // history rewrite" risk — the honest wording must not be softened away.
    expect(note.textContent).toMatch(/adjusting trade/i);
    expect(note.textContent).toMatch(/does not rewrite past transactions/i);
  });

  it("test_edit_position_submit_disabled_on_zero_delta: target === current disables Submit", () => {
    // The dialog opens pre-filled with the current quantity → delta 0 → nothing
    // to record → the Submit button is disabled and reads "No change".
    renderDialog();
    const submit = screen.getByRole("button", { name: /no change/i });
    expect(submit).toBeDisabled();
  });

  it("test_edit_position_posts_delta_trade_buy: target > current posts a BUY of the delta", async () => {
    const mockFetch = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    // Raise the target from 50 → 80 (BUY 30).
    const qty = screen.getByLabelText(/target qty/i);
    await user.clear(qty);
    await user.type(qty, "80");

    // The submit label reflects the derived action.
    const submit = screen.getByRole("button", { name: /record buy of 30/i });
    await user.click(submit);

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/transactions");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.transaction_type).toBe("TRADE");
    expect(body.trade_side).toBe("BUY");
    expect(body.quantity).toBe(30);
    expect(body.instrument_id).toBe("inst-1");
    expect(body.portfolio_id).toBe("port-1");
    // Idempotency-Key must be present so a double-submit is de-duped.
    expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
  });

  it("test_edit_position_posts_delta_trade_sell: target < current posts a SELL of the delta", async () => {
    const mockFetch = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    // Lower the target from 50 → 20 (SELL 30).
    const qty = screen.getByLabelText(/target qty/i);
    await user.clear(qty);
    await user.type(qty, "20");

    await user.click(screen.getByRole("button", { name: /record sell of 30/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.trade_side).toBe("SELL");
    expect(body.quantity).toBe(30);
  });

  it("test_edit_position_error_keeps_dialog_open: POST failure toasts and does not close", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", mockFetch);
    const { toast } = await import("sonner");
    const user = userEvent.setup();
    const { onClose } = renderDialog();

    const qty = screen.getByLabelText(/target qty/i);
    await user.clear(qty);
    await user.type(qty, "80");
    await user.click(screen.getByRole("button", { name: /record buy of 30/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Adjustment failed",
        expect.objectContaining({ description: "boom" }),
      ),
    );
    // Dialog stays open so the user can retry — onClose must NOT have fired.
    expect(onClose).not.toHaveBeenCalled();
  });

  it("target 0 records a full SELL of the whole position", async () => {
    const mockFetch = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", mockFetch);
    const user = userEvent.setup();
    renderDialog();

    const qty = screen.getByLabelText(/target qty/i);
    await user.clear(qty);
    await user.type(qty, "0");

    await user.click(screen.getByRole("button", { name: /record sell of 50/i }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.trade_side).toBe("SELL");
    expect(body.quantity).toBe(50);
  });
});
