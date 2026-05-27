/**
 * features/chat/components/RelationEvidencePopover.tsx — KG-edge evidence drawer.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block D, T-14):
 *   When the chat answer cites a knowledge-graph relation (e.g. "Apple
 *   supplier_of TSMC"), the analyst's first question is always "what's the
 *   evidence?". The S6 knowledge-graph pipeline already extracts a
 *   `relation_summary` (one-line LLM gloss) and the top `evidence_snippets[]`
 *   (raw quotes from `relation_evidence_raw`, each ≤ ~250 chars) per edge.
 *   Until this commit the frontend rendered the KG citation row as a flat
 *   `[type] title …` cell with no way to see the raw evidence behind the
 *   claim. T-14 surfaces both `relation_summary` and up to 3 evidence
 *   snippets in a Radix Popover anchored to KG-type citation rows.
 *
 *   BLOCK G NOTE: actual wiring into `CitationStrip`'s `kind === 'relation'`
 *   rows is deferred to T-20 (Block G). For now this component is built
 *   stand-alone and can be exercised through callers that already have a
 *   `GraphEdge` in hand (e.g. the right-rail in T-16).
 *
 * DATA SOURCE: caller passes `relation: GraphEdge` (from cached
 *   `get_entity_graph` tool result) plus `evidenceSnippets` and `summary`.
 *   This component does NOT fetch — it is a pure presentational drawer
 *   over data the caller has already captured during a turn.
 *
 * DESIGN REFERENCE:
 *   - docs/designs/0089/10-chat-ai.md §3.3 (KG evidence surfacing) + §6.4
 *     (10px mono rows, 200-char snippet truncation).
 *   - docs/ui/DESIGN_SYSTEM.md §0.1 typography (text-[10px] font-mono) and
 *     §0.3 semantic palette (bg-card / border-border / text-foreground).
 *
 * EARLY-RETURN INVARIANT: if there are no snippets AND no summary the
 *   popover would have nothing meaningful to show, so the component returns
 *   `null` (matches the Block C "render nothing when nothing to show" rule).
 */

"use client";

// "use client" because Radix Popover registers DOM event listeners (escape
// key, click-outside, focus management) that are only available in the
// browser. SSR would render the trigger but never the floating content.

import { type ReactNode } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { GraphEdge } from "@/types/api";

// Maximum number of evidence snippets rendered. Mirrors the S6 KG pipeline
// invariant (`relation_evidence_raw` top-K=3 per edge). More than 3 visually
// overflows the popover even at 10px mono, so we hard-cap on the frontend.
const MAX_SNIPPETS = 3;

// Per-snippet character cap. The S6 extractor sometimes hands back full
// sentences (>200 chars) — we tighten to a Bloomberg-friendly preview and
// suffix `…` so the analyst knows the row is truncated. Full text is one
// follow-up click away (T-20 will wire the row click → research drawer).
const SNIPPET_CHAR_CAP = 200;

interface RelationEvidencePopoverProps {
  /** The KG edge being explained. Used for the popover header label. */
  readonly relation: GraphEdge;
  /**
   * Top-K evidence snippets. Empty array is valid — the popover still
   * renders if `summary` is present. Order is preserved (caller is expected
   * to pass them already sorted by S6's relevance score).
   */
  readonly evidenceSnippets: string[];
  /** Optional one-line LLM gloss of the relation (Worker 13C output). */
  readonly summary?: string | null;
  /**
   * Trigger element — the citation row in `CitationStrip`, or any other
   * surface that wants to anchor the popover. We accept `children` so
   * callers control the trigger styling (the row already has its own dense
   * 18px chrome — wrapping it in another button would double-stamp the
   * affordance).
   */
  readonly children: ReactNode;
}

/**
 * truncate — clamps a snippet to SNIPPET_CHAR_CAP and appends `…`.
 *
 * WHY pure helper: zero-cost to test, and the truncation rule is likely to
 * evolve (e.g. word-boundary truncation). Keeping it isolated means the
 * future change is a one-spot edit.
 */
function truncate(snippet: string): string {
  if (snippet.length <= SNIPPET_CHAR_CAP) return snippet;
  return `${snippet.slice(0, SNIPPET_CHAR_CAP - 1).trimEnd()}…`;
}

/**
 * RelationEvidencePopover — see file header.
 *
 * CALLER PATTERN:
 *   <RelationEvidencePopover relation={edge} evidenceSnippets={edge.evidence_snippets ?? []} summary={edge.relation_summary}>
 *     <button data-cell …>Apple supplier_of TSMC</button>
 *   </RelationEvidencePopover>
 */
export function RelationEvidencePopover({
  relation,
  evidenceSnippets,
  summary,
  children,
}: RelationEvidencePopoverProps) {
  // Defensive: cap to MAX_SNIPPETS BEFORE the empty check, otherwise a
  // caller that passes [] but expects the slice to fail-safe would still
  // get into the render path. We slice first, then check truthiness.
  const snippets = evidenceSnippets.slice(0, MAX_SNIPPETS);
  const hasSummary = typeof summary === "string" && summary.trim().length > 0;
  const hasSnippets = snippets.length > 0;

  // No data → no popover. We still need to return SOMETHING (parent expects
  // children to render either way), so we render the trigger plain instead
  // of wrapping it in a popover that would never have content.
  if (!hasSummary && !hasSnippets) return <>{children}</>;

  return (
    <Popover>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        // Narrower than the shadcn default (w-72) — evidence popover is a
        // dense terminal panel, not a marketing card. 320px matches the
        // right-rail width so the visual rhythm carries across.
        className="w-80 p-0"
        align="start"
        sideOffset={6}
      >
        {/*
          Header: relation label + endpoints. 9px uppercase mono mirrors the
          section heading rows used elsewhere in the chat rail.
        */}
        <div className="flex h-[18px] items-center gap-2 border-b border-border bg-muted/40 px-2 text-[9px] font-mono uppercase tracking-wide text-muted-foreground">
          <span>{relation.label}</span>
          <span className="tabular-nums">· {(relation.weight ?? 0).toFixed(2)}</span>
        </div>
        {hasSummary ? (
          <div
            data-cell
            className="border-b border-border px-2 py-1.5 text-[10px] font-mono text-foreground"
          >
            {summary}
          </div>
        ) : null}
        {hasSnippets ? (
          <ul role="list" className="divide-y divide-border">
            {snippets.map((snippet, idx) => (
              <li
                key={idx}
                data-cell
                className="px-2 py-1 text-[10px] font-mono leading-[1.35] text-muted-foreground"
              >
                {truncate(snippet)}
              </li>
            ))}
          </ul>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
