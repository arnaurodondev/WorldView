/**
 * __tests__/instrument-graph.test.tsx — Unit tests for EntityGraph component
 *
 * WHY THIS EXISTS: EntityGraph is the most complex component in the app —
 * it wraps sigma.js (WebGL) + graphology + ForceAtlas2. These tests verify
 * the React-level behavior: empty state, correct rendering, ErrorBoundary,
 * legend presence, and control hints.
 *
 * WHY MOCK SIGMA: jsdom has no WebGL. Sigma attempts WebGL context creation
 * at mount time, which throws in jsdom. We mock @react-sigma/core so the
 * SigmaContainer renders a plain div instead of initializing WebGL, while
 * still letting us test the surrounding React component tree.
 *
 * WHY MOCK graphology + forceatlas2: no real graph computation needed in
 * unit tests. Mocking prevents import-time side effects from Node.js-incompatible
 * WebGL/canvas APIs that some graphology internals reference.
 *
 * WHAT IS NOT TESTED HERE (covered in e2e/instrument.spec.ts instead):
 * - Hover tooltips (require real mouse events on WebGL canvas)
 * - Pan/zoom/drag (require real WebGL context)
 * - Click-to-navigate (requires real sigma event system)
 * - ForceAtlas2 layout accuracy (requires real graphology)
 *
 * DATA SOURCE: Mocked EntityGraphData
 * DESIGN REFERENCE: PRD-0028 §6.5 Intelligence tab, ADR-F-08
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { EntityGraph, GraphErrorBoundary } from "@/components/instrument/EntityGraph";
import type { EntityGraph as EntityGraphData } from "@/types/api";

// ── @react-sigma/core mock ────────────────────────────────────────────────────
// WHY: sigma.js uses WebGL — unavailable in jsdom. We mock the entire module
// so SigmaContainer renders a div and the hooks return no-op functions.
vi.mock("@react-sigma/core", () => ({
  SigmaContainer: ({ children, className, style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) => (
    // WHY render children: GraphLoader and GraphEvents are children of SigmaContainer.
    // Rendering them (even with mocked hooks) lets us verify the component tree.
    <div data-testid="sigma-container" className={className} style={style}>{children}</div>
  ),
  // WHY vi.fn(() => vi.fn()): useRegisterEvents returns a function that registers events.
  // GraphEvents calls registerEvents({...}) in a useEffect — the mock prevents errors.
  useRegisterEvents: vi.fn(() => vi.fn()),
  // WHY vi.fn(() => vi.fn()): useLoadGraph returns a function that loads a graph.
  // GraphLoader calls loadGraph(graph) in a useEffect — the mock prevents errors.
  useLoadGraph: vi.fn(() => vi.fn()),
  useSigma: vi.fn(() => ({
    getGraph: vi.fn(() => ({
      getNodeAttributes: vi.fn(() => ({ label: "Test Node", nodeType: "company" })),
      getEdgeAttributes: vi.fn(() => ({ label: "CEO_OF", weight: 0.9 })),
      degree: vi.fn(() => 3),
    })),
    // WHY setSettings/refresh: EntityGraph H-4 adds FilterController which calls
    // sigma.setSettings({edgeReducer, nodeReducer}) + sigma.refresh() on mount.
    // Without these stubs, FilterController throws "setSettings is not a function".
    setSettings: vi.fn(),
    refresh: vi.fn(),
    // WHY getCamera: SA-3 (2026-05-10) added CameraAutoFit + KeyboardResetListener
    // which call sigma.getCamera().animatedReset(). Without this stub they throw.
    getCamera: vi.fn(() => ({ animatedReset: vi.fn() })),
  })),
}));

// ── graphology mock ───────────────────────────────────────────────────────────
// WHY: GraphLoader calls `new Graph(...)` to build the graphology instance.
// The mock Graph constructor returns an object with all needed methods as stubs.
vi.mock("graphology", () => ({
  default: vi.fn(() => ({
    addNode: vi.fn(),
    addEdge: vi.fn(),
    hasNode: vi.fn(() => false),
    hasEdge: vi.fn(() => false),
    // WHY order:0: forceAtlas2 checks graph.order before running layout.
    // Returning 0 causes the layout block to be skipped, preventing forceAtlas2 errors.
    order: 0,
    degree: vi.fn(() => 0),
  })),
}));

// ── graphology-layout-forceatlas2 mock ────────────────────────────────────────
// WHY: GraphLoader calls forceAtlas2.assign() and forceAtlas2.inferSettings().
// The mock prevents the real FA2 from running (which would fail without a real graph).
vi.mock("graphology-layout-forceatlas2", () => ({
  default: {
    assign: vi.fn(),
    inferSettings: vi.fn(() => ({})),
  },
}));

// ── next/navigation mock ──────────────────────────────────────────────────────
// WHY: GraphEvents uses useRouter() for click-to-navigate. The mock prevents
// "invariant useRouter must be in Next.js Router context" errors in jsdom.
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() })),
  usePathname: vi.fn(() => "/instruments/ent-001"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({ entityId: "ent-001" })),
}));

// ── Test fixtures ──────────────────────────────────────────────────────────────

const MOCK_GRAPH_DATA: EntityGraphData = {
  entity_id: "ent-001",
  nodes: [
    { id: "ent-001", label: "Apple Inc.", type: "company", size: 3 },
    { id: "ent-002", label: "Tim Cook", type: "person", size: 2 },
    { id: "ent-003", label: "TSMC", type: "company", size: 2 },
    { id: "ent-004", label: "Earnings Q1", type: "event", size: 1 },
  ],
  edges: [
    { id: "e1", source: "ent-001", target: "ent-002", label: "CEO_OF", weight: 0.99 },
    { id: "e2", source: "ent-001", target: "ent-003", label: "SUPPLIER_OF", weight: 0.85 },
    { id: "e3", source: "ent-001", target: "ent-004", label: "REPORTED", weight: 0.72 },
  ],
};

const EMPTY_GRAPH_DATA: EntityGraphData = {
  entity_id: "ent-001",
  nodes: [],
  edges: [],
};

// ── Tests ──────────────────────────────────────────────────────────────────────

describe("EntityGraph", () => {
  beforeEach(() => {
    // WHY reset mocks: prevent state leakage between tests (e.g., mock call counts).
    vi.clearAllMocks();
  });

  it("renders nothing-but-empty-state when node list is empty", () => {
    // WHY: empty graph should show a user-friendly message, not a blank canvas.
    render(
      <EntityGraph data={EMPTY_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    expect(screen.getByText("No relationship data available")).toBeInTheDocument();
    // WHY assert sigma-container absent: SigmaContainer should NOT mount for empty data.
    expect(screen.queryByTestId("sigma-container")).not.toBeInTheDocument();
  });

  it("renders sigma container when data is present", () => {
    // WHY: verifies the core rendering path — SigmaContainer mounts when data exists.
    render(
      <EntityGraph data={MOCK_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    expect(screen.getByTestId("sigma-container")).toBeInTheDocument();
  });

  it("renders the controls hint text", () => {
    // WHY: the controls hint tells users how to interact with the graph and
    // shows the keyboard shortcut. SA-3 (2026-05-10) added "R to fit" to the hint
    // so keyboard-friendly analysts know the reset shortcut without mousing to the button.
    render(
      <EntityGraph data={MOCK_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    // WHY single regex: the hint is one span — any partial match confirms it rendered.
    // Using a regex avoids over-specifying the exact punctuation style.
    expect(screen.getByText(/Scroll/)).toBeInTheDocument();
    expect(screen.getByText(/Drag/)).toBeInTheDocument();
    expect(screen.getByText(/R to fit/)).toBeInTheDocument();
  });

  it("renders legend reflecting only entity types present in the data", () => {
    // PLAN-0057 Wave F-1: the legend is now data-driven so it doesn't show
    // 13+ swatches when most graphs have 4–5 types.  MOCK_GRAPH_DATA carries
    // company / person / event nodes (no `topic`) so the legend should mirror
    // that exact set.  This is the post-F-1 contract; the previous "show every
    // type from the static palette" behaviour over-rendered swatches and
    // implied the graph contained types it didn't.
    render(
      <EntityGraph data={MOCK_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    expect(screen.getByText("company")).toBeInTheDocument();
    expect(screen.getByText("person")).toBeInTheDocument();
    expect(screen.getByText("event")).toBeInTheDocument();
    // `topic` is NOT in MOCK_GRAPH_DATA so the legend must not show it.
    expect(screen.queryByText("topic")).not.toBeInTheDocument();
  });

  it("does not render 'default' in legend", () => {
    // WHY: "default" is the fallback color for unknown entity types — it should
    // not appear as a legend item (it's not a real entity type category).
    render(
      <EntityGraph data={MOCK_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    // The text "default" should not appear anywhere in the legend
    expect(screen.queryByText("default")).not.toBeInTheDocument();
  });

  it("renders the graph container with the canvas-wrapper height classes", () => {
    // WHY: PLAN-0090 T-D-01 BUG 1 (black void) changed the wrapper from a
    // fixed `h-[460px]` to `h-full w-full min-h-[460px]` so the canvas grows
    // with its column instead of leaving a black gap below. We pin the new
    // canonical class set so a future refactor cannot silently regress.
    render(
      <EntityGraph data={MOCK_GRAPH_DATA} centerEntityId="ent-001" />,
    );

    // WHY min-h-[460px]: of the three new classes, min-h-[460px] is the most
    // specific and the one PRD-0088 still requires for narrow layouts.
    const container = document.querySelector(".min-h-\\[460px\\]");
    expect(container).toBeInTheDocument();
  });

  it("GraphErrorBoundary renders children when no error occurs", () => {
    // WHY: confirms the boundary is transparent in the happy path so it doesn't
    // cosmetically affect the EntityGraph component tree when WebGL is healthy.
    render(
      <GraphErrorBoundary>
        <div data-testid="boundary-child">healthy</div>
      </GraphErrorBoundary>,
    );

    expect(screen.getByTestId("boundary-child")).toBeInTheDocument();
    expect(screen.getByText("healthy")).toBeInTheDocument();
  });

  it("GraphErrorBoundary renders the production fallback when a child throws", () => {
    // PLAN-0057 Wave C T-008: assert the REAL production fallback text instead
    // of an inline-mirrored boundary (the previous test rebuilt its own boundary
    // class and asserted on its own copy — a tautology).  We import the actual
    // exported `GraphErrorBoundary` and let a `<ThrowingChild>` trigger it; the
    // assertions check the exact strings rendered by the production component.

    // React logs the captured error via console.error when an ErrorBoundary
    // catches a render-time throw.  Silencing keeps the test output clean.
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      // A child that throws during render — simulates WebGL context creation
      // failure inside the SigmaContainer subtree.
      const ThrowingChild = (): React.ReactNode => {
        throw new Error("WebGL2RenderingContext is not defined");
      };

      render(
        <GraphErrorBoundary>
          {React.createElement(ThrowingChild)}
        </GraphErrorBoundary>,
      );

      // WHY partial match: the exact text changes based on error type detection.
      // Assert on the stable prefix "Graph unavailable" rather than the full
      // message, which varies for WebGL vs non-WebGL errors.
      expect(
        screen.getByText(/Graph unavailable/),
      ).toBeInTheDocument();
      // The "Reload page" button is the user's only recovery affordance — it
      // must be rendered so we can click it (and it must be a real <button>).
      expect(
        screen.getByRole("button", { name: /reload page/i }),
      ).toBeInTheDocument();
    } finally {
      consoleSpy.mockRestore();
    }
  });
});
