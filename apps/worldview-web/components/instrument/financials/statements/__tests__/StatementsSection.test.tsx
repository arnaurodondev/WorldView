/**
 * StatementsSection.test.tsx — statements block on the Financials tab
 * (Wave-2 redesign; replaces FinancialStatementsPanel.test.tsx).
 *
 * PORTED CONTRACTS (from the deleted FinancialStatementsPanel suite):
 *   1. All three statement tables render from a bundle whose `fundamentals`
 *      leg carries income/balance/cash-flow section records.
 *   2. ANNUAL default: income columns carry FY captions (no TTM captions).
 *   3. The mode toggle switches the derivation (TTM captions appear).
 *   4. YoY delta cells colour-code by direction (text-positive/-negative).
 *   5. Cold first load → shape-matched skeleton, no header chrome.
 *   6. Total failure → named error with Retry (NOT the empty state).
 *   Plus, ported from the deleted IncomeStatementTable suite:
 *   7. The income table renders one column per fiscal year + all row labels.
 *
 * NEW Wave-2 CONTRACTS:
 *   8. QUARTERLY mode renders quarter captions (Qx'yy).
 *   9. Wave-1 fallback: a null bundle leg now PROBES the dedicated
 *      endpoints — records found → tables render; genuinely empty → the
 *      named empty state (which is finally honest).
 *
 * MOCK SEAMS: useFinancialsBundle (the panel's primary data dependency,
 * same seam the old suite used) + apiFetch (the Wave-1 fallback fetchers).
 * A real QueryClientProvider wraps each render because the fallback path
 * uses live useQuery instances.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { FundamentalsRecord } from "@/types/api";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockBundle = vi.hoisted(() => ({
  state: {
    data: undefined as unknown,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  },
}));

vi.mock("@/components/instrument/hooks/useFinancialsBundle", () => ({
  useFinancialsBundle: () => mockBundle.state,
}));

// apiFetch backs the Wave-1 fallback fetchers (income/balance/cash-flow).
const mockApiFetch = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/_client", async (importOriginal) => {
  // Keep the real exports (GatewayError etc.) — only apiFetch is stubbed.
  const actual = await importOriginal<typeof import("@/lib/api/_client")>();
  return { ...actual, apiFetch: mockApiFetch };
});

vi.mock("@/lib/api-client", () => ({
  useAccessToken: () => "test-token",
}));

// eslint-disable-next-line import/first
import { StatementsSection } from "@/components/instrument/financials/statements/StatementsSection";

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

function allRecords(): FundamentalsRecord[] {
  return [
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
}

function fullBundle() {
  return { fundamentals: { security_id: "sec-1", records: allRecords() } };
}

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderSection() {
  return render(
    <Wrapper>
      <StatementsSection instrumentId="i-1" />
    </Wrapper>,
  );
}

beforeEach(() => {
  mockBundle.state = { data: fullBundle(), isLoading: false, isError: false, refetch: vi.fn() };
  mockApiFetch.mockReset();
});

/** Activate a Radix tab trigger (mouseDown-driven activation in jsdom). */
function activateTab(name: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name }));
  fireEvent.click(screen.getByRole("tab", { name }));
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("StatementsSection", () => {
  it("renders all three statement tables with row labels", () => {
    renderSection();
    expect(screen.getByText("INCOME STATEMENT")).toBeInTheDocument();
    expect(screen.getByText("BALANCE SHEET")).toBeInTheDocument();
    expect(screen.getByText("CASH FLOW")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("Total Assets")).toBeInTheDocument();
    expect(screen.getByText("Operating CF")).toBeInTheDocument();
  });

  it("renders the full income row ladder (ported from IncomeStatementTable)", () => {
    renderSection();
    // The old standalone P&L pinned its 5 labels; the upgraded ladder is 6
    // (EPS dropped — never ingested; R&D + EBITDA added from live data).
    for (const label of [
      "Revenue",
      "Gross Profit",
      "Operating Income",
      "EBITDA",
      "R&D Expense",
      "Net Income",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("defaults to ANNUAL: income columns carry FY captions", () => {
    renderSection();
    expect(screen.getByText("FY25")).toBeInTheDocument();
    expect(screen.getByText("FY24")).toBeInTheDocument();
    // No TTM caption in annual mode.
    expect(screen.queryByText("PRIOR TTM")).not.toBeInTheDocument();
  });

  it("toggle to TTM switches the derivation (TTM captions appear)", () => {
    renderSection();
    activateTab("TTM");
    // "TTM" appears on the trigger AND as the current-column caption of the
    // income + cash-flow tables → at least 3 occurrences post-toggle.
    expect(screen.getAllByText("TTM").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("PRIOR TTM").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("FY25")).not.toBeInTheDocument();
  });

  it("toggle to QUARTERLY renders 8 quarter captions (Wave-2)", () => {
    renderSection();
    activateTab("Quarterly");
    // Oldest + newest quarter captions present on the income table (each
    // caption repeats per table → getAllByText).
    expect(screen.getAllByText("Q3'24").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Q2'26").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("FY25")).not.toBeInTheDocument();
  });

  it("colour-codes YoY deltas by direction", () => {
    renderSection();
    // Income FY25 revenue 150B vs FY24 200B → -25.0% (negative token).
    const negDelta = screen.getByText("-25.0%");
    expect(negDelta.className).toContain("text-negative");
    // Cash flow quarter-sums rise → at least one positive token.
    expect(document.querySelectorAll(".text-positive").length).toBeGreaterThan(0);
  });

  it("shows the skeleton only during the bundle's cold first load", () => {
    mockBundle.state = { data: undefined, isLoading: true, isError: false, refetch: vi.fn() };
    renderSection();
    expect(screen.getByTestId("statements-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("FINANCIAL STATEMENTS")).not.toBeInTheDocument();
  });

  // ── Wave-1 fallback path (null bundle leg ≠ no data any more) ──────────────

  it("probes the dedicated endpoints when the bundle leg is null and renders their records", async () => {
    mockBundle.state = { data: { fundamentals: null }, isLoading: false, isError: false, refetch: vi.fn() };
    // Each fallback endpoint returns its own section slice.
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes("income-statement")) {
        return Promise.resolve({
          security_id: "sec-1",
          records: [
            rec("income_statement", "ANNUAL", "2025-09-30T00:00:00Z", { totalRevenue: 1e9 }),
          ],
        });
      }
      return Promise.resolve({ security_id: "sec-1", records: [] });
    });
    renderSection();
    await waitFor(() => {
      expect(screen.getByText("INCOME STATEMENT")).toBeInTheDocument();
    });
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    // All three endpoints were probed.
    const paths = mockApiFetch.mock.calls.map((c) => c[0] as string);
    expect(paths.some((p) => p.includes("/balance-sheet"))).toBe(true);
    expect(paths.some((p) => p.includes("/cash-flow"))).toBe(true);
  });

  it("renders the named empty state only when the fallback confirms zero records", async () => {
    mockBundle.state = { data: { fundamentals: null }, isLoading: false, isError: false, refetch: vi.fn() };
    mockApiFetch.mockResolvedValue({ security_id: "sec-1", records: [] });
    renderSection();
    await waitFor(() => {
      expect(screen.getByText("No financial statements")).toBeInTheDocument();
    });
    // The section header chrome still renders (structural).
    expect(screen.getByText("FINANCIAL STATEMENTS")).toBeInTheDocument();
  });

  it("renders a named error with Retry when bundle AND fallback endpoints fail (NOT the empty state)", async () => {
    const refetch = vi.fn();
    mockBundle.state = { data: undefined, isLoading: false, isError: true, refetch };
    mockApiFetch.mockRejectedValue(new Error("downstream 503"));
    renderSection();
    // A failed FETCH must not claim the instrument "has no statements".
    await waitFor(() => {
      expect(screen.getByTestId("statements-fetch-error")).toBeInTheDocument();
    });
    expect(screen.queryByText("No financial statements")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
