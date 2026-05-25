/**
 * __tests__/primitives/SectionDivider.test.tsx
 *
 * PRD-0089 F1: pins the col-span-3 contract and the new border-subtle token.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionDivider } from "@/components/primitives/SectionDivider";

describe("SectionDivider", () => {
  it("renders the 1px divider with border-subtle background and col-span-3", () => {
    const { container } = render(<SectionDivider />);
    const line = container.querySelector("div.h-\\[1px\\]");
    expect(line?.className).toContain("bg-border-subtle");
    expect(line?.className).toContain("col-span-3");
  });

  it("renders the uppercase label when provided", () => {
    render(<SectionDivider label="VALUATION" />);
    expect(screen.getByText("VALUATION")).toBeInTheDocument();
  });
});
