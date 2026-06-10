/**
 * FinancialStatementsPanel.test.tsx — statements block on the Financials tab
 * (Round-2 item 2).
 *
 * CONTRACTS PINNED:
 *   1. All three mini-tables render from a bundle whose `fundamentals` leg
 *      carries income/balance/cash-flow section records.
 *   2. The Annual / TTM toggle switches the derivation (column captions move
 *      from FY-labels to TTM) — toggle behaviour required by the scope.
 *   3. Empty bundle leg → named empty state (never a silent blank).
 *   4. YoY delta cells colour-code by direction (text-positive/-negative).
 *
 * WHY mock useFinancialsBundle (not the gateway): the panel's single data
 * dependency is the bundle hook (which dedupes with useFinancialsTabData in
 * production). Mocking at the hook seam avoids wiring auth + gateway + cache
 * hydration that other suites already cover.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { FundamentalsRecord } from "@/types/api";

// ── Hook mock ────────────────────────────────────────────────────────────────

const mockBundle = vi.hoisted(() => ({
  state: {
    data: undefined as unknown,
    isLoading: false,
  },
}));

vi.mock("@/components/instrument/hooks/useFinancialsBundle", () => ({
  useFinancialsBundle: () => mockBundle.state,
}));

// eslint-disable-next-line import/first
import { FinancialStatementsPanel } from "@/components/instrument/financials/statements/FinancialStatementsPanel";

// ── Fixtures ─────────────────────────────────────────────────────────────────

let idCounter = 0;
function rec(
  section: string,
  periodType: "ANNUAL" | "QUARTERLY",
  periodEnd: string,
  data: Record<string, unknown>,
): FundamentalsRecord {
  idCounter += 1;
  return {
    id: `r${idCounter}`,
    security_id: "sec-1",
    section,
    period_end: periodEnd,
    period_type: periodType,
    data,
    source: "eodhd",
    ingested_at: "2026-06-01T00:00:00Z",
  } as FundamentalsRecord;
}

/** Quarter-end dates for 8 trailing quarters (oldest → newest). */
const QUARTER_ENDS = [
  "2024-09-30T00:00:00Z",
  "2024-12-31T00:00:00Z",
  "2025-03-31T00:00:00Z",
  "2025-06-30T00:00:00Z",
  "2025-09-30T00:00:00Z",
  "2025-12-31T00:00:00Z",
  "2026-03-31T00:00:00Z",
  "2026-06-30T00:00:00Z",
];

function fullBundle() {
  const records: FundamentalsRecord[] = [
    // Income: two ANNUAL years (declining revenue → negative YoY) + 8 quarters.
    rec("income_statement", "ANNUAL", "2024-09-30T00:00:00Z", { totalRevenue: 200e9 }),
    rec("income_statement", "ANNUAL", "2025-09-30T00:00:00Z", { totalRevenue: 150e9 }),
    ...QUARTER_ENDS.map((end, i) =>
      rec("income_statement", "QUARTERLY", end, { totalRevenue: (50 + i) * 1e9 }),
    ),
    // Balance sheet: quarterly-only (live DB state).
    ...QUARTER_ENDS.map((end, i) =>
      rec("balance_sheet", "QUARTERLY", end, { totalAssets: (300 + i * 10) * 1e9 }),
    ),
    // Cash flow: quarterly-only, rising OCF → positive YoY.
    ...QUARTER_ENDS.map((end, i) =>
      rec("cash_flow", "QUARTERLY", end, {
        totalCashFromOperatingActivities: (10 + i) * 1e9,
      }),
    ),
  ];
  return { fundamentals: { security_id: "sec-1", records } };
}

beforeEach(() => {
  mockBundle.state = { data: fullBundle(), isLoading: false };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("FinancialStatementsPanel", () => {
  it("renders all three statement mini-tables with row labels", () => {
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    expect(screen.getByText("INCOME STATEMENT")).toBeInTheDocument();
    expect(screen.getByText("BALANCE SHEET")).toBeInTheDocument();
    expect(screen.getByText("CASH FLOW")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Total Assets")).toBeInTheDocument();
    expect(screen.getByText("Operating CF")).toBeInTheDocument();
  });

  it("defaults to ANNUAL: income columns carry FY captions", () => {
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    expect(screen.getByText("FY25")).toBeInTheDocument();
    expect(screen.getByText("FY24")).toBeInTheDocument();
    // No TTM caption in annual mode (income table).
    expect(screen.queryByText("PRIOR TTM")).not.toBeInTheDocument();
  });

  it("toggle to TTM switches the derivation (TTM captions appear)", () => {
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    // Radix TabsTrigger responds to mouseDown-driven activation; fireEvent.click
    // dispatches the full pointer sequence jsdom supports.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "TTM" }));
    fireEvent.click(screen.getByRole("tab", { name: "TTM" }));
    // "TTM" appears on the trigger AND as the current-column caption of the
    // income + cash-flow tables → at least 3 occurrences post-toggle.
    expect(screen.getAllByText("TTM").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("PRIOR TTM").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("FY25")).not.toBeInTheDocument();
  });

  it("colour-codes YoY deltas by direction", () => {
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    // Income FY25 revenue 150B vs FY24 200B → -25.0% (negative token).
    const negDelta = screen.getByText("-25.0%");
    expect(negDelta.className).toContain("text-negative");
    // Cash flow quarter-sums rise (54B → 38B prior) → positive token.
    const posDeltas = document.querySelectorAll(".text-positive");
    expect(posDeltas.length).toBeGreaterThan(0);
  });

  it("renders the named empty state when the fundamentals leg is null", () => {
    mockBundle.state = { data: { fundamentals: null }, isLoading: false };
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    expect(screen.getByText("No financial statements")).toBeInTheDocument();
    // The toggle still renders (the section header is structural).
    expect(screen.getByText("FINANCIAL STATEMENTS")).toBeInTheDocument();
  });

  it("shows the skeleton only during the bundle's cold first load", () => {
    mockBundle.state = { data: undefined, isLoading: true };
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    expect(screen.getByTestId("statements-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("FINANCIAL STATEMENTS")).not.toBeInTheDocument();
  });

  // ── Round-4 hardening (item 1b): error ≠ empty ─────────────────────────────

  it("renders a named error with Retry when the bundle request fails (NOT the empty state)", () => {
    const refetch = vi.fn();
    // WHY the never-cast: the hook mock's state literal only declares the
    // fields the panel destructures; isError/refetch are Round-4 additions.
    mockBundle.state = {
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as never;
    render(<FinancialStatementsPanel instrumentId="i-1" />);
    // A failed FETCH must not claim the instrument "has no statements" —
    // that's a data statement the client cannot honestly make here.
    expect(screen.getByTestId("statements-fetch-error")).toBeInTheDocument();
    expect(screen.queryByText("No financial statements")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
