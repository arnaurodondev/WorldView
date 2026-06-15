/**
 * components/instrument/financials/__tests__/EarningsBarChart.test.tsx
 *
 * WHY THIS EXISTS (Wave-4 chart rebuild): the EarningsBarChart is the dual-bar
 * (actual vs estimate) EPS-history widget on the Financials tab. It was
 * rebuilt from a hand-rolled <svg> to a recharts <ComposedChart> to gain a
 * labelled Y axis, per-bar value labels, a trajectory line, and a hover
 * tooltip (the old SVG was static and unreadable).
 *
 * ── HOW WE TEST RECHARTS UNDER JSDOM ──
 * recharts sizes its inner SVG from the container's measured width, but jsdom
 * reports width 0 and the project's ResizeObserver stub never fires — so a
 * real ResponsiveContainer renders an EMPTY svg (no bars/labels/axis ticks).
 * This is the same reason SectorAllocationDonut.test asserts on legend DOM
 * rather than SVG slices. We therefore MOCK ResponsiveContainer to a
 * fixed-size wrapper so the chart's children (axes, bars, tooltip plumbing)
 * actually render and we can assert on stable structural DOM.
 *
 * The assertions deliberately target STABLE DOM (the named panel, the legend,
 * the chart svg, the FY axis labels, and the empty-state branch) rather than
 * pixel geometry. Visual regressions belong in the Playwright suite.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ────────────────────────────────────────────────────────────────────

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

const mockGateway = vi.hoisted(() => ({ getEarningsHistory: vi.fn() }));

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// Force recharts' ResponsiveContainer to a fixed 480x168 box so its children
// render in jsdom (where measured width is 0). We import the real module and
// override only that one export.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactNode }) =>
      // recharts' chart children read width/height from the *parent* of the
      // chart element via context; passing an explicit-size wrapper that
      // recharts' <Surface> can measure is unreliable, so we render the chart
      // children inside a div with a deterministic inline size.
      actual.ResponsiveContainer
        ? // Use a real container but lock its dimensions.
          (
            <div style={{ width: 480, height: 168 }}>
              <actual.ResponsiveContainer width={480} height={168}>
                {children as never}
              </actual.ResponsiveContainer>
            </div>
          )
        : null,
  };
});

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
 * record.data.{date,epsActual,epsEstimate,surprisePercent}; it sorts ascending
 * by date and slices the last 6 so any order is fine.
 */
function fourYearEarnings() {
  const rows = [
    { date: "2021-12-31", epsActual: 5.61, epsEstimate: 5.4, surprisePercent: 3.9 },
    { date: "2022-12-31", epsActual: 6.11, epsEstimate: 6.05, surprisePercent: 1.0 },
    { date: "2023-12-31", epsActual: 6.16, epsEstimate: 6.1, surprisePercent: 1.0 },
    { date: "2024-12-31", epsActual: 6.75, epsEstimate: 6.7, surprisePercent: 0.7 },
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
  it("renders the named EARNINGS panel + recharts svg when data arrives", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue(fourYearEarnings());
    render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    // The panel header names the chart (was an orphan SVG before).
    await waitFor(() => {
      expect(screen.getByText("EARNINGS")).toBeInTheDocument();
    });
    // recharts attaches our data-testid to the chart root <svg>.
    expect(screen.getByTestId("earnings-bar-chart")).toBeInTheDocument();
  });

  it("renders a legend naming the ACT / EST / TREND encoding", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue(fourYearEarnings());
    render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    // The legend makes the dual-bar + trend-line encoding explicit instead of
    // leaving the user to guess (a key readability fix). TREND only shows when
    // surprise data exists — the fixture supplies it.
    await waitFor(() => {
      expect(screen.getByText("ACT")).toBeInTheDocument();
    });
    expect(screen.getByText("EST")).toBeInTheDocument();
    expect(screen.getByText("TREND")).toBeInTheDocument();
  });

  it("emits the FY axis labels (FY21..FY24) for the four records", async () => {
    mockGateway.getEarningsHistory.mockResolvedValue(fourYearEarnings());
    render(
      <Wrapper>
        <EarningsBarChart instrumentId="i-test-1" />
      </Wrapper>,
    );
    // XAxis renders each label as an SVG <text>. A future change that
    // truncates the window would silently drop the oldest FY label.
    await waitFor(() => {
      expect(screen.getByText("FY21")).toBeInTheDocument();
    });
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
    // The empty branch returns null — no panel, no chart.
    await waitFor(() => {
      expect(container.querySelector('[data-testid="earnings-panel"]')).toBeNull();
    });
    expect(screen.queryByText("EARNINGS")).not.toBeInTheDocument();
  });
});
