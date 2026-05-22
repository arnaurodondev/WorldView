/**
 * InsiderTransactionsTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the dict-of-dicts EODHD format parsing contract.
 * Confirms the table renders transaction rows from the EODHD dict-of-dicts
 * format, shows the "View all →" link when ticker is set, and renders the
 * empty-state gracefully when data is absent.
 */

import { describe, it, expect } from "vitest";
import { vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { InsiderTransactionsTable } from "@/components/instrument/financials/InsiderTransactionsTable";
import type { FundamentalsSectionResponse } from "@/types/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

// EODHD dict-of-dicts format
const INSIDER_DATA: FundamentalsSectionResponse = {
  security_id: "aapl",
  records: [
    {
      id: "r1",
      security_id: "aapl",
      section: "insider_transactions",
      period_end: "2026-05-01",
      period_type: "SNAPSHOT",
      source: "eodhd",
      ingested_at: "2026-05-01T00:00:00Z",
      data: {
        "0": {
          date: "2026-04-15",
          ownerName: "Tim Cook",
          transactionCode: "S",
          transactionAmount: 50000,
          transactionPrice: 210.5,
          transactionDate: "2026-04-15",
          secLink: "https://sec.gov/filing/001",
        },
        "1": {
          date: "2026-03-20",
          ownerName: "Luca Maestri",
          transactionCode: "P",
          transactionAmount: 10000,
          transactionPrice: 198.0,
          transactionDate: "2026-03-20",
          secLink: "https://sec.gov/filing/002",
        },
      },
    },
  ],
};

describe("InsiderTransactionsTable", () => {
  it("renders section header", () => {
    render(<InsiderTransactionsTable insiderData={INSIDER_DATA} ticker="AAPL" />);
    expect(screen.getByText("INSIDER TRANSACTIONS")).toBeInTheDocument();
  });

  it("parses dict-of-dicts and renders insider names", () => {
    render(<InsiderTransactionsTable insiderData={INSIDER_DATA} ticker="AAPL" />);
    expect(screen.getByText("Tim Cook")).toBeInTheDocument();
    expect(screen.getByText("Luca Maestri")).toBeInTheDocument();
  });

  it("renders View all link when ticker is provided", () => {
    render(<InsiderTransactionsTable insiderData={INSIDER_DATA} ticker="AAPL" />);
    expect(screen.getByText(/view all/i)).toBeInTheDocument();
  });

  it("renders empty state when insiderData is undefined", () => {
    render(<InsiderTransactionsTable insiderData={undefined} ticker="AAPL" />);
    expect(screen.getByText(/no insider activity/i)).toBeInTheDocument();
  });
});
