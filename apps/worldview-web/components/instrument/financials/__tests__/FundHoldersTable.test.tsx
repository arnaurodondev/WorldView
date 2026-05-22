/**
 * FundHoldersTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Verifies fund/ETF holder data is parsed and rendered
 * correctly from EODHD dict-of-dicts format, and empty state is shown when
 * data is absent.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
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
});
