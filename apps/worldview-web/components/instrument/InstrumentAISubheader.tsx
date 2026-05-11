/**
 * components/instrument/InstrumentAISubheader.tsx — Collapsible AI brief subheader
 *
 * WHY THIS EXISTS: Replaces InstrumentBriefPanel with a terminal-style collapsed
 * band (h-7, 28px) that the analyst can expand to read the full AI brief. The panel
 * sits between the compact header and the tab navigation — always visible
 * regardless of which tab is active.
 *
 * WHY sessionStorage (not useState only): Expand state should persist across tab
 * switches on the same page visit (e.g., switching Overview → Fundamentals → back).
 * sessionStorage resets on new page load (correct — each visit starts collapsed).
 * localStorage would persist across browser sessions which is too sticky for a
 * dynamic brief that regenerates daily.
 *
 * WHY KEYED BY entityId: Each instrument has its own expand state. Navigating
 * from AAPL → MSFT should not carry over the expanded state.
 *
 * WHY border-l-2 border-l-primary: The yellow-left-border pattern is the worldview
 * design system's visual marker for AI-generated content. bg-primary/10 provides
 * the subtle amber tint without being distracting.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (above <Tabs>)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/brief → S8 AI brief generation
 * DESIGN REFERENCE: PRD-0031 §9 InstrumentAISubheader, Wave 5
 */

"use client";
// WHY "use client": uses useState (expand state), useEffect (sessionStorage),
// useQuery (brief fetch), and browser APIs (sessionStorage).

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ChevronDown } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// WHY MarkdownContent (PLAN-0049 T-D-4-02): the expanded subheader previously
// rendered ``brief.narrative`` as plain text inside a <p> — markdown structures
// emitted by the LLM (headers, lists, bold, links) rendered as raw "##" prefixes
// instead of styled prose. The shared <MarkdownContent size="compact"> is the
// canonical worldview renderer (used by MorningBriefCard expanded view + the
// IntelligenceTab brief block) so all three AI brief surfaces look identical.
// The collapsed preview row keeps the plain-text slice — markdown formatting
// inside a 120-char preview would expand vertical chrome that the h-9 band
// cannot accommodate.
import { MarkdownContent } from "@/components/ui/markdown-content";
import type { BriefingResponse } from "@/types/api";
// PLAN-0062-W4 T-W4-E-02: StructuredBrief renders W4+ sections (BriefBullet
// with citation chips) in the expanded subheader. Falls back to MarkdownContent
// for pre-W4 cached responses that have no sections array.
import { StructuredBrief } from "@/components/brief/StructuredBrief";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Characters of brief text shown in the collapsed preview row */
const PREVIEW_CHARS = 120;

// ── Props ─────────────────────────────────────────────────────────────────────

interface InstrumentAISubheaderProps {
  entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InstrumentAISubheader({ entityId }: InstrumentAISubheaderProps) {
  const { accessToken } = useAuth();

  // WHY sessionStorage (not localStorage): brief expand state is per-session,
  // not persistent across browser sessions. Each page visit starts collapsed.
  // WHY keyed by entityId: each instrument has its own expand state so switching
  // from AAPL to MSFT doesn't carry over the expanded state.
  const storageKey = `ai-subheader-${entityId}`;
  const [expanded, setExpanded] = useState(() => {
    try {
      return sessionStorage.getItem(storageKey) === "1";
    } catch {
      // sessionStorage unavailable (SSR, private mode) — default collapsed
      return false;
    }
  });

  // Toggle expand state and persist to sessionStorage
  const toggle = () => {
    setExpanded((v) => {
      const next = !v;
      try {
        sessionStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        // sessionStorage unavailable — still update React state
      }
      return next;
    });
  };

  // TODO(T-C-3-01): No per-symbol earnings endpoint in S9 — wire when
  // /v1/entities/{id}/earnings is added. An "upcoming earnings" chip would sit
  // alongside the AI BRIEF label in the collapsed row (e.g., "AAPL earnings in 12d").
  // The dashboard uses a separate /calendar/earnings endpoint that returns a list,
  // not a per-symbol lookup, so it cannot be reused here without filtering.

  // ── Brief data query ──────────────────────────────────────────────────────
  // WHY staleTime 30min: instrument briefs are generated on-demand by S8 and
  // cached in Valkey for 24h. No need to refetch aggressively.
  // WHY retry 2 + 10s delay: S8 may still be generating (503); give it time.
  const {
    data: brief,
    isLoading,
    isError,
  } = useQuery<BriefingResponse>({
    queryKey: ["instrument-brief", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 30 * 60_000,
    retry: 2,
    retryDelay: 10_000,
  });

  // ── No data / error → show nothing ────────────────────────────────────────
  // WHY return null for error: the brief is supplemental context, not critical data.
  // An error bar between header and tabs would be distracting for non-fatal errors.
  // WHY !brief?.narrative guard: API may return {} (empty object) when brief is not yet
  // generated. brief = {} is truthy so !brief alone doesn't catch it — check narrative.
  // WHY narrative (not content): BriefingResponse.narrative mirrors S8's PublicBriefingResponse.
  if (!isLoading && (isError || !brief?.narrative)) {
    // Show a minimal "Brief generating..." inline if error
    if (isError) {
      return (
        <div className="border-b border-border border-l-2 border-l-primary bg-primary/10 shrink-0">
          <div className="flex items-center h-7 px-2 gap-1.5">
            <ChevronRight className="h-3 w-3 text-primary shrink-0" strokeWidth={1.5} />
            <span className="text-[10px] uppercase tracking-[0.08em] text-primary shrink-0">
              AI BRIEF
            </span>
            <span className="truncate text-[11px] text-muted-foreground ml-1 flex-1">
              Brief generating…
            </span>
          </div>
        </div>
      );
    }
    // No brief at all — return nothing
    return null;
  }

  // ── Loading skeleton ───────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="border-b border-border border-l-2 border-l-primary bg-primary/10 shrink-0">
        {/* WHY h-7 (28px): T-B-2-02 — collapsed band is now the terminal-standard
            h-7 row height. Was h-9 (36px) which was non-standard. */}
        <div className="flex items-center h-7 px-2 gap-1.5">
          <ChevronRight className="h-3 w-3 text-primary shrink-0" strokeWidth={1.5} />
          <span className="text-[10px] uppercase tracking-[0.08em] text-primary shrink-0">
            AI BRIEF
          </span>
          {/* WHY skeleton inside collapsed row (not full-height): the skeleton
              should not shift layout — it stays within the fixed h-7 band. */}
          <Skeleton className="h-3 flex-1 ml-1" />
        </div>
      </div>
    );
  }

  // brief is guaranteed non-null here (isLoading=false, isError=false, brief exists)
  // WHY .narrative (not .content): BriefingResponse.narrative is the canonical field
  // per types/api.ts — mirrors S8 PublicBriefingResponse.narrative.
  //
  // WHY prefer lead for preview (PLAN-0062-W4 T-W4-E-02): when the W4 lead block
  // is present it is a 1-2 sentence executive summary — perfect for the 120-char
  // preview row. Falling back to narrative.slice keeps pre-W4 cached responses working.
  const previewSource = brief!.lead || brief!.narrative;
  const previewText = previewSource.slice(0, PREVIEW_CHARS);
  const hasMore = previewSource.length > PREVIEW_CHARS;

  return (
    // WHY border-l-2 border-l-primary: yellow-left-border is the AI content marker
    // in the worldview design system. Keeps it visually consistent with other AI panels.
    <div className="border-b border-border border-l-2 border-l-primary bg-primary/10 shrink-0">

      {/* ── Collapsed row (always visible, h-7) ──────────────────────────── */}
      {/* WHY h-7 (28px): T-B-2-02 — collapsed band uses the terminal-standard h-7
          height. Was h-9 (36px) which was non-standard for terminal rows.
          Expanded state height is controlled by grid-template-rows, not this button. */}
      {/* WHY button wrapping the whole row: makes the entire band clickable for
          expand/collapse — not just the chevron. Bloomberg panel headers work this way. */}
      <button
        onClick={toggle}
        className="flex items-center w-full h-7 px-2 gap-1.5 text-left"
        aria-expanded={expanded}
        aria-label={expanded ? "Collapse AI brief" : "Expand AI brief"}
      >
        {/* Toggle chevron — right when collapsed, down when expanded */}
        {expanded
          ? <ChevronDown className="h-3 w-3 text-primary shrink-0" strokeWidth={1.5} />
          : <ChevronRight className="h-3 w-3 text-primary shrink-0" strokeWidth={1.5} />
        }

        {/* Label — uppercase terminal style */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-primary shrink-0">
          AI BRIEF
        </span>

        {/* Preview text — truncated to PREVIEW_CHARS in collapsed state */}
        <span className="truncate text-[11px] text-muted-foreground ml-1 flex-1">
          {previewText}{hasMore && !expanded ? "…" : ""}
        </span>
      </button>

      {/* ── Expanded content (grid-rows animation) ────────────────────────── */}
      {/* WHY grid-template-rows 0fr→1fr: GPU-composited transition, no layout thrash.
          The inner div needs overflow-hidden to clip the content at 0fr height. */}
      <div
        className="grid transition-[grid-template-rows] duration-150 ease-out"
        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
      >
        <div className="overflow-hidden">
          {/* WHY two-tier expanded path (PLAN-0062-W4 T-W4-E-02):
              - W4+ sections present: StructuredBrief renders citation chips per bullet.
                variant="inline" is used here so the expanded panel stays horizontally
                compact (subheader band, not a full card). Only lead + section count
                is shown; full sections are available via the instrument detail tab.
              - No sections (pre-W4): MarkdownContent as before — renders narrative markdown
                with compact typography. */}
          <div className="px-2 py-2">
            {brief!.sections && brief!.sections.length > 0 ? (
              // WHY variant="compact": the subheader expanded state is still constrained —
              // "compact" suppresses citation chips in bullets and uses smaller spacing so
              // the band doesn't grow to card height. The lead block is still shown.
              <StructuredBrief
                lead={brief!.lead}
                sections={brief!.sections}
                confidence={brief!.confidence}
                variant="compact"
              />
            ) : (
              // Fallback: pre-W4 brief with no sections — render markdown narrative.
              <MarkdownContent size="compact">{brief!.narrative}</MarkdownContent>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
