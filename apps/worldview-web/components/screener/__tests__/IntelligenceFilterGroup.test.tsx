/**
 * components/screener/__tests__/IntelligenceFilterGroup.test.tsx
 * (PRD-0089 Wave I-A · Block D · T-IA-12)
 *
 * WHY: the IntelligenceFilterGroup ships 7 filter rows whose backends land
 * in Wave L-5. Each row carries a BackendPendingBadge while
 * `backendReady.X === false` (the I-A baseline). When the L-5 sub-tasks
 * land, individual flags flip to true and the badge disappears.
 *
 * Pin both states (badge shown when not ready; badge absent when ready)
 * so a regression that breaks the gating cannot ship silently.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IntelligenceFilterGroup } from "@/components/screener/IntelligenceFilterGroup";
import { DEFAULT_FILTERS } from "@/features/screener/lib/filter-state";

describe("IntelligenceFilterGroup", () => {
  it("renders 7 filter rows in the Wave I-A baseline (all disabled)", () => {
    // WHY: the plan's row count is exactly 7. Locking it ensures a future
    // edit doesn't drop or duplicate a row by accident — the design table
    // lists the canonical labels.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    // Each row exposes a disabled <input aria-label="… filter (backend pending)">.
    const inputs = screen.getAllByLabelText(/filter \(backend pending\)/i);
    expect(inputs).toHaveLength(7);
    for (const input of inputs) {
      expect(input).toBeDisabled();
    }
  });

  it("shows BackendPendingBadge on every row when backendReady is undefined", () => {
    // WHY: undefined backendReady = the I-A baseline. Every row must show
    // the warning badge so users see the roadmap. Counting role=status
    // gives us the badge count without grepping for the literal copy.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
      />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(7);
  });

  it("hides the badge on rows whose backendReady flag is true", () => {
    // WHY: this is the contract that lets Wave I-B flip individual flags
    // when their L-5 sub-task lands. Flipping `newsCount7d` → true should
    // strip exactly one badge; the other 6 stay.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{ newsCount7d: true }}
      />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(6);
  });

  it("hides all badges when every backendReady flag is true (post-L-5)", () => {
    // WHY: the final state — all L-5 rollups shipped — must produce zero
    // badges. Asserting the upper bound pairs with the lower bound above.
    render(
      <IntelligenceFilterGroup
        value={DEFAULT_FILTERS}
        onChange={() => {}}
        backendReady={{
          newsCount7d: true,
          aiBrief: true,
          activeAlert: true,
          contradictions: true,
          llmRelevance: true,
          upcomingEarnings: true,
          upcomingDividend: true,
        }}
      />,
    );
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });
});
