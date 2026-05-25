/**
 * components/instrument/quote/metrics/__tests__/MetricsTable.test.tsx
 *
 * WHY THIS EXISTS: MetricsTable is the right-rail Statistics panel
 * (PRD-0088 §6.7.2 / PLAN-0090 §T-B-03) — 24 metric cells (3 × MetricGrid4Col)
 * + ownership rows + analyst bar + target row.
 *
 * W5-T-15 refactor: the first 24 rows replaced by 3 × MetricGrid4Col blocks
 * (VALUATION / MARGINS / LEVERAGE+YIELD — 8 cells each). Labels are now
 * abbreviated to fit 4-col layout (e.g. "MKT CAP" not "MARKET CAP").
 *
 * Tests pin:
 *   1. test_MetricsTable_renders_MKT_CAP_label
 *      The first VALUATION cell "MKT CAP" must appear in the DOM — cheapest
 *      "table mounted and rendered" sanity check. (Replaces pre-W5 "MARKET CAP"
 *      assertion; label shortened for 4-col density layout.)
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
  it("renders the MKT CAP label in the VALUATION block (W5-T-15: 4-col grid)", () => {
    // WHY pass null fundamentals/quote: this is the "no data loaded yet"
    // path. Every value renders "—" but every static LABEL must still
    // appear — labels are the structural skeleton of the table.
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={null} />);
    // WHY "MKT CAP" (not "MARKET CAP"): W5-T-15 shortened the label to fit
    // the 4-col MetricGrid4Col layout (90px cells at 11px font). The old
    // single-column MetricRow used "MARKET CAP" which no longer exists.
    expect(screen.getByText("MKT CAP")).toBeInTheDocument();
  });
});
