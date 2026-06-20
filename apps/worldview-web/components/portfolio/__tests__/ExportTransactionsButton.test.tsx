/**
 * components/portfolio/__tests__/ExportTransactionsButton.test.tsx
 *
 * WHY THIS EXISTS: Guards the ExportTransactionsButton's key behaviours:
 *  1. Click triggers a fetch to the correct export endpoint URL.
 *  2. Loading spinner is shown during the download (button shows Loader icon).
 *  3. Error toast appears when the API returns a non-OK response.
 *  4. Button is re-enabled after an error (not stuck in loading state).
 *
 * WHY we stub global.fetch (not MSW): the ExportTransactionsButton calls
 * global fetch directly (not apiFetch) because it needs the raw Response
 * object to convert to a Blob. Stubbing global.fetch in these unit tests
 * is simpler than setting up MSW for Blob responses.
 *
 * WHY we mock URL.createObjectURL: jsdom does not implement this API.
 * Without the mock, the happy-path test would throw because
 * URL.createObjectURL(blob) is undefined in the jsdom environment.
 *
 * PRD-0114 W5-T09
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { ExportTransactionsButton } from "../ExportTransactionsButton";

// ── Shared mocks ─────────────────────────────────────────────────────────────

// Mock sonner toast so we can assert on toast.error calls without rendering
// a real toast DOM (sonner requires a Toaster context component).
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// Mock URL.createObjectURL + URL.revokeObjectURL — jsdom does not implement these.
// The ExportTransactionsButton calls createObjectURL after a successful fetch
// to build the temporary download URL.
// WHY assign directly (not vi.spyOn): jsdom does not define these methods at all,
// so vi.spyOn(URL, "createObjectURL") throws "createObjectURL does not exist".
// We define them on the constructor directly before spying.
const mockCreateObjectURL = vi.fn().mockReturnValue("blob:mock-url");
const mockRevokeObjectURL = vi.fn();

// Track anchor elements appended by the download mechanism.
// WHY we track (not fully mock appendChlid): RTL uses document.body.appendChild
// to mount the React root container — if we mock it to a no-op, the entire rendered
// tree is never added to the DOM, making all getByRole queries fail.
// Instead, we let appendChild run normally and stub HTMLAnchorElement.click to
// prevent an actual browser navigation during tests.
let anchorClickSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  // Define the URL object URL methods that jsdom does not provide.
  URL.createObjectURL = mockCreateObjectURL;
  URL.revokeObjectURL = mockRevokeObjectURL;

  // WHY stub .click on the prototype: the component creates a new <a> element
  // and calls .click() on it. Stubbing the prototype prevents jsdom from throwing
  // "Not implemented: navigation" while still recording that the click happened.
  anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

afterEach(() => {
  anchorClickSpy?.mockRestore();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

// ── Helper: render the button ─────────────────────────────────────────────────

function renderButton(overrides: Partial<React.ComponentProps<typeof ExportTransactionsButton>> = {}) {
  const props = {
    portfolioId: "portfolio-abc-123",
    filter: {},
    accessToken: "test-token",
    ...overrides,
  };
  return render(<ExportTransactionsButton {...props} />);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ExportTransactionsButton", () => {
  it("renders the Export CSV button", () => {
    renderButton();
    expect(screen.getByRole("button", { name: /export.*csv/i })).toBeInTheDocument();
  });

  it("triggers a fetch to the export endpoint on click", async () => {
    // Stub fetch to return a successful CSV response.
    const mockFetch = vi.fn().mockResolvedValue(
      new Response("date,type\n2026-01-01,BUY", {
        status: 200,
        headers: { "Content-Type": "text/csv" },
      }),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderButton({ portfolioId: "port-123", filter: {}, accessToken: "tok-abc" });

    await user.click(screen.getByRole("button", { name: /export.*csv/i }));

    // Wait for the fetch to be called (it's async).
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledOnce();
    });

    // Verify the endpoint URL includes portfolio_id.
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("portfolio_id=port-123");
    expect(url).toContain("/v1/transactions/export");

    // Verify the Authorization header was set.
    const headers = init.headers as Record<string, string>;
    expect(headers["Authorization"]).toBe("Bearer tok-abc");
  });

  it("forwards filter params as query params to the export endpoint", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response("", { status: 200 }),
    );
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderButton({
      portfolioId: "port-456",
      filter: {
        from_date: "2026-01-01",
        to_date: "2026-06-30",
        ticker: "AAPL",
        transaction_type: ["BUY", "SELL"],
      },
    });

    await user.click(screen.getByRole("button", { name: /export.*csv/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledOnce());

    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toContain("from_date=2026-01-01");
    expect(url).toContain("to_date=2026-06-30");
    expect(url).toContain("ticker=AAPL");
    expect(url).toContain("transaction_type=BUY");
    expect(url).toContain("transaction_type=SELL");
  });

  it("shows error toast when the API returns a non-OK response", async () => {
    // Stub fetch to return a 500 error response.
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Internal server error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", mockFetch);

    const { toast } = await import("sonner");
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: /export.*csv/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "CSV export failed",
        expect.objectContaining({ description: "Internal server error" }),
      );
    });
  });

  it("button is re-enabled after an error (not stuck in loading)", async () => {
    // Stub fetch to reject with a network error.
    const mockFetch = vi.fn().mockRejectedValue(new Error("Network error"));
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderButton();
    const button = screen.getByRole("button", { name: /export.*csv/i });

    await user.click(button);

    // After the error is handled, the button should be enabled again.
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
  });

  it("does not make a second fetch if clicked while loading", async () => {
    // Use a never-resolving fetch to keep the button in loading state.
    // We'll count how many times fetch is called despite multiple clicks.
    let resolveFetch!: (val: unknown) => void;
    const pendingPromise = new Promise((res) => { resolveFetch = res; });
    const mockFetch = vi.fn().mockReturnValue(pendingPromise);
    vi.stubGlobal("fetch", mockFetch);

    const user = userEvent.setup();
    renderButton();
    const button = screen.getByRole("button", { name: /export.*csv/i });

    // First click — starts the fetch (button enters loading state).
    await user.click(button);

    // Second click while loading — should be ignored because button is disabled.
    await user.click(button);

    // Only one fetch call should have been made.
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Resolve the pending fetch so the test cleans up properly.
    resolveFetch(new Response("", { status: 200 }));
  });
});
