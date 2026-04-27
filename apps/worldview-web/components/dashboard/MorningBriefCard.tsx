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
 * WHY EXPAND/COLLAPSE: The brief can be 500+ words. A collapsed preview (first 200 chars)
 * respects screen real estate — the user can expand when they want full detail.
 *
 * WHY 503 HANDLING AS SOFT ERROR: S8 briefing endpoint returns 503 while generating.
 * A 503 → "generating" UX is better than a hard error that breaks the dashboard.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /api/v1/briefings/morning → S8 GET /api/v1/briefings/morning
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard, canvas State A MorningBriefCard
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
import { RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
// WHY import BriefingResponse (not MorningBrief): PLAN-0034 unified the briefing
// response type — both morning and instrument briefs now return BriefingResponse
// which includes citations, risk_summary, and cached flag.
import type { BriefingResponse } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Show first 200 chars in collapsed state — enough for 2-3 sentences */
const PREVIEW_CHARS = 200;

/** Brief older than 12h shows a refresh prompt */
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
      <div className="space-y-2 p-1">
        {/* 5-line skeleton matching typical brief length */}
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className={`h-4 ${i === 4 ? "w-2/3" : "w-full"}`} style={{ animationDelay: `${i * 50}ms` }} />
        ))}
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
      <div className="flex items-center justify-between py-1">
        <p className="text-sm text-muted-foreground">
          {is503
            ? "Brief generating... check back in a few minutes."
            : "Morning brief unavailable."}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="ml-2 h-6 px-2 text-xs"
          title="Retry"
        >
          <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
        </Button>
      </div>
    );
  }

  // ── No data ────────────────────────────────────────────────────────────────
  // WHY "AI brief unavailable — system initializing" (not "No brief available"):
  // "System initializing" sets correct expectations — the platform may be warming
  // up ML inference services or the briefing generation job hasn't run yet today.
  // A blank space here would confuse traders into thinking the widget is broken.
  if (!brief) {
    return (
      <p className="py-1 text-sm text-muted-foreground">
        AI brief unavailable — system initializing
      </p>
    );
  }

  // ── Empty content guard ────────────────────────────────────────────────────
  // WHY check safeContent length: the API may return a brief object with an empty
  // string for `narrative` if the LLM generated zero tokens (e.g., context was empty
  // or the generation timed out). In this case the UI would render a blank panel
  // (ReactMarkdown on "" produces nothing). Show the fallback message instead.
  //
  // WHY "narrative" (not "content"): S8's PublicBriefingResponse schema field is
  // "narrative". The types/api.ts BriefingResponse interface mirrors this exactly.
  // Using brief.content would always be undefined → always show the fallback.
  const safeContentEarly = brief.narrative ?? "";
  if (!safeContentEarly.trim()) {
    return (
      <p className="py-1 text-sm text-muted-foreground">
        AI brief unavailable — system initializing
      </p>
    );
  }

  // ── Stale brief indicator ──────────────────────────────────────────────────
  const generatedAt = new Date(brief.generated_at);
  const isStale = Date.now() - generatedAt.getTime() > STALE_MS;

  // ── Content rendering ──────────────────────────────────────────────────────
  // WHY replace entity names with links: lets traders click directly to the
  // instrument detail page — faster than searching. Regex scans entity_mentions.
  // WHY reuse safeContentEarly: we already computed `brief.content ?? ""` above
  // for the empty-guard check — reuse it here to avoid a second null-coalesce.
  const safeContent = safeContentEarly;

  const contentWithLinks = (brief.entity_mentions ?? []).reduce((text, mention) => {
    // WHY empty-name guard: if mention.name is "" then escapeRegex("") returns ""
    // and new RegExp("\\b\\b", "g") matches EVERY word boundary in the string.
    // With 9+ empty-name mentions, each reduce iteration inserts "/instruments/UUID"
    // (which contains new word chars like "instruments") into every boundary, causing
    // exponential string growth → RangeError: Invalid string length → error boundary.
    if (!mention.name) return text;
    // WHY word boundary match: avoid partial matches inside longer names
    const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
    return text.replace(
      regex,
      `[${mention.name}](/instruments/${mention.entity_id})`,
    );
  }, safeContent);

  const isLong = safeContent.length > PREVIEW_CHARS;
  const preview = safeContent.slice(0, PREVIEW_CHARS);

  return (
    <div>
      {/* Stale indicator — show if brief is > 12h old */}
      {isStale && (
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs text-amber-400">Brief may be outdated</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="h-5 px-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className={`mr-1 h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      )}

      {/* Brief text — collapsed or expanded */}
      {/* WHY ReactMarkdown: the LLM returns markdown with headers, bold, lists.
          ReactMarkdown renders these as proper HTML elements with semantic structure.
          remarkGfm adds support for tables, task lists, and strikethrough. */}
      {/*
       * WHY NOT prose/prose-sm/prose-invert (UI-002):
       * Tailwind's `prose` plugin is designed for article/blog typography — it sets
       * generous font sizes (prose-sm base is still 14px), large heading sizes (h2
       * becomes 1.25em → ~17.5px), and spacious line heights/margins. For a financial
       * terminal widget that lives in a compact card alongside 8 other panels, this
       * feels like a newspaper inside a Bloomberg terminal.
       *
       * Instead we use Tailwind's arbitrary-selector syntax `[&_selector]:property`
       * to directly style each markdown-generated HTML element at text-xs (12px).
       * This keeps ALL content — headings, paragraphs, lists — at terminal density
       * while preserving the semantic structure ReactMarkdown emits.
       *
       * The `[&_h2]` pattern (underscore = descendant) means "any h2 inside this div",
       * equivalent to `.container h2 { ... }` in plain CSS.
       */}
      <div className="max-w-none text-xs leading-relaxed text-foreground/90 [&_a]:text-primary [&_a]:hover:underline [&_h1]:mb-1 [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:mb-0.5 [&_h2]:mt-2 [&_h2]:text-xs [&_h2]:font-semibold [&_h3]:mt-1 [&_h3]:text-xs [&_h3]:font-medium [&_li]:leading-relaxed [&_p]:mt-1 [&_strong]:font-semibold [&_ul]:mt-1 [&_ul]:pl-3">
        {isLong && !expanded ? (
          // WHY slice plain text for preview (not rendered content):
          // Slicing the raw markdown avoids breaking markdown syntax mid-tag.
          // Show plain text preview, then render full markdown when expanded.
          // WHY text-xs here (not text-sm): matches the expanded rendered content so
          // the visual density does not jump when the user clicks "Read more".
          <p className="text-xs leading-relaxed text-foreground/90">
            {preview}
            <span className="text-muted-foreground">...</span>
          </p>
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            // WHY custom link component: entity mentions are replaced with
            // markdown links ([name](/instruments/id)) above. This custom
            // renderer uses Next.js Link for client-side navigation instead
            // of a full page reload.
            components={{
              a: ({ href, children }) => (
                <Link
                  href={href ?? "#"}
                  className="text-primary hover:underline"
                >
                  {children}
                </Link>
              ),
            }}
          >
            {contentWithLinks}
          </ReactMarkdown>
        )}
      </div>

      {/* Expand/collapse toggle */}
      {isLong && (
        <button
          onClick={() => setExpanded((prev) => !prev)}
          className="mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" /> Show less
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" /> Read more
            </>
          )}
        </button>
      )}

      {/* Generated timestamp */}
      <p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
        Generated {generatedAt.toISOString().slice(0, 16).replace("T", " ")} UTC
      </p>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** escapeRegex — escape special chars in entity names for use in RegExp */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
