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

/**
 * formatCiteDate — turn an ISO-8601 `published_at` into a compact, locale-
 * neutral "Mon D, YYYY" label (e.g. "Jun 30, 2026") for the citation chip.
 *
 * WHY a guarded helper (not inline `new Date(...).toLocaleDateString()`):
 *   1. `published_at` is optional + nullable — KG/relation citations have no
 *      date. We must return null (and render nothing) rather than print
 *      "Invalid Date".
 *   2. The backend already normalizes empty strings to null, but a defensive
 *      `Number.isNaN(getTime())` check means a malformed string from any future
 *      source can never leak a broken label into the UI.
 *   3. `timeZone: "UTC"` keeps the day stable regardless of the viewer's
 *      timezone — a market article's publish DATE should not shift by a day
 *      for a user in Tokyo vs New York.
 */
function formatCiteDate(published_at: string | null | undefined): string | null {
  if (!published_at) return null;
  const d = new Date(published_at);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
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

        // Pre-format the publish date once. null = no date to show (KG items,
        // or a source without a published_at) → the date span is omitted.
        const citeDate = formatCiteDate(cite.published_at);

        // Tooltip leads with the SOURCE TITLE (what the analyst hovers to
        // learn: "which article is this?"), then source + relevance as
        // secondary context. Falls back to the source name for title-less
        // KG citations so the tooltip is never empty. The publish date is
        // appended when present so a hover reveals recency without cluttering
        // the always-visible chip.
        const tooltipHead = cite.title
          ? `${cite.title} — ${cite.source} (${(cite.relevance_score * 100).toFixed(0)}% relevance)`
          : `${cite.source} (${(cite.relevance_score * 100).toFixed(0)}% relevance)`;
        const tooltip = citeDate ? `${tooltipHead} · ${citeDate}` : tooltipHead;

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
            {/* Publish date — only rendered when the source actually has one.
                Kept to the muted 9px chrome weight so it reads as metadata
                next to the source, never competing with the title. */}
            {citeDate ? (
              <span className="font-mono text-[9px] text-muted-foreground">{citeDate}</span>
            ) : null}
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
            // Round 3 focus polish: linked badges are tab stops — give them a
            // visible :focus-visible ring (Tier-2 input ring weight) so
            // keyboard users can tell WHICH citation Enter will open. Outline
            // suppressed only for the focus-visible case we restyle.
            className={`${badgeClass} hover:border-primary/50 hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary`}
            title={tooltip}
          >
            {inner}
          </a>
        );
      })}
    </div>
  );
}
