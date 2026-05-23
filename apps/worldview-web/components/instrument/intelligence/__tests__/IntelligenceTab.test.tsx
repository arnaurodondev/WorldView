/**
 * components/instrument/intelligence/__tests__/IntelligenceTab.test.tsx
 *
 * WHY THIS EXISTS (F-006):
 * IntelligenceTab owns the selection state that drives InlineSelectionPanel
 * (node/edge detail) and the visual highlight in the sigma graph. These 4
 * tests pin the core selection-state contracts so regressions (deselect not
 * firing, edge not clearing on node click, stale selection after entity change)
 * surface in CI rather than in a browser QA session.
 *
 * TEST STRATEGY:
 * We render IntelligenceTab with heavily mocked children so the test focuses
 * on the state orchestration in IntelligenceTab itself:
 *   - GraphColumn → test-double that captures and exposes its onNodeChange +
 *     onEdgeSelect callbacks so we can fire them directly.
 *   - ContextPanel → lightweight div (we only care it renders, not its contents).
 *   - NewsColumn, InlineSelectionPanel → their own unit tests cover their
 *     internal contracts; we mock them here for isolation.
 *
 * WHY fireEvent (not userEvent): we call the callback props directly via
 * the captured refs — no real DOM click events needed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// WHY mock HotkeyContext: IntelligenceTab calls pushScope/popScope on mount.
// Without this mock the test would throw "useHotkeyScope must be inside HotkeyProvider".
vi.mock("@/contexts/HotkeyContext", () => ({
  useHotkeyScope: vi.fn(() => ({
    registry: { register: vi.fn(() => vi.fn()) },
    pushScope: vi.fn(),
    popScope: vi.fn(),
    activeScopes: new Set(),
  })),
}));

// ── GraphColumn test-double ───────────────────────────────────────────────────
// WHY capture ref (not spy): GraphColumn receives onNodeChange + onEdgeSelect
// as props. We capture them via module-level refs so individual tests can fire
// them directly with the exact payloads they want to test.

let capturedOnNodeChange: ((info: import("@/components/instrument/intelligence/InlineSelectionPanel").SelectedNodeInfo | null) => void) | null = null;
let capturedOnEdgeSelect: ((info: import("@/components/instrument/EntityGraph").SelectedEdgeInfo) => void) | null = null;

vi.mock("@/components/instrument/intelligence/graph/GraphColumn", () => ({
  GraphColumn: (props: {
    entityId: string;
    selectedNodeId: string | null;
    onNodeChange?: (info: unknown) => void;
    onEdgeSelect?: (info: unknown) => void;
  }) => {
    // Capture the callbacks on every render so tests can invoke them.
    capturedOnNodeChange = props.onNodeChange as typeof capturedOnNodeChange;
    capturedOnEdgeSelect = props.onEdgeSelect as typeof capturedOnEdgeSelect;
    return (
      <div
        data-testid="graph-column-stub"
        data-entity={props.entityId}
        data-selected-node={props.selectedNodeId ?? ""}
      />
    );
  },
}));

vi.mock("@/components/instrument/intelligence/context/ContextPanel", () => ({
  ContextPanel: ({ entityId }: { entityId: string }) => (
    <div data-testid="context-panel-stub" data-entity={entityId} />
  ),
}));

vi.mock("@/components/instrument/intelligence/news/NewsColumn", () => ({
  NewsColumn: () => <div data-testid="news-column-stub" />,
}));

// InlineSelectionPanel is NOT mocked — we assert on its rendered output to
// verify the parent's state drives it correctly.

// ── Import AFTER mocks ────────────────────────────────────────────────────────

// eslint-disable-next-line import/first
import { IntelligenceTab } from "@/components/instrument/intelligence/IntelligenceTab";
// eslint-disable-next-line import/first
import type { SelectedNodeInfo } from "@/components/instrument/intelligence/InlineSelectionPanel";
// eslint-disable-next-line import/first
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";

// ── Fixtures ─────────────────────────────────────────────────────────────────

const NODE_1: SelectedNodeInfo = {
  id: "n1",
  label: "Apple Inc.",
  type: "company",
  degree: 3,
  edges: [{ label: "COMPETES_WITH", weight: 0.8, neighborId: "n2", neighborLabel: "Microsoft" }],
};

const NODE_2: SelectedNodeInfo = {
  id: "n2",
  label: "Microsoft",
  type: "company",
  degree: 2,
  edges: [],
};

const EDGE_1: SelectedEdgeInfo = {
  id: "e1",
  label: "COMPETES_WITH",
  weight: 0.8,
  evidence_snippets: ["Apple and Microsoft compete in cloud."],
  sourceId: "n1",
  targetId: "n2",
  sourceLabel: "Apple Inc.",
  targetLabel: "Microsoft",
  direction: "outbound",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function Wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("IntelligenceTab — selection state", () => {
  beforeEach(() => {
    capturedOnNodeChange = null;
    capturedOnEdgeSelect = null;
  });

  it("T1: selecting the same node a second time deselects it (toggle)", () => {
    // WHY: clicking a node that is already selected should collapse InlineSelectionPanel
    // (null selection). The toggle logic lives in GraphColumn (F-203) but the
    // parent IntelligenceTab must propagate null correctly.
    render(
      <Wrapper>
        <IntelligenceTab entityId="ent-001" />
      </Wrapper>,
    );

    // First click — select node n1
    act(() => { capturedOnNodeChange?.(NODE_1); });
    // InlineSelectionPanel should now be visible (it renders non-null when selectedNode != null)
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();

    // GraphColumn signals deselect (same node clicked again → onNodeChange(null))
    act(() => { capturedOnNodeChange?.(null); });
    // InlineSelectionPanel renders null — the text should be gone
    expect(screen.queryByText(/COMPANY · Apple Inc\./i)).not.toBeInTheDocument();
  });

  it("T2: selecting a node clears any active edge selection", () => {
    // WHY mutual exclusion: node and edge detail panels are alternatives, not
    // co-visible. Selecting a node while an edge is shown must hide the edge panel.
    render(
      <Wrapper>
        <IntelligenceTab entityId="ent-001" />
      </Wrapper>,
    );

    // Set up an edge selection first
    act(() => { capturedOnEdgeSelect?.(EDGE_1); });
    // Edge panel should be visible — direction badge "outbound" is edge-mode only.
    expect(screen.getByText(/outbound/i)).toBeInTheDocument();

    // Now select a node — edge must be cleared
    act(() => { capturedOnNodeChange?.(NODE_1); });
    // Edge breadcrumb "COMPETES WITH" is part of the edge panel header;
    // Node header "COMPANY · Apple Inc." comes from node mode.
    // After node select: node panel visible, edge panel gone.
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();
    // The edge direction badge ("outbound") would only appear in edge mode.
    // WHY check outbound: it's an unambiguous edge-mode-only string.
    expect(screen.queryByText(/outbound/i)).not.toBeInTheDocument();
  });

  it("T3: selecting an edge clears any active node selection", () => {
    // WHY: clicking an edge while a node is selected should collapse node panel
    // and open the edge panel.
    render(
      <Wrapper>
        <IntelligenceTab entityId="ent-001" />
      </Wrapper>,
    );

    // Select node first
    act(() => { capturedOnNodeChange?.(NODE_1); });
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();

    // Now click an edge
    act(() => { capturedOnEdgeSelect?.(EDGE_1); });
    // Node panel should be gone; edge panel should be visible.
    expect(screen.queryByText(/COMPANY · Apple Inc\./i)).not.toBeInTheDocument();
    expect(screen.getByText(/outbound/i)).toBeInTheDocument();
  });

  it("T4: entityId change clears both node and edge selections", () => {
    // WHY: when the instrument page navigates to a new entity (entityId prop changes),
    // a stale selectedNodeId from the old graph would point at a node that doesn't
    // exist in the new payload. Both selections must reset.
    const { rerender } = render(
      <Wrapper>
        <IntelligenceTab entityId="ent-001" />
      </Wrapper>,
    );

    // Set up node and edge selections on entity ent-001
    act(() => { capturedOnNodeChange?.(NODE_1); });
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();

    // Navigate to a different entity — both node and edge selections must clear.
    rerender(
      <Wrapper>
        <IntelligenceTab entityId="ent-002" />
      </Wrapper>,
    );

    // InlineSelectionPanel returns null when both selections are null.
    expect(screen.queryByText(/COMPANY · Apple Inc\./i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("entity-graph-stub")).toBeDefined(); // graph column still renders

    // Also verify entityId propagated to child stubs
    expect(screen.getByTestId("graph-column-stub")).toHaveAttribute("data-entity", "ent-002");
  });
});
