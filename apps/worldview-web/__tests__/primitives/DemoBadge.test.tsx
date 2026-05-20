/**
 * __tests__/primitives/DemoBadge.test.tsx
 *
 * PRD-0089 F1: pins the warning-color outline + aria-label contract.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DemoBadge } from "@/components/primitives/DemoBadge";

describe("DemoBadge", () => {
  it("renders the DEMO chip with warning color border", () => {
    render(<DemoBadge />);
    const el = screen.getByLabelText("Demo portfolio");
    expect(el).toHaveTextContent("Demo");
    expect(el.className).toContain("border-warning");
    expect(el.className).toContain("text-warning");
  });
});
