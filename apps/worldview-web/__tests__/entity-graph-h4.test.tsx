/**
 * __tests__/entity-graph-h4.test.tsx — PLAN-0059 Wave H-4 filter controls
 *
 * WHY THIS EXISTS: EntityGraph now has four interactive filter mechanisms
 * (relation-type pills, strength slider, node search, layout switcher).
 * Tests verify that the filter state is wired correctly without exercising
 * the sigma WebGL renderer (which is unavailable in jsdom).
 *
 * WHY mock sigma/graphology: sigma.js uses WebGL context APIs (canvas.getContext("webgl"))
 * that jsdom does not implement. All sigma hooks are mocked with stable vi.fn()
 * stubs so the component tree renders as plain DOM for assertion.
 *
 * IMPORTANT: The mocks below must stay in sync with the actual @react-sigma/core
 * and graphology APIs. If those packages upgrade their API surface, update mocks.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";

// ── sigma mock ────────────────────────────────────────────────────────────────
// WHY module-level vi.mock: Vitest hoists vi.mock() calls before imports, so
// any transitive import of @react-sigma/core (e.g., via EntityGraph.tsx) will
// receive the mocked module without any real sigma code executing.

// WHY vi.hoisted(): vi.mock() factories are hoisted to the top of the file BEFORE
// variable declarations. If we used `const mockSetSettings = vi.fn()` at module
// scope and referenced it inside vi.mock(), it would be `undefined` when the
// factory runs (temporal dead zone for const). vi.hoisted() runs BEFORE hoisting,
// so the returned values are available inside vi.mock() factories. (BP-023 class)
const { mockSetSettings, mockRefresh, mockGetGraph } = vi.hoisted(() => ({
  mockSetSettings: vi.fn(),
  mockRefresh: vi.fn(),
  mockGetGraph: vi.fn(() => ({
    getNodeAttributes: vi.fn(() => ({ label: "Test Node", nodeType: "company" })),
    getEdgeAttributes: vi.fn(() => ({ label: "CEO_OF", weight: 0.9 })),
    degree: vi.fn(() => 3),
    nodes: vi.fn(() => []),
  })),
}));

vi.mock("@react-sigma/core", () => ({
  SigmaContainer: ({ children }: { children: React.ReactNode }) => (
    // WHY data-testid: allows tests to assert the container renders without
    // depending on implementation details of the sigma WebGL canvas.
    <div data-testid="sigma-container">{children}</div>
  ),
  useLoadGraph: () => vi.fn(),
  useRegisterEvents: () => vi.fn(),
  useSigma: () => ({
    getGraph: mockGetGraph,
    setSettings: mockSetSettings,
    refresh: mockRefresh,
  }),
}));

// ── graphology mock ───────────────────────────────────────────────────────────
// WHY: GraphLoader instantiates a graphology Graph inside useEffect. The mock
// prevents any real graph logic from running — we only test the filter UI.
vi.mock("graphology", () => ({
  default: class MockGraph {
    addNode = vi.fn();
    addEdge = vi.fn();
    hasNode = () => true;
    hasEdge = () => false;
    order = 0;
    nodes = () => [];
    degree = () => 0;
    getNodeAttributes = vi.fn(() => ({}));
    setNodeAttribute = vi.fn();
  },
}));

// ── ForceAtlas2 mock ──────────────────────────────────────────────────────────
// WHY: forceAtlas2.assign() runs a CPU-intensive layout algorithm. In tests
// we only care about whether the graph data is passed; the layout is irrelevant.
vi.mock("graphology-layout-forceatlas2", () => ({
  default: {
    assign: vi.fn(),
    inferSettings: vi.fn(() => ({})),
  },
}));

// ── @react-sigma/core CSS mock ────────────────────────────────────────────────
// WHY: vitest can't process CSS imports. The sigma core CSS import in EntityGraph
// is style-only; we stub it to prevent "unknown file extension .css" errors.
vi.mock("@react-sigma/core/lib/style.css", () => ({}));

// ── next/navigation mock ──────────────────────────────────────────────────────
// WHY: GraphEvents calls useRouter() for node click navigation. Mock it so
// the component renders without a Next.js router context in jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

// ── @/components/ui/slider mock ──────────────────────────────────────────────
// WHY mock the shadcn wrapper (not @radix-ui/react-slider directly): the Radix
// Root component renders as a <span> container with child Track/Range/Thumb
// primitives. Mocking Radix Root as an <input> causes React 19 to error
// ("input is a void element, cannot have children") because slider.tsx still
// passes Track + Thumb children to Root. Mocking the final shadcn export at
// component boundary sidesteps the Radix internal tree entirely.
vi.mock("@/components/ui/slider", () => ({
  Slider: React.forwardRef(function MockSlider(
    {
      value,
      onValueChange,
      min,
      max,
      step,
      className,
    }: {
      value?: number[];
      onValueChange?: (v: number[]) => void;
      min?: number;
      max?: number;
      step?: number;
      className?: string;
    },
    ref: React.Ref<HTMLInputElement>,
  ) {
    return (
      <input
        ref={ref}
        type="range"
        data-testid="strength-slider-input"
        className={className}
        value={value?.[0] ?? 0}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onValueChange?.([Number(e.target.value)])}
        readOnly={!onValueChange}
      />
    );
  }),
}));

// ── lib/entity-types mock ─────────────────────────────────────────────────────
// WHY: ENTITY_TYPE_COLOR_MAP is used inside GraphLoader/GraphLegend. Minimal stub
// avoids needing the full entity-types lib to be importable in test environment.
vi.mock("@/lib/entity-types", () => ({
  ENTITY_TYPE_COLOR_MAP: {
    company: "#FFD60A",
    person: "#3B82F6",
  },
}));

// ── Import the component AFTER mocks ─────────────────────────────────────────
// WHY import after vi.mock: vi.mock() is hoisted, so by the time this import
// runs all the mocked modules are in place.
import { EntityGraph } from "@/components/instrument/EntityGraph";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// ── Sample graph data ─────────────────────────────────────────────────────────
const mockData: EntityGraphData = {
  entity_id: "e1",
  nodes: [
    { id: "e1", label: "Apple Inc", type: "company", size: 2 },
    { id: "e2", label: "Tim Cook", type: "person", size: 2 },
  ],
  edges: [{ id: "r1", source: "e1", target: "e2", label: "CEO_OF", weight: 0.9 }],
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("EntityGraph H-4 filter controls", () => {
  beforeEach(() => {
    // WHY reset: each test needs a clean call count so assertions are isolated
    vi.clearAllMocks();
  });

  // ── 1. Filter pills render ──────────────────────────────────────────────────
  it("renders filter pills for all relation types", () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);

    // WHY assert pill count: ensures all 6 RELATION_TYPES are rendered —
    // a missing pill would silently drop a filter option from the UI.
    const pills = screen.getAllByTestId(/^filter-pill-/);
    expect(pills).toHaveLength(6); // all | executive | investor | supplier | customer | competitor

    // Spot-check each pill label is rendered
    expect(screen.getByTestId("filter-pill-all")).toBeInTheDocument();
    expect(screen.getByTestId("filter-pill-executive")).toBeInTheDocument();
    expect(screen.getByTestId("filter-pill-investor")).toBeInTheDocument();
    expect(screen.getByTestId("filter-pill-supplier")).toBeInTheDocument();
    expect(screen.getByTestId("filter-pill-customer")).toBeInTheDocument();
    expect(screen.getByTestId("filter-pill-competitor")).toBeInTheDocument();
  });

  // ── 2. Filter pill click ────────────────────────────────────────────────────
  it("clicking a filter pill marks it active and others inactive", () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);

    const executivePill = screen.getByTestId("filter-pill-executive");
    const allPill = screen.getByTestId("filter-pill-all");

    // Initial state: "all" is active
    expect(allPill).toHaveAttribute("data-active", "true");
    expect(executivePill).toHaveAttribute("data-active", "false");

    // Click "executive" pill
    fireEvent.click(executivePill);

    // WHY check data-active: this attribute is the authoritative record of the
    // active pill. The visual styling (class names) is derived from it.
    expect(executivePill).toHaveAttribute("data-active", "true");
    expect(allPill).toHaveAttribute("data-active", "false");
  });

  // ── 3. Search input triggers FilterController ───────────────────────────────
  it("typing in the search input invokes sigma.setSettings with a nodeReducer", async () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);

    const searchInput = screen.getByTestId("node-search");

    // WHY act(): FilterController's useEffect is async (runs after render).
    // act() flushes all pending React effects before we assert.
    await act(async () => {
      fireEvent.change(searchInput, { target: { value: "Apple" } });
    });

    // WHY check setSettings was called: that is the sigma API surface FilterController
    // uses to push nodeReducer changes — if it's not called, sigma won't dim any nodes.
    expect(mockSetSettings).toHaveBeenCalled();

    // Verify the most recent call included a nodeReducer function
    const lastCall = mockSetSettings.mock.calls[mockSetSettings.mock.calls.length - 1][0];
    expect(typeof lastCall.nodeReducer).toBe("function");
  });

  // ── 4. Layout switcher rerenders GraphLoader with correct prop ──────────────
  it("clicking the hierarchical layout button activates the hierarchical button", () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);

    const forceBtn = screen.getByTestId("layout-force");
    const hierarchicalBtn = screen.getByTestId("layout-hierarchical");

    // Initial state: force is active
    // WHY check class substring: the active class includes "bg-primary/20"
    expect(forceBtn.className).toContain("bg-primary/20");
    expect(hierarchicalBtn.className).not.toContain("bg-primary/20");

    // Switch to hierarchical
    fireEvent.click(hierarchicalBtn);

    // WHY re-check classes after click: React state update triggers re-render,
    // which should swap active class from force → hierarchical button.
    expect(hierarchicalBtn.className).toContain("bg-primary/20");
    expect(forceBtn.className).not.toContain("bg-primary/20");
  });

  // ── 5. Strength slider renders with correct initial value ───────────────────
  it("renders the strength slider with initial value 0", () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);

    // WHY check the label text: "Strength ≥ 0%" confirms the initial minWeight=0
    // state is reflected in the label alongside the slider control.
    expect(screen.getByText("Strength ≥ 0%")).toBeInTheDocument();
    expect(screen.getByTestId("strength-slider-input")).toBeInTheDocument();
  });

  // ── 6. Empty state renders without graph controls ───────────────────────────
  it("renders empty state message when data has no nodes", () => {
    const emptyData: EntityGraphData = { entity_id: "e1", nodes: [], edges: [] };
    render(<EntityGraph data={emptyData} centerEntityId="e1" />);

    // WHY check empty text: the component short-circuits before rendering filter
    // controls when there is no data — filter pills on empty graphs are meaningless.
    expect(screen.getByText("No relationship data available")).toBeInTheDocument();

    // Filter controls should NOT appear for empty graphs
    expect(screen.queryByTestId("filter-pills")).not.toBeInTheDocument();
  });

  // ── 7. Sigma container renders when data is present ─────────────────────────
  it("renders sigma container when nodes are present", () => {
    render(<EntityGraph data={mockData} centerEntityId="e1" />);
    expect(screen.getByTestId("sigma-container")).toBeInTheDocument();
  });

  // ── 8. FilterController calls setSettings + refresh on mount ────────────────
  it("FilterController calls sigma.setSettings and sigma.refresh on mount", async () => {
    await act(async () => {
      render(<EntityGraph data={mockData} centerEntityId="e1" />);
    });

    // WHY: on mount, FilterController's useEffect fires once with the default
    // filter state (all, minWeight=0, searchQuery=""). setSettings must be called
    // so sigma's reducers are initialized even before user interaction.
    expect(mockSetSettings).toHaveBeenCalled();
    expect(mockRefresh).toHaveBeenCalled();
  });
});
