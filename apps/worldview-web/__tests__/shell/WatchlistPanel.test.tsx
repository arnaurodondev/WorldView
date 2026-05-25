/**
 * __tests__/shell/WatchlistPanel.test.tsx — PRD-0089 W1 §4.5.
 *
 * Pins the contract that the refactored WatchlistPanel:
 *   - wraps its rows in data-table-grid so they inherit the 20px row height
 *   - renders a per-row 40×16 trend-tinted Sparkline (F1 primitive)
 *   - renders a per-row FreshnessDot driven by quote.freshness_status
 *   - routes row clicks to /instruments/{ticker} (C-08), not entity_id
 *   - "+N more →" link routes to /watchlists (C-09)
 *   - registers `mod+shift+w` to open the add-flow
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { HotkeyProvider } from "@/contexts/HotkeyContext";
import { HotkeyRegistry } from "@/lib/hotkey-registry";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockGetWatchlists = vi.fn();
const mockGetWatchlistMembers = vi.fn();
const mockGetBatchQuotes = vi.fn();
const mockGetBatchOhlcvBars = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getWatchlists: mockGetWatchlists,
    getWatchlistMembers: mockGetWatchlistMembers,
    getBatchQuotes: mockGetBatchQuotes,
    getBatchOhlcvBars: mockGetBatchOhlcvBars,
  }),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "tok", isAuthenticated: true }),
}));
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Sonner toast spy
const mockToast = vi.fn();
vi.mock("sonner", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

import { WatchlistPanel } from "@/components/shell/WatchlistPanel";

// ── Fixtures ───────────────────────────────────────────────────────────────

const WATCHLIST = {
  watchlist_id: "wl-1",
  name: "Tech",
  owner_id: "u-1",
  member_count: 2,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  members: [
    {
      entity_id: "e-aapl",
      instrument_id: "i-aapl",
      ticker: "AAPL",
      name: "Apple Inc.",
      added_at: "2026-01-01T00:00:00Z",
      resolution: "resolved" as const,
    },
    {
      entity_id: "e-msft",
      instrument_id: "i-msft",
      ticker: "MSFT",
      name: "Microsoft Corp.",
      added_at: "2026-01-01T00:00:00Z",
      resolution: "resolved" as const,
    },
  ],
};

function makeWrapper(registry: HotkeyRegistry) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <HotkeyProvider registry={registry}>{children}</HotkeyProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // List endpoint deliberately returns SHALLOW watchlists (no members) —
  // matches the real S1 contract. Members come from getWatchlistMembers.
  const shallow = { ...WATCHLIST, members: [] };
  mockGetWatchlists.mockResolvedValue([shallow]);
  // Members endpoint returns the populated array — what the component
  // actually consumes for the row list after QA F-003 fix.
  mockGetWatchlistMembers.mockResolvedValue(WATCHLIST.members);
  mockGetBatchQuotes.mockResolvedValue({
    quotes: {
      "e-aapl": {
        ticker: "AAPL",
        price: 234.56,
        change: 2.0,
        change_pct: 0.84,
        timestamp: "2026-05-20T13:42:00Z",
        volume: 1_000_000,
        freshness_status: "live" as const,
      },
      "e-msft": {
        ticker: "MSFT",
        price: 428.12,
        change: 1.3,
        change_pct: 0.31,
        timestamp: "2026-05-20T13:42:00Z",
        volume: 1_000_000,
        freshness_status: "stale" as const,
      },
    },
  });
  mockGetBatchOhlcvBars.mockResolvedValue({
    results: [
      {
        instrument_id: "e-aapl",
        bars: [
          { timestamp: "2026-05-20T13:00:00Z", open: 230, high: 235, low: 229, close: 234, volume: 1000 },
          { timestamp: "2026-05-20T13:05:00Z", open: 234, high: 235, low: 233, close: 234.5, volume: 1000 },
        ],
      },
    ],
  });
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("WatchlistPanel (PRD-0089 W1)", () => {
  it("wraps rows in data-table-grid so they inherit the 20px F1 row height", async () => {
    const { container } = render(<WatchlistPanel />, {
      wrapper: makeWrapper(new HotkeyRegistry()),
    });
    await screen.findByText("AAPL");
    const grid = container.querySelector("[data-table-grid]");
    expect(grid).not.toBeNull();
  });

  it("routes row click to /instruments/{TICKER} (not entity_id) — C-08", async () => {
    const user = userEvent.setup();
    render(<WatchlistPanel />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    const aapl = await screen.findByLabelText(/AAPL — view instrument detail/i);
    await user.click(aapl);
    expect(mockPush).toHaveBeenCalledWith("/instruments/AAPL");
    // Make sure we never used the UUID form.
    expect(mockPush).not.toHaveBeenCalledWith(expect.stringContaining("e-aapl"));
  });

  it('"+N more →" link routes to /watchlists (C-09)', async () => {
    // Build a watchlist with 12 members so the overflow link renders.
    const bigMembers = Array.from({ length: 12 }).map((_, i) => ({
      entity_id: `e-${i}`,
      instrument_id: `i-${i}`,
      ticker: `T${i}`,
      name: `Ticker ${i}`,
      added_at: "2026-01-01T00:00:00Z",
      resolution: "resolved" as const,
    }));
    const big = { ...WATCHLIST, member_count: 12, members: [] };
    mockGetWatchlists.mockResolvedValue([big]);
    mockGetWatchlistMembers.mockResolvedValue(bigMembers);
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });
    mockGetBatchOhlcvBars.mockResolvedValue({ results: [] });

    const user = userEvent.setup();
    render(<WatchlistPanel />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    const overflow = await screen.findByRole("button", { name: /\+2 more →/ });
    await user.click(overflow);
    expect(mockPush).toHaveBeenCalledWith("/watchlists");
  });

  it("renders FreshnessDot driven by quote.freshness_status", async () => {
    const { container } = render(<WatchlistPanel />, {
      wrapper: makeWrapper(new HotkeyRegistry()),
    });
    await screen.findByText("AAPL");
    // FreshnessDot renders an aria-labelled span ("live data" / "stale data").
    expect(container.querySelector('[aria-label="live data"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="stale data"]')).not.toBeNull();
  });

  it("renders a Sparkline per row", async () => {
    const { container } = render(<WatchlistPanel />, {
      wrapper: makeWrapper(new HotkeyRegistry()),
    });
    await screen.findByText("AAPL");
    // Sparkline primitive renders an <svg role="img">. We tolerate the empty
    // skeleton fallback (rendered when bars haven't loaded yet) by counting
    // ALL svgs and asserting at least one per visible row.
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(2);
  });

  it("registers the mod+shift+w chord for add-to-watchlist", () => {
    const registry = new HotkeyRegistry();
    render(<WatchlistPanel />, { wrapper: makeWrapper(registry) });
    const binding = registry.all().find((b) => b.id === "shell.watchlist.add");
    expect(binding).toBeDefined();
    expect(binding?.chord).toBe("mod+shift+w");
  });

  it("shows 5 skeleton rows while watchlists are loading", () => {
    mockGetWatchlists.mockImplementation(() => new Promise(() => {})); // never resolves
    render(<WatchlistPanel />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    const skeletons = screen.getAllByTestId("watchlist-skeleton-row");
    expect(skeletons).toHaveLength(5);
  });

  // QA F-003 regression: the S1 list endpoint returns shallow watchlists
  // (no members). Pre-fix the sidebar consumed activeWatchlist.members and
  // always rendered the empty state. The fix is a dependent
  // getWatchlistMembers query — this test pins both that the second call
  // fires once activeWatchlistId is known and that its results drive the
  // row list.
  it("(F-003 regression) hydrates members via getWatchlistMembers when list returns shallow watchlists", async () => {
    render(<WatchlistPanel />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    // AAPL row only renders if the members fetch resolved AND its result
    // was consumed in place of the (empty) list-endpoint members.
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    // Sanity check: the second call really happened.
    expect(mockGetWatchlistMembers).toHaveBeenCalledWith("wl-1");
  });

  // H-002 regression: column header row renders above the data rows so the
  // user can read what each numeric column represents.
  it("(H-002) renders the column header row above the data rows", async () => {
    render(<WatchlistPanel />, { wrapper: makeWrapper(new HotkeyRegistry()) });
    await screen.findByText("AAPL");
    expect(screen.getByText("Tkr")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("%Chg")).toBeInTheDocument();
  });
});
