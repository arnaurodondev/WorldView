/**
 * components/portfolio/__tests__/ContributorsStrip.test.tsx
 * (2026-06-10 sprint — Top Movers clipping fix, mode prop.)
 *
 * WHY: BottomStripCluster's cells are fixed-height + overflow-hidden. The
 * root-caused bug: in the legacy "both" layout the contributors section
 * rendered FIRST (~128px), pushing the real detractor rows below the
 * clipped fold — the detractors column showed only dashes. The new `mode`
 * prop renders exactly ONE section per cell. These tests pin:
 *   1. mode="detractors" renders the detractor rows IMMEDIATELY after its
 *      own 22px header (nothing above them to clip) — the regression test.
 *   2. mode="contributors" mirrors it for the winners column.
 *   3. default mode keeps the legacy two-section layout byte-compatible
 *      (Top Movers header + both sub-headers).
 */

import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ContributorsStrip } from "../ContributorsStrip";

// next/link renders an <a> in jsdom without needing a router mock in this
// repo's test setup (vitest.setup mocks next/link globally if needed) —
// SingleMoverRow uses Link for tickers.

const CONTRIBUTORS = [
  { ticker: "AAPL", name: "Apple Inc.", pnlPct: 5.2 },
  { ticker: "MSFT", name: "Microsoft Corp.", pnlPct: 3.1 },
];
const DETRACTORS = [
  { ticker: "META", name: "Meta Platforms", pnlPct: -4.7 },
  { ticker: "NFLX", name: "Netflix Inc.", pnlPct: -2.3 },
];

describe("ContributorsStrip mode prop (clipping fix)", () => {
  it("mode='detractors' renders ONLY the detractors section — real rows at the top", () => {
    render(
      <ContributorsStrip
        mode="detractors"
        contributors={[]}
        detractors={DETRACTORS}
      />,
    );

    const section = screen.getByTestId("movers-detractors");
    // Own section header — no "Top Movers" umbrella, no contributors
    // sub-header consuming slot height above the data.
    expect(within(section).getByText("Top Detractors")).toBeInTheDocument();
    expect(within(section).queryByText("Top Movers")).not.toBeInTheDocument();
    expect(within(section).queryByText("Top Contributors")).not.toBeInTheDocument();

    // THE regression: real detractor rows are present and not preceded by a
    // padded contributors block (in the old layout these sat below the
    // 96px overflow fold and the user saw only dashes).
    expect(within(section).getByText("META")).toBeInTheDocument();
    expect(within(section).getByText("NFLX")).toBeInTheDocument();
    expect(within(section).getByText("-4.70%")).toBeInTheDocument();
  });

  it("mode='contributors' renders ONLY the contributors section", () => {
    render(
      <ContributorsStrip
        mode="contributors"
        contributors={CONTRIBUTORS}
        detractors={[]}
      />,
    );

    const section = screen.getByTestId("movers-contributors");
    expect(within(section).getByText("Top Contributors")).toBeInTheDocument();
    expect(within(section).queryByText("Top Detractors")).not.toBeInTheDocument();
    expect(within(section).getByText("AAPL")).toBeInTheDocument();
    expect(within(section).getByText("+5.20%")).toBeInTheDocument();
  });

  it("single-section modes pad to exactly 4 row slots (stable height contract)", () => {
    render(
      <ContributorsStrip
        mode="detractors"
        contributors={[]}
        detractors={DETRACTORS.slice(0, 1)}
      />,
    );
    const section = screen.getByTestId("movers-detractors");
    // 1 real row + 3 dash placeholders.
    expect(within(section).getAllByText("—")).toHaveLength(3);
  });

  it("default mode keeps the legacy two-section 'Top Movers' layout", () => {
    render(
      <ContributorsStrip contributors={CONTRIBUTORS} detractors={DETRACTORS} />,
    );
    expect(screen.getByText("Top Movers")).toBeInTheDocument();
    expect(screen.getByText("Top Contributors")).toBeInTheDocument();
    expect(screen.getByText("Top Detractors")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("META")).toBeInTheDocument();
  });
});
