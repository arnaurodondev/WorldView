"use client";

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
      {citations.map((cite, i) => (
        <a
          key={`${cite.article_id}-${i}`}
          href={safeExternalUrl(cite.url)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-[2px] border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20"
          title={`${cite.source} — relevance: ${(cite.relevance_score * 100).toFixed(0)}%`}
        >
          <sup className="font-mono text-[9px]">[{i + 1}]</sup>
          <span className="font-mono text-[9px]" aria-hidden="true">
            {getCitationIcon(cite)}
          </span>
          <span className="font-mono text-[9px] text-primary/70">{cite.source}</span>
          <span className="max-w-[140px] truncate">{cite.title}</span>
          <span className="font-mono text-[9px] text-primary/60">
            {(cite.relevance_score * 100).toFixed(0)}%
          </span>
        </a>
      ))}
    </div>
  );
}
