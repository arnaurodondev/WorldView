/**
 * __tests__/primitives/EmptyState.test.tsx
 *
 * PRD-0089 F1: pins the copyKey → dictionary lookup + condition fallback.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "@/components/primitives/EmptyState";

describe("EmptyState", () => {
  it("renders the resolved title + body from the dictionary", () => {
    render(<EmptyState condition="empty-cold-start" copyKey="portfolio.no-holdings" />);
    expect(screen.getByText("No holdings yet")).toBeInTheDocument();
    expect(
      screen.getByText("Connect a brokerage or enter a manual lot to populate this view."),
    ).toBeInTheDocument();
  });

  it("falls back to generic copy when copyKey is missing", () => {
    render(<EmptyState condition="error" copyKey="does.not.exist" />);
    expect(screen.getByText("Couldn't load")).toBeInTheDocument();
  });

  it("sets aria-live=polite for loading state", () => {
    render(<EmptyState condition="loading" copyKey="generic.loading" />);
    const el = screen.getByRole("status");
    expect(el).toHaveAttribute("aria-live", "polite");
  });
});
