/**
 * features/portfolio/components/__tests__/AnalyticsAttributionTable.test.tsx
 *
 * WHY THESE TESTS EXIST: AnalyticsAttributionTable is the attribution component
 * that sorts by |contrib_bps| and caps at 10 rows. Tests pin:
 *  1. Renders only the top 10 rows when more than 10 rows are returned.
 *  2. Shows "Attribution unavailable" on error (isError=true or data=null).
 *  3. Sorts by absolute CONTRIB bps descending (largest movers first).
 *
 * MOCKED MODULES:
 *  - @/hooks/useAuth  → stub token so the component never gates on auth.
 *  - @/lib/gateway    → stub getAttribution so we control responses.
 *
 * WHAT IS NOT TESTED:
 *  - CSS colour classes (Tailwind not computed in jsdom).
 *  - The gateway error handling / retry logic (gateway module concern).
 *  - Different dimensions (holding/sector/asset_class) — the component is
 *    dimension-agnostic; the rendering path is identical for all three.
 *
 * DATA SOURCE: mocked AttributionResponse
 * DESIGN REFERENCE: docs/designs/0089/04-portfolio-detail.md §5.3
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

const mockGetAttribution = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    getAttribution: mockGetAttribution,
  })),
}));

// ── SUT import ───────────────────────────────────────────────────────────────

import { AnalyticsAttributionTable } from "../AnalyticsAttributionTable";

// ── Helpers ───────────────────────────────────────────────────────────────────

function wrap(children: ReactNode) {
  // WHY retry: false — without this TanStack Query retries 3× before error state.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// Build n attribution rows with descending contrib_bps values.
// WHY factory: allows tests to create controlled data sets without repeating
// the row shape. Negative indices produce negative contrib_bps (detractors).
function makeRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    name: `TICKER${i + 1}`,
    weight: 0.05,
    period_return: 0.1 + i * 0.01,
    // WHY descending absolute value: tests rely on the sort order being
    // largest |contrib_bps| first. We assign values in ascending order so
    // the expected sort reverses them (row 14 = highest absolute value).
    contrib_bps: (i + 1) * 10, // 10, 20, 30, ... — last row has largest value
  }));
}

// Build rows with mixed positive/negative contrib to test absolute-value sort.
function makeMixedRows() {
  return [
    { name: "SMALL_POS",  weight: 0.05, period_return: 0.01, contrib_bps: 10 },
    { name: "LARGE_NEG",  weight: 0.10, period_return: -0.20, contrib_bps: -300 },
    { name: "LARGE_POS",  weight: 0.15, period_return: 0.25, contrib_bps: 250 },
    { name: "MEDIUM_POS", weight: 0.08, period_return: 0.10, contrib_bps: 50 },
    { name: "MEDIUM_NEG", weight: 0.05, period_return: -0.05, contrib_bps: -80 },
  ];
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("AnalyticsAttributionTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Test 1: Renders top 10 rows max.
  it("renders top 10 rows max when API returns more than 10 rows", async () => {
    // Return 14 rows — the component should cap at 10.
    const rows = makeRows(14);
    mockGetAttribution.mockResolvedValue({
      portfolio_id: "p1",
      period: "YTD",
      dimension: "holding",
      rows,
    });

    render(
      wrap(
        <AnalyticsAttributionTable
          portfolioId="p1"
          period="YTD"
          dimension="holding"
        />,
      ),
    );

    await waitFor(() => {
      // WHY check for TICKER1 (the smallest in our factory, but after absolute-
      // value sort the last 10 of 14 rows are the biggest). The key assertion
      // is that only 10 table rows appear inside <tbody>.
      // We look for TICKER5 (the 5th smallest) to NOT be present — because
      // after sorting by |contrib_bps| descending, rows 14→5 appear, so
      // TICKER1 through TICKER4 are cut off (they have contrib_bps 10–40,
      // the 4 smallest values among 14).
      expect(screen.queryByText("TICKER1")).not.toBeInTheDocument();
      expect(screen.queryByText("TICKER2")).not.toBeInTheDocument();
      expect(screen.queryByText("TICKER3")).not.toBeInTheDocument();
      expect(screen.queryByText("TICKER4")).not.toBeInTheDocument();
      // TICKER14 through TICKER5 (the 10 largest) should be present.
      expect(screen.getByText("TICKER14")).toBeInTheDocument();
      expect(screen.getByText("TICKER5")).toBeInTheDocument();
    });
  });

  // Test 2: Shows "Attribution unavailable" on error.
  it("shows 'Attribution unavailable' when getAttribution throws", async () => {
    // WHY mockRejectedValue: simulates the endpoint returning a 404 or network
    // error. The component's error state should render the "unavailable" message.
    mockGetAttribution.mockRejectedValue(new Error("Not found"));

    render(
      wrap(
        <AnalyticsAttributionTable
          portfolioId="p1"
          period="YTD"
          dimension="holding"
        />,
      ),
    );

    await waitFor(() => {
      // WHY data-testid: pins the test to the semantic element, not the text.
      // Text wording may change; the data-testid is the stable contract.
      expect(screen.getByTestId("attribution-unavailable")).toBeInTheDocument();
      // Also verify the user-facing message.
      expect(screen.getByText("Attribution unavailable")).toBeInTheDocument();
    });
  });

  // Test 3: Sorts by absolute CONTRIB descending.
  it("sorts rows by absolute contrib_bps descending", async () => {
    // Mixed positive and negative rows. Expected sort order by |contrib_bps|:
    //   1. LARGE_NEG  → |−300| = 300
    //   2. LARGE_POS  → |+250| = 250
    //   3. MEDIUM_NEG → |−80|  = 80
    //   4. MEDIUM_POS → |+50|  = 50
    //   5. SMALL_POS  → |+10|  = 10
    mockGetAttribution.mockResolvedValue({
      portfolio_id: "p1",
      period: "YTD",
      dimension: "holding",
      rows: makeMixedRows(),
    });

    render(
      wrap(
        <AnalyticsAttributionTable
          portfolioId="p1"
          period="YTD"
          dimension="holding"
        />,
      ),
    );

    await waitFor(() => {
      // All 5 rows should appear (< 10 cap).
      expect(screen.getByText("LARGE_NEG")).toBeInTheDocument();
      expect(screen.getByText("LARGE_POS")).toBeInTheDocument();
      expect(screen.getByText("MEDIUM_NEG")).toBeInTheDocument();
      expect(screen.getByText("MEDIUM_POS")).toBeInTheDocument();
      expect(screen.getByText("SMALL_POS")).toBeInTheDocument();
    });

    // Verify sort order by checking the DOM row order.
    // WHY querySelectorAll: gets all <tr> elements in document order, which
    // reflects the React render order after the sort.
    const rows = document.querySelectorAll("tbody tr");
    const names = Array.from(rows).map((r) => r.querySelector("td")?.textContent?.trim());

    // WHY check first two rows: the absolute-value sort is the critical
    // invariant. LARGE_NEG (|300|) must come before LARGE_POS (|250|).
    expect(names[0]).toBe("LARGE_NEG");
    expect(names[1]).toBe("LARGE_POS");
    // SMALL_POS (|10|) must be last — smallest absolute contrib.
    expect(names[names.length - 1]).toBe("SMALL_POS");
  });
});
