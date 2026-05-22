/**
 * components/instrument/brief/AiBriefBanner.tsx — collapsible AI brief banner (T-23)
 *
 * WHY THIS EXISTS: PRD-0088 §6.5 — a 1-line brief between header and tab
 *   bar, always visible (never returns null — §1.4). Collapsed default; click
 *   expands. Uses `useInstrumentBrief` (T-04) for lazy-generate flow (Δ27).
 *
 * STATUS RENDERS:
 *   loading      → "BRIEF · —" (placeholder, keeps layout height stable)
 *   generating   → "BRIEF · Generating…" (POST queued; polling)
 *   ready        → preview text + expand toggle
 *   unavailable  → "BRIEF · Unavailable"
 *   quota-exceeded → "BRIEF · Quota exceeded — retry in Nm" (Δ44)
 *
 * CITATIONS (expanded state): when the brief has article citations, a Top
 *   Stories chip strip is rendered below the narrative — matching the pattern
 *   in MorningBriefCard. Uses `<a>` not `<Link>` (external URLs). Up to 3
 *   chips; each shows the source domain + truncated title (60 chars).
 *
 * DESIGN: No `transition-[transform]` on chevron (Δ9 — F1 animation policy).
 *   Border-b hairline; bg-card. h-6 banner row. text-[10px] "BRIEF" label.
 *   No `rounded-*` on any element (Δ3).
 *
 * WHO USES IT: InstrumentPageClient.tsx. LINE LIMIT: soft 160.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";
import { formatRelativeTime } from "@/lib/utils";
import type { BriefCitation, BriefingCitation } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PREVIEW_CHARS = 140;

/**
 * Maximum characters of an article title rendered inside a chip. Mirrors
 * MorningBriefCard's CHIP_TITLE_MAX — consistent truncation across both
 * citation strip implementations.
 */
const CHIP_TITLE_MAX = 60;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * extractDomain — pull a short host label from a full article URL.
 * WHY not use `URL.hostname` directly: we strip the "www." prefix so the
 * chip shows "reuters.com" instead of "www.reuters.com". Falls back to
 * "source" for non-parseable URLs (avoids a visible crash in the chip).
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
 * truncate — clip a string to `max` characters with a trailing ellipsis.
 * WHY JS slice (not CSS text-overflow): CSS ellipsis on flex children inside
 * a flex-wrap row is fragile — the intrinsic width doesn't constrain reliably.
 */
function truncate(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max)}…`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface AiBriefBannerProps {
  /** entityId used for the GET/POST brief endpoints (may equal instrumentId). */
  readonly entityId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AiBriefBanner({ entityId }: AiBriefBannerProps) {
  const storageKey = `wv:brief-collapsed:${entityId}`;
  const [expanded, setExpanded] = useState(false);

  // Adopt session-persisted expand preference on the client (SSR-safe).
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.sessionStorage.getItem(storageKey) === "expanded") setExpanded(true);
  }, [storageKey]);

  const { data: brief, status, retryAfter } = useInstrumentBrief(entityId, entityId);

  // WHY "wv:brief-toggle" custom event: InstrumentTabs (T-26) dispatches it on
  // "B" keydown so the banner responds to the hotkey without prop-drilling.
  const toggle = useCallback(() => {
    const next = !expanded;
    setExpanded(next);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(storageKey, next ? "expanded" : "collapsed");
    }
  }, [expanded, storageKey]);

  useEffect(() => {
    window.addEventListener("wv:brief-toggle", toggle);
    return () => window.removeEventListener("wv:brief-toggle", toggle);
  }, [toggle]);

  // ── Status label (collapsed-mode suffix) ─────────────────────────────────
  let statusLabel: string | null = null;
  if (status === "generating") statusLabel = "Generating…";
  if (status === "unavailable") statusLabel = "Unavailable";
  if (status === "quota-exceeded") {
    const mins = retryAfter != null ? Math.ceil(retryAfter / 60) : null;
    statusLabel = mins != null ? `Quota exceeded — retry in ${mins}m` : "Quota exceeded";
  }

  const preview = brief?.narrative?.slice(0, PREVIEW_CHARS) ?? null;
  const isReady = status === "ready" && preview != null;

  // WHY filter source_type==="article": events and alerts have no external URL
  // to link to. Only article citations produce meaningful clickable chips.
  // WHY union type: W4+ responses emit BriefCitation; pre-W4 cached responses
  // emit BriefingCitation. Both have source_type and url — the chip strip
  // renders identically for both shapes.
  const topSources: (BriefCitation | BriefingCitation)[] = (brief?.citations ?? [])
    .filter((c) => c.source_type === "article" && c.url)
    .slice(0, 3);

  return (
    // WHY always mounted (never return null): §1.4 — AiBriefBanner is ALWAYS
    // visible. The "loading" state preserves the 24px layout slot.
    <div className="border-b border-border/50 bg-card">
      <button
        type="button"
        onClick={toggle}
        className="flex h-6 w-full items-center gap-2 px-3 text-left"
        aria-expanded={expanded && isReady}
        aria-label="Toggle AI brief"
      >
        {/* WHY no transition-[transform] (Δ9): F1 animation-policy forbids CSS
            transition on layout-shifting elements; instant flip is preferred. */}
        <ChevronRight
          className={`size-3 shrink-0 text-muted-foreground ${expanded && isReady ? "rotate-90" : "rotate-0"}`}
          aria-hidden="true"
        />
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground shrink-0">
          BRIEF
        </span>
        {/* Collapsed state: preview text OR status label */}
        {!expanded && (
          <>
            <span className="flex-1 truncate text-[11px] text-foreground/70">
              {isReady ? preview : (statusLabel ?? "—")}
            </span>
            {/* Compact source domain badges — visible in collapsed state so the
                trader can tell at a glance where the brief was sourced from
                without opening the expanded panel. WHY shrink-0: prevents the
                domain labels from being squeezed out when the preview is long. */}
            {isReady && topSources.length > 0 && (
              <div className="flex shrink-0 items-center gap-1 ml-2">
                {topSources.slice(0, 2).map((s, i) => (
                  <span key={i} className="font-mono text-[9px] uppercase text-muted-foreground/50">
                    {extractDomain(s.url ?? "")}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </button>

      {/* Expanded body — only shown when brief is ready */}
      {expanded && isReady && (
        <div className="max-h-[180px] overflow-y-auto px-3 pb-2">
          {/* WHY whitespace-pre-wrap: §6.5 — plain text, not markdown. */}
          <p className="whitespace-pre-wrap text-[11px] leading-[1.5] text-foreground/80">
            {brief?.narrative}
          </p>

          {/* Top Stories chip strip — mirrors MorningBriefCard pattern.
              WHY <a> not <Link>: citations point to external publisher URLs;
              opening in a new tab keeps the instrument page in focus. */}
          {topSources.length > 0 && (
            <div
              className="mt-1.5 flex flex-wrap gap-1 border-t border-border/40 pt-1.5"
              aria-label="Source citations"
            >
              {topSources.map((story, i) => (
                <a
                  key={i}
                  href={story.url ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-[260px] items-center gap-1 rounded-[2px] border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                  title={story.title}
                >
                  {/* Source domain — uppercase mono label lets the trader
                      identify the publisher before clicking. */}
                  <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/70">
                    {extractDomain(story.url ?? "")}
                  </span>
                  {/* Title capped at CHIP_TITLE_MAX chars via JS slice —
                      CSS text-overflow on flex-wrap children is unreliable. */}
                  <span className="truncate">{truncate(story.title, CHIP_TITLE_MAX)}</span>
                </a>
              ))}
            </div>
          )}

          {brief?.generated_at && (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Updated {formatRelativeTime(brief.generated_at)}
            </p>
          )}
        </div>
      )}

      {/* Expanded error states */}
      {expanded && !isReady && statusLabel && (
        <div className="px-3 pb-2 text-[11px] text-muted-foreground/60">
          {statusLabel}
        </div>
      )}
    </div>
  );
}
