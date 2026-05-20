/**
 * components/instrument/intelligence/context/__tests__/NodeDetailCard.test.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-E-02): NodeDetailCard is the right-rail card
 * the Intelligence tab swaps in when a graph node is selected (PRD-0088
 * §6.9, T-D-03). It is fully presentational — props in, JSX out — so the
 * relevant contracts are:
 *
 *   1. The selected node's label + normalised type badge render.
 *   2. The Back button fires onBack() when clicked.
 *   3. Node weight (size) is shown ONLY when present; null/undefined size
 *      hides the row entirely (matches the "no description available"
 *      stable-label policy).
 *   4. Ticker row appears only for financial_instrument nodes (truthy ticker);
 *      non-instrument nodes hide it.
 *
 * NOTE on the plan wording "null vs non-null relation_summary": the
 * GraphNode type in types/api.ts does NOT carry a relation_summary field —
 * it has `size` (importance score) and an optional `ticker`. The closest
 * present-vs-absent pair on the current card is the node-weight row
 * (controlled by `typeof node.size === "number"`) and the ticker row
 * (controlled by `node.ticker`). We test both branches.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { NodeDetailCard } from "@/components/instrument/intelligence/context/NodeDetailCard";
import type { GraphNode } from "@/types/api";

/**
 * baseNode — minimal GraphNode skeleton. Tests override per-scenario.
 */
function baseNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "ent-aapl",
    label: "Apple Inc.",
    type: "financial_instrument",
    size: 5.4,
    ticker: "AAPL",
    ...overrides,
  };
}

describe("NodeDetailCard", () => {
  it("renders the node label and normalises the type (underscores → spaces)", () => {
    render(<NodeDetailCard node={baseNode()} onBack={() => {}} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    // WHY "financial instrument" not "financial_instrument": the component
    // does `node.type.replace(/_/g, " ")` for display only.
    expect(screen.getByText("financial instrument")).toBeInTheDocument();
  });

  it("fires onBack when the Back button is clicked", () => {
    const onBack = vi.fn();
    render(<NodeDetailCard node={baseNode()} onBack={onBack} />);
    // The button has an explicit aria-label so screen-reader-style query is stable.
    fireEvent.click(screen.getByRole("button", { name: /back to entity overview/i }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders the node weight row when node.size is a finite number", () => {
    render(<NodeDetailCard node={baseNode({ size: 7.13 })} onBack={() => {}} />);
    // WHY uppercase "NODE WEIGHT": the label uses the uppercase-tracking
    // utility but the underlying text is title-cased; it renders as
    // "Node weight" in the DOM.
    expect(screen.getByText("Node weight")).toBeInTheDocument();
    // toFixed(2) of 7.13 = "7.13".
    expect(screen.getByText("7.13")).toBeInTheDocument();
  });

  it("hides the node weight row when node.size is undefined", () => {
    // WHY: T-E-02 "null vs non-null" — the present-vs-absent contract for
    // the optional metadata row. GraphNode.size is `number | undefined` so
    // we omit it via the spread.
    const noSize: GraphNode = { id: "x", label: "Test", type: "topic" };
    render(<NodeDetailCard node={noSize} onBack={() => {}} />);
    expect(screen.queryByText("Node weight")).not.toBeInTheDocument();
  });

  it("renders the Ticker row for financial_instrument nodes with a ticker", () => {
    render(<NodeDetailCard node={baseNode({ ticker: "AAPL" })} onBack={() => {}} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("hides the Ticker row when ticker is empty / undefined (non-instrument node)", () => {
    // sectors / people / events come back with ticker === "" or undefined.
    render(
      <NodeDetailCard
        node={{ id: "p-1", label: "Tim Cook", type: "person", size: 1.2 }}
        onBack={() => {}}
      />,
    );
    // Label "Ticker" must not appear when there is no ticker to show — this
    // is the "no noise" policy of the panel.
    expect(screen.queryByText("Ticker")).not.toBeInTheDocument();
  });
});
