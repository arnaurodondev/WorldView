/**
 * components/instrument/intelligence/context/RelationsList.tsx — PLAN-0090 T-D-03
 *
 * WHY THIS EXISTS:
 * When a graph node is selected, the user wants to see all relationships that
 * touch that node — not just the visual lines on the graph. This list renders
 * each relation as a "source → target" row with the LLM-generated summary from
 * `relation_summary` (Worker 13C). Without this list, the user has to hover
 * every edge in the graph to read its summary — unusable for >5 edges.
 *
 * DATA SOURCE: GraphEdge[] passed by the parent (ContextPanel). The parent
 * filters the full edge list to just the edges incident to the selected node;
 * this component is dumb and just renders whatever it receives.
 *
 * WHY a fallback string for null relation_summary:
 * `relation_summary` is null when SummaryWorker hasn't yet processed the edge.
 * Showing an empty row would make the list look broken. "No summary available."
 * is the explicit, scannable null-state per the spec (§6.10).
 */

"use client";
// WHY "use client": no hooks, but lives inside the client-side ContextPanel
// tree. Marking it explicitly avoids accidental server-component rendering if
// imported elsewhere — a cheap safety hatch.

import { cn } from "@/lib/utils";
import type { GraphEdge, GraphNode } from "@/types/api";

/**
 * Props for RelationsList.
 *
 * WHY also accepting a `nodesById` map: GraphEdge stores source/target as
 * entity_id strings. To render the human-readable "Apple → Tim Cook" line we
 * need the labels. Passing a pre-built lookup is faster than rebuilding it
 * inside this component on every render (the parent builds it once).
 */
export interface RelationsListProps {
  /** Edges incident to the selected node. Pre-filtered by the parent so this
   *  component never has to know WHICH node is selected. */
  edges: GraphEdge[];
  /** Optional id→node lookup so we can resolve entity_ids to readable labels.
   *  When absent we fall back to displaying the raw entity_id (better than
   *  rendering nothing — at least debuggable). */
  nodesById?: Record<string, GraphNode>;
  /** Optional class for spacing/layout overrides. */
  className?: string;
}

// ── Constants ────────────────────────────────────────────────────────────────

/** WHY this exact string: matches the spec (§6.10) verbatim — UI copy must be
 *  stable so QA scripts and a11y audits can grep for it. */
const NO_SUMMARY_FALLBACK = "No summary available.";

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * resolveLabel — entity_id → display string.
 *
 * WHY a helper (not inline): used twice per row (source + target). Inlining
 * the ternary would obscure the intent and risk diverging fallbacks.
 */
function resolveLabel(
  entityId: string,
  nodesById: Record<string, GraphNode> | undefined,
): string {
  const node = nodesById?.[entityId];
  // WHY fall back to entity_id (not "Unknown"): unknown labels are usually a
  // transient cache miss during graph load. Showing the id lets devs debug
  // the mismatch in production logs without exposing scary copy to users.
  return node?.label ?? entityId;
}

// ── Component ────────────────────────────────────────────────────────────────

export function RelationsList({ edges, nodesById, className }: RelationsListProps) {
  // WHY an explicit empty-state: an empty <ul> with no items is invisible to
  // the user — they would think the panel is broken. A short copy line keeps
  // the surface area honest.
  if (edges.length === 0) {
    return (
      <section className={cn("p-3", className)} aria-label="Relations">
        <p className="text-[11px] text-muted-foreground italic">
          No relations for this node.
        </p>
      </section>
    );
  }

  return (
    <section className={cn("p-3 space-y-2", className)} aria-label="Relations">
      {/* ── Section header ─────────────────────────────────────────────────
          WHY a header at all: distinguishes this section from the node detail
          card above it. Without it, the relations list visually merges into
          the metadata block — bad scannability. */}
      <header className="flex items-center justify-between">
        <h4 className="text-[9px] font-mono uppercase tracking-[0.07em] text-muted-foreground">
          Relations
        </h4>
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
          {/* WHY show the count: when a node has 30+ edges, the user wants to
              know the total at a glance before scrolling. tabular-nums keeps
              the count visually anchored to the right. */}
          {edges.length}
        </span>
      </header>

      {/* ── List ───────────────────────────────────────────────────────────
          WHY <ul> + role="list": some screen readers strip the list semantics
          off un-styled lists; the explicit role guarantees the right output.
          WHY space-y-2 (not divide-y): a 2 px gap reads less heavy than a
          divider line — important when 20+ relations stack vertically. */}
      <ul role="list" className="space-y-2">
        {edges.map((edge) => {
          const sourceLabel = resolveLabel(edge.source, nodesById);
          const targetLabel = resolveLabel(edge.target, nodesById);
          // WHY normalise the relation label for display: relation `label`
          // arrives lowercase with underscores ("competes_with"). Spaces read
          // better in prose context — but we keep them lowercase so they look
          // like the rest of the Finviz-density UI.
          const relationLabel = edge.label.replace(/_/g, " ");

          return (
            <li
              key={edge.id}
              // WHY a bordered card per row: groups the 3 lines (header,
              // arrow, summary) visually so the eye doesn't conflate them
              // with the next row. border-border/40 = subtle, not heavy.
              className="border border-border/40 rounded-[2px] p-2 space-y-1"
            >
              {/* ── Row 1: source → target with relation label ────────── */}
              <div className="flex items-center gap-1.5 text-[11px] leading-tight">
                <span className="font-mono text-foreground/80 truncate" title={sourceLabel}>
                  {sourceLabel}
                </span>
                {/* WHY a Unicode arrow: see NodeDetailCard.tsx — consistent
                    iconography across the context panel, zero bundle weight. */}
                <span aria-hidden="true" className="text-muted-foreground/60 shrink-0">
                  →
                </span>
                <span className="font-mono text-foreground/80 truncate" title={targetLabel}>
                  {targetLabel}
                </span>
              </div>

              {/* ── Row 2: relation type + confidence ───────────────────
                  WHY both on the same row: a relation TYPE without strength
                  is meaningless to a finance user. Same row prevents users
                  from reading the label and missing the weak-evidence flag. */}
              <div className="flex items-center justify-between gap-2">
                <span className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
                  {relationLabel}
                </span>
                {/* WHY conditional: weight is `number` (required), but defensive
                    typeof check guards against unexpected runtime values (e.g.,
                    backend regression returning null). */}
                {typeof edge.weight === "number" && (
                  <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
                    {/* WHY toFixed(2): two decimals fit confidence [0,1]
                        compactly without rounding away meaningful detail. */}
                    {edge.weight.toFixed(2)}
                  </span>
                )}
              </div>

              {/* ── Row 3: summary (or fallback) ────────────────────────
                  WHY render the fallback in a dimmer color: distinguishes a
                  KNOWN missing value from a real summary. Otherwise users
                  might read it as a one-line title and click "no value". */}
              <p
                className={cn(
                  "text-[11px] leading-relaxed",
                  edge.relation_summary
                    ? "text-foreground/80"
                    : "text-muted-foreground italic",
                )}
              >
                {edge.relation_summary ?? NO_SUMMARY_FALLBACK}
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
