/**
 * components/instrument/financials/__tests__/EarningsBarChart.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): the EarningsBarChart is the dual-bar
 * (actual vs estimate) EPS-history widget on the Financials tab (PRD-0088
 * §6.8, T-C-02). It is hand-rolled SVG (no recharts) so the only test that
 * matters at the unit level is: "Does it mount and render the SVG with the
 * right number of bar groups?"
 *
 *   1. The chart's <svg data-testid="earnings-bar-chart"> renders when data
 *      arrives — the empty branch returns null which would surface as a
 *      regression.
 *   2. Each FY emits one <text> label inside the SVG so 4-records → 4 FY
 *      labels.
 *
 * WHY no pixel-coord assertions: this test runs in jsdom where SVG geometry
 * (BBox, getComputedStyle) is unreliable. We assert on what's stable —
 * presence + count of structural children. Visual regressions belong in the
 * Playwright suite.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockGateway = vi.hoisted(() => ({ getEarningsHistory: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

// eslint-disable-next-line import/first
import { EarningsBarChart } from "@/components/instrument/financials/EarningsBarChart";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * fourYearEarnings — synthetic earnings-history records. Component reads
 * record.data.{date,epsActual,epsEstimate}; component sorts ascending by
 * date and slices the last 4 so any order is fine.
 */
function fourYearEarnings() {
  const rows = [
    { date: "2021-12-31", epsActual: 5.61, epsEstimate: 5.40 },
    { date: "2022-12-31", epsActual: 6.11, epsEstimate: 6.05 },
    { date: "2023-12-31", epsActual: 6.16, epsEstimate: 6.10 },
    { date: "2024-12-31", epsActual: 6.75, epsEstimate: 6.70 },
  ];
  return {
    security_id: "i-test-1",
    records: rows.map((r, i) => ({
      id: `er-${i}`,
      security_id: "i-test-1",
      section: "earnings_annual_trend",
      period_end: r.date,
      period_type: "ANNUAL" as const,
      data: r,
      source: "eodhd",
      ingested_at: new Date().toISOString(),
    })),
  };
}

beforeEach(() => {
  mockGateway.getEarningsHistory.mockReset();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("EarningsBarChart", () => {
  it("renders the SVG chart with the expected test id when 4 records arrive", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue(fourYearEarnings());
    render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    // The component sets data-testid="earnings-bar-chart" on the <svg>. We
    // wait for the query to resolve and the chart to mount.
    await waitFor(() => {
      expect(screen.getByTestId("earnings-bar-chart")).toBeInTheDocument();
    });
  });

  it("emits one FY label per record (FY21..FY24)", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue(fourYearEarnings());
    render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    await waitFor(() => {
      expect(screen.getByText("FY21")).toBeInTheDocument();
    });
    // WHY assert each: a future change that truncates to "last 3 FYs" or
    // accidentally dedupes by year would silently drop the oldest label.
    expect(screen.getByText("FY22")).toBeInTheDocument();
    expect(screen.getByText("FY23")).toBeInTheDocument();
    expect(screen.getByText("FY24")).toBeInTheDocument();
  });

  it("renders nothing when the gateway returns zero records (empty-state hidden)", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue({ security_id: "i-test-1", records: [] });
    const { container } = render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    // WHY waitFor: query resolves async; we wait until the loading skeleton
    // is gone (no <svg>, no skeleton) — i.e. the empty branch returned null.
    await waitFor(() => {
      expect(container.querySelector('[data-testid="earnings-bar-chart"]')).toBeNull();
    });
  });
});
