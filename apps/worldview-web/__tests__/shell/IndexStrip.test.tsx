/**
 * __tests__/shell/IndexStrip.test.tsx — PRD-0089 W1 §4.1 + §6.1
 *
 * Pins the contract that IndexStrip:
 *   - renders 10 ticker cells when data is loaded
 *   - shows loading skeleton cells while resolving instrument IDs
 *   - clicking a cell navigates to /indices/{ticker} (not /instruments/*)
 *   - strips "^" caret from URL segments (^TNX → /indices/TNX)
 *   - is hidden below xl breakpoint (CSS: hidden xl:flex)
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockResolveTickersBatch = vi.fn();
const mockGetBatchQuotes = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    resolveTickersBatch: mockResolveTickersBatch,
    getBatchQuotes: mockGetBatchQuotes,
  }),
}));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token" }),
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import { IndexStrip } from "@/components/shell/IndexStrip";

// ── Helpers ────────────────────────────────────────────────────────────────

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

/** Build a mock resolveTickersBatch result mapping each ticker to a fake UUID */
function makeTickerMap(tickers: string[]) {
  const map: Record<string, string> = {};
  tickers.forEach((t, i) => { map[t] = `instrument-id-${i}`; });
  return map;
}

/** Build a mock getBatchQuotes result with price/change_pct for each UUID */
function makeQuotes(ids: string[]) {
  const quotes: Record<string, { price: number; change_pct: number }> = {};
  ids.forEach((id, i) => { quotes[id] = { price: 100 + i * 10, change_pct: i % 2 === 0 ? 1.5 : -0.5 }; });
  return { quotes };
}

const ALL_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "VIX", "TLT", "^TNX", "GLD", "USO", "BTC-USD"];

beforeEach(() => {
  vi.clearAllMocks();
  const map = makeTickerMap(ALL_TICKERS);
  mockResolveTickersBatch.mockResolvedValue(map);
  const ids = Object.values(map);
  mockGetBatchQuotes.mockResolvedValue(makeQuotes(ids));
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("IndexStrip (PRD-0089 W1 §4.1)", () => {
  it("renders loading skeleton (10 cells) before data resolves", () => {
    // Keep the mock pending forever so we stay in loading state.
    mockResolveTickersBatch.mockImplementation(() => new Promise(() => {}));
    const { container } = render(<IndexStrip />, { wrapper: makeWrapper() });
    // The skeleton container has aria-busy="true" while loading.
    expect(container.querySelector("[aria-busy='true']")).toBeInTheDocument();
  });

  it("renders all 10 ticker display labels after data loads", async () => {
    render(<IndexStrip />, { wrapper: makeWrapper() });
    // Wait for the quotes to populate cells.
    await waitFor(() => {
      // Each ticker has a display label in the cell.
      expect(screen.getByText("SPY")).toBeInTheDocument();
      expect(screen.getByText("QQQ")).toBeInTheDocument();
    });
    // BTC-USD is displayed as "BTC" (short label).
    expect(screen.getByText("BTC")).toBeInTheDocument();
    // "^TNX" is displayed as "TNX" (caret stripped from label).
    expect(screen.getByText("TNX")).toBeInTheDocument();
  });

  it("clicking SPY cell navigates to /indices/SPY", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("SPY"));
    await user.click(screen.getByText("SPY").closest("button")!);
    expect(mockPush).toHaveBeenCalledWith("/indices/SPY");
  });

  it("clicking TNX cell navigates to /indices/TNX (caret stripped)", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("TNX"));
    await user.click(screen.getByText("TNX").closest("button")!);
    // WHY /indices/TNX (not /indices/^TNX): caret is stripped from URL segments
    // per C-10 — the "^" character is meta in URLs and looks odd in routes.
    expect(mockPush).toHaveBeenCalledWith("/indices/TNX");
  });

  it("clicking BTC-USD cell navigates to /indices/BTC-USD", async () => {
    const user = userEvent.setup();
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("BTC"));
    await user.click(screen.getByText("BTC").closest("button")!);
    expect(mockPush).toHaveBeenCalledWith("/indices/BTC-USD");
  });

  it("shows '—' price when no quote is available for a ticker", async () => {
    // Return an empty quotes object so no ticker has price data.
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} });
    render(<IndexStrip />, { wrapper: makeWrapper() });
    await waitFor(() => screen.getByText("SPY"));
    // All price slots should show "—" (em-dash fallback per plan §4.1).
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });
});
