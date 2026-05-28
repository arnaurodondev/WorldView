/**
 * features/portfolio/components/__tests__/AnalyticsDrawdownChart.test.tsx (F-005)
 *
 * WHY: Pins three critical paths:
 *  1. Shows skeleton while value-history is loading.
 *  2. Shows "no drawdowns" message when fewer than 2 history points exist.
 *  3. Renders SVG + max-drawdown label when drawdown can be computed.
 *
 * MOCKED: recharts (ResponsiveContainer → div forwarder), useAuth, createGateway.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Recharts mock ─────────────────────────────────────────────────────────────
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

// ── Gateway stub ──────────────────────────────────────────────────────────────
const mockGetValueHistory = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getValueHistory: mockGetValueHistory,
  })),
}));

// WHY stub @/lib/api-client (Wave G QA D1).
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({
    getValueHistory: mockGetValueHistory,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { AnalyticsDrawdownChart } from "../AnalyticsDrawdownChart";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * History with a -10% drawdown: 100 → 120 → 108.
 * Running max at point 3 is 120, so drawdown = (108-120)/120 = -10%.
 */
const HISTORY_WITH_DRAWDOWN: ValueHistoryResponse = {
  points: [
    { date: "2026-01-01", value: 100, cost_basis: 100, cash: 0 },
    { date: "2026-02-01", value: 120, cost_basis: 100, cash: 0 },
    { date: "2026-03-01", value: 108, cost_basis: 100, cash: 0 },
  ],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AnalyticsDrawdownChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows skeleton while value-history is loading", () => {
    mockGetValueHistory.mockReturnValue(new Promise(() => {}));

    const { container } = render(
      wrap(<AnalyticsDrawdownChart portfolioId="p-001" period="1Y" />),
    );

    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("shows 'No drawdowns recorded yet' when fewer than 2 history points", async () => {
    mockGetValueHistory.mockResolvedValue({
      points: [{ date: "2026-05-01", value: 100, cost_basis: 100, cash: 0 }],
    } satisfies ValueHistoryResponse);

    render(
      wrap(<AnalyticsDrawdownChart portfolioId="p-001" period="1Y" />),
    );

    await waitFor(() => {
      expect(screen.getByText(/No drawdowns recorded yet/i)).toBeInTheDocument();
    });
  });

  it("renders SVG and max-drawdown label when drawdown series is non-empty", async () => {
    mockGetValueHistory.mockResolvedValue(HISTORY_WITH_DRAWDOWN);

    const { container } = render(
      wrap(<AnalyticsDrawdownChart portfolioId="p-001" period="1Y" />),
    );

    await waitFor(() => {
      // The area chart renders into an SVG.
      expect(container.querySelector("svg")).toBeTruthy();
      // The "Max Drawdown:" label must be visible.
      expect(screen.getByText(/Max Drawdown:/i)).toBeInTheDocument();
    });
  });
});
