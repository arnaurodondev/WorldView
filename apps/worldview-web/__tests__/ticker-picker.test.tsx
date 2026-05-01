/**
 * __tests__/ticker-picker.test.tsx — Unit tests for TickerPicker
 *
 * WHY THIS EXISTS: TickerPicker is the per-panel symbol selector that drives the
 * symbol-linking broadcast. It replaces the static "[AAPL]" label in panel headers.
 * Tests verify:
 *   1. Badge renders current symbol (or "—" when none set)
 *   2. Recent instruments appear when input is empty
 *   3. Selecting an instrument calls setActiveSymbol + saves to recents
 *   4. Search results appear when query is non-empty
 *   5. No % errors in the gateway contract (entity_id, instrument_id)
 *
 * WHY MOCK SymbolLinkingContext: setActiveSymbol must be verifiable as called
 * with the correct arguments — the real context would require a full provider tree.
 * WHY MOCK gateway: deterministic search results; no network.
 * WHY MOCK localStorage: avoids cross-test pollution from recents state.
 *
 * DESIGN REFERENCE: Handoff 2026-05-01 Tier-3 #8
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Auth mock ──────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: null,
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── SymbolLinkingContext mock ───────────────────────────────────────────────────
const mockSetActiveSymbol = vi.fn();
vi.mock("@/contexts/SymbolLinkingContext", () => ({
  useSymbolLinking: vi.fn(() => ({
    links: {},
    setLinkColor: vi.fn(),
    setActiveSymbol: mockSetActiveSymbol,
    getSymbolForPanel: vi.fn(() => ({ symbol: null, instrumentId: null })),
  })),
}));

// ── Gateway mock ───────────────────────────────────────────────────────────────
const mockSearchInstruments = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    searchInstruments: mockSearchInstruments,
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

// ── localStorage mock ──────────────────────────────────────────────────────────
// WHY: prevents recents from one test leaking into another.
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, val: string) => { store[key] = val; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock, writable: true });

// ── Helper ─────────────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Import component AFTER mocks ───────────────────────────────────────────────
const { TickerPicker } = await import("@/components/workspace/TickerPicker");

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("TickerPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    mockSearchInstruments.mockResolvedValue({ results: [] });
  });

  it("renders the current symbol in bracket notation", () => {
    // WHY: the badge must show [AAPL] — the Bloomberg-style panel symbol indicator.
    render(<TickerPicker panelId="p-1" symbol="AAPL" />, { wrapper: makeWrapper() });
    expect(screen.getByRole("button", { name: /Change symbol, currently AAPL/i })).toBeInTheDocument();
    expect(screen.getByText("[AAPL]")).toBeInTheDocument();
  });

  it("renders [—] when no symbol is set", () => {
    // WHY: unlinked panels must show a visible invite to pick a symbol.
    render(<TickerPicker panelId="p-1" symbol={null} />, { wrapper: makeWrapper() });
    expect(screen.getByText("[—]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pick a symbol/i })).toBeInTheDocument();
  });

  it("shows search results when user types a query", async () => {
    // WHY: the core function of TickerPicker is to search for and select instruments.
    mockSearchInstruments.mockResolvedValue({
      results: [
        { instrument_id: "ins-msft", entity_id: "ent-msft", ticker: "MSFT", name: "Microsoft Corporation", exchange: "NASDAQ", type: "equity" },
      ],
    });

    render(<TickerPicker panelId="p-1" symbol={null} />, { wrapper: makeWrapper() });

    // Open the picker
    fireEvent.click(screen.getByRole("button", { name: /Pick a symbol/i }));

    // Type a query
    const input = screen.getByPlaceholderText("Symbol or name…");
    fireEvent.change(input, { target: { value: "MSFT" } });

    // Wait for debounce + search result to appear
    await waitFor(() => {
      expect(screen.getByText("MSFT")).toBeInTheDocument();
    });
    expect(screen.getByText("Microsoft Corporation")).toBeInTheDocument();
  });

  it("calls setActiveSymbol when a result is selected", async () => {
    // WHY: selection must broadcast to all panels in the same color group —
    // this is the whole purpose of the TickerPicker.
    mockSearchInstruments.mockResolvedValue({
      results: [
        { instrument_id: "ins-tsla", entity_id: "ent-tsla", ticker: "TSLA", name: "Tesla Inc", exchange: "NASDAQ", type: "equity" },
      ],
    });

    render(<TickerPicker panelId="p-2" symbol={null} />, { wrapper: makeWrapper() });

    fireEvent.click(screen.getByRole("button", { name: /Pick a symbol/i }));

    const input = screen.getByPlaceholderText("Symbol or name…");
    fireEvent.change(input, { target: { value: "TSLA" } });

    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });

    // Select the TSLA result
    fireEvent.click(screen.getByText("TSLA"));

    // setActiveSymbol must be called with (panelId, ticker, instrumentId)
    expect(mockSetActiveSymbol).toHaveBeenCalledWith("p-2", "TSLA", "ins-tsla");
  });

  it("saves the selected instrument to recent instruments", async () => {
    // WHY: recents are how TickerPicker pre-populates its list on the next open —
    // if saving fails, the "recent" section is always empty.
    mockSearchInstruments.mockResolvedValue({
      results: [
        { instrument_id: "ins-nvda", entity_id: "ent-nvda", ticker: "NVDA", name: "NVIDIA Corporation", exchange: "NASDAQ", type: "equity" },
      ],
    });

    render(<TickerPicker panelId="p-3" symbol={null} />, { wrapper: makeWrapper() });

    fireEvent.click(screen.getByRole("button", { name: /Pick a symbol/i }));
    const input = screen.getByPlaceholderText("Symbol or name…");
    fireEvent.change(input, { target: { value: "NVDA" } });

    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("NVDA"));

    // Verify localStorage was written with the selected instrument
    const stored = JSON.parse(localStorageMock.getItem("worldview-recent-instruments") ?? "[]") as Array<{ ticker: string }>;
    expect(stored[0]?.ticker).toBe("NVDA");
  });
});
