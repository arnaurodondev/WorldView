/**
 * FollowUpChips.test.tsx — PLAN-0089 K Block I T-22 case 7.
 *
 * WHAT THIS GUARDS:
 *   - 2..4 chip render count: below 2 renders null, above 4 clamps to 4.
 *   - Click on a chip forwards the exact suggestion string to onPick.
 *   - Each chip carries data-cell so it counts toward the density gate.
 */

import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";

import { FollowUpChips } from "../FollowUpChips";

describe("FollowUpChips (Wave K T-13)", () => {
  it("returns null when fewer than 2 suggestions are supplied", () => {
    // WHY: a single chip looks like dead chrome; the spec mandates >=2.
    const { container } = render(
      <FollowUpChips suggestions={["only one"]} onPick={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders all chips when 2..4 are supplied", () => {
    const suggestions = ["a", "b", "c"];
    const { container } = render(
      <FollowUpChips suggestions={suggestions} onPick={vi.fn()} />,
    );
    const chips = container.querySelectorAll("button[data-cell]");
    expect(chips.length).toBe(3);
  });

  it("clamps to MAX_CHIPS=4 when more than 4 are supplied", () => {
    const suggestions = ["a", "b", "c", "d", "e", "f"];
    const { container } = render(
      <FollowUpChips suggestions={suggestions} onPick={vi.fn()} />,
    );
    const chips = container.querySelectorAll("button[data-cell]");
    expect(chips.length).toBe(4);
  });

  it("invokes onPick with the suggestion text on click", () => {
    // WHY exact string match: the caller (chat page) sends the chip text
    // as a chat message. A truncation here would mean the LLM sees a
    // different prompt than the analyst clicked.
    const onPick = vi.fn();
    render(
      <FollowUpChips suggestions={["What's the risk?", "Show evidence"]} onPick={onPick} />,
    );
    fireEvent.click(screen.getByText("What's the risk?"));
    expect(onPick).toHaveBeenCalledWith("What's the risk?");
  });
});
