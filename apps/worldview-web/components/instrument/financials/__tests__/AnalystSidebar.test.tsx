/**
 * components/instrument/financials/__tests__/AnalystSidebar.test.tsx
 *
 * WHY THIS EXISTS: PLAN-0090 §T-C-04 pins one composition contract on
 * the Financials right-rail (PRD-0088 §6.8):
 *
 *   1. test_AnalystSidebar_renders_consensus_bar
 *      When at least one of the 5 bucket counts is non-null, the
 *      <AnalystMiniBar/> stacked-consensus bar MUST render inside the
 *      sidebar. The sidebar's whole reason for existing is to surface the
 *      consensus pill next to the metrics grid; a silent regression that
 *      drops the bar (e.g. accidental conditional gate, props rename)
 *      would eliminate the only Wall-Street opinion artefact on the page.
 *
 * WHY assert on the bar's text summary "{B}B · {H}H · {S}S" (rather than
 * on a DOM-internal selector): AnalystMiniBar deliberately writes this
 * summary string as part of its rendered output — it is a stable, visible
 * contract owned by AnalystMiniBar's own test (`AnalystMiniBar.test.tsx`).
 * Reusing it here keeps this test loosely coupled to the bar's internals
 * (no querySelectorAll on `[style*=width]`) while still proving the bar
 * mounted. If the bar fails to mount, the summary text is absent.
 *
 * WHY NOT also assert on null-coverage path: that scenario is covered by
 * AnalystMiniBar's own "all-null inputs" test. T-C-04 only requires the
 * positive-render contract here.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";

describe("AnalystSidebar", () => {
  it("renders the AnalystMiniBar consensus bar when bucket counts are non-null", () => {
    // WHY 25/5/10/4/1: the same split used by AnalystMiniBar's own test
    // (25 StrongBuy + 5 Buy = 30B, 10H, 4 Sell + 1 StrongSell = 5S). This
    // makes the rendered summary "30B · 10H · 5S" recognisable across both
    // tests if a debugging session straddles them.
    render(
      <AnalystSidebar
        strongBuy={25}
        buy={5}
        hold={10}
        sell={4}
        strongSell={1}
        targetPrice={150.5}
        updatedAt="2026-05-19T12:00:00Z"
      />,
    );

    // WHY assert on the bar's summary text: presence of "30B · 10H · 5S"
    // can only happen if AnalystMiniBar mounted and ran its bucket-collapse
    // arithmetic. That is the cheapest proof that the bar is in the tree.
    expect(screen.getByText("30B · 10H · 5S")).toBeInTheDocument();

    // WHY also assert the section header is present: pins the sidebar's
    // own structural contract (header → bar → target → timestamp) and
    // catches a regression where the bar renders but the surrounding
    // sidebar chrome disappears.
    expect(screen.getByText("ANALYST CONSENSUS")).toBeInTheDocument();
  });
});
