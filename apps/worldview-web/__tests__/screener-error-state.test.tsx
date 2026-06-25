/**
 * __tests__/screener-error-state.test.tsx — Round-4 item 1: error recovery.
 *
 * WHY THIS EXISTS: before Round 4 a failed screener query rendered a BLANK
 * grid — page.tsx destructured `error` from useQuery but never rendered it,
 * and the zero-state was guarded by `!error`, so the user saw column headers
 * over nothing with no recovery affordance. DS §6.1 mandates a named error
 * state with retry for EVERY data fetch. This file pins:
 *
 *   1. Query failure → "Couldn't load" error state with a Retry button —
 *      NOT a blank grid, NOT a stuck skeleton overlay.
 *   2. Retry actually refetches: a transient failure recovers to data rows.
 *   3. Load More page failure (rows already on screen) → inline error strip
 *      with its own Retry; the loaded rows are NOT blanked.
 *   4. The Retry button is keyboard-focusable (a11y, Round-4 item 2).
 *
 * MOCK SHAPE: mirrors screener-empty-states.test.tsx — a vi.hoisted
 * runScreenerMock so each test scripts its own success/failure sequence.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

// ── Gateway mock — per-test scripted runScreener ─────────────────────────────
const { runScreenerMock } = vi.hoisted(() => ({
  runScreenerMock: vi.fn(),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    runScreener: runScreenerMock,
    refreshToken: vi.fn(),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/screener"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

import ScreenerPage from "@/app/(app)/screener/page";

function makeWrapper() {
  // WHY retry: false — the page relies on TanStack settling to the error
  // state; default retries (3 × backoff) would make these tests take ~10s.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <NuqsTestingAdapter searchParams="">
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </NuqsTestingAdapter>
    );
  };
}

/** Build a minimal valid screener row — only fields the renderers read. */
function makeRow(i: number) {
  return {
    instrument_id: `ins-${i}`,
    entity_id: `ent-${i}`,
    ticker: `TK${i}`,
    name: `Test Co ${i}`,
    exchange: "NASDAQ",
    gics_sector: "Information Technology",
    market_cap: 1_000_000_000 + i,
    pe_ratio: 20,
    daily_return: 0.01,
    market_impact_score: 0.5,
  };
}

beforeEach(() => {
  runScreenerMock.mockReset();
});

describe("ScreenerPage — query-failure error state (Round 4 item 1)", () => {
  it("shows a named error state with Retry on failure — not a blank grid or stuck skeleton", async () => {
    runScreenerMock.mockRejectedValue(new Error("S9 unavailable"));
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Named error state — copy from lib/copy/empty-states.ts "generic.error".
    expect(await screen.findByText("Couldn't load")).toBeInTheDocument();

    // Retry affordance is present and uniquely labeled.
    const retry = screen.getByRole("button", { name: /retry screener query/i });
    expect(retry).toBeInTheDocument();
    expect(retry).toBeEnabled();

    // NOT a stuck skeleton: once the query settles to error, isLoading is
    // false, so the loading overlay must be gone.
    expect(screen.queryByTestId("screener-table-skeleton")).not.toBeInTheDocument();

    // The grid itself stays mounted (headers visible) — the error card is an
    // overlay, not a replacement, so the page structure doesn't collapse.
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);

    // The zero-state must NOT fire on error — an error is not "no matches".
    expect(screen.queryByText("No results match your filters")).not.toBeInTheDocument();
    expect(screen.queryByText("No instruments yet")).not.toBeInTheDocument();
  });

  it("Retry refetches the same query and recovers to data rows", async () => {
    const user = userEvent.setup();
    // First call fails; every subsequent call succeeds.
    runScreenerMock
      .mockRejectedValueOnce(new Error("transient 502"))
      .mockImplementation(async () => ({
        results: [makeRow(1), makeRow(2)],
        total: 2,
        offset: 0,
        limit: 50,
      }));

    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("Couldn't load");

    await user.click(screen.getByRole("button", { name: /retry screener query/i }));

    // Recovery: rows render, error card unmounts.
    expect(await screen.findByText("TK1")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load")).not.toBeInTheDocument();
    // Exactly 2 calls: the failed initial fetch + the retry — proves Retry
    // re-fired the SAME query rather than resetting filters/pagination.
    expect(runScreenerMock).toHaveBeenCalledTimes(2);
  });

  it("the Retry button is keyboard-focusable (a11y)", async () => {
    runScreenerMock.mockRejectedValue(new Error("down"));
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("Couldn't load");

    const retry = screen.getByRole("button", { name: /retry screener query/i });
    retry.focus();
    // A focusable element is the precondition for keyboard activation
    // (Enter/Space on a native <button> is browser-native behaviour).
    expect(retry).toHaveFocus();
  });
});

describe("ScreenerPage — Load More failure keeps loaded rows (Round 4 item 1)", () => {
  it("shows an inline error strip with Retry instead of blanking the table", async () => {
    const user = userEvent.setup();
    // Page 1 (offset 0): 50 rows of a 100-row universe → Load More appears.
    // Page 2 (offset 50): fails. Page 2 retry: succeeds.
    const page1 = {
      results: Array.from({ length: 50 }, (_, i) => makeRow(i)),
      total: 100,
      offset: 0,
      limit: 50,
    };
    const page2 = {
      results: Array.from({ length: 50 }, (_, i) => makeRow(50 + i)),
      total: 100,
      offset: 50,
      limit: 50,
    };
    runScreenerMock
      .mockImplementationOnce(async () => ({ ...page1 }))
      .mockRejectedValueOnce(new Error("page 2 boom"))
      .mockImplementation(async () => ({ ...page2 }));

    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("TK0");

    // Load More is offered (50 of 100 loaded), then fails.
    await user.click(screen.getByRole("button", { name: /load 50 more results/i }));

    // Inline strip appears with its own retry…
    expect(await screen.findByText(/couldn't load more results/i)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /retry loading more results/i });
    expect(retry).toBeInTheDocument();
    // …and the already-loaded rows are NOT blanked (no full-page error card).
    expect(screen.getByText("TK0")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load")).not.toBeInTheDocument();
    // The regular Load More button is hidden while errored — the strip owns
    // the retry path (no two competing affordances for the same request).
    expect(
      screen.queryByRole("button", { name: /load 50 more results/i }),
    ).not.toBeInTheDocument();

    // Retrying loads page 2 and clears the strip.
    await user.click(retry);
    expect(await screen.findByText("TK99")).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load more results/i)).not.toBeInTheDocument();
  });
});
