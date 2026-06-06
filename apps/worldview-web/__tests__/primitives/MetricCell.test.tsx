/**
 * __tests__/primitives/MetricCell.test.tsx
 *
 * PRD-0089 F1: pins the null → em-dash + color prop wiring.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricCell } from "@/components/primitives/MetricCell";

describe("MetricCell", () => {
  it("renders the em-dash placeholder when value is null", () => {
    render(<MetricCell label="P/E" value={null} />);
    const placeholder = screen.getByText("—");
    expect(placeholder).toHaveClass("text-muted-foreground/50");
  });

  it("applies positive color class when color='positive'", () => {
    render(<MetricCell label="Δ" value="+1.23%" color="positive" />);
    const value = screen.getByText("+1.23%");
    expect(value).toHaveClass("text-positive");
    expect(value).toHaveClass("font-mono");
    expect(value).toHaveClass("tabular-nums");
  });

  it("applies left alignment when align='left'", () => {
    render(<MetricCell label="Note" value="hi" align="left" />);
    const cell = screen.getByRole("cell");
    expect(cell.className).toContain("items-start");
  });
});
