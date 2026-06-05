/**
 * features/chat/components/__tests__/AgentIterationProgress.test.tsx
 *
 * Unit tests for AgentIterationProgress (PLAN-0099 W4). We exercise the
 * actual DOM output via @testing-library/react so a regression in copy /
 * elapsed-time rounding / singular-vs-plural surfaces immediately.
 *
 * WHY isolated unit tests (not just integration): the strip's copy is the
 * user-facing contract. Pinning it here means a typo in
 * "Reasoning over N results…" gets caught at the component layer instead of
 * leaking through to an integration test that may not assert on the exact
 * string.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { AgentIterationProgress } from "../AgentIterationProgress";
import type { AgentIterationEvent } from "@/features/chat/lib/types";

// Small helper to keep test bodies focused on the assertion (not on event
// boilerplate). Defaults reflect "iter 0, just started" which is the first
// event the backend ever emits for a turn.
function makeEvent(overrides: Partial<AgentIterationEvent> = {}): AgentIterationEvent {
  return {
    iteration: 0,
    max_iterations: 8,
    stage: "planning_tools",
    tools_completed_total: 0,
    elapsed_ms: 0,
    ...overrides,
  };
}

describe("AgentIterationProgress", () => {
  it("renders nothing when event is null", () => {
    // WHY check container.firstChild: the component returns null in the
    // initial state. render()'s container has no children when that happens.
    const { container } = render(<AgentIterationProgress event={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders 'Planning approach…' for the planning_tools stage", () => {
    render(
      <AgentIterationProgress event={makeEvent({ stage: "planning_tools" })} />,
    );
    expect(screen.getByText("Planning approach…")).toBeDefined();
  });

  it("renders 'Writing answer…' for the synthesizing stage", () => {
    render(
      <AgentIterationProgress event={makeEvent({ stage: "synthesizing" })} />,
    );
    expect(screen.getByText("Writing answer…")).toBeDefined();
  });

  it("renders 'Step N of M · Reasoning over X results…' for reasoning_over_results", () => {
    // iteration=2 → human-readable Step 3 (we add 1 for 1-indexed display).
    render(
      <AgentIterationProgress
        event={makeEvent({
          stage: "reasoning_over_results",
          iteration: 2,
          max_iterations: 8,
          tools_completed_total: 4,
        })}
      />,
    );
    expect(
      screen.getByText("Step 3 of 8 · Reasoning over 4 results…"),
    ).toBeDefined();
  });

  it("uses singular 'result' when tools_completed_total === 1", () => {
    render(
      <AgentIterationProgress
        event={makeEvent({
          stage: "reasoning_over_results",
          iteration: 0,
          max_iterations: 8,
          tools_completed_total: 1,
        })}
      />,
    );
    // Step 1 of 8 (iteration 0 + 1 = 1), and "1 result" (singular).
    expect(screen.getByText("Step 1 of 8 · Reasoning over 1 result…")).toBeDefined();
  });

  it("uses plural 'results' for 0 tools completed (edge case)", () => {
    // The reasoning stage CAN fire with zero tools completed if the agent
    // bails out before any tool finishes. We still use plural ("0 results")
    // because English convention treats zero as plural.
    render(
      <AgentIterationProgress
        event={makeEvent({
          stage: "reasoning_over_results",
          iteration: 0,
          max_iterations: 8,
          tools_completed_total: 0,
        })}
      />,
    );
    expect(screen.getByText("Step 1 of 8 · Reasoning over 0 results…")).toBeDefined();
  });

  it("rounds elapsed_ms to the nearest whole second for the chip", () => {
    // 1500ms rounds to 2s (Math.round, not Math.floor). Pinned because a
    // future refactor to floor would degrade UX: "1s" while the wall clock
    // shows 1.5s reads as "the strip is slow".
    render(
      <AgentIterationProgress
        event={makeEvent({ stage: "planning_tools", elapsed_ms: 1500 })}
      />,
    );
    expect(screen.getByText("2s")).toBeDefined();
  });

  it("renders '0s' when elapsed_ms is 0 (initial event)", () => {
    render(
      <AgentIterationProgress event={makeEvent({ elapsed_ms: 0 })} />,
    );
    expect(screen.getByText("0s")).toBeDefined();
  });

  it("renders '12s' for 12000ms elapsed", () => {
    render(
      <AgentIterationProgress event={makeEvent({ elapsed_ms: 12000 })} />,
    );
    expect(screen.getByText("12s")).toBeDefined();
  });

  it("exposes role=status with aria-live=polite for screen readers", () => {
    render(<AgentIterationProgress event={makeEvent()} />);
    // role=status announces the strip as a status update; polite ensures
    // it does not interrupt the user's current narration.
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
  });
});
