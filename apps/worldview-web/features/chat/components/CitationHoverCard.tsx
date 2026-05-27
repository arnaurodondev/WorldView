/**
 * features/chat/components/CitationHoverCard.tsx — Hover excerpt for citations.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block C, T-12):
 *   Inline `[N]` citation rows in `CitationStrip` are visually dense by
 *   design (18px tall) so they can only show title + source + score.
 *   Analysts still need a quick way to preview the underlying evidence
 *   WITHOUT navigating away from the chat — Bloomberg / Refinitiv solved
 *   this with a 250ms-delay hovercard. This file is the chat-citation
 *   hovercard: it shows the source badge, kind, title, an optional excerpt
 *   (240-char truncated, word-boundary aware), an optional publication
 *   timestamp, and an "Open ↗" link to the source URL in a new tab.
 *
 *   T-10 inlined a minimal version of this layout inside CitationStrip to
 *   ship the strip without a forward dependency. T-12 extracts the full
 *   layout here and CitationStrip now imports it directly — one rendering
 *   contract, one place to evolve as Q-9 adds excerpt + published_at to
 *   the wire shape.
 *
 * DATA SOURCE: `CitationHoverData` adapter passed by `CitationStrip`. The
 *   shipped `CitationV2` wire shape (types/api.ts) does not yet carry
 *   `excerpt` or `published_at`; this component renders gracefully without
 *   them — title-only fallback is acceptable per K-plan §4 check #12.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5.3 + design system
 *   Tier-2 chrome (opacity-only transition, ≤250ms open delay).
 */

import type { ReactNode } from "react";

import { HoverCardContent } from "@/components/ui/hover-card";
import { safeExternalUrl } from "@/lib/utils";

/**
 * CitationHoverData — adapter shape so the hovercard does not have to
 * consume the full `CitationV2` interface. Structural type makes the
 * component testable in isolation (no need to mock unrelated wire fields).
 * `excerpt` + `publishedAt` are optional pending the Q-9 wire extension.
 */
export interface CitationHoverData {
  readonly title: string;
  readonly source: string;
  readonly url: string | null;
  readonly kind: string;
  readonly excerpt?: string | null;
  readonly publishedAt?: string | null;
}

interface CitationHoverCardProps {
  readonly citation: CitationHoverData;
}

// 240-char truncation limit per the K-plan §6 T-12 spec. Module-level so
// the unit test can assert against the same number.
const EXCERPT_LIMIT = 240;

/**
 * truncateExcerpt — slices at 240 chars, walking back to the last space
 * so we never break mid-word (mono 11px text reads badly with mid-word
 * cuts). Falls back to hard cut if the slice has no space in the last
 * 30% (one very long token); that's still better than a 240-char
 * ellipsis-less wall.
 */
function truncateExcerpt(text: string): string {
  if (text.length <= EXCERPT_LIMIT) return text;
  const slice = text.slice(0, EXCERPT_LIMIT);
  const lastSpace = slice.lastIndexOf(" ");
  const cutAt = lastSpace > EXCERPT_LIMIT * 0.7 ? lastSpace : EXCERPT_LIMIT;
  return `${slice.slice(0, cutAt)}…`;
}

/**
 * formatPublishedAt — ISO-8601 UTC → `YYYY-MM-DD`. Mono fonts align
 * cleanly that way and traders scan timestamps left-to-right. Returns
 * null on invalid input so the caller can skip the row.
 */
function formatPublishedAt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString().slice(0, 10);
  } catch {
    return null;
  }
}

/**
 * CitationHoverCard — designed to be rendered as the `HoverCardContent`
 * child of a `HoverCard` whose `HoverCardTrigger` is a citation row in
 * `CitationStrip`. Returning `HoverCardContent` directly (rather than
 * wrapping in `<HoverCard>` ourselves) keeps composition flexible —
 * `CitationStrip` owns the `HoverCard` root and wires `openDelay`
 * consistently across all rows.
 */
export function CitationHoverCard({ citation }: CitationHoverCardProps): ReactNode {
  const publishedLabel = formatPublishedAt(citation.publishedAt);
  const excerpt = citation.excerpt ? truncateExcerpt(citation.excerpt) : null;
  // safeExternalUrl prevents `javascript:` / data-URL injection — same
  // helper used by the legacy CitationList for parity.
  const safeUrl = citation.url ? safeExternalUrl(citation.url) : null;

  return (
    <HoverCardContent
      align="start"
      sideOffset={4}
      className="w-80 p-2 text-[11px] font-mono text-popover-foreground"
    >
      {/* Top row: kind badge + source label. */}
      <div className="flex items-center gap-1">
        <span className="border border-border bg-muted px-1 text-[9px] uppercase text-muted-foreground tabular-nums">
          {citation.kind}
        </span>
        <span className="truncate text-muted-foreground">{citation.source}</span>
      </div>
      {/* Headline title — always rendered, fallback to "Untitled". */}
      <div className="mt-1 leading-snug text-foreground">{citation.title || "Untitled"}</div>
      {/* Excerpt block: only when the wire shape grows the field. */}
      {excerpt ? (
        <div className="mt-1 leading-snug text-muted-foreground">{excerpt}</div>
      ) : null}
      {/* Bottom row: published-at on the left, Open link on the right. */}
      <div className="mt-1.5 flex items-center justify-between gap-2">
        {publishedLabel ? (
          <span className="text-[10px] text-muted-foreground tabular-nums">{publishedLabel}</span>
        ) : (
          // Empty placeholder so the Open link stays right-aligned even
          // when there's no published_at to show. aria-hidden because it
          // carries no information.
          <span aria-hidden />
        )}
        {safeUrl ? (
          <a
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-primary hover:underline"
          >
            Open ↗
          </a>
        ) : null}
      </div>
    </HoverCardContent>
  );
}
