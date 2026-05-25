/**
 * CompanySnapshotPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the sector/industry/country display contract.
 * Uses mocked gateway + QueryClient so no real network calls fire.
 * The "more ↓ / less ↑" toggle is also verified.
 *
 * F-009: extended to cover the EMPLOYEES row (full_time_employees field).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CompanySnapshotPanel } from "@/components/instrument/financials/sidebar/CompanySnapshotPanel";

// WHY mockGetOverview is hoisted: keeping a reference to the inner mock function
// lets individual tests override the resolved value without re-mocking the whole
// module. useApiClient returns an object whose getCompanyOverview property
// points to this same vi.fn().
const mockGetOverview = vi.fn();

vi.mock("@/lib/api-client", () => ({
  useApiClient: () => ({ getCompanyOverview: mockGetOverview }),
}));

const MOCK_OVERVIEW = {
  instrument: {
    instrument_id: "aapl",
    ticker: "AAPL",
    name: "Apple Inc.",
    gics_sector: "Information Technology",
    gics_industry: "Technology Hardware",
    country: "United States",
    description:
      "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide. It also sells related accessories and services, including AppleCare, iCloud, Apple Music, Apple TV+, Apple Arcade, Apple Fitness+, Apple News+, and Apple Card. The company is headquartered in Cupertino, California, and was founded in 1976.",
    exchange: "NASDAQ",
    currency: "USD",
    isin: null,
    description_updated_at: null,
    // F-009: full_time_employees from EODHD General.FullTimeEmployees (cast to int by S9).
    full_time_employees: 147000,
  },
};

function wrap(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("CompanySnapshotPanel", () => {
  // Reset the mock before each test so overrides in one test don't bleed over.
  beforeEach(() => {
    mockGetOverview.mockResolvedValue(MOCK_OVERVIEW);
  });

  it("renders section header", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("COMPANY SNAPSHOT")).toBeInTheDocument();
  });

  it("renders sector label and value", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("SECTOR")).toBeInTheDocument();
    expect(await findByText("Information Technology")).toBeInTheDocument();
  });

  it("renders industry label and value", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("INDUSTRY")).toBeInTheDocument();
    expect(await findByText("Technology Hardware")).toBeInTheDocument();
  });

  it("renders country", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("United States")).toBeInTheDocument();
  });

  it("shows more/less toggle for long description", async () => {
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    const moreBtn = await findByText("more ↓");
    expect(moreBtn).toBeInTheDocument();

    await userEvent.click(moreBtn);
    expect(screen.getByText("less ↑")).toBeInTheDocument();
  });

  // ── F-009: EMPLOYEES row ────────────────────────────────────────────────────

  it("renders EMPLOYEES label and formatted headcount (147,000)", async () => {
    // WHY toLocaleString assertion: the component calls .toLocaleString() so
    // 147000 should render as "147,000" (comma-separated for readability).
    // Spec: docs/designs/0089/06-instrument-financials.md §5.2
    const { findByText } = render(wrap(<CompanySnapshotPanel instrumentId="aapl" />));
    expect(await findByText("EMPLOYEES")).toBeInTheDocument();
    expect(await findByText("147,000")).toBeInTheDocument();
  });

  it("does not render EMPLOYEES row when full_time_employees is null", async () => {
    // Override the resolved value for this test only (beforeEach resets it afterwards).
    // WHY: ETFs and foreign ADRs omit FullTimeEmployees; the row must be absent
    // when the value is null (SnapshotRow returns null, rendering nothing to the DOM).
    mockGetOverview.mockResolvedValueOnce({
      instrument: { ...MOCK_OVERVIEW.instrument, full_time_employees: null },
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { queryByText } = render(
      <QueryClientProvider client={qc}>
        <CompanySnapshotPanel instrumentId="aapl-null-emp" />
      </QueryClientProvider>
    );

    // Wait for the component to settle (query resolves → instrument renders).
    await screen.findByText("COMPANY SNAPSHOT");
    // The EMPLOYEES label must be absent when the value is null.
    expect(queryByText("EMPLOYEES")).not.toBeInTheDocument();
  });
});
