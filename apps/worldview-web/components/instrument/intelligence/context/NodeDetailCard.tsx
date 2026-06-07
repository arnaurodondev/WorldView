/**
 * components/instrument/intelligence/context/NodeDetailCard.tsx — PLAN-0090 T-D-03
 *
 * WHY THIS EXISTS:
 * When the user clicks a node in the Intelligence tab's knowledge graph, the
 * ContextPanel switches from the entity overview to THIS card so the user can
 * see the selected node's metadata (name, type, description, confidence) WITHOUT
 * losing the graph context. A "Back" arrow returns to the entity overview.
 *
 * WHY a pure presentational component (no data fetching):
 * The graph already carries the GraphNode payload (label, type, size) from the
 * /v1/entities/{id}/graph response. Re-fetching per-node would add a network
 * round-trip on every click. The parent (ContextPanel) just passes the node
 * directly. If we later need richer per-node metadata (e.g., description), we
 * fan that in here via additional optional props — not by adding a hook.
 *
 * WHY a "Back" button (not just clicking-elsewhere):
 * Discoverability + accessibility — users with keyboard nav need an explicit
 * focusable control to escape the detail view. The graph's deselect-on-click
 * remains an alternative path (handled by the graph component itself).
 *
 * STYLING: matches EntityDescriptionPanel.tsx (same tab, sibling component) —
 * 11/12 px text, mono lowercase type badge, compact 3 px vertical rhythm.
 */

"use client";
// WHY "use client": this component uses an onClick handler (onBack) AND
// a TanStack Query hook (useQuery for entity description). Server Components
// cannot use either — this must be a client island.

import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import type { GraphNode } from "@/types/api";

/**
 * Props for NodeDetailCard.
 *
 * WHY only two props: presentational components stay reusable when the surface
 * area is small. Anything else (confidence, description) is derived from `node`
 * or fanned in via optional fields on the node payload itself.
 */
export interface NodeDetailCardProps {
  /** The graph node selected by the user. Coming from GraphEdge.source/target
   *  lookup → GraphNode in the parent component. */
  node: GraphNode;
  /** Click handler for the "Back" arrow. The parent clears selectedNodeId,
   *  which causes ContextPanel to re-render the entity overview. */
  onBack: () => void;
  /** Optional extra class names (used by ContextPanel to control spacing). */
  className?: string;
}

// ── Component ────────────────────────────────────────────────────────────────

export function NodeDetailCard({ node, onBack, className }: NodeDetailCardProps) {
  const { accessToken } = useAuth();

  // WHY fetch entity detail here (PLAN-0099 W4 Step 7):
  // The GraphNode payload carries only label/type/size/ticker — no description.
  // Rather than showing "No description available." forever, we fetch the enriched
  // entity record from GET /v1/entities/{id}. staleTime=30min because descriptions
  // are refreshed nightly by Worker 13J; no need to re-fetch on every node click.
  // retry=1: 404 means enrichment hasn't run yet (returns null) — one retry covers
  // transient S9 blips without hammering the backend on a cold entity.
  const { data: detail } = useQuery({
    queryKey: qk.kg.entityDetail(node.id),
    queryFn: () => createGateway(accessToken).getEntityDetail(node.id),
    enabled: !!accessToken && !!node.id,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });

  // WHY normalise the type label here (not in the parent):
  // KG entity_type strings use snake_case ("financial_instrument"). Displaying
  // the raw value is jarring. We only do this for VIEW; the underlying value
  // remains canonical for any logic that branches on it.
  const typeLabel = node.type.replace(/_/g, " ");

  // WHY a size-based confidence proxy when no explicit confidence exists:
  // GraphNode.size is the "relative importance score" computed by S9 from edge
  // count + relation strength. We DO NOT pretend it's a confidence score here;
  // we surface it as "node weight" so the user can compare nodes within the
  // same graph. If T-D-01 later adds an explicit `confidence` field, this block
  // becomes a `node.confidence ?? node.size` fallback (no API change needed).
  const weight = node.size;

  return (
    <section
      className={cn("p-3 space-y-3", className)}
      aria-label={`Selected node: ${node.label}`}
    >
      {/* ── Back button row ─────────────────────────────────────────────────
          WHY a separate row (not inline with the title): the "Back" affordance
          MUST be visually distinct from the entity name so screen readers and
          eyes both treat it as a navigation control, not part of the title. */}
      <div className="flex items-center">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onBack}
          // WHY h-6 + px-1.5 + text-[10px]: matches Finviz-density rail buttons
          // used elsewhere in the instrument page (compact, never-shouting).
          className="h-6 px-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground"
          aria-label="Back to entity overview"
        >
          {/* WHY a Unicode arrow (not an SVG icon):
              The instrument page already standardises on Unicode arrows for
              compact toolbars (lower bundle weight, no lucide-react import for
              a one-pixel arrow). The aria-label above handles a11y. */}
          <span aria-hidden="true" className="mr-1">←</span>
          Back
        </Button>
      </div>

      {/* ── Header: name + type badge ──────────────────────────────────────
          WHY truncate on the name: long company names ("Berkshire Hathaway
          Inc. Class A") overflow the 280 px sidebar. We truncate; the full
          name remains in the title attribute for hover-tooltip discovery. */}
      <div className="flex items-center gap-2">
        <h3
          className="text-[12px] font-medium text-foreground leading-tight truncate"
          title={node.label}
        >
          {node.label}
        </h3>
        <span
          className="shrink-0 text-[9px] font-mono uppercase tracking-wider bg-muted text-muted-foreground px-1.5 py-0.5 rounded-[2px]"
        >
          {typeLabel}
        </span>
      </div>

      {/* ── Description ───────────────────────────────────────────────────
          WHY fetched (not hardcoded placeholder): PLAN-0099 W4 Step 7 wires
          getEntityDetail() here. The KG entity detail endpoint returns a
          Worker-13J-enriched description. When null (enrichment hasn't run yet
          or entity too new), we render a muted italic placeholder so the slot
          height is stable (no layout shift on data arrival). */}
      <p className="text-[11px] leading-relaxed text-foreground/80">
        {detail?.description != null ? (
          detail.description
        ) : (
          <span className="italic text-muted-foreground">
            Description unavailable.
          </span>
        )}
      </p>

      {/* ── Node weight (importance proxy) ─────────────────────────────────
          WHY display this at all: gives the user a sense of why this node was
          drawn at its size. Without it, the visualisation makes a claim the UI
          never explains — bad practice for finance-grade dashboards. */}
      {typeof weight === "number" && (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
              Node weight
            </span>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
              {/* WHY toFixed(2): weight is a float in [0, ~10]. Two decimals
                  give the user enough precision without visual noise. */}
              {weight.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {/* ── Ticker line (only for financial_instrument nodes) ──────────────
          WHY conditional: tickers are empty strings for non-instrument nodes
          (sectors, people, events). Showing "Ticker: —" for those would be
          noise — better to hide the row entirely. */}
      {node.ticker && (
        <div className="flex items-baseline gap-2">
          <span className="shrink-0 w-[88px] text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
            Ticker
          </span>
          <span className="font-mono text-[11px] text-foreground/80 truncate">
            {node.ticker}
          </span>
        </div>
      )}
    </section>
  );
}
