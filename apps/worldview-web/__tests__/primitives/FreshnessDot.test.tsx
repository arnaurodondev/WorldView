/**
 * __tests__/primitives/FreshnessDot.test.tsx
 *
 * PRD-0089 F1: pins the status → color mapping and the rounded-full
 * allowance (sole sharp-corners exception for dots).
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FreshnessDot } from "@/components/primitives/FreshnessDot";

describe("FreshnessDot", () => {
  it("renders live with positive color", () => {
    render(<FreshnessDot status="live" />);
    const el = screen.getByLabelText("live data");
    expect(el).toHaveClass("bg-positive");
    expect(el).toHaveClass("rounded-full");
  });

  it("renders stale with warning color", () => {
    render(<FreshnessDot status="stale" />);
    const el = screen.getByLabelText("stale data");
    expect(el).toHaveClass("bg-warning");
  });

  it("renders closed with muted-foreground color", () => {
    render(<FreshnessDot status="closed" />);
    const el = screen.getByLabelText("market closed");
    expect(el).toHaveClass("bg-muted-foreground");
  });
});
