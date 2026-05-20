/**
 * components/instrument/header/__tests__/WeekRangeMini.test.tsx
 *
 * WHY THIS EXISTS: WeekRangeMini renders a 60×6 px fill bar showing where
 * the live price sits inside its 52-week low→high band. The percent
 * calculation has three edge cases that, if regressed, either crash
 * (null inputs) or leak out of the bar (clamping) and look like a layout
 * bug. These tests pin all three:
 *   1. current < low  → 0% fill (clamp lower bound).
 *   2. current > high → 100% fill (clamp upper bound).
 *   3. any null input → 0% fill, no crash.
 *
 * DESIGN REFERENCE: docs/plans/0090-instrument-detail-page-redesign-plan.md
 *   §T-A-06 (the 3 WeekRangeMini tests listed in the test table).
 *   PRD-0088 §6.4 (60×6 px bar spec + clamp rationale).
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { WeekRangeMini } from "@/components/instrument/header/WeekRangeMini";

/**
 * Helper: grab the inner fill div from the rendered output and return
 * its inline width style. The fill div is the first child of the outer
 * track div with class `bg-primary` (per WeekRangeMini.tsx).
 */
function getFillWidth(container: HTMLElement): string {
  const fill = container.querySelector("div.bg-primary") as HTMLElement | null;
  if (!fill) throw new Error("WeekRangeMini fill div not found");
  return fill.style.width;
}

describe("WeekRangeMini", () => {
  it("clamps the fill to 0% when current is below the 52-week low", () => {
    // current=40, low=50, high=100 → raw percent = -20%, must clamp to 0%.
    const { container } = render(<WeekRangeMini low={50} high={100} current={40} />);
    expect(getFillWidth(container)).toBe("0%");
  });

  it("clamps the fill to 100% when current is above the 52-week high", () => {
    // current=150, low=50, high=100 → raw percent = 200%, must clamp to 100%.
    const { container } = render(<WeekRangeMini low={50} high={100} current={150} />);
    expect(getFillWidth(container)).toBe("100%");
  });

  it("renders 0% fill (and does not crash) when any input is null", () => {
    // WHY each null path is checked: fundamentals (low/high) and quote
    // (current) load on independent timelines — every combination of
    // missing inputs is reachable in production.
    const { container: c1 } = render(<WeekRangeMini low={null} high={100} current={75} />);
    expect(getFillWidth(c1)).toBe("0%");

    const { container: c2 } = render(<WeekRangeMini low={50} high={null} current={75} />);
    expect(getFillWidth(c2)).toBe("0%");

    const { container: c3 } = render(<WeekRangeMini low={50} high={100} current={null} />);
    expect(getFillWidth(c3)).toBe("0%");
  });
});
