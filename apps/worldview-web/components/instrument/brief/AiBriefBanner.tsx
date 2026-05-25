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
 *   ready        → preview text + sources badge + date
 *   unavailable  → "BRIEF · Unavailable"
 *   quota-exceeded → "BRIEF · Quota exceeded — retry in Nm" (Δ44)
 *
 * DESIGN SYSTEM:
 *   - "BRIEF" label + chevron → text-primary (Bloomberg yellow #FFD60A, ADR-F-01)
 *   - Date → font-mono text-[9px] absolute UTC time (ADR-F-15 tabular-nums rule)
 *   - Sources badge → bg-primary/5 border-primary/30 text-primary text-[9px]
 *   - Preview text → text-foreground (full contrast, no opacity reduction)
 *   - No `transition-[transform]` on chevron (Δ9 — F1 animation policy)
 *   - No `rounded-*` on any element (Δ3)
 *   - Expanded state: StructuredBrief variant="compact" (W4+) or plain text fallback
 *
 * WHO USES IT: InstrumentPageClient.tsx. LINE LIMIT: soft 200.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";
import { StructuredBrief } from "@/components/brief/StructuredBrief";
import type { BriefCitation, BriefingCitation } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PREVIEW_CHARS = 120;

/** Article title cap inside expanded chip. 60 chars mirrors MorningBriefCard. */
const CHIP_TITLE_MAX = 60;

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * truncate — clip a string to `max` characters with a trailing ellipsis.
 * WHY JS slice (not CSS text-overflow): CSS ellipsis on flex-wrap children
 * is fragile — intrinsic width doesn't constrain reliably on variable widths.
 */
function truncate(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max)}…`;
}

/**
 * extractDomain — pull a short host label from a full article URL.
 * WHY strip www.: chip shows "reuters.com" not "www.reuters.com".
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
 * fmtBriefDate — compact absolute UTC timestamp for the collapsed header.
 * WHY absolute (not relative): "2h ago" is ambiguous at a glance — traders
 * need to know the exact generation time to judge staleness. "May 21 14:22 UTC"
 * is unambiguous and fits within ~90px at 9px monospace.
 */
function fmtBriefDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const mon = d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
    const hhmm = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
    return `${mon} ${hhmm} UTC`;
  } catch {
    return null;
  }
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

  // ── Status label (non-ready states) ──────────────────────────────────────
  let statusLabel: string | null = null;
  if (status === "generating") statusLabel = "Generating…";
  if (status === "unavailable") statusLabel = "Unavailable";
  if (status === "quota-exceeded") {
    const mins = retryAfter != null ? Math.ceil(retryAfter / 60) : null;
    statusLabel = mins != null ? `Quota exceeded — retry in ${mins}m` : "Quota exceeded";
  }

  // WHY lead first: brief.lead is the pre-extracted ## LEAD executive summary.
  // Pre-W4 cached responses lack lead; fall back to narrative slice.
  const preview = brief?.lead ?? brief?.narrative?.slice(0, PREVIEW_CHARS) ?? null;
  const isReady = status === "ready" && preview != null;

  // WHY filter source_type==="article": events/alerts have no external URL.
  const topSources: (BriefCitation | BriefingCitation)[] = (brief?.citations ?? [])
    .filter((c) => c.source_type === "article" && c.url)
    .slice(0, 3);

  const briefDate = fmtBriefDate(brief?.generated_at);
  const sourceCount = topSources.length;

  return (
    // WHY always mounted (never return null): §1.4 — preserves the 24px layout slot.
    <div className="border-b border-border/40 bg-card">
      <button
        type="button"
        onClick={toggle}
        className="flex h-6 w-full items-center gap-1.5 px-2 text-left"
        aria-expanded={expanded && isReady}
        aria-label="Toggle AI brief"
      >
        {/* WHY text-primary: Bloomberg yellow accent signals AI-generated content
            (matches MorningBriefCard header, ADR-F-01). Δ9: no CSS transition. */}
        <ChevronRight
          className={`size-3 shrink-0 text-primary ${expanded && isReady ? "rotate-90" : "rotate-0"}`}
          aria-hidden="true"
        />

        {/* "BRIEF" label — yellow, medium weight, tighter tracking */}
        <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-primary shrink-0">
          BRIEF
        </span>

        {/* Preview text (ready) or status label (non-ready) — full contrast */}
        <span className="flex-1 truncate text-[11px] text-foreground min-w-0">
          {isReady ? preview : (statusLabel ?? "—")}
        </span>

        {/* Sources count badge — signals evidence-grounded brief at a glance.
            WHY rounded-[2px]: Δ3 allows 0–4px; 2px matches chip style in expanded. */}
        {isReady && sourceCount > 0 && (
          <span className="shrink-0 border border-primary/30 bg-primary/5 text-primary font-mono text-[9px] px-1 rounded-[2px]">
            {sourceCount} {sourceCount === 1 ? "source" : "sources"}
          </span>
        )}

        {/* Compact absolute UTC date — tells the trader how fresh the brief is.
            WHY font-mono tabular-nums: time values must not shift layout (ADR-F-15). */}
        {isReady && briefDate && (
          <span className="shrink-0 font-mono text-[9px] text-muted-foreground/50 tabular-nums">
            {briefDate}
          </span>
        )}
      </button>

      {/* ── Expanded body (ready state) ───────────────────────────────────── */}
      {expanded && isReady && (
        <div className="max-h-[240px] overflow-y-auto px-3 pb-2 pt-1">
          {/* WHY StructuredBrief for W4+ responses: sections[] carry per-bullet
              citation chips — shared renderer ensures Bloomberg-grade formatting
              identical to MorningBriefCard. Fallback to plain text for pre-W4
              cached entries that lack sections[]. */}
          {brief?.sections && brief.sections.length > 0 ? (
            <StructuredBrief
              lead={brief.lead}
              sections={brief.sections.filter(
                // Filter LLM "REMOVED" placeholder sections (prompt artifact).
                (s) => !s.title?.toUpperCase().includes("REMOVED")
              )}
              confidence={brief.confidence}
              variant="compact"
            />
          ) : (
            <p className="whitespace-pre-wrap text-[11px] leading-[1.5] text-foreground/80">
              {brief?.narrative}
            </p>
          )}

          {/* Top Stories chip strip — clickable source links below the narrative.
              WHY <a> not <Link>: external publisher URLs open in a new tab
              so the instrument page stays in focus. */}
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
                  <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground/70">
                    {extractDomain(story.url ?? "")}
                  </span>
                  <span className="truncate">{truncate(story.title, CHIP_TITLE_MAX)}</span>
                </a>
              ))}
            </div>
          )}

          {/* Absolute UTC timestamp — more informative than relative "Updated 2h ago". */}
          {briefDate && (
            <p className="mt-1 font-mono text-[9px] text-muted-foreground/50 tabular-nums">
              Generated {briefDate}
            </p>
          )}
        </div>
      )}

      {/* ── Expanded error states ─────────────────────────────────────────── */}
      {expanded && !isReady && statusLabel && (
        <div className="px-3 pb-2 text-[11px] text-muted-foreground/60">
          {statusLabel}
        </div>
      )}
    </div>
  );
}
