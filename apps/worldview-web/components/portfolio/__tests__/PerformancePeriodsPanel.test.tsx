/**
 * components/portfolio/__tests__/PerformancePeriodsPanel.test.tsx
 * (2026-06-10 sprint, Wave 2 — overview band panel #3.)
 *
 * WHY: pins the TWR-vs-SPY comparison wiring — real rows from the
 * flow-adjusted endpoint, window-not-covered "—" cells, the named
 * "SPY unavailable" degradation, the not-enough-history state, and the
 * error + retry path. The window math lives in
 * lib/__tests__/period-returns.test.ts; this suite covers the surface.
 *
 * MOCKED: @/lib/gateway (createGateway pattern — the panel mounts on the
 * default Holdings tab) + useAuth. TanStack Query runs for real.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockGetTwr = vi.fn();
const mockResolveTickersBatch = vi.fn();
const mockGetOHLCV = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getTwr: mockGetTwr,
    resolveTickersBatch: mockResolveTickersBatch,
    getOHLCV: mockGetOHLCV,
  })),
  GatewayError: class GatewayError extends Error {},
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "test-token" })),
}));

import { PerformancePeriodsPanel } from "../PerformancePeriodsPanel";
import type { TwrResponse } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** ISO date N days before today (panel windows are relative to "now"). */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** 10 days of TWR (+1pp/day) — covers 1D/1W, NOT 1M/3M.
 *
 * 2026-06-11 Wave 3: NAV now moves WITH the TWR (was a constant 100_000
 * placeholder). A frozen NAV with a moving TWR is exactly the stale-snapshot
 * flow-artifact signature period-returns.ts now suppresses — the fixture must
 * look like an honest flow-free series for the window-math assertions to see
 * real numbers. */
function shortTwr(): TwrResponse {
  const points = [];
  for (let i = 9; i >= 0; i--) {
    const twr = (9 - i) * 0.01;
    points.push({ date: daysAgo(i), twr_cum: twr, nav: 100_000 * (1 + twr) });
  }
  return {
    portfolio_id: "p-1",
    from_date: daysAgo(9),
    to_date: daysAgo(0),
    points,
    flow_days: 0,
  };
}

/** SPY closes for the same 10 days (+$1/day from 500). */
function spyBars() {
  const bars = [];
  for (let i = 9; i >= 0; i--) {
    bars.push({ timestamp: daysAgo(i), close: 500 + (9 - i) });
  }
  return { instrument_id: "iid-spy", ticker: "SPY", timeframe: "1D", bars };
}

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetTwr.mockResolvedValue(shortTwr());
  mockResolveTickersBatch.mockResolvedValue({ SPY: "iid-spy" });
  mockGetOHLCV.mockResolvedValue(spyBars());
});

describe("PerformancePeriodsPanel", () => {
  it("renders all four window rows with portfolio + SPY + excess", async () => {
    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));

    await waitFor(() =>
      expect(screen.getByTestId("period-row-1W")).toBeInTheDocument(),
    );
    expect(screen.getByText("Performance — TWR vs SPY")).toBeInTheDocument();

    const oneW = screen.getByTestId("period-row-1W");
    // Portfolio TWR over 7d: (1.09/1.02)−1 ≈ +6.86%.
    expect(oneW).toHaveTextContent("+6.86%");
    // SPY over the same window: 509/502−1 ≈ +1.39%.
    expect(oneW).toHaveTextContent("SPY +1.39%");
    // Excess in percentage points.
    expect(oneW).toHaveTextContent("pp");
  });

  it("windows not covered by the series render '—' (never a mislabelled return)", async () => {
    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("period-row-3M")).toBeInTheDocument(),
    );
    // 10 days of history → 1M/3M cannot be honestly computed.
    expect(screen.getByTestId("period-row-3M")).toHaveTextContent("—");
    expect(screen.getByTestId("period-row-1M")).toHaveTextContent("—");
  });

  it("suppresses windows containing a backend flow artifact ('—' + tooltip, never +23.97%)", async () => {
    // 2026-06-11 Wave 3 regression (live bug): the demo book's TWR series
    // contains a final-day +24% jump that is a FLOW, not performance —
    // the panel showed "1D +23.97%" on a −4.6% book day. The guarded math
    // must suppress the window and name the reason in a tooltip.
    const points = [];
    for (let i = 9; i >= 1; i--) {
      const twr = (9 - i) * 0.01;
      points.push({ date: daysAgo(i), twr_cum: twr, nav: 100_000 * (1 + twr) });
    }
    // Final day: +24% TWR jump in one interval (> the 15% plausibility bound).
    points.push({ date: daysAgo(0), twr_cum: 0.08 * 1.24 + 0.24, nav: 134_000 });
    mockGetTwr.mockResolvedValue({
      portfolio_id: "p-1",
      from_date: daysAgo(9),
      to_date: daysAgo(0),
      points,
      flow_days: 1,
    });

    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("period-row-1D")).toBeInTheDocument(),
    );

    // The 1D window contains the artifact: suppressed cell, named tooltip.
    const suppressed = screen.getByTestId("period-flow-artifact-1D");
    expect(suppressed).toHaveTextContent("—");
    expect(suppressed.getAttribute("title")).toMatch(/cash-flow artifact/i);
    // The corrupted number must never reach the DOM.
    expect(screen.queryByText(/\+2[0-9]\.\d{2}%/)).toBeNull();
  });

  it("announces SPY unavailability instead of failing silently", async () => {
    mockResolveTickersBatch.mockRejectedValue(new Error("resolve down"));
    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));

    // Portfolio rows still render — benchmark failure never blocks them.
    await waitFor(() =>
      expect(screen.getByTestId("period-row-1W")).toBeInTheDocument(),
    );
    expect(
      await screen.findByTestId("performance-spy-unavailable"),
    ).toBeInTheDocument();
    // Benchmark cells degrade to "SPY —".
    expect(screen.getByTestId("period-row-1W")).toHaveTextContent("SPY —");
  });

  it("named gap state for a brand-new portfolio (<2 TWR points)", async () => {
    mockGetTwr.mockResolvedValue({
      portfolio_id: "p-1",
      from_date: daysAgo(0),
      to_date: daysAgo(0),
      points: [{ date: daysAgo(0), twr_cum: 0, nav: 1_000 }],
      flow_days: 0,
    });
    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));
    expect(
      await screen.findByText(/not enough history yet/i),
    ).toBeInTheDocument();
  });

  it("named error state with retry when the TWR fetch fails", async () => {
    mockGetTwr.mockRejectedValue(new Error("boom"));
    render(wrap(<PerformancePeriodsPanel portfolioId="p-1" />));
    expect(
      await screen.findByTestId("performance-periods-error"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /retry loading twr series/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing without a portfolio id", () => {
    const { container } = render(wrap(<PerformancePeriodsPanel portfolioId={null} />));
    expect(container.firstChild).toBeNull();
  });
});
