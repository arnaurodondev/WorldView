/**
 * RelatedEntitiesPanel.test.tsx — related-entity chips on the Intelligence tab
 * (Round-2 item 3).
 *
 * CONTRACTS PINNED:
 *   1. Chips group by type (Companies / People / Topics & Other) and the root
 *      entity is excluded.
 *   2. Company chip WITH ticker navigates to /instruments/{ticker}.
 *   3. Ticker-less chip falls back to onNodeSelect (in-panel node detail).
 *   4. "+N more" expander caps visible chips at 12 and expands on click.
 *   5. Named empty state when the graph has no neighbours.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import type { GraphNode } from "@/types/api";

// ── Router mock ──────────────────────────────────────────────────────────────

const pushMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// eslint-disable-next-line import/first
import { RelatedEntitiesPanel } from "@/components/instrument/intelligence/context/RelatedEntitiesPanel";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const ROOT_ID = "root-entity";

function node(partial: Partial<GraphNode> & { id: string; label: string; type: string }): GraphNode {
  return { size: 1, ticker: "", ...partial };
}

const BASE_NODES: GraphNode[] = [
  node({ id: ROOT_ID, label: "Apple Inc.", type: "financial_instrument", ticker: "AAPL", size: 10 }),
  node({ id: "msft", label: "Microsoft", type: "financial_instrument", ticker: "MSFT", size: 5 }),
  node({ id: "unlisted", label: "Stealth Startup", type: "company", size: 2 }), // no ticker
  node({ id: "cook", label: "Tim Cook", type: "person", size: 4 }),
  node({ id: "tech", label: "Information Technology", type: "sector", size: 3 }),
];

beforeEach(() => {
  pushMock.mockReset();
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("RelatedEntitiesPanel", () => {
  it("groups chips by type and excludes the root entity", () => {
    render(<RelatedEntitiesPanel entityId={ROOT_ID} nodes={BASE_NODES} onNodeSelect={vi.fn()} />);

    expect(screen.getByText("Companies")).toBeInTheDocument();
    expect(screen.getByText("People")).toBeInTheDocument();
    expect(screen.getByText("Topics & Other")).toBeInTheDocument();

    expect(screen.getByText("Microsoft")).toBeInTheDocument();
    expect(screen.getByText("Tim Cook")).toBeInTheDocument();
    expect(screen.getByText("Information Technology")).toBeInTheDocument();
    // Root entity must NOT appear as its own related chip.
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
    // Count badge: 4 neighbours (root excluded).
    expect(screen.getByText(/Related Entities · \(4\)/)).toBeInTheDocument();
  });

  it("navigates to /instruments/{ticker} for a company chip with a ticker", () => {
    render(<RelatedEntitiesPanel entityId={ROOT_ID} nodes={BASE_NODES} onNodeSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Open instrument page for Microsoft/ }));
    expect(pushMock).toHaveBeenCalledWith("/instruments/MSFT");
  });

  it("falls back to onNodeSelect for ticker-less chips (people, sectors, unlisted)", () => {
    const onNodeSelect = vi.fn();
    render(<RelatedEntitiesPanel entityId={ROOT_ID} nodes={BASE_NODES} onNodeSelect={onNodeSelect} />);

    fireEvent.click(screen.getByRole("button", { name: /Show details for Tim Cook/ }));
    expect(onNodeSelect).toHaveBeenCalledWith("cook");

    fireEvent.click(screen.getByRole("button", { name: /Show details for Stealth Startup/ }));
    expect(onNodeSelect).toHaveBeenCalledWith("unlisted");

    // Neither fallback path may navigate.
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("caps visible chips at 12 with a +N more expander, expands on click", () => {
    // 20 neighbour companies → 12 visible + "+8 more".
    const many: GraphNode[] = [
      node({ id: ROOT_ID, label: "Root", type: "financial_instrument", ticker: "ROOT" }),
      ...Array.from({ length: 20 }, (_, i) =>
        node({
          id: `c${i}`,
          label: `Company ${String(i).padStart(2, "0")}`,
          type: "financial_instrument",
          ticker: `C${i}`,
          // Descending size so visibility order is deterministic.
          size: 100 - i,
        }),
      ),
    ];
    render(<RelatedEntitiesPanel entityId={ROOT_ID} nodes={many} onNodeSelect={vi.fn()} />);

    expect(screen.getAllByRole("button", { name: /Open instrument page/ })).toHaveLength(12);
    const expander = screen.getByRole("button", { name: "+8 more" });
    fireEvent.click(expander);
    expect(screen.getAllByRole("button", { name: /Open instrument page/ })).toHaveLength(20);
    // Collapse affordance appears after expanding.
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("renders the named empty state when there are no neighbours", () => {
    // Only the root node → zero related entities.
    // Round-3 consolidation: this panel reuses the reserved
    // "instrument.no-connections" registry key (the chip list and the graph
    // canvas surface the SAME depth-2 data state), so the headline changed
    // from the local component's "No related entities" to the registry title.
    render(
      <RelatedEntitiesPanel
        entityId={ROOT_ID}
        nodes={[BASE_NODES[0]!]}
        onNodeSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("No connections found")).toBeInTheDocument();
    // Ported from the retired local EmptyState contract test: role="status"
    // semantics + inline <svg> icon keep the state announceable + scannable.
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.querySelector("svg")).not.toBeNull();
  });

  it("renders the empty state while the graph cache is still cold (undefined nodes)", () => {
    render(<RelatedEntitiesPanel entityId={ROOT_ID} nodes={undefined} onNodeSelect={vi.fn()} />);
    expect(screen.getByText("No connections found")).toBeInTheDocument();
  });
});
