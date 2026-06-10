/**
 * __tests__/screener-empty-states.test.tsx — Round-3 item 5: EmptyState
 * migration + distinct zero-states.
 *
 * WHY THIS EXISTS: the screener used one DashboardEmptyState for every
 * zero-row outcome. Round 3 migrated it onto the shared
 * components/primitives/EmptyState (icon + action API, DS §15.12) with TWO
 * distinct user-facing states:
 *
 *   COLD START         — default filters AND the server universe is empty.
 *                        Copy: "No instruments yet". NO Reset CTA (resetting
 *                        filters can't conjure data).
 *   FILTERED-TO-ZERO   — active filters excluded everything.
 *                        Copy: "No results match your filters" + Reset CTA.
 *
 * The filtered-state headline + Reset round-trip is ALREADY pinned by
 * __tests__/screener.test.tsx (client-side filter path); this file covers the
 * cold-start branch and the cold↔filtered distinction with a ZERO-row server
 * response, which that file's 2-row mock cannot produce.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

// ── Gateway mock — EMPTY universe (total: 0) ─────────────────────────────────
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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <NuqsTestingAdapter searchParams="">
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      </NuqsTestingAdapter>
    );
  };
}

const EMPTY_RESPONSE = { results: [], total: 0, offset: 0, limit: 50 };

beforeEach(() => {
  runScreenerMock.mockReset();
  // WHY a fresh object per call (not mockResolvedValue(EMPTY_RESPONSE)): the
  // real gateway returns a NEW response object per request. Reusing one shared
  // reference makes TanStack hand back an identical `data` reference across
  // different query keys, which (correctly) suppresses the page's
  // [data, offset] merge effect after a filter reset — a mock artifact, not a
  // product behaviour.
  runScreenerMock.mockImplementation(async () => ({ ...EMPTY_RESPONSE }));
});

describe("ScreenerPage — distinct zero-states (Round 3 item 5)", () => {
  it("shows the COLD-START state (no Reset CTA) when default filters return an empty universe", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Cold-start copy from lib/copy/empty-states.ts "screener.cold-start".
    expect(await screen.findByText("No instruments yet")).toBeInTheDocument();
    // WHY no Reset CTA here: there are no filters to widen — offering a reset
    // button that does nothing would be a broken affordance.
    expect(
      screen.queryByRole("button", { name: /reset filters and show all instruments/i }),
    ).not.toBeInTheDocument();
    // And it must NOT claim the user's filters caused the emptiness.
    expect(screen.queryByText("No results match your filters")).not.toBeInTheDocument();
  });

  it("switches to the FILTERED state (headline + Reset CTA) once a filter is active", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });

    // Wait for the cold-start state first (query resolved, zero rows).
    await screen.findByText("No instruments yet");

    // Apply a search filter — filters are no longer DEFAULT_FILTERS, so the
    // same zero-row outcome must now present as "your filters matched nothing".
    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    await user.type(
      screen.getByLabelText(/search instruments by name or ticker/i),
      "AAPL",
    );
    await user.click(screen.getByRole("button", { name: /apply filters/i }));

    await waitFor(() => {
      expect(screen.getByText("No results match your filters")).toBeInTheDocument();
    });
    // The actionable Reset CTA lives in the EmptyState `action` slot now.
    expect(
      screen.getByRole("button", { name: /reset filters and show all instruments/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("No instruments yet")).not.toBeInTheDocument();
  });

  it("returns to the cold-start state when the Reset CTA restores default filters", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("No instruments yet");

    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    await user.type(
      screen.getByLabelText(/search instruments by name or ticker/i),
      "AAPL",
    );
    await user.click(screen.getByRole("button", { name: /apply filters/i }));
    await screen.findByText("No results match your filters");

    await user.click(
      screen.getByRole("button", { name: /reset filters and show all instruments/i }),
    );

    // Filters back to defaults + still an empty universe → cold start again.
    await waitFor(() => {
      expect(screen.getByText("No instruments yet")).toBeInTheDocument();
    });
    expect(screen.queryByText("No results match your filters")).not.toBeInTheDocument();
  });
});
