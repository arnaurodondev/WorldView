/**
 * features/portfolio/components/__tests__/AnalyticsTab.test.tsx (R2 sprint)
 *
 * WHY: integration-level wiring tests for the analytics surface —
 *   1. Period pills drive the backend lookback (YTD default → 1W → ALL).
 *   2. Benchmark toggles: SPY on by default; toggling QQQ lazily resolves
 *      and fetches its series (no QQQ traffic until requested).
 *   3. Client risk panel renders honest em-dashes + tooltips when the
 *      series is below the 20-observation gate (this is the user's money —
 *      a fabricated Sharpe would be worse than no Sharpe).
 *
 * MOCKED: @/lib/api-client (gateway). TanStack Query runs for real.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Gateway mocks ─────────────────────────────────────────────────────────────

const mockGetValueHistory = vi.fn();
const mockGetRiskMetrics = vi.fn();
const mockGetHoldings = vi.fn();
const mockResolveTickersBatch = vi.fn();
const mockGetOHLCV = vi.fn();

const gatewayStub = {
  getValueHistory: mockGetValueHistory,
  getRiskMetrics: mockGetRiskMetrics,
  getHoldings: mockGetHoldings,
  resolveTickersBatch: mockResolveTickersBatch,
  getOHLCV: mockGetOHLCV,
};

vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => gatewayStub),
}));

// ── SUT import (after mocks) ─────────────────────────────────────────────────
import { AnalyticsTab } from "../AnalyticsTab";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** 2 points — enough for the charts, BELOW the 20-obs risk-metric gate. */
const SHORT_HISTORY: ValueHistoryResponse = {
  points: [
    { date: "2026-06-01", value: 100_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-02", value: 101_000, cost_basis: 90_000, cash: 0 },
  ],
};

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("AnalyticsTab (R2 wiring)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetValueHistory.mockResolvedValue(SHORT_HISTORY);
    mockGetRiskMetrics.mockResolvedValue({
      portfolio_id: "p-1",
      lookback_days: 365,
      drawdown_max: null,
      drawdown_current: null,
      volatility_annualized: null,
      sharpe: null,
      sortino: null,
      beta_vs_spy: null,
      n_returns: 1,
    });
    mockGetHoldings.mockResolvedValue({ portfolio_id: "p-1", holdings: [] });
    mockResolveTickersBatch.mockResolvedValue({ SPY: "iid-spy", QQQ: "iid-qqq" });
    mockGetOHLCV.mockResolvedValue({
      instrument_id: "iid-spy",
      ticker: "",
      timeframe: "1D",
      bars: [],
    });
  });

  it("defaults to YTD: backend risk metrics fetched with a 365-day lookback", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));
    await waitFor(() => {
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 365);
    });
  });

  it("clicking 1W re-fetches risk metrics with the clamped 10-day lookback; ALL → 1825", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));
    await waitFor(() => expect(mockGetRiskMetrics).toHaveBeenCalled());

    // Period pills are role=tab (AnalyticsPeriodSelector a11y contract).
    // 1W maps to 7 days for value-history, but the BACKEND risk endpoint
    // validates lookback_days ≥ 10 (verified live: 7 → 422). The clamp in
    // riskLookbackDays keeps the request valid.
    fireEvent.click(screen.getByRole("tab", { name: "1W" }));
    await waitFor(() => {
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 10);
    });

    fireEvent.click(screen.getByRole("tab", { name: "ALL" }));
    await waitFor(() => {
      // "ALL" maps to the widest concrete lookback the endpoint accepts.
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 1825);
    });
  });

  it("SPY overlay is on by default; QQQ is lazy until toggled", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    // SPY resolves at mount (overlay on + beta needs it)…
    await waitFor(() => {
      expect(mockResolveTickersBatch).toHaveBeenCalledWith(["SPY"]);
    });
    // …and QQQ generated zero traffic.
    expect(mockResolveTickersBatch).not.toHaveBeenCalledWith(
      expect.arrayContaining(["QQQ"]),
    );

    // Toggle states are exposed via aria-pressed.
    expect(screen.getByRole("button", { name: "SPY" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const qqqBtn = screen.getByRole("button", { name: "QQQ" });
    expect(qqqBtn).toHaveAttribute("aria-pressed", "false");

    // Toggling QQQ on triggers the batched resolve for both tickers
    // (sorted key — see useBenchmarkSeries).
    fireEvent.click(qqqBtn);
    await waitFor(() => {
      expect(mockResolveTickersBatch).toHaveBeenCalledWith(["QQQ", "SPY"]);
    });
    expect(qqqBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("client risk panel shows em-dashes + insufficient-data tooltips below 20 observations", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    await waitFor(() => {
      expect(screen.getByTestId("client-risk-panel")).toBeInTheDocument();
    });

    // 2 points ⇒ 1 daily return ⇒ every metric is an honest "—".
    for (const id of [
      "client-risk-sharpe",
      "client-risk-max-dd",
      "client-risk-vol-ann",
      "client-risk-beta-spy",
    ]) {
      const tile = await screen.findByTestId(id);
      expect(tile).toHaveTextContent("—");
      // The tooltip names the reason (insufficient data / benchmark gap) —
      // never a bare dash the user has to guess about.
      expect(tile.getAttribute("title")).toMatch(/insufficient data|unavailable/i);
    }

    // Observation count footer quantifies the gate.
    await waitFor(() => {
      expect(screen.getByText(/n=1 daily returns/)).toBeInTheDocument();
    });
  });
});
