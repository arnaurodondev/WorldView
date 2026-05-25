/**
 * components/instrument/shared/__tests__/MetricValue.test.tsx
 *
 * WHY THIS EXISTS: MetricValue is the single source of truth for how a
 * numeric metric renders on the instrument page (PRD-0088 §6.11). These
 * tests pin three contracts that the rest of the redesign depends on:
 *   1. null / undefined children render the "—" placeholder (NOT "null"
 *      text, NOT an empty span) — so finance UX is preserved everywhere.
 *   2. color="positive" applies `text-positive` (green) — gain semantics.
 *   3. color="negative" applies `text-negative` (red) — loss semantics.
 *
 * If a refactor breaks any of these, dozens of downstream metric rows
 * silently change appearance — this file catches that at PR time.
 * DESIGN REFERENCE: docs/plans/0090-instrument-detail-page-redesign-plan.md
 *   §T-A-06 (the 3 MetricValue tests listed in the test table).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricValue } from "@/components/primitives/MetricValue";

describe("MetricValue", () => {
  it("renders the em-dash placeholder when children is null", () => {
    render(<MetricValue>{null}</MetricValue>);
    // WHY query by text: the em-dash glyph is what the user sees; if the
    // implementation accidentally renders "null" or "" this assertion fails.
    const placeholder = screen.getByText("—");
    expect(placeholder).toBeInTheDocument();
    // WHY check the muted/50 class: spec says missing data must be
    // de-emphasised so it does not compete with real values on the row.
    expect(placeholder).toHaveClass("text-muted-foreground/50");
  });

  it("applies text-positive class when color='positive'", () => {
    render(<MetricValue color="positive">+1.23%</MetricValue>);
    const node = screen.getByText("+1.23%");
    // WHY assert exact class token: downstream theming relies on the
    // semantic class name `text-positive`, not the raw colour value.
    expect(node).toHaveClass("text-positive");
  });

  it("applies text-negative class when color='negative'", () => {
    render(<MetricValue color="negative">-2.34%</MetricValue>);
    const node = screen.getByText("-2.34%");
    expect(node).toHaveClass("text-negative");
  });
});
