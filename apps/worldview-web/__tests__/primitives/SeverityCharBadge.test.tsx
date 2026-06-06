/**
 * __tests__/primitives/SeverityCharBadge.test.tsx
 *
 * PRD-0089 F1: pins the glyph + color mapping for the 4 severity levels.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SeverityCharBadge } from "@/components/primitives/SeverityCharBadge";

describe("SeverityCharBadge", () => {
  it("renders ! for critical with destructive color", () => {
    render(<SeverityCharBadge severity="critical" />);
    const el = screen.getByLabelText("severity critical");
    expect(el).toHaveTextContent("!");
    expect(el).toHaveClass("text-destructive");
  });

  it("renders * for high with warning color", () => {
    render(<SeverityCharBadge severity="high" />);
    const el = screen.getByLabelText("severity high");
    expect(el).toHaveTextContent("*");
    expect(el).toHaveClass("text-warning");
  });

  it("renders · for med with muted color", () => {
    render(<SeverityCharBadge severity="med" />);
    const el = screen.getByLabelText("severity med");
    expect(el).toHaveTextContent("·");
    expect(el).toHaveClass("text-muted-foreground");
  });
});
