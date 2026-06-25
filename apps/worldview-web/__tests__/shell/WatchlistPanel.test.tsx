/**
 * __tests__/shell/WatchlistPanel.test.tsx — PRD-0089 W1 §4.5 + §6.1
 *
 * Pins the contract that WatchlistPanel:
 *   - clicking a row navigates to /instruments/{ticker} (NOT entity_id) — C-08
 *   - "+N more →" link points to /watchlists (NOT /portfolio?tab=watchlists) — C-09
 *   - rows are wrapped in a data-table-grid container (C-01, 20px row-height token)
 *   - Sparkline column is rendered per row (40×16 SVG)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

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
  useAuth: () => ({ accessToken: "test-token" }),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { WatchlistPanel } from "@/components/shell/WatchlistPanel";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

const WATCHLIST = {
  watchlist_id: "wl-001",
  name: "Tech Stocks",
  owner_id: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  members: [],
};

// WHY members include both ticker and entity_id: the click target must use
// ticker (/instruments/AAPL) NOT entity_id (/instruments/uuid). C-08 lock.
const MEMBERS = [
  { entity_id: "entity-uuid-aapl", instrument_id: "inst-uuid-aapl", ticker: "AAPL", name: "Apple Inc." },
  { entity_id: "entity-uuid-msft", instrument_id: "inst-uuid-msft", ticker: "MSFT", name: "Microsoft Corp." },
];

// Build a batch quotes response for the instrument IDs.
const QUOTES = {
  quotes: {
    "inst-uuid-aapl": { price: 193.42, change_pct: 1.25, freshness_status: "fresh" },
    "inst-uuid-msft": { price: 412.75, change_pct: -0.35, freshness_status: "fresh" },
  },
};

// Sparkline bars — a short series is enough for the Sparkline primitive.
const OHLCV_RESULTS = {
  results: [
    { instrument_id: "inst-uuid-aapl", bars: Array.from({ length: 10 }, (_, i) => ({ timestamp: `2026-01-0${i + 1}`, open: 190, high: 195, low: 188, close: 190 + i, volume: 1_000_000 })) },
    { instrument_id: "inst-uuid-msft", bars: Array.from({ length: 10 }, (_, i) => ({ timestamp: `2026-01-0${i + 1}`, open: 410, high: 415, low: 408, close: 410 + i, volume: 500_000 })) },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGetWatchlists.mockResolvedValue([WATCHLIST]);
  mockGetWatchlistMembers.mockResolvedValue(MEMBERS);
  mockGetBatchQuotes.mockResolvedValue(QUOTES);
  mockGetBatchOhlcvBars.mockResolvedValue(OHLCV_RESULTS);
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("WatchlistPanel (PRD-0089 W1 §4.5)", () => {
  it("clicking a row navigates to /instruments/{ticker} (NOT entity_id) — C-08", async () => {
    const user = userEvent.setup();
    render(<WatchlistPanel />, { wrapper: makeWrapper() });
    // Wait for AAPL row to appear.
    const aaplRow = await screen.findByLabelText(/AAPL.*view instrument detail/i);
    await user.click(aaplRow);
    // Must route to /instruments/AAPL, NOT /instruments/entity-uuid-aapl.
    expect(mockPush).toHaveBeenCalledWith("/instruments/AAPL");
    expect(mockPush).not.toHaveBeenCalledWith(expect.stringContaining("entity-uuid"));
  });

  it("wraps rows in a data-table-grid container for 20px row-height token (C-01)", async () => {
    const { container } = render(<WatchlistPanel />, { wrapper: makeWrapper() });
    // data-table-grid attribute triggers --row-h: 20px from globals.css.
    await waitFor(() => {
      expect(container.querySelector("[data-table-grid]")).toBeInTheDocument();
    });
  });

  it("renders a Sparkline SVG per row", async () => {
    const { container } = render(<WatchlistPanel />, { wrapper: makeWrapper() });
    await screen.findByLabelText(/AAPL.*view instrument detail/i);
    // Each row should contain an SVG (the Sparkline primitive renders an <svg>).
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(2);
  });

  it("shows prices from batch quotes", async () => {
    render(<WatchlistPanel />, { wrapper: makeWrapper() });
    // AAPL price 193.42 should appear.
    await screen.findByText("193.42");
  });
});

describe("WatchlistPanel +N more link (C-09)", () => {
  it("'+N more →' link navigates to /watchlists when MAX_ROWS is exceeded", async () => {
    // Generate 11 members (1 over the 10-row MAX_ROWS limit).
    const manyMembers = Array.from({ length: 11 }, (_, i) => ({
      entity_id: `entity-${i}`,
      instrument_id: `inst-${i}`,
      ticker: `TKR${i}`,
      name: `Ticker ${i}`,
    }));
    mockGetWatchlistMembers.mockResolvedValue(manyMembers);
    // Provide enough quotes for the expanded member list.
    const manyQuotes: Record<string, { price: number; change_pct: number; freshness_status: string }> = {};
    manyMembers.forEach((m) => { manyQuotes[m.instrument_id] = { price: 100, change_pct: 0.5, freshness_status: "fresh" }; });
    mockGetBatchQuotes.mockResolvedValue({ quotes: manyQuotes });
    mockGetBatchOhlcvBars.mockResolvedValue({ results: [] });

    const user = userEvent.setup();
    render(<WatchlistPanel />, { wrapper: makeWrapper() });
    // Wait for the "+1 more →" button to appear.
    const moreBtn = await screen.findByText(/\+1 more →/i);
    await user.click(moreBtn);
    // Must navigate to /watchlists (NOT /portfolio?tab=watchlists).
    expect(mockPush).toHaveBeenCalledWith("/watchlists");
  });
});
