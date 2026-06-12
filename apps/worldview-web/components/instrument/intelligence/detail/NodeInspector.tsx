/**
 * detail/NodeInspector.tsx — enriched node dossier for the Intelligence tab's
 * selection inspector (PLAN-0099 Wave 2).
 *
 * WHY THIS EXISTS (replaces context/NodeDetailCard.tsx):
 * The retired NodeDetailCard rendered label/type/weight/ticker plus a fetched
 * description. Wave 1 enriched GET /v1/entities/{id} with health_score,
 * aliases, top_relations (with LLM summaries) and relation_count — this
 * inspector surfaces all of it, plus three actions the investigation flow
 * needs:
 *   - "Open instrument" — navigates to /instruments/{ticker} when the node is
 *     a listed instrument (ticker present on the GraphNode payload).
 *   - "Focus graph here" — animates the canvas camera onto this node
 *     (FocusNodeController), so the analyst can read its local neighbourhood.
 *   - Top-relation rows — open the EDGE inspector for that relation
 *     (the list-first path to edge detail; same flow as a canvas edge click).
 *
 * PORTED CONTRACTS (from NodeDetailCard.test.tsx — kept verbatim so the
 * ported assertions hold):
 *   - label + normalised type badge ("financial_instrument" → "financial instrument")
 *   - "Node weight" row only when node.size is a number
 *   - "Ticker" row only when node.ticker is truthy
 *   - a clear/back control with an accessible name
 *
 * DATA SOURCES:
 *   - props.node (GraphNode from the graph cache — label/type/size/ticker)
 *   - ["entity-detail", node.id] → EntityDetailEnriched (description, health,
 *     aliases, top_relations). 404→null = "not enriched yet", a normal state.
 *
 * WHO USES IT: SelectionDetailPanel (node mode).
 */

"use client";
// WHY "use client": useQuery + router navigation + click handlers.

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Crosshair, ExternalLink, MessageSquare } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { cn, formatDate } from "@/lib/utils";
import type { EntityDetailEnriched } from "@/lib/api/knowledge-graph";
import type { GraphNode } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface NodeInspectorProps {
  /** Entity id of the selected node — the only REQUIRED identity. */
  readonly nodeId: string;
  /**
   * The GraphNode payload when the node is present in the rendered graph
   * (canvas click / chip click). May be null when the selection arrived from
   * an edge-inspector endpoint pill whose entity is OUTSIDE the current graph
   * snapshot — the inspector then renders entirely from the entity-detail
   * fetch (canonical_name/entity_type) instead of degrading to a dead end.
   */
  readonly graphNode?: GraphNode | null;
  /** Opens the edge inspector for one of this node's top relations. */
  readonly onSelectRelation?: (relationId: string) => void;
  /** "Focus graph here" — centre the canvas camera on this node. */
  readonly onFocusNode?: (nodeId: string) => void;
  /** Opens the entity chat strip (anchor-scoped — see EntityChatPanel). */
  readonly onDiscuss?: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Same 3-bucket health classes used by the dossier — one colour language. */
function healthClass(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "text-muted-foreground bg-muted";
  if (score >= 0.75) return "text-positive bg-positive/15";
  if (score >= 0.5) return "text-warning bg-warning/15";
  return "text-negative bg-negative/15";
}

function formatHealth(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return `${Math.round(score * 100)}%`;
}

// ── Component ────────────────────────────────────────────────────────────────

export function NodeInspector({
  nodeId,
  graphNode = null,
  onSelectRelation,
  onFocusNode,
  onDiscuss,
}: NodeInspectorProps) {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY ["entity-detail", id]: the SAME key family the dossier/bundle use —
  // inspecting the root node re-reads the already-hydrated cache; inspecting a
  // neighbour fires one fetch then caches it for the session (descriptions are
  // stable; 30min staleTime mirrors the retired NodeDetailCard's policy).
  const { data: detail } = useQuery<EntityDetailEnriched | null>({
    queryKey: ["entity-detail", nodeId],
    queryFn: () => createGateway(accessToken).getEntityDetail(nodeId),
    enabled: !!accessToken && !!nodeId,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  // Identity resolution order: graph payload (zero-latency) → entity detail
  // (covers off-graph selections from edge endpoint pills) → id stub.
  const label = graphNode?.label ?? detail?.canonical_name ?? nodeId;
  const rawType = graphNode?.type ?? detail?.entity_type ?? null;
  const typeLabel = rawType ? rawType.replace(/_/g, " ") : null;
  const ticker = graphNode?.ticker || detail?.ticker || null;
  const weight = graphNode?.size;
  const aliases = detail?.aliases ?? [];
  const topRelations = detail?.top_relations ?? [];
  const health = detail?.health_score ?? null;
  // GraphNode.description (S9 forwards it on graph nodes since Wave 1) is the
  // zero-latency first paint; the entity-detail fetch upgrades it.
  const description = detail?.description ?? graphNode?.description ?? null;

  return (
    <div className="p-3 space-y-2 text-left" aria-label={`Selected node: ${label}`}>
      {/* ── Header: name + type + health ──────────────────────────────────── */}
      <div className="flex items-center gap-1.5 min-w-0">
        <h3
          className="text-[12px] font-semibold text-foreground leading-tight truncate"
          title={label}
        >
          {label}
        </h3>
        {typeLabel && (
          <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]">
            {typeLabel}
          </span>
        )}
        {/* Health only when the enrichment payload provides it — neighbours
            without enrichment show no badge (absence beats a misleading "—"
            in this compact header; the dossier keeps the always-on variant). */}
        {health != null && (
          <span
            className={cn(
              "ml-auto shrink-0 text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px] tabular-nums",
              healthClass(health),
            )}
            title="Composite KG health"
            aria-label={`Entity health ${formatHealth(health)}`}
          >
            {formatHealth(health)}
          </span>
        )}
      </div>

      {/* ── Action row: open instrument / focus graph / discuss ───────────── */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {/* "Open instrument" ONLY for nodes with a ticker — the KG↔S3 bridge
            (GraphNode.ticker docstring). People/sectors have no page to open. */}
        {ticker && (
          <button
            type="button"
            onClick={() => router.push(`/instruments/${encodeURIComponent(ticker)}`)}
            data-testid="node-open-instrument"
            className="flex items-center gap-1 border border-border/60 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <ExternalLink className="h-2.5 w-2.5" strokeWidth={1.5} aria-hidden />
            Open instrument
          </button>
        )}
        {/* Focus only makes sense for nodes that EXIST in the rendered graph —
            off-graph selections (edge endpoint pills) have no canvas position. */}
        {onFocusNode && graphNode && (
          <button
            type="button"
            onClick={() => onFocusNode(nodeId)}
            data-testid="node-focus-graph"
            className="flex items-center gap-1 border border-border/60 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <Crosshair className="h-2.5 w-2.5" strokeWidth={1.5} aria-hidden />
            Focus graph here
          </button>
        )}
        {onDiscuss && (
          <button
            type="button"
            onClick={onDiscuss}
            data-testid="node-discuss"
            className="flex items-center gap-1 border border-border/60 rounded-[2px] px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-border focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <MessageSquare className="h-2.5 w-2.5" strokeWidth={1.5} aria-hidden />
            Discuss
          </button>
        )}
      </div>

      {/* ── Description ─────────────────────────────────────────────────────
          Stable slot: italic placeholder when missing so the panel height
          doesn't jump when the entity-detail fetch lands. */}
      <p className="text-[11px] leading-relaxed text-foreground/80">
        {description ?? (
          <span className="italic text-muted-foreground">Description unavailable.</span>
        )}
      </p>

      {/* ── Aliases chips (enrichment) ──────────────────────────────────────── */}
      {aliases.length > 0 && (
        <div className="flex flex-wrap gap-1" data-testid="node-aliases">
          {aliases.slice(0, 6).map((a) => (
            <span
              key={`${a.alias_text}-${a.alias_type}`}
              className="text-[9px] font-mono bg-muted text-muted-foreground px-1 py-0.5 rounded-[2px]"
              title={a.alias_type ?? undefined}
            >
              {a.alias_text}
            </span>
          ))}
        </div>
      )}

      {/* ── Metadata rows: weight / ticker / enriched_at ────────────────────
          PORTED CONTRACT: "Node weight" renders ONLY for numeric size;
          "Ticker" renders ONLY when truthy (no-noise policy). */}
      {typeof weight === "number" && (
        <div className="flex items-center justify-between">
          <span className="text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
            Node weight
          </span>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {weight.toFixed(2)}
          </span>
        </div>
      )}
      {ticker && (
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 w-[88px] text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
            Ticker
          </span>
          <span className="font-mono text-[11px] text-foreground/80 truncate">{ticker}</span>
        </div>
      )}
      {detail?.enriched_at && (
        <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/70">
          Updated{" "}
          <span className="tabular-nums text-muted-foreground">{formatDate(detail.enriched_at)}</span>
        </p>
      )}

      {/* ── Top relations (with LLM summaries) ─────────────────────────────
          Clicking a row opens the EDGE inspector — the list-first path to the
          relation dossier. Summary renders under the row when present so the
          analyst can triage without opening each relation. */}
      {topRelations.length > 0 && (
        <div className="space-y-1 border-t border-border/40 pt-1.5">
          <header className="flex items-center justify-between">
            <h4 className="text-[9px] font-mono uppercase tracking-[0.07em] text-muted-foreground">
              Top relations
            </h4>
            <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
              {detail?.relation_count ?? topRelations.length}
            </span>
          </header>
          <ul role="list" className="space-y-1">
            {topRelations.slice(0, 6).map((r) => (
              <li key={r.relation_id}>
                <button
                  type="button"
                  onClick={() => onSelectRelation?.(r.relation_id)}
                  disabled={!onSelectRelation}
                  data-testid={`node-relation-${r.relation_id}`}
                  className="w-full text-left px-1 py-0.5 rounded-[2px] hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default"
                >
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="shrink-0 text-[9px] text-muted-foreground/60 font-mono">
                      {r.direction === "inbound" ? "←" : "→"}
                    </span>
                    <span className="shrink-0 text-[9px] font-mono uppercase tracking-wider text-muted-foreground">
                      {r.canonical_type.replace(/_/g, " ")}
                    </span>
                    <span className="flex-1 truncate text-[11px] text-foreground/80" title={r.other_entity_name}>
                      {r.other_entity_name}
                    </span>
                    {typeof r.confidence === "number" && (
                      <span className="shrink-0 font-mono text-[9px] tabular-nums text-muted-foreground">
                        {r.confidence.toFixed(2)}
                      </span>
                    )}
                  </span>
                  {r.relation_summary && (
                    <span className="block pl-4 text-[10px] text-muted-foreground line-clamp-2">
                      {r.relation_summary}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
