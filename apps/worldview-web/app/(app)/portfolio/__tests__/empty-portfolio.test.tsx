/**
 * app/(app)/portfolio/__tests__/empty-portfolio.test.tsx
 *
 * WHY THIS EXISTS (R1 sprint): with zero portfolios the page previously fell
 * through to the full tab layout — the holdings empty-state told the user to
 * "Connect a brokerage", which presumes a portfolio already exists, and there
 * was no visible path to creating one. The page now early-returns a named
 * "Select or create a portfolio" state with a prominent Create CTA. These
 * tests pin:
 *   - the named empty state renders when getPortfolios resolves to []
 *   - the CTA button is present (never a blank page)
 *   - the tab chrome (Holdings/Transactions/…) is NOT rendered in this state
 *
 * MOCKING MIRRORS __tests__/portfolio.test.tsx: gateway, auth, and router are
 * stubbed; nuqs gets its testing adapter. The only difference is
 * getPortfolios → [].
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import PortfolioPage from "@/app/(app)/portfolio/page";

// ── Next.js navigation mock ───────────────────────────────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — the user has NO portfolios ────────────────────────────────
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    // The case under test: an empty portfolio list.
    getPortfolios: vi.fn().mockResolvedValue([]),
    // Watchlists query fires unconditionally (enabled on accessToken only);
    // resolve empty so no unhandled rejection noise appears in the output.
    getWatchlists: vi.fn().mockResolvedValue([]),
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: {
        user_id: "u1",
        tenant_id: "t1",
        email: "trader@example.com",
        name: "Test Trader",
        avatar_url: null,
      },
      expires_in: 900,
    }),
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

// ── Test helpers ──────────────────────────────────────────────────────────────

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <NuqsTestingAdapter searchParams="">
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </NuqsTestingAdapter>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PortfolioPage — empty portfolio state (R1 sprint)", () => {
  it("renders the named 'Select or create a portfolio' state", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("empty-portfolio-state")).toBeInTheDocument();
    });
    // The named heading — never a blank page.
    expect(
      screen.getByText("Select or create a portfolio"),
    ).toBeInTheDocument();
  });

  it("renders a prominent Create portfolio CTA", async () => {
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Create your first portfolio" }),
      ).toBeInTheDocument();
    });
  });

  it("does NOT render the tab chrome while no portfolio exists", async () => {
    // WHY: tabs over an empty book are dead chrome — every tab body would be
    // an empty state. The early return keeps the single CTA as the only focus.
    render(<PortfolioPage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("empty-portfolio-state")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("tab", { name: "Holdings" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Transactions" }),
    ).not.toBeInTheDocument();
  });
});
