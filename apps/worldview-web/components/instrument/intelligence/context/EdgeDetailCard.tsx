/**
 * context/EdgeDetailCard.tsx — right-rail edge detail mode (W7 Block I, T-26).
 *
 * WHY THIS EXISTS: Clicking a graph edge switches the right panel to edge-detail
 * mode. This card shows the full context for a single relation: the entities it
 * connects, its LLM summary, temporal decay class, and evidence snippets.
 *
 * WHY NO NETWORK FETCH: The edge data is already in the TanStack Query graph
 * cache (populated by GraphColumn's depth=2 fetch). Reading from the cache avoids
 * a redundant S9 round-trip and ensures the card renders instantly on click.
 *
 * DESIGN REFERENCE: W7 §1 checks 24/25 (Δ11 + Δ20); T-26 spec (≤150 LOC).
 * DATA SOURCE: queryClient.getQueryData(qk.instruments.entityGraph(entityId, depth))
 *              — zero new network requests.
 *
 * WHO USES IT: ContextPanel (third mode when selectedEdgeId is set).
 */

"use client";
// WHY "use client": useQueryClient + keyboard event listener require browser.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import type { EntityGraph, GraphEdge, GraphNode } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * decayBadgeClass — maps decay_class → color token class.
 *
 * WHY semantic tokens (not raw Tailwind colors): no-off-palette-colors rule.
 * PERMANENT/DURABLE = positive (relation is stable, reliable signal).
 * SLOW/MEDIUM = warning (relation fades, use with caution).
 * FAST/EPHEMERAL = negative (relation is transient, low reliability).
 */
function decayBadgeClass(decayClass: string | null | undefined): string {
  const d = (decayClass ?? "").toUpperCase();
  if (d === "PERMANENT" || d === "DURABLE") return "text-positive bg-positive/15";
  if (d === "SLOW" || d === "MEDIUM") return "text-warning bg-warning/15";
  if (d === "FAST" || d === "EPHEMERAL") return "text-negative bg-negative/15";
  // Unknown decay class → neutral muted style
  return "text-muted-foreground bg-muted";
}

/**
 * formatDate — ISO timestamp → "12 Jun 2026" string.
 * WHY fixed format: avoids server/client locale mismatch during SSR hydration.
 */
function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  } catch {
    return iso;
  }
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface EdgeDetailCardProps {
  /** The edge id that was clicked. Null = card should not be visible. */
  edgeId: string | null;
  /** The primary entity id (used to locate the correct graph cache slot). */
  entityId: string;
  /** Currently active graph depth (used to target the right cache key). */
  graphDepth?: number;
  /** Callback to close the card and return to overview / node-detail mode. */
  onClose: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EdgeDetailCard({
  edgeId,
  entityId,
  graphDepth = 2,
  onClose,
}: EdgeDetailCardProps) {
  const qc = useQueryClient();

  // ── Esc key to close (accessibility + power-user UX) ─────────────────────
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // ── Read edge from graph cache (zero new requests) ────────────────────────
  const graph = qc.getQueryData<EntityGraph>(qk.instruments.entityGraph(entityId, graphDepth));
  const edge: GraphEdge | null = graph?.edges.find((e) => e.id === edgeId) ?? null;

  // Build a node lookup from cache so we can resolve source/target labels
  const nodesById: Record<string, GraphNode> = {};
  for (const n of graph?.nodes ?? []) {
    nodesById[n.id] = n;
  }

  // ── Edge not found (cache miss or stale cache) ────────────────────────────
  if (!edge) {
    return (
      <section className="p-3 space-y-2" aria-label="Edge detail">
        <button
          type="button"
          onClick={onClose}
          className="text-[10px] font-mono text-muted-foreground hover:text-foreground"
        >
          ← Back
        </button>
        <p className="text-[10px] text-muted-foreground italic">
          Edge data not available — select a depth to reload the graph.
        </p>
      </section>
    );
  }

  const sourceNode = nodesById[edge.source];
  const targetNode = nodesById[edge.target];
  const sourceLabel = sourceNode?.label ?? edge.source;
  const targetLabel = targetNode?.label ?? edge.target;
  const relationLabel = edge.label.replace(/_/g, " ").toUpperCase();
  const decayClass = edge.decay_class ?? null;
  const snippets = (edge.evidence_snippets ?? []).slice(0, 5);
  const strengthPct = Math.round(edge.weight * 100);

  return (
    <section className="p-3 space-y-3 overflow-y-auto" aria-label="Edge detail">
      {/* ── Back button ────────────────────────────────────────────────────── */}
      <button
        type="button"
        onClick={onClose}
        className="text-[10px] font-mono text-muted-foreground hover:text-foreground"
      >
        ← Back
      </button>

      {/* ── Breadcrumb: SOURCE → RELATION → TARGET ─────────────────────────── */}
      <div className="space-y-0.5">
        <p
          className="text-[12px] font-semibold text-foreground leading-tight"
          title={`${sourceLabel} → ${relationLabel} → ${targetLabel}`}
        >
          <span className="truncate">{sourceLabel}</span>
          <span className="text-muted-foreground font-normal mx-1">→</span>
          <span className="text-[10px] font-mono text-foreground/80">{relationLabel}</span>
          <span className="text-muted-foreground font-normal mx-1">→</span>
          <span className="truncate">{targetLabel}</span>
        </p>
      </div>

      {/* ── Strength bar ───────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-wider shrink-0">
          Strength
        </span>
        {/* WHY relative bar: gives immediate visual impression of relation
            confidence without forcing the analyst to parse the raw decimal. */}
        <div className="flex-1 h-[3px] bg-muted rounded-[1px]">
          <div
            className="h-full bg-foreground/60 rounded-[1px]"
            style={{ width: `${strengthPct}%` }}
          />
        </div>
        <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
          {strengthPct} / 100
        </span>
      </div>

      {/* ── Decay badge ────────────────────────────────────────────────────── */}
      {decayClass && (
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-wider">
            Decay
          </span>
          <span
            className={cn(
              "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px]",
              decayBadgeClass(decayClass),
            )}
          >
            {decayClass.toUpperCase()}
          </span>
        </div>
      )}

      {/* ── LLM relation summary ─────────────────────────────────────────────
          WHY italic when null: absence of a summary is informative — the
          SummaryWorker hasn't processed this relation yet. Italic makes it
          visually distinct from real content. */}
      <p
        className={cn(
          "text-[11px] leading-relaxed",
          edge.relation_summary ? "text-foreground/80" : "text-muted-foreground italic",
        )}
        style={{ WebkitLineClamp: 4, overflow: "hidden", display: "-webkit-box", WebkitBoxOrient: "vertical" }}
      >
        {edge.relation_summary ?? "No summary available."}
      </p>

      {/* ── Evidence snippets ─────────────────────────────────────────────── */}
      {snippets.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
            Evidence · {edge.evidence_count ?? snippets.length} article{snippets.length !== 1 ? "s" : ""}
          </p>
          {snippets.map((s, i) => (
            // WHY blockquote: semantic HTML for quoted source material.
            // border-l-2 + pl-2 is the design-system pattern for evidence rows.
            <blockquote
              // eslint-disable-next-line react/no-array-index-key
              key={i}
              className="border-l-2 border-border/40 pl-2 text-[9px] text-foreground/70 leading-snug"
            >
              {s}
            </blockquote>
          ))}
        </div>
      )}

      {/* ── Temporal info ─────────────────────────────────────────────────── */}
      {edge.latest_evidence_at && (
        <p className="text-[9px] font-mono text-muted-foreground">
          Last seen: {formatDate(edge.latest_evidence_at)}
        </p>
      )}
    </section>
  );
}
