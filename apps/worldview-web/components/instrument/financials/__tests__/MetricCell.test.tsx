/**
 * components/instrument/financials/__tests__/MetricCell.test.tsx
 *
 * WHY THIS EXISTS: PLAN-0090 §T-C-04 pins one behavioural contract on
 * the grid-cell primitive that backs all 45 fundamentals fields on the
 * Financials tab:
 *
 *   1. test_MetricCell_renders_dash_for_null
 *      A null/missing value must render as the em-dash placeholder "—"
 *      (Bloomberg / Finviz convention for "no data"). MetricCell takes a
 *      pre-formatted `value: string`; the caller passes "—" when its
 *      underlying field is null. This test verifies that contract end-to-
 *      end: caller passes "—" → DOM shows "—".
 *
 * WHY NOT test MetricValue directly: that primitive has its own test
 * (`__tests__/primitives/MetricValue.test.tsx`) which
 * pins the null → "—" behaviour at the source. This file tests the
 * concrete cell as wired into the financials grid — a separate seam.
 *
 * WHY 22px height + label not asserted: those are covered implicitly by
 * the FlatMetricsGrid structural test (which renders dozens of cells)
 * and by visual review. T-C-04 specifies only the null → "—" contract.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { MetricCell } from "@/components/instrument/financials/MetricCell";

describe("MetricCell", () => {
  it("renders the em-dash placeholder when the caller passes a null-coalesced '—' value", () => {
    // WHY pass "—" directly: MetricCell is a pure presentational primitive
    // that accepts a pre-formatted string. In FlatMetricsGrid the SAFE_DASH
    // constant ("—") is passed whenever the underlying field is null —
    // this test verifies that the cell renders that string verbatim into
    // the DOM (and does not, e.g., strip it or replace it).
    render(<MetricCell label="P/E" value="—" />);
    // WHY query by text on "—": same glyph the user sees on the live page.
    // Using getByText pins the contract: the em-dash MUST be in the DOM.
    const placeholder = screen.getByText("—");
    expect(placeholder).toBeInTheDocument();
    // WHY also assert the value span has the font-mono + tabular-nums
    // classes: ADR-F-15 (PLAN-0090 Wave C architecture compliance) requires
    // every MetricCell value to use tabular-nums for column alignment.
    // If a refactor strips those classes the em-dash would still appear
    // but the alignment guarantee would silently regress.
    expect(placeholder).toHaveClass("font-mono");
    expect(placeholder).toHaveClass("tabular-nums");
  });
});
