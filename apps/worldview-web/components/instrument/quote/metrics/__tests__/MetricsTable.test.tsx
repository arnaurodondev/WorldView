/**
 * components/instrument/quote/metrics/__tests__/MetricsTable.test.tsx
 *
 * WHY THIS EXISTS: MetricsTable is the right-rail Statistics panel
 * (PRD-0088 §6.7.2 / PLAN-0090 §T-B-03) — 26 rows + 5 dividers stitched
 * from four S9 sub-resources. PLAN-0090 §T-B-05 pins ONE smoke contract
 * on the table itself:
 *
 *   1. test_MetricsTable_renders_MARKET_CAP_label
 *      The first VALUATION row label "MARKET CAP" must be present in the
 *      DOM. That is the cheapest possible "did the table mount and render
 *      its labels" sanity check; threshold colouring + per-row formatting
 *      are covered by the unit tests on MetricRow, WeekRangeBar, and
 *      AnalystMiniBar (and by integration tests downstream).
 *
 * WHY mock useMetricsTableData (not the gateway): the hook is the single
 * data dependency MetricsTable has (PLAN-0090 forbids inline useQuery).
 * Mocking it avoids wiring a QueryClientProvider, an AuthContext, AND a
 * fetch stub for three S9 endpoints — none of which are under test here.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// WHY mock BEFORE import of MetricsTable: vi.mock is hoisted, but we still
// declare the factory up here for readability. The mock returns empty
// sub-resources so MetricsTable falls back to "—" everywhere — that is the
// path we want for a label-only smoke test (no need to fabricate
// FundamentalsSnapshot / TechnicalsData / ShareStatisticsData shapes).
vi.mock("@/components/instrument/hooks/useMetricsTableData", () => ({
  useMetricsTableData: () => ({
    snapshot: undefined,
    technicals: undefined,
    shareStats: undefined,
    isLoading: false,
    isError: false,
  }),
}));

import { MetricsTable } from "@/components/instrument/quote/metrics/MetricsTable";

describe("MetricsTable", () => {
  it("renders the MARKET CAP label in the VALUATION section", () => {
    // WHY pass null fundamentals/quote: this is the "no data loaded yet"
    // path. Every value renders "—" but every static LABEL must still
    // appear — labels are the structural skeleton of the table.
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={null} />);
    // WHY exact string "MARKET CAP" (uppercase): MetricLabel renders the
    // text uppercase via CSS, but the literal string passed in is already
    // "MARKET CAP" (see MetricsTable.tsx). getByText matches the raw text
    // content, which preserves the uppercase form.
    expect(screen.getByText("MARKET CAP")).toBeInTheDocument();
  });
});
