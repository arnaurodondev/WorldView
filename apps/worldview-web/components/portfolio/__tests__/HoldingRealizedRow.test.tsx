/**
 * components/portfolio/__tests__/HoldingRealizedRow.test.tsx
 *
 * WHY THIS EXISTS: HoldingRealizedRow is the first component in
 * HoldingDetailPanel — it shows per-instrument ST/LT realized P&L. Tests pin:
 *  1. Renders "—" when the query returns an error.
 *  2. Renders ST/LT values when the query returns a successful response.
 *  3. Shows zeros when the instrument has no realized P&L (not in breakdown).
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth  → stub token so the component doesn't gate on real auth.
 *  - @/lib/gateway    → stub getRealizedPnL so we control responses per-test.
 *
 * PATTERN NOTE: we mock @tanstack/react-query for granular control over the
 * query status (error vs success vs loading) per-test. This avoids having to
 * configure TanStack Query's retry/stale machinery, giving faster and more
 * deterministic tests.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { RealizedPnLResponse } from "@/types/api";

// ── Auth stub ────────────────────────────────────────────────────────────────
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "test@example.com", name: "Test User", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway stub ─────────────────────────────────────────────────────────────
// WHY a named variable: per-test overrides call mockGetRealizedPnL.mockResolvedValue()
// or mockGetRealizedPnL.mockRejectedValue() without re-declaring.
const mockGetRealizedPnL = vi.fn();

const mockGateway = {
  getRealizedPnL: mockGetRealizedPnL,
};

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => mockGateway),
}));

// WHY also mock api-client: the SUT now uses useApiClient() instead of
// createGateway() (D1 remediation). The createGateway stub is kept for
// backward compatibility with any indirect imports.
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

// ── SUT import ───────────────────────────────────────────────────────────────
import { HoldingRealizedRow } from "../HoldingRealizedRow";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  // WHY retry: false — see HoldingDetailPanel test for the same rationale.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Base RealizedPnLResponse fixture with one instrument in the breakdown. */
const BASE_PNL_RESPONSE: RealizedPnLResponse = {
  portfolio_id: "p-001",
  from: "2026-01-01",
  to: "2026-05-23",
  total_realized: 500.0,
  realized_long_term: 300.0,
  realized_short_term: 200.0,
  count: 3,
  breakdown_by_instrument: [
    {
      instrument_id: "i-001",
      ticker: "AAPL",
      realized: 500.0, // 100% of portfolio P&L from this instrument
      count: 3,
    },
  ],
  currency: "USD",
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HoldingRealizedRow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders '—' when query returns an error", async () => {
    // WHY reject (not pending): we want to test the error display path.
    // The component should show "—" rather than crashing or showing stale data.
    mockGetRealizedPnL.mockRejectedValue(new Error("Network error"));

    render(
      wrap(
        <HoldingRealizedRow portfolioId="p-001" instrumentId="i-001" />,
      ),
    );

    // Wait for the query to settle into the error state.
    // WHY waitFor: TanStack Query is asynchronous — the error state is not
    // visible on the first synchronous render tick.
    await waitFor(() => {
      // The "Realized" label should still be present.
      expect(screen.getByText("Realized")).toBeInTheDocument();
      // The em-dash ("—") should appear as the fallback value.
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });

  it("renders ST and LT values when query returns success", async () => {
    mockGetRealizedPnL.mockResolvedValue(BASE_PNL_RESPONSE);

    render(
      wrap(
        <HoldingRealizedRow portfolioId="p-001" instrumentId="i-001" />,
      ),
    );

    await waitFor(() => {
      // The section label should be present.
      expect(screen.getByText("Realized")).toBeInTheDocument();

      // WHY getAllByText: there may be multiple matching text nodes when ST
      // and LT labels are rendered. We use a partial text matcher to find
      // each independently.
      const stEl = screen.getByText((content) => content.startsWith("ST:"));
      const ltEl = screen.getByText((content) => content.startsWith("LT:"));

      expect(stEl).toBeInTheDocument();
      expect(ltEl).toBeInTheDocument();
    });
  });

  it("renders zeros when instrument has no realized P&L (not in breakdown)", async () => {
    // The response has NO entry for instrument i-999 in breakdown_by_instrument.
    mockGetRealizedPnL.mockResolvedValue(BASE_PNL_RESPONSE);

    render(
      wrap(
        // WHY different instrumentId: we test the "not found in breakdown" path.
        <HoldingRealizedRow portfolioId="p-001" instrumentId="i-999" />,
      ),
    );

    await waitFor(() => {
      // Both ST and LT should show $0.00 when the instrument has no realized P&L.
      const stEl = screen.getByText("ST: $0.00");
      const ltEl = screen.getByText("LT: $0.00");

      expect(stEl).toBeInTheDocument();
      expect(ltEl).toBeInTheDocument();
    });
  });
});
