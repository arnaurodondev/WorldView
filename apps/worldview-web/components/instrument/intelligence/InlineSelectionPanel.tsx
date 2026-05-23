/**
 * InlineSelectionPanel — node / edge detail strip rendered below the sigma graph.
 *
 * WHY THIS EXISTS (Block I, T-26 / T-27):
 * Clicking a graph node or edge previously switched the RIGHT rail to a detail
 * view, hiding the persistent entity-overview context. Moving the detail inline
 * (below the graph) lets the right rail always show overview data while the
 * analyst inspects a specific node or edge immediately next to the canvas that
 * produced the click.
 *
 * MODES:
 *   node — shows entity label + type + incident edges (collapsed list)
 *   edge — shows source → relation → target + weight + evidence snippets
 *   null — renders nothing (zero height)
 *
 * HEIGHT: fixed 180 px with overflow-y-auto — tall enough for 5 evidence
 * snippets at 18 px each without pushing the graph off screen.
 */

"use client";
// WHY "use client": onClick callbacks require browser context.

import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";

// ── Node selection type (sourced from GraphEvents.clickNode callback) ─────────

export interface SelectedNodeInfo {
  id: string;
  label: string;
  type: string;
  degree: number;
  edges: Array<{ label: string; weight: number; neighborId: string; neighborLabel: string }>;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface InlineSelectionPanelProps {
  selectedNode: SelectedNodeInfo | null;
  selectedEdge: SelectedEdgeInfo | null;
  /** Dismiss the panel and clear both selections. */
  onClear: () => void;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function relLabel(raw: string): string {
  return raw.replace(/_/g, " ").toLowerCase();
}

function weightBar(weight: number): React.ReactElement {
  const pct = Math.round(weight * 100);
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-mono tabular-nums text-muted-foreground shrink-0">
      <span className="block h-1.5 w-[40px] bg-muted/40 rounded-[1px] overflow-hidden">
        <span
          className="block h-full bg-muted-foreground/50 rounded-[1px]"
          style={{ width: `${pct}%` }}
        />
      </span>
      {pct}
    </span>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InlineSelectionPanel({ selectedNode, selectedEdge, onClear }: InlineSelectionPanelProps) {
  if (!selectedNode && !selectedEdge) return null;

  return (
    <div
      className={cn(
        "border-t border-border/40 bg-card/50 overflow-y-auto shrink-0",
        // WHY h-[180px]: fixed height keeps the graph stable; tall enough for
        // 5 evidence rows at 18px + header + stats.
        "h-[180px]",
      )}
    >
      {/* ── Header row ─────────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border/40 bg-card/80 px-3 h-[22px] backdrop-blur-sm">
        <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
          {selectedNode
            ? `${selectedNode.type.toUpperCase()} · ${selectedNode.label}`
            : selectedEdge
              ? relLabel(selectedEdge.label).toUpperCase()
              : ""}
        </span>
        <button
          type="button"
          aria-label="Close selection panel"
          onClick={onClear}
          className="text-muted-foreground/60 hover:text-foreground transition-colors"
        >
          <X className="h-3 w-3" />
        </button>
      </div>

      {/* ── Node mode ──────────────────────────────────────────────────────── */}
      {selectedNode && (
        <div>
          <div className="h-[18px] flex items-center px-3 gap-2 border-b border-border/30">
            <span className="text-[10px] font-mono text-muted-foreground">
              {selectedNode.degree} connection{selectedNode.degree !== 1 ? "s" : ""}
            </span>
          </div>
          {selectedNode.edges.slice(0, 6).map((e, i) => (
            <div
              key={i}
              className="h-[18px] flex items-center px-3 gap-2 border-b border-border/20"
            >
              <span className="text-[10px] text-muted-foreground w-[80px] shrink-0 truncate">
                {relLabel(e.label)}
              </span>
              <span className="text-[11px] text-foreground/90 flex-1 truncate">
                {e.neighborLabel}
              </span>
              {weightBar(e.weight)}
            </div>
          ))}
        </div>
      )}

      {/* ── Edge mode ──────────────────────────────────────────────────────── */}
      {selectedEdge && (
        <div>
          {/* Source → target breadcrumb */}
          <div className="h-[22px] flex items-center px-3 gap-1.5 border-b border-border/30">
            <span className="text-[11px] font-medium text-foreground/90 truncate max-w-[120px]">
              {selectedEdge.sourceLabel}
            </span>
            <span className="text-[9px] text-muted-foreground shrink-0">→</span>
            <span className="text-[9px] uppercase font-mono tracking-wider text-primary/80 shrink-0 truncate max-w-[100px]">
              {relLabel(selectedEdge.label)}
            </span>
            <span className="text-[9px] text-muted-foreground shrink-0">→</span>
            <span className="text-[11px] font-medium text-foreground/90 truncate max-w-[120px]">
              {selectedEdge.targetLabel}
            </span>
            {/* WHY direction badge: asymmetric types (employs, acquired_by, subsidiary_of)
                read differently depending on which entity is the subject. Showing outbound/inbound
                lets analysts immediately understand the semantic orientation. */}
            {selectedEdge.direction && selectedEdge.direction !== "lateral" && (
              <span
                className={cn(
                  "text-[8px] font-mono uppercase tracking-wider px-1 py-0.5 rounded shrink-0",
                  selectedEdge.direction === "outbound"
                    ? "text-positive/80 bg-positive/10"
                    : "text-chart-2/80 bg-chart-2/10",
                )}
              >
                {selectedEdge.direction}
              </span>
            )}
            <span className="ml-auto shrink-0">{weightBar(selectedEdge.weight)}</span>
          </div>

          {/* LLM summary */}
          {selectedEdge.relation_summary && (
            <div className="px-3 py-1.5 border-b border-border/20">
              <p className="text-[10px] text-muted-foreground/80 leading-snug line-clamp-2 italic">
                {selectedEdge.relation_summary}
              </p>
            </div>
          )}

          {/* Evidence snippets (T-26 spec) */}
          {selectedEdge.evidence_snippets.length > 0 && (
            <div className="px-3 pt-1 space-y-1">
              <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground/60 block">
                EVIDENCE · {selectedEdge.evidence_snippets.length} snippet{selectedEdge.evidence_snippets.length !== 1 ? "s" : ""}
              </span>
              {selectedEdge.evidence_snippets.slice(0, 3).map((snippet, i) => (
                <blockquote
                  key={i}
                  className="border-l-2 border-border/40 pl-2 text-[9px] text-muted-foreground/70 leading-tight line-clamp-2"
                >
                  {`"${snippet}"`}
                </blockquote>
              ))}
            </div>
          )}

          {selectedEdge.evidence_snippets.length === 0 && !selectedEdge.relation_summary && (
            <div className="px-3 py-2">
              <p className="text-[10px] text-muted-foreground/50 italic">No evidence or summary available.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
