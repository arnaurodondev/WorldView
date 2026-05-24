/**
 * features/portfolio/components/__tests__/AnalyticsPeriodReturnsTable.test.tsx (F-006)
 *
 * WHY: Covers the D-002 refactor (useQueries) and verifies:
 *  1. All 7 period rows render (data-testid="period-row-{PERIOD}").
 *  2. A positive return renders with a "+" prefix.
 *  3. A null/insufficient history renders "—" in the RETURN cell.
 *
 * MOCKED: useAuth, createGateway.
 * NOTE: @tanstack/react-query is real — useQueries is called normally through
 * QueryClientProvider. Mocking it would bypass the hook we're testing.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { ValueHistoryResponse } from "@/types/api";

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
const mockGetValueHistory = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getValueHistory: mockGetValueHistory,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { AnalyticsPeriodReturnsTable } from "../AnalyticsPeriodReturnsTable";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const ALL_PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "2Y", "ALL"] as const;

/** 7 history responses — all with +20% returns so we can assert the "+" prefix. */
function makeHistory(_portfolioId: string): ValueHistoryResponse {
  return {
    points: [
      { date: "2026-04-01", value: 100, cost_basis: 100, cash: 0 },
      { date: "2026-05-01", value: 120, cost_basis: 100, cash: 0 },
    ],
  };
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
  });

  it("renders all 7 period rows via data-testid", async () => {
    // WHY use data-testid: the rows are <tr data-testid="period-row-{PERIOD}">
    // inserted by the D-002 useQueries refactor. This is the canonical selector
    // that confirms each period rendered.
    mockGetValueHistory.mockResolvedValue(makeHistory("p-001"));

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      for (const p of ALL_PERIODS) {
        expect(screen.getByTestId(`period-row-${p}`)).toBeInTheDocument();
      }
    });
  });

  it("shows '+' prefixed return for a positive period", async () => {
    mockGetValueHistory.mockResolvedValue(makeHistory("p-001"));

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      // +20% return → "+20.00%". At least one row must show a positive return.
      const positiveReturns = screen.getAllByText(/^\+\d/);
      expect(positiveReturns.length).toBeGreaterThan(0);
    });
  });

  it("shows '—' when value history is insufficient (fewer than 2 points)", async () => {
    // WHY single-point response: periodReturns[i] = null when pts.length < 2,
    // so the cell should render the fallback em-dash ("—").
    mockGetValueHistory.mockResolvedValue({
      points: [{ date: "2026-05-01", value: 100, cost_basis: 100, cash: 0 }],
    } satisfies ValueHistoryResponse);

    render(wrap(<AnalyticsPeriodReturnsTable portfolioId="p-001" />));

    await waitFor(() => {
      // At least the RETURN cells should show "—" when all periods lack enough points.
      const dashes = screen.getAllByText("—");
      // WHY ≥7: each of the 7 rows contributes at least one "—" in the RETURN column.
      expect(dashes.length).toBeGreaterThanOrEqual(7);
    });
  });
});
