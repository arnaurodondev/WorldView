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
 *
 * LAZY ENTITY DETAIL (Task 1):
 * When `selectedNode.description === null` (graph response didn't include a
 * description — common for nodes that haven't been through the enrichment
 * pipeline yet), this component fires a lazy `useQuery(qk.kg.entityDetail(id))`
 * to fetch the full entity record and display the description.
 * staleTime=30min — entity descriptions are stable for hours after 13J enrichment.
 *
 * EDGE EVIDENCE COUNT (Task 2):
 * `evidence_count` is NOT present in the S9 `/v1/entities/{id}/graph` response.
 * S9 returns `evidence_snippets: string[]` (a subset of raw text) and
 * `relation_summary: string | null` on each edge, but no aggregate count field.
 * Future enhancement: add `evidence_count: number` to S7 RelationResponse and
 * surface it via S9's `_transform_graph_response()`. Until then, we display
 * snippet count from the already-loaded `evidence_snippets` array length.
 */

"use client";
// WHY "use client": useQuery + onClick callbacks both require browser context.

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAccessToken } from "@/lib/api-client";
import { apiFetch } from "@/lib/api/_client";
import { qk } from "@/lib/query/keys";
import type { EntityPublic } from "@/types/api";
import type { SelectedEdgeInfo } from "@/components/instrument/EntityGraph";

// ── Node selection type (sourced from GraphEvents.clickNode callback) ─────────

export interface SelectedNodeInfo {
  id: string;
  label: string;
  type: string;
  degree: number;
  edges: Array<{ label: string; weight: number; neighborId: string; neighborLabel: string }>;
  description: string | null;
  sector: string | null;
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

/**
 * toYearQuarter — converts an ISO-8601 date string to "YYYY-Qn" display format.
 *
 * WHY "YYYY-Qn" (not full ISO): finance terminals use fiscal quarter notation
 * for relation validity — "2024-Q3" communicates "this relation was active in
 * the July–September 2024 period" more intuitively than a raw date string.
 * Bloomberg and FactSet both use this notation for relation validity ranges.
 *
 * WHY guard on NaN: Date.parse() returns NaN for invalid strings. If the KG
 * stores a malformed date we should fall back gracefully, not crash the panel.
 *
 * @param dateStr - ISO-8601 date string (e.g., "2024-08-15T00:00:00Z")
 * @returns "YYYY-Qn" string (e.g., "2024-Q3") or the original string on parse failure
 */
function toYearQuarter(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr; // graceful fallback for malformed dates
  const year = d.getUTCFullYear();
  // WHY Math.ceil(month/3): months 1–3 → Q1, 4–6 → Q2, 7–9 → Q3, 10–12 → Q4.
  // getUTCMonth() is 0-indexed so we add 1 first.
  const quarter = Math.ceil((d.getUTCMonth() + 1) / 3);
  return `${year}-Q${quarter}`;
}

/**
 * isDateInPast — returns true when a date string represents a moment before now.
 *
 * WHY UTC comparison: the KG stores validity dates in UTC. Comparing against
 * Date.now() (also UTC epoch) avoids false positives from local timezone offsets.
 *
 * @param dateStr - ISO-8601 date string to compare against today
 */
function isDateInPast(dateStr: string): boolean {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return false; // unknown date → do not mark stale
  return d.getTime() < Date.now();
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
  // WHY useAccessToken at component level (not inside the conditional):
  // React hooks must be called unconditionally (Rules of Hooks). We always call
  // this hook; the `enabled` guard below prevents any network request when not needed.
  const token = useAccessToken();

  // ── Lazy entity detail fetch (Task 1) ────────────────────────────────────
  // WHY: The graph response populates `description` from S7 EntitySummary, but
  // many graph nodes are not yet enriched — their description field arrives as
  // null. When that happens we fire a targeted GET /v1/entities/{id} call to
  // fetch the full EntityPublic record and surface the description from there.
  //
  // WHY enabled guard: `description === null` (not undefined) means the graph
  // response explicitly returned null — we need to fall back. `undefined` would
  // mean the field was missing entirely from the graph response (shouldn't
  // happen after B-01, but guard it anyway). We never fire when description is
  // already a non-null string — no point fetching what we already have.
  //
  // WHY staleTime=30min: entity descriptions are written once by 13J enrichment
  // and rarely updated. Caching for 30 minutes avoids re-fetching on every node
  // click and matches the staleTime used in EntityOverviewBlock for the same endpoint.
  //
  // WHY we silently hide on error (not show a banner):
  // The node click itself is working — the panel shows label, type, edges.
  // A failed description fetch is a minor data gap, not an action-blocking error.
  // Showing an error banner for a description would confuse analysts who need the
  // relation data (which loaded fine) more than the description.
  const detailQuery = useQuery<EntityPublic | null>({
    queryKey: qk.kg.entityDetail(selectedNode?.id ?? ""),
    queryFn: () =>
      apiFetch<EntityPublic>(
        `/v1/entities/${encodeURIComponent(selectedNode!.id)}`,
        { token: token ?? undefined },
      ),
    // WHY this enabled condition:
    //   1. selectedNode must exist (obvious — we're in node mode)
    //   2. description must be null — if it's a non-null string we already have it
    //   3. token must be available — no point firing without auth
    enabled: selectedNode?.description === null && !!selectedNode?.id && !!token,
    staleTime: 30 * 60 * 1000,
    // WHY retry:1 — mirrors EntityOverviewBlock pattern (F-156). Default retry=3
    // with backoff stalls the UI for ~30s; one retry is enough for transient blips.
    retry: 1,
  });

  // Resolve the description to display: prefer graph attrs (non-null string),
  // then fall back to the lazy-fetched entity detail, then nothing.
  const resolvedDescription: string | null =
    selectedNode?.description ??
    detailQuery.data?.description ??
    null;

  // WHY isLoading (not isPending): isLoading=true only when the query is
  // fetching for the first time AND enabled=true. isPending is true even when
  // disabled — using it would show the skeleton on every node click.
  const isDescriptionLoading = detailQuery.isLoading;

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
            {selectedNode.sector && (
              <span className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground/60 ml-auto shrink-0 truncate max-w-[120px]">
                {selectedNode.sector}
              </span>
            )}
          </div>
          {/* ── Description row (with lazy-fetch fallback) ───────────────
              WHY show skeleton on loading (not empty gap):
              An empty gap between "3 connections" and the first edge row would
              look like a layout bug. A single skeleton row communicates "data
              inbound" clearly without jank. We only show the skeleton when the
              lazy fetch is in flight AND the graph attrs description is null —
              if the graph already had a description we skip the fetch entirely.

              WHY NOT show error state: description fetch failure is silent.
              The panel still shows label, type, sector, and all edge rows —
              the core information the analyst needs. A description is additive
              context, not load-bearing data. */}
          {isDescriptionLoading && (
            <div className="px-3 py-1 border-b border-border/20" aria-label="Loading description">
              <Skeleton className="h-2.5 w-full rounded-[2px]" />
            </div>
          )}
          {!isDescriptionLoading && resolvedDescription && (
            <div className="px-3 py-1 border-b border-border/20">
              <p className="text-[10px] text-muted-foreground/80 leading-snug line-clamp-2">
                {resolvedDescription}
              </p>
            </div>
          )}
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

          {/* ── Edge validity period (D-2) ─────────────────────────────────
              WHY here (between breadcrumb and summary): validity metadata gives
              the analyst temporal context before they read the evidence.
              Showing "STALE" immediately after the relation breadcrumb signals
              that the claim may no longer be current — relevant before investing
              time reading the LLM summary and evidence snippets below.
              WHY conditional rendering (not always shown): most KG relations lack
              explicit validity dates (open-ended). We only show this section when
              at least one validity field is present. */}
          {(selectedEdge.valid_from ?? selectedEdge.valid_to) && (
            <div className="h-[22px] flex items-center px-3 gap-2 border-b border-border/20">
              {/* Valid-from in YYYY-Qn format */}
              {selectedEdge.valid_from && (
                <span className="text-[9px] font-mono text-muted-foreground">
                  FROM {toYearQuarter(selectedEdge.valid_from)}
                </span>
              )}
              {/* Valid-to in YYYY-Qn format */}
              {selectedEdge.valid_to && (
                <span className="text-[9px] font-mono text-muted-foreground">
                  TO {toYearQuarter(selectedEdge.valid_to)}
                </span>
              )}
              {/* STALE badge — only when valid_to is in the past.
                  WHY warning amber (#FFB000): signals caution without the severity
                  of #EF5350 (error red). A stale relation may still be partially
                  relevant; it is not an error, just aged data. */}
              {selectedEdge.valid_to && isDateInPast(selectedEdge.valid_to) && (
                <span className="text-[9px] font-mono bg-[#FFB000]/10 text-[#FFB000]/80 px-1 rounded">
                  STALE
                </span>
              )}
            </div>
          )}

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
