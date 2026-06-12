/**
 * detail/__tests__/SelectionDetailPanel.test.tsx — PLAN-0099 Wave 2.
 *
 * Pins the inspector's three-mode dispatch (edge > node > NAMED empty) and
 * the clear affordances (X button + Esc key). The child inspectors are
 * stubbed — their internals are pinned by EdgeInspector.test / NodeInspector.test.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import type { ReactNode } from "react";

vi.mock("@/components/instrument/intelligence/detail/EdgeInspector", () => ({
  EdgeInspector: ({ relationId }: { relationId: string }) => (
    <div data-testid="edge-inspector-stub">{relationId}</div>
  ),
}));

vi.mock("@/components/instrument/intelligence/detail/NodeInspector", () => ({
  NodeInspector: ({ nodeId, graphNode }: { nodeId: string; graphNode?: unknown }) => (
    <div data-testid="node-inspector-stub" data-has-graph-node={graphNode ? "yes" : "no"}>
      {nodeId}
    </div>
  ),
}));

import { SelectionDetailPanel } from "@/components/instrument/intelligence/detail/SelectionDetailPanel";

// One QueryClient per test — the panel reads the graph cache slot directly.
let qc: QueryClient;

function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof SelectionDetailPanel>> = {}) {
  return render(
    <Wrapper>
      <SelectionDetailPanel
        entityId="ent-001"
        selectedNodeId={null}
        selectedEdgeId={null}
        onClear={vi.fn()}
        onSelectNode={vi.fn()}
        onSelectRelation={vi.fn()}
        onFocusNode={vi.fn()}
        onDiscuss={vi.fn()}
        {...overrides}
      />
    </Wrapper>,
  );
}

beforeEach(() => {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(() => cleanup());

describe("SelectionDetailPanel mode dispatch", () => {
  it("renders the NAMED empty state when nothing is selected (never blank)", () => {
    renderPanel();
    const empty = screen.getByTestId("inspector-empty");
    expect(empty).toBeInTheDocument();
    expect(screen.getByText("Select a node or edge to inspect")).toBeInTheDocument();
    // role=status + icon svg: the house named-empty-state anatomy.
    expect(empty.getAttribute("role")).toBe("status");
    expect(empty.querySelector("svg")).not.toBeNull();
    // No clear button without a selection.
    expect(screen.queryByRole("button", { name: /clear selection/i })).not.toBeInTheDocument();
  });

  it("renders the edge inspector when an edge is selected", () => {
    renderPanel({ selectedEdgeId: "rel-1" });
    expect(screen.getByTestId("edge-inspector-stub")).toHaveTextContent("rel-1");
    expect(screen.getByText("Inspector · Relation")).toBeInTheDocument();
  });

  it("prefers edge mode when BOTH ids are set (edge selection cleared node)", () => {
    // Defensive: the parent enforces mutual exclusion, but if both ever leak
    // through, edge wins (checking node first would shadow edge forever).
    renderPanel({ selectedEdgeId: "rel-1", selectedNodeId: "n-1" });
    expect(screen.getByTestId("edge-inspector-stub")).toBeInTheDocument();
    expect(screen.queryByTestId("node-inspector-stub")).not.toBeInTheDocument();
  });

  it("renders the node inspector with the graph payload when the node is in the cached graph", () => {
    qc.setQueryData(qk.instruments.entityGraph("ent-001", 2), {
      entity_id: "ent-001",
      nodes: [{ id: "n-1", label: "Tim Cook", type: "person" }],
      edges: [],
    });
    renderPanel({ selectedNodeId: "n-1" });
    const stub = screen.getByTestId("node-inspector-stub");
    expect(stub).toHaveTextContent("n-1");
    expect(stub.getAttribute("data-has-graph-node")).toBe("yes");
    expect(screen.getByText("Inspector · Entity")).toBeInTheDocument();
  });

  it("still renders the node inspector (off-graph mode) when the node is NOT in the graph cache", () => {
    renderPanel({ selectedNodeId: "n-unknown" });
    const stub = screen.getByTestId("node-inspector-stub");
    expect(stub).toHaveTextContent("n-unknown");
    expect(stub.getAttribute("data-has-graph-node")).toBe("no");
  });
});

describe("SelectionDetailPanel clear affordances", () => {
  it("fires onClear when the X button is clicked", () => {
    const onClear = vi.fn();
    renderPanel({ selectedEdgeId: "rel-1", onClear });
    fireEvent.click(screen.getByRole("button", { name: /clear selection/i }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("fires onClear on Escape (window-level)", () => {
    const onClear = vi.fn();
    renderPanel({ selectedNodeId: "n-1", onClear });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("does NOT clear on Escape while typing in an input", () => {
    const onClear = vi.fn();
    render(
      <Wrapper>
        <input data-testid="ext-input" />
        <SelectionDetailPanel
          entityId="ent-001"
          selectedNodeId="n-1"
          selectedEdgeId={null}
          onClear={onClear}
          onSelectNode={vi.fn()}
          onSelectRelation={vi.fn()}
          onFocusNode={vi.fn()}
          onDiscuss={vi.fn()}
        />
      </Wrapper>,
    );
    fireEvent.keyDown(screen.getByTestId("ext-input"), { key: "Escape" });
    expect(onClear).not.toHaveBeenCalled();
  });

  it("does NOT register the Esc handler when nothing is selected", () => {
    const onClear = vi.fn();
    renderPanel({ onClear });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClear).not.toHaveBeenCalled();
  });
});
