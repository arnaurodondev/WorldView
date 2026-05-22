/**
 * InstitutionalHoldersTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Verifies EODHD dict-of-dicts holder data is parsed and
 * rendered correctly, and that the empty state shows when data is absent.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InstitutionalHoldersTable } from "@/components/instrument/financials/InstitutionalHoldersTable";
import type { FundamentalsSectionResponse } from "@/types/api";

const INSTITUTIONAL_DATA: FundamentalsSectionResponse = {
  security_id: "aapl",
  records: [
    {
      id: "r1",
      security_id: "aapl",
      section: "institutional_holders",
      period_end: "2026-03-31",
      period_type: "SNAPSHOT",
      source: "eodhd",
      ingested_at: "2026-04-01T00:00:00Z",
      data: {
        "0": {
          name: "Vanguard Group Inc",
          currentShares: 1_200_000_000,
          currentValue: 240_000_000_000,
          currentPercent: 7.8,
          change: 5_000_000,
        },
        "1": {
          name: "BlackRock Inc",
          currentShares: 900_000_000,
          currentValue: 180_000_000_000,
          currentPercent: 5.85,
          change: -2_000_000,
        },
      },
    },
  ],
};

describe("InstitutionalHoldersTable", () => {
  it("renders section header", () => {
    render(<InstitutionalHoldersTable institutionalData={INSTITUTIONAL_DATA} />);
    expect(screen.getByText("INSTITUTIONAL HOLDERS")).toBeInTheDocument();
  });

  it("renders holder names from dict-of-dicts data", () => {
    render(<InstitutionalHoldersTable institutionalData={INSTITUTIONAL_DATA} />);
    expect(screen.getByText("Vanguard Group Inc")).toBeInTheDocument();
    expect(screen.getByText("BlackRock Inc")).toBeInTheDocument();
  });

  it("renders Shares column header", () => {
    render(<InstitutionalHoldersTable institutionalData={INSTITUTIONAL_DATA} />);
    expect(screen.getByText("Shares")).toBeInTheDocument();
  });

  it("renders empty state when institutionalData is undefined", () => {
    render(<InstitutionalHoldersTable institutionalData={undefined} />);
    expect(screen.getByText(/institutional holder data not available/i)).toBeInTheDocument();
  });

  it("renders Holder column header", () => {
    render(<InstitutionalHoldersTable institutionalData={INSTITUTIONAL_DATA} />);
    expect(screen.getByText("Holder")).toBeInTheDocument();
  });
});
