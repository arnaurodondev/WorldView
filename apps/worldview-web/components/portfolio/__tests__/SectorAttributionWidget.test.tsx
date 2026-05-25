/**
 * components/portfolio/__tests__/SectorAttributionWidget.test.tsx
 *
 * WHY THIS EXISTS: SectorAttributionWidget has two view modes (bars / donut)
 * and a `prices_stale` badge. The donut toggle is a stateful interaction that
 * must not regress — switching to donut mode must hide the bar rows, and the
 * toggle button must flip its aria-pressed label.
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth      → stub token.
 *  - @/lib/gateway        → stub getSectorAttribution so we control responses.
 *
 * DATA SOURCE: mocked SectorAttributionResponse
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Sector Attribution widget, Wave F-3 donut
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Auth stub ────────────────────────────────────────────────────────────────

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

const mockGetSectorAttribution = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getSectorAttribution: mockGetSectorAttribution,
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────

import { SectorAttributionWidget } from "../SectorAttributionWidget";

// ── Helpers ──────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Baseline SectorAttributionResponse — 3 GICS sectors, prices live.
const BASE_SECTOR_DATA = {
  portfolio_id: "p1",
  buckets: [
    { sector: "Technology", holding_count: 4, market_value: 50000, sector_weight_pct: 50, sector_day_pnl: 320 },
    { sector: "Healthcare", holding_count: 2, market_value: 30000, sector_weight_pct: 30, sector_day_pnl: -120 },
    { sector: "Financials",  holding_count: 2, market_value: 20000, sector_weight_pct: 20, sector_day_pnl: 85 },
  ],
  covered_pct: 1.0,
  prices_stale: false,
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("SectorAttributionWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders loading state while query is pending", () => {
    mockGetSectorAttribution.mockReturnValue(new Promise(() => {}));

    render(wrap(<SectorAttributionWidget portfolioId="p1" />));

    expect(screen.getByTestId("sector-attribution-widget")).toBeInTheDocument();

    // WHY data-testid: Tailwind classes are not computed in jsdom.
    // The skeleton container has data-testid="sector-skeleton".
    expect(screen.getByTestId("sector-skeleton")).toBeInTheDocument();
  });

  it("renders sector names in bar mode", async () => {
    mockGetSectorAttribution.mockResolvedValue(BASE_SECTOR_DATA);

    render(wrap(<SectorAttributionWidget portfolioId="p1" />));

    await waitFor(() => {
      // All 3 sector names should be visible as text in bar rows.
      expect(screen.getByText("Technology")).toBeInTheDocument();
      expect(screen.getByText("Healthcare")).toBeInTheDocument();
      expect(screen.getByText("Financials")).toBeInTheDocument();
    });

    // Bar rows should be present (data-testid="sector-row").
    const rows = screen.getAllByTestId("sector-row");
    expect(rows).toHaveLength(3);
  });

  it("clicking the donut toggle switches to donut view", async () => {
    mockGetSectorAttribution.mockResolvedValue(BASE_SECTOR_DATA);

    render(wrap(<SectorAttributionWidget portfolioId="p1" />));

    await waitFor(() => {
      expect(screen.getByTestId("donut-toggle")).toBeInTheDocument();
    });

    // Initial state: bar mode — toggle shows "[○]", sector rows are visible.
    const toggleBtn = screen.getByTestId("donut-toggle");
    expect(toggleBtn.textContent).toBe("[○]");
    expect(toggleBtn).toHaveAttribute("aria-pressed", "false");

    // Click to switch to donut mode.
    fireEvent.click(toggleBtn);

    await waitFor(() => {
      // WHY check aria-pressed: it is the reliable DOM indicator for toggle state,
      // independent of which CSS class the button currently uses.
      expect(toggleBtn).toHaveAttribute("aria-pressed", "true");
      // The toggle label flips to "[■]" to indicate "donut active".
      expect(toggleBtn.textContent).toBe("[■]");
    });

    // Donut view container should now be visible.
    expect(screen.getByTestId("donut-view")).toBeInTheDocument();

    // Bar rows should no longer be present — donut replaces them.
    expect(screen.queryAllByTestId("sector-row")).toHaveLength(0);
  });

  it("shows 'prices delayed' badge when prices_stale is true", async () => {
    mockGetSectorAttribution.mockResolvedValue({
      ...BASE_SECTOR_DATA,
      prices_stale: true,
    });

    render(wrap(<SectorAttributionWidget portfolioId="p1" />));

    await waitFor(() => {
      // WHY data-testid: the badge is a small <span> — finding it by text is
      // equally valid, but the testid makes the intent explicit.
      expect(screen.getByTestId("prices-stale-badge")).toBeInTheDocument();
    });

    const badge = screen.getByTestId("prices-stale-badge");
    expect(badge.textContent).toContain("prices delayed");
    // WHY check colour class: the badge must be amber (#FFB000) to signal
    // "degraded, not broken" — a red badge would suggest an error state.
    expect(badge.className).toContain("text-[#FFB000]");
  });
});
