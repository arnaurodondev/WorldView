/**
 * features/portfolio/components/__tests__/AnalyticsPlaceholderData.test.tsx
 * — Round-3 polish: period switches keep stale data visible (no unmount flash).
 *
 * WHY THIS EXISTS: the analytics queries are PERIOD-SCOPED
 * (qk.portfolios.valueHistory(id, period)), so before Round 3 every
 * period-pill click unmounted the populated chart back to a skeleton for
 * the duration of the refetch — a visible flash for what is usually a
 * sub-second request. Round 3 added `placeholderData: (prev) => prev`
 * (TanStack v5 keepPreviousData pattern) to the TWR chart, drawdown chart,
 * risk panel and risk sidebar; the components dim (opacity-60 +
 * data-stale) while the placeholder is showing.
 *
 * These tests pin the contract on AnalyticsTwrChart (the representative
 * consumer) and AnalyticsRiskMetricsPanel:
 *   1. First load → skeleton (no data to keep).
 *   2. Period change → chart STAYS MOUNTED with the previous series,
 *      flagged data-stale; the skeleton must NOT reappear.
 *   3. New data lands → data-stale clears.
 *
 * MOCKED: @/lib/api-client (deferred promises so the in-flight state is
 * controllable). TanStack Query runs for real — that's the layer under test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Gateway mock ─────────────────────────────────────────────────────────────
const mockGetValueHistory = vi.fn();
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({ getValueHistory: mockGetValueHistory })),
}));

// ── SUT imports (after mocks) ────────────────────────────────────────────────
import { AnalyticsTwrChart } from "../AnalyticsTwrChart";
import { AnalyticsRiskMetricsPanel } from "../AnalyticsRiskMetricsPanel";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const HISTORY_1M: ValueHistoryResponse = {
  points: [
    { date: "2026-06-01", value: 100_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-02", value: 101_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-03", value: 102_000, cost_basis: 90_000, cash: 0 },
  ],
} as ValueHistoryResponse;

const HISTORY_3M: ValueHistoryResponse = {
  points: [
    { date: "2026-03-01", value: 95_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-03", value: 102_000, cost_basis: 90_000, cash: 0 },
  ],
} as ValueHistoryResponse;

/** Deferred promise so the test controls exactly when a fetch resolves. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function makeWrapper() {
  // One QueryClient per test — placeholderData reads the PREVIOUS observer
  // result, so cache isolation between tests matters.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const NO_BENCHMARKS = { SPY: false, QQQ: false };

function twrProps(period: string, periodDays: number) {
  return {
    portfolioId: "p1",
    period,
    periodDays,
    benchmarks: NO_BENCHMARKS,
    benchmarkCloses: {},
  };
}

beforeEach(() => {
  mockGetValueHistory.mockReset();
});

// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · AnalyticsTwrChart placeholderData", () => {
  it("first load shows the skeleton (nothing to keep yet)", () => {
    mockGetValueHistory.mockReturnValue(new Promise(() => {})); // never resolves
    render(<AnalyticsTwrChart {...twrProps("1M", 30)} />, {
      wrapper: makeWrapper(),
    });
    expect(screen.getByTestId("twr-chart-skeleton")).toBeInTheDocument();
  });

  it("period change keeps the previous chart mounted (data-stale), no skeleton flash", async () => {
    const Wrapper = makeWrapper();

    // Resolve the 1M fetch immediately.
    mockGetValueHistory.mockResolvedValueOnce(HISTORY_1M);
    const { rerender } = render(<AnalyticsTwrChart {...twrProps("1M", 30)} />, {
      wrapper: Wrapper,
    });
    await waitFor(() =>
      expect(screen.getByTestId("twr-chart")).toBeInTheDocument(),
    );
    // Settled data is NOT flagged stale.
    expect(screen.getByTestId("twr-chart")).not.toHaveAttribute("data-stale");

    // Switch to 3M — leave the fetch IN FLIGHT so we can observe the
    // placeholder window.
    const pending = deferred<ValueHistoryResponse>();
    mockGetValueHistory.mockReturnValueOnce(pending.promise);
    rerender(<AnalyticsTwrChart {...twrProps("3M", 90)} />);

    // THE contract: the chart stays mounted with the 1M series (dimmed via
    // data-stale), and the skeleton must NOT reappear mid-session.
    await waitFor(() =>
      expect(screen.getByTestId("twr-chart")).toHaveAttribute(
        "data-stale",
        "true",
      ),
    );
    expect(screen.queryByTestId("twr-chart-skeleton")).not.toBeInTheDocument();

    // New data lands → the stale flag clears.
    await act(async () => {
      pending.resolve(HISTORY_3M);
    });
    await waitFor(() =>
      expect(screen.getByTestId("twr-chart")).not.toHaveAttribute("data-stale"),
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe("Round 3 · AnalyticsRiskMetricsPanel placeholderData", () => {
  it("period change keeps the panel populated and dims it via data-stale", async () => {
    const Wrapper = makeWrapper();

    mockGetValueHistory.mockResolvedValueOnce(HISTORY_1M);
    const { rerender } = render(
      <AnalyticsRiskMetricsPanel portfolioId="p1" period="1M" periodDays={30} />,
      { wrapper: Wrapper },
    );
    // n=2 daily returns from the 3-point series — proves data landed.
    await waitFor(() =>
      expect(screen.getByText(/n=2 daily returns/)).toBeInTheDocument(),
    );

    const pending = deferred<ValueHistoryResponse>();
    mockGetValueHistory.mockReturnValueOnce(pending.promise);
    rerender(
      <AnalyticsRiskMetricsPanel portfolioId="p1" period="3M" periodDays={90} />,
    );

    // Previous period's numbers stay rendered (no per-tile skeletons) and
    // the panel is flagged stale for the opacity dim.
    await waitFor(() =>
      expect(screen.getByTestId("client-risk-panel")).toHaveAttribute(
        "data-stale",
        "true",
      ),
    );
    expect(screen.getByText(/n=2 daily returns/)).toBeInTheDocument();

    await act(async () => {
      pending.resolve(HISTORY_3M);
    });
    await waitFor(() =>
      expect(screen.getByTestId("client-risk-panel")).not.toHaveAttribute(
        "data-stale",
      ),
    );
  });
});
