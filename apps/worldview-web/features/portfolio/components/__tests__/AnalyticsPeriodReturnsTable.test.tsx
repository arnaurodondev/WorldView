/**
 * features/portfolio/components/__tests__/AnalyticsPeriodReturnsTable.test.tsx (F-006)
 *
 * WHY: Covers the D-002 refactor (useQueries) and — since the 2026-06-10
 * TWR upgrade — verifies:
 *  1. All 8 period rows render (data-testid="period-row-{PERIOD}").
 *  2. A positive flow-adjusted TWR renders with a "+" prefix (PORTED from
 *     the value-history era: same assertion, real TWR source now).
 *  3. Insufficient history (<2 points) renders "—" (PORTED).
 *  4. NEW: the vs SPY / EXCESS columns populate from real SPY closes over
 *     the same window, and the ALL row keeps an honest "—" benchmark.
 *
 * MOCKED: useAuth, api-client gateway (getTwr / resolveTickersBatch /
 * getOHLCV). @tanstack/react-query is real — useQueries is the layer under
 * test.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { TwrResponse } from "@/types/api";

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
const mockGetTwr = vi.fn();
const mockResolveTickersBatch = vi.fn();
const mockGetOHLCV = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getTwr: mockGetTwr,
    resolveTickersBatch: mockResolveTickersBatch,
    getOHLCV: mockGetOHLCV,
  })),
}));

// WHY stub @/lib/api-client (Wave G QA D1): the table reads the gateway via
// the provider-memoised useApiClient.
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => ({
    getTwr: mockGetTwr,
    resolveTickersBatch: mockResolveTickersBatch,
    getOHLCV: mockGetOHLCV,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { AnalyticsPeriodReturnsTable } from "../AnalyticsPeriodReturnsTable";

// ── Fixtures ──────────────────────────────────────────────────────────────────

// R2 sprint: "1W" row added to the table — list extended to stay exhaustive.
const ALL_PERIODS = ["1W", "1M", "3M", "6M", "YTD", "1Y", "2Y", "ALL"] as const;

/** ISO date N days before today. */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** TWR window response: rebased to 0, ending at +20% (fraction). */
function makeTwr(): TwrResponse {
  return {
    portfolio_id: "p-001",
    from_date: daysAgo(30),
    to_date: daysAgo(0),
    points: [
      { date: daysAgo(30), twr_cum: 0, nav: 100 },
      { date: daysAgo(0), twr_cum: 0.2, nav: 120 },
    ],
    flow_days: 1,
  };
}

/** SPY closes covering 2 years: flat 500 → 550 (+10%) over the span. */
function makeSpyBars() {
  const bars = [];
  for (let i = 735; i >= 0; i -= 5) {
    bars.push({ timestamp: daysAgo(i), close: 500 + ((735 - i) / 735) * 50 });
  }
  return { instrument_id: "iid-spy", ticker: "SPY", timeframe: "1D", bars };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AnalyticsPeriodReturnsTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockResolveTickersBatch.mockResolvedValue({ SPY: "iid-spy" });
    mockGetOHLCV.mockResolvedValue(makeSpyBars());
  });

  it("renders all 8 period rows via data-testid", async () => {
    mockGetTwr.mockResolvedValue(makeTwr());

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      for (const p of ALL_PERIODS) {
        expect(screen.getByTestId(`period-row-${p}`)).toBeInTheDocument();
      }
    });
  });

  it("shows '+' prefixed TWR for a positive period (ported from the NAV era)", async () => {
    mockGetTwr.mockResolvedValue(makeTwr());

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      // +20% TWR → "+20.00%" in every row's TWR cell (8 rows), and the
      // benchmark/excess columns add their own "+" values on top — assert
      // at least the 8 TWR cells.
      const positiveReturns = screen.getAllByText(/^\+\d/);
      expect(positiveReturns.length).toBeGreaterThanOrEqual(8);
    });
  });

  it("shows '—' when the TWR series is insufficient (fewer than 2 points)", async () => {
    mockGetTwr.mockResolvedValue({
      portfolio_id: "p-001",
      from_date: daysAgo(0),
      to_date: daysAgo(0),
      points: [{ date: daysAgo(0), twr_cum: 0, nav: 100 }],
      flow_days: 0,
    } satisfies TwrResponse);

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      const dashes = screen.getAllByText("—");
      // Each of the 8 rows contributes at least one "—" in the TWR column
      // (plus the dependent benchmark/excess dashes).
      expect(dashes.length).toBeGreaterThanOrEqual(8);
    });
  });

  it("populates vs SPY + EXCESS from real closes; ALL keeps an honest '—' benchmark", async () => {
    mockGetTwr.mockResolvedValue(makeTwr());

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      // 1Y row: SPY moved ≈ half its 2y span — a real "+x.xx%" appears in
      // the benchmark cell and an excess "pp" value computes from it.
      const oneY = screen.getByTestId("period-row-1Y");
      expect(oneY).toHaveTextContent(/\+\d+\.\d{2}%.*\+\d+\.\d{2}%.*pp/);
    });

    // The ALL row's benchmark is "—" (open-ended window has no SPY span)
    // and so is its excess — the TWR value still renders.
    const allRow = screen.getByTestId("period-row-ALL");
    expect(allRow).toHaveTextContent("+20.00%");
    expect(allRow).toHaveTextContent("—");
  });
});
