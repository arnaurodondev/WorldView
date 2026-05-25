/**
 * __tests__/primitives/LoadingSkeleton.test.tsx
 *
 * PRD-0089 F1: pins the 4 variant renderings.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoadingSkeleton } from "@/components/primitives/LoadingSkeleton";

describe("LoadingSkeleton", () => {
  it("renders a table-row variant with 20px height + pulse animation", () => {
    render(<LoadingSkeleton variant="table-row" />);
    const row = screen.getByRole("row");
    expect(row.className).toContain("h-[20px]");
  });

  it("renders an em-dash for cell variant", () => {
    render(<LoadingSkeleton variant="cell" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders `count` copies when count > 1", () => {
    render(<LoadingSkeleton variant="table-row" count={3} />);
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });
});
