/**
 * features/dashboard/components/__tests__/WatchlistMoverRow.test.tsx
 *
 * Regression test for the 2026-06-19 row-overflow ("winners/losers wrap") fix.
 * See docs/audits/2026-06-19-winners-losers-wrap.md.
 *
 * WHAT WE GUARD:
 *   1. The clamping classes (overflow-hidden + min-w-0 on the row, plus
 *      whitespace-nowrap on the fixed ticker / price / % slots) stay applied so
 *      a long ticker + a large price + an extreme % can never wrap to a second
 *      line or bleed past the column edge into the sibling list.
 *   2. The bounded formatters render — the price uses formatPriceCompact
 *      ("$650.00K") and the % uses formatChangePct ("+135.4%") so neither
 *      overflows its fixed-width slot at extreme values.
 *
 * WHY a DOM-class assertion (not a pixel-width assertion): jsdom does not lay
 * out / measure boxes, so we cannot assert "fits 52px". The clamping is purely
 * a function of the Tailwind classes, so asserting the classes + the bounded
 * formatter output is the faithful, deterministic check.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { WatchlistMoverRow } from "../WatchlistMoverRow";
import type { WatchlistMover } from "../../lib/movers";

// A deliberately hostile row: a long-ish ticker, a high price (≥$1M, where the
// compact formatter engages), and a short-squeeze % move — the exact
// combination that used to overflow. formatPriceCompact only switches to a
// suffix at ≥$1M (below that it stays full-precision but the whitespace-nowrap
// + row overflow-hidden clamping still prevents any two-line wrap), so we pick a
// value above the threshold here to also assert the compact rendering.
const extremeMover: WatchlistMover = {
  instrumentId: "00000000-0000-0000-0000-000000000001",
  ticker: "BRKAVERYLONG", // intentionally too wide for the 40px ticker slot
  name: "Berkshire Hathaway Inc. Class A Common Stock (Very Long Name)",
  sector: "Financials",
  price: 1_200_000, // → formatPriceCompact → "$1.20M"
  changePct: 135.43, // → formatChangePct → "+135.4%"
  newsCount24h: 0,
  hasActiveAlert: false,
  topNewsTitle: null,
  topNewsUrl: null,
};

describe("WatchlistMoverRow — overflow clamping (winners/losers wrap fix)", () => {
  it("keeps the row clamped: overflow-hidden + min-w-0 on the row container", () => {
    render(
      <WatchlistMoverRow
        mover={extremeMover}
        side="gainer"
        showEnrichmentBadges={false}
        onClick={vi.fn()}
      />,
    );

    // The row is the element carrying the aria-label.
    const row = screen.getByRole("button", {
      name: /Open BRKAVERYLONG instrument page/,
    });
    expect(row.className).toContain("overflow-hidden");
    expect(row.className).toContain("min-w-0");
  });

  it("renders the bounded price + % so they fit the fixed slots", () => {
    render(
      <WatchlistMoverRow
        mover={extremeMover}
        side="gainer"
        showEnrichmentBadges={false}
        onClick={vi.fn()}
      />,
    );

    // Compact price (not "$1,200,000.00") and bounded % (not "+135.43%").
    expect(screen.getByText("$1.20M")).toBeInTheDocument();
    expect(screen.getByText("+135.4%")).toBeInTheDocument();
  });

  it("clamps the fixed ticker slot (overflow-hidden + whitespace-nowrap) so a long ticker cannot bleed", () => {
    render(
      <WatchlistMoverRow
        mover={extremeMover}
        side="gainer"
        showEnrichmentBadges={false}
        onClick={vi.fn()}
      />,
    );

    const ticker = screen.getByText("BRKAVERYLONG");
    expect(ticker.className).toContain("overflow-hidden");
    expect(ticker.className).toContain("whitespace-nowrap");
    // The slot stays fixed-width + non-shrinking so columns align across rows.
    expect(ticker.className).toContain("w-[40px]");
    expect(ticker.className).toContain("shrink-0");
  });

  it("keeps whitespace-nowrap on the fixed price + % slots (no two-line wrap)", () => {
    render(
      <WatchlistMoverRow
        mover={extremeMover}
        side="gainer"
        showEnrichmentBadges={false}
        onClick={vi.fn()}
      />,
    );

    expect(screen.getByText("$1.20M").className).toContain("whitespace-nowrap");
    expect(screen.getByText("+135.4%").className).toContain("whitespace-nowrap");
  });
});
