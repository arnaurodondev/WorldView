/**
 * FilterController.orphanNodes.test.tsx
 * — Regression test for the KG FILTER BUG (2026-06-23).
 *
 * BUG: the relation-type filter pills hid non-matching EDGES in sigma's
 * edgeReducer but NEVER hid the now-orphaned NODES. Disconnected dots stayed
 * painted, so analysts perceived "toggling a filter does nothing to the nodes."
 *
 * FIX (SigmaInternalComponents.tsx FilterController): when a relation pill is
 * active, compute the set of nodes that still keep >=1 visible edge and hide the
 * rest via nodeReducer — always keeping the centre + selected node visible.
 *
 * WHY THIS TEST SHAPE: the real EntityGraph pulls in sigma.js / WebGL which has
 * no jsdom support, so we cannot mount the full canvas. Instead we mock the
 * @react-sigma/core useSigma() hook to hand FilterController a REAL graphology
 * graph plus a fake setSettings() that captures the node/edge reducers. We then
 * invoke the captured nodeReducer ourselves and assert the hidden flags. This
 * exercises the exact closure that ships — the orphan-node logic, the
 * keptNodeIds set, and the centre/selection exemptions — without WebGL.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import Graph from "graphology";

// ── Capture handles (hoisted so the vi.mock factory can see them) ─────────────
// setSettingsCapture receives whatever FilterController pushes via
// sigma.setSettings(); we read back .nodeReducer / .edgeReducer from it.
const setSettingsCapture = vi.fn();
// The real graphology graph the mocked sigma returns from getGraph(). Each test
// rebuilds it in beforeEach so the topology is explicit per scenario.
let testGraph: Graph;

// WHY mock @react-sigma/core: useSigma() is a context hook that only resolves
// inside <SigmaContainer> (which needs WebGL). We replace it with a stub sigma
// exposing the two methods FilterController calls: getGraph() + setSettings().
// refresh() is a no-op. forEachEdge on the real graph drives keptNodeIds.
vi.mock("@react-sigma/core", () => ({
  useSigma: () => ({
    getGraph: () => testGraph,
    setSettings: setSettingsCapture,
    refresh: vi.fn(),
  }),
}));

// Import AFTER the mock is registered so FilterController binds to the stub hook.
import { FilterController } from "../SigmaInternalComponents";

/** Build a tiny star graph:
 *    center ──HAS_EXECUTIVE──> person   (matches "executive" pill)
 *    center ──SUPPLIER_OF─────> supplier (matches "supplier" pill, NOT executive)
 *    orphan (no edges)
 *  All edge weights = 0.9 so the 0% strength floor never hides them.
 */
function buildStarGraph(): Graph {
  const g = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });
  g.addNode("center", { label: "Apple Inc", nodeType: "company" });
  g.addNode("person", { label: "Tim Cook", nodeType: "person" });
  g.addNode("supplier", { label: "TSMC", nodeType: "company" });
  g.addNode("orphan", { label: "Lonely Co", nodeType: "company" });
  g.addEdgeWithKey("e1", "center", "person", { label: "HAS_EXECUTIVE", weight: 0.9 });
  g.addEdgeWithKey("e2", "center", "supplier", { label: "SUPPLIER_OF", weight: 0.9 });
  return g;
}

/** Render FilterController with the given props and return the captured reducers. */
function mountAndCaptureReducers(props: {
  activeRelFilter: "all" | "executive" | "investor" | "supplier" | "customer" | "competitor";
  selectedNodeId?: string | null;
}) {
  render(
    <FilterController
      activeRelFilter={props.activeRelFilter}
      minWeight={0}
      searchQuery=""
      // graphData is unused by the orphan-node logic (it reads the live
      // graphology graph from sigma), but the prop is required — minimal stub.
      graphData={{ entity_id: "center", nodes: [], edges: [] }}
      centerEntityId="center"
      selectedNodeId={props.selectedNodeId ?? null}
      selectedEdgeId={null}
    />,
  );
  // The reducer-setting effect runs on mount; grab the last setSettings payload.
  const lastCall = setSettingsCapture.mock.calls.at(-1);
  expect(lastCall).toBeDefined();
  return lastCall![0] as {
    nodeReducer: (node: string, data: Record<string, unknown>) => Record<string, unknown>;
    edgeReducer: (edge: string, data: Record<string, unknown>) => Record<string, unknown>;
  };
}

/** Convenience: run nodeReducer for a node and report whether it's hidden. */
function isHidden(
  reducers: { nodeReducer: (n: string, d: Record<string, unknown>) => Record<string, unknown> },
  node: string,
): boolean {
  const graph = testGraph;
  const data = { ...graph.getNodeAttributes(node) };
  const out = reducers.nodeReducer(node, data);
  return out.hidden === true;
}

describe("FilterController — orphan-node hiding (KG filter bug)", () => {
  beforeEach(() => {
    setSettingsCapture.mockClear();
    testGraph = buildStarGraph();
  });

  it("hides nodes with no surviving edge when a relation pill is active", () => {
    // "executive" keeps only the center<->person edge. supplier + orphan lose
    // all visible edges → both must be hidden. person stays (matching edge).
    const reducers = mountAndCaptureReducers({ activeRelFilter: "executive" });

    expect(isHidden(reducers, "person")).toBe(false); // matching neighbor — visible
    expect(isHidden(reducers, "supplier")).toBe(true); // orphaned by filter — hidden
    expect(isHidden(reducers, "orphan")).toBe(true); // had no edges at all — hidden
  });

  it("always keeps the centre entity visible even when all its edges are filtered out", () => {
    // "customer" matches NEITHER edge → center would be orphaned, but the centre
    // node must never be hidden (the analyst is inspecting it).
    const reducers = mountAndCaptureReducers({ activeRelFilter: "customer" });

    expect(isHidden(reducers, "center")).toBe(false); // centre exempt
    expect(isHidden(reducers, "person")).toBe(true);
    expect(isHidden(reducers, "supplier")).toBe(true);
  });

  it("keeps the explicitly selected node visible even if the filter orphans it", () => {
    // Select the supplier node, then apply the "executive" pill which orphans it.
    // The selection exemption must override the orphan-hide.
    const reducers = mountAndCaptureReducers({
      activeRelFilter: "executive",
      selectedNodeId: "supplier",
    });

    expect(isHidden(reducers, "supplier")).toBe(false); // selected — stays visible
    expect(isHidden(reducers, "orphan")).toBe(true); // still hidden
  });

  it("hides NO nodes when the filter is 'all' (only edges dim via strength)", () => {
    // Regression guard for the pre-fix behaviour: in "all" mode every node —
    // including the genuinely edge-less orphan — stays visible.
    const reducers = mountAndCaptureReducers({ activeRelFilter: "all" });

    expect(isHidden(reducers, "center")).toBe(false);
    expect(isHidden(reducers, "person")).toBe(false);
    expect(isHidden(reducers, "supplier")).toBe(false);
    expect(isHidden(reducers, "orphan")).toBe(false);
  });
});
