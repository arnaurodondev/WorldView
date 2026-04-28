/**
 * components/dashboard/MorningBriefCard.tsx — AI-generated morning brief widget
 *
 * WHY THIS EXISTS: Institutional traders start the day by reviewing a macro brief.
 * Rather than reading 20 sources, they want a single synthesised summary of
 * what matters today: key events, portfolio risk, market regime shifts.
 *
 * WHY MARKDOWN RENDERING: S8 returns the brief as markdown (headers, bold, lists).
 * ReactMarkdown + remark-gfm renders tables, task lists, and strikethrough in
 * addition to standard Markdown — matching the rich formatting the LLM generates.
 *
 * WHY COMPACT REDESIGN (Wave A-1, PLAN-0043):
 * The old layout had metadata rows (stale indicator, generated timestamp, read-more
 * button) stacked vertically, eating ~60px of a short Row 1 cell. The new layout
 * uses a single h-5 header row for all metadata so the text area fills the rest.
 * This mirrors Bloomberg Terminal's compact header-bar pattern.
 *
 * WHY 503 HANDLING AS SOFT ERROR: S8 briefing endpoint returns 503 while generating.
 * A 503 → "generating" UX is better than a hard error that breaks the dashboard.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 1, col-span-12)
 * DATA SOURCE: S9 GET /api/v1/briefings/morning → S8 GET /api/v1/briefings/morning
 * DESIGN REFERENCE: PLAN-0043 Wave A-1, PRD-0028 §6.5 Dashboard
 */

"use client";
// WHY "use client": uses useState for expand/collapse toggle, useQuery for data fetching.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
// WHY ReactMarkdown: S8 returns brief content as markdown — plain text rendering
// would lose headers, bold, lists, and tables that the LLM generates.
import ReactMarkdown from "react-markdown";
// WHY remarkGfm: enables GitHub Flavored Markdown extensions (tables, task lists,
// strikethrough) that the LLM may include in the briefing output.
import remarkGfm from "remark-gfm";
import { RefreshCw } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// WHY import BriefingResponse (not MorningBrief): PLAN-0034 unified the briefing
// response type — both morning and instrument briefs now return BriefingResponse
// which includes citations, risk_summary, and cached flag.
import type { BriefingResponse } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Brief older than 12h shows a stale badge in the header */
const STALE_MS = 12 * 60 * 60 * 1000;

// ── Component ─────────────────────────────────────────────────────────────────

export function MorningBriefCard() {
  const { accessToken } = useAuth();
  const [expanded, setExpanded] = useState(false);

  // WHY useQuery: TanStack Query handles caching, refetching, error retries,
  // and deduplication automatically. The queryKey ensures the cache is keyed
  // per endpoint (not per component instance).
  const {
    data: brief,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery<BriefingResponse>({
    queryKey: ["morning-brief"],
    queryFn: () => createGateway(accessToken).getMorningBrief(),
    enabled: !!accessToken,
    // WHY staleTime 30min: briefs are generated once per morning; no need to refetch constantly
    staleTime: 30 * 60 * 1000,
    // WHY retry: S8 briefing may be generating; retry up to 2x with 10s delay
    retry: 2,
    retryDelay: 10_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      // WHY flex flex-col h-full: component must fill its grid cell height so
      // Row 1 height is driven by the cell, not by the brief content length.
      <div className="flex h-full flex-col">
        {/* Placeholder header so height matches the loaded state */}
        <div className="flex h-5 shrink-0 items-center border-b border-border/40 px-1">
          <Skeleton className="h-2.5 w-[160px]" />
        </div>
        {/* 5-line skeleton matching typical brief length in the text area */}
        <div className="flex-1 overflow-auto px-1 pt-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton
              key={i}
              className={`mb-1 h-3 ${i === 4 ? "w-2/3" : "w-full"}`}
              style={{ animationDelay: `${i * 50}ms` }}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── Error / unavailable state ──────────────────────────────────────────────
  // WHY soft error: S8 briefing endpoint may be generating (503). Showing a
  // "generating" state is less alarming than a hard error card.
  if (isError) {
    const is503 =
      error instanceof Error &&
      (error.message.includes("503") || error.message.includes("unavailable"));

    return (
      <div className="flex h-full flex-col">
        <MetaHeader />
        <div className="flex flex-1 items-center gap-2 px-1">
          <p className="text-[10px] text-muted-foreground">
            {is503
              ? "Brief generating… check back in a few minutes."
              : "Morning brief unavailable."}
          </p>
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="ml-auto text-muted-foreground hover:text-foreground disabled:opacity-50"
            title="Retry"
            aria-label="Retry loading brief"
          >
            <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
    );
  }

  // ── No data / empty content guard ─────────────────────────────────────────
  // WHY check both: the API may return a brief object with an empty narrative
  // (LLM generated zero tokens). Show the fallback message in both cases.
  const safeContent = brief?.narrative?.trim() ?? "";
  if (!brief || !safeContent) {
    return (
      <div className="flex h-full flex-col">
        <MetaHeader />
        <div className="flex flex-1 items-center px-1">
          <p className="text-[10px] text-muted-foreground">
            AI brief unavailable — system initializing
          </p>
        </div>
      </div>
    );
  }

  // ── Content rendering ──────────────────────────────────────────────────────
  const generatedAt = new Date(brief.generated_at);
  const isStale = Date.now() - generatedAt.getTime() > STALE_MS;
  // WHY "YYYY-MM-DD HH:MM" format: compact enough for the 9px header label;
  // ISO 8601 slice [0,16] gives "YYYY-MM-DDTHH:MM" — replace T with space.
  const ts = generatedAt.toISOString().slice(0, 16).replace("T", " ");

  // WHY replace entity names with links: lets traders click directly to the
  // instrument detail page — faster than searching.
  const contentWithLinks = (brief.entity_mentions ?? []).reduce((text, mention) => {
    if (!mention.name) return text;
    const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
    return text.replace(
      regex,
      `[${mention.name}](/instruments/${mention.entity_id})`,
    );
  }, safeContent);

  // Extract a 1-line headline for the collapsed state — first H2 or first bold phrase.
  // WHY extractHeadline here (not a helper): keeps the logic co-located with the
  // one component that uses it. Bloomberg Terminal always surfaces a top-line signal
  // so traders can absorb the brief's key message without reading the body.
  const headline = extractHeadline(safeContent);
  // A brief is "long" if there is meaningful content beyond the headline.
  // We always show 3 body lines; the expand button appears when there is more.
  const isLong = safeContent.length > 200;

  return (
    // WHY flex flex-col h-full: fills Row 1 grid cell; header is fixed h-5,
    // text area fills the rest with overflow-auto for long briefs.
    <div className="flex h-full flex-col">

      {/* ── Header row: timestamp (left) + stale badge + refresh (right) ─── */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border/40 px-1">
        {/* Generated timestamp — muted, monospace for scannable date/time */}
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground/60">
          Generated {ts} UTC
        </span>

        {/* Stale badge + refresh — only visible when brief is > 12h old */}
        {isStale && (
          <div className="flex items-center gap-1">
            <span className="text-[9px] text-amber-400">stale</span>
            <button
              onClick={() => void refetch()}
              disabled={isFetching}
              className="text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="Refresh morning brief"
              aria-label="Refresh morning brief"
            >
              <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
            </button>
          </div>
        )}
      </div>

      {/* ── Text area: flex-1 so it fills remaining Row 1 height ────────────── */}
      <div className="flex-1 overflow-auto px-1 py-0.5">
        {/* WHY shared ReactMarkdown classes: both collapsed and expanded use the
            same markdown styling so the transition between states is seamless. */}
        {/* WHY ReactMarkdown for all states: entity mentions ([Apple](/instruments/ent-1))
            must render as clickable links even in the collapsed preview. Plain <p> text
            would display the raw markdown syntax, breaking entity navigation. */}
        <div className="text-[10px] leading-snug text-foreground/90 [&_a]:text-primary [&_a]:hover:underline [&_h1]:mb-0.5 [&_h1]:text-[9px] [&_h1]:font-semibold [&_h1]:uppercase [&_h1]:tracking-[0.08em] [&_h1]:text-muted-foreground [&_h2]:mb-0 [&_h2]:mt-1.5 [&_h2]:text-[9px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.08em] [&_h2]:text-muted-foreground [&_h3]:mt-0.5 [&_h3]:text-[10px] [&_h3]:font-medium [&_li]:leading-snug [&_p]:mt-0.5 [&_strong]:font-semibold [&_ul]:mt-0.5 [&_ul]:pl-3">
          {!expanded ? (
            // ── Collapsed view: headline + clamp-3 ReactMarkdown preview ─────
            // WHY headline first: Bloomberg-grade briefs lead with the most
            // important signal. A trader reads "Fed signals pause" in 1s.
            // WHY ReactMarkdown in collapsed: entity mentions must render as
            // links even in preview (not raw markdown text).
            <>
              {headline && (
                <p className="mb-0.5 font-semibold leading-tight">
                  {headline}
                </p>
              )}
              {/* WHY [&>*:first-child]:mt-0: remove top margin from first
                  child element so the preview aligns flush with the headline */}
              <div className="line-clamp-3 [&>*:first-child]:mt-0">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    a: ({ href, children }) => (
                      <Link href={href ?? "#"} className="text-primary hover:underline">
                        {children}
                      </Link>
                    ),
                    // WHY strip headers: ## headings in a 3-line clamp waste the
                    // visible space with section labels; show body content instead.
                    h1: ({ children }) => <span>{children} </span>,
                    h2: ({ children }) => <span>{children} </span>,
                    h3: ({ children }) => <span>{children} </span>,
                  }}
                >
                  {contentWithLinks}
                </ReactMarkdown>
              </div>
              {isLong && (
                <button
                  onClick={() => setExpanded(true)}
                  className="mt-0.5 text-[9px] text-primary hover:underline"
                  aria-label="Expand morning brief"
                >
                  Read more →
                </button>
              )}
            </>
          ) : (
            // ── Expanded view: full markdown rendering ────────────────────────
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <Link href={href ?? "#"} className="text-primary hover:underline">
                    {children}
                  </Link>
                ),
              }}
            >
              {contentWithLinks}
            </ReactMarkdown>
          )}
        </div>
      </div>

      {/* ── "Show less" link — only when expanded ────────────────────────────── */}
      {isLong && expanded && (
        <div className="shrink-0 border-t border-border/40 px-1 py-0.5">
          <button
            onClick={() => setExpanded(false)}
            className="text-[9px] text-muted-foreground hover:text-foreground"
            aria-label="Collapse morning brief"
          >
            show less ↑
          </button>
        </div>
      )}

    </div>
  );
}

// ── MetaHeader ────────────────────────────────────────────────────────────────

/**
 * MetaHeader — placeholder h-5 header bar used in loading/error/empty states
 * where the generated-at timestamp is not yet available.
 * WHY: ensures all states have the same top chrome so height is predictable.
 */
function MetaHeader() {
  return (
    <div className="flex h-5 shrink-0 items-center border-b border-border/40 px-1">
      <span className="text-[9px] uppercase tracking-[0.08em] text-muted-foreground/40">
        MORNING BRIEF
      </span>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** escapeRegex — escape special chars in entity names for use in RegExp */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * extractHeadline — pull the most important 1-line signal from brief markdown.
 * WHY: Institutional traders expect a top-line summary before reading the brief
 * body. We try H2 headers first (LLM sections like "## Market Regime"), then
 * bold phrases ("**Key Signal: …**"), then the first sentence as a fallback.
 * Returns null if the brief is too short to warrant a separate headline.
 */
function extractHeadline(markdown: string): string | null {
  if (!markdown || markdown.length < 40) return null;

  // Try first ## H2 header (LLM-generated section titles like "## Market Regime")
  const h2Match = markdown.match(/^##\s+(.+)$/m);
  if (h2Match?.[1]) return h2Match[1].trim();

  // Try first **bold phrase** (often the LLM key signal)
  const boldMatch = markdown.match(/\*\*([^*]{10,80})\*\*/);
  if (boldMatch?.[1]) return boldMatch[1].trim();

  // Fallback: first meaningful sentence (>30 chars) from the first paragraph
  const firstPara = markdown.split(/\n\n/)[0] ?? "";
  const clean = firstPara.replace(/[#*`_]/g, "").trim();
  const sentenceEnd = clean.search(/[.!?]/);
  if (sentenceEnd > 30) return clean.slice(0, sentenceEnd + 1).trim();

  return null;
}
