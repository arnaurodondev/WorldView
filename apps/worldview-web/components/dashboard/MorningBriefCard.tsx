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

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
// PLAN-0059 G-2: dashboard is the home route, so its initial bundle is the
// most cost-sensitive in the app. react-markdown + remark-gfm + the GFM
// plugins together push ~150KB gz that ONLY matters when this card is on
// screen. Dynamic-import them so the dashboard chrome paints first; the
// brief content streams in after the markdown bundle resolves.
//
// remarkGfm is configured at module scope below so the dynamic ReactMarkdown
// can pass it as `remarkPlugins`. It's a tiny module — no point lazy-loading.
import dynamic from "next/dynamic";
import remarkGfm from "remark-gfm";
// PLAN-0062-W4 T-W4-E-01: StructuredBrief replaces the inline brief.sections.map
// block in the expanded view. This shared component handles BriefBullet citation
// chips, confidence badge, and variant-specific layout so MorningBriefCard only
// needs to decide WHEN to show the structured view (sections non-empty) vs the
// markdown fallback (sections empty or absent).
import { StructuredBrief } from "@/components/brief/StructuredBrief";
// Roadmap 2026-06-19 Top-8 #8 / C3 ("Cited, structured Morning Briefing"):
// promote the COLLAPSED view from a prose blob to a scannable, cited catalyst
// preview when the backend parsed the brief into `sections`. The preview shows
// the top sections' catalyst bullets each with inline source chips + a
// best-effort affected-ticker pill. When `sections` is empty (the live v4.x
// reality) the card keeps the prose summary fallback below.
import { BriefCatalystPreview } from "@/components/dashboard/BriefCatalystPreview";
// PLAN-0066 Wave F: diff badge (amber pill), "Discuss in Chat" button (hook),
// and brief-level rating widget all added to the card.
import { BriefDiffBadge } from "@/features/dashboard/components/BriefDiffBadge";
import { BriefRating } from "@/features/dashboard/components/BriefRating";
import { useBriefChatSeed } from "@/features/dashboard/hooks/useBriefChatSeed";

// QA-iter1: hoist remark plugins to module scope. Inline `[remarkGfm]`
// passed as a prop creates a NEW array reference on every render, which
// re-triggers react-markdown's full remark pipeline on every parent
// re-render (expand toggle, isFetching flip). Module-scope const = stable
// reference, single pipeline run per content change.
const REMARK_PLUGINS = [remarkGfm];

// QA-iter1: brief 5-line skeleton shown while the dynamic react-markdown
// bundle resolves (~50–200ms first load). Without this, the card chrome
// paints first and the brief surface is silent until the bundle lands —
// SR users hear nothing during the gap.
function BriefMarkdownSkeleton() {
  return (
    <div
      className="space-y-1.5 px-1 pt-1"
      aria-busy="true"
      aria-label="Loading brief"
    >
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-3 rounded-[2px] bg-muted/40"
          style={{
            width: i === 4 ? "66%" : "100%",
          }}
        />
      ))}
    </div>
  );
}

const ReactMarkdown = dynamic(() => import("react-markdown"), {
  ssr: false,
  loading: () => <BriefMarkdownSkeleton />,
});
import { ChevronRight, ChevronUp, FileText, RefreshCw } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): the no-brief named empty state migrates onto the shared
// EmptyState primitive (§15.12) — icon + action props landed in Round 2, so
// the bespoke icon/headline/CTA block here became a duplicate of it.
import { EmptyState } from "@/components/primitives/EmptyState";
// DESIGN-QA D-1 "Skeletons that never resolve": cap how long this card may
// show its loading skeleton. After the budget the skeleton yields to the
// designed empty/unavailable state so the dashboard hero never spins forever
// when S8's briefing endpoint hangs (rather than 503-ing cleanly).
import { useSkeletonTimeout } from "@/components/dashboard/useSkeletonTimeout";
// WHY import BriefingResponse (not MorningBrief): PLAN-0034 unified the briefing
// response type — both morning and instrument briefs now return BriefingResponse
// which includes citations, risk_summary, and cached flag.
// WHY also import BriefCitation and BriefingCitation: PLAN-0062-W4 changed the
// citations array to emit BriefCitation objects (with document_id). We keep the
// BriefingCitation import for the legacy back-compat filter in topStories below.
import type { BriefingResponse, BriefCitation, BriefingCitation } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Brief older than 12h shows a stale badge in the header */
const STALE_MS = 12 * 60 * 60 * 1000;

/**
 * Freshness thresholds for the header status dot (roadmap #8: "a subtle
 * freshness indicator"). The dot encodes how recently the brief was generated:
 *   - FRESH (< 4h)   → positive/green: today's brief, current.
 *   - AGING (4h-12h) → warning/amber: still today's but several hours old.
 *   - STALE (> 12h)  → negative/red: matches the existing STALE_MS "stale"
 *     badge so the dot and the badge agree.
 * WHY a static dot (no animation): DESIGN_SYSTEM.md §15.11 — status dots never
 * pulse (Bloomberg convention); color alone encodes freshness.
 */
const FRESH_MS = 4 * 60 * 60 * 1000;

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
  // PLAN-0066 Wave F T-W10-F-02: "Discuss in Chat" button hook.
  // The hook returns a `discuss` callback + loading/error state.
  const { discuss, loading: discussLoading, error: discussError } = useBriefChatSeed(accessToken ?? undefined);

  // FR-1.4: useQueryClient for midnight UTC invalidation scheduling.
  // WHY useQueryClient here (not at module level): hooks must be called inside
  // a component function — useQueryClient grabs the client from React context.
  const queryClient = useQueryClient();

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
    // Round 1 foundation: the named empty state shows a "last attempt"
    // timestamp. TanStack exposes both — dataUpdatedAt is the last SUCCESSFUL
    // fetch (which may still carry an empty brief body), errorUpdatedAt the
    // last FAILED one. The max of the two is "when we last heard from S8".
    dataUpdatedAt,
    errorUpdatedAt,
  } = useQuery<BriefingResponse>({
    queryKey: ["morning-brief"],
    queryFn: () => createGateway(accessToken).getMorningBrief(),
    enabled: !!accessToken,
    // WHY staleTime 12h (was 30min): morning briefs are generated once per day.
    // A 30-minute window caused unnecessary refetches during a single session;
    // 12 hours matches the generation cadence and prevents redundant round-trips
    // while still refreshing when the user returns for an afternoon session.
    staleTime: 12 * 60 * 60 * 1000,
    // WHY retry: S8 briefing may be generating; retry up to 2x with 10s delay
    retry: 2,
    retryDelay: 10_000,
  });

  // FR-1.4: Schedule a one-shot cache invalidation at the next 00:00 UTC so
  // the brief refreshes automatically when a new one is generated at midnight.
  // WHY setTimeout (not setInterval): we only need a single invalidation; the
  // subsequent render after invalidation will re-enter this effect and schedule
  // the next night's timer. WHY 00:00 UTC specifically: S8 generates briefs at
  // midnight UTC — invalidating at that moment ensures the next query hits the
  // fresh brief rather than serving the previous day's cached response.
  useEffect(() => {
    const now = new Date();
    const nextMidnightUTC = new Date();
    // setUTCHours(24, 0, 0, 0) rolls over to the next day's midnight
    nextMidnightUTC.setUTCHours(24, 0, 0, 0);
    const msUntilMidnight = nextMidnightUTC.getTime() - now.getTime();

    const timer = setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: ["morning-brief"] });
    }, msUntilMidnight);

    // WHY cleanup: if the component unmounts before midnight (e.g. the user
    // navigates away), cancel the timer so we don't call invalidateQueries
    // on an unmounted component's stale queryClient reference.
    return () => clearTimeout(timer);
  }, [queryClient]);

  // DESIGN-QA D-1: once the loading skeleton has shown for longer than the
  // max-wait budget we stop trusting `isLoading` and let the render fall
  // through to the settled branches below (error if the query errored, else
  // the "AI brief unavailable" empty state). If the brief still arrives later,
  // TanStack flips isLoading→false, this resets, and the real brief renders.
  const skeletonTimedOut = useSkeletonTimeout(isLoading);

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading && !skeletonTimedOut) {
    return (
      // WHY flex flex-col h-full: component must fill its grid cell height so
      // Row 1 height is driven by the cell, not by the brief content length.
      // Round 4 (item 2): role="region" + aria-label on every return branch —
      // the landmark must exist from first paint for SR panel navigation.
      <div className="flex h-full flex-col" role="region" aria-label="Morning briefing">
        {/* Placeholder header so height matches the loaded state.
            Round 3 (item 3): h-6 — the LOADED header grew to 24px in the
            2026-05-09 density bundle but this placeholder stayed at 20px,
            so the whole Row-1 card shifted 4px when the brief arrived. */}
        <div className="flex h-6 shrink-0 items-center border-b border-border/40 px-1">
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
      <div className="flex h-full flex-col" role="region" aria-label="Morning briefing">
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
            className="ml-auto text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))]"
            title="Retry"
            aria-label="Retry loading brief"
          >
            {/* WHY strokeWidth={1.5}: terminal icon convention — thinner strokes match 11px data density; default 2px looks heavy at h-3 w-3 */}
            <RefreshCw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} strokeWidth={1.5} />
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
  //
  // Density bundle 2026-05-09 — markdown asterisk leak fix.
  // The LLM occasionally emits stale-data metadata as Markdown emphasis,
  // e.g. ``*(as of 2026-05-09)*``. ReactMarkdown SHOULD render this as
  // ``<em>(as of …)</em>``, but two failure modes leak literal asterisks:
  //   1. The opening ``*`` is followed immediately by ``(`` and remark-gfm
  //      flanking rules sometimes refuse to treat it as emphasis (left flank
  //      must be a non-punctuation character).
  //   2. The metadata is a parenthetical aside that adds noise to the brief
  //      summary even when it DOES render correctly — analysts don't need a
  //      visible "as of" timestamp because the card header already shows
  //      "Generated YYYY-MM-DD HH:MM UTC".
  // Strip these inline metadata wrappers entirely BEFORE feeding the markdown
  // to ReactMarkdown so neither failure mode is visible. Match shapes:
  //   - ``*(as of 2026-05-09)*`` (asterisk-italic)
  //   - ``_(as of 2026-05-09)_`` (underscore-italic)
  //   - ``(as of 2026-05-09)``   (no emphasis at all — also redundant)
  function stripStaleMetadata(text: string): string {
    return text
      // Remove ``*(...)*`` and ``_(...)_`` parenthetical italic asides.
      .replace(/[*_]\((?:as of|updated)[^)]*\)[*_]/gi, "")
      // Remove the same content without surrounding emphasis markers.
      .replace(/\((?:as of|updated)[^)]*\)/gi, "")
      // Collapse any double-spaces left by the removal so paragraphs reflow.
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  }

  // User report 2026-06-14: the live v4.x morning brief leaks cryptic inline
  // citation markers — uppercase ``[N2]``, ``[N10]``, ``[N12]`` — into the
  // narrative/summary text (e.g. "…unwind $2B Manus deal after Beijing's
  // demand [N2]"). Users have no idea what "[N2]" means, and unlike the chat
  // surface there is NO inline footnote index on the dashboard that maps N→
  // article (provenance is served instead by the "Top Stories" chip strip and
  // the StructuredBrief per-bullet citation chips). So these markers are pure
  // visual noise here — STRIP them.
  //
  // WHY this also lives in MorningBriefCard (not only StructuredBrief): the
  // live v4.x morning brief returns its whole body in ``narrative`` with an
  // EMPTY ``sections[]``, so the card renders the raw markdown via ReactMarkdown
  // (collapsed + narrative-fallback paths) and NEVER goes through StructuredBrief
  // — which is the only place that previously stripped ``[N#]``. That left the
  // markers leaking on the dashboard. Mirror the same strip the LeadProse /
  // BriefBulletItem renderers in StructuredBrief.tsx already apply.
  //
  // WHY ``\[c?\d+\]`` (digits only): real content-bearing brackets the brief
  // legitimately emits — date ranges like ``[2026-06-30]`` (contains ``-``) and
  // freshness tags like ``[Q stale]`` (contains a space) — do NOT match
  // ``[<optional c/N><digits>]`` and are therefore preserved untouched.
  function stripCitationMarkers(text: string): string {
    return text
      // ``[cN]`` (v3.0 marker form) and ``[N#]`` (v4.0+ marker form). The
      // leading ``\s*`` eats the space before the marker so "demand [N2]"
      // collapses cleanly to "demand".
      .replace(/\s*\[(?:c|N)\d+\]/g, "")
      // Collapse any double-spaces left between two now-removed markers.
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  }

  // W4 fix (user report 2026-06-12): the live v4.2 morning brief returns its
  // whole body in `narrative` as markdown — `summary`/`summary_paragraph` and
  // the structured `sections[]` are all empty (the backend's citation-aware
  // parser only structures briefs that carry a `---` divider + [cN] markers,
  // which the v4.2 prompt no longer emits). So the card was falling back to the
  // raw narrative and showing literal "## Details" / "**Market Snapshot**"
  // chrome. We strip the redundant top-level "## Details" wrapper heading here
  // (the card already labels itself "Morning Briefing"; the wrapper just adds a
  // noisy "Details" line) BEFORE any rendering. The inner "**Market Snapshot**"
  // etc. section headings are KEPT — they render as clean uppercase sub-heads
  // via the prose overrides below, which is exactly the structured look we want.
  function stripDetailsWrapper(text: string): string {
    // Remove a standalone "## Details" / "# Details" / "### Details" heading
    // line (case-insensitive, optional trailing colon) anywhere in the first
    // few lines — it's the v4.2 prompt's wrapper around the 6 real sections.
    return text
      .replace(/^\s*#{1,3}\s*details\s*:?\s*$/gim, "")
      // Collapse the blank line the removal leaves at the top so the first real
      // section heading sits flush.
      .replace(/^\s*\n/, "")
      .trim();
  }

  // Strip order: citation markers FIRST (so "demand [N2] ." → "demand ."),
  // then the stale-metadata / details-wrapper cleanups, which already collapse
  // residual double-spaces. Applied to all three text sources because any of
  // them can carry the leaked [N#] markers depending on the brief format.
  const safeNarrative = stripDetailsWrapper(
    stripStaleMetadata(stripCitationMarkers(brief?.narrative?.trim() ?? "")),
  );
  const safeSummary = stripStaleMetadata(
    stripCitationMarkers(brief?.summary?.trim() ?? ""),
  );
  const safeSummaryParagraph = stripStaleMetadata(
    stripCitationMarkers(brief?.summary_paragraph?.trim() ?? ""),
  );
  if (!brief || (!safeNarrative && !safeSummary && !safeSummaryParagraph)) {
    // Round 1 foundation: NAMED empty state — icon + headline + last-attempt
    // timestamp + Regenerate action — replaces the bare one-liner.
    //
    // WHY "last attempt" from query timestamps (not brief.generated_at): in
    // this branch there IS no usable brief — the only truthful timestamps we
    // have are when the frontend last asked S8 for one. dataUpdatedAt covers
    // "S8 answered but the brief body was empty"; errorUpdatedAt covers
    // "the request failed". 0 means "never attempted in this session".
    const lastAttemptMs = Math.max(dataUpdatedAt ?? 0, errorUpdatedAt ?? 0);
    // Same compact "YYYY-MM-DD HH:MM" format as the loaded-state header so
    // timestamps read consistently across card states.
    const lastAttempt =
      lastAttemptMs > 0
        ? new Date(lastAttemptMs).toISOString().slice(0, 16).replace("T", " ")
        : null;

    return (
      <div className="flex h-full flex-col" role="region" aria-label="Morning briefing">
        <MetaHeader />
        {/* Round 3 (item 4): shared EmptyState primitive — it owns the icon
            treatment, role="status" announcement and title/body layout that
            this card previously hand-rolled. Copy key dashboard.brief-
            unavailable keeps the exact "AI brief unavailable" headline the
            regression tests pin (R19). The action slot carries BOTH the
            last-attempt timestamp and the Regenerate button (it accepts any
            ReactNode — position below the body is all the primitive owns). */}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.brief-unavailable"
            icon={FileText}
            action={
              <div className="flex flex-col items-center gap-1">
                {/* Last-attempt timestamp — only when we actually attempted.
                    9px is allowed here: it is a timestamp, not a data value
                    (§15.9 exception list). */}
                {lastAttempt && (
                  <p className="font-mono text-[9px] tabular-nums text-muted-foreground-dim">
                    Last attempt {lastAttempt} UTC
                  </p>
                )}
                {/* Regenerate — WHY refetch() (GET /v1/briefings/morning) and
                    not a dedicated POST: S9/S8 expose no explicit morning-brief
                    regenerate endpoint (backend gap — only instrument briefs
                    have POST /briefings/instrument/{id}/generate). The morning
                    GET itself triggers S8's background regeneration when the
                    cached brief is stale/absent, so a refetch IS the closest
                    available "regenerate" action today.
                    Round 3 (item 5): hover bg + keyboard focus ring added. */}
                <button
                  onClick={() => void refetch()}
                  disabled={isFetching}
                  className="mt-0.5 inline-flex items-center gap-1 px-1.5 font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-muted hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:text-[hsl(var(--disabled-foreground))]"
                  aria-label="Regenerate morning brief"
                >
                  <RefreshCw
                    className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`}
                    strokeWidth={1.5}
                  />
                  {isFetching ? "Regenerating…" : "Regenerate"}
                </button>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  // ── Content rendering ──────────────────────────────────────────────────────
  const generatedAt = new Date(brief.generated_at);
  const ageMs = Date.now() - generatedAt.getTime();
  const isStale = ageMs > STALE_MS;

  // Roadmap #8 freshness indicator: a single static dot whose color encodes
  // how old the brief is. The three tiers agree with the existing "stale"
  // badge (>12h) so the dot and badge never contradict each other.
  // WHY Tailwind token classes (text-positive / text-warning / text-negative)
  // and NOT inline `hsl(var(--positive))`: globals.css defines the semantic
  // colors only as Tailwind utilities; an inline `var()` compiles but paints
  // nothing (DESIGN_SYSTEM.md §F-VISUAL-001 / the "no-paint" bug class).
  const freshness: { dotClass: string; label: string } =
    ageMs <= FRESH_MS
      ? { dotClass: "text-positive", label: "Fresh — generated within 4h" }
      : ageMs <= STALE_MS
        ? { dotClass: "text-warning", label: "Aging — generated 4-12h ago" }
        : { dotClass: "text-negative", label: "Stale — generated over 12h ago" };
  // WHY date-only format: the header is one compact line; "2026-04-28 07:14 UTC"
  // gives the trader both the date and generation time at a glance.
  const ts = generatedAt.toISOString().slice(0, 16).replace("T", " ");

  // WHY entity-name → link replacement is shared by both views: the LLM weaves
  // entity names into prose (e.g., "Apple Inc. ..."). Turning each mention into
  // a deep-link to the instrument page lets traders jump from the brief to the
  // instrument detail page without searching. Applied to BOTH summary and
  // narrative for consistent navigation behaviour.
  // WHY ?? []: entity_mentions is now optional in BriefingResponse (PLAN-0062-W4).
  // The field may be absent in W4+ responses that don't populate it.
  const linkifyEntities = (text: string): string =>
    (brief.entity_mentions ?? []).reduce((acc, mention) => {
      if (!mention.name) return acc;
      const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
      // PRD-0089 F2 §6.6: prefer ticker-first URLs (`/instruments/AAPL`) when
      // the mention carries a ticker; fall back to the UUID form for entities
      // without a ticker (e.g. private companies, macro topics).
      const slug = (mention as { ticker?: string | null }).ticker ?? mention.entity_id;
      return acc.replace(regex, `[${mention.name}](/instruments/${slug})`);
    }, text);

  // WHY two parallel pipelines: summary is the collapsed-view source and
  // narrative is the expanded-view source. Both must be linkified separately
  // so each view has working entity links. We compute both eagerly because
  // the work is cheap (string replace) and React rerenders on expand.
  const summaryParagraphWithLinks = linkifyEntities(safeSummaryParagraph);
  const summaryWithLinks = linkifyEntities(safeSummary);
  const narrativeWithLinks = linkifyEntities(safeNarrative);

  // WHY 3-tier fallback for collapsed view (PLAN-0103 W3 / BP-624 recovery):
  // The v4.2 backend emits a landscape `summary_paragraph` that is the
  // preferred collapsed-view source. When absent (legacy cached briefs,
  // instrument briefs, or v2.2-format briefs), fall back to `summary`, then
  // to `narrative` so the card always renders *something*. The clamp-3 only
  // applies in the narrative-fallback branch — when summary_paragraph or
  // summary is present it's already short enough.
  const collapsedSource =
    summaryParagraphWithLinks || summaryWithLinks || narrativeWithLinks;
  const usingSummaryFallback =
    !summaryParagraphWithLinks && !summaryWithLinks;

  // WHY isLong on narrative (not summary): the "Read more" affordance only
  // makes sense if there's substantially more content to reveal when expanded.
  // If summary == narrative (legacy fallback) we still want the toggle so the
  // user can scroll past the clamp.
  const isLong = narrativeWithLinks.length > 200;

  // ── Top Stories: chip-style article links from citations ───────────────────
  // WHY filter then slice: only "article" citations have URLs we can navigate
  // to. Events and alerts lack a destination so we exclude them from the strip.
  // The first 3 articles are already ordered by relevance from the backend.
  //
  // WHY cast to (BriefCitation | BriefingCitation): the citations array is a
  // union type after PLAN-0062-W4 — W4+ responses emit BriefCitation (with
  // document_id); pre-W4 cached responses emit BriefingCitation (with source_id).
  // Both shapes share source_type, title, and url — the only fields this strip uses.
  const topStories: (BriefCitation | BriefingCitation)[] = (brief.citations ?? [])
    .filter((c) => c.source_type === "article" && c.url)
    .slice(0, TOP_STORIES_LIMIT);

  // ── Structured collapsed preview gating (roadmap #8 / C3) ──────────────────
  // WHY: the collapsed view defaulted to a prose blob (summary_paragraph). When
  // the backend parsed the brief into `sections` we instead render a scannable,
  // CITED catalyst preview (BriefCatalystPreview) so the structure + sources
  // are visible WITHOUT clicking "Read more". When `sections` is empty (the
  // live v4.x reality, where the whole body arrives as `narrative`) we keep the
  // prose fallback. Filter REMOVED placeholder sections the LLM occasionally
  // emits — same guard the expanded StructuredBrief path uses.
  const previewSections =
    brief.sections?.filter((s) => !s.title?.toUpperCase().includes("REMOVED")) ?? [];
  // Render the structured preview only when at least one section carries a
  // bullet — otherwise BriefCatalystPreview would return null and we'd show an
  // empty card body. The lead/summary line still renders above the preview.
  const useStructuredCollapsed = previewSections.some(
    (s) => (s.bullets?.length ?? 0) > 0,
  );

  return (
    // WHY flex flex-col h-full: fills Row 1 grid cell; header is fixed h-5,
    // text area fills the rest with overflow-auto for long briefs.
    <div className="flex h-full flex-col" role="region" aria-label="Morning briefing">

      {/* ── Header row: date (left) | "Morning Briefing" (center) | CTA (right) ── */}
      {/* WHY single-line header with all three elements: the user wants the brief
          to occupy minimal vertical real estate while still being informative.
          One line of chrome (timestamp + title + action) leaves all remaining
          height for the actual brief content.
          Density bundle 2026-05-09 — h-5 (20px) → h-6 (24px). The 20px row was
          too short to host the BriefDiffBadge ("7 new" amber pill, ~18px tall
          including padding) which visibly overflowed above the card border.
          24px gives the pill room to sit centered without clipping. */}
      <div className="flex h-6 shrink-0 items-center border-b border-border/40 px-1">
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
        <span className="flex min-w-[120px] max-w-[148px] shrink-0 items-center gap-1 whitespace-nowrap font-mono text-[9px] tabular-nums text-muted-foreground-dim">
          {/* Roadmap #8 freshness dot — static (never pulses); color encodes
              how recently the brief was generated. title= gives the human
              tier label on hover; aria-label exposes it to assistive tech. */}
          <span
            className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-current ${freshness.dotClass}`}
            title={freshness.label}
            aria-label={freshness.label}
            role="img"
            data-testid="brief-freshness-dot"
          />
          Generated {ts} UTC
        </span>

        {/* "Morning Briefing" title — centered in the remaining space */}
        {/* Round 3 (item 1): 9px → 10px — aligns the card title with the
            dashboard-wide widget-header treatment (10px tracked uppercase). */}
        <span className="flex-1 text-center text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          Morning Briefing
        </span>

        {/* ── Right action strip: diff badge · Discuss · stale/refresh · expand ── */}
        {/* SA-2 PLAN-0088 Demo P1: polish pass — gap-1.5 (was gap-1) for better
            breathing room between actions; RefreshCw icon now inline-flex centered;
            Discuss and Read more labels are styled consistently at text-[9px].
            WHY w-[220px] (was 200px): added 20px to accommodate the new gap and
            prevent the Discuss label from wrapping on "Opening…" text. */}
        <div className="flex w-[220px] shrink-0 items-center justify-end gap-1.5">
          {/* PLAN-0066 Wave F T-W10-F-01: diff badge — amber pill showing new bullets */}
          {/* WHY brief.id ?? generated_at as briefId: prefer the DB id (PLAN-0066 Wave A
              adds it to PublicBriefingResponse). Fall back to generated_at so the diff
              cache is still invalidated when a new brief is generated (new timestamp),
              even for cached responses that don't yet carry the id field. */}
          <BriefDiffBadge
            token={accessToken ?? undefined}
            briefId={brief.id ?? brief.generated_at}
          />

          {/* PLAN-0066 Wave F T-W10-F-02: "Discuss in Chat" button */}
          {/* WHY only when not loading: avoids showing "Discuss" during the POST */}
          <button
            onClick={() => void discuss()}
            disabled={discussLoading}
            title={discussError ?? "Open a chat thread seeded with this brief"}
            aria-label="Discuss this brief in chat"
            className="whitespace-nowrap text-[9px] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:text-[hsl(var(--disabled-foreground))]"
          >
            {discussLoading ? "Opening…" : "Discuss"}
          </button>

          {isStale && (
            <>
              <span className="text-[9px] text-warning/80">stale</span>
              {/* WHY inline-flex items-center: ensures the RefreshCw icon is
                  vertically centered within the 24px header row — without it the
                  icon floats 1-2px high on some font-stack configurations. */}
              <button
                onClick={() => void refetch()}
                disabled={isFetching}
                className="inline-flex items-center text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:text-[hsl(var(--disabled-foreground))]"
                title="Refresh morning brief"
                aria-label="Refresh morning brief"
              >
                {/* WHY strokeWidth={1.5}: terminal icon convention */}
                <RefreshCw
                  className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`}
                  strokeWidth={1.5}
                />
              </button>
            </>
          )}

          {/* WHY Read more / show less in header: always-visible expand CTA.
              Bloomberg panel-header affordance for secondary content. */}
          {isLong && !expanded && (
            <button
              onClick={() => setExpanded(true)}
              className="inline-flex items-center gap-0.5 whitespace-nowrap text-[9px] text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              aria-label="Expand morning brief"
            >
              Read more <ChevronRight className="h-3 w-3 shrink-0" strokeWidth={1.5} />
            </button>
          )}
          {isLong && expanded && (
            <button
              onClick={() => setExpanded(false)}
              className="inline-flex items-center gap-0.5 whitespace-nowrap text-[9px] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              aria-label="Collapse morning brief"
            >
              show less <ChevronUp className="h-3 w-3 shrink-0" strokeWidth={1.5} />
            </button>
          )}
        </div>
      </div>

      {/* ── Text area: flex-1 so it fills remaining Row 1 height ────────────── */}
      <div className="flex-1 overflow-auto px-1 py-0.5">
        {/* WHY shared ReactMarkdown classes: both collapsed and expanded use the
            same markdown styling so the transition between states is seamless. */}
        {/* WHY prose overrides: ReactMarkdown default styles use browser defaults — h2 at 1.5em
            (~21px), paragraph margin-bottom 16px. On a terminal card these create blog-like
            spacing that breaks data density. These overrides enforce 10-11px headers, 1.4
            line-height, and tight paragraph margins matching Bloomberg briefing panels. */}
        <div className="text-[10px] leading-snug text-foreground/90 [&_a]:text-primary [&_h1]:mb-0.5 [&_h1]:text-[9px] [&_h1]:font-semibold [&_h1]:uppercase [&_h1]:tracking-[0.08em] [&_h1]:text-muted-foreground [&_h2]:mb-0.5 [&_h2]:mt-2 [&_h2]:text-[10px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.08em] [&_h2]:text-muted-foreground [&_h3]:mb-0.5 [&_h3]:text-[10px] [&_h3]:font-semibold [&_h3]:uppercase [&_h3]:tracking-[0.06em] [&_h3]:text-muted-foreground [&_li]:leading-[1.4] [&_li]:text-[11px] [&_p]:mb-1 [&_p]:leading-[1.4] [&_strong]:font-semibold [&_ul]:mb-1 [&_ul]:pl-3">
          {!expanded ? (
            // ── Collapsed view ─────────────────────────────────────────────
            // Roadmap #8 / C3: when the backend parsed the brief into
            // `sections`, render a STRUCTURED, CITED catalyst preview — the top
            // sections' bullets each with inline source chips + a best-effort
            // affected-ticker pill — instead of the prose blob. The 1-2
            // sentence lead/summary still renders above it for the 10-second
            // synthesis. When sections are empty (the live v4.x reality, whole
            // body in `narrative`) we keep the original prose-markdown path.
            useStructuredCollapsed ? (
              <div className="flex flex-col gap-1.5 [&>*:first-child]:mt-0">
                {/* Lead / summary synthesis line above the catalysts. WHY
                    ReactMarkdown: collapsedSource carries entity deep-links
                    produced by linkifyEntities() (markdown anchors). */}
                {collapsedSource && (
                  <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                    <ReactMarkdown
                      remarkPlugins={REMARK_PLUGINS}
                      components={{
                        a: ({ href, children }) => (
                          <Link href={href ?? "#"} className="text-primary">
                            {children}
                          </Link>
                        ),
                        // Collapse residual headings to inline emphasis so a
                        // stray ## doesn't break the 1-2 sentence synthesis.
                        h1: ({ children }) => <span className="font-semibold">{children} </span>,
                        h2: ({ children }) => <span className="font-semibold">{children} </span>,
                        h3: ({ children }) => <span className="font-medium">{children} </span>,
                      }}
                    >
                      {collapsedSource}
                    </ReactMarkdown>
                  </div>
                )}
                {/* The structured, cited catalyst preview. */}
                <BriefCatalystPreview
                  sections={previewSections}
                  mentions={brief.entity_mentions ?? []}
                />
              </div>
            ) : (
              // ── Collapsed prose fallback (sections empty) ────────────────
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
                  remarkPlugins={REMARK_PLUGINS}
                  components={{
                    a: ({ href, children }) => (
                      <Link href={href ?? "#"} className="text-primary">
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
            )
          ) : brief.sections && brief.sections.length > 0 ? (
            // ── Expanded view (structured): PLAN-0062-W4 T-W4-E-01 ──
            // WHY render the summary above the structured view: the v4.2+
            // prompt produces a ``## Summary`` paragraph that is the single
            // best 10-second synthesis of the brief. Previously the expanded
            // view jumped straight to the 6 sections, so a user clicking
            // "Read more" *lost* the summary they had been reading in the
            // collapsed card. Keeping the summary visible at the top of the
            // expanded view preserves context, matches the v4.x design
            // (Summary + Details), and adds no extra height when summary is
            // null (legacy/cached briefs).
            // We render the summary via ReactMarkdown (not StructuredBrief.lead)
            // because (a) brief.lead is the v3.0 LEAD field which is distinct
            // from v4.x summary, and (b) summary may contain markdown links
            // produced by linkifyEntities() above.
            <>
              {summaryWithLinks && (
                <div className="mb-2 border-b border-border/40 pb-2 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                  <ReactMarkdown
                    remarkPlugins={REMARK_PLUGINS}
                    components={{
                      a: ({ href, children }) => (
                        <Link href={href ?? "#"} className="text-primary">
                          {children}
                        </Link>
                      ),
                    }}
                  >
                    {summaryWithLinks}
                  </ReactMarkdown>
                </div>
              )}
            {/* StructuredBrief renders the shared bullet/citation/confidence layout;
                variant=full = expanded card view; data-testid emitted by the component
                satisfies the PLAN-0049 T-D-4-06 E2E assertion. PLAN-0066 Wave F adds
                briefId+token for BulletFeedback widgets (briefId null/undefined disables).
                Filtering out LLM REMOVED placeholder sections is a prompt-quirk workaround. */}
            <StructuredBrief
              lead={brief.lead}
              sections={
                // WHY toUpperCase(): match any case variant ("removed", "Removed", "REMOVED")
                brief.sections?.filter(
                  (s) => !s.title?.toUpperCase().includes("REMOVED")
                ) ?? []
              }
              confidence={brief.confidence}
              variant="full"
              briefId={brief.id ?? undefined}
              token={accessToken ?? undefined}
            />
            </>
          ) : (
            // ── Expanded view (fallback): brief.narrative as raw markdown ──
            // Used when sections[] is empty (parser couldn't structure the
            // narrative) — same look as before PLAN-0049, plus the summary
            // header so the user keeps the synthesis context they were
            // reading in the collapsed view (see structured branch above for
            // the rationale).
            // WHY data-testid="brief-narrative" (T-D-4-06): see the section
            // marker above for the rationale.
            <div data-testid="brief-narrative">
              {summaryWithLinks && (
                <div className="mb-2 border-b border-border/40 pb-2 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                  <ReactMarkdown
                    remarkPlugins={REMARK_PLUGINS}
                    components={{
                      a: ({ href, children }) => (
                        <Link href={href ?? "#"} className="text-primary">
                          {children}
                        </Link>
                      ),
                    }}
                  >
                    {summaryWithLinks}
                  </ReactMarkdown>
                </div>
              )}
              <ReactMarkdown
                remarkPlugins={REMARK_PLUGINS}
                components={{
                  a: ({ href, children }) => (
                    <Link href={href ?? "#"} className="text-primary">
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
          {/* PLAN-0066 Wave F T-W10-F-03: BriefRating — 5-star rating shown in expanded view.
              WHY only when expanded: the rating widget is a post-read action (the trader
              rates AFTER reading the full brief). Showing it in the collapsed view would
              prompt rating without context. WHY brief.id guard: feedback requires the DB id
              to POST to /api/v1/briefings/feedback/brief. Without it, BriefRating is hidden. */}
          {expanded && brief.id && (
            <div className="mt-2 border-t border-border/40 pt-2">
              <BriefRating token={accessToken ?? undefined} briefId={brief.id} />
            </div>
          )}

          {topStories.length > 0 && (
            <div
              className="mt-1.5 flex flex-wrap gap-1 border-t border-border/40 pt-1.5"
              aria-label="Top stories"
            >
              {topStories.map((story) => (
                <Link
                  // WHY back-compat key: W4+ BriefCitation has `document_id`;
                  // pre-W4 BriefingCitation has `source_id`. Use whichever is
                  // populated, falling back to title as a last resort.
                  key={"document_id" in story ? story.document_id : story.source_id}
                  href={story.url ?? "#"}
                  // WHY target=_blank: news article URLs go to external
                  // publishers — opening in a new tab keeps the dashboard
                  // visible while the trader reads the full story.
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-[260px] items-center gap-1 rounded-[2px] border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  title={story.title}
                >
                  {/* Source domain — small uppercase label so the user can
                      tell at a glance whether the chip points to e.g.
                      Bloomberg vs. Reuters before they click. */}
                  <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim">
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
    // Round 3 (items 1+3): h-6 — must match the loaded-state header height
    // (24px since the 2026-05-09 density bundle) so the card never shifts
    // 4px when transitioning loading/error/empty → loaded. Label bumped
    // 9px → 10px to match the dominant widget-header treatment
    // (text-[10px] uppercase tracking-[0.08em]) used by every other panel.
    <div className="flex h-6 shrink-0 items-center border-b border-border/40 px-1">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground/40">
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
