/**
 * components/intelligence/PathChain.tsx — node→relation→node path renderer
 * (PLAN-0112 T-5-03)
 *
 * WHY THIS EXISTS:
 * Both the global WeirdConnectionsFeed and the pairwise PathBetweenPanel render a
 * path as a chain of entity pills joined by relation labels ("Apple →PARTNER_OF→
 * OpenAI →INVESTED_IN→ Anthropic"). PathsTab already had its own inline version;
 * this extracts the SAME pattern so the two new surfaces don't duplicate it.
 *
 * WHY inline flex (not SVG):
 * A path is a simple linear sequence. CSS flex with wrap handles overflow (long
 * paths wrap to the next line) far better than a fixed-dimension SVG, and matches
 * the existing PathsTab visualisation so the look is consistent.
 *
 * DESIGN: Midnight Pro. Pills use bg-muted/text-foreground (guaranteed to paint —
 * avoids the hsl(var()) no-paint class). Optional highlight uses bg-primary tints.
 */

"use client";

import { cn } from "@/lib/utils";
import type { PathNodePublic, PathEdgePublic } from "@/types/intelligence";

export interface PathChainProps {
  nodes: PathNodePublic[];
  edges: PathEdgePublic[];
  /**
   * Optional entity id to highlight (amber pill). Used by surfaces that want to
   * mark "the entity you came from". Pass undefined for no highlight.
   */
  highlightEntityId?: string;
  className?: string;
}

export function PathChain({
  nodes,
  edges,
  highlightEntityId,
  className,
}: PathChainProps) {
  return (
    <div
      className={cn("flex flex-wrap items-center gap-1", className)}
      aria-label="Path"
    >
      {nodes.map((node, i) => (
        // WHY index in key in addition to entity_id: a single path can legitimately
        // revisit an entity_id at two positions; entity_id alone would collide.
        <div key={`${node.entity_id}-${i}`} className="flex items-center gap-1">
          {/* Entity pill */}
          <span
            className={cn(
              "inline-block rounded-[2px] border px-2 py-0.5 text-[10px] font-mono font-medium",
              node.entity_id === highlightEntityId
                ? "border-primary/40 bg-primary/20 text-primary"
                : "border-border/60 bg-muted/60 text-foreground/80",
            )}
            title={`${node.name} (${node.entity_type})`}
          >
            {node.name}
          </span>

          {/* Relation label + arrow — rendered after every node except the last. */}
          {i < edges.length && (
            <div className="flex items-center gap-0.5">
              <div className="h-px w-3 bg-border/60" />
              <span
                className="text-[9px] uppercase tracking-wider text-muted-foreground"
                title={edges[i].relation_type}
              >
                {/* Humanise "PARTNER_OF" → "partner of"; cap length so long
                    relation names don't blow out the row width. */}
                {edges[i].relation_type.replace(/_/g, " ").toLowerCase().slice(0, 14)}
              </span>
              <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                <path
                  d="M0 4h6M4 1l3 3-3 3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  fill="none"
                  className="text-border/60"
                />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
