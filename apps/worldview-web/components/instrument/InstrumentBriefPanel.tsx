/**
 * components/instrument/InstrumentBriefPanel.tsx — Compact AI instrument brief
 *
 * WHY THIS EXISTS: Analysts want an AI-generated context summary at the TOP of
 * every instrument tab — not buried in the Intelligence tab. This panel appears
 * between the instrument header (ticker, stats) and the tab navigation, so it
 * is always visible regardless of which tab the user is on.
 *
 * WHY SEPARATE FROM IntelligenceTab: IntelligenceTab.tsx has an inline
 * InstrumentBriefSection that is only rendered inside the Intelligence tab.
 * Extracting this into a standalone component allows the instrument page to
 * render it once, at the page level, shared across all four tabs.
 *
 * WHY COMPACT LAYOUT: This panel sits above the tabs, so it must be as dense
 * as possible. We show the brief in a horizontal band (not a card with padding)
 * to avoid pushing the chart content below the fold.
 *
 * WHY COLLAPSIBLE: The brief can be 300–600 chars. A collapsed one-liner lets
 * traders who don't need the brief scroll past it quickly; expanding reveals
 * the full markdown-rendered text for analysts who want depth.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (above <Tabs>)
 * DATA SOURCE: S9 GET /v1/entities/{entityId}/brief → S8 AI brief generation
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail shared brief (UI-003 fix)
 */

"use client";
// WHY "use client": useQuery for data fetching, useState for expand/collapse.

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { RefreshCw, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import type { BriefingResponse } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Show first 220 chars collapsed — 1-2 sentences of context before "read more" */
const PREVIEW_CHARS = 220;

/** Brief older than 12h is considered stale for an instrument context */
const STALE_MS = 12 * 60 * 60 * 1000;

// ── Props ─────────────────────────────────────────────────────────────────────

interface InstrumentBriefPanelProps {
  /** Entity ID of the instrument — used to fetch the AI brief */
  entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InstrumentBriefPanel({ entityId }: InstrumentBriefPanelProps) {
  const { accessToken } = useAuth();
  const [expanded, setExpanded] = useState(false);

  // WHY staleTime 30min: instrument briefs are generated on-demand by S8 and
  // cached in Valkey for 24h. Aggressive refetching wastes quota.
  // WHY retry 2 + 10s delay: S8 may still be generating (503 status); give it
  // time to complete before surfacing an error to the trader.
  const {
    data: brief,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery<BriefingResponse>({
    queryKey: ["instrument-brief", entityId],
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: 30 * 60 * 1000,
    retry: 2,
    retryDelay: 10_000,
  });

  // ── Loading skeleton ───────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="border-b border-border/40 px-4 py-2">
        <div className="flex items-start gap-2">
          {/* Sparkles icon placeholder */}
          <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-amber-500/60" aria-hidden="true" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3 w-full" style={{ animationDelay: "0ms" }} />
            <Skeleton className="h-3 w-4/5" style={{ animationDelay: "50ms" }} />
          </div>
        </div>
      </div>
    );
  }

  // ── Error / unavailable ────────────────────────────────────────────────────
  if (isError) {
    const is503 =
      error instanceof Error &&
      (error.message.includes("503") || error.message.includes("unavailable"));

    return (
      <div className="flex items-center gap-2 border-b border-border/40 px-4 py-2">
        <Sparkles className="h-3 w-3 shrink-0 text-amber-500/40" aria-hidden="true" />
        <p className="flex-1 text-xs text-muted-foreground">
          {is503
            ? "Brief generating… check back in a moment."
            : "AI brief unavailable."}
        </p>
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="shrink-0 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
          title="Retry"
        >
          <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
        </button>
      </div>
    );
  }

  // ── No brief yet ───────────────────────────────────────────────────────────
  if (!brief) {
    return null; // WHY null: no brief = nothing to show; avoid empty placeholder bar
  }

  // ── Stale indicator ────────────────────────────────────────────────────────
  const generatedAt = new Date(brief.generated_at);
  const isStale = Date.now() - generatedAt.getTime() > STALE_MS;

  // ── Content — resolve entity mention links ─────────────────────────────────
  // WHY replace entity names with links: lets traders click directly to the
  // related instrument page. Empty-name guard prevents RegExp(\b\b) catastrophe.
  // WHY ?? "": brief.content may be null/undefined if generation failed mid-stream.
  const safeContent = brief.content ?? "";
  const contentWithLinks = brief.entity_mentions.reduce((text, mention) => {
    if (!mention.name) return text;
    const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
    return text.replace(
      regex,
      `[${mention.name}](/instruments/${mention.entity_id})`,
    );
  }, safeContent);

  const isLong = safeContent.length > PREVIEW_CHARS;

  return (
    // WHY border-b: visually separates the brief from the tab strip below it.
    // The brief is contextual header content, not a tab's body content.
    <div className="border-b border-border/40 px-4 py-2">
      <div className="flex items-start gap-2">
        {/* Amber sparkle icon — signals AI-generated content */}
        <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" aria-hidden="true" />

        <div className="min-w-0 flex-1">
          {/* Stale warning — show before the content if brief is old */}
          {isStale && (
            <span className="mr-2 text-[10px] text-amber-400">
              (outdated —{" "}
              <button
                onClick={() => void refetch()}
                disabled={isFetching}
                className="underline hover:no-underline disabled:opacity-50"
              >
                refresh
              </button>
              )
            </span>
          )}

          {/* Brief text — collapsed to preview or expanded to full markdown */}
          {/* WHY identical styling to MorningBriefCard (text-xs, [&_selector]):
              ReactMarkdown defaults to article-scale typography. Tailwind's
              prose plugin applies 14px base size which looks oversized in a
              compact terminal header band. The [&_selector] pattern pins all
              markdown-generated elements to text-xs (12px). */}
          <div className="inline max-w-none text-xs leading-relaxed text-foreground/90 [&_a]:text-primary [&_a]:hover:underline [&_strong]:font-semibold">
            {isLong && !expanded ? (
              <span className="text-xs text-foreground/90">
                {safeContent.slice(0, PREVIEW_CHARS)}
                <span className="text-muted-foreground">…</span>
              </span>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // WHY custom link: entity mentions become Next.js Links for client-side nav
                  a: ({ href, children }) => (
                    <Link href={href ?? "#"} className="text-primary hover:underline">
                      {children}
                    </Link>
                  ),
                  // WHY custom p: inline display so the brief flows as a single
                  // horizontal band rather than a block paragraph with margins.
                  p: ({ children }) => <span className="text-xs leading-relaxed text-foreground/90">{children}</span>,
                }}
              >
                {contentWithLinks}
              </ReactMarkdown>
            )}
          </div>

          {/* Expand/collapse + timestamp row */}
          <div className="mt-0.5 flex items-center gap-3">
            {isLong && (
              <button
                onClick={() => setExpanded((p) => !p)}
                className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground"
              >
                {expanded ? (
                  <><ChevronUp className="h-2.5 w-2.5" /> Less</>
                ) : (
                  <><ChevronDown className="h-2.5 w-2.5" /> More</>
                )}
              </button>
            )}
            <span className="font-mono text-[9px] tabular-nums text-muted-foreground/60">
              {generatedAt.toISOString().slice(0, 16).replace("T", " ")} UTC
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Helper ────────────────────────────────────────────────────────────────────

/** escapeRegex — escape special chars in entity names for safe use in RegExp */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
