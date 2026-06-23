/**
 * intelligence/__tests__/IntelligenceTab.test.tsx — PLAN-0099 Wave 2.
 *
 * Pins the investigation-grid WIRING (children stubbed — their internals are
 * pinned by their own suites):
 *   - all three zones + the inspector mount
 *   - node/edge selection is MUTUALLY EXCLUSIVE (selecting one clears the other)
 *   - dossier top-relation click opens the edge inspector
 *   - the chat strip toggles open via the bottom strip AND the dossier Discuss
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

// ── Child stubs ──────────────────────────────────────────────────────────────
// Each stub exposes buttons that trigger the callbacks the tab wires, and
// renders its received selection props so assertions can read the state.

vi.mock("@/components/instrument/intelligence/dossier/EntityDossier", () => ({
  EntityDossier: (p: {
    onSelectRelation: (id: string) => void;
    onDiscuss: () => void;
  }) => (
    <div data-testid="dossier-stub">
      <button data-testid="stub-dossier-relation" onClick={() => p.onSelectRelation("rel-7")} />
      <button data-testid="stub-dossier-discuss" onClick={() => p.onDiscuss()} />
    </div>
  ),
}));

vi.mock("@/components/instrument/intelligence/graph/GraphColumn", () => ({
  GraphColumn: (p: {
    selectedNodeId: string | null;
    selectedEdgeId?: string | null;
    onNodeSelect: (id: string | null) => void;
    onEdgeSelect?: (id: string) => void;
  }) => (
    <div
      data-testid="graph-stub"
      data-selected-node={p.selectedNodeId ?? ""}
      data-selected-edge={p.selectedEdgeId ?? ""}
    >
      <button data-testid="stub-click-node" onClick={() => p.onNodeSelect("n-1")} />
      <button data-testid="stub-click-edge" onClick={() => p.onEdgeSelect?.("e-1")} />
    </div>
  ),
}));

vi.mock("@/components/instrument/intelligence/detail/SelectionDetailPanel", () => ({
  SelectionDetailPanel: (p: { selectedNodeId: string | null; selectedEdgeId: string | null }) => (
    <div
      data-testid="inspector-stub"
      data-selected-node={p.selectedNodeId ?? ""}
      data-selected-edge={p.selectedEdgeId ?? ""}
    />
  ),
}));

vi.mock("@/components/instrument/intelligence/news/NewsColumn", () => ({
  NewsColumn: () => <div data-testid="news-stub" />,
}));

vi.mock("@/components/instrument/intelligence/events/EventsBlock", () => ({
  EventsBlock: () => <div data-testid="events-stub" />,
}));

vi.mock("@/components/instrument/intelligence/context/ContradictionsBlock", () => ({
  ContradictionsBlock: () => <div data-testid="contradictions-stub" />,
}));

vi.mock("@/components/instrument/intelligence/context/NarrativeHistoryDisclosure", () => ({
  NarrativeHistoryDisclosure: () => <div data-testid="narrative-stub" />,
}));

// PATH INSIGHTS (audit 2026-06-23 §2a): the tab must MOUNT this block (its
// internals — warm-cache read, weirdness chips, empty state — are pinned by its
// own suite, so here we only stub it to assert the WIRING and the entityId it
// receives so the warm-cache key match is exercised by IntelligenceTab.warm.test).
vi.mock("@/components/instrument/intelligence/context/PathInsightsBlock", () => ({
  PathInsightsBlock: (p: { entityId: string }) => (
    <div data-testid="path-insights-stub" data-entity-id={p.entityId} />
  ),
}));

vi.mock("@/components/intelligence/EntityChatPanel", () => ({
  EntityChatPanel: () => <div data-testid="chat-stub" />,
}));

// SelectedEntityProvider needs next/navigation's usePathname.
vi.mock("next/navigation", () => ({
  usePathname: () => "/instruments/AAPL",
  useRouter: () => ({ push: vi.fn() }),
}));

// The bundle hook fires a gateway call — stub it to a no-op.
vi.mock("@/features/intelligence/hooks/useEntityIntelligenceBundle", () => ({
  useEntityIntelligenceBundle: vi.fn(() => ({ data: null, isLoading: false })),
}));

import { IntelligenceTab } from "@/components/instrument/intelligence/IntelligenceTab";

beforeEach(() => vi.clearAllMocks());
afterEach(() => cleanup());

describe("IntelligenceTab investigation grid", () => {
  it("mounts all three zones + the inspector + the chat strip toggle", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    expect(screen.getByTestId("dossier-stub")).toBeInTheDocument();
    expect(screen.getByTestId("graph-stub")).toBeInTheDocument();
    expect(screen.getByTestId("inspector-stub")).toBeInTheDocument();
    expect(screen.getByTestId("news-stub")).toBeInTheDocument();
    expect(screen.getByTestId("events-stub")).toBeInTheDocument();
    expect(screen.getByTestId("contradictions-stub")).toBeInTheDocument();
    expect(screen.getByTestId("narrative-stub")).toBeInTheDocument();
    // Audit §2a MUST-FIX: the path-insights block is mounted (it was prefetched
    // into cache then discarded before this fix) and receives the page entityId.
    const pathStub = screen.getByTestId("path-insights-stub");
    expect(pathStub).toBeInTheDocument();
    expect(pathStub.getAttribute("data-entity-id")).toBe("ent-001");
    expect(screen.getByTestId("intel-chat-toggle")).toBeInTheDocument();
    // Chat is CLOSED by default.
    expect(screen.queryByTestId("chat-stub")).not.toBeInTheDocument();
  });
});

describe("IntelligenceTab selection wiring (mutual exclusion)", () => {
  it("node click selects the node on canvas + inspector", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("stub-click-node"));
    expect(screen.getByTestId("graph-stub").getAttribute("data-selected-node")).toBe("n-1");
    expect(screen.getByTestId("inspector-stub").getAttribute("data-selected-node")).toBe("n-1");
  });

  it("edge click clears any node selection (edge wins)", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("stub-click-node"));
    fireEvent.click(screen.getByTestId("stub-click-edge"));
    const inspector = screen.getByTestId("inspector-stub");
    expect(inspector.getAttribute("data-selected-edge")).toBe("e-1");
    expect(inspector.getAttribute("data-selected-node")).toBe("");
    // Canvas highlight follows the same state.
    expect(screen.getByTestId("graph-stub").getAttribute("data-selected-edge")).toBe("e-1");
  });

  it("node click clears any edge selection (node wins)", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("stub-click-edge"));
    fireEvent.click(screen.getByTestId("stub-click-node"));
    const inspector = screen.getByTestId("inspector-stub");
    expect(inspector.getAttribute("data-selected-node")).toBe("n-1");
    expect(inspector.getAttribute("data-selected-edge")).toBe("");
  });

  it("a dossier top-relation click opens the EDGE inspector", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("stub-dossier-relation"));
    expect(screen.getByTestId("inspector-stub").getAttribute("data-selected-edge")).toBe("rel-7");
  });
});

describe("IntelligenceTab chat strip", () => {
  it("opens the chat via the bottom strip toggle and closes via the X", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("intel-chat-toggle"));
    expect(screen.getByTestId("chat-stub")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close chat/i }));
    expect(screen.queryByTestId("chat-stub")).not.toBeInTheDocument();
  });

  it("opens the chat via the dossier Discuss action", () => {
    render(<IntelligenceTab entityId="ent-001" />);
    fireEvent.click(screen.getByTestId("stub-dossier-discuss"));
    expect(screen.getByTestId("chat-stub")).toBeInTheDocument();
  });
});
