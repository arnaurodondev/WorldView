/**
 * InstitutionalHoldersTable.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Verifies EODHD dict-of-dicts holder data is parsed and
 * rendered correctly, and that the empty state shows when data is absent.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
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

  it("renders empty state when data is an empty dict-of-dicts", () => {
    // EODHD can return {} when no institutional filings exist yet.
    const emptyDict: FundamentalsSectionResponse = {
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
          data: {},
        },
      ],
    };
    render(<InstitutionalHoldersTable institutionalData={emptyDict} />);
    expect(screen.getByText(/institutional holder data not available/i)).toBeInTheDocument();
  });

  // ── Wave-4 interactivity: click-to-sort columns ─────────────────────────────

  // Three holders whose ENDPOINT order (Vanguard, BlackRock, StateStreet) is
  // NOT the same as any single-column sort, so a re-sort is observably different.
  const SORT_DATA: FundamentalsSectionResponse = {
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
          "0": { name: "Vanguard", currentShares: 300, currentPercent: 9, currentValue: 30, change: 1 },
          "1": { name: "BlackRock", currentShares: 100, currentPercent: 3, currentValue: 10, change: 9 },
          "2": { name: "StateStreet", currentShares: 200, currentPercent: 6, currentValue: 20, change: 5 },
        },
      },
    ],
  };

  /** Read the holder names in DOM (row) order from the rendered tbody. */
  function holderOrder(): string[] {
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    // row[0] is the header; data rows follow.
    return rows
      .slice(1)
      .map((r) => within(r).getAllByRole("cell")[0].textContent?.trim() ?? "");
  }

  it("keeps the endpoint order until a header is clicked", () => {
    render(<InstitutionalHoldersTable institutionalData={SORT_DATA} />);
    expect(holderOrder()).toEqual(["Vanguard", "BlackRock", "StateStreet"]);
  });

  it("sorts by Change descending when the Change header is clicked", () => {
    render(<InstitutionalHoldersTable institutionalData={SORT_DATA} />);
    fireEvent.click(screen.getByRole("button", { name: /change/i }));
    // change: BlackRock 9, StateStreet 5, Vanguard 1.
    expect(holderOrder()).toEqual(["BlackRock", "StateStreet", "Vanguard"]);
  });

  it("flips to ascending on a second click of the same column", () => {
    render(<InstitutionalHoldersTable institutionalData={SORT_DATA} />);
    const changeHeader = screen.getByRole("button", { name: /change/i });
    fireEvent.click(changeHeader); // desc
    fireEvent.click(changeHeader); // asc
    expect(holderOrder()).toEqual(["Vanguard", "StateStreet", "BlackRock"]);
  });

  it("sets aria-sort on the active column header for screen readers", () => {
    render(<InstitutionalHoldersTable institutionalData={SORT_DATA} />);
    fireEvent.click(screen.getByRole("button", { name: /shares/i }));
    // The header CELL (not the button) carries aria-sort per the ARIA grid pattern.
    const sharesCell = screen
      .getAllByRole("columnheader")
      .find((th) => within(th).queryByText("Shares"));
    expect(sharesCell).toHaveAttribute("aria-sort", "descending");
  });
});
