/**
 * __tests__/primitives/Sparkline.test.tsx
 *
 * PRD-0089 F1: pins the trend="auto" ±0.1% threshold + null-safe rendering.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "@/components/primitives/Sparkline";

describe("Sparkline", () => {
  it("renders the dotted-line empty-state for empty data", () => {
    const { container } = render(<Sparkline data={[]} />);
    const line = container.querySelector("line");
    expect(line).not.toBeNull();
    expect(line?.getAttribute("stroke-dasharray")).toBe("2 2");
  });

  it("auto-detects positive trend when last>first by ≥0.1%", () => {
    const { container } = render(<Sparkline data={[100, 100.5]} />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-positive");
  });

  it("auto-detects negative trend when last<first by ≤-0.1%", () => {
    const { container } = render(<Sparkline data={[100, 99.5]} />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-negative");
  });

  it("resolves flat when delta is within ±0.1%", () => {
    const { container } = render(<Sparkline data={[100, 100.05]} />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-muted-foreground");
  });
});
