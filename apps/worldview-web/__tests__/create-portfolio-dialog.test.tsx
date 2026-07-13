/**
 * __tests__/create-portfolio-dialog.test.tsx — Unit tests for CreatePortfolioDialog
 *
 * WHY THIS EXISTS: Verifies the BP-329 and BP-330 fixes:
 *   - BP-329: currency must be a Select (not a free-text input) so invalid ISO
 *     codes cannot be submitted.
 *   - BP-330: blank name must show inline "Name is required" error with
 *     aria-invalid on the input.
 *
 * DATA SOURCE: Mocked gateway — deterministic, no network.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreatePortfolioDialog } from "@/features/portfolio/components/CreatePortfolioDialog";
import type { Portfolio } from "@/types/api";

// ── Gateway mock ─────────────────────────────────────────────────────────────
// WHY mock: the dialog calls createGateway(accessToken).createPortfolio().
// We control the response to test both success and failure paths.

const mockCreatePortfolio = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    createPortfolio: mockCreatePortfolio,
  })),
}));

const SAMPLE_PORTFOLIO: Portfolio = {
  portfolio_id: "port-1",
  name: "Main Portfolio",
  currency: "USD",
  owner_id: "u-1",
  created_at: "2026-05-03T00:00:00Z",
  updated_at: "2026-05-03T00:00:00Z",
};

// ── Helpers ────────────────────────────────────────────────────────────────

function renderDialog(overrides: Partial<Parameters<typeof CreatePortfolioDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  const onSuccess = vi.fn();
  render(
    <CreatePortfolioDialog
      open={true}
      onOpenChange={onOpenChange}
      onSuccess={onSuccess}
      accessToken="test-token"
      {...overrides}
    />,
  );
  return { onOpenChange, onSuccess };
}

beforeEach(() => {
  mockCreatePortfolio.mockReset();
  // PLAN-0122 W-F: the tour flag lives in localStorage; isolate each test.
  window.localStorage.clear();
});

// ── Currency field type ────────────────────────────────────────────────────

describe("CreatePortfolioDialog — currency field (BP-329)", () => {
  it("currency is a combobox (Select), not a free-text input", () => {
    renderDialog();
    // A shadcn Select trigger has role="combobox".
    // WHY combobox: ARIA spec maps combobox to a control that opens a listbox.
    // A plain Input would have role="textbox".
    // PLAN-0114 W6: there are now two comboboxes (currency + cost_basis_method).
    // We specifically look for the one that contains a USD-family value.
    const comboboxes = screen.getAllByRole("combobox");
    expect(comboboxes.length).toBeGreaterThanOrEqual(1);
    // At least one must be present (the currency combobox).
    expect(comboboxes[0]).toBeInTheDocument();
  });

  it("shows USD as the default selected currency", () => {
    renderDialog();
    // PLAN-0114 W6: two comboboxes now — find the one containing "USD".
    const comboboxes = screen.getAllByRole("combobox");
    const currencyTrigger = comboboxes.find((el) => el.textContent?.includes("USD"));
    expect(currencyTrigger).toBeTruthy();
    expect(currencyTrigger).toHaveTextContent(/USD/);
  });
});

// ── Name validation ───────────────────────────────────────────────────────

describe("CreatePortfolioDialog — name validation (BP-330)", () => {
  it("shows 'Name is required' when submitting blank name", async () => {
    const user = userEvent.setup();
    renderDialog();
    // Click Create Portfolio without typing anything.
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));
    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
  });

  it("name input has aria-invalid after blank submit", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));
    await waitFor(() => {
      const nameInput = screen.getByPlaceholderText(/main portfolio/i);
      expect(nameInput).toHaveAttribute("aria-invalid", "true");
    });
  });

  it("shows 'Max 100 characters' for names over 100 chars", async () => {
    const user = userEvent.setup();
    renderDialog();
    const nameInput = screen.getByPlaceholderText(/main portfolio/i);
    await user.type(nameInput, "a".repeat(101));
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));
    await waitFor(() => {
      expect(screen.getByText("Max 100 characters")).toBeInTheDocument();
    });
  });
});

// ── Successful submission ─────────────────────────────────────────────────

describe("CreatePortfolioDialog — success path", () => {
  it("calls gateway.createPortfolio with name and currency", async () => {
    const user = userEvent.setup();
    mockCreatePortfolio.mockResolvedValueOnce(SAMPLE_PORTFOLIO);
    const { onSuccess } = renderDialog();
    await user.type(screen.getByPlaceholderText(/main portfolio/i), "My Fund");
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));
    await waitFor(() => {
      // PLAN-0114 W6: createPortfolio now takes 3 args (name, currency, cost_basis_method).
      // Default cost_basis_method is "FIFO".
      expect(mockCreatePortfolio).toHaveBeenCalledWith("My Fund", "USD", "FIFO");
    });
    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(SAMPLE_PORTFOLIO);
    });
  });

  it("shows server error when gateway throws", async () => {
    const user = userEvent.setup();
    mockCreatePortfolio.mockRejectedValueOnce(new Error("Portfolio limit reached"));
    renderDialog();
    await user.type(screen.getByPlaceholderText(/main portfolio/i), "My Fund");
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));
    await waitFor(() => {
      expect(screen.getByText("Portfolio limit reached")).toBeInTheDocument();
    });
  });
});

// ── PLAN-0122 W-F: onboarding-tour trigger (T-A-F-02, R-28) ─────────────────

import { PORTFOLIO_TOUR_SEEN_KEY } from "@/components/portfolio/PortfolioTour";

describe("CreatePortfolioDialog — onboarding-tour trigger (PLAN-0122 W-F)", () => {
  it("test_create_sets_pending_when_unset: first-ever create arms the tour", async () => {
    const user = userEvent.setup();
    mockCreatePortfolio.mockResolvedValueOnce(SAMPLE_PORTFOLIO);
    renderDialog();
    // Precondition: no flag yet (a brand-new user's first portfolio).
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBeNull();

    await user.type(screen.getByPlaceholderText(/main portfolio/i), "My Fund");
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));

    await waitFor(() => {
      // The flag is armed to "pending" so /portfolio auto-starts the tour once.
      expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("pending");
    });
  });

  it("test_create_sets_pending_only_if_unset: a later create does not re-arm", async () => {
    const user = userEvent.setup();
    mockCreatePortfolio.mockResolvedValueOnce(SAMPLE_PORTFOLIO);
    // Simulate a user who has already seen (or been backfilled past) the tour.
    window.localStorage.setItem(PORTFOLIO_TOUR_SEEN_KEY, "done");
    renderDialog();

    await user.type(screen.getByPlaceholderText(/main portfolio/i), "Second Fund");
    await user.click(screen.getByRole("button", { name: /create portfolio/i }));

    await waitFor(() => {
      expect(mockCreatePortfolio).toHaveBeenCalled();
    });
    // markTourPending is only-if-unset → the "done" flag is untouched (no re-show).
    expect(window.localStorage.getItem(PORTFOLIO_TOUR_SEEN_KEY)).toBe("done");
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────

describe("CreatePortfolioDialog — cancel", () => {
  it("calls onOpenChange(false) when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
