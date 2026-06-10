/**
 * __tests__/screener-a11y.test.tsx — Round-4 item 2: accessibility hardening.
 *
 * Pins the Round-4 a11y contract for the screener surface:
 *   1. The results grid lives inside a NAMED landmark (role="region" with
 *      aria-label "Screener results") — AgGridBase is shared and doesn't
 *      forward a label to AG Grid's internal role="grid" element, so the
 *      page-level region is the navigable handle for AT users.
 *   2. Every toolbar control has an accessible name.
 *   3. The empty-state Reset CTA is keyboard-reachable AND keyboard-
 *      activatable (Enter on the focused button resets the filters).
 *
 * (Slider aria-valuetext is pinned in RangeSliderRow.test.tsx; filter-chip
 * dismiss labels in FilterChipStrip.test.tsx — co-located with their
 * components.)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";

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

const ONE_ROW_RESPONSE = {
  results: [
    {
      instrument_id: "ins-1",
      entity_id: "ent-1",
      ticker: "AAPL",
      name: "Apple Inc.",
      gics_sector: "Information Technology",
      market_cap: 3e12,
      pe_ratio: 28.5,
      daily_return: 0.01,
      market_impact_score: 0.75,
    },
  ],
  total: 1,
  offset: 0,
  limit: 50,
};

beforeEach(() => {
  runScreenerMock.mockReset();
  runScreenerMock.mockImplementation(async () => ({ ...ONE_ROW_RESPONSE }));
});

describe("ScreenerPage — a11y hardening (Round 4 item 2)", () => {
  it("exposes the results grid inside a named region landmark", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("AAPL");
    expect(
      screen.getByRole("region", { name: /screener results/i }),
    ).toBeInTheDocument();
  });

  it("every toolbar control has an accessible name", async () => {
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("AAPL");
    // The full toolbar set: Filters toggle, Saved Screens, column gear, Export.
    expect(
      screen.getByRole("button", { name: /toggle screener filters/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /saved screens/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /configure columns/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export results/i })).toBeInTheDocument();
  });

  it("the empty-state Reset CTA is keyboard-reachable and Enter-activatable", async () => {
    const user = userEvent.setup();
    render(<ScreenerPage />, { wrapper: makeWrapper() });
    await screen.findByText("AAPL");

    // Filter everything out client-side to surface the filtered-to-zero state.
    await user.click(screen.getByRole("button", { name: /toggle screener filters/i }));
    await user.type(
      screen.getByLabelText(/search instruments by name or ticker/i),
      "ZZZZNOMATCH",
    );
    await user.click(screen.getByRole("button", { name: /apply filters/i }));
    await screen.findByText("No results match your filters");

    const cta = screen.getByRole("button", {
      name: /reset filters and show all instruments/i,
    });
    // Keyboard-reachable: a real, enabled <button> accepts programmatic focus
    // (the same precondition Tab order uses — disabled/divs would fail here).
    cta.focus();
    expect(cta).toHaveFocus();

    // Keyboard-activatable: Enter on the focused CTA fires the reset and the
    // rows come back — proving the recovery path needs zero pointer input.
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByText("AAPL")).toBeInTheDocument());
    expect(screen.queryByText("No results match your filters")).not.toBeInTheDocument();
  });
});
