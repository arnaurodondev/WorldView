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
 * WHY TWO-TIER REDESIGN (PLAN-0048 Wave A):
 * The v2.2 MORNING_BRIEFING prompt now emits a ``## SUMMARY`` block (1-2
 * sentences) followed by a ``---`` divider and a ``## DETAILS`` block (the four
 * structured sections). S8 splits them apart server-side and surfaces them as
 * ``brief.summary`` and ``brief.narrative`` on the response. The card uses:
 *   - Collapsed view → ``brief.summary`` rendered at full readability (no clamp).
 *   - Expanded view → ``brief.narrative`` (the structured DETAILS sections).
 * This eliminates the 15% of vertical space the old layout wasted on
 * "Morning Briefing" / "Date:" preamble that duplicated the card chrome.
 * The previous ``stripBriefPreamble()`` helper is no longer needed because
 * the v2.2 prompt forbids those headers in the body.
 *
 * WHY TOP STORIES STRIP: The brief alone is read-only — to act on a story the
 * user must click through. Surfacing 3 chip-style links to the most relevant
 * articles in BOTH collapsed and expanded views removes a navigation step
 * (no need to expand the brief just to read the underlying article).
 *
 * WHY 503 HANDLING AS SOFT ERROR: S8 briefing endpoint returns 503 while generating.
 * A 503 → "generating" UX is better than a hard error that breaks the dashboard.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 1, col-span-12)
 * DATA SOURCE: S9 GET /api/v1/briefings/morning → S8 GET /api/v1/briefings/morning
 * DESIGN REFERENCE: PLAN-0048 Wave A, supersedes PLAN-0043 Wave A-1
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
import type { BriefingResponse, BriefingCitation } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Brief older than 12h shows a stale badge in the header */
const STALE_MS = 12 * 60 * 60 * 1000;

/**
 * Maximum number of "Top Stories" chips rendered below the summary.
 * 3 fits comfortably on one row at 11px text in the dashboard's 12-col grid
 * without forcing a wrap on standard 1440px+ trader screens. More than 3
 * starts to feel like a list and steals attention from the brief itself.
 */
const TOP_STORIES_LIMIT = 3;

/**
 * Maximum characters of an article title rendered inside a chip. Anything
 * longer is truncated with an ellipsis — keeps chips a uniform height and
 * prevents one verbose headline from monopolising the row.
 */
const CHIP_TITLE_MAX = 60;

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
  // WHY check summary OR narrative: with v2.2 split, either field can carry
  // content. As long as one is non-empty we have something to render.
  const safeNarrative = brief?.narrative?.trim() ?? "";
  const safeSummary = brief?.summary?.trim() ?? "";
  if (!brief || (!safeNarrative && !safeSummary)) {
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
  // WHY date-only format: the header is one compact line; "2026-04-28 07:14 UTC"
  // gives the trader both the date and generation time at a glance.
  const ts = generatedAt.toISOString().slice(0, 16).replace("T", " ");

  // WHY entity-name → link replacement is shared by both views: the LLM weaves
  // entity names into prose (e.g., "Apple Inc. ..."). Turning each mention into
  // a deep-link to the instrument page lets traders jump from the brief to the
  // instrument detail page without searching. Applied to BOTH summary and
  // narrative for consistent navigation behaviour.
  const linkifyEntities = (text: string): string =>
    (brief.entity_mentions ?? []).reduce((acc, mention) => {
      if (!mention.name) return acc;
      const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
      return acc.replace(regex, `[${mention.name}](/instruments/${mention.entity_id})`);
    }, text);

  // WHY two parallel pipelines: summary is the collapsed-view source and
  // narrative is the expanded-view source. Both must be linkified separately
  // so each view has working entity links. We compute both eagerly because
  // the work is cheap (string replace) and React rerenders on expand.
  const summaryWithLinks = linkifyEntities(safeSummary);
  const narrativeWithLinks = linkifyEntities(safeNarrative);

  // WHY fallback for collapsed view: when the v2.2 prompt's two-tier output
  // wasn't honored (legacy cached briefs, instrument briefs, or LLM ignored
  // the format directive), summary is null. We fall back to the narrative so
  // the collapsed card still shows *something*. The line-clamp-3 only applies
  // in this fallback branch — when summary IS present it's already short
  // enough (1-2 sentences) and clamping is unnecessary.
  const collapsedSource = summaryWithLinks || narrativeWithLinks;
  const usingSummaryFallback = !summaryWithLinks;

  // WHY isLong on narrative (not summary): the "Read more" affordance only
  // makes sense if there's substantially more content to reveal when expanded.
  // If summary == narrative (legacy fallback) we still want the toggle so the
  // user can scroll past the clamp.
  const isLong = narrativeWithLinks.length > 200;

  // ── Top Stories: chip-style article links from citations ───────────────────
  // WHY filter then slice: only "article" citations have URLs we can navigate
  // to. Events and alerts lack a destination so we exclude them from the strip.
  // The first 3 articles are already ordered by relevance from the backend.
  const topStories: BriefingCitation[] = (brief.citations ?? [])
    .filter((c) => c.source_type === "article" && c.url)
    .slice(0, TOP_STORIES_LIMIT);

  return (
    // WHY flex flex-col h-full: fills Row 1 grid cell; header is fixed h-5,
    // text area fills the rest with overflow-auto for long briefs.
    <div className="flex h-full flex-col">

      {/* ── Header row: date (left) | "Morning Briefing" (center) | CTA (right) ── */}
      {/* WHY single-line header with all three elements: the user wants the brief
          to occupy minimal vertical real estate while still being informative.
          One line of chrome (timestamp + title + action) leaves all remaining
          height for the actual brief content. */}
      <div className="flex h-5 shrink-0 items-center border-b border-border/40 px-1">
        {/* Generated timestamp — muted, monospace for scannable date/time.
            font-mono + tabular-nums keeps digit columns aligned per Midnight
            Pro convention for any numeric data.
            F-115 fix (PLAN-0048 QA iter-1): the previous 100px slot wrapped
            "2026-04-28 07:14 UTC" onto a second line, breaking the h-5
            header. We widen the slot to 152px AND restore the "Generated "
            prefix that was silently dropped during the Wave A redesign —
            the briefing.test.tsx test asserts the visible "Generated" text
            (R19 forbids deleting/weakening tests). The label also
            disambiguates the timestamp from "current UTC time" so users
            don't confuse the brief's mtime with wall-clock time. */}
        <span className="w-[152px] shrink-0 whitespace-nowrap font-mono text-[9px] tabular-nums text-muted-foreground/60">
          Generated {ts} UTC
        </span>

        {/* "Morning Briefing" title — centered in the remaining space */}
        <span className="flex-1 text-center text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          Morning Briefing
        </span>

        {/* Right side: stale badge + refresh + Read more / show less */}
        <div className="flex w-[100px] shrink-0 items-center justify-end gap-1">
          {isStale && (
            <>
              <span className="text-[9px] text-warning">stale</span>
              <button
                onClick={() => void refetch()}
                disabled={isFetching}
                className="text-muted-foreground hover:text-foreground disabled:opacity-50"
                title="Refresh morning brief"
                aria-label="Refresh morning brief"
              >
                <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
              </button>
            </>
          )}
          {/* WHY Read more in header (not text area): moving the CTA to the header
              gives users a persistent, always-visible expand action. In the old layout
              the button appeared only after the 3 content lines, making it easy to miss.
              This mirrors Bloomberg's panel-header affordance for secondary content. */}
          {isLong && !expanded && (
            <button
              onClick={() => setExpanded(true)}
              className="text-[9px] text-primary hover:underline"
              aria-label="Expand morning brief"
            >
              Read more →
            </button>
          )}
          {isLong && expanded && (
            <button
              onClick={() => setExpanded(false)}
              className="text-[9px] text-muted-foreground hover:text-foreground"
              aria-label="Collapse morning brief"
            >
              show less ↑
            </button>
          )}
        </div>
      </div>

      {/* ── Text area: flex-1 so it fills remaining Row 1 height ────────────── */}
      <div className="flex-1 overflow-auto px-1 py-0.5">
        {/* WHY shared ReactMarkdown classes: both collapsed and expanded use the
            same markdown styling so the transition between states is seamless. */}
        <div className="text-[10px] leading-snug text-foreground/90 [&_a]:text-primary [&_a]:hover:underline [&_h1]:mb-0.5 [&_h1]:text-[9px] [&_h1]:font-semibold [&_h1]:uppercase [&_h1]:tracking-[0.08em] [&_h1]:text-muted-foreground [&_h2]:mb-0 [&_h2]:mt-1.5 [&_h2]:text-[9px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.08em] [&_h2]:text-muted-foreground [&_h3]:mt-0.5 [&_h3]:text-[10px] [&_h3]:font-medium [&_li]:leading-snug [&_p]:mt-0.5 [&_strong]:font-semibold [&_ul]:mt-0.5 [&_ul]:pl-3">
          {!expanded ? (
            // ── Collapsed view: brief.summary rendered at full readability ──
            // WHY no line-clamp when summary is present: the v2.2 prompt
            // already constrains the summary to 1-2 sentences, so clamping is
            // redundant and risks hiding the second sentence. We only apply
            // line-clamp-3 in the legacy fallback branch (no summary field).
            <div
              className={
                usingSummaryFallback
                  ? "line-clamp-3 [&>*:first-child]:mt-0"
                  : "[&>*:first-child]:mt-0"
              }
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => (
                    <Link href={href ?? "#"} className="text-primary hover:underline">
                      {children}
                    </Link>
                  ),
                  // WHY render headers inline in the collapsed view: any
                  // residual ## / ### headings the LLM emits would otherwise
                  // create awkward block breaks in a 1-2 sentence summary.
                  h1: ({ children }) => <span className="font-semibold">{children} </span>,
                  h2: ({ children }) => <span className="font-semibold">{children} </span>,
                  h3: ({ children }) => <span className="font-medium">{children} </span>,
                }}
              >
                {collapsedSource}
              </ReactMarkdown>
            </div>
          ) : brief.sections && brief.sections.length > 0 ? (
            // ── Expanded view (structured): PLAN-0049 T-D-4-01 ──
            // When the backend's section parser succeeded we render polished
            // section cards instead of raw markdown — gives the brief a
            // Bloomberg-grade typographic hierarchy (heading + bullets).
            // WHY data-testid="brief-section" (PLAN-0049 T-D-4-06): the
            // stabilization E2E spec asserts that EITHER ≥1 brief-section OR
            // a brief-narrative is rendered after expansion. The marker
            // disambiguates the two branches without coupling the test to
            // class names (which churn) or section copy (LLM-dependent).
            <div className="flex flex-col gap-2">
              {brief.sections.map((sec, i) => (
                <section
                  key={`${sec.title}-${i}`}
                  className="border-l-2 border-primary/40 pl-2"
                  data-testid="brief-section"
                >
                  <h3 className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    {sec.title}
                  </h3>
                  <ul className="m-0 list-none p-0">
                    {sec.bullets.map((b, j) => (
                      <li
                        key={j}
                        className="relative pl-2 text-[10px] leading-snug text-foreground/90 before:absolute before:left-0 before:top-1.5 before:h-[3px] before:w-[3px] before:rounded-full before:bg-primary/60"
                      >
                        {b}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          ) : (
            // ── Expanded view (fallback): brief.narrative as raw markdown ──
            // Used when sections[] is empty (parser couldn't structure the
            // narrative) — same look as before PLAN-0049.
            // WHY data-testid="brief-narrative" (T-D-4-06): see the section
            // marker above for the rationale.
            <div data-testid="brief-narrative">
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
                {narrativeWithLinks}
              </ReactMarkdown>
            </div>
          )}

          {/* ── Top Stories chip strip ─────────────────────────────────────
              Rendered in BOTH collapsed and expanded views (per A-3 spec) so
              the user can jump to the underlying article without expanding
              the brief first. Hidden when there are no article citations to
              avoid an empty row of chrome. */}
          {topStories.length > 0 && (
            <div
              className="mt-1.5 flex flex-wrap gap-1 border-t border-border/40 pt-1.5"
              aria-label="Top stories"
            >
              {topStories.map((story) => (
                <Link
                  key={story.source_id}
                  href={story.url ?? "#"}
                  // WHY target=_blank: news article URLs go to external
                  // publishers — opening in a new tab keeps the dashboard
                  // visible while the trader reads the full story.
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-[260px] items-center gap-1 rounded border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                  title={story.title}
                >
                  {/* Source domain — small uppercase label so the user can
                      tell at a glance whether the chip points to e.g.
                      Bloomberg vs. Reuters before they click. */}
                  <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/70">
                    {extractDomain(story.url ?? "")}
                  </span>
                  {/* Title truncated by a JS slice (CSS ellipsis on flex
                      children is fragile inside a flex-wrap row). */}
                  <span className="truncate">{truncate(story.title, CHIP_TITLE_MAX)}</span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

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
 * extractDomain — pull a short host label from a full article URL.
 *
 * WHY: chips display the source ("BLOOMBERG.COM", "REUTERS.COM") so the
 * trader can prioritise sources at a glance. We strip the leading "www." for
 * compactness; everything else (subdomains like "finance.yahoo.com") is kept
 * to disambiguate sub-properties.
 *
 * Returns "source" as a fallback when the URL is malformed — never throws,
 * because a thrown URL parse error would crash the dashboard cell.
 */
function extractDomain(url: string): string {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host.startsWith("www.") ? host.slice(4) : host;
  } catch {
    return "source";
  }
}

/**
 * truncate — clip a string to ``max`` characters with a trailing ellipsis.
 *
 * WHY in JS not CSS: the chip lives inside a flex-wrap container, where CSS
 * text-overflow:ellipsis is unreliable (relies on a fixed parent width).
 * Slicing in JS guarantees a stable visual length across all chip widths.
 */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  // Trim trailing whitespace before appending the ellipsis so we never get
  // "Foo bar …" with a space gap.
  return text.slice(0, max).trimEnd() + "…";
}
