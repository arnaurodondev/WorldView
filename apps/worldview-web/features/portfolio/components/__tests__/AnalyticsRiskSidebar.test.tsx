/**
 * features/portfolio/components/__tests__/AnalyticsRiskSidebar.test.tsx
 *
 * WHY THESE TESTS EXIST: AnalyticsRiskSidebar renders 11 metric tiles driven by
 * the risk-metrics API response. Tests pin:
 *  1. Renders 11 skeleton tiles while the query is loading.
 *  2. Renders "—" for null metric values (null = absent, not zero).
 *  3. Renders formatted percentage for win_rate (0.583 → "58.3%").
 *  4. Renders formatted ratio for calmar (1.57 → "1.57").
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth        → stub token so the component never gates on auth.
 *  - @/lib/gateway          → stub getRiskMetrics so we control responses.
 *
 * WHAT IS NOT TESTED:
 *  - Actual CSS colour classes (Tailwind not computed in jsdom).
 *  - The 5-tile RiskMetricsStrip (separate component with its own tests).
 *  - Network error handling (getRiskMetrics never rejects in these tests).
 *
 * DATA SOURCE: mocked ExtendedRiskMetricsResponse
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §5.3
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

const mockGetRiskMetrics = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getRiskMetrics: mockGetRiskMetrics,
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────

import { AnalyticsRiskSidebar } from "../AnalyticsRiskSidebar";

// ── Test helpers ─────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  // WHY retry: false — without this TanStack Query retries failed queries 3×
  // before entering error state, making error tests take ~12s.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Base metrics with all optional Wave G fields populated.
// WHY include calmar/win_rate/alpha/cagr/var_95/period_return: these are the
// new fields the test specifically exercises (tiles 3–5 and 9–11).
const BASE_METRICS = {
  portfolio_id: "p1",
  lookback_days: 90,
  drawdown_max: -0.082,
  drawdown_current: -0.03,
  volatility_annualized: 0.184,
  sharpe: 1.42,
  sortino: 2.11,
  beta_vs_spy: 1.08,
  n_returns: 90,
  // Wave G extended fields (design spec §3 backend gap #6)
  calmar: 1.57,
  win_rate: 0.583,
  alpha: 0.0263,
  cagr: 0.1284,
  var_95: -0.023,
  period_return: 0.1284,
  data_quality: { status: "ok" as const, n_returns: 90, lookback_days: 90 },
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AnalyticsRiskSidebar", () => {
  beforeEach(() => {
    // WHY clearAllMocks: prevents a prior test's mockResolvedValue from bleeding
    // into subsequent tests via the shared mock function closure.
    vi.clearAllMocks();
  });

  // Test 1: Loading state renders 11 skeleton tiles.
  it("renders 11 skeleton tiles when loading", () => {
    // WHY never-resolving promise: keeps the query in the "loading" state for
    // the entire duration of the test — the component should show skeletons.
    mockGetRiskMetrics.mockReturnValue(new Promise(() => {}));

    render(wrap(<AnalyticsRiskSidebar portfolioId="p1" period="YTD" />));

    // The skeleton container must exist.
    const skeleton = screen.getByTestId("risk-sidebar-skeleton");
    expect(skeleton).toBeInTheDocument();

    // WHY count children: 11 skeleton tiles must render so the layout doesn't
    // collapse to a smaller grid while loading. The skeleton div has exactly 11
    // child tile elements (each a div with p-2 + Skeleton inside).
    expect(skeleton.children).toHaveLength(11);
  });

  // Test 2: Null metric values render as "—".
  it("renders '—' for null metric values", async () => {
    // All extended Wave G fields null — simulates an older gateway that hasn't
    // shipped calmar/win_rate/alpha/cagr/var_95/period_return yet.
    mockGetRiskMetrics.mockResolvedValue({
      ...BASE_METRICS,
      calmar: null,
      win_rate: null,
      alpha: null,
      cagr: null,
      var_95: null,
      period_return: null,
      sharpe: null,
      sortino: null,
      volatility_annualized: null,
      drawdown_max: null,
      beta_vs_spy: null,
    });

    render(wrap(<AnalyticsRiskSidebar portfolioId="p1" period="YTD" />));

    // WHY waitFor: TanStack Query resolves asynchronously — we must wait for
    // the data to appear before asserting.
    await waitFor(() => {
      // With all fields null, every tile should display "—".
      // WHY getAllByText("—"): there will be exactly 11 dashes (one per tile).
      const dashes = screen.getAllByText("—");
      expect(dashes.length).toBeGreaterThanOrEqual(11);
    });
  });

  // Test 3: win_rate renders as formatted percentage.
  it("renders formatted percentage for win_rate (0.583 → '58.3%')", async () => {
    mockGetRiskMetrics.mockResolvedValue(BASE_METRICS);

    render(wrap(<AnalyticsRiskSidebar portfolioId="p1" period="YTD" />));

    await waitFor(() => {
      // win_rate = 0.583 → "58.3%" (1dp, no sign prefix per the spec).
      // WHY exact string check: the format rule is "win_rate uses 1dp, no sign".
      // Testing the formatted output pins this rule against future refactors.
      expect(screen.getByText("58.3%")).toBeInTheDocument();
    });
  });

  // Test 4: calmar renders as formatted ratio.
  it("renders formatted ratio for calmar (1.57 → '1.57')", async () => {
    mockGetRiskMetrics.mockResolvedValue(BASE_METRICS);

    render(wrap(<AnalyticsRiskSidebar portfolioId="p1" period="YTD" />));

    await waitFor(() => {
      // calmar = 1.57 → "1.57" (2dp ratio, same as Sharpe/Sortino format).
      // WHY check the CALMAR tile specifically: it's the "new from Phase 1"
      // tile that did not exist on the 5-tile strip.
      expect(screen.getByText("1.57")).toBeInTheDocument();
      // Verify the tile label is also present.
      expect(screen.getByText("CALMAR")).toBeInTheDocument();
    });
  });
});
