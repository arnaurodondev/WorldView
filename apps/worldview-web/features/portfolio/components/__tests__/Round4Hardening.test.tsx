/**
 * features/portfolio/components/__tests__/Round4Hardening.test.tsx
 *
 * Round-4 hardening — analytics-surface contracts:
 *
 *   1. Benchmark-failure ISOLATION: when the SPY resolve/OHLCV chain dies,
 *      the TWR chart still renders the portfolio line (the primary chart is
 *      never blocked on benchmark availability) and a small inline
 *      "unavailable" notice appears next to the toggles — the failure is
 *      explained, never silent (R4 item 1e).
 *   2. The notice does NOT appear when the benchmark chain merely returns
 *      an empty bar set (no data ≠ failure) — the annotation must mean
 *      "won't appear", never "hasn't appeared yet".
 *   3. useBenchmarkSeries referential stability: closesByTicker keeps its
 *      identity across unrelated re-renders (the combine memoisation that
 *      the chart-row useMemo in AnalyticsTwrChart depends on — R4 item 3a).
 *
 * MOCKED: @/lib/api-client (same pattern as AnalyticsTab.test.tsx).
 * TanStack Query runs for real.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Gateway mocks ─────────────────────────────────────────────────────────────

const mockGetValueHistory = vi.fn();
const mockGetRiskMetrics = vi.fn();
const mockGetHoldings = vi.fn();
const mockResolveTickersBatch = vi.fn();
const mockGetOHLCV = vi.fn();
// 2026-06-10 sprint gap #3: AnalyticsTwrChart reads the flow-adjusted TWR
// endpoint via useTwrSeries (createGateway + useAuth pattern, not useApiClient).
const mockGetTwr = vi.fn();

vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({
    getValueHistory: mockGetValueHistory,
    getRiskMetrics: mockGetRiskMetrics,
    getHoldings: mockGetHoldings,
    resolveTickersBatch: mockResolveTickersBatch,
    getOHLCV: mockGetOHLCV,
  })),
}));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getTwr: mockGetTwr })),
  GatewayError: class GatewayError extends Error {},
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token" })),
}));

// ── SUT imports (after mocks) ────────────────────────────────────────────────
import { AnalyticsTab } from "../AnalyticsTab";
import { useBenchmarkSeries } from "@/features/portfolio/hooks/useBenchmarkSeries";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const HISTORY: ValueHistoryResponse = {
  points: [
    { date: "2026-06-01", value: 100_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-02", value: 101_000, cost_basis: 90_000, cash: 0 },
  ],
} as ValueHistoryResponse;

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

function wrap(children: ReactNode) {
  const Wrapper = makeWrapper();
  return <Wrapper>{children}</Wrapper>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetValueHistory.mockResolvedValue(HISTORY);
  // TWR fixture mirroring HISTORY (fractions; first point 0 per the
  // endpoint's window-rebase contract).
  mockGetTwr.mockResolvedValue({
    portfolio_id: "p-1",
    from_date: "2026-06-01",
    to_date: "2026-06-02",
    points: [
      { date: "2026-06-01", twr_cum: 0, nav: 100_000 },
      { date: "2026-06-02", twr_cum: 0.01, nav: 101_000 },
    ],
    flow_days: 0,
  });
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
    ticker: "SPY",
    timeframe: "1D",
    bars: [],
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 1+2. Benchmark failure isolation + honest notice semantics
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · benchmark failure isolation (AnalyticsTab)", () => {
  it("renders the portfolio chart AND the inline notice when the SPY chain fails", async () => {
    // Kill the entire benchmark chain at the resolve step.
    mockResolveTickersBatch.mockRejectedValue(new Error("resolve down"));

    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    // The PRIMARY chart must still draw — benchmark availability can never
    // block the portfolio line (the value-history query succeeded).
    await waitFor(() =>
      expect(screen.getByTestId("twr-chart")).toBeInTheDocument(),
    );

    // SPY is toggled on by default → its dead chain must be ANNOUNCED, not
    // silently absent (a never-appearing overlay reads as a broken toggle).
    const notice = await screen.findByTestId("benchmark-unavailable-notice");
    expect(notice).toHaveTextContent("SPY data unavailable");
  });

  it("shows NO notice when the benchmark merely has no bars (no data ≠ failure)", async () => {
    // Resolve OK, OHLCV succeeds with an empty bar set (default mocks).
    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    await waitFor(() =>
      expect(screen.getByTestId("twr-chart")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("benchmark-unavailable-notice"),
    ).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. useBenchmarkSeries — output identity stability (memo contract)
// ─────────────────────────────────────────────────────────────────────────────
describe("Round 4 · useBenchmarkSeries referential stability", () => {
  it("closesByTicker keeps its identity across unrelated re-renders", async () => {
    mockGetOHLCV.mockResolvedValue({
      instrument_id: "iid-spy",
      ticker: "SPY",
      timeframe: "1D",
      bars: [
        { timestamp: "2026-06-01", open: 1, high: 1, low: 1, close: 500, volume: 1 },
        { timestamp: "2026-06-02", open: 1, high: 1, low: 1, close: 505, volume: 1 },
      ],
    });

    const { result, rerender } = renderHook(
      () =>
        // WHY a fresh array literal per call: this is exactly what the real
        // caller (AnalyticsTab) does on every render — the hook must absorb
        // it (tickersKey memo) rather than treat it as a new ticker set.
        useBenchmarkSeries({ tickers: ["SPY"], enabled: true }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() =>
      expect(result.current.closesByTicker["SPY"]).toBeDefined(),
    );
    const first = result.current.closesByTicker;

    // Re-render with no data change — the combined object must be the SAME
    // reference, otherwise AnalyticsTwrChart's rows useMemo (keyed on it)
    // recomputes on every parent render, silently defeating the memo.
    rerender();
    expect(result.current.closesByTicker).toBe(first);
    expect(result.current.failedTickers).toEqual([]);
  });

  it("flags a ticker as failed when its OHLCV fetch errors", async () => {
    mockGetOHLCV.mockRejectedValue(new Error("ohlcv down"));

    const { result } = renderHook(
      () => useBenchmarkSeries({ tickers: ["SPY"], enabled: true }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() =>
      expect(result.current.failedTickers).toContain("SPY"),
    );
    // Failed ≠ fabricated: no closes entry may exist for a dead chain.
    expect(result.current.closesByTicker["SPY"]).toBeUndefined();
  });

  it("flags a ticker as failed when the resolve returns no instrument for it", async () => {
    // Resolve succeeds but knows nothing about SPY → the OHLCV query is
    // permanently disabled; without the failed flag, consumers would wait
    // on a load that never ends.
    mockResolveTickersBatch.mockResolvedValue({});

    const { result } = renderHook(
      () => useBenchmarkSeries({ tickers: ["SPY"], enabled: true }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() =>
      expect(result.current.failedTickers).toContain("SPY"),
    );
  });
});
