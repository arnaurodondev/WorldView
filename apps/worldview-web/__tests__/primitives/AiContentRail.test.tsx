/**
 * __tests__/primitives/AiContentRail.test.tsx
 *
 * PRD-0089 F1: pins the accent-ai violet left-rail contract.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AiContentRail } from "@/components/primitives/AiContentRail";

describe("AiContentRail", () => {
  it("wraps children with the accent-ai left rail", () => {
    render(
      <AiContentRail>
        <p>AI-generated brief</p>
      </AiContentRail>,
    );
    const text = screen.getByText("AI-generated brief");
    const wrapper = text.parentElement;
    expect(wrapper?.getAttribute("data-ai-content")).toBe("true");
    expect(wrapper?.className).toContain("border-l-2");
    expect(wrapper?.className).toContain("--accent-ai");
  });
});
