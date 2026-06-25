/**
 * AnalystConsensusPanel.test.tsx (T-30, updated Wave-2)
 *
 * WHY THIS EXISTS: Pins the consensus panel composition contract — the
 * section header renders, and the AnalystMiniBar (which since Wave-2 owns
 * BOTH the colour-coded breakdown and the "{N} analysts" sample size)
 * renders through the panel.
 *
 * WAVE-2 UPDATE: the panel's own "{N} analysts" subline was removed (the
 * redesigned AnalystMiniBar carries the sample size itself — keeping both
 * would print it twice). Assertions now pin:
 *   - exactly ONE "45 analysts" instance (duplicate-regression guard);
 *   - the bar's breakdown text in the panel;
 *   - the bar's honest zero-coverage state replacing the old hidden line.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalystConsensusPanel } from "@/components/instrument/financials/sidebar/AnalystConsensusPanel";

describe("AnalystConsensusPanel", () => {
  it("renders section header", () => {
    render(
      <AnalystConsensusPanel strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
  });

  it("renders the analyst count exactly once (bar-owned, no panel duplicate)", () => {
    render(
      <AnalystConsensusPanel strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    // total = 25+5+10+4+1 = 45 — rendered ONLY by AnalystMiniBar since Wave-2.
    expect(screen.getAllByText("45 analysts")).toHaveLength(1);
  });

  it("renders the AnalystMiniBar colour-coded breakdown", () => {
    render(
      <AnalystConsensusPanel strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    // Wave-2 bar collapses 5 buckets → 3: (25+5) Buy / 10 Hold / (4+1) Sell.
    expect(screen.getByText("30 Buy")).toBeInTheDocument();
    expect(screen.getByText("10 Hold")).toBeInTheDocument();
    expect(screen.getByText("5 Sell")).toBeInTheDocument();
  });

  it("renders the honest zero-coverage state when all buckets are null", () => {
    render(
      <AnalystConsensusPanel
        strongBuy={null}
        buy={null}
        hold={null}
        sell={null}
        strongSell={null}
      />,
    );
    // Header still present; the bar names the absence instead of faking a bar.
    expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
    expect(screen.getByText("No analyst coverage")).toBeInTheDocument();
    expect(screen.queryByText(/0 analyst/i)).toBeNull();
  });
});
