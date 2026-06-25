/**
 * detail/__tests__/NodeInspector.test.tsx — PLAN-0099 Wave 2.
 *
 * PORTED ASSERTIONS from the retired NodeDetailCard.test.tsx (the inspector
 * replaced that card):
 *   1. label + normalised type badge ("financial_instrument" → "financial instrument")
 *   2. "Node weight" row ONLY when node.size is a finite number
 *   3. "Ticker" row ONLY for nodes with a truthy ticker
 *
 * NEW WAVE-2 CONTRACTS:
 *   - "Open instrument" action renders only for ticker-bearing nodes and
 *     navigates to /instruments/{ticker}
 *   - "Focus graph here" fires onFocusNode(nodeId) — and hides itself for
 *     off-graph selections (graphNode null)
 *   - top_relations from the enriched detail render with summaries and fire
 *     onSelectRelation(relation_id)
 *   - off-graph selections (graphNode null) render identity from the
 *     entity-detail fetch instead of dead-ending
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const mockPush = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mockPush }) }));

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: { user_id: "u1", tenant_id: "t1", email: "a@b.com", name: "A", avatar_url: null },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

const mockGetEntityDetail = vi.hoisted(() => vi.fn());
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ getEntityDetail: mockGetEntityDetail })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  },
}));

import { NodeInspector } from "@/components/instrument/intelligence/detail/NodeInspector";
import type { GraphNode } from "@/types/api";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

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

const renderInspector = (ui: React.ReactElement) => render(ui, { wrapper });

beforeEach(() => {
  mockPush.mockReset();
  mockGetEntityDetail.mockReset();
  mockGetEntityDetail.mockResolvedValue({
    entity_id: "ent-aapl",
    canonical_name: "Apple Inc.",
    entity_type: "financial_instrument",
    description: "Test entity description.",
    metadata: {},
  });
});

afterEach(() => cleanup());

describe("NodeInspector (ported NodeDetailCard contracts)", () => {
  it("renders the node label and normalises the type (underscores → spaces)", () => {
    renderInspector(<NodeInspector nodeId="ent-aapl" graphNode={baseNode()} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("financial instrument")).toBeInTheDocument();
  });

  it("renders the node weight row when node.size is a finite number", () => {
    renderInspector(<NodeInspector nodeId="ent-aapl" graphNode={baseNode({ size: 7.13 })} />);
    expect(screen.getByText("Node weight")).toBeInTheDocument();
    expect(screen.getByText("7.13")).toBeInTheDocument();
  });

  it("hides the node weight row when node.size is undefined", () => {
    const noSize: GraphNode = { id: "x", label: "Test", type: "topic" };
    mockGetEntityDetail.mockResolvedValue(null);
    renderInspector(<NodeInspector nodeId="x" graphNode={noSize} />);
    expect(screen.queryByText("Node weight")).not.toBeInTheDocument();
  });

  it("renders the Ticker row for financial_instrument nodes with a ticker", () => {
    renderInspector(<NodeInspector nodeId="ent-aapl" graphNode={baseNode({ ticker: "AAPL" })} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    // AAPL appears in both the ticker row and the open-instrument context —
    // assert at least one match (getAllByText) for the row value.
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
  });

  it("hides the Ticker row when ticker is empty / undefined (non-instrument node)", () => {
    mockGetEntityDetail.mockResolvedValue(null);
    renderInspector(
      <NodeInspector
        nodeId="p-1"
        graphNode={{ id: "p-1", label: "Tim Cook", type: "person", size: 1.2 }}
      />,
    );
    expect(screen.queryByText("Ticker")).not.toBeInTheDocument();
  });
});

describe("NodeInspector Wave-2 actions", () => {
  it("navigates to /instruments/{ticker} via the Open instrument action", () => {
    renderInspector(<NodeInspector nodeId="ent-aapl" graphNode={baseNode()} />);
    fireEvent.click(screen.getByTestId("node-open-instrument"));
    expect(mockPush).toHaveBeenCalledWith("/instruments/AAPL");
  });

  it("hides the Open instrument action for ticker-less nodes", () => {
    mockGetEntityDetail.mockResolvedValue(null);
    renderInspector(
      <NodeInspector
        nodeId="p-1"
        graphNode={{ id: "p-1", label: "Tim Cook", type: "person" }}
      />,
    );
    expect(screen.queryByTestId("node-open-instrument")).not.toBeInTheDocument();
  });

  it("fires onFocusNode(nodeId) via the Focus graph here action", () => {
    const onFocusNode = vi.fn();
    renderInspector(
      <NodeInspector nodeId="ent-aapl" graphNode={baseNode()} onFocusNode={onFocusNode} />,
    );
    fireEvent.click(screen.getByTestId("node-focus-graph"));
    expect(onFocusNode).toHaveBeenCalledWith("ent-aapl");
  });

  it("hides Focus graph here for OFF-GRAPH selections (graphNode null)", () => {
    renderInspector(
      <NodeInspector nodeId="ent-aapl" graphNode={null} onFocusNode={vi.fn()} />,
    );
    expect(screen.queryByTestId("node-focus-graph")).not.toBeInTheDocument();
  });

  it("renders identity from the entity-detail fetch for off-graph selections", async () => {
    renderInspector(<NodeInspector nodeId="ent-aapl" graphNode={null} />);
    // canonical_name arrives from the mocked detail fetch — no GraphNode needed.
    await waitFor(() => {
      expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    });
    expect(screen.getByText("Test entity description.")).toBeInTheDocument();
  });

  it("renders enriched top relations and fires onSelectRelation on click", async () => {
    mockGetEntityDetail.mockResolvedValue({
      entity_id: "ent-aapl",
      canonical_name: "Apple Inc.",
      entity_type: "financial_instrument",
      description: "Test entity description.",
      metadata: {},
      relation_count: 2,
      top_relations: [
        {
          relation_id: "rel-9",
          canonical_type: "competes_with",
          direction: "outbound",
          other_entity_id: "ent-msft",
          other_entity_name: "Microsoft",
          other_entity_type: "financial_instrument",
          confidence: 0.7,
          evidence_count: 3,
          relation_summary: "Both compete in consumer devices.",
        },
      ],
    });
    const onSelectRelation = vi.fn();
    renderInspector(
      <NodeInspector nodeId="ent-aapl" graphNode={baseNode()} onSelectRelation={onSelectRelation} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("node-relation-rel-9")).toBeInTheDocument();
    });
    // The LLM summary renders under the row for in-place triage.
    expect(screen.getByText(/Both compete in consumer devices/)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("node-relation-rel-9"));
    expect(onSelectRelation).toHaveBeenCalledWith("rel-9");
  });
});
