/**
 * components/portfolio/__tests__/PerformanceChartPanel.test.tsx — PLAN-0108 W3-T304.
 *
 * WHY THIS EXISTS: T-3-04 spec audit requires tests that pin the three most
 * critical behavioural contracts of PerformanceChartPanel:
 *   1. The collapse toggle button is always rendered.
 *   2. Clicking the toggle calls onToggleCollapse (collapse/expand lifecycle).
 *   3. The outer wrapper carries h-[120px] when expanded.
 *
 * WHAT IS NOT TESTED HERE:
 *   - Actual chart paint (lightweight-charts is mocked — Canvas is unavailable
 *     in jsdom; the library is dynamically imported so it never reaches that
 *     code path in these unit tests anyway).
 *   - TanStack Query resolution paths (covered by equity-curve-empty-state.test.tsx
 *     which already tests the getValueHistory 0-point / populated paths).
 *
 * MOCKED MODULES:
 *   - @/hooks/useAuth: stub so the enabled guard on useQuery resolves without a
 *     real Zitadel token.
 *   - @/lib/gateway: stub createGateway so the component doesn't fire real HTTP
 *     calls. getValueHistory and related methods return pending promises by
 *     default (vi.fn() = never resolves) — we only care about the initial render.
 *   - lightweight-charts: Canvas API unavailable in jsdom; mock with stub objects
 *     so the dynamic import in mountChart() resolves without throwing.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth stub ─────────────────────────────────────────────────────────────────
// WHY vi.mock at module scope (not beforeEach): vitest hoists vi.mock() calls
// before any imports so the module factory runs with the right mock in place.
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
// WHY never-resolving fns: we only test render-time DOM state, not async data.
// Leaving the mocks as vi.fn() means useQuery stays in "loading" state and the
// component renders its chart-container branch (not the error/unavailable branch).
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getValueHistory: vi.fn(),          // stays pending → historyData = undefined
    resolveTickersBatch: vi.fn(),      // stays pending → spyIdMap = undefined
    getOHLCV: vi.fn(),                 // stays pending → spyOhlcv = undefined
  })),
}));

// ── lightweight-charts stub ────────────────────────────────────────────────────
// WHY this mock: the component does `await import("lightweight-charts")` inside
// a useCallback that fires only when historyData is available. Since our gateway
// stub never resolves, mountChart() returns early before the dynamic import —
// but we mock the module anyway to prevent any future change from breaking the
// test environment. Pattern matches equity-curve-empty-state.test.tsx exactly.
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn(), applyOptions: vi.fn() })),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
  })),
  LineSeries: "LineSeries",
  ColorType: { Solid: "Solid" },
}));

// ── SUT import (after mocks are hoisted) ─────────────────────────────────────
import { PerformanceChartPanel } from "../PerformanceChartPanel";

// ── Test helpers ──────────────────────────────────────────────────────────────

/** Wrap in a minimal QueryClientProvider. retry:false prevents noisy console. */
function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PerformanceChartPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders collapse toggle", () => {
    // WHY this test: the toggle button is the primary interactive element of
    // the panel. If it's ever accidentally removed or hidden (e.g. behind a
    // conditional that defaults to false), the user loses all ability to
    // reclaim screen space — a critical UX regression.
    render(
      wrap(
        <PerformanceChartPanel
          portfolioId="p-001"
          period="1M"
          onPeriodChange={vi.fn()}
          collapsed={false}
          onToggleCollapse={vi.fn()}
        />,
      ),
    );

    // The toggle button has an aria-label that describes its action.
    // WHY aria-label query (not text): the button text "Performance" is split
    // across two <span>s with an arrow glyph; aria-label is the canonical
    // accessible name and is stable across glyph changes.
    const toggle = screen.getByRole("button", { name: "Collapse performance chart" });
    expect(toggle).toBeInTheDocument();
  });

  it("is collapsed when toggle clicked", () => {
    // WHY this test: collapse is a controlled component — collapsed state lives
    // outside PerformanceChartPanel (in the parent) and is passed down as a prop.
    // We verify that clicking the toggle fires onToggleCollapse so the parent
    // can update its state — if this call is ever dropped, collapse breaks silently.
    const onToggle = vi.fn();

    render(
      wrap(
        <PerformanceChartPanel
          portfolioId="p-001"
          period="1M"
          onPeriodChange={vi.fn()}
          collapsed={false}
          onToggleCollapse={onToggle}
        />,
      ),
    );

    const toggle = screen.getByRole("button", { name: "Collapse performance chart" });
    fireEvent.click(toggle);

    // onToggleCollapse must be called exactly once after a single click.
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("renders at 120px when expanded", () => {
    // WHY this test: PRD-0108 §6.1 specifies h-[120px] for the expanded panel.
    // If the height class is removed or changed, the strip either collapses to
    // content height (too small for the chart) or balloons to fill the container
    // (too large, obscures the holdings table). This test pins that class.
    const { container } = render(
      wrap(
        <PerformanceChartPanel
          portfolioId="p-001"
          period="1M"
          onPeriodChange={vi.fn()}
          collapsed={false}
          onToggleCollapse={vi.fn()}
        />,
      ),
    );

    // The outermost <div> of the component carries the height class.
    // WHY firstElementChild: the wrapper injected by QueryClientProvider is a
    // React fragment/context boundary, not a DOM element; firstElementChild
    // gives us the actual panel root div.
    const panel = container.firstElementChild;
    expect(panel).toHaveClass("h-[120px]");
  });

  it("renders at 22px when collapsed", () => {
    // WHY this test: collapsed height is h-[22px] per PRD-0108 §6.1.
    // 22px (not 28px) is specified to keep the collapsed bar ultra-compact.
    // This assertion catches a regression to the old 28px value.
    const { container } = render(
      wrap(
        <PerformanceChartPanel
          portfolioId="p-001"
          period="1M"
          onPeriodChange={vi.fn()}
          collapsed={true}
          onToggleCollapse={vi.fn()}
        />,
      ),
    );

    const panel = container.firstElementChild;
    expect(panel).toHaveClass("h-[22px]");
    // Sanity-check: expanded class must NOT be present in collapsed state.
    expect(panel).not.toHaveClass("h-[120px]");
  });
});
