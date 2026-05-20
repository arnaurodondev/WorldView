/**
 * components/instrument/financials/__tests__/FlatMetricsGrid.test.tsx
 *
 * WHY THIS EXISTS: PLAN-0090 §T-C-04 pins two structural contracts on the
 * Finviz-style 3-col flat metrics grid that drives the entire Financials
 * tab (PRD-0088 §6.8.1):
 *
 *   1. test_FlatMetricsGrid_renders_valuation_label
 *      "VALUATION" — the first of 8 group headers — must render. This is
 *      the cheapest possible "did the grid mount + did the header variant
 *      of MetricCell render" smoke test.
 *
 *   2. test_FlatMetricsGrid_renders_all_8_group_labels
 *      ALL 8 group dividers (VALUATION / PROFITABILITY / GROWTH /
 *      BALANCE SHEET / CASH FLOW / DIVIDENDS / OWNERSHIP / TECHNICALS)
 *      must render. If a future refactor accidentally drops one group,
 *      that section's ~5 metric cells silently disappear with no test
 *      failure elsewhere — this assertion is the safety net.
 *
 * WHY null props for fundamentals / snapshot / technicals / shareStats /
 * dividends: the test is a label-only structural smoke check. Every cell
 * value will resolve to the em-dash placeholder when its underlying field
 * is null — but the LABELS (and the 8 group headers in particular) must
 * still render. This is also the most defensive path because it exercises
 * the null-guard branch on every cell.
 *
 * WHY a QueryClientProvider wrapper: FlatMetricsGrid uses `useQuery` to
 * read OHLCV bars from the cache (RSI/ATR derivation — see component
 * header). Without a QueryClientProvider, the hook throws at render. We
 * use a disposable client with retry:false so missing data is benign.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { FlatMetricsGrid } from "@/components/instrument/financials/FlatMetricsGrid";

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * makeQueryClient — fresh client per render so tests are isolated.
 * retry:false avoids the default 3× exponential-backoff retry on the
 * (intentionally rejecting) cache-only OHLCV fetch.
 */
function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function Wrapper({ children }: { children: ReactNode }) {
  const qc = makeQueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * renderGrid — render FlatMetricsGrid with all-null data props. Every cell
 * value resolves to "—"; every label still renders. This is the path under
 * test for both structural assertions.
 */
function renderGrid() {
  return render(
    <Wrapper>
      <FlatMetricsGrid
        instrumentId="i-test-1"
        fundamentals={null}
        snapshot={null}
        technicals={null}
        shareStats={null}
        dividends={null}
      />
    </Wrapper>,
  );
}

describe("FlatMetricsGrid", () => {
  it("renders the VALUATION group header label", () => {
    renderGrid();
    // WHY exact text "VALUATION": the label is passed verbatim to MetricCell
    // (no runtime uppercase transform); getByText matches the raw string.
    expect(screen.getByText("VALUATION")).toBeInTheDocument();
  });

  it("renders all 8 group header labels (VALUATION / PROFITABILITY / GROWTH / BALANCE SHEET / CASH FLOW / DIVIDENDS / OWNERSHIP / TECHNICALS)", () => {
    renderGrid();
    // WHY an array iteration (not 8 individual assertions): the contract is
    // "ALL 8 group headers present" — a single missed entry should fail
    // visibly. Looping makes the test self-documenting if a label changes.
    const groupLabels = [
      "VALUATION",
      "PROFITABILITY",
      "GROWTH",
      "BALANCE SHEET",
      "CASH FLOW",
      "DIVIDENDS",
      "OWNERSHIP",
      "TECHNICALS",
    ];
    for (const label of groupLabels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
