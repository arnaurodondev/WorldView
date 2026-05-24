/**
 * features/portfolio/components/__tests__/AnalyticsPerformanceChart.test.tsx (F-004)
 *
 * WHY: Pins the three critical rendering paths:
 *  1. Shows loading skeleton while value-history is in-flight.
 *  2. Shows "no data" message when value-history returns an empty array.
 *  3. Renders a chart (SVG) + portfolio return label when data is available.
 *
 * MOCKED:
 *  - recharts (ResponsiveContainer → fixed-size div forwarder)
 *  - useAuth (stub token)
 *  - createGateway (stub getValueHistory + getTwr)
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Recharts mock ─────────────────────────────────────────────────────────────
// WHY: ResponsiveContainer uses ResizeObserver which returns 0 in jsdom —
// without the mock, Recharts never renders its SVG children.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({
      children,
    }: {
      children:
        | React.ReactElement<{ width?: number; height?: number }>
        | ((props: { width: number; height: number }) => React.ReactElement);
    }) => {
      const child =
        typeof children === "function"
          ? children({ width: 400, height: 200 })
          : // eslint-disable-next-line @typescript-eslint/no-explicit-any
            React.cloneElement(children as React.ReactElement<any>, { width: 400, height: 200 });
      return <div data-testid="responsive-container">{child}</div>;
    },
  };
});

// ── Auth stub ─────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "t@x.com", name: "T", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway stubs ─────────────────────────────────────────────────────────────
const mockGetValueHistory = vi.fn();
const mockGetTwr = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getValueHistory: mockGetValueHistory,
    getTwr: mockGetTwr,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { AnalyticsPerformanceChart } from "../AnalyticsPerformanceChart";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Two-point history giving a +10% period return. */
const HISTORY_10PCT: ValueHistoryResponse = {
  points: [
    { date: "2025-05-01", value: 100, cost_basis: 100, cash: 0 },
    { date: "2026-05-01", value: 110, cost_basis: 100, cash: 0 },
  ],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AnalyticsPerformanceChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // By default, getTwr stays unresolved (not needed for core path tests).
    mockGetTwr.mockReturnValue(new Promise(() => {}));
  });

  it("shows skeleton while value-history is loading", () => {
    // WHY never-resolving promise: keeps the query in loading state so we can
    // assert the skeleton before data arrives.
    mockGetValueHistory.mockReturnValue(new Promise(() => {}));

    const { container } = render(
      wrap(
        <AnalyticsPerformanceChart portfolioId="p-001" period="1Y" benchmark="SPY" />,
      ),
    );

    // The loading skeleton is an animate-pulse div; it should be present.
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("shows 'no data' message when value history is empty", async () => {
    // WHY empty points (not single point): computeCumulativeReturn(points) returns
    // [] only when points.length === 0 or base === 0. A single non-zero point
    // produces [{date, portfolio: 0}] — non-empty — so the chart renders instead.
    mockGetValueHistory.mockResolvedValue({
      points: [],
    } satisfies ValueHistoryResponse);

    render(
      wrap(
        <AnalyticsPerformanceChart portfolioId="p-001" period="1Y" benchmark="SPY" />,
      ),
    );

    await waitFor(() => {
      // WHY partial match: the exact wording may be adjusted; the key phrase
      // "trading days" identifies the no-data state.
      expect(screen.getByText(/trading days/i)).toBeInTheDocument();
    });
  });

  it("renders SVG chart and portfolio return label when data is available", async () => {
    mockGetValueHistory.mockResolvedValue(HISTORY_10PCT);

    const { container } = render(
      wrap(
        <AnalyticsPerformanceChart portfolioId="p-001" period="1Y" benchmark="SPY" />,
      ),
    );

    await waitFor(() => {
      // The chart renders an SVG.
      expect(container.querySelector("svg")).toBeTruthy();
      // The portfolio return label should show "+10.00%"
      // (110 - 100) / 100 = 0.10 → +10.00%.
      expect(screen.getByText("+10.00%")).toBeInTheDocument();
    });
  });
});
