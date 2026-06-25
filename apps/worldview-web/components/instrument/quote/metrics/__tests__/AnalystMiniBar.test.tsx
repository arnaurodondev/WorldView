/**
 * components/instrument/quote/metrics/__tests__/AnalystMiniBar.test.tsx
 *
 * WHY THIS EXISTS: AnalystMiniBar collapses 5 analyst-rating buckets
 * (StrongBuy + Buy / Hold / Sell + StrongSell) into a 3-segment compact bar.
 * PLAN-0090 §T-B-05 pinned two contracts; the Wave-2 redesign (2026-06-10)
 * PORTS both with updated readout expectations:
 *
 *   1. test_AnalystMiniBar_proportional (PORTED, readout text updated)
 *      30B + 10H + 5S (total = 45) → buy segment ≈ 66.6%, hold ≈ 22.2%,
 *      sell ≈ 11.1%. The textual breakdown is now the colour-coded
 *      "{B} Buy · {H} Hold · {S} Sell" + "{total} analysts" sample size
 *      (replaces the cryptic "{B}B · {H}H · {S}S").
 *
 *   2. test_AnalystMiniBar_all_null (PORTED, behaviour redesigned)
 *      All-null counts must NOT raise (no divide-by-zero, no NaN%). The
 *      redesign renders an honest "No analyst coverage" line INSTEAD of an
 *      empty bar + "0B · 0H · 0S" noise — the bar is hidden entirely.
 *
 * If contract 1 regresses, the consensus block in MetricsTable would render
 * NaN% widths; if contract 2 regresses, zero-coverage tickers show cryptic
 * zeros again (the exact bug the Wave-2 verdict called out).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalystMiniBar } from "@/components/instrument/quote/metrics/AnalystMiniBar";

/**
 * WHY: each segment's width is set via inline style; the bar contains
 * exactly three width-styled divs in (buy, hold, sell) order. This helper
 * isolates DOM traversal so each test can assert on percentages directly.
 */
function readSegmentWidths(container: HTMLElement): { buy: string; hold: string; sell: string } {
  const segments = Array.from(
    container.querySelectorAll('div[style*="width"]'),
  ) as HTMLElement[];
  if (segments.length < 3) {
    throw new Error(`AnalystMiniBar: expected 3 segments, got ${segments.length}`);
  }
  return {
    buy: segments[0].style.width,
    hold: segments[1].style.width,
    sell: segments[2].style.width,
  };
}

describe("AnalystMiniBar", () => {
  it("renders proportional segment widths for 30B / 10H / 5S", () => {
    // WHY 25/5 buy split (=30), 10 hold, 4/1 sell split (=5): replicates
    // the plan's "30B/10H/5S → buy 66.6% / hold 22.2% / sell 11.1%" case
    // while exercising BOTH halves of the strong/regular collapse.
    const { container } = render(
      <AnalystMiniBar strongBuy={25} buy={5} hold={10} sell={4} strongSell={1} />,
    );
    const widths = readSegmentWidths(container);
    // WHY assert with startsWith on "66.6": JS floating point yields a
    // long fractional ("66.66666666666666%") — startsWith pins the right
    // proportional bucket without coupling to digit precision.
    expect(widths.buy.startsWith("66.6")).toBe(true);
    expect(widths.hold.startsWith("22.2")).toBe(true);
    expect(widths.sell.startsWith("11.1")).toBe(true);
    // Wave-2 readout: colour-coded counts + the sample size. Confirms the
    // bucket-collapse math feeds the text too (30 = 25 SB + 5 B etc.).
    expect(screen.getByText("30 Buy")).toBeInTheDocument();
    expect(screen.getByText("10 Hold")).toBeInTheDocument();
    expect(screen.getByText("5 Sell")).toBeInTheDocument();
    expect(screen.getByText("45 analysts")).toBeInTheDocument();
  });

  it("renders 'No analyst coverage' (and NO bar) for all-null inputs", () => {
    // WHY: any null bucket must coerce to 0; total=0 short-circuits to the
    // named empty state BEFORE any division — no divide-by-zero, no NaN%.
    // This is exactly the "no coverage" scenario for an obscure ticker.
    const { container } = render(
      <AnalystMiniBar strongBuy={null} buy={null} hold={null} sell={null} strongSell={null} />,
    );
    expect(screen.getByText("No analyst coverage")).toBeInTheDocument();
    // The segment bar is hidden entirely — an empty bar shell would read as
    // broken data rather than a real market fact.
    expect(container.querySelectorAll('div[style*="width"]')).toHaveLength(0);
  });
});
