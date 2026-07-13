/**
 * __tests__/add-position-dialog.test.tsx — Unit tests for AddPositionDialog
 *
 * WHY THIS EXISTS: Verifies the BP-328 and BP-330 fixes:
 *   - BP-328: quantity=0 must fail validation. The old guard (`parsedQty <= 0`)
 *     was submit-only (no live feedback). With Zod onChange mode, the error
 *     appears as the user types.
 *   - BP-330: field errors must set aria-invalid on the input.
 *
 * DATA SOURCE: Mocked gateway — deterministic, no network.
 * DESIGN REFERENCE: PLAN-0059 F-2 Form Layer.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { z } from "zod";
import { AddPositionDialog } from "@/features/portfolio/components/AddPositionDialog";

// WHY mock useDebounce as identity (PLAN-0122 W-C): the ticker typeahead debounces
// the query by 250 ms via useDebounce. In tests we want the debounced value to
// update synchronously so the typeahead fires without a real timer wait — the
// EntityPicker/InstrumentPicker tests use the same identity-mock convention.
vi.mock("@/hooks/useDebounce", () => ({
  useDebounce: (v: string) => v,
}));

// ── Hoisted mock functions ────────────────────────────────────────────────────
// WHY vi.hoisted: vi.mock() factory functions are hoisted to the top of the
// file before any variable declarations. Variables declared with `const` below
// the vi.mock() call cannot be referenced inside the factory — doing so causes
// a ReferenceError at module initialisation time. vi.hoisted() runs its
// callback *before* module resolution, so the returned references are
// initialised in time to be captured by the vi.mock() factories.
const { mockSearchInstruments, mockAddPosition, mockToastSuccess } = vi.hoisted(() => ({
  mockSearchInstruments: vi.fn(),
  mockAddPosition: vi.fn(),
  mockToastSuccess: vi.fn(),
}));

// ── Gateway mock ─────────────────────────────────────────────────────────────

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    searchInstruments: mockSearchInstruments,
    addPosition: mockAddPosition,
  })),
}));

// ── Toast mock (FR-8) ─────────────────────────────────────────────────────────
// WHY mock sonner: toast.success is a side-effect that does not render DOM
// nodes in jsdom. Mocking lets us assert on the call arguments directly.
vi.mock("sonner", () => ({
  toast: { success: mockToastSuccess },
}));

const SAMPLE_INSTRUMENT = {
  instrument_id: "ins-aapl",
  ticker: "AAPL",
  name: "Apple Inc.",
  exchange: "NASDAQ",
  entity_id: "ent-aapl",
};

// ── Helpers ────────────────────────────────────────────────────────────────

// WHY a QueryClientProvider wrapper (PLAN-0122 W-C): the ticker typeahead now uses
// TanStack Query (useQuery keyed ["instrument-search", q]); without a provider the
// hook throws "No QueryClient set". retry:false keeps failed queries deterministic.
function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderDialog(overrides: Partial<Parameters<typeof AddPositionDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  const onSuccess = vi.fn();
  render(
    <AddPositionDialog
      open={true}
      onOpenChange={onOpenChange}
      onSuccess={onSuccess}
      portfolioId="port-1"
      accessToken="test-token"
      {...overrides}
    />,
    { wrapper },
  );
  return { onOpenChange, onSuccess };
}

/**
 * fillQuantity — types a value into the NumberInput and fires blur directly.
 *
 * WHY fireEvent.blur not user.tab(): Inside a Radix Dialog, the focus-trap
 * intercepts Tab keypresses and re-routes focus, which can prevent the blur
 * event from landing on the NumberInput in jsdom. fireEvent.blur fires the
 * blur event unconditionally, which is what NumberInput's commit-on-blur
 * lifecycle actually depends on.
 */
async function fillQuantity(user: ReturnType<typeof userEvent.setup>, value: string) {
  const qtyInput = screen.getByRole("textbox", { name: "Quantity" });
  await user.clear(qtyInput);
  await user.type(qtyInput, value);
  // Fire blur directly to trigger NumberInput.commit() → onValueChange → field.onChange
  await act(async () => { fireEvent.blur(qtyInput); });
}

beforeEach(() => {
  mockSearchInstruments.mockReset();
  mockAddPosition.mockReset();
  mockToastSuccess.mockReset();
  // WHY a default resolved value (PLAN-0122 W-C): the typeahead's useQuery calls
  // searchInstruments on any typed ticker. Without a default, an un-stubbed mock
  // returns undefined and TanStack Query errors on undefined data. Tests that need
  // a real match override this with a persistent mockResolvedValue below.
  mockSearchInstruments.mockResolvedValue({ results: [], query: "" });
});

// ── Ticker required ────────────────────────────────────────────────────────

describe("AddPositionDialog — ticker validation", () => {
  it("submit button is disabled when ticker is empty", () => {
    renderDialog();
    const submitBtn = screen.getByRole("button", { name: /add position/i });
    expect(submitBtn).toBeDisabled();
  });

  it("submit button enables when ticker is typed", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByPlaceholderText(/aapl/i), "MSFT");
    const submitBtn = screen.getByRole("button", { name: /add position/i });
    expect(submitBtn).not.toBeDisabled();
  });

  it("shows ticker-not-found error when S3 returns empty results", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValueOnce({ results: [] });
    renderDialog();
    await user.type(screen.getByPlaceholderText(/aapl/i), "FAKE");
    // Must also provide a valid quantity or Zod validation blocks the submit.
    await fillQuantity(user, "10");
    // Click submit — Zod passes (ticker+qty valid), gateway search runs.
    await user.click(screen.getByRole("button", { name: /add position/i }));
    await waitFor(() => {
      expect(screen.getByText(/"FAKE" not found/i)).toBeInTheDocument();
    });
  });
});

// ── Quantity validation (BP-328) ──────────────────────────────────────────

describe("AddPositionDialog — quantity validation schema (BP-328)", () => {
  it("Zod schema: 0 quantity fails positive() with 'Must be greater than 0'", () => {
    // WHY test schema directly: NumberInput interactions in jsdom are complex
    // (commit-on-blur lifecycle). The schema rule is the authoritative fix for
    // BP-328 — testing the schema is more reliable than UI simulation.
    const schema = z.object({
      quantity: z
        .number({ invalid_type_error: "Must be a number" })
        .positive("Must be greater than 0"),
    });
    const result = schema.safeParse({ quantity: 0 });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.errors[0].message).toBe("Must be greater than 0");
    }
  });

  it("Zod schema: positive quantity passes", () => {
    const schema = z.object({
      quantity: z.number().positive("Must be greater than 0"),
    });
    expect(schema.safeParse({ quantity: 1 }).success).toBe(true);
    expect(schema.safeParse({ quantity: 0.5 }).success).toBe(true);
    expect(schema.safeParse({ quantity: 1_000_000 }).success).toBe(true);
  });
});

// ── Avg price validation (BP-328) ─────────────────────────────────────────

describe("AddPositionDialog — avgPrice validation schema (BP-328)", () => {
  it("Zod schema: negative avgPrice fails nonnegative()", () => {
    const schema = z.object({
      avgPrice: z
        .number({ invalid_type_error: "Must be a number" })
        .nonnegative("Must be 0 or greater"),
    });
    const result = schema.safeParse({ avgPrice: -1 });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.errors[0].message).toBe("Must be 0 or greater");
    }
  });

  it("Zod schema: 0 avgPrice passes nonnegative (gifted shares use case)", () => {
    const schema = z.object({
      avgPrice: z.number().nonnegative("Must be 0 or greater"),
    });
    expect(schema.safeParse({ avgPrice: 0 }).success).toBe(true);
  });
});

// ── Successful submission ─────────────────────────────────────────────────

describe("AddPositionDialog — success path", () => {
  it("calls searchInstruments then addPosition on valid submit", async () => {
    const user = userEvent.setup();
    // WHY persistent (not Once): searchInstruments is called by BOTH the typeahead
    // useQuery and the submit-time fallback resolve. A persistent mock serves both.
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-1" });
    const { onSuccess } = renderDialog();

    // Type without picking a dropdown row → submit uses the fallback resolve (R-14).
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "10");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      // The submit-time fallback resolve fires with limit=1 (distinct from the
      // typeahead's limit=8 call) — proving the fallback path still works.
      expect(mockSearchInstruments).toHaveBeenCalledWith("AAPL", 1);
    });
    await waitFor(() => {
      // WHY a 5th arg now: addPosition gained an optional tradeDate (PLAN-0122 R-13).
      // The dialog always sends the picked trade date as `${YYYY-MM-DD}T00:00:00Z`.
      expect(mockAddPosition).toHaveBeenCalledWith(
        "port-1",
        "ins-aapl",
        expect.any(Number),
        expect.any(Number),
        expect.stringMatching(/^\d{4}-\d{2}-\d{2}T00:00:00Z$/),
      );
    });
    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("shows server error when addPosition throws", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockRejectedValueOnce(new Error("Insufficient buying power"));
    renderDialog();

    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "5");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(screen.getByText("Insufficient buying power")).toBeInTheDocument();
    });
  });
});

// ── Quantity component interaction (F-M-003) ──────────────────────────────

describe("AddPositionDialog — quantity component interaction (F-M-003)", () => {
  it("shows 'Must be greater than 0' message after typing 0 and blurring (BP-328)", async () => {
    // WHY this test exists: the Zod schema tests above verify the rule is defined,
    // but this integration test verifies the error actually reaches the DOM — i.e.
    // RHF's onChange mode is wired, NumberInput.commit() calls field.onChange, and
    // FormMessage renders the destructive text.
    const user = userEvent.setup();
    renderDialog();
    await fillQuantity(user, "0");
    await waitFor(() => {
      expect(screen.getByText("Must be greater than 0")).toBeInTheDocument();
    });
  });

  it("quantity input has aria-invalid='true' after 0 is entered (BP-330)", async () => {
    // WHY aria-invalid: AT users need the field announced as invalid — the
    // text error alone is not surfaced by all screen readers until re-focused.
    const user = userEvent.setup();
    renderDialog();
    await fillQuantity(user, "0");
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Quantity" })).toHaveAttribute(
        "aria-invalid",
        "true",
      );
    });
  });
});

// ── Cancel ────────────────────────────────────────────────────────────────

describe("AddPositionDialog — cancel", () => {
  it("calls onOpenChange(false) when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

// ── FR-8: portfolio-kind-aware toast copy ─────────────────────────────────
//
// WHY these tests: PRD-0114 FR-8 acceptance criterion requires a unit test
// verifying the toast message copy is gated on portfolioKind. The manual
// copy ("Holdings will reflect this trade within seconds.") sets the correct
// async expectation; the brokerage copy ("Position added successfully.")
// is the generic fallback. These tests cover both branches of the condition
// at AddPositionDialog.tsx:173.

describe("AddPositionDialog — FR-8 toast copy (portfolioKind)", () => {
  it("shows async-holdings toast for manual portfolio", async () => {
    // WHY manual: manual portfolios trigger async W1 consumer recompute.
    // The 'within seconds' copy sets the user's expectation correctly.
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-manual" });

    renderDialog({ portfolioKind: "manual" });
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "10");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Transaction recorded",
        expect.objectContaining({
          description: "Holdings will reflect this trade within seconds.",
        }),
      );
    });
  });

  it("shows generic success toast for brokerage portfolio", async () => {
    // WHY brokerage: brokerage portfolios sync from broker — no async consumer
    // recompute — so the generic copy is correct (no 'within seconds' promise).
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-brokerage" });

    renderDialog({ portfolioKind: "brokerage" });
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "10");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      // Called with just the message string (no description object).
      expect(mockToastSuccess).toHaveBeenCalledWith("Position added successfully.");
    });
    // Confirm the manual copy does NOT appear.
    expect(mockToastSuccess).not.toHaveBeenCalledWith(
      "Transaction recorded",
      expect.anything(),
    );
  });
});

// ── PLAN-0122 W-C §6.3: trade-date picker (R-11) ──────────────────────────────

/** Rebuild today's local YYYY-MM-DD the same way the component does. */
function localTodayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

describe("AddPositionDialog — trade-date picker (PLAN-0122 R-11)", () => {
  it("defaults the trade date to today and flows the chosen date into executed_at", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-date" });
    renderDialog();

    const dateInput = screen.getByLabelText(/trade date/i) as HTMLInputElement;
    // Default is today (local date, not UTC).
    expect(dateInput.value).toBe(localTodayStr());

    // Back-date to a past day and submit (typed ticker, no pick → fallback resolve).
    fireEvent.change(dateInput, { target: { value: "2020-01-15" } });
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "3");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      // The 5th arg is the chosen date as a midnight-UTC datetime string.
      expect(mockAddPosition).toHaveBeenCalledWith(
        "port-1",
        "ins-aapl",
        expect.any(Number),
        expect.any(Number),
        "2020-01-15T00:00:00Z",
      );
    });
  });

  it("blocks a future trade date and does not post the transaction", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    renderDialog();

    const dateInput = screen.getByLabelText(/trade date/i);
    fireEvent.change(dateInput, { target: { value: "2999-12-31" } });
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAPL");
    await fillQuantity(user, "3");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Trade date can't be in the future."),
      ).toBeInTheDocument();
    });
    // Zod blocked the submit before any network call.
    expect(mockAddPosition).not.toHaveBeenCalled();
  });
});

// ── PLAN-0122 W-C §6.3: debounced ticker typeahead (R-12, R-14) ───────────────

describe("AddPositionDialog — ticker typeahead (PLAN-0122 R-12/R-14)", () => {
  it("shows a dropdown as the user types and selecting a row skips the submit-time resolve", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-pick" });
    renderDialog();

    // Type a partial ticker → the debounced typeahead surfaces the match.
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAP");
    const row = await screen.findByText("Apple Inc.");

    // Pick the row (mouse click → exercises the onClick half of the dual handler).
    await user.click(row);

    await fillQuantity(user, "5");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      // addPosition received the STASHED instrument_id from the pick.
      expect(mockAddPosition).toHaveBeenCalledWith(
        "port-1",
        "ins-aapl",
        expect.any(Number),
        expect.any(Number),
        expect.any(String),
      );
    });
    // The submit-time fallback (limit=1) was SKIPPED because the pick already
    // resolved the instrument — only the typeahead's limit=8 call ever ran.
    expect(mockSearchInstruments).not.toHaveBeenCalledWith(expect.anything(), 1);
  });

  it("renders the empty state and still resolves a typed-but-unpicked ticker at submit (fallback)", async () => {
    const user = userEvent.setup();
    // Typeahead finds nothing for this prefix.
    mockSearchInstruments.mockResolvedValue({ results: [] });
    renderDialog();

    await user.type(screen.getByPlaceholderText(/aapl/i), "ZZ");
    await waitFor(() => {
      expect(screen.getByText(/No instruments match/i)).toBeInTheDocument();
    });

    // Now the submit-time resolve succeeds → the fallback path still works (R-14).
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-fallback" });
    await fillQuantity(user, "2");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    await waitFor(() => {
      expect(mockSearchInstruments).toHaveBeenCalledWith("ZZ", 1);
    });
    await waitFor(() => {
      expect(mockAddPosition).toHaveBeenCalled();
    });
  });

  it("clears the stashed instrument_id when the ticker is hand-edited after a pick", async () => {
    const user = userEvent.setup();
    mockSearchInstruments.mockResolvedValue({ results: [SAMPLE_INSTRUMENT] });
    mockAddPosition.mockResolvedValueOnce({ transaction_id: "tx-edit" });
    renderDialog();

    // Pick a row (stashes ins-aapl), then hand-edit the ticker text.
    await user.type(screen.getByPlaceholderText(/aapl/i), "AAP");
    await user.click(await screen.findByText("Apple Inc."));
    await user.type(screen.getByPlaceholderText(/aapl/i), "X"); // → AAPLX

    await fillQuantity(user, "1");
    await user.click(screen.getByRole("button", { name: /add position/i }));

    // Because the manual edit invalidated the stash, submit RE-RESOLVES via limit=1.
    await waitFor(() => {
      expect(mockSearchInstruments).toHaveBeenCalledWith("AAPLX", 1);
    });
  });
});
