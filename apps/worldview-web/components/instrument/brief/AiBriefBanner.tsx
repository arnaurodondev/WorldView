/**
 * components/instrument/brief/AiBriefBanner.tsx — collapsible AI brief banner
 *
 * WHY THIS EXISTS: PRD-0088 §6.5 — a 1-line brief between header and tab
 * bar, visible on all 3 tabs. Collapsed by default to maximise chart real
 * estate; click expands. Hidden entirely when no brief is cached.
 * WHO USES IT: components/instrument/InstrumentPageClient.tsx (T-A-05).
 * DATA SOURCE: GET /v1/briefings/instrument/{entityId} (S9 gateway, 10 min cache).
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.5.
 * TARGET READER: junior Next.js dev — sessionStorage (not localStorage)
 *              because the choice is per-tab/window, not user-wide.
 */

"use client";
// WHY "use client": useState + useQuery + sessionStorage all require the
// browser runtime; this is a client-only interactive component.

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { formatRelativeTime } from "@/lib/utils";

interface AiBriefBannerProps {
  readonly entityId: string;
}

// WHY 10 minutes: briefs cost LLM tokens; the backend already caches them
// in Valkey for ~10 min so any refetch sooner just hits cache. Matches
// the staleTime used by morning-brief consumers elsewhere.
const BRIEF_STALE_MS = 10 * 60 * 1000;

// WHY first-140 char preview: spec §6.5 — collapsed row shows a single
// truncated line. 140 chars roughly fills the available width at 11px.
const PREVIEW_CHARS = 140;

export function AiBriefBanner({ entityId }: AiBriefBannerProps) {
  const { accessToken } = useAuth();

  // WHY sessionStorage (not localStorage): collapse pref is per-tab and
  // resets on a fresh session — spec §6.5. Key shape namespaces by
  // entityId so each ticker keeps its own state.
  const storageKey = `wv:brief-collapsed:${entityId}`;

  // WHY initial state TRUE (collapsed): spec §6.5 default.
  const [expanded, setExpanded] = useState(false);

  // WHY useEffect for hydration: reading sessionStorage during initial
  // render breaks SSR (window undefined). We start collapsed on the
  // server and adopt the persisted preference on the client after mount.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.sessionStorage.getItem(storageKey);
    if (stored === "expanded") setExpanded(true);
  }, [storageKey]);

  const { data: brief } = useQuery({
    queryKey: qk.instruments.brief(entityId),
    queryFn: () => createGateway(accessToken).getInstrumentBrief(entityId),
    enabled: !!accessToken && !!entityId,
    staleTime: BRIEF_STALE_MS,
    // WHY retry:false: brief endpoint 404s for instruments with no cached
    // brief yet — retrying just hits the LLM-cold path again and again.
    retry: false,
  });

  // WHY render nothing on null/missing: spec §6.5 — "Unavailable state:
  // show nothing (banner hidden entirely if brief returns 404 or is null)".
  // No skeleton; we never reserve empty space.
  if (!brief || !brief.narrative) return null;

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(storageKey, next ? "expanded" : "collapsed");
    }
  };

  const preview = brief.narrative.slice(0, PREVIEW_CHARS);

  return (
    <div className="border-b border-border/50 bg-card">
      {/* WHY a button (not a div with onClick): keyboard + screen-reader
          users get free focus + Enter activation. The visual styling is
          identical to a flex row. */}
      <button
        type="button"
        onClick={toggle}
        className="flex h-6 w-full items-center gap-2 px-3 text-left"
        aria-expanded={expanded}
      >
        <ChevronRight
          className={`size-3 shrink-0 text-muted-foreground transition-transform ${expanded ? "rotate-90" : "rotate-0"}`}
          aria-hidden="true"
        />
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">BRIEF</span>
        {!expanded && (
          <span className="flex-1 truncate text-[11px] text-foreground/70">{preview}</span>
        )}
      </button>
      {expanded && (
        <div className="max-h-[120px] overflow-y-auto px-3 pb-2">
          {/* WHY whitespace-pre-wrap: spec §6.5 — "markdown NOT rendered
              (plain text)". Preserves paragraph breaks the LLM emitted. */}
          <p className="whitespace-pre-wrap text-[11px] leading-[1.5] text-foreground/80">
            {brief.narrative}
          </p>
          <p className="mt-1 text-[10px] text-muted-foreground">
            Updated {formatRelativeTime(brief.generated_at)}
          </p>
        </div>
      )}
    </div>
  );
}
