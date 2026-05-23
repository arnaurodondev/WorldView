/**
 * context/__tests__/TopRelationsBlock.test.tsx — W7 T-23
 *
 * Pins 5 contracts:
 *  1. Empty graph → "No direct relations."
 *  2. Renders rows sorted by weight (heaviest first).
 *  3. Clicking a row calls onNodeSelect with the target node ID.
 *  4. F-158: inbound edges are rendered (neighbor is edge.source).
 *  5. F-158: both inbound and outbound edges appear when graph has mixed directions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
}));

const mockGateway = vi.hoisted(() => ({ getEntityGraph: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  useApiClient: vi.fn(() => mockGateway),
}));

import { TopRelationsBlock } from "@/components/instrument/intelligence/context/TopRelationsBlock";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockGateway.getEntityGraph.mockReset(); });

interface EdgeSpec {
  source: string;
  target: string;
  label: string;
  weight: number;
  direction?: "outbound" | "inbound" | "lateral";
}

function makeGraph(edges: EdgeSpec[]) {
  return {
    entity_id: "ent-001",
    nodes: [
      { id: "ent-001", label: "Apple Inc.", type: "financial_instrument", size: 10 },
      { id: "ent-tsmc", label: "TSMC", type: "financial_instrument", size: 5 },
      { id: "ent-inv", label: "Berkshire", type: "financial_instrument", size: 4 },
    ],
    edges: edges.map((e) => ({ ...e, id: `${e.source}-${e.target}` })),
  };
}

describe("TopRelationsBlock", () => {
  it("shows empty state when graph has no edges from entityId", async () => {
    mockGateway.getEntityGraph.mockResolvedValue(makeGraph([]));
    render(
      <Wrapper>
        <TopRelationsBlock entityId="ent-001" onNodeSelect={vi.fn()} />
      </Wrapper>,
    );
    await waitFor(() => screen.getByText("No direct relations."));
  });

  it("calls onNodeSelect with target when row clicked", async () => {
    const onNodeSelect = vi.fn();
    mockGateway.getEntityGraph.mockResolvedValue(makeGraph([
      { source: "ent-001", target: "ent-tsmc", label: "SUPPLIER_OF", weight: 0.8 },
    ]));
    render(
      <Wrapper>
        <TopRelationsBlock entityId="ent-001" onNodeSelect={onNodeSelect} />
      </Wrapper>,
    );
    await waitFor(() => screen.getByText("TSMC"));
    fireEvent.click(screen.getByText("TSMC").closest("button")!);
    expect(onNodeSelect).toHaveBeenCalledWith("ent-tsmc");
  });

  it("sorts rows by weight descending", async () => {
    mockGateway.getEntityGraph.mockResolvedValue(makeGraph([
      { source: "ent-001", target: "ent-inv", label: "INVESTOR_IN", weight: 0.4 },
      { source: "ent-001", target: "ent-tsmc", label: "SUPPLIER_OF", weight: 0.9 },
    ]));
    render(
      <Wrapper>
        <TopRelationsBlock entityId="ent-001" onNodeSelect={vi.fn()} />
      </Wrapper>,
    );
    await waitFor(() => {
      const buttons = screen.getAllByRole("button");
      // First button should be TSMC (weight 0.9) before Berkshire (0.4)
      expect(buttons[0]?.textContent).toContain("TSMC");
    });
  });

  // F-158: inbound edge (TSMC supplier_of Apple) — neighbor is edge.source, not target.
  // WHY this test: the old code used edge.target for all edges. After the fix,
  // inbound edges must resolve the neighbor from edge.source.
  it("F-158: renders inbound edges and calls onNodeSelect with source node", async () => {
    const onNodeSelect = vi.fn();
    // TSMC → Apple (TSMC is the supplier, Apple is the target = entity center)
    mockGateway.getEntityGraph.mockResolvedValue(makeGraph([
      { source: "ent-tsmc", target: "ent-001", label: "SUPPLIER_OF", weight: 0.9, direction: "inbound" },
    ]));
    render(
      <Wrapper>
        <TopRelationsBlock entityId="ent-001" onNodeSelect={onNodeSelect} />
      </Wrapper>,
    );
    // TSMC row must be visible (neighbor resolved from edge.source)
    await waitFor(() => screen.getByText("TSMC"));
    // Clicking should navigate to TSMC (the source node), not ent-001
    fireEvent.click(screen.getByText("TSMC").closest("button")!);
    expect(onNodeSelect).toHaveBeenCalledWith("ent-tsmc");
  });

  // F-158: graph with both inbound and outbound — both must render.
  it("F-158: shows both inbound and outbound edges", async () => {
    mockGateway.getEntityGraph.mockResolvedValue(makeGraph([
      { source: "ent-001", target: "ent-inv", label: "INVESTOR_IN", weight: 0.6, direction: "outbound" },
      { source: "ent-tsmc", target: "ent-001", label: "SUPPLIER_OF", weight: 0.9, direction: "inbound" },
    ]));
    render(
      <Wrapper>
        <TopRelationsBlock entityId="ent-001" onNodeSelect={vi.fn()} />
      </Wrapper>,
    );
    // Both neighbor labels must appear in the list
    await waitFor(() => {
      expect(screen.getByText("TSMC")).toBeDefined();
      expect(screen.getByText("Berkshire")).toBeDefined();
    });
  });
});
