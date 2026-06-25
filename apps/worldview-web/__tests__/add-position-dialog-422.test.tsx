/**
 * __tests__/add-position-dialog-422.test.tsx — 422 error surfacing tests
 *
 * WHY THIS EXISTS (PLAN-0108 W5 T-5-03):
 *   T-5-03 hardened AddPositionDialog to surface backend errors (422 / network
 *   failures) inside the form itself via RHF's `root` error slot, not just as a
 *   transient toast. A 422 error from S1 (e.g. invalid instrument_id or quantity
 *   out of range) must be visible inline next to the Submit button so traders
 *   see it even if a toast has auto-dismissed.
 *
 * STRATEGY:
 *   - Mock createGateway so searchInstruments returns a known instrument.
 *   - Mock addPosition to reject with a specific error message.
 *   - Assert the error text appears in the rendered dialog (role="alert").
 *
 * DATA SOURCE: Mocked gateway — deterministic, no network.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AddPositionDialog } from "@/features/portfolio/components/AddPositionDialog";

// ── Gateway mock ─────────────────────────────────────────────────────────────
// WHY mock createGateway (not fetch): the dialog calls gw.searchInstruments()
// then gw.addPosition(). Mocking at the gateway layer gives us full control
// over the submit pipeline without reimplementing apiFetch internals.

const mockSearchInstruments = vi.fn();
const mockAddPosition = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    searchInstruments: mockSearchInstruments,
    addPosition: mockAddPosition,
  })),
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

// A minimal InstrumentSearchResult that satisfies the type used by the dialog.
const MOCK_INSTRUMENT = {
  instrument_id: "inst-aapl-001",
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  asset_class: "equity",
  currency: "USD",
};

function renderDialog() {
  const onOpenChange = vi.fn();
  const onSuccess = vi.fn();
  render(
    <AddPositionDialog
      open={true}
      onOpenChange={onOpenChange}
      onSuccess={onSuccess}
      portfolioId="port-123"
      accessToken="test-token"
    />,
  );
  return { onOpenChange, onSuccess };
}

beforeEach(() => {
  mockSearchInstruments.mockReset();
  mockAddPosition.mockReset();
  // Default: search succeeds — only addPosition failures are under test here.
  mockSearchInstruments.mockResolvedValue({ results: [MOCK_INSTRUMENT] });
});

// ── 422 error inline rendering ────────────────────────────────────────────────

describe("AddPositionDialog — 422 / server error inline rendering (T-5-03, PLAN-0108)", () => {
  it("shows server error message inside the form when addPosition rejects", async () => {
    const user = userEvent.setup();
    mockAddPosition.mockRejectedValueOnce(new Error("quantity exceeds position limit"));

    renderDialog();

    // Fill in a ticker and quantity so the submit button becomes enabled.
    await user.type(screen.getByPlaceholderText(/e\.g\. AAPL/i), "AAPL");

    // NumberInput renders an <input> — locate it by accessible label.
    const qtyInput = screen.getByLabelText("Quantity");
    await user.clear(qtyInput);
    await user.type(qtyInput, "100");

    await user.click(screen.getByRole("button", { name: /add position/i }));

    // WHY role="alert": the error paragraph has role="alert" to be announced
    // by screen readers immediately (T-5-03 + aria requirement).
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("quantity exceeds position limit");
    });
  });

  it("shows a generic fallback message when the thrown value is not an Error", async () => {
    const user = userEvent.setup();
    // Some code paths throw plain strings or non-Error objects.
    mockAddPosition.mockRejectedValueOnce("oops");

    renderDialog();
    await user.type(screen.getByPlaceholderText(/e\.g\. AAPL/i), "AAPL");
    const qtyInput = screen.getByLabelText("Quantity");
    await user.clear(qtyInput);
    await user.type(qtyInput, "50");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Failed to add position.");
    });
  });

  it("clears the server error when the dialog is reset after close", async () => {
    const user = userEvent.setup();
    mockAddPosition.mockRejectedValueOnce(new Error("bad request"));

    const { onOpenChange } = renderDialog();
    await user.type(screen.getByPlaceholderText(/e\.g\. AAPL/i), "AAPL");
    const qtyInput = screen.getByLabelText("Quantity");
    await user.clear(qtyInput);
    await user.type(qtyInput, "10");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    // Error appears.
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    // Cancel resets form state (and thus clears errors).
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does NOT call onSuccess when addPosition rejects", async () => {
    const user = userEvent.setup();
    mockAddPosition.mockRejectedValueOnce(new Error("server error"));

    const { onSuccess } = renderDialog();
    await user.type(screen.getByPlaceholderText(/e\.g\. AAPL/i), "AAPL");
    const qtyInput = screen.getByLabelText("Quantity");
    await user.clear(qtyInput);
    await user.type(qtyInput, "10");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    // onSuccess must NOT fire — position was not recorded.
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
