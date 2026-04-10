import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SeverityBadge } from "../src/components/alerts/SeverityBadge";

describe("SeverityBadge", () => {
  it("renders_LOW_with_grey", () => {
    const { container } = render(<SeverityBadge severity="low" />);
    expect(screen.getByText("LOW")).toBeInTheDocument();
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("bg-gray-100");
    expect(badge.className).toContain("text-gray-600");
  });

  it("renders_MEDIUM_with_yellow", () => {
    const { container } = render(<SeverityBadge severity="medium" />);
    expect(screen.getByText("MED")).toBeInTheDocument();
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("bg-yellow-100");
    expect(badge.className).toContain("text-yellow-700");
  });

  it("renders_HIGH_with_orange", () => {
    const { container } = render(<SeverityBadge severity="high" />);
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("bg-orange-100");
    expect(badge.className).toContain("text-orange-700");
  });

  it("renders_CRITICAL_with_red", () => {
    const { container } = render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("bg-red-100");
    expect(badge.className).toContain("text-red-700");
  });
});
