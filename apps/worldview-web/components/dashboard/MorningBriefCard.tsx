/**
 * components/dashboard/MorningBriefCard.tsx — AI-generated morning brief widget
 *
 * WHY THIS EXISTS: Institutional traders start the day by reviewing a macro brief.
 * Rather than reading 20 sources, they want a single synthesised summary of
 * what matters today: key events, portfolio risk, market regime shifts.
 *
 * WHY EXPAND/COLLAPSE: The brief can be 500+ words. A collapsed preview (first 200 chars)
 * respects screen real estate — the user can expand when they want full detail.
 *
 * WHY 503 HANDLING AS SOFT ERROR: S8 briefing endpoint is not yet implemented (PLAN-0029).
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
import { RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Show first 200 chars in collapsed state — enough for 2-3 sentences */
const PREVIEW_CHARS = 200;

/** Brief older than 12h shows a refresh prompt */
const STALE_MS = 12 * 60 * 60 * 1000;

// ── Component ─────────────────────────────────────────────────────────────────

export function MorningBriefCard() {
  const { accessToken } = useAuth();
  const [expanded, setExpanded] = useState(false);

  const {
    data: brief,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
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
  // WHY soft error: S8 briefing endpoint is a stub (PLAN-0029). Showing a
  // "generating" state is less alarming than a hard error card.
  if (isError) {
    const is503 =
      error instanceof Error &&
      (error.message.includes("503") || error.message.includes("unavailable"));

    return (
      <div className="flex items-center justify-between py-1">
        <p className="text-sm text-muted-foreground">
          {is503
            ? "Brief generating… check back in a few minutes."
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
  if (!brief) {
    return (
      <p className="py-1 text-sm text-muted-foreground">No brief available yet.</p>
    );
  }

  // ── Stale brief indicator ──────────────────────────────────────────────────
  const generatedAt = new Date(brief.generated_at);
  const isStale = Date.now() - generatedAt.getTime() > STALE_MS;

  // ── Content rendering ──────────────────────────────────────────────────────
  // WHY replace entity names with links: lets traders click directly to the
  // instrument detail page — faster than searching. Regex scans entity_mentions.
  const contentWithLinks = brief.entity_mentions.reduce((text, mention) => {
    // WHY word boundary match: avoid partial matches inside longer names
    const regex = new RegExp(`\\b${escapeRegex(mention.name)}\\b`, "g");
    return text.replace(
      regex,
      `ENTITY_LINK:${mention.entity_id}:${mention.name}:END`,
    );
  }, brief.content);

  // Split by entity link markers and render as React nodes
  const parts = contentWithLinks.split(/(ENTITY_LINK:[^:]+:[^:]+:END)/);
  const renderedContent = parts.map((part, i) => {
    if (part.startsWith("ENTITY_LINK:")) {
      // Parse ENTITY_LINK:entityId:name:END
      const [, entityId, name] = part.split(":");
      return (
        <Link
          key={i}
          href={`/instruments/${entityId}`}
          className="text-primary hover:underline"
        >
          {name}
        </Link>
      );
    }
    return part;
  });

  const isLong = brief.content.length > PREVIEW_CHARS;
  const preview = brief.content.slice(0, PREVIEW_CHARS);

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
      <p className="text-sm leading-relaxed text-foreground">
        {isLong && !expanded ? (
          // WHY slice plain text for preview (not rendered content):
          // React nodes can't be sliced — show plain preview, render full content when expanded.
          <>
            {preview}
            <span className="text-muted-foreground">…</span>
          </>
        ) : (
          renderedContent
        )}
      </p>

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
