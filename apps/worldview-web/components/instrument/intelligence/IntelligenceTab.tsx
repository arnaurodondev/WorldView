/**
 * IntelligenceTab — W7 T-16 — orchestrator for the Intelligence tab.
 *
 * WHY THIS EXISTS (PRD-0089 §6.9):
 * The Intelligence tab is a 3-column grid (14-col base, 4+5+5):
 *   left   (col-span-4) : <NewsColumn />          — dense 18px news rail
 *   center (col-span-5) : <GraphColumn />          — brief + sigma.js graph
 *                       + <InlineSelectionPanel /> — node/edge detail below graph
 *   right  (col-span-5) : <ContextPanel />         — entity overview (always)
 *
 * WHY 4+5+5 (was 4+7+3):
 * User feedback: right rail too narrow for 5 data blocks; graph occupied 50%
 * which left the overview panel cramped at 21%. New split: graph at 35.7%,
 * right rail at 35.7% — right rail gets meaningful extra horizontal space.
 *
 * SELECTION STATE — `selectedNodeId` and `selectedEdgeInfo` are lifted here so
 * InlineSelectionPanel (center) and GraphColumn (center) share a single source
 * of truth. ContextPanel (right) always renders entity-overview mode.
 *
 * HOTKEY SCOPE — IntelligenceTab pushes the "page" scope on mount and pops
 * it on unmount. This activates the j/k/Enter news bindings (T-17) and the
 * 1/2/3/g/r/Esc graph bindings (T-18).
 */

"use client";
// WHY "use client": useState + useEffect + useHotkeyScope require the browser.

import { useState, useEffect, useCallback } from "react";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { NewsColumn } from "./news/NewsColumn";
import { GraphColumn } from "./graph/GraphColumn";
import { ContextPanel } from "./context/ContextPanel";
import { InlineSelectionPanel } from "./InlineSelectionPanel";
import type { SelectedNodeInfo } from "./InlineSelectionPanel";
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";

export interface IntelligenceTabProps {
  /** Authoritative KG entity_id for the instrument being viewed. */
  readonly entityId: string;
}

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  // WHY two separate selection slots: node and edge are mutually exclusive.
  // Selecting a node clears edge; selecting an edge clears node.
  const [selectedNodeInfo, setSelectedNodeInfo] = useState<SelectedNodeInfo | null>(null);
  const [selectedEdgeInfo, setSelectedEdgeInfo] = useState<SelectedEdgeInfo | null>(null);
  // WHY separate visualHighlightNodeId: ContextPanel row clicks (TopRelationsBlock)
  // need to highlight a node in sigma WITHOUT opening InlineSelectionPanel — the
  // right-rail click lacks full node data (label, edges list) required to render
  // the panel. selectedNodeInfo drives InlineSelectionPanel; this drives sigma only.
  const [visualHighlightNodeId, setVisualHighlightNodeId] = useState<string | null>(null);

  // Derived: sigma receives whichever ID is active — full selection takes priority.
  const selectedNodeId = selectedNodeInfo?.id ?? visualHighlightNodeId;

  const handleNodeClick = useCallback((
    nodeId: string,
    label: string,
    nodeType: string,
    degree: number,
    edges: SelectedNodeInfo["edges"],
  ) => {
    // Toggle: clicking the already-selected node deselects it.
    setSelectedNodeInfo((prev) =>
      prev?.id === nodeId ? null : { id: nodeId, label, type: nodeType, degree, edges },
    );
    setSelectedEdgeInfo(null);
    setVisualHighlightNodeId(null); // graph-click supersedes any right-rail highlight
  }, []);

  const handleEdgeClick = useCallback((info: SelectedEdgeInfo) => {
    setSelectedEdgeInfo(info);
    setSelectedNodeInfo(null);
    setVisualHighlightNodeId(null);
  }, []);

  const handleClearSelection = useCallback(() => {
    setSelectedNodeInfo(null);
    setSelectedEdgeInfo(null);
    setVisualHighlightNodeId(null);
  }, []);

  // Reset selection when entity changes (stale selection from prior entity would
  // point at nodes that don't exist in the new graph payload).
  useEffect(() => {
    setSelectedNodeInfo(null);
    setSelectedEdgeInfo(null);
    setVisualHighlightNodeId(null);
  }, [entityId]);

  // Push "page" scope so j/k/Enter (news) and 1/2/3/g/r/Esc (graph) bindings
  // are active while this tab is mounted. Pop on unmount / tab switch.
  const { pushScope, popScope } = useHotkeyScope();
  useEffect(() => {
    pushScope("page");
    return () => popScope("page");
  }, [pushScope, popScope]);

  return (
    // WHY grid-cols-14 4+5+5: W7 §3 layout, revised to widen right rail.
    // Literal class so JIT scanner picks it up.
    // h-full + overflow-hidden lock the tab to the parent's scroll context;
    // each column owns its own overflow independently.
    <div className="grid grid-cols-14 h-full overflow-hidden">
      {/* ── LEFT: dense news rail (4/14 ≈ 28.6%) ──────────────────────────
          Unchanged from W7 initial implementation. */}
      <div className="col-span-4 overflow-y-auto border-r border-border">
        <NewsColumn instrumentId={entityId} />
      </div>

      {/* ── CENTER: graph + inline detail below (5/14 ≈ 35.7%) ─────────────
          Flex column: GraphColumn takes flex-1 (all remaining vertical),
          InlineSelectionPanel takes fixed 180px below when active. */}
      <div className="col-span-5 flex flex-col border-r border-border overflow-hidden">
        <div className="flex-1 min-h-0 overflow-hidden">
          <GraphColumn
            entityId={entityId}
            selectedNodeId={selectedNodeId}
            onNodeSelect={(id) => {
              // WHY onNodeSelect still needed: GraphColumn uses it internally
              // for the toggle (deselect on same-node click). The full info
              // arrives via onNodeClick which was called with the node data.
              // Pass null to GraphColumn to clear visual highlight on deselect.
              if (id === null) handleClearSelection();
            }}
            onNodeClickFull={handleNodeClick}
            onEdgeSelect={handleEdgeClick}
          />
        </div>
        <InlineSelectionPanel
          selectedNode={selectedNodeInfo}
          selectedEdge={selectedEdgeInfo}
          onClear={handleClearSelection}
        />
      </div>

      {/* ── RIGHT: entity overview (5/14 ≈ 35.7%) — always overview mode ───
          WHY always overview: node/edge detail is now in InlineSelectionPanel
          below the graph. The right rail is persistently useful context
          (top relations, path insights, contradictions, narrative history)
          rather than switching away when the analyst clicks a node. */}
      <div className="col-span-5 overflow-y-auto">
        <ContextPanel
          entityId={entityId}
          onNodeSelect={(nodeId) => {
            // WHY visualHighlightNodeId (not selectedNodeInfo): TopRelationsBlock
            // row clicks only have a nodeId, not the full edges list needed to
            // render InlineSelectionPanel. Use the visual-only highlight slot so
            // sigma shows the yellow ring without opening the detail panel.
            setVisualHighlightNodeId(nodeId);
            setSelectedNodeInfo(null);
            setSelectedEdgeInfo(null);
          }}
        />
      </div>
    </div>
  );
}
