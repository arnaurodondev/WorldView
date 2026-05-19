/**
 * components/instrument/quote/metrics/__tests__/AnalystMiniBar.test.tsx
 *
 * WHY THIS EXISTS: AnalystMiniBar collapses 5 analyst-rating buckets
 * (StrongBuy + Buy / Hold / Sell + StrongSell) into a 3-segment compact
 * bar — see the WHY notes in AnalystMiniBar.tsx. PLAN-0090 §T-B-05 pins
 * two behavioural contracts here:
 *
 *   1. test_AnalystMiniBar_proportional
 *      30B + 10H + 5S (total = 45) → buy segment ≈ 66.6%, hold ≈ 22.2%,
 *      sell ≈ 11.1%. Verifies the bucket-collapse arithmetic AND the text
 *      "{B}B · {H}H · {S}S" summary used on the 22px row.
 *
 *   2. test_AnalystMiniBar_all_null_no_crash
 *      Passing all-null counts must NOT raise (no divide-by-zero, no NaN%)
 *      and must render an empty bar shell with "0B · 0H · 0S" text.
 *
 * If either contract regresses, the consensus row in MetricsTable would
 * render NaN% widths (invalid CSS) or crash the component tree for
 * low-coverage tickers.
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
    // WHY also assert text summary: the 22px row shows "{B}B · {H}H · {S}S"
    // below the bar — confirms bucket-collapse math feeds the readout too.
    expect(screen.getByText("30B · 10H · 5S")).toBeInTheDocument();
  });

  it("does not crash with all-null inputs and shows a 0B · 0H · 0S summary", () => {
    // WHY: any null bucket must coerce to 0 in the `n` helper; total=0
    // then short-circuits pct() to "0%" (no divide-by-zero, no NaN%).
    // This is exactly the "no coverage" scenario for an obscure ticker.
    const { container } = render(
      <AnalystMiniBar strongBuy={null} buy={null} hold={null} sell={null} strongSell={null} />,
    );
    const widths = readSegmentWidths(container);
    expect(widths.buy).toBe("0%");
    expect(widths.hold).toBe("0%");
    expect(widths.sell).toBe("0%");
    expect(screen.getByText("0B · 0H · 0S")).toBeInTheDocument();
  });
});
