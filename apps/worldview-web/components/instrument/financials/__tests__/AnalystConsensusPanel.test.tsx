/**
 * AnalystConsensusPanel.test.tsx (T-30)
 *
 * WHY THIS EXISTS: Pins the consensus bar rendering contract — verifies the
 * section header, analyst count, and the AnalystMiniBar summary string are
 * all present when counts are non-null.
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

  it("renders analyst count when counts are non-null", () => {
    render(
      <AnalystConsensusPanel strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    // total = 25+5+10+4+1 = 45
    expect(screen.getByText("45 analysts")).toBeInTheDocument();
  });

  it("renders AnalystMiniBar summary text", () => {
    render(
      <AnalystConsensusPanel strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    // AnalystMiniBar renders "30B · 10H · 5S" (strongBuy+buy / hold / sell+strongSell)
    expect(screen.getByText("30B · 10H · 5S")).toBeInTheDocument();
  });

  it("hides analyst count when all buckets are null", () => {
    render(
      <AnalystConsensusPanel
        strongBuy={null}
        buy={null}
        hold={null}
        sell={null}
        strongSell={null}
      />,
    );
    // total = 0 → no count line
    expect(screen.queryByText(/analyst/i)).not.toBeNull(); // header still present
    expect(screen.queryByText(/0 analyst/i)).toBeNull();
  });
});
