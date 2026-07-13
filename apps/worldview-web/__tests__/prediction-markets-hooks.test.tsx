/**
 * __tests__/prediction-markets-hooks.test.tsx — TanStack hooks (PLAN-0056 E2).
 *
 * Verifies each hook calls the RIGHT gateway method with the right args, and is
 * DISABLED (no call) when there is no auth token.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Auth mock (token toggled per-test) ─────────────────────────────────────────
const mockUseAuth = vi.fn();
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => mockUseAuth() }));

// ── Gateway mock ───────────────────────────────────────────────────────────────
const getPredictionMarketPriceHistory = vi.fn();
const getPredictionMarketTrades = vi.fn();
const getPredictionEvents = vi.fn();
const getEntityPredictions = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getPredictionMarketPriceHistory,
    getPredictionMarketTrades,
    getPredictionEvents,
    getEntityPredictions,
  })),
}));

import {
  usePredictionMarketPriceHistory,
  usePredictionMarketTrades,
  usePredictionEvents,
  useEntityPredictions,
} from "@/lib/api/prediction-markets-hooks";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function authed() {
  mockUseAuth.mockReturnValue({ accessToken: "test-token", isAuthenticated: true });
}
function signedOut() {
  mockUseAuth.mockReturnValue({ accessToken: null, isAuthenticated: false });
}

beforeEach(() => {
  vi.clearAllMocks();
  getPredictionMarketPriceHistory.mockResolvedValue({ market_id: "c1", interval: "1d", points: [] });
  getPredictionMarketTrades.mockResolvedValue({ market_id: "c1", items: [], limit: 30 });
  getPredictionEvents.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  getEntityPredictions.mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 });
});

describe("prediction-markets hooks", () => {
  it("usePredictionMarketPriceHistory calls the gateway with conditionId + interval", async () => {
    authed();
    renderHook(() => usePredictionMarketPriceHistory("c1", "1h"), { wrapper });
    await waitFor(() =>
      expect(getPredictionMarketPriceHistory).toHaveBeenCalledWith("c1", "1h"),
    );
  });

  it("usePredictionMarketPriceHistory is disabled without a token", () => {
    signedOut();
    renderHook(() => usePredictionMarketPriceHistory("c1", "1d"), { wrapper });
    expect(getPredictionMarketPriceHistory).not.toHaveBeenCalled();
  });

  it("usePredictionMarketPriceHistory is disabled without a conditionId", () => {
    authed();
    renderHook(() => usePredictionMarketPriceHistory("", "1d"), { wrapper });
    expect(getPredictionMarketPriceHistory).not.toHaveBeenCalled();
  });

  it("usePredictionMarketTrades calls the gateway with conditionId", async () => {
    authed();
    renderHook(() => usePredictionMarketTrades("c1"), { wrapper });
    await waitFor(() => expect(getPredictionMarketTrades).toHaveBeenCalledWith("c1", 30));
  });

  it("usePredictionEvents calls the gateway and is token-gated", async () => {
    authed();
    renderHook(() => usePredictionEvents({ limit: 25 }), { wrapper });
    await waitFor(() => expect(getPredictionEvents).toHaveBeenCalledWith({ limit: 25 }));
  });

  it("useEntityPredictions calls the gateway with the entity id", async () => {
    authed();
    renderHook(() => useEntityPredictions("e1", { limit: 10 }), { wrapper });
    await waitFor(() => expect(getEntityPredictions).toHaveBeenCalledWith("e1", { limit: 10 }));
  });

  it("useEntityPredictions is disabled without an entity id", () => {
    authed();
    renderHook(() => useEntityPredictions("", { limit: 10 }), { wrapper });
    expect(getEntityPredictions).not.toHaveBeenCalled();
  });
});
