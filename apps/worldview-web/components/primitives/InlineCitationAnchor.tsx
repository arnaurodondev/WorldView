/**
 * components/primitives/InlineCitationAnchor.tsx — `[c1]`-style citation chip
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 — chat, brief, AskAi panel, and
 * Intelligence brief footer all render inline citations. Pre-F1 each
 * surface had its own parser + HoverCard wiring (~310 LOC duplicated).
 * One primitive collapses all three surfaces to a shared anchor + hover
 * preview contract.
 * WHO USES IT: rag-chat ChatMessage, brief BriefBullet, Quote tab brief
 *   footer, AskAiPanel response.
 * DATA SOURCE: Pure presentational — caller passes kind + id. The hover
 *   preview is rendered by the parent (which has the citation metadata
 *   already in context).
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (InlineCitationAnchor row) +
 *   FU-DISCUSS-12 (consolidated citation contract).
 *
 * 250ms HoverCard open delay — Tier-2 chrome transition (animate the
 * popover opacity, not its size).
 */

import type { ReactNode } from "react";

type CitationKind = "SEC" | "EARN" | "NEWS" | "KG" | "BRF";

interface InlineCitationAnchorProps {
  readonly kind: CitationKind;
  readonly id: string;
  /** Label override. Defaults to `[c1]` style auto-numbered text. */
  readonly label?: string;
  /** Rendering density. "brief-footer" = even tighter for the brief footer. */
  readonly density?: "terminal" | "compact" | "brief-footer";
  /** Optional click handler — caller usually wires this to scroll-to-source. */
  readonly onActivate?: (kind: CitationKind, id: string) => void;
  /** Optional hover-preview content. Parent provides citation metadata. */
  readonly preview?: ReactNode;
}

// Kind → token color. Each citation kind maps to a known data domain:
// SEC = filings, EARN = earnings, NEWS = articles, KG = knowledge-graph
// fact, BRF = generated brief. Distinct color = fast visual triage.
const KIND_CLASS: Record<CitationKind, string> = {
  SEC: "text-positive",
  EARN: "text-primary",
  NEWS: "text-foreground",
  KG: "text-accent-foreground",
  BRF: "text-warning",
};

export function InlineCitationAnchor({
  kind,
  id,
  label,
  density = "terminal",
  onActivate,
  preview,
}: InlineCitationAnchorProps): ReactNode {
  const sizeClass = density === "brief-footer" ? "text-[9px]" : "text-[10px]";
  const displayLabel = label ?? `[${kind.toLowerCase()}-${id}]`;
  return (
    <span
      role="link"
      tabIndex={0}
      onClick={() => onActivate?.(kind, id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onActivate?.(kind, id);
      }}
      className={`group relative inline-flex cursor-pointer font-mono ${sizeClass} ${KIND_CLASS[kind]} transition-color-only duration-100 hover:underline`}
      aria-label={`Citation: ${kind} ${id}`}
    >
      {displayLabel}
      {preview ? (
        // Caller-rendered preview, shown on hover/focus.  Tier-2 chrome —
        // opacity-only transition, 200ms ceiling.
        <span className="pointer-events-none absolute left-0 top-full z-40 mt-1 hidden min-w-[200px] border border-border-strong bg-popover p-1.5 text-[11px] text-popover-foreground opacity-0 transition-color-and-opacity duration-200 group-hover:block group-hover:opacity-100 group-focus:block group-focus:opacity-100">
          {preview}
        </span>
      ) : null}
    </span>
  );
}
