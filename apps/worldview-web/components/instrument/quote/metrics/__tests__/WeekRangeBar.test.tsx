/**
 * components/instrument/quote/metrics/__tests__/WeekRangeBar.test.tsx
 *
 * WHY THIS EXISTS: WeekRangeBar renders a 52-week price band with a fill
 * proportional to the live quote's position inside [low, high]. The WHY
 * notes in WeekRangeBar.tsx explicitly call out that the live quote can
 * print outside the cached 52W band (after-hours, stale fundamentals) and
 * that an unclamped width would blow the bar off-screen. PLAN-0090 §T-B-05
 * pins the clamp behaviour in both directions:
 *
 *   1. test_WeekRangeBar_clamps_below_zero — current < low → fill width 0%
 *   2. test_WeekRangeBar_clamps_above_100  — current > high → fill width 100%
 *
 * If a refactor accidentally drops the Math.max / Math.min guards, these
 * tests will catch it before the bar visually overflows in production.
 */

import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { WeekRangeBar } from "@/components/instrument/quote/metrics/WeekRangeBar";

/**
 * WHY a tiny helper: the fill is the second descendant of the track div,
 * positioned absolutely with an inline `style.width`. Centralising the
 * lookup keeps each test focused on the clamping contract, not on DOM
 * traversal mechanics.
 */
function readFillPercent(container: HTMLElement): number {
  // WHY querySelector on the absolute fill: it is the only element with
  // inline style.width in the rendered tree, so this selector is stable.
  const fill = container.querySelector('div[style*="width"]') as HTMLElement | null;
  if (!fill) throw new Error("WeekRangeBar: fill element not found");
  // WHY parseFloat (not exact string match): jsdom's CSSOM normalises CSS
  // percent strings — `"100.0%"` is serialised back as `"100%"`. We only
  // care that the clamp produced the right number; the literal trailing-zero
  // formatting is implementation detail of `.toFixed(1)` and not worth
  // pinning here.
  return parseFloat(fill.style.width);
}

describe("WeekRangeBar", () => {
  it("clamps the fill width to 0% when current price is below the 52W low", () => {
    // WHY current=50 against low=100/high=200: raw % = -50% before clamp.
    // Without Math.max(0, …) the fill would be a negative width (invalid
    // CSS) — clamping to 0% keeps the layout stable.
    const { container } = render(<WeekRangeBar high={200} low={100} current={50} />);
    expect(readFillPercent(container)).toBe(0);
  });

  it("clamps the fill width to 100% when current price is above the 52W high", () => {
    // WHY current=300 against low=100/high=200: raw % = 200% before clamp.
    // Without Math.min(100, …) the bar would visually overflow its track.
    const { container } = render(<WeekRangeBar high={200} low={100} current={300} />);
    expect(readFillPercent(container)).toBe(100);
  });
});
