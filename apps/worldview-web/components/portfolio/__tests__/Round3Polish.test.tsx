/**
 * components/portfolio/__tests__/Round3Polish.test.tsx — Round-3 polish sprint.
 *
 * WHY THIS EXISTS: Round 3 migrated the portfolio surface's bespoke empty
 * states onto the shared components/primitives/EmptyState (DS §15.12),
 * replaced text-only loading lines with shape-matched skeletons, and made
 * the signedPrice convention (R1: "+" only for strictly-positive, zero
 * unsigned) uniform across every dollar P&L render. These tests pin those
 * contracts so future PRs can't silently revert them:
 *
 *   1. SemanticHoldingsTable  — no-holdings state renders via EmptyState
 *                               (role="status"), title keeps the pinned
 *                               "No holdings yet." string.
 *   2. TransactionsTable      — no-transactions state via EmptyState; the
 *                               R1 "+ Add your first transaction" CTA rides
 *                               the `action` slot and stays conditional.
 *   3. WatchlistTable         — named no-tickers state via EmptyState.
 *   4. WatchlistsTabPanel     — loading renders 22px-row skeletons, never
 *                               the old "Loading watchlists…" text line.
 *   5. WatchlistMemberRow     — CHG$ uses signedPrice: zero is unsigned.
 *
 * MOCKED MODULES: same set as portfolio-wave-f-polish.test.tsx (auth,
 * gateway, next/navigation) — the components under test gate on them.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

// ── Gateway mock — only the calls the panel fires while loading/empty. ──────
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getBatchQuotes: vi.fn().mockResolvedValue({ quotes: {} }),
    getWatchlistMembers: vi.fn().mockResolvedValue([]),
    getSectorBreakdown: vi.fn().mockResolvedValue({ segments: [], covered_pct: 1 }),
  })),
  GatewayError: class GatewayError extends Error {},
}));

// ── next/navigation mock — row clicks push routes. ──────────────────────────
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── SUT imports (after mocks) ───────────────────────────────────────────────
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { WatchlistTable } from "@/components/portfolio/watchlists/WatchlistTable";
import { WatchlistMemberRow } from "@/components/portfolio/watchlists/WatchlistMemberRow";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";
import { signedPrice } from "@/components/portfolio/PortfolioKPIStrip";
import type { Watchlist, WatchlistMember } from "@/types/api";

// ── Helpers ─────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const MEMBER: WatchlistMember = {
  entity_id: "e1",
  instrument_id: "i1",
  ticker: "AAPL",
  name: "Apple Inc.",
  resolution: "resolved",
} as unknown as WatchlistMember;

// ─────────────────────────────────────────────────────────────────────────────
// 1. SemanticHoldingsTable — EmptyState migration
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · SemanticHoldingsTable empty state", () => {
  it("renders the shared EmptyState (role=status) with the pinned copy", () => {
    render(
      wrap(
        <SemanticHoldingsTable holdings={[]} quotes={{}} sectors={{}} totalValue={0} />,
      ),
    );
    // role="status" is the EmptyState primitive's container — proves the
    // migration off the bespoke InlineEmptyState markup.
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("No holdings yet.");
    expect(status).toHaveTextContent(/Add Position/i);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. TransactionsTable — EmptyState migration + action slot
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · TransactionsTable empty state", () => {
  it("renders via the shared EmptyState and keeps the pinned copy", () => {
    render(<TransactionsTable transactions={[]} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("No transactions yet.");
    expect(status).toHaveTextContent(/Connect a brokerage to import activity/i);
  });

  it("CTA rides the action slot and invokes onAddFirst", () => {
    const onAddFirst = vi.fn();
    render(<TransactionsTable transactions={[]} onAddFirst={onAddFirst} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Add your first transaction" }),
    );
    expect(onAddFirst).toHaveBeenCalledOnce();
  });

  it("hides the CTA when onAddFirst is omitted (read-only ROOT context)", () => {
    render(<TransactionsTable transactions={[]} />);
    expect(
      screen.queryByRole("button", { name: "Add your first transaction" }),
    ).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. WatchlistTable — named no-tickers state
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · WatchlistTable empty state", () => {
  it("renders the named no-tickers EmptyState pointing at the search bar", () => {
    const watchlist = {
      watchlist_id: "w1",
      name: "Tech",
      members: [],
      member_count: 0,
    } as unknown as Watchlist;
    render(
      <WatchlistTable
        watchlist={watchlist}
        quotes={{}}
        onRowClick={vi.fn()}
        onDeleteMember={vi.fn()}
        deletingEntityId={null}
      />,
    );
    expect(screen.getByTestId("watchlist-empty-state")).toBeInTheDocument();
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("No tickers in this watchlist.");
    expect(status).toHaveTextContent(/Search above/i);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. WatchlistsTabPanel — shape-matched loading skeletons
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · WatchlistsTabPanel loading skeleton", () => {
  it("renders skeleton bars (not the old text loader) while loading", () => {
    render(wrap(<WatchlistsTabPanel watchlists={[]} quotes={{}} isLoading />));
    expect(screen.getByTestId("watchlists-skeleton")).toBeInTheDocument();
    // The pre-R3 text-only loader must be gone — skeletons communicate
    // progress without a layout jump when the chrome mounts.
    expect(screen.queryByText(/Loading watchlists/i)).not.toBeInTheDocument();
  });

  it("renders the named no-watchlists EmptyState with the create action", () => {
    render(
      wrap(<WatchlistsTabPanel watchlists={[]} quotes={{}} isLoading={false} />),
    );
    expect(screen.getByTestId("watchlists-empty-state")).toBeInTheDocument();
    expect(screen.getByText("No watchlists yet.")).toBeInTheDocument();
    // The CTA lives in the EmptyState action slot.
    expect(
      screen.getByRole("button", { name: /create watchlist/i }),
    ).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. signedPrice convention — uniform dollar P&L sign display
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · signedPrice convention on watchlist CHG$", () => {
  function renderRow(change: number) {
    render(
      <table>
        <tbody>
          <WatchlistMemberRow
            member={MEMBER}
            quote={{ price: 100, change, change_pct: 0 }}
            onRowClick={vi.fn()}
            onDelete={vi.fn()}
            isDeleting={false}
          />
        </tbody>
      </table>,
    );
  }

  it("zero day-change renders UNSIGNED ($0.00, never +$0.00)", () => {
    renderRow(0);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
    expect(screen.queryByText("+$0.00")).not.toBeInTheDocument();
  });

  it("positive day-change carries an explicit + prefix", () => {
    renderRow(1.5);
    expect(screen.getByText(signedPrice(1.5))).toBeInTheDocument();
    expect(signedPrice(1.5).startsWith("+")).toBe(true);
  });
});
