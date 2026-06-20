/**
 * features/portfolio/components/__tests__/AnalyticsTab.test.tsx (R2 sprint)
 *
 * WHY: integration-level wiring tests for the analytics surface —
 *   1. Period pills drive the backend lookback (YTD default → 1W → ALL).
 *   2. Benchmark toggles: SPY on by default; toggling QQQ lazily resolves
 *      and fetches its series (no QQQ traffic until requested).
 *   3. Client risk panel renders honest em-dashes + tooltips when the
 *      series is below the 20-observation gate (this is the user's money —
 *      a fabricated Sharpe would be worse than no Sharpe).
 *
 * MOCKED: @/lib/api-client (gateway). TanStack Query runs for real.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

// ── Gateway mocks ─────────────────────────────────────────────────────────────

const mockGetValueHistory = vi.fn();
const mockGetRiskMetrics = vi.fn();
const mockGetHoldings = vi.fn();
const mockResolveTickersBatch = vi.fn();
const mockGetOHLCV = vi.fn();
// 2026-06-10 sprint gap #3: the TWR chart now reads the flow-adjusted
// series endpoint (via useTwrSeries → createGateway, not useApiClient).
const mockGetTwr = vi.fn();

const gatewayStub = {
  getValueHistory: mockGetValueHistory,
  getRiskMetrics: mockGetRiskMetrics,
  getHoldings: mockGetHoldings,
  resolveTickersBatch: mockResolveTickersBatch,
  getOHLCV: mockGetOHLCV,
  getTwr: mockGetTwr,
};

vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => gatewayStub),
}));

// useTwrSeries goes through createGateway + useAuth (the overview-surface
// client pattern) — mock both so the chart's TWR query resolves in tests.
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => gatewayStub),
  GatewayError: class GatewayError extends Error {},
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token" })),
}));

// ── SUT import (after mocks) ─────────────────────────────────────────────────
import { AnalyticsTab } from "../AnalyticsTab";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** 2 points — enough for the charts, BELOW the 20-obs risk-metric gate. */
const SHORT_HISTORY: ValueHistoryResponse = {
  points: [
    { date: "2026-06-01", value: 100_000, cost_basis: 90_000, cash: 0 },
    { date: "2026-06-02", value: 101_000, cost_basis: 90_000, cash: 0 },
  ],
};

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Matching short TWR fixture for the chart (fractions; first point 0). */
const SHORT_TWR = {
  portfolio_id: "p-1",
  from_date: "2026-06-01",
  to_date: "2026-06-02",
  points: [
    { date: "2026-06-01", twr_cum: 0, nav: 100_000 },
    { date: "2026-06-02", twr_cum: 0.01, nav: 101_000 },
  ],
  flow_days: 0,
};

describe("AnalyticsTab (R2 wiring)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetValueHistory.mockResolvedValue(SHORT_HISTORY);
    mockGetTwr.mockResolvedValue(SHORT_TWR);
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
      ticker: "",
      timeframe: "1D",
      bars: [],
    });
  });

  it("defaults to YTD: backend risk metrics fetched with a 365-day lookback", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));
    await waitFor(() => {
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 365);
    });
  });

  it("clicking 1W re-fetches risk metrics with the real 7-day lookback; ALL → 1825", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));
    await waitFor(() => expect(mockGetRiskMetrics).toHaveBeenCalled());

    // Period pills are role=tab (AnalyticsPeriodSelector a11y contract).
    // 2026-06-10 sprint gap #4: the endpoint floor dropped 10 → 5 (short
    // windows now return 200 + insufficient_data instead of a 422), so 1W
    // passes through UNCLAMPED as 7 — the sidebar hint finally shows the
    // window the user actually selected.
    fireEvent.click(screen.getByRole("tab", { name: "1W" }));
    await waitFor(() => {
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 7);
    });

    fireEvent.click(screen.getByRole("tab", { name: "ALL" }));
    await waitFor(() => {
      // "ALL" maps to the widest concrete lookback the endpoint accepts.
      expect(mockGetRiskMetrics).toHaveBeenCalledWith("p-1", 1825);
    });
  });

  it("SPY overlay is on by default; QQQ is lazy until toggled", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    // SPY resolves at mount (overlay on + beta needs it)…
    await waitFor(() => {
      expect(mockResolveTickersBatch).toHaveBeenCalledWith(["SPY"]);
    });
    // …and QQQ generated zero traffic.
    expect(mockResolveTickersBatch).not.toHaveBeenCalledWith(
      expect.arrayContaining(["QQQ"]),
    );

    // Toggle states are exposed via aria-pressed.
    expect(screen.getByRole("button", { name: "SPY" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const qqqBtn = screen.getByRole("button", { name: "QQQ" });
    expect(qqqBtn).toHaveAttribute("aria-pressed", "false");

    // Toggling QQQ on triggers the batched resolve for both tickers
    // (sorted key — see useBenchmarkSeries).
    fireEvent.click(qqqBtn);
    await waitFor(() => {
      expect(mockResolveTickersBatch).toHaveBeenCalledWith(["QQQ", "SPY"]);
    });
    expect(qqqBtn).toHaveAttribute("aria-pressed", "true");
  });

  // ── Layout-overlap regression (2026-06-19) ─────────────────────────────────
  // The PERIOD RISK sidebar panel used to overlap the ATTRIBUTION column: the
  // charts column is a CSS-grid item with the default `min-width: auto`, so a
  // recharts ResponsiveContainer inside it could grow the 9/12 track past its
  // share and shove the col-span-3 sidebar sideways until they collided. The
  // fix pins every grid row with `items-start` and gives each column `min-w-0`
  // so the tracks size to their fractional share. These assertions lock the
  // structural guard in place — if a refactor drops min-w-0, the overlap
  // returns and this test fails loudly.
  it("lays the analytics grids out with overlap guards (items-start + min-w-0)", async () => {
    const { container } = render(wrap(<AnalyticsTab portfolioId="p-1" />));

    await waitFor(() => {
      expect(screen.getByTestId("client-risk-panel")).toBeInTheDocument();
    });

    // Every 12-column grid in the tab must pin its items to the top so a tall
    // sidebar column never stretches a neighbour into overlap.
    const grids = Array.from(
      container.querySelectorAll<HTMLElement>(".grid.grid-cols-12"),
    );
    expect(grids.length).toBeGreaterThanOrEqual(2);
    for (const grid of grids) {
      expect(grid.className).toContain("items-start");
      // Each direct grid child (a column) carries min-w-0 so the grid track
      // can shrink to its fractional width instead of its content's intrinsic
      // minimum (the recharts overflow vector).
      for (const col of Array.from(grid.children) as HTMLElement[]) {
        expect(col.className).toContain("min-w-0");
      }
    }
  });

  // ── Pathological-contribution clamping (2026-06-19) ────────────────────────
  // A cash-flow artifact can inflate the portfolio period return to +2327%,
  // making a single holding's contribution ~+218,000 bps. Printed raw this is
  // a ~10-char string that helped bleed the attribution panel into its
  // neighbour. fmtContribBps collapses 5+ digit bps to a "kbps" suffix and the
  // cell is whitespace-nowrap, so a hostile-wide value stays clamped.
  it("clamps a pathologically wide attribution contribution to a kbps suffix", async () => {
    // A huge period return (last/first − 1 ≈ +21.8x) over a single full-weight
    // holding → ~+218,000 bps contribution.
    mockGetValueHistory.mockResolvedValue({
      points: [
        { date: "2026-06-01", value: 10_000, cost_basis: 10_000, cash: 0 },
        { date: "2026-06-02", value: 228_000, cost_basis: 10_000, cash: 0 },
      ],
    } satisfies ValueHistoryResponse);
    mockGetHoldings.mockResolvedValue({
      portfolio_id: "p-1",
      holdings: [
        { ticker: "ZZZZ", quantity: 1, average_cost: 100 } as never,
      ],
    });

    const { container } = render(wrap(<AnalyticsTab portfolioId="p-1" />));

    // The contrib cell renders the bounded "kbps" form, never a raw 6-figure
    // bps string. We scan the attribution table's value cells for the suffix.
    await waitFor(() => {
      const text = container.textContent ?? "";
      expect(text).toMatch(/[+-]?\d+(\.\d)?kbps/);
    });
    // And the un-clamped raw form (e.g. "+218000bps") must NOT appear.
    expect(container.textContent ?? "").not.toMatch(/\d{5,}bps/);
  });

  it("client risk panel shows em-dashes + insufficient-data tooltips below 20 observations", async () => {
    render(wrap(<AnalyticsTab portfolioId="p-1" />));

    await waitFor(() => {
      expect(screen.getByTestId("client-risk-panel")).toBeInTheDocument();
    });

    // 2 points ⇒ 1 daily return ⇒ every metric is an honest "—".
    for (const id of [
      "client-risk-sharpe",
      "client-risk-max-dd",
      "client-risk-vol-ann",
      "client-risk-beta-spy",
    ]) {
      const tile = await screen.findByTestId(id);
      expect(tile).toHaveTextContent("—");
      // The tooltip names the reason (insufficient data / benchmark gap) —
      // never a bare dash the user has to guess about.
      expect(tile.getAttribute("title")).toMatch(/insufficient data|unavailable/i);
    }

    // Observation count footer quantifies the gate.
    await waitFor(() => {
      expect(screen.getByText(/n=1 daily returns/)).toBeInTheDocument();
    });
  });
});
