/**
 * components/portfolio/__tests__/HoldingContributionStat.test.tsx (F-003)
 *
 * WHY: Verifies the contribution bps computation, the "—" fallback when
 * the holding is not found in the portfolio, and the "—" fallback when
 * value-history has fewer than 2 points.
 *
 * MOCKED: useAuth, createGateway. TanStack Query is real (QueryClientProvider)
 * so the component's useQuery calls resolve to mock data through the gateway stub.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { HoldingsResponse, ValueHistoryResponse } from "@/types/api";

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

// ── Gateway stubs ─────────────────────────────────────────────────────────────
const mockGetHoldings = vi.fn();
const mockGetValueHistory = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getHoldings: mockGetHoldings,
    getValueHistory: mockGetValueHistory,
  })),
}));

// ── SUT import ────────────────────────────────────────────────────────────────
import { HoldingContributionStat } from "../HoldingContributionStat";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Minimal Holdings fixture: one holding for instrument i-001. */
const HOLDINGS_RESP: HoldingsResponse = {
  portfolio_id: "p-001",
  total_value: null,
  total_cost: null,
  total_unrealised_pnl: null,
  total_unrealised_pnl_pct: null,
  holdings: [
    {
      holding_id: "h-001",
      portfolio_id: "p-001",
      instrument_id: "i-001",
      entity_id: "i-001",
      ticker: "AAPL",
      name: "Apple Inc.",
      quantity: 10,
      average_cost: 150,
    },
  ],
};

/** Value history with a +10% period return (100 → 110). */
const VALUE_HISTORY_10PCT: ValueHistoryResponse = {
  points: [
    { date: "2026-04-01", value: 100, cost_basis: 100, cash: 0 },
    { date: "2026-05-01", value: 110, cost_basis: 100, cash: 0 },
  ],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingContributionStat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders '—' when the holding is not found in the portfolio", async () => {
    // WHY unknown instrumentId: tests the guard branch where
    // holdings.find(h => h.instrument_id === instrumentId) returns undefined.
    mockGetHoldings.mockResolvedValue(HOLDINGS_RESP);
    mockGetValueHistory.mockResolvedValue(VALUE_HISTORY_10PCT);

    render(
      wrap(
        <HoldingContributionStat
          portfolioId="p-001"
          instrumentId="i-UNKNOWN"
          period="1M"
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });

  it("renders '—' when value-history has fewer than 2 points", async () => {
    // WHY single-point history: periodReturn() returns null for < 2 pts,
    // so contributionBps remains null and the fallback dash shows.
    mockGetHoldings.mockResolvedValue(HOLDINGS_RESP);
    mockGetValueHistory.mockResolvedValue({
      points: [{ date: "2026-05-01", value: 100, cost_basis: 100, cash: 0 }],
    } satisfies ValueHistoryResponse);

    render(
      wrap(
        <HoldingContributionStat
          portfolioId="p-001"
          instrumentId="i-001"
          period="1M"
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });

  it("renders a numeric contribution value when holding + history both exist", async () => {
    // WHY check for bps label: the component shows "Contrib" as the label and
    // a numeric value when computation succeeds. We don't pin the exact bps
    // number (it depends on weights) — just that a non-dash value appears.
    mockGetHoldings.mockResolvedValue(HOLDINGS_RESP);
    mockGetValueHistory.mockResolvedValue(VALUE_HISTORY_10PCT);

    render(
      wrap(
        <HoldingContributionStat
          portfolioId="p-001"
          instrumentId="i-001"
          period="1M"
        />,
      ),
    );

    await waitFor(() => {
      // The label text should always appear once data is loaded.
      expect(screen.getByText("Contrib")).toBeInTheDocument();
      // A numeric bps value (positive or negative) should be present.
      // The full portfolio is one holding → weight = 1.0 → contrib = 10% × 1 × 10000 = 1000 bps.
      expect(screen.getByText(/1000(\.\d+)?\s*bps/i)).toBeInTheDocument();
    });
  });
});
