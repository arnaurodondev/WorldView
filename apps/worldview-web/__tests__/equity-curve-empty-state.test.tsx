/**
 * __tests__/equity-curve-empty-state.test.tsx — PLAN-0049 T-D-4-05.
 *
 * WHY THIS EXISTS: A real bug shipped where a brand-new portfolio rendered a
 * large black panel where the equity curve should be — no chart, no message,
 * just a void. The fix wired the empty state through ``<InlineEmptyState>``
 * (BP-265 / F-009 / F-210). This test pins the contract so a regression in
 * the empty-state branch trips the suite immediately.
 *
 * SCOPE: 2 specs:
 *   1. With NO snapshots → renders ``<InlineEmptyState>`` (NOT the chart, and
 *      NOT a bare empty <div>).
 *   2. With populated points → renders the chart (LineChart from Recharts).
 *
 * WHY MOCK GATEWAY: EquityCurveChart calls ``getValueHistory()`` inside a
 * TanStack Query. Mocking lets us drive the empty vs populated paths
 * deterministically without standing up S1.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Auth + navigation mocks ──────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/portfolio"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// ── Gateway mock — ValueHistoryResponse drives the two paths ─────────────────
const mockGetValueHistory = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getValueHistory: mockGetValueHistory })),
}));

import { EquityCurveChart } from "@/components/portfolio/EquityCurveChart";

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("EquityCurveChart — PLAN-0049 T-D-4-05 empty-state guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders InlineEmptyState (not a large black panel) when there are no snapshots", async () => {
    // WHY this is the primary regression: pre-fix, the empty branch returned
    // an unstyled flex container with no children — appearing as a giant
    // black rectangle on the portfolio page. The fix uses InlineEmptyState
    // which renders a single muted line of copy.
    const emptyResp: ValueHistoryResponse = {
      points: [],
      metadata: { last_snapshot_at: null, next_scheduled_run_utc: null },
    };
    mockGetValueHistory.mockResolvedValue(emptyResp);

    const { container, findByText } = render(
      <EquityCurveChart portfolioId="port-1" />,
      { wrapper: ({ children }) => wrap(children) },
    );

    // The InlineEmptyState message text from EquityCurveChart line 301.
    await findByText(/No snapshots yet/i);

    // Negative assertion: NO svg (Recharts <LineChart> renders an SVG). If a
    // chart appeared with the empty data, this would fail.
    const svg = container.querySelector("svg");
    expect(svg).toBeNull();
  });

  it("renders the chart container (not the empty state) when there are points", async () => {
    // Inverse of the above — populated data must render the chart, not the
    // empty state. We assert the absence of the empty-state copy AND the
    // presence of the recharts ResponsiveContainer wrapper class
    // (".recharts-responsive-container") that EquityCurveChart wraps the
    // LineChart in. We avoid asserting the SVG itself because Recharts'
    // ResponsiveContainer needs a real ResizeObserver to compute width/height
    // and skips rendering its child in jsdom — but the wrapper div is always
    // present and is enough to prove we took the chart branch (not empty).
    const populatedResp: ValueHistoryResponse = {
      points: [
        { date: "2026-04-01", value: 100, cost_basis: 100, cash: 0 },
        { date: "2026-04-15", value: 110, cost_basis: 100, cash: 0 },
        { date: "2026-04-29", value: 120, cost_basis: 100, cash: 0 },
      ],
      metadata: { last_snapshot_at: "2026-04-29", next_scheduled_run_utc: null },
    };
    mockGetValueHistory.mockResolvedValue(populatedResp);

    const { container, queryByText } = render(
      <EquityCurveChart portfolioId="port-1" />,
      { wrapper: ({ children }) => wrap(children) },
    );

    // Wait for any tick after the query resolves so React re-renders.
    await waitFor(() => {
      // The recharts ResponsiveContainer wrapper class confirms we entered
      // the chart branch (the empty branch would render only a <p>).
      const respContainer = container.querySelector(".recharts-responsive-container");
      expect(respContainer).not.toBeNull();
    });

    // Negative: empty-state copy must NOT be present.
    expect(queryByText(/No snapshots yet/i)).toBeNull();
    expect(queryByText(/Open a position to see your equity curve/i)).toBeNull();
  });
});
