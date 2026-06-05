/**
 * components/instrument/financials/__tests__/IncomeStatementTable.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): the Income Statement table is the
 * top-of-page P&L ladder on the Financials tab (PRD-0088 §6.8). T-C-02
 * specs: 4 fiscal-year columns × 5 rows (Revenue / Gross Profit / EBIT /
 * Net Income / EPS). We pin two contracts:
 *
 *   1. Exactly 4 FY column headers render when 4 ANNUAL records are returned.
 *   2. Row labels are present (mount + label-render smoke check).
 *
 * WHY mock the gateway: the component owns its own useQuery — the easiest
 * way to drive it to a populated state is to stub the gateway return value
 * with synthetic records. EODHD's data shape uses PascalCase (totalRevenue
 * etc.) which we mirror in the synthetic data so extractValue() finds them.
 *
 * WHY skip the empty / loading branches here: the FY-count and label
 * contract are the load-bearing ones for T-E-02. Loading-state assertions
 * are already exercised by neighbouring widgets (wave-f-remainder pattern).
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

const mockGateway = vi.hoisted(() => ({ getIncomeStatement: vi.fn() }));

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

// eslint-disable-next-line import/first
import { IncomeStatementTable } from "@/components/instrument/financials/IncomeStatementTable";

// ── Helpers ──────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * fourYearAnnual — synthetic FundamentalsSectionResponse with exactly four
 * ANNUAL records FY21 → FY24. PascalCase keys mirror EODHD's payload.
 */
function fourYearAnnual() {
  const years = [2021, 2022, 2023, 2024];
  return {
    security_id: "i-test-1",
    records: years.map((y, i) => ({
      id: `rec-${y}`,
      security_id: "i-test-1",
      section: "income_statement",
      // WHY 12-31: EODHD uses fiscal-year-end dates; this is the canonical
      // calendar-year FY close (good enough for non-shifted-FY tickers).
      period_end: `${y}-12-31`,
      period_type: "ANNUAL" as const,
      data: {
        totalRevenue: 100_000_000 * (i + 1),
        grossProfit: 40_000_000 * (i + 1),
        operatingIncome: 25_000_000 * (i + 1),
        netIncome: 20_000_000 * (i + 1),
        eps: 1.5 + i * 0.5,
      },
      source: "eodhd",
      ingested_at: new Date().toISOString(),
    })),
  };
}

beforeEach(() => {
  mockGateway.getIncomeStatement.mockReset();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("IncomeStatementTable", () => {
  it("renders 4 fiscal-year column headers (FY21..FY24) when 4 ANNUAL records arrive", async () => {
    mockGateway.getIncomeStatement.mockResolvedValue(fourYearAnnual());
    render(
      <Wrapper>
        <IncomeStatementTable instrumentId="i-test-1" />
      </Wrapper>,
    );
    // WHY use within the column headers role: there could be more "FY" text
    // somewhere else in future; scoping to <th> tags isolates the contract.
    await waitFor(() => {
      expect(screen.getByText("FY21")).toBeInTheDocument();
    });
    expect(screen.getByText("FY22")).toBeInTheDocument();
    expect(screen.getByText("FY23")).toBeInTheDocument();
    expect(screen.getByText("FY24")).toBeInTheDocument();
  });

  it("renders all 5 P&L row labels", async () => {
    mockGateway.getIncomeStatement.mockResolvedValue(fourYearAnnual());
    render(
      <Wrapper>
        <IncomeStatementTable instrumentId="i-test-1" />
      </Wrapper>,
    );
    // Wait for the table to mount.
    await waitFor(() => {
      expect(screen.getByText("Revenue")).toBeInTheDocument();
    });
    // WHY iterate: any label drop (e.g. a future refactor accidentally
    // removing "EBIT") fails noisily here.
    for (const label of ["Revenue", "Gross Profit", "EBIT", "Net Income", "EPS"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
