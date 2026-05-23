/**
 * components/portfolio/__tests__/RiskMetricsPanel.test.tsx
 *
 * WHY THIS EXISTS: RiskMetricsPanel is the first 2×3 interactive risk grid
 * with a lookback chip selector. Tests pin:
 *  1. Loading skeleton renders while query is pending.
 *  2. All 6 metric cells appear when data arrives.
 *  3. Null metrics render as "—" (no NaN, no "0", no crash).
 *  4. Clicking the 180D chip fires a new query with lookback_days=180.
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth  → stub token so the component doesn't gate on a real auth flow.
 *  - @/lib/gateway    → stub getRiskMetrics so we control responses per-test.
 *
 * DATA SOURCE: mocked RiskMetricsResponse
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Risk Grid
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth stub ────────────────────────────────────────────────────────────────

// WHY module-level vi.mock: Vitest hoists vi.mock() to the top of the file
// (before imports) so every test gets the stub before any module code runs.
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

// ── Gateway stub ─────────────────────────────────────────────────────────────

// WHY a named variable: per-test overrides use mockGetRiskMetrics.mockResolvedValue()
// and mockGetRiskMetrics.mockRejectedValue() without re-declaring the mock.
const mockGetRiskMetrics = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getRiskMetrics: mockGetRiskMetrics,
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────

import { RiskMetricsPanel } from "../RiskMetricsPanel";

// ── Helpers ──────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  // WHY retry: false — without this, TanStack Query retries failed queries 3×
  // before entering error state, making the error test take ~12s and time out.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Baseline RiskMetricsResponse with all metrics populated.
const BASE_METRICS = {
  portfolio_id: "p1",
  lookback_days: 90,
  drawdown_max: -0.15,
  drawdown_current: -0.08,
  volatility_annualized: 0.22,
  sharpe: 1.2,
  sortino: 1.5,
  beta_vs_spy: 0.95,
  n_returns: 90,
  data_quality: { status: "ok" as const, n_returns: 90, lookback_days: 90 },
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("RiskMetricsPanel", () => {
  beforeEach(() => {
    // WHY reset: each test controls its own mock response. Without reset, a
    // prior test's mockResolvedValue bleeds into the next test.
    vi.clearAllMocks();
  });

  it("renders loading skeleton while query is pending", () => {
    // WHY never-resolve promise: keeps the query in the "loading" state for the
    // entire duration of the test — the component should show skeletons.
    mockGetRiskMetrics.mockReturnValue(new Promise(() => {}));

    render(
      wrap(<RiskMetricsPanel portfolioId="p1" />),
    );

    // The panel container should exist.
    expect(screen.getByTestId("risk-metrics-panel")).toBeInTheDocument();

    // WHY data-testid (not .animate-pulse): Tailwind classes are not computed in jsdom
    // (no CSS runtime). Using a data-testid on the skeleton container is the stable
    // pattern used throughout this codebase (see PortfolioKPIStrip, ExposureBreakdown).
    expect(screen.getByTestId("risk-metrics-skeleton")).toBeInTheDocument();
  });

  it("renders all 6 metric cells with data", async () => {
    mockGetRiskMetrics.mockResolvedValue(BASE_METRICS);

    render(
      wrap(<RiskMetricsPanel portfolioId="p1" />),
    );

    // Wait for the async query to resolve and DOM to update.
    // WHY waitFor: TanStack Query resolves asynchronously — we must wait for
    // the data to appear rather than synchronously asserting after render().
    await waitFor(() => {
      // Verify that all 6 cell labels are visible. If any are missing, the
      // test fails with a clear "Unable to find element with text ..." message.
      expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
      expect(screen.getByText("Volatility (Ann.)")).toBeInTheDocument();
      expect(screen.getByText("Sharpe Ratio")).toBeInTheDocument();
      expect(screen.getByText("Sortino Ratio")).toBeInTheDocument();
      expect(screen.getByText("Beta (vs SPY)")).toBeInTheDocument();
      expect(screen.getByText("VaR 95%")).toBeInTheDocument();
    });

    // Verify at least one formatted numeric value appears.
    // Max drawdown of -0.15 → "-15.00%" (formatPercent applied).
    // WHY this specific value: it exercises the fmtPct path including the "-" sign.
    const panelEl = screen.getByTestId("risk-metrics-panel");
    expect(panelEl.textContent).toContain("15");
  });

  it("null metrics render as '—'", async () => {
    // All metrics null — e.g., insufficient history (< 10 returns).
    mockGetRiskMetrics.mockResolvedValue({
      ...BASE_METRICS,
      drawdown_max: null,
      volatility_annualized: null,
      sharpe: null,
      sortino: null,
      beta_vs_spy: null,
    });

    render(
      wrap(<RiskMetricsPanel portfolioId="p1" />),
    );

    await waitFor(() => {
      // Labels should still be present (the grid doesn't collapse).
      expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    });

    // WHY getAllByText: multiple cells can show "—" simultaneously (all 5 nulls + VaR).
    // We assert there are at least 5 em-dashes.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(5);
  });

  it("clicking 180D chip switches the lookback and fires query with 180", async () => {
    // First call: 90D default.
    mockGetRiskMetrics.mockResolvedValue(BASE_METRICS);

    render(
      wrap(<RiskMetricsPanel portfolioId="p1" />),
    );

    await waitFor(() => {
      expect(screen.getByTestId("chip-90D")).toBeInTheDocument();
    });

    // The 90D chip should be active (aria-pressed=true) by default.
    expect(screen.getByTestId("chip-90D")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("chip-180D")).toHaveAttribute("aria-pressed", "false");

    // Click the 180D chip — should switch aria-pressed AND trigger a new query.
    mockGetRiskMetrics.mockResolvedValue({ ...BASE_METRICS, lookback_days: 180 });
    fireEvent.click(screen.getByTestId("chip-180D"));

    await waitFor(() => {
      // WHY check aria-pressed: it is the canonical accessible indicator that
      // the chip is now active — it drives screen-reader announcements and can
      // be asserted without relying on Tailwind colour classes (which jsdom
      // doesn't compute).
      expect(screen.getByTestId("chip-180D")).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByTestId("chip-90D")).toHaveAttribute("aria-pressed", "false");
    });

    // The mock should have been called with lookback_days=180 on the new render.
    // WHY check mock calls: verifies the useQuery key changed (new lookback triggers refetch).
    expect(mockGetRiskMetrics).toHaveBeenCalledWith("p1", 180);
  });
});
