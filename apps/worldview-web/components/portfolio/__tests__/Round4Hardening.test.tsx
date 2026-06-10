/**
 * components/portfolio/__tests__/Round4Hardening.test.tsx — Round-4 hardening.
 *
 * WHY THIS EXISTS: Round 4 hardened the portfolio surface's error recovery,
 * accessibility, and skeleton compliance. These tests pin the new contracts
 * so future PRs can't silently revert them:
 *
 *   1. Portfolio page  — page-level load failure renders the NAMED error
 *                        state (copy: portfolio.load-error, title pinned by
 *                        the e2e suite) with a Retry action that refetches
 *                        the portfolio-list query IN PLACE (the deferred R3
 *                        item — previously a dead-end InlineEmptyState).
 *   2. WatchlistsTabPanel — a failed remove-member mutation fires an error
 *                        toast (DS §6.16) and leaves the row on screen
 *                        (previously a SILENT failure).
 *   3. SectorAllocationDonut — panel aria-label announces the top sector,
 *                        its weight/position count, and the sector count
 *                        (was a static "Sector allocation").
 *   4. PortfolioKPIStrip — each tile is a named role="group" so values are
 *                        announced under their labels.
 *   5. TransactionsTab — pager buttons carry page context in their
 *                        accessible names ("(currently page 1 of 3)").
 *   6. HoldingRealizedRow — loading pills use the static Skeleton primitive;
 *                        raw animate-pulse is BANNED for skeletons (DS §6.2).
 *
 * MOCKED MODULES: auth, gateway, next/navigation (same set as
 * Round3Polish.test.tsx) + sonner (toast spy) + api-client (for
 * HoldingRealizedRow, which talks through useApiClient).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsTestingAdapter } from "nuqs/adapters/testing";
import type { ReactNode } from "react";

// ── Auth mock — consumers gate on accessToken; provide one. ─────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock — per-test controllable fns (hoisted refs). ────────────────
// WHY individual vi.fn() consts: tests reprogram failure modes per case
// (getPortfolios rejecting for the page-retry test, removeWatchlistMember
// rejecting for the toast test) without re-mocking the module.
const mockGetPortfolios = vi.fn();
const mockGetHoldings = vi.fn();
const mockGetBatchQuotes = vi.fn();
const mockGetTransactions = vi.fn();
const mockGetWatchlists = vi.fn();
const mockGetWatchlistMembers = vi.fn();
const mockRemoveWatchlistMember = vi.fn();
const mockGetSectorBreakdown = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPortfolios: mockGetPortfolios,
    getHoldings: mockGetHoldings,
    getBatchQuotes: mockGetBatchQuotes,
    getTransactions: mockGetTransactions,
    getWatchlists: mockGetWatchlists,
    getWatchlistMembers: mockGetWatchlistMembers,
    removeWatchlistMember: mockRemoveWatchlistMember,
    getSectorBreakdown: mockGetSectorBreakdown,
    // Surfaces the page touches on its happy path — resolved stubs so the
    // error-path test never trips an unrelated unhandled rejection.
    getCompanyOverviewsBatch: vi.fn().mockResolvedValue({}),
    getPortfolioPerformance: vi.fn().mockResolvedValue(undefined),
    getRealizedPnL: vi.fn().mockResolvedValue(null),
    getExposure: vi.fn().mockResolvedValue(undefined),
    getPortfolioBundle: vi.fn().mockResolvedValue(undefined),
    getConcentration: vi.fn().mockResolvedValue(undefined),
  })),
  GatewayError: class GatewayError extends Error {},
}));

// ── sonner mock — assert toasts without mounting a Toaster. ─────────────────
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  }),
}));

// ── next/navigation mock — row clicks push routes. ──────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── api-client mock — HoldingRealizedRow talks through useApiClient. ────────
const mockGetRealizedPnLApi = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({ getRealizedPnL: mockGetRealizedPnLApi })),
}));

// ── SUT imports (after mocks) ───────────────────────────────────────────────
import { toast } from "sonner";
import PortfolioPage from "@/app/(app)/portfolio/page";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";
import { SectorAllocationDonut } from "@/components/portfolio/SectorAllocationDonut";
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
import { HoldingRealizedRow } from "@/components/portfolio/HoldingRealizedRow";
import type { Watchlist } from "@/types/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  // retry:false — error-path tests must settle after ONE failed call, not
  // after TanStack's default 3-retry backoff (which would time the test out).
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <NuqsTestingAdapter>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </NuqsTestingAdapter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Happy-path defaults; individual tests override the failure they need.
  mockGetPortfolios.mockResolvedValue([]);
  mockGetHoldings.mockResolvedValue({ portfolio_id: "p1", holdings: [] });
  mockGetBatchQuotes.mockResolvedValue({ quotes: {} });
  mockGetTransactions.mockResolvedValue({ transactions: [], total: 0, offset: 0, limit: 100 });
  mockGetWatchlists.mockResolvedValue([]);
  mockGetWatchlistMembers.mockResolvedValue([]);
  mockRemoveWatchlistMember.mockResolvedValue(undefined);
  mockGetSectorBreakdown.mockResolvedValue({ segments: [], covered_pct: 1 });
  mockGetRealizedPnLApi.mockResolvedValue(null);
});

// ─────────────────────────────────────────────────────────────────────────────
// 1. Page-level error → named state + in-place Retry (R4 item 1a)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · portfolio page load-error retry", () => {
  it("renders the named error state with the pinned title and a Retry action", async () => {
    mockGetPortfolios.mockRejectedValue(new Error("503"));
    render(wrap(<PortfolioPage />));

    // Named state — the title string is ALSO pinned by the e2e suite
    // (qa-exhaustive "Portfolio shows error state with retry option").
    await waitFor(() =>
      expect(screen.getByTestId("portfolio-error-state")).toBeInTheDocument(),
    );
    expect(screen.getByText("Failed to load portfolio data")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry loading portfolio data" }),
    ).toBeInTheDocument();
  });

  it("Retry refetches the portfolio-list query in place (no full reload)", async () => {
    mockGetPortfolios.mockRejectedValue(new Error("503"));
    render(wrap(<PortfolioPage />));

    await waitFor(() =>
      expect(screen.getByTestId("portfolio-error-retry")).toBeInTheDocument(),
    );
    expect(mockGetPortfolios).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("portfolio-error-retry"));

    // The Retry action must re-run the SAME query — proving recovery happens
    // through TanStack refetch, not through a window reload the test
    // environment couldn't observe anyway.
    await waitFor(() => expect(mockGetPortfolios).toHaveBeenCalledTimes(2));
  });

  it("recovers to the page after a successful retry", async () => {
    // First call fails; the retried call succeeds with zero portfolios →
    // the page must transition error → empty-portfolio named state.
    mockGetPortfolios
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce([]);
    render(wrap(<PortfolioPage />));

    await waitFor(() =>
      expect(screen.getByTestId("portfolio-error-retry")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("portfolio-error-retry"));

    await waitFor(() =>
      expect(screen.getByTestId("empty-portfolio-state")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("portfolio-error-state")).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. Watchlist remove-member failure → toast + row preserved (R4 item 1d)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · watchlist mutation onError", () => {
  const WATCHLIST = {
    watchlist_id: "w1",
    name: "Tech",
    members: [],
    member_count: 1,
  } as unknown as Watchlist;

  const MEMBER = {
    entity_id: "e1",
    instrument_id: "i1",
    ticker: "AAPL",
    name: "Apple Inc.",
  };

  it("fires toast.error and keeps the row when remove fails", async () => {
    mockGetWatchlistMembers.mockResolvedValue([MEMBER]);
    mockRemoveWatchlistMember.mockRejectedValue(new Error("500"));

    render(
      wrap(<WatchlistsTabPanel watchlists={[WATCHLIST]} quotes={{}} isLoading={false} />),
    );

    // Wait for the lazily-fetched member row to mount.
    const removeBtn = await screen.findByRole("button", {
      name: "Remove AAPL from watchlist",
    });
    fireEvent.click(removeBtn);

    // DS §6.16: fire-and-forget failure → error toast.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Couldn't remove ticker from watchlist",
        expect.objectContaining({ description: expect.any(String) }),
      ),
    );
    // Row preserved — invalidation only runs onSuccess, so the member never
    // left the table (the user can simply retry the ×).
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. Donut aria-label — top sector + counts (R4 item 2)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · SectorAllocationDonut aria-label", () => {
  it("announces the top sector, its weight/positions, and the sector count", async () => {
    mockGetSectorBreakdown.mockResolvedValue({
      segments: [
        { sector: "Technology", weight: 0.421, count: 12, market_value: 50_000 },
        { sector: "Energy", weight: 0.3, count: 4, market_value: 35_000 },
      ],
      covered_pct: 1,
    });
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );

    await waitFor(() =>
      expect(screen.getByTestId("donut-chart")).toBeInTheDocument(),
    );
    // role="group" makes the label AT-exposed; the name leads with the
    // donut's primary answer ("where is my money").
    expect(
      screen.getByRole("group", {
        name: "Sector allocation: Technology is the largest sector at 42.1% across 12 positions; 2 sectors shown",
      }),
    ).toBeInTheDocument();
  });

  it("falls back to the static label while empty (the name must never lie)", async () => {
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );
    await waitFor(() =>
      expect(screen.getByTestId("donut-empty-state")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("group", { name: "Sector allocation" }),
    ).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. KPI strip — tiles are named groups (R4 item 2)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · PortfolioKPIStrip tile labelling", () => {
  it("exposes every tile as a role=group named by its label", () => {
    render(
      wrap(
        <PortfolioKPIStrip
          totalValue={10_000}
          dayPnl={120}
          unrealisedPnl={500}
          unrealisedPnlPct={0.05}
          topGainer={{ ticker: "AAPL", pnlPct: 4.2 }}
          topLoser={{ ticker: "MSFT", pnlPct: -1.1 }}
          realizedPnl={50}
          cash={1_000}
          buyingPower={1_000}
        />,
      ),
    );
    // One named group per tile — values are announced UNDER their labels
    // instead of as disconnected strings.
    for (const label of [
      "Total Value",
      "Day P&L",
      "Unrealised P&L",
      "Realized P&L",
      "Cash",
      "Buying Pwr",
      "Top Gain",
      "Top Lose",
    ]) {
      expect(screen.getByRole("group", { name: label })).toBeInTheDocument();
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. Transactions pager — page context in the accessible names (R4 item 2)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · transactions pager page-context labels", () => {
  it("buttons announce the current page position", () => {
    render(
      <TransactionsTab
        activePortfolioId="p1"
        txLoading={false}
        transactionsResp={{
          transactions: [],
          total: 250,
          offset: 100,
          limit: 100,
        }}
        holdingOverviews={undefined}
        onConnect={vi.fn()}
        onTxOffsetChange={vi.fn()}
      />,
    );
    // Page 2 of 3 (offset 100 / limit 100 / total 250).
    expect(
      screen.getByRole("button", {
        name: "Previous transactions page (currently page 2 of 3)",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Next transactions page (currently page 2 of 3)",
      }),
    ).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 6. HoldingRealizedRow — static Skeleton, no raw animate-pulse (DS §6.2)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · HoldingRealizedRow skeleton compliance", () => {
  it("loading pills use the Skeleton primitive without animate-pulse", () => {
    // Never-resolving query keeps the row in its loading state.
    mockGetRealizedPnLApi.mockReturnValue(new Promise(() => {}));
    const { container } = render(
      wrap(<HoldingRealizedRow portfolioId="p1" instrumentId="i1" />),
    );
    // §6.2: raw animate-pulse is BANNED for skeletons (this file was the
    // flagged offender in the R4 sweep).
    expect(container.querySelector(".animate-pulse")).toBeNull();
    // The shared primitive renders data-slot="skeleton" markers.
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThanOrEqual(2);
  });
});
