/**
 * __tests__/usePortfolioMetrics.test.tsx — composite hook contract tests.
 *
 * WHY: PLAN-0050 T-A-1-02 hoisted the rail computation out of the layout.
 * If a future refactor breaks the math (NAV / Day P&L / Total P&L), the
 * TopBar would silently show wrong numbers and the user would only catch
 * it during a trading session. These tests pin the formulas.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Mock the gateway BEFORE the hook is imported so the dynamic gateway
// returned by createGateway() exposes our stubs.
const mockGetPortfolios = vi.fn();
const mockGetHoldings = vi.fn();
const mockGetBatchQuotes = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: () => ({
    getPortfolios: mockGetPortfolios,
    getHoldings: mockGetHoldings,
    getBatchQuotes: mockGetBatchQuotes,
  }),
}));

// useAuth would otherwise require AuthContext provider — stub it.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ accessToken: "test-token", isAuthenticated: true }),
}));

import { usePortfolioMetrics } from "@/hooks/usePortfolioMetrics";

function makeWrapper() {
  // retry:false so test failures fail fast instead of looping the queryFn.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  mockGetPortfolios.mockReset();
  mockGetHoldings.mockReset();
  mockGetBatchQuotes.mockReset();
});

describe("usePortfolioMetrics", () => {
  it("returns null values until queries resolve", () => {
    mockGetPortfolios.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => usePortfolioMetrics(), { wrapper: makeWrapper() });
    expect(result.current.portfolioValue).toBeNull();
    expect(result.current.dailyPnl).toBeNull();
    expect(result.current.unrealisedPnl).toBeNull();
  });

  it("computes portfolio value from qty × live price", async () => {
    mockGetPortfolios.mockResolvedValue([{ portfolio_id: "p1" }]);
    mockGetHoldings.mockResolvedValue({
      holdings: [
        { instrument_id: "i1", quantity: 10, average_cost: 100 },
        { instrument_id: "i2", quantity: 5, average_cost: 200 },
      ],
    });
    mockGetBatchQuotes.mockResolvedValue({
      quotes: { i1: { price: 110, change: 1 }, i2: { price: 220, change: -2 } },
    });

    const { result } = renderHook(() => usePortfolioMetrics(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.portfolioValue).not.toBeNull());

    // 10×110 + 5×220 = 1100 + 1100 = 2200
    expect(result.current.portfolioValue).toBe(2200);
    // 10×1 + 5×-2 = 10 − 10 = 0
    expect(result.current.dailyPnl).toBe(0);
    // unrealised = 2200 − (10×100 + 5×200) = 2200 − 2000 = 200
    expect(result.current.unrealisedPnl).toBe(200);
  });

  it("falls back to average_cost when a quote is missing (avoids flicker)", async () => {
    mockGetPortfolios.mockResolvedValue([{ portfolio_id: "p1" }]);
    mockGetHoldings.mockResolvedValue({
      holdings: [{ instrument_id: "i1", quantity: 10, average_cost: 100 }],
    });
    mockGetBatchQuotes.mockResolvedValue({ quotes: {} }); // empty — quote not yet loaded

    const { result } = renderHook(() => usePortfolioMetrics(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.portfolioValue).not.toBeNull());

    // No quote ⇒ price defaults to average_cost (100). 10×100 = 1000.
    expect(result.current.portfolioValue).toBe(1000);
    // No change field ⇒ daily contribution is 0.
    expect(result.current.dailyPnl).toBe(0);
    // unrealised = 1000 − 1000 = 0 (cost basis matches the fallback price).
    expect(result.current.unrealisedPnl).toBe(0);
  });

  it("returns null portfolio fields for empty holdings", async () => {
    mockGetPortfolios.mockResolvedValue([{ portfolio_id: "p1" }]);
    mockGetHoldings.mockResolvedValue({ holdings: [] });

    const { result } = renderHook(() => usePortfolioMetrics(), { wrapper: makeWrapper() });
    // No holdings ever resolves to non-null. Wait briefly to confirm.
    await waitFor(() => expect(mockGetHoldings).toHaveBeenCalled());
    expect(result.current.portfolioValue).toBeNull();
    expect(result.current.dailyPnl).toBeNull();
    expect(result.current.unrealisedPnl).toBeNull();
  });
});
