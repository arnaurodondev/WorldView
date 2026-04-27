/**
 * components/workspace/WorkspaceBriefWidget.tsx — Morning Brief AI panel for workspace
 *
 * WHY THIS EXISTS: The Morning Brief (PRD-0031 §5.4) is Worldview's key AI-generated
 * insight product. In the workspace, it surfaces as an amber-accented collapsible panel
 * that gives traders an instant summary before market open without navigating away.
 *
 * WHY AMBER STYLING (#FFD60A/10 fill + border-l-2): Per §0.4, amber (#FFD60A) is
 * EXCLUSIVELY for AI-generated content. The left accent + tinted background is the
 * canonical Worldview pattern for AI surfaces (also used in InstrumentAISubheader).
 *
 * WHY COLLAPSIBLE: The brief can be long (500+ words). In collapsed mode, the user
 * sees the first sentence to judge relevance; they expand to read if interested.
 * This preserves workspace panel density without losing access to the full text.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "brief"
 * DATA SOURCE: GET /v1/briefings/morning (S9 gateway, rag-chat service S8)
 * DESIGN REFERENCE: PRD-0031 §5.4 WorkspaceBriefWidget, §0.4 Color discipline
 */

"use client";
// WHY "use client": uses useState for expand/collapse toggle + TanStack Query

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";

export function WorkspaceBriefWidget() {
  const { accessToken } = useAuth();
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["morning-brief"],
    queryFn: () => createGateway(accessToken).getMorningBrief(),
    enabled: !!accessToken,
    // WHY 10min staleTime: morning briefs are generated once daily at market open.
    // Refetching every request wastes API calls — 10 min gives fresh reads after
    // generation without polling aggressively.
    staleTime: 10 * 60_000,
  });

  if (isLoading) {
    return (
      // WHY border-primary / bg-primary/10: these are the design-token equivalents of
      // the AI accent style. Using tokens (not hardcoded hex) ensures the colour
      // updates automatically if the primary token changes in globals.css.
      <div className="border-l-2 border-primary bg-primary/10 p-2 space-y-1">
        <Skeleton className="h-2.5 w-full" />
        <Skeleton className="h-2.5 w-4/5" />
        <Skeleton className="h-2.5 w-2/3" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="border-l-2 border-primary bg-primary/10 px-2 py-1">
        <p className="text-[11px] text-muted-foreground">Morning brief not yet generated.</p>
      </div>
    );
  }

  // WHY check narrative field: BriefingResponse.narrative is the canonical field
  // per the api.ts type definition — mirrors S8's PublicBriefingResponse.narrative.
  // Guard defensively against empty strings from failed/timed-out LLM generation.
  const briefText = data.narrative ?? "";

  if (!briefText) {
    return (
      <div className="border-l-2 border-primary bg-primary/10 px-2 py-1">
        <p className="text-[11px] text-muted-foreground">Morning brief not yet generated.</p>
      </div>
    );
  }

  // WHY first 120 chars for preview: gives enough context (~1 sentence) to judge
  // whether to expand without spoiling the full analysis.
  const preview = briefText.length > 120 ? `${briefText.slice(0, 120)}…` : briefText;

  return (
    // WHY border-primary / bg-primary/10: design-token equivalents of the AI accent.
    // border-l-2 is the canonical left-rail pattern for AI-generated content (§0.3).
    // Using tokens (not hardcoded #FFD60A hex) keeps palette changes in globals.css.
    <div className="border-l-2 border-primary bg-primary/10">
      {/* Header row with expand toggle */}
      <button
        className="flex w-full items-center gap-1.5 px-2 h-[22px] hover:bg-primary/5"
        aria-expanded={expanded}
        aria-label="Toggle morning brief"
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Toggle icon — chevron down when collapsed, right when expanded */}
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-primary shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="h-3 w-3 text-primary shrink-0" aria-hidden />
        )}
        {/* Section label */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-primary font-sans">
          Morning Brief
        </span>
        {/* Collapsed preview text — shown inline when collapsed */}
        {!expanded && (
          <span className="truncate text-[11px] text-muted-foreground ml-1">
            {preview}
          </span>
        )}
      </button>

      {/* Expanded content — grid-rows animation per §0.5 approved animations */}
      {/*
       * WHY grid-rows approach for expand/collapse: §0.5 bans animating height directly
       * (causes browser reflow). grid-template-rows: 0fr→1fr is the approved pattern
       * for height transitions in this codebase.
       */}
      <div
        className="grid transition-[grid-template-rows] duration-150 ease-out"
        style={{
          gridTemplateRows: expanded ? "1fr" : "0fr",
        }}
      >
        <div className="overflow-hidden">
          <p className="px-2 py-2 text-[13px] text-foreground leading-relaxed">
            {briefText}
          </p>
        </div>
      </div>
    </div>
  );
}
