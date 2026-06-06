/**
 * graph/__tests__/GraphStats.test.tsx — W7 T-23
 *
 * WHY THIS EXISTS: GraphStats is the 18px status strip below the brief.
 * Pins 3 contracts:
 *  1. Renders node/edge/depth counts as "N nodes · N edges · depth N · N ms".
 *  2. latencyMs=null → "— ms" fallback.
 *  3. Strip carries h-[18px] (density gate).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GraphStats } from "@/components/instrument/intelligence/graph/GraphStats";

describe("GraphStats", () => {
  it("renders node, edge, depth, and latency counts", () => {
    render(<GraphStats nodeCount={24} edgeCount={41} depth={2} latencyMs={312} />);
    const text = screen.getByText(/24 nodes/);
    expect(text.textContent).toContain("41 edges");
    expect(text.textContent).toContain("depth 2");
    expect(text.textContent).toContain("312 ms");
  });

  it("shows '—' when latencyMs is null", () => {
    const { container } = render(
      <GraphStats nodeCount={0} edgeCount={0} depth={1} latencyMs={null} />,
    );
    // GraphStats aria-label contains the latency value; "—" is the null placeholder
    const el = container.querySelector("[aria-label]");
    expect(el?.getAttribute("aria-label")).toContain("—");
  });

  it("carries the h-[18px] density class", () => {
    const { container } = render(
      <GraphStats nodeCount={5} edgeCount={3} depth={1} latencyMs={100} />,
    );
    const strip = container.querySelector("[class*='h-\\[18px\\]']");
    expect(strip).not.toBeNull();
  });
});
