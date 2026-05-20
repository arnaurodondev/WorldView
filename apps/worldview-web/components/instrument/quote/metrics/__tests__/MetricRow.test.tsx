/**
 * components/instrument/quote/metrics/__tests__/MetricRow.test.tsx
 *
 * WHY THIS EXISTS: MetricRow (and the sibling MetricGroupDivider) are the
 * structural primitives behind every row of the right-rail Statistics table
 * (PRD-0088 §6.7.2). PLAN-0090 §T-B-05 pins three behavioural contracts
 * here so future refactors cannot silently regress the 22px row rhythm:
 *
 *   1. test_MetricRow_renders_null_as_dash
 *      A `null` (or undefined) `value` prop must render the muted em-dash
 *      placeholder — proving the row delegates "missing data" semantics to
 *      MetricValue rather than reinventing them.
 *
 *   2. test_MetricRow_applies_color_class
 *      The `color="negative"` prop must propagate into the rendered value's
 *      `text-negative` className. That guarantees the threshold-colour
 *      helpers in MetricsTable (peColor, betaColor, …) actually paint cells.
 *
 *   3. test_MetricGroupDivider_renders_hr
 *      MetricGroupDivider must render a thin horizontal divider element
 *      (1px tall, border-class styled) so visual group breaks survive a
 *      Tailwind class rename or a refactor that swaps the underlying tag.
 *
 * If any of these break, dozens of downstream stat rows quietly mis-render
 * and the QA gate at the end of Wave B should fail — this test catches it
 * at PR time on the change itself.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricRow } from "@/components/instrument/quote/metrics/MetricRow";
import { MetricGroupDivider } from "@/components/instrument/quote/metrics/MetricGroupDivider";

describe("MetricRow", () => {
  it("renders the em-dash placeholder when value is null", () => {
    // WHY render with value=null explicitly: we are testing that MetricRow
    // forwards null to MetricValue (the single source of truth for the
    // placeholder glyph). Asserting on the literal "—" character verifies
    // the user-visible string, not an internal helper.
    render(<MetricRow label="P/E" value={null} />);
    const dash = screen.getByText("—");
    expect(dash).toBeInTheDocument();
    // WHY muted/50 class: PRD-0088 §6.11 — absent data must be visually
    // de-emphasised so it does not compete with real values on the row.
    expect(dash).toHaveClass("text-muted-foreground/50");
  });

  it("applies the negative colour class when color='negative' is passed", () => {
    // WHY use a numeric-looking string for value: matches real-world calls
    // from MetricsTable where threshold-colour helpers return "negative".
    render(<MetricRow label="P/E" value="62.5" color="negative" />);
    const valueNode = screen.getByText("62.5");
    // WHY assert text-negative directly: MetricsTable depends on this exact
    // class token for FR-10 threshold colouring. A rename would break the
    // colour semantics across the entire Statistics table.
    expect(valueNode).toHaveClass("text-negative");
  });
});

describe("MetricGroupDivider", () => {
  it("renders a 1px-tall divider element with a border-coloured background", () => {
    // WHY use container (not getByRole): the divider is a div with no
    // semantic role; querying by class is the most stable contract because
    // MetricsTable's group cadence depends on the hairline being visible.
    const { container } = render(<MetricGroupDivider />);
    const divider = container.firstElementChild as HTMLElement | null;
    expect(divider).not.toBeNull();
    // WHY h-[1px] + bg-border/30: the WHY notes in MetricGroupDivider.tsx
    // explicitly pin these (a "whisper, not a shout" between row groups);
    // breaking either would shift the 22px row rhythm or hide the divider.
    expect(divider).toHaveClass("h-[1px]");
    expect(divider).toHaveClass("bg-border/30");
  });
});
