/**
 * components/chat/CitationBar.tsx — segmented confidence bar for citations
 *
 * WHY THIS EXISTS (PLAN-0051 T-E-5-04):
 * RAG answers cite the articles the LLM read to produce the response. The
 * old chat UI showed every citation as a flat percentage pill — readable
 * but not at-a-glance. A horizontal bar segmented per citation, coloured by
 * relevance score, gives the trader an instant gestalt: "5 strong sources"
 * vs "3 weak ones I should re-check". Hover shows the source title and exact
 * score; clicking scrolls to the matching anchor in the message body.
 *
 * COLOUR THRESHOLDS (per task spec):
 * score ≥ 0.7 → green (text-positive — high confidence)
 * 0.4–0.7 → amber (bg-warning — medium)
 * < 0.4 → red (text-negative — weak)
 *
 * WHY use design tokens (positive/warning/negative): hard-coded HEX would
 * break dark-theme parity. The Midnight Pro palette already has these.
 *
 * WHY anchor scrolling: assistant messages can mention citations inline
 * (e.g. "... [1] ..."). When the user clicks a bar segment we scroll the
 * message body so the matching [n] is visible — a small but Bloomberg-grade
 * polish detail.
 */

"use client";
// WHY "use client": we use document.getElementById for anchor scroll on click,
// which is a browser-only API.

import type { Citation } from "@/types/api";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface CitationBarProps {
 /** Citations from the message — each becomes one bar segment. */
 citations: Citation[];
 /**
 * The DOM id of the anchor target this bar links to. Each segment uses the
 * pattern `${anchorPrefix}-${index}` so the message body's [N] markers must
 * match. Wave 4 message renderer pre-emits matching ids when it finds [N]
 * tokens.
 */
 anchorPrefix: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * scoreToClasses — map a 0..1 relevance score to colour token classes.
 *
 * WHY return separate fg + bg: the segment uses bg-* for its visible body and
 * we keep an extra outline-on-hover via the same colour family so the hover
 * state reads as "stronger emphasis on the same colour" rather than a colour
 * jump.
 */
function scoreToClasses(score: number): { bg: string; outline: string; label: string } {
 if (score >= 0.7) {
 return {
 bg: "bg-positive/70",
 outline: "hover:ring-positive",
 label: "high",
 };
 }
 if (score >= 0.4) {
 return {
 // WHY amber/warning: middle band — neither failing nor strong.
 bg: "bg-warning/70",
 outline: "hover:ring-warning",
 label: "medium",
 };
 }
 return {
 bg: "bg-negative/70",
 outline: "hover:ring-negative",
 label: "low",
 };
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * CitationBar — render one segmented horizontal bar with one block per citation.
 *
 * Each segment is an anchor link. Clicking scrolls the matching [N] marker in
 * the message body into view (when present). The native browser title= on the
 * anchor doubles as an accessibility tooltip for keyboard / screen-reader users.
 *
 * QA-iter1 MIN-1: with >25 citations the old `flex-1` segments collapsed below
 * 2px each — a noisy rainbow with no scannable structure. We now apply
 * ``min-w-[8px]`` per segment AND allow the row to wrap to a second line when
 * width runs out (``flex-wrap``). 8px is the smallest size where the colour
 * coding is still legible against a dark background.
 */
export function CitationBar({ citations, anchorPrefix }: CitationBarProps) {
 if (citations.length === 0) return null;

 return (
 <div
 // WHY role=group + aria-label: assistive tech announces this as a unit.
 role="group"
 aria-label="Citation confidence"
 // WHY flex-wrap (not horizontal scroll): for >25 citations a wrap reads
 // as "another row of segments below" which mirrors how dense citation
 // lists are presented in PDF reports. Horizontal scroll would hide the
 // long tail entirely until the user scrolls the bar — easy to miss.
 className="mt-2 flex flex-wrap items-stretch gap-px"
 >
 {citations.map((c, i) => {
 const score = c.relevance_score ?? 0;
 const { bg, outline, label } = scoreToClasses(score);
 const anchorId = `${anchorPrefix}-${i + 1}`;
 return (
 <a
 key={`${anchorPrefix}-${c.article_id}-${i}`}
 href={`#${anchorId}`}
 // WHY use safeExternalUrl in the title only when we have one: the
 // anchor href targets the in-page id; the title shows the source URL
 // for context if present.
 title={`[${i + 1}] ${c.title} — ${c.source} — ${(score * 100).toFixed(0)}% (${label})`}
 // WHY data-* attribute: makes the segment programmatically findable
 // in tests without depending on the colour class name.
 data-citation-index={i + 1}
 data-citation-score={score.toFixed(2)}
 data-citation-band={label}
 // WHY onClick that does nothing: anchors with hashes already trigger
 // the browser's native scrollIntoView for matching #id targets in
 // the same document. We rely on that — no explicit JS needed.
 onClick={(e) => {
 // Prevent default only when the target id genuinely doesn't exist
 // (avoids dirtying the URL bar with a useless hash).
 const target = document.getElementById(anchorId);
 if (!target) {
 e.preventDefault();
 return;
 }
 // WHY scrollIntoView({block:"nearest"}): the message bubble is
 // typically already visible — we just want to nudge the [N]
 // marker into view if it's been scrolled out.
 target.scrollIntoView({ behavior: "smooth", block: "nearest" });
 }}
 // QA-iter1 MIN-1: ``min-w-[8px]`` keeps each segment legible even
 // when the bar is overcrowded. Combined with ``flex-wrap`` on the
 // parent, surplus segments overflow to a second row instead of
 // collapsing to invisible slivers.
 className={cn(
 "h-1.5 min-w-[8px] flex-1 rounded-[2px]",
 bg,
 outline,
 "hover:ring-1 focus:ring-1 focus:outline-none",
 )}
 >
 {/* Visually hidden text for screen readers — the title attribute
 handles desktop tooltips, but SR users get the same info here. */}
 <span className="sr-only">
 Citation {i + 1}: {c.title} — {(score * 100).toFixed(0)}% relevance ({label})
 </span>
 </a>
 );
 })}
 {/*
 * NOTE: we deliberately do NOT add hidden anchor links to the source
 * URLs here — the visible CitationList component (rendered by the
 * chat page below the message bubble) already exposes those, and
 * duplicating them inside this aria-group inflates the link role
 * count for screen readers + test queries.
 */}
 </div>
 );
}

// ── Re-export helper for tests ───────────────────────────────────────────────

/**
 * scoreBand — exposed so the unit test can verify the threshold mapping
 * without rendering a tree. Mirrors `scoreToClasses(...).label`.
 */
export function scoreBand(score: number): "high" | "medium" | "low" {
 if (score >= 0.7) return "high";
 if (score >= 0.4) return "medium";
 return "low";
}
