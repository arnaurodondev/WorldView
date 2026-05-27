/**
 * EntityHealthDot.test.tsx — PLAN-0089 K Block I T-22 case 9.
 *
 * WHAT THIS GUARDS:
 *   - Colour ramps at thresholds: >=0.7 bg-positive, >=0.4 bg-warning,
 *     <0.4 bg-negative. The thresholds must match ContradictionStrip's
 *     so the visual language stays coherent across the chat surface.
 *   - aria-label is informative for screen readers (includes both score
 *     and completeness when present).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { EntityHealthDot } from "../EntityHealthDot";

// WHY wrap in TooltipProvider: Radix Tooltip throws when used outside a
// TooltipProvider context. The chat layout provides one at the page level
// but unit tests must supply it manually.
function withTooltip(ui: React.ReactNode) {
  return <TooltipProvider>{ui}</TooltipProvider>;
}

describe("EntityHealthDot (Wave K T-15)", () => {
  it("uses bg-positive class when score >= 0.7", () => {
    const { container } = render(withTooltip(<EntityHealthDot score={0.85} />));
    expect(container.querySelector(".bg-positive")).not.toBeNull();
  });

  it("uses bg-warning class when 0.4 <= score < 0.7", () => {
    const { container } = render(withTooltip(<EntityHealthDot score={0.55} />));
    expect(container.querySelector(".bg-warning")).not.toBeNull();
  });

  it("uses bg-negative class when score < 0.4", () => {
    const { container } = render(withTooltip(<EntityHealthDot score={0.15} />));
    expect(container.querySelector(".bg-negative")).not.toBeNull();
  });

  it("aria-label includes the score and completeness when both present", () => {
    // WHY this matters: screen-reader users get the same information the
    // dot conveys visually. The format must be deterministic so a11y
    // tests on downstream pages can pin it.
    render(
      withTooltip(
        <EntityHealthDot score={0.85} dataCompleteness={{ populated: 8, total: 10 }} />,
      ),
    );
    const dot = screen.getByRole("img");
    expect(dot.getAttribute("aria-label")).toContain("0.85");
    expect(dot.getAttribute("aria-label")).toContain("8/10");
  });

  it("clamps out-of-range scores to [0,1]", () => {
    // Backend bug guard: a score of 1.7 must not render as 170% or in a
    // disallowed colour bucket.
    const { container } = render(withTooltip(<EntityHealthDot score={1.7} />));
    // Clamped to 1.0 → still bg-positive.
    expect(container.querySelector(".bg-positive")).not.toBeNull();
  });
});
