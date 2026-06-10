/**
 * components/instrument/shared/__tests__/EmptyState.test.tsx
 *
 * WHY THIS EXISTS (Round-1 Foundation, requirement 4): the named empty state
 * (icon + headline) replaces bare italic sentences across the Intelligence
 * tab. These tests pin the contract every consumer relies on: role="status"
 * semantics, icon presence, headline + optional hint rendering.
 */

import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { Newspaper } from "lucide-react";
import { EmptyState } from "@/components/instrument/shared/EmptyState";

afterEach(() => cleanup());

describe("EmptyState", () => {
  it("renders the headline and hint with role=status", () => {
    render(
      <EmptyState
        icon={Newspaper}
        headline="No articles yet"
        hint="Articles appear as the pipeline links coverage."
      />,
    );
    const state = screen.getByRole("status");
    expect(state).toBeInTheDocument();
    expect(screen.getByText("No articles yet")).toBeInTheDocument();
    expect(
      screen.getByText("Articles appear as the pipeline links coverage."),
    ).toBeInTheDocument();
  });

  it("renders an icon (svg) so the state is scannable", () => {
    const { container } = render(
      <EmptyState icon={Newspaper} headline="No articles yet" />,
    );
    // lucide icons render as inline <svg> elements.
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("omits the hint paragraph when not provided", () => {
    render(<EmptyState icon={Newspaper} headline="No articles yet" />);
    const state = screen.getByRole("status");
    // Only the icon+headline row — no second paragraph.
    expect(state.querySelectorAll("p").length).toBe(1);
  });

  it("supports the inline variant for stacked-rail sub-sections", () => {
    render(
      <EmptyState
        icon={Newspaper}
        headline="No contradictions detected"
        variant="inline"
      />,
    );
    const state = screen.getByRole("status");
    // inline → left-aligned compact padding (block variant centres with py-8).
    expect(state.className).toContain("py-2");
    expect(state.className).not.toContain("py-8");
  });
});
