/**
 * sidebar/__tests__/CompanySnapshotPanel.test.tsx — T-30 unit tests
 *
 * WHY THIS EXISTS (T-30): CompanySnapshotPanel is the "COMPANY" block at the
 * top of the 7-panel sidebar (T-23). These tests verify:
 *   1. All four identity rows render correctly (SECTOR, INDUSTRY, EXCHANGE, HQ).
 *   2. The description clamp + "more/less" toggle works.
 *   3. Null instrument renders the "COMPANY" header and a "No data" fallback.
 *
 * WHY no provider tree needed: CompanySnapshotPanel is purely presentational
 * — it reads from the `instrument` prop only, with a local useState for the
 * description toggle. No TanStack Query or Auth context required.
 *
 * WHY spot-check content (not snapshot): snapshot tests break on every minor
 * copy or styling change. Asserting specific text values ties the test to the
 * business contract (sector label renders), not the markup.
 */

import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CompanySnapshotPanel } from "@/components/instrument/financials/sidebar/CompanySnapshotPanel";
import type { Instrument } from "@/types/api";

const INSTRUMENT: Partial<Instrument> = {
  ticker: "AAPL",
  name: "Apple Inc.",
  gics_sector: "Information Technology",
  gics_industry: "Technology Hardware, Storage & Peripherals",
  exchange: "NASDAQ",
  country: "USA",
  description: "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide.",
};

describe("CompanySnapshotPanel", () => {
  it("renders the COMPANY section header", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    expect(screen.getByText("COMPANY")).toBeInTheDocument();
  });

  it("renders sector field from instrument.gics_sector", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    // WHY assert the actual sector value: this confirms the panel reads the
    // gics_sector field and doesn't silently render "—" due to a field name typo.
    expect(screen.getByText("Information Technology")).toBeInTheDocument();
  });

  it("renders industry field from instrument.gics_industry", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    expect(screen.getByText("Technology Hardware, Storage & Peripherals")).toBeInTheDocument();
  });

  it("renders exchange from instrument.exchange", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    expect(screen.getByText("NASDAQ")).toBeInTheDocument();
  });

  it("renders country in the HQ row", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    expect(screen.getByText("USA")).toBeInTheDocument();
  });

  it("renders the description (clamped by default)", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    // WHY check partial text: the full description is rendered in the DOM even
    // when clamped via CSS. getByText with exact=false checks it is present.
    expect(screen.getByText((t) => t.includes("Apple Inc. designs"))).toBeInTheDocument();
  });

  it("shows 'more →' toggle button when description is present", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    expect(screen.getByRole("button", { name: "Show full description" })).toBeInTheDocument();
  });

  it("toggles description expand/collapse on button click", () => {
    render(<CompanySnapshotPanel instrument={INSTRUMENT as Instrument} />);
    const btn = screen.getByRole("button", { name: "Show full description" });
    // After click: aria-label should reflect the "collapse" state.
    fireEvent.click(btn);
    expect(screen.getByRole("button", { name: "Show less description" })).toBeInTheDocument();
    // Second click: reverts to "expand" state.
    fireEvent.click(screen.getByRole("button", { name: "Show less description" }));
    expect(screen.getByRole("button", { name: "Show full description" })).toBeInTheDocument();
  });

  it("renders 'No data' fallback when instrument is null", () => {
    render(<CompanySnapshotPanel instrument={null} />);
    // WHY check both header and fallback text: the null branch must still render
    // the COMPANY header so the sidebar panel structure doesn't collapse.
    expect(screen.getByText("COMPANY")).toBeInTheDocument();
    expect(screen.getByText("No data")).toBeInTheDocument();
  });

  it("renders '—' for missing optional fields (no description)", () => {
    const noDesc: Partial<Instrument> = {
      ticker: "TST",
      gics_sector: "Industrials",
      gics_industry: null,
      exchange: "NYSE",
      country: null,
      description: null,
    };
    render(<CompanySnapshotPanel instrument={noDesc as Instrument} />);
    // WHY two "—" dashes: gics_industry = null + country = null → 2 dash values.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    // No description → no "more →" toggle button present.
    expect(screen.queryByRole("button", { name: /description/i })).not.toBeInTheDocument();
  });
});
