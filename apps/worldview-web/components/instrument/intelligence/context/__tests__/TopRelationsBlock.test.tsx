/**
 * context/__tests__/TopRelationsBlock.test.tsx — W7 T-23
 *
 * Pins 3 contracts:
 *  1. Empty graph → "No direct relations found."
 *  2. Renders rows sorted by weight (heaviest first).
 *  3. Clicking a row calls onNodeSelect with the target node ID.
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

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ accessToken: "tok" })),
}));

const mockGateway = vi.hoisted(() => ({ getEntityGraph: vi.fn() }));
vi.mock("@/lib/gateway", () => ({ createGateway: vi.fn(() => mockGateway) }));

import { TopRelationsBlock } from "@/components/instrument/intelligence/context/TopRelationsBlock";

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => { mockGateway.getEntityGraph.mockReset(); });

function makeGraph(edges: Array<{ source: string; target: string; label: string; weight: number }>) {
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
});
