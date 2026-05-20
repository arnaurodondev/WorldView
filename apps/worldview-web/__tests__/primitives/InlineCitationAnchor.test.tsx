/**
 * __tests__/primitives/InlineCitationAnchor.test.tsx
 *
 * PRD-0089 F1: pins the kind→color mapping + onActivate handler wiring.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InlineCitationAnchor } from "@/components/primitives/InlineCitationAnchor";

describe("InlineCitationAnchor", () => {
  it("renders the kind-prefixed label by default", () => {
    render(<InlineCitationAnchor kind="SEC" id="42" />);
    expect(screen.getByText("[sec-42]")).toBeInTheDocument();
  });

  it("applies positive color for SEC and warning color for BRF", () => {
    const { container, rerender } = render(<InlineCitationAnchor kind="SEC" id="1" />);
    let anchor = container.querySelector('[role="link"]');
    expect(anchor?.className).toContain("text-positive");
    rerender(<InlineCitationAnchor kind="BRF" id="2" />);
    anchor = container.querySelector('[role="link"]');
    expect(anchor?.className).toContain("text-warning");
  });

  it("calls onActivate on click", () => {
    const onActivate = vi.fn();
    render(<InlineCitationAnchor kind="NEWS" id="7" onActivate={onActivate} />);
    fireEvent.click(screen.getByText("[news-7]"));
    expect(onActivate).toHaveBeenCalledWith("NEWS", "7");
  });
});
