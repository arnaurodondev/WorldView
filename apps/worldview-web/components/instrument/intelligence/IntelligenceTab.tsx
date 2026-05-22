/**
 * IntelligenceTab — W7 T-16 — orchestrator for the Intelligence tab.
 *
 * WHY THIS EXISTS (PRD-0089 §6.9):
 * The Intelligence tab is a 3-column grid (14-col base, 4+7+3):
 *   left   (col-span-4) : <NewsColumn />   — dense 18px news rail
 *   center (col-span-7) : <GraphColumn />  — brief + sigma.js graph
 *   right  (col-span-3) : <ContextPanel /> — entity overview / node detail
 *
 * WHY 14-COL (not 12): W7 design doc §3 — the extra 2 columns give the
 * graph center more breathing room (7/14 = 50% same ratio, but 4/14 vs 3/12
 * widens the news rail from 25% → 28.6% to accommodate 18px row density).
 *
 * STATE OWNERSHIP — `selectedNodeId` is lifted here so ContextPanel (right)
 * and GraphColumn (center) share a single source of truth. Keeping selection
 * at the smallest common parent avoids a context provider for a single string.
 *
 * HOTKEY SCOPE — IntelligenceTab pushes the "page" scope on mount and pops
 * it on unmount. This activates the j/k/Enter news bindings (T-17) and the
 * 1/2/3/g/r/Esc graph bindings (T-18) which are registered under scope="page"
 * by their respective columns.
 */

"use client";
// WHY "use client": useState + useEffect + useHotkeyScope require the browser.

import { useState, useEffect } from "react";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { NewsColumn } from "./news/NewsColumn";
import { GraphColumn } from "./graph/GraphColumn";
import { ContextPanel } from "./context/ContextPanel";

export interface IntelligenceTabProps {
  /** Authoritative KG entity_id for the instrument being viewed. */
  readonly entityId: string;
}

export function IntelligenceTab({ entityId }: IntelligenceTabProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Push "page" scope so j/k/Enter (news) and 1/2/3/g/r/Esc (graph) bindings
  // are active while this tab is mounted. Pop on unmount / tab switch.
  const { pushScope, popScope } = useHotkeyScope();
  useEffect(() => {
    pushScope("page");
    return () => popScope("page");
  }, [pushScope, popScope]);

  return (
    // WHY grid-cols-14: W7 §3 — 4+7+3 split. Literal class so JIT scanner picks it up.
    // h-full + overflow-hidden lock the tab to the parent's scroll context;
    // each column owns its own overflow independently.
    <div className="grid grid-cols-14 h-full overflow-hidden">
      {/* ── LEFT: dense news rail (4/14 ≈ 28.6%) ──────────────────────────
          Extra column vs. previous 3/12 to accommodate 18px DenseArticleRow
          density — wider rail shows more of each headline before truncation. */}
      <div className="col-span-4 overflow-y-auto border-r border-border">
        <NewsColumn instrumentId={entityId} />
      </div>

      {/* ── CENTER: graph + brief (7/14 = 50%) ─────────────────────────────
          GraphColumn manages its own internal layout (brief strip on top,
          depth toolbar, sigma.js canvas fills remaining height). */}
      <div className="col-span-7 flex flex-col border-r border-border">
        <GraphColumn
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onNodeSelect={setSelectedNodeId}
        />
      </div>

      {/* ── RIGHT: context panel (3/14 ≈ 21.4%) ────────────────────────────
          selectedNodeId === null → entity-overview (5-block stack).
          selectedNodeId !== null → node-detail (NodeDetailCard + paths). */}
      <div className="col-span-3 overflow-y-auto">
        <ContextPanel
          entityId={entityId}
          selectedNodeId={selectedNodeId}
          onClearSelection={() => setSelectedNodeId(null)}
          onNodeSelect={setSelectedNodeId}
        />
      </div>
    </div>
  );
}
