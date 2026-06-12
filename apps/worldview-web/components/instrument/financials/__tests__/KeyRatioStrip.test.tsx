/**
 * KeyRatioStrip.test.tsx — top-of-tab headline ratio band
 * (Wave-2 redesign, scope item 1 — net-new component, net-new coverage).
 *
 * CONTRACTS:
 *   1. All 12 headline cells render with their uppercase labels.
 *   2. Values format through the shared formatters (compact currency,
 *      signed percent, ratio) — spot-checked per category.
 *   3. Nulls render the em-dash placeholder, never "0" or blank.
 *   4. Colour intent matches the DenseMetricsGrid thresholds (P/E < 20 →
 *      positive; negative margin → negative) so strip and grid never
 *      disagree about the same metric on one screen.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { KeyRatioStrip } from "@/components/instrument/financials/KeyRatioStrip";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const FUNDAMENTALS = {
  instrument_id: "i-1",
  ticker: "AAPL",
  name: "Apple Inc",
  market_cap: 3.2e12,
  pe_ratio: 18.4, // < 20 → positive (cheap) per the shared threshold
  forward_pe: 26.1, // 20–35 → warning
  ev_to_ebitda: 22.5,
  price_to_sales: 8.1,
  roe: 1.47,
  net_margin: -0.05, // negative → negative token
  revenue_growth_yoy: 0.062,
  dividend_yield: 0.0044,
  debt_to_equity: 1.45,
} as unknown as Fundamentals;

const SNAPSHOT = {
  free_cash_flow: 98e9,
  beta: 1.24,
} as unknown as FundamentalsSnapshot;

// ── Tests ────────────────────────────────────────────────────────────────────

describe("KeyRatioStrip", () => {
  it("renders all 12 headline labels", () => {
    render(<KeyRatioStrip fundamentals={FUNDAMENTALS} snapshot={SNAPSHOT} />);
    for (const label of [
      "MKT CAP",
      "P/E",
      "FWD P/E",
      "EV/EBITDA",
      "P/S",
      "ROE",
      "NET MGN",
      "REV YOY",
      "FCF",
      "DIV YLD",
      "BETA",
      "D/E",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("formats values per category (currency / ratio / percent / plain)", () => {
    render(<KeyRatioStrip fundamentals={FUNDAMENTALS} snapshot={SNAPSHOT} />);
    expect(screen.getByText("$3.20T")).toBeInTheDocument(); // market cap
    expect(screen.getByText("18.40x")).toBeInTheDocument(); // P/E ratio
    expect(screen.getByText("+6.20%")).toBeInTheDocument(); // rev YoY (decimal → %)
    expect(screen.getByText("1.24")).toBeInTheDocument(); // beta (plain 2dp)
  });

  it("renders em-dashes for null data (strip never shows fake zeros)", () => {
    render(<KeyRatioStrip fundamentals={null} snapshot={null} />);
    // All 12 cells null → 12 dashes.
    expect(screen.getAllByText("—")).toHaveLength(12);
  });

  it("colour intent agrees with the grid thresholds", () => {
    render(<KeyRatioStrip fundamentals={FUNDAMENTALS} snapshot={SNAPSHOT} />);
    // Cheap P/E (18.4 < 20) → positive token.
    expect(screen.getByText("18.40x").className).toContain("text-positive");
    // Negative net margin → negative token.
    expect(screen.getByText("-5.00%").className).toContain("text-negative");
  });
});
