/**
 * components/portfolio/__tests__/SectorExposurePanel.test.tsx
 * (2026-06-10 sprint, Wave 2 — overview band panel #2, rewritten component.)
 *
 * WHY: pins the panel's render contract — per-sector weight + LIVE day Δ$
 * joined by exact instrument ID, the null-path "—" (old S9 build without
 * instrument_ids), the honest benchmark-gap caption, and the skeleton.
 * The join math itself is unit-tested in lib/__tests__/sector-stats.test.ts;
 * this suite covers the presentational wiring.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { SectorExposurePanel } from "../SectorExposurePanel";
import type { Holding, SectorBreakdownSegment } from "@/types/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function holding(id: string, qty: number): Holding {
  return {
    holding_id: `h-${id}`,
    portfolio_id: "p1",
    instrument_id: id,
    entity_id: `e-${id}`,
    ticker: id.toUpperCase(),
    name: id,
    quantity: qty,
    average_cost: 100,
  };
}

const SEGMENTS: SectorBreakdownSegment[] = [
  {
    sector: "Technology",
    weight: 0.439,
    count: 3,
    market_value: 32_000,
    instrument_ids: ["aapl"],
  },
  {
    sector: "Communication Services",
    weight: 0.211,
    count: 4,
    market_value: 15_000,
    // No instrument_ids — simulates an older S9 build for this segment.
  },
];

const HOLDINGS = [holding("aapl", 10)];
const QUOTES = { aapl: { change: 2.5 } }; // +$25 day change for Technology

describe("SectorExposurePanel", () => {
  it("renders per-sector rows: name, weight and live day Δ$", () => {
    render(
      <SectorExposurePanel
        segments={SEGMENTS}
        holdings={HOLDINGS}
        quotes={QUOTES}
      />,
    );

    expect(screen.getByText("Sector Exposure")).toBeInTheDocument();
    expect(screen.getByTestId("sector-row-Technology")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("43.90%")).toBeInTheDocument(); // weight (unsigned)
    expect(screen.getByText("+$25.00")).toBeInTheDocument(); // day Δ$ (2.5 × 10)
  });

  it("renders an em-dash (never $0.00) for segments without instrument_ids", () => {
    render(
      <SectorExposurePanel
        segments={SEGMENTS}
        holdings={HOLDINGS}
        quotes={QUOTES}
      />,
    );
    const row = screen.getByTestId("sector-row-Communication Services");
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent("$0.00");
  });

  it("names the benchmark gap honestly in the footer caption", () => {
    render(
      <SectorExposurePanel segments={SEGMENTS} holdings={HOLDINGS} quotes={QUOTES} />,
    );
    expect(
      screen.getByText(/benchmark sector weights unavailable/i),
    ).toBeInTheDocument();
  });

  it("shows a skeleton while the breakdown is loading (segments undefined)", () => {
    render(<SectorExposurePanel holdings={[]} quotes={{}} />);
    expect(screen.getByTestId("sector-exposure-skeleton")).toBeInTheDocument();
  });

  it("shows a named empty state for an empty portfolio", () => {
    render(<SectorExposurePanel segments={[]} holdings={[]} quotes={{}} />);
    expect(screen.getByText("No sector data yet.")).toBeInTheDocument();
  });

  it("caps visible rows at 4 and quantifies the hidden tail", () => {
    const many: SectorBreakdownSegment[] = Array.from({ length: 6 }, (_, i) => ({
      sector: `Sector ${i}`,
      weight: 0.1,
      count: 1,
      market_value: 1_000,
      instrument_ids: [],
    }));
    render(<SectorExposurePanel segments={many} holdings={[]} quotes={{}} />);
    expect(screen.getByText("+2 more")).toBeInTheDocument();
    expect(screen.queryByTestId("sector-row-Sector 4")).not.toBeInTheDocument();
  });
});
