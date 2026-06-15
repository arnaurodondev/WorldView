/**
 * FundHoldersTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Verifies fund/ETF holder data is parsed and rendered
 * correctly from EODHD dict-of-dicts format, and empty state is shown when
 * data is absent.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { FundHoldersTable } from "@/components/instrument/financials/FundHoldersTable";
import type { FundamentalsSectionResponse } from "@/types/api";

const FUND_DATA: FundamentalsSectionResponse = {
  security_id: "aapl",
  records: [
    {
      id: "r1",
      security_id: "aapl",
      section: "fund_holders",
      period_end: "2026-03-31",
      period_type: "SNAPSHOT",
      source: "eodhd",
      ingested_at: "2026-04-01T00:00:00Z",
      data: {
        "0": {
          name: "Vanguard 500 Index Fund",
          totalShares: 400_000_000,
          currentShares: 400_000_000,
          currentValue: 80_000_000_000,
          currentPercent: 2.6,
          change: 1_000_000,
        },
        "1": {
          name: "iShares Core S&P 500 ETF",
          totalShares: 320_000_000,
          currentShares: 320_000_000,
          currentValue: 64_000_000_000,
          currentPercent: 2.08,
          change: -500_000,
        },
      },
    },
  ],
};

describe("FundHoldersTable", () => {
  it("renders section header", () => {
    render(<FundHoldersTable fundHoldersData={FUND_DATA} />);
    expect(screen.getByText("FUND HOLDERS")).toBeInTheDocument();
  });

  it("renders fund names from dict-of-dicts data", () => {
    render(<FundHoldersTable fundHoldersData={FUND_DATA} />);
    expect(screen.getByText("Vanguard 500 Index Fund")).toBeInTheDocument();
    expect(screen.getByText(/iShares Core/)).toBeInTheDocument();
  });

  it("renders empty state when fundHoldersData is undefined", () => {
    render(<FundHoldersTable fundHoldersData={undefined} />);
    expect(screen.getByText(/fund holder data not available/i)).toBeInTheDocument();
  });

  it("renders empty state when data is an empty dict-of-dicts", () => {
    // EODHD can return {} when no fund filings are available for this ticker.
    const emptyDict: FundamentalsSectionResponse = {
      security_id: "aapl",
      records: [
        {
          id: "r1",
          security_id: "aapl",
          section: "fund_holders",
          period_end: "2026-03-31",
          period_type: "SNAPSHOT",
          source: "eodhd",
          ingested_at: "2026-04-01T00:00:00Z",
          data: {},
        },
      ],
    };
    render(<FundHoldersTable fundHoldersData={emptyDict} />);
    expect(screen.getByText(/fund holder data not available/i)).toBeInTheDocument();
  });

  // ── Wave-4 interactivity: click-to-sort columns ─────────────────────────────

  // Endpoint order (A, B, C) deliberately differs from any single-column sort.
  const SORT_DATA: FundamentalsSectionResponse = {
    security_id: "aapl",
    records: [
      {
        id: "r1",
        security_id: "aapl",
        section: "fund_holders",
        period_end: "2026-03-31",
        period_type: "SNAPSHOT",
        source: "eodhd",
        ingested_at: "2026-04-01T00:00:00Z",
        data: {
          "0": { name: "AlphaFund", currentShares: 300, totalShares: 300, currentPercent: 9, currentValue: 30, change: 1 },
          "1": { name: "BetaFund", currentShares: 100, totalShares: 100, currentPercent: 3, currentValue: 10, change: 9 },
          "2": { name: "GammaFund", currentShares: 200, totalShares: 200, currentPercent: 6, currentValue: 20, change: 5 },
        },
      },
    ],
  };

  function fundOrder(): string[] {
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    return rows
      .slice(1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent?.trim() ?? "");
  }

  it("keeps the endpoint order until a header is clicked", () => {
    render(<FundHoldersTable fundHoldersData={SORT_DATA} />);
    expect(fundOrder()).toEqual(["AlphaFund", "BetaFund", "GammaFund"]);
  });

  it("sorts by Shares descending on the Shares header click", () => {
    render(<FundHoldersTable fundHoldersData={SORT_DATA} />);
    fireEvent.click(screen.getByRole("button", { name: /shares/i }));
    // shares: AlphaFund 300, GammaFund 200, BetaFund 100.
    expect(fundOrder()).toEqual(["AlphaFund", "GammaFund", "BetaFund"]);
  });

  it("sorts by Change descending on the Change header click", () => {
    render(<FundHoldersTable fundHoldersData={SORT_DATA} />);
    fireEvent.click(screen.getByRole("button", { name: /change/i }));
    // change: BetaFund 9, GammaFund 5, AlphaFund 1.
    expect(fundOrder()).toEqual(["BetaFund", "GammaFund", "AlphaFund"]);
  });
});
