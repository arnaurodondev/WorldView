/**
 * features/chat/components/CitationStrip.tsx — Dense citation evidence strip.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block C, T-10):
 *   Bloomberg/Refinitiv chat surfaces show the evidence behind an answer as a
 *   single bordered region of one-line rows — NOT as fat pill chips spread
 *   across the message column. The legacy `CitationBar`/`CitationList` pair
 *   wasted ~3x the vertical real estate per citation and silently rendered
 *   `NaN%` when `relevance_score` was undefined (Q-10 drift bug). This
 *   component replaces both with the canonical `CitationV2` wire shape:
 *
 *     [N] [TYPE] title · src · pct · [low-conf chip if relevance_score < 0.6]
 *
 *   Each row is 18px tall (design §6.4). Hover reveals a `CitationHoverCard`
 *   (T-12) with the longer excerpt. Click scrolls the matching inline `[c{N}]`
 *   anchor in the message body into view + flashes it (the same anchor the
 *   InlineCitationAnchor primitive renders inside the markdown content).
 *
 * DATA SOURCE: `CitationV2[]` produced by `useChatStream` from S8's
 *   `SSEEmitter.emit_citations` payload. No fetch in this component.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5.3 + §6.4 (row heights).
 *
 * Q-12 LOCK: the low-confidence chip surfaces extraction confidence below
 *   the 0.6 threshold so analysts know which evidence to verify by hand.
 *
 * SHIPPED CITATIONV2 SHAPE NOTE: the spec in K-chat-polish-plan.md §6 T-10
 *   referenced `published_at`, `source_name`, `entity_name`, `confidence`,
 *   and `ref`. The actually-shipped `CitationV2` (types/api.ts L1376, Block
 *   A commit b7e986da) uses `id`, `kind`, `title`, `source`, `url`,
 *   `relevance_score`. We honour the shipped wire shape verbatim and adapt
 *   the row template accordingly: `[N]` = 1-based index, `[TYPE]` = `kind`,
 *   `src` = `source`, `pct` = `relevance_score * 100`, and the low-conf chip
 *   keys off `relevance_score` (the field S8 sets to extraction confidence
 *   per Q-12). `published_at` is not yet on the wire — omitted gracefully.
 */

"use client";

// "use client" because this component owns interactive hover + click-to-scroll
// behaviour (DOM lookup via querySelector, scrollIntoView, requestAnimationFrame
// for the flash). Pure presentational SSR is not possible here.

import { useCallback } from "react";

import {
  CitationHoverCard,
  type CitationHoverData,
} from "@/features/chat/components/CitationHoverCard";
import { HoverCard, HoverCardTrigger } from "@/components/ui/hover-card";
import type { CitationV2 } from "@/types/api";

interface CitationStripProps {
  readonly citations: CitationV2[];
  /**
   * Prefix used to build the matching inline anchor selector. The chat
   * message body marks each `[cN]` anchor with `data-citation-ref={N}`; if
   * an embedding surface uses a different namespace (e.g. AskAiPanel) it can
   * scope the lookup via an attribute prefix. Defaults to no prefix — the
   * lookup uses `[data-citation-ref="{n}"]` directly.
   */
  readonly anchorPrefix?: string;
}

// Low-confidence threshold from Q-12. Anything strictly below this gets a
// chip nudging the analyst to verify the source before quoting it.
const LOW_CONFIDENCE_THRESHOLD = 0.6;

/**
 * formatPercent — safely renders `relevance_score` as `NN%`. Guards against
 * undefined / null (the Q-10 drift bug we are fixing) by returning `null`
 * so the caller can skip rendering instead of emitting `NaN%`.
 */
function formatPercent(score: number | undefined): string | null {
  if (score === undefined || score === null || Number.isNaN(score)) return null;
  // Clamp to [0,1] before multiplying — defensive against backend overflow.
  const clamped = Math.max(0, Math.min(1, score));
  return `${(clamped * 100).toFixed(0)}%`;
}

/**
 * scrollToAnchor — finds the matching inline `[cN]` anchor in the message
 * body and scrolls it into view, then flashes it via a transient CSS class
 * for 600ms. Uses requestAnimationFrame to ensure the scroll has committed
 * before the flash class fires (otherwise the browser may batch them).
 *
 * The flash class `citation-anchor-flash` is defined in globals.css; if it
 * is not present the scroll still works — only the visual ping is lost.
 */
function scrollToAnchor(ref: number, anchorPrefix?: string): void {
  if (typeof document === "undefined") return;
  const selector = anchorPrefix
    ? `[data-citation-prefix="${anchorPrefix}"][data-citation-ref="${ref}"]`
    : `[data-citation-ref="${ref}"]`;
  const target = document.querySelector<HTMLElement>(selector);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  requestAnimationFrame(() => {
    target.classList.add("citation-anchor-flash");
    window.setTimeout(() => target.classList.remove("citation-anchor-flash"), 600);
  });
}

/**
 * CitationStrip — see file header. Returns `null` for empty arrays so
 * callers do not need to wrap with a conditional (matches the rest of
 * Wave K's "render nothing when nothing to show" convention).
 *
 * HOVERCARD CONTENT (T-12): the per-row hovercard layout lives in
 * `CitationHoverCard.tsx`. CitationStrip owns the `<HoverCard>` root so
 * the `openDelay`/`closeDelay` is consistent across all rows; the
 * extracted component renders the `<HoverCardContent>` child.
 */
export function CitationStrip({ citations, anchorPrefix }: CitationStripProps) {
  // useCallback so the row-level closure does not get re-created every
  // render (the strip can hold a dozen rows + hovercards).
  const onRowClick = useCallback(
    (ref: number) => {
      scrollToAnchor(ref, anchorPrefix);
    },
    [anchorPrefix],
  );

  if (citations.length === 0) return null;

  // Mean relevance for the top confidence bar. Undefined scores count as
  // zero (worst-case) so the indicator is never falsely optimistic.
  const meanScore =
    citations.reduce((sum, c) => sum + (c.relevance_score ?? 0), 0) / citations.length;

  return (
    <div className="mt-1 border border-border bg-card" role="list" aria-label="Citations">
      {/*
        Confidence bar: a 2px sliver coloured by the mean relevance across
        the strip — quick scannable signal whether the answer is well-sourced
        overall.
      */}
      <div
        className="h-[2px] bg-positive"
        style={{ width: `${(Math.max(0, Math.min(1, meanScore)) * 100).toFixed(0)}%` }}
        aria-hidden
      />
      {citations.map((cite, idx) => {
        const ref = idx + 1; // 1-based for display
        const pct = formatPercent(cite.relevance_score);
        const isLowConf =
          cite.relevance_score !== undefined &&
          cite.relevance_score !== null &&
          cite.relevance_score < LOW_CONFIDENCE_THRESHOLD;
        // Adapter into the hovercard's structural shape — keeps the
        // hovercard decoupled from `CitationV2` so we can grow the wire
        // shape (Q-9: published_at, excerpt) without re-typing the
        // hovercard's props.
        const hoverData: CitationHoverData = {
          title: cite.title,
          source: cite.source,
          url: cite.url,
          kind: cite.kind,
        };
        return (
          <HoverCard key={`${cite.id}-${ref}`} openDelay={250} closeDelay={100}>
            <HoverCardTrigger asChild>
              <button
                type="button"
                data-cell
                data-citation-row={ref}
                onClick={() => onRowClick(ref)}
                className="flex h-[18px] w-full items-center gap-2 border-t border-border px-2 text-left text-[10px] font-mono text-foreground tabular-nums first:border-t-0 hover:bg-muted/40 transition-color-only duration-75"
              >
                <span className="text-muted-foreground tabular-nums">[{ref}]</span>
                <span className="text-muted-foreground uppercase">[{cite.kind}]</span>
                <span className="truncate flex-1 text-foreground">
                  {cite.title || "Untitled"}
                </span>
                <span className="max-w-[120px] truncate text-muted-foreground">{cite.source}</span>
                {pct !== null ? (
                  <span className="text-muted-foreground tabular-nums">{pct}</span>
                ) : null}
                {isLowConf ? (
                  <span
                    className="text-warning tabular-nums"
                    title="Extraction confidence < 0.6 — verify before quoting"
                  >
                    low-conf
                  </span>
                ) : null}
              </button>
            </HoverCardTrigger>
            <CitationHoverCard citation={hoverData} />
          </HoverCard>
        );
      })}
    </div>
  );
}
