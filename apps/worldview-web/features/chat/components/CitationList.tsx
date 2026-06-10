// Server Component — no hooks, no browser APIs, no event handlers, no interactive shadcn imports.
// Pure data display: renders a list of <a> anchor tags with formatted citation props.
// Do not re-add "use client" without checking all of the above.

/**
 * features/chat/components/CitationList.tsx — Clickable citation pills below
 * assistant messages.
 *
 * WHY EXTRACTED (PLAN-0059 E-3 partial): the citation pills + the icon-mapping
 * helper used to live inline in `app/(app)/chat/page.tsx`. They are pure
 * render with no SSE / abort coupling, so extraction is mechanical and risk-
 * free relative to the rest of the chat page.
 *
 * Wave E: the inline pill list is now complemented by the CitationBar (see
 * MessageBubble). Pills remain because traders frequently click through to
 * source URLs.
 */

import { safeExternalUrl } from "@/lib/utils";
import type { Citation } from "@/types/api";

/**
 * CITATION_ICONS — maps citation source type to a display icon string.
 * Kept inline (no SVG icons) because traders scan for `[SEC]`, `[NEWS]`,
 * `[EARN]` text faster than they parse glyphs.
 */
const CITATION_ICONS: Record<string, string> = {
  sec: "[SEC]",
  news: "[NEWS]",
  earnings: "[EARN]",
  knowledge_graph: "[KG]",
};

/**
 * getCitationIcon — pick the [SEC]/[EARN]/[KG]/[NEWS] tag based on the
 * citation's source string + title heuristics. Defaults to [NEWS] so the
 * pill always has SOMETHING to render — never an empty bracket.
 */
export function getCitationIcon(cite: Citation): string {
  const src = cite.source.toLowerCase();
  if (src.includes("sec") || src.includes("edgar") || src.includes("filing")) {
    return CITATION_ICONS.sec;
  }
  if (src.includes("earning") || src.includes("transcript")) {
    return CITATION_ICONS.earnings;
  }
  if (src.includes("knowledge") || src.includes("graph")) {
    return CITATION_ICONS.knowledge_graph;
  }
  const title = (cite.title ?? "").toLowerCase();
  if (title.includes("10-k") || title.includes("10-q") || title.includes("8-k")) {
    return CITATION_ICONS.sec;
  }
  return CITATION_ICONS.news;
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((cite, i) => {
        // Round 1 Foundation: knowledge-graph citations carry NO url (they
        // reference in-platform graph data, not an external article). The old
        // code always rendered an <a href="#"> for them — clicking scrolled
        // the page to the top, a confusing dead link. This ALSO closes the
        // contract gap documented in useChatStream's citations handler, which
        // promised "CitationList renders KG citations as plain text when url
        // is null/undefined" but the component never implemented it.
        const hasUrl = !!cite.url && safeExternalUrl(cite.url) !== "#";

        // Tooltip leads with the SOURCE TITLE (what the analyst hovers to
        // learn: "which article is this?"), then source + relevance as
        // secondary context. Falls back to the source name for title-less
        // KG citations so the tooltip is never empty.
        const tooltip = cite.title
          ? `${cite.title} — ${cite.source} (${(cite.relevance_score * 100).toFixed(0)}% relevance)`
          : `${cite.source} (${(cite.relevance_score * 100).toFixed(0)}% relevance)`;

        // Shared badge chrome for both the <a> and the non-link <span> variant.
        // WHY muted bg (was primary/10): citations are REFERENCE metadata, not
        // calls-to-action — the primary (amber) tint made every assistant
        // answer look like a row of action buttons. bg-muted + border-border
        // recedes; the hover ring signals clickability on the linked variant.
        // WHY rounded-[2px] (not rounded-full): terminal 2px-radius rule
        // (DESIGN_SYSTEM.md) — fully-rounded pills are a consumer convention.
        const badgeClass =
          "inline-flex items-center gap-1 rounded-[2px] border border-border bg-muted px-2 py-0.5 text-[10px] text-foreground";

        const inner = (
          <>
            <sup className="font-mono text-[9px]">[{i + 1}]</sup>
            <span className="font-mono text-[9px] text-muted-foreground" aria-hidden="true">
              {getCitationIcon(cite)}
            </span>
            <span className="font-mono text-[9px] text-muted-foreground">{cite.source}</span>
            {/* WHY text-[10px]: title snippet inside chip inherits the chip's 10px
                chrome-label density — no explicit size would let it fall back to
                the parent bubble's 11px, creating an internal size mismatch. */}
            <span className="max-w-[140px] truncate text-[10px]">{cite.title}</span>
            <span className="font-mono text-[9px] text-muted-foreground">
              {(cite.relevance_score * 100).toFixed(0)}%
            </span>
          </>
        );

        if (!hasUrl) {
          // Plain badge — same look, no pointer affordance, no dead "#" link.
          return (
            <span
              key={`${cite.article_id}-${i}`}
              className={`${badgeClass} cursor-default`}
              title={tooltip}
            >
              {inner}
            </span>
          );
        }

        return (
          <a
            key={`${cite.article_id}-${i}`}
            href={safeExternalUrl(cite.url)}
            target="_blank"
            rel="noopener noreferrer"
            className={`${badgeClass} hover:border-primary/50 hover:text-primary`}
            title={tooltip}
          >
            {inner}
          </a>
        );
      })}
    </div>
  );
}
