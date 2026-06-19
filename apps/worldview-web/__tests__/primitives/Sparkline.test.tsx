/**
 * __tests__/primitives/Sparkline.test.tsx
 *
 * PRD-0089 F1: pins the trend="auto" ±0.1% threshold + null-safe rendering.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Sparkline } from "@/components/primitives/Sparkline";

describe("Sparkline", () => {
  it("renders a clean FLAT BASELINE (no dotted line) for empty data", () => {
    // Design QA 2026-06-18 (cross-cutting #1): the empty/short-series state must
    // be a calm solid baseline, NOT a dotted placeholder that reads as a broken
    // or perpetually-loading chart. We assert a single line exists with NO
    // stroke-dasharray (solid) — the visual contract for "no data / flat".
    const { container } = render(<Sparkline data={[]} />);
    const line = container.querySelector("line");
    expect(line).not.toBeNull();
    // Solid line: the dasharray attribute must be absent (was "2 2" before).
    expect(line?.getAttribute("stroke-dasharray")).toBeNull();
    // Still a single horizontal baseline at the vertical midpoint.
    expect(line?.getAttribute("y1")).toBe(line?.getAttribute("y2"));
  });

  it("renders the same flat baseline for a single-point series (<2)", () => {
    // A one-element array can't form a line; it must fall into the empty branch
    // and render the same clean baseline (not a dot, not a dotted line).
    const { container } = render(<Sparkline data={[100]} />);
    const line = container.querySelector("line");
    expect(line).not.toBeNull();
    expect(line?.getAttribute("stroke-dasharray")).toBeNull();
    // No <path> (that's only for real ≥2-point series).
    expect(container.querySelector("path")).toBeNull();
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
