/**
 * components/portfolio/__tests__/SectorAllocationDonut.test.tsx (R2 sprint)
 *
 * WHY: the donut is the page-level allocation summary AND the entry point
 * for the holdings sector filter. These tests cover:
 *   1. Legend rows render sector / weight% / value from the S9 breakdown.
 *   2. Center label shows the total allocated value.
 *   3. Clicking a legend row toggles the filter callback (select → clear).
 *   4. The aggregated "Other" row is informational (disabled, no callback).
 *   5. Error / empty named states (never a fabricated allocation).
 *   6. Partial-pricing coverage hint when covered_pct < 0.99.
 *
 * WHY legend rows (not SVG slices) drive the interaction tests: the Pie
 * cells and legend rows share the same handleSelect handler, and DOM
 * buttons are deterministic in jsdom while recharts SVG hit-areas are not.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { SectorBreakdownResponse } from "@/types/api";

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
const mockGetSectorBreakdown = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getSectorBreakdown: mockGetSectorBreakdown,
  })),
}));

// ── SUT import (after mocks) ─────────────────────────────────────────────────
import { SectorAllocationDonut } from "../SectorAllocationDonut";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const BREAKDOWN: SectorBreakdownResponse = {
  portfolio_id: "p-1",
  segments: [
    { sector: "Information Technology", weight: 0.5, count: 3, market_value: 50_000 },
    { sector: "Energy", weight: 0.3, count: 2, market_value: 30_000 },
    { sector: "Health Care", weight: 0.2, count: 1, market_value: 20_000 },
  ],
  covered_pct: 1,
  as_of: "2026-06-10",
};

/** 10 sectors — forces the top-8 + "Other" aggregation path. */
const MANY_SECTORS: SectorBreakdownResponse = {
  portfolio_id: "p-1",
  segments: Array.from({ length: 10 }, (_, i) => ({
    sector: `Sector ${i + 1}`,
    weight: (10 - i) / 55, // descending weights summing to 1
    count: 1,
    market_value: (10 - i) * 1000,
  })),
  covered_pct: 1,
  as_of: "2026-06-10",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("SectorAllocationDonut", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders legend rows with sector, weight % and value", async () => {
    mockGetSectorBreakdown.mockResolvedValue(BREAKDOWN);
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByTestId("donut-legend-Information Technology")).toBeInTheDocument();
    });
    // Weight % and compact value per legend row.
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("$50.0K")).toBeInTheDocument();
    expect(screen.getByText("Energy")).toBeInTheDocument();
    expect(screen.getByText("30.0%")).toBeInTheDocument();
  });

  it("shows the total allocated value in the donut center", async () => {
    mockGetSectorBreakdown.mockResolvedValue(BREAKDOWN);
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );
    await waitFor(() => {
      // 50k + 30k + 20k = $100.0K total.
      expect(screen.getByTestId("donut-total")).toHaveTextContent("$100.0K");
    });
  });

  it("clicking a sector selects it; clicking the selected sector clears", async () => {
    mockGetSectorBreakdown.mockResolvedValue(BREAKDOWN);
    const onSelect = vi.fn();

    const { rerender } = render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={onSelect}
        />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId("donut-legend-Energy")).toBeInTheDocument();
    });

    // First click → filter by Energy.
    fireEvent.click(screen.getByTestId("donut-legend-Energy"));
    expect(onSelect).toHaveBeenCalledWith("Energy");

    // Re-render with Energy selected (parent owns the state) → aria-pressed
    // reflects the toggle, and a second click CLEARS (null).
    rerender(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector="Energy"
          onSelectSector={onSelect}
        />,
      ),
    );
    const row = screen.getByTestId("donut-legend-Energy");
    expect(row).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(row);
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("aggregates past 8 sectors into a disabled 'Other' row", async () => {
    mockGetSectorBreakdown.mockResolvedValue(MANY_SECTORS);
    const onSelect = vi.fn();
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={onSelect}
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByTestId("donut-legend-Other")).toBeInTheDocument();
    });
    // "+2 more" = sectors 9 and 10 aggregated.
    expect(screen.getByText("+2 more")).toBeInTheDocument();
    // Disabled — clicking must NOT fire the filter callback (an "Other"
    // filter spanning several real sectors would be ambiguous).
    const other = screen.getByTestId("donut-legend-Other");
    expect(other).toBeDisabled();
    fireEvent.click(other);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("renders the named error state when the endpoint fails", async () => {
    mockGetSectorBreakdown.mockRejectedValue(new Error("boom"));
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId("donut-empty-state")).toHaveTextContent(
        "Sector data unavailable",
      );
    });
  });

  it("renders the named empty state for a portfolio with no segments", async () => {
    mockGetSectorBreakdown.mockResolvedValue({
      portfolio_id: "p-1",
      segments: [],
      covered_pct: 0,
      as_of: "2026-06-10",
    } satisfies SectorBreakdownResponse);
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId("donut-empty-state")).toHaveTextContent(
        "No sector data yet",
      );
    });
  });

  it("shows the ~coverage hint when covered_pct < 0.99", async () => {
    mockGetSectorBreakdown.mockResolvedValue({
      ...BREAKDOWN,
      covered_pct: 0.8,
    });
    render(
      wrap(
        <SectorAllocationDonut
          portfolioId="p-1"
          selectedSector={null}
          onSelectSector={vi.fn()}
        />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId("donut-coverage-hint")).toHaveTextContent("~80%");
    });
  });
});
