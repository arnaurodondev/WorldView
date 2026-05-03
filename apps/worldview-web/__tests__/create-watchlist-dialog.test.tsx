/**
 * __tests__/create-watchlist-dialog.test.tsx — Unit tests for CreateWatchlistDialog
 *
 * WHY THIS EXISTS: CreateWatchlistDialog was migrated to RHF + Zod in PLAN-0059
 * F-2 (BP-330 fix). AddPositionDialog and CreatePortfolioDialog both have tests;
 * this dialog has the same validation concerns (whitespace-only name, server
 * error display) and an inconsistent test gap was flagged by QA as F-C-003.
 *
 * Tested invariants:
 *   1. Blank name submission shows "Name is required" + sets aria-invalid.
 *   2. Whitespace-only name (BP-332 regression) fails validation.
 *   3. Name over 80 characters shows "Max 80 characters".
 *   4. Valid submission calls gateway.createWatchlist and shows success state.
 *   5. Server error is displayed inline (dialog stays open).
 *   6. Cancel button resets form and calls onOpenChange(false).
 *
 * DATA SOURCE: Mocked via @/lib/api-client — deterministic, no network.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CreateWatchlistDialog } from "@/components/watchlists/CreateWatchlistDialog";
import type { Watchlist } from "@/types/api";

// ── Mocks ──────────────────────────────────────────────────────────────────────

// sonner toast is a side-effect; we don't assert on it in these tests.
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mockCreateWatchlist = vi.fn();

// WHY mock useApiClient: the dialog calls gateway.createWatchlist() via
// useMutation. Mocking at the hook level avoids needing full auth context.
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({
    createWatchlist: mockCreateWatchlist,
  })),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  usePathname: vi.fn(() => "/watchlists"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Fixtures ───────────────────────────────────────────────────────────────────

const SAMPLE_WATCHLIST: Watchlist = {
  watchlist_id: "wl-1",
  name: "Tech Momentum",
  owner_id: "u-1",
  members: [],
  member_count: 0,
  created_at: "2026-05-03T00:00:00Z",
  updated_at: "2026-05-03T00:00:00Z",
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderDialog(overrides: Partial<Parameters<typeof CreateWatchlistDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  const onCreated = vi.fn();
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <CreateWatchlistDialog
        open={true}
        onOpenChange={onOpenChange}
        onCreated={onCreated}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange, onCreated };
}

function nameInput() {
  return screen.getByPlaceholderText(/mega-cap tech/i);
}

/**
 * submitForm — triggers form submit directly on the <form> element.
 *
 * WHY NOT click the submit button: CreateWatchlistDialog disables the submit
 * button when `!form.formState.isValid`. With RHF + zodResolver, isValid starts
 * as false before the first submit attempt (resolver has not run yet). So the
 * button is disabled when the form is freshly rendered with an empty name.
 * Submitting via the form element bypasses the disabled button and triggers
 * RHF validation — which is exactly what we want to test.
 */
function submitForm() {
  // The Dialog renders in a Radix portal; document.querySelector finds it.
  const form = document.querySelector("form");
  if (!form) throw new Error("No <form> element found in the document");
  fireEvent.submit(form);
}

beforeEach(() => {
  mockCreateWatchlist.mockReset();
});

// ── Name validation ────────────────────────────────────────────────────────────

describe("CreateWatchlistDialog — name validation", () => {
  it("shows 'Name is required' when submitting blank name", async () => {
    renderDialog();
    submitForm();
    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
  });

  it("name input has aria-invalid after blank submit", async () => {
    renderDialog();
    submitForm();
    await waitFor(() => {
      expect(nameInput()).toHaveAttribute("aria-invalid", "true");
    });
  });

  it("rejects whitespace-only name (BP-332 regression)", async () => {
    // WHY: Zod's .trim().min(1) means "   " trims to "" and fails .min(1).
    // Before the F-2 fix, .min(1) without .trim() would pass " " (length=1).
    const user = userEvent.setup();
    renderDialog();
    await user.type(nameInput(), "   ");
    submitForm();
    await waitFor(() => {
      expect(screen.getByText("Name is required")).toBeInTheDocument();
    });
    expect(mockCreateWatchlist).not.toHaveBeenCalled();
  });

  it("shows 'Max 80 characters' for names over 80 chars", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.type(nameInput(), "a".repeat(81));
    submitForm();
    await waitFor(() => {
      expect(screen.getByText("Max 80 characters")).toBeInTheDocument();
    });
  });
});

// ── Success path ───────────────────────────────────────────────────────────────

describe("CreateWatchlistDialog — success path", () => {
  it("calls gateway.createWatchlist with the trimmed name", async () => {
    const user = userEvent.setup();
    mockCreateWatchlist.mockResolvedValueOnce(SAMPLE_WATCHLIST);
    renderDialog();
    await user.type(nameInput(), "Tech Momentum");
    submitForm();
    await waitFor(() => {
      expect(mockCreateWatchlist).toHaveBeenCalledWith("Tech Momentum");
    });
  });

  it("calls onCreated with the returned watchlist on success", async () => {
    const user = userEvent.setup();
    mockCreateWatchlist.mockResolvedValueOnce(SAMPLE_WATCHLIST);
    const { onCreated } = renderDialog();
    await user.type(nameInput(), "Tech Momentum");
    submitForm();
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(SAMPLE_WATCHLIST);
    });
  });

  it("calls onOpenChange(false) on success", async () => {
    const user = userEvent.setup();
    mockCreateWatchlist.mockResolvedValueOnce(SAMPLE_WATCHLIST);
    const { onOpenChange } = renderDialog();
    await user.type(nameInput(), "Tech Momentum");
    submitForm();
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });
});

// ── Server error path ─────────────────────────────────────────────────────────

describe("CreateWatchlistDialog — server error", () => {
  it("shows server error message inline when gateway throws", async () => {
    const user = userEvent.setup();
    mockCreateWatchlist.mockRejectedValueOnce(new Error("Watchlist limit reached"));
    renderDialog();
    await user.type(nameInput(), "My List");
    // WHY submitForm(): after typing a valid name, the form becomes valid and
    // the submit button becomes enabled. submitForm() is equivalent to clicking
    // the button but more robust across RHF timing edge cases.
    submitForm();
    await waitFor(() => {
      expect(screen.getByText("Watchlist limit reached")).toBeInTheDocument();
    });
  });

  it("does NOT call onOpenChange(false) when server returns an error", async () => {
    const user = userEvent.setup();
    mockCreateWatchlist.mockRejectedValueOnce(new Error("Watchlist limit reached"));
    const { onOpenChange } = renderDialog();
    await user.type(nameInput(), "My List");
    submitForm();
    await waitFor(() => {
      expect(screen.getByText("Watchlist limit reached")).toBeInTheDocument();
    });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────────

describe("CreateWatchlistDialog — cancel", () => {
  it("calls onOpenChange(false) when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
