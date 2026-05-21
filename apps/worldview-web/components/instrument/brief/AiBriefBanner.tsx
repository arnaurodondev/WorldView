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
 * DESIGN: No `transition-[transform]` on chevron (Δ9 — F1 animation policy).
 *   Border-b hairline; bg-card. h-6 banner row. text-[10px] "BRIEF" label.
 *
 * WHO USES IT: InstrumentPageClient.tsx. LINE LIMIT: soft 120.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useInstrumentBrief } from "@/components/instrument/hooks/useInstrumentBrief";
import { formatRelativeTime } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

const PREVIEW_CHARS = 140;

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
          <span className="flex-1 truncate text-[11px] text-foreground/70">
            {isReady ? preview : (statusLabel ?? "—")}
          </span>
        )}
      </button>

      {/* Expanded body — only shown when brief is ready */}
      {expanded && isReady && (
        <div className="max-h-[120px] overflow-y-auto px-3 pb-2">
          {/* WHY whitespace-pre-wrap: §6.5 — plain text, not markdown. */}
          <p className="whitespace-pre-wrap text-[11px] leading-[1.5] text-foreground/80">
            {brief?.narrative}
          </p>
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
