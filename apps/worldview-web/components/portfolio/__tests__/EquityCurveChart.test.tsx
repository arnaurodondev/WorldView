/**
 * components/portfolio/__tests__/EquityCurveChart.test.tsx — PLAN-0108 W4-T406.
 *
 * WHY THIS EXISTS: T-4-06 spec requires a test that pins the "Value ($)" y-axis
 * label added to EquityCurveChart. lightweight-charts renders to a Canvas API
 * that is unavailable in jsdom, so we mock the dynamic import and focus on the
 * HTML label overlay (the only DOM element we own inside the chart container).
 *
 * MOCKED MODULES:
 *   - @/hooks/useAuth: stub so the enabled guard on useQuery resolves without a
 *     real Zitadel token.
 *   - @/lib/gateway: stub createGateway so useQuery stays in loading state and
 *     the component renders without firing real HTTP.
 *   - lightweight-charts: Canvas API unavailable in jsdom; mock with stub objects
 *     consistent with PerformanceChartPanel.test.tsx pattern.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth stub ─────────────────────────────────────────────────────────────────
// WHY vi.mock at module scope: vitest hoists vi.mock() before imports so the
// factory runs with the correct mock in place when the SUT is imported.
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
// WHY never-resolving fns: keeping useQuery in "loading" state means the
// component never progresses past the Skeleton branch — we don't need data to
// test the label, which is rendered in the chart (non-loading) branch.
// To reach the chart branch we resolve with a populated points array below.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getValueHistory: vi.fn(),
  })),
}));

// ── lightweight-charts stub ────────────────────────────────────────────────────
// WHY this mock: EquityCurveCanvas does `await import("lightweight-charts")`
// inside a useEffect. jsdom has no Canvas API so the real library would throw.
// We provide stub objects that satisfy the component's usage pattern.
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn(), setVisibleRange: vi.fn() })),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
  })),
  LineSeries: "LineSeries",
  ColorType: { Solid: "Solid" },
}));

// ── SUT import (after mocks are hoisted) ─────────────────────────────────────
import { EquityCurveChart } from "../EquityCurveChart";

// ── Test helpers ──────────────────────────────────────────────────────────────

/** Wrap in a minimal QueryClientProvider. retry:false prevents noisy console. */
function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("EquityCurveChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Value ($) label", async () => {
    // WHY this test: T-4-06 requires the y-axis label to be present in the DOM.
    // lightweight-charts cannot render HTML labels natively (Canvas-only), so
    // the label is an absolutely-positioned <span> overlaid on the chart container.
    // This test pins that the span exists with the correct text so future refactors
    // cannot silently remove it.
    //
    // WHY we override getValueHistory to return resolved data: the label lives
    // inside EquityCurveCanvas which only renders when the query succeeds with
    // ≥1 non-zero data points. Keeping useQuery in "loading" state would show
    // the Skeleton branch, which never reaches the canvas + label.
    const { createGateway } = await import("@/lib/gateway");
    (createGateway as ReturnType<typeof vi.fn>).mockReturnValue({
      getValueHistory: vi.fn().mockResolvedValue({
        points: [
          { date: "2026-01-01", value: 10000, cost_basis: 9000, cash: 500 },
          { date: "2026-01-02", value: 10500, cost_basis: 9000, cash: 500 },
        ],
        metadata: null,
      }),
    });

    render(wrap(<EquityCurveChart portfolioId="p-001" />));

    // The label must be in the document. We use findByText (async) because the
    // query resolves asynchronously and the chart branch renders after the tick.
    const label = await screen.findByText("Value ($)");
    expect(label).toBeInTheDocument();
  });
});
