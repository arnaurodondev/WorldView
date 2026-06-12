/**
 * GraphControls.test.tsx — PLAN-0099 W4 (filters-don't-fully-work fix)
 *
 * WHY THIS EXISTS: the relation-type pills + strength slider only HIDE edges
 * inside sigma's WebGL reducer — the graph frame itself looks unchanged, so the
 * analyst perceived the pills as no-ops. W4 adds a "X of Y edges" indicator that
 * renders whenever visibleEdgeCount < edgeCount. These tests pin:
 *   - the indicator appears (with the right counts) when a filter hides edges
 *   - the indicator is ABSENT when nothing is filtered out (visible == total)
 *   - clicking a relation pill fires onRelFilterChange (the param actually moves)
 *
 * sigma/WebGL is NOT involved here — GraphControls is a pure presentational
 * component, so it renders cleanly in jsdom without the canvas.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { GraphControls } from "@/components/instrument/graph/GraphControls";

afterEach(cleanup);

// Minimal prop factory — only the fields each test cares about are overridden.
function renderControls(overrides: Partial<React.ComponentProps<typeof GraphControls>> = {}) {
  const props = {
    activeRelFilter: "all" as const,
    minWeight: 0,
    searchQuery: "",
    layout: "force" as const,
    edgeCount: 71,
    visibleEdgeCount: 71,
    denseGraphEdgeThreshold: 50,
    onRelFilterChange: vi.fn(),
    onMinWeightChange: vi.fn(),
    onSearchQueryChange: vi.fn(),
    onLayoutChange: vi.fn(),
    ...overrides,
  };
  render(<GraphControls {...props} />);
  return props;
}

describe("GraphControls — filter feedback (W4)", () => {
  it('shows "X of Y edges" when a filter has hidden some edges', () => {
    // 20 of 71 visible → the relation pill / strength slider DID something.
    renderControls({ visibleEdgeCount: 20, edgeCount: 71, activeRelFilter: "investor" });
    const badge = screen.getByTestId("visible-edge-count");
    expect(badge.textContent).toContain("20 of 71 edges");
  });

  it("does NOT show the filtered-count badge when nothing is hidden", () => {
    // visible == total → no filter active → the badge must not appear.
    renderControls({ visibleEdgeCount: 71, edgeCount: 71 });
    expect(screen.queryByTestId("visible-edge-count")).toBeNull();
  });

  it("fires onRelFilterChange when a relation pill is clicked (param actually moves)", () => {
    const props = renderControls();
    fireEvent.click(screen.getByTestId("filter-pill-investor"));
    expect(props.onRelFilterChange).toHaveBeenCalledWith("investor");
  });
});
