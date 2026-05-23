/**
 * InlineSelectionPanel.test.tsx — Block I T-26/T-27 unit tests
 *
 * WHY THIS EXISTS: InlineSelectionPanel is the primary interaction surface
 * for node/edge detail on the Intelligence tab. These 4 tests pin the core
 * rendering contract so regressions (blank panel on click, breadcrumb missing,
 * × button not firing) surface immediately in CI rather than in browser testing.
 *
 * TEST STRATEGY: purely structural — no S9 calls, no MSW, no TanStack Query.
 * InlineSelectionPanel is a pure presentational component: receives props,
 * renders deterministic output, fires callbacks. RTL render + assertions suffice.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InlineSelectionPanel } from "@/components/instrument/intelligence/InlineSelectionPanel";
import type { SelectedNodeInfo } from "@/components/instrument/intelligence/InlineSelectionPanel";
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";

// ── Test fixtures ────────────────────────────────────────────────────────────

const mockNode: SelectedNodeInfo = {
  id: "node-001",
  label: "Apple Inc.",
  type: "company",
  degree: 3,
  edges: [
    { label: "COMPETES_WITH", weight: 0.85, neighborId: "node-002", neighborLabel: "Microsoft" },
    { label: "SUPPLIER_OF", weight: 0.6, neighborId: "node-003", neighborLabel: "TSMC" },
  ],
};

const mockEdge: SelectedEdgeInfo = {
  id: "edge-001",
  label: "COMPETES_WITH",
  weight: 0.85,
  evidence_snippets: [
    "Apple and Microsoft compete directly in the cloud and productivity segments.",
    "Both companies vied for enterprise contracts in Q4 2023.",
  ],
  relation_summary: "Direct competitors in cloud, productivity, and enterprise software.",
  sourceId: "node-001",
  targetId: "node-002",
  sourceLabel: "Apple Inc.",
  targetLabel: "Microsoft",
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe("InlineSelectionPanel", () => {
  it("renders nothing when both selectedNode and selectedEdge are null", () => {
    // WHY: null/null is the initial state — the panel must be a zero-height
    // no-op so the graph column doesn't reserve 180px before any click.
    const { container } = render(
      <InlineSelectionPanel selectedNode={null} selectedEdge={null} onClear={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("node mode: renders label, connection count, and edge rows", () => {
    // WHY: clicking a node must show the entity name + type + how many
    // direct connections it has so the analyst immediately understands
    // the node's centrality. Edge rows show the actual neighbour names.
    render(
      <InlineSelectionPanel selectedNode={mockNode} selectedEdge={null} onClear={vi.fn()} />,
    );

    // Header contains type + label
    expect(screen.getByText(/COMPANY · Apple Inc\./i)).toBeInTheDocument();

    // Connection count line
    expect(screen.getByText(/3 connections/i)).toBeInTheDocument();

    // Neighbour labels rendered in edge rows
    expect(screen.getByText("Microsoft")).toBeInTheDocument();
    expect(screen.getByText("TSMC")).toBeInTheDocument();

    // Relation labels (lowercased with _ replaced by space)
    expect(screen.getByText(/competes with/i)).toBeInTheDocument();
    expect(screen.getByText(/supplier of/i)).toBeInTheDocument();
  });

  it("edge mode: renders source → relation → target breadcrumb + evidence snippets", () => {
    // WHY: clicking an edge exposes the claim behind the relationship —
    // the source/relation/target triple tells the analyst WHAT the edge is,
    // and evidence snippets tell them WHERE the signal came from (important
    // for credibility evaluation in a hedge-fund context).
    render(
      <InlineSelectionPanel selectedNode={null} selectedEdge={mockEdge} onClear={vi.fn()} />,
    );

    // Breadcrumb: source and target labels visible
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("Microsoft")).toBeInTheDocument();

    // Relation type appears in both header and breadcrumb — assert at least one match
    expect(screen.getAllByText(/competes with/i).length).toBeGreaterThanOrEqual(1);

    // LLM summary
    expect(screen.getByText(/Direct competitors in cloud/i)).toBeInTheDocument();

    // Evidence snippet header
    expect(screen.getByText(/EVIDENCE · 2 snippets/i)).toBeInTheDocument();

    // Both snippets rendered
    expect(screen.getByText(/Apple and Microsoft compete/i)).toBeInTheDocument();
    expect(screen.getByText(/Both companies vied/i)).toBeInTheDocument();
  });

  it("onClear fires when the × button is clicked", () => {
    // WHY: the × dismiss button must trigger the parent's clear handler
    // (sets selectedNode/selectedEdge to null) — if it silently fails the
    // analyst cannot collapse the panel and loses 180px of graph real-estate.
    const onClear = vi.fn();
    render(
      <InlineSelectionPanel selectedNode={mockNode} selectedEdge={null} onClear={onClear} />,
    );

    const closeBtn = screen.getByRole("button", { name: /close selection panel/i });
    fireEvent.click(closeBtn);
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
