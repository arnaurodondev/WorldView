/**
 * __tests__/primitives/MetricLabel.test.tsx
 *
 * PRD-0089 F1: pins the truncation + 10px uppercase contract so any per-page
 * agent that switches to <MetricLabel> gets the same look as Quote/Financials.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricLabel } from "@/components/primitives/MetricLabel";

describe("MetricLabel", () => {
  it("renders the uppercase tracking-wide label class", () => {
    render(<MetricLabel>Market Cap</MetricLabel>);
    const el = screen.getByText("Market Cap");
    expect(el).toHaveClass("text-[10px]");
    expect(el).toHaveClass("uppercase");
    expect(el).toHaveClass("truncate");
  });
});
