/**
 * __tests__/prediction-markets-signal-badge.test.tsx — SignalBadge drivers
 * (PLAN-0056 Wave E2, task 4).
 *
 * Pins that each badge variant renders ONLY from its documented driver:
 *   resolved/closed ← market.status; moving ← measured YES Δpp ≥ threshold.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SignalBadge, MOVING_THRESHOLD_PP } from "@/components/prediction-markets/SignalBadge";

describe("SignalBadge", () => {
  it("renders a resolved badge when status is resolved", () => {
    render(<SignalBadge status="resolved" />);
    const badge = screen.getByTestId("signal-badge");
    expect(badge).toHaveAttribute("data-signal", "resolved");
    expect(badge).toHaveTextContent(/resolved/i);
  });

  it("renders a closed badge when status is closed", () => {
    render(<SignalBadge status="closed" />);
    expect(screen.getByTestId("signal-badge")).toHaveAttribute("data-signal", "closed");
  });

  it("renders nothing for a plain open market with no move data", () => {
    const { container } = render(<SignalBadge status="open" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an open market whose move is below threshold", () => {
    const { container } = render(
      <SignalBadge status="open" deltaPp={MOVING_THRESHOLD_PP - 1} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a moving badge when the YES move clears the threshold", () => {
    render(<SignalBadge status="open" deltaPp={MOVING_THRESHOLD_PP + 4} />);
    const badge = screen.getByTestId("signal-badge");
    expect(badge).toHaveAttribute("data-signal", "moving");
    // Positive move rounds and shows a signed pp value.
    expect(badge).toHaveTextContent(`+${MOVING_THRESHOLD_PP + 4}pp`);
  });

  it("prioritises the terminal status badge over a live move", () => {
    // A resolved market whose history moved should still read "resolved", not
    // "moving" — a settled market's move is history, not a signal.
    render(<SignalBadge status="resolved" deltaPp={30} />);
    expect(screen.getByTestId("signal-badge")).toHaveAttribute("data-signal", "resolved");
  });
});
