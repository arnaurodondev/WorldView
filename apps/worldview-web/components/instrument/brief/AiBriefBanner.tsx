/**
 * components/instrument/brief/AiBriefBanner.tsx — collapsible AI brief block
 *
 * WHY THIS EXISTS: PRD-0088 §6.5 — a 1-line brief between header and tab bar,
 * visible on all 3 tabs. Collapsed by default to maximise chart real estate;
 * click expands. Hidden entirely when no brief is cached.
 *
 * ── WAVE-2 REDESIGN (2026-06-10) ─────────────────────────────────────────────
 * The old banner dumped the RAW markdown narrative ("## LEAD\nApple's …
 * [c6][c7]") into a whitespace-pre-wrap <p> — literal hashes and citation
 * tokens on screen. Rebuilt:
 *   - the narrative is parsed by briefMarkdown.ts into { lead, body };
 *   - COLLAPSED: chevron + "AI BRIEF" + the citation-stripped LEAD sentence
 *     + relative timestamp (+ amber STALE tag past 24h);
 *   - EXPANDED: the LEAD rendered prominently as styled text, the DETAILS
 *     sections rendered as REAL markdown via the house <MarkdownContent>
 *     renderer (same component the chat/morning-brief surfaces use), and a
 *     footer with Updated-ago + Discuss (deep-link to /chat?entity_id=…) +
 *     Regenerate (POST …/generate, then refetch after the backend's typical
 *     generation window).
 *
 * WHO USES IT: components/instrument/InstrumentPageClient.tsx (T-A-05).
 * DATA SOURCE: GET /v1/briefings/instrument/{entityId} (S9 gateway).
 * DESIGN REFERENCE: docs/specs/0088-…-redesign.md §6.5 + MorningBriefCard patterns.
 */

"use client";
// WHY "use client": useState + useQuery + sessionStorage all require the
// browser runtime; this is a client-only interactive component.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, MessageSquare, RefreshCw } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { formatRelativeTime } from "@/lib/utils";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { isBriefStale, parseInstrumentBrief } from "./briefMarkdown";

interface AiBriefBannerProps {
  readonly entityId: string;
}

// WHY 10 minutes: briefs cost LLM tokens; the backend already caches them in
// Valkey for ~10 min so any refetch sooner just hits cache.
const BRIEF_STALE_MS = 10 * 60 * 1000;

// How long after a regenerate POST we wait before refetching. Instrument
// briefs typically generate in 10-25s via DeepInfra; 30s catches the common
// case in one refetch without hammering the endpoint.
const REGEN_REFETCH_DELAY_MS = 30_000;

export function AiBriefBanner({ entityId }: AiBriefBannerProps) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // WHY sessionStorage (not localStorage): collapse pref is per-tab and
  // resets on a fresh session — spec §6.5. Key shape namespaces by entityId.
  const storageKey = `wv:brief-collapsed:${entityId}`;

  // WHY initial state false (collapsed): spec §6.5 default.
  const [expanded, setExpanded] = useState(false);

  // Regenerate lifecycle: idle → queued (POST sent, refetch timer pending).
  // WHY local state (not a TanStack mutation object): the only consumer is
  // this button's disabled/label state — a boolean is the honest model.
  const [regenQueued, setRegenQueued] = useState(false);
  const regenTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Clear the pending refetch timer on unmount (avoid setState-after-unmount).
  useEffect(() => () => { if (regenTimerRef.current) clearTimeout(regenTimerRef.current); }, []);

  // WHY useEffect for hydration: reading sessionStorage during initial render
  // breaks SSR (window undefined). We start collapsed on the server and adopt
  // the persisted preference on the client after mount.
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

  // WHY render nothing on null/missing: spec §6.5 — "Unavailable state: show
  // nothing (banner hidden entirely if brief returns 404 or is null)".
  if (!brief || !brief.narrative) return null;

  // Parse ONCE per render — lead for the strip, body for the expanded block.
  // (Cheap string ops; memoisation would cost more than it saves at this size.)
  const { lead, body } = parseInstrumentBrief(brief.narrative);
  const stale = isBriefStale(brief.generated_at);

  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(storageKey, next ? "expanded" : "collapsed");
    }
  };

  /**
   * regenerate — POST the lazy-generate trigger, then refetch after the
   * typical generation window. The backend is idempotent (1 generation per
   * entity per 60-min window) so a double-click cannot queue duplicate jobs.
   */
  const regenerate = async () => {
    if (regenQueued) return;
    setRegenQueued(true);
    try {
      await createGateway(accessToken).triggerInstrumentBriefingGeneration(entityId);
      regenTimerRef.current = setTimeout(() => {
        // Invalidate (not setQueryData): the fresh brief comes from the GET.
        void queryClient.invalidateQueries({ queryKey: qk.instruments.brief(entityId) });
        setRegenQueued(false);
      }, REGEN_REFETCH_DELAY_MS);
    } catch {
      // POST failed (rate-limited / transient) — re-enable the button so the
      // analyst can retry; the existing brief stays on screen regardless.
      setRegenQueued(false);
    }
  };

  return (
    <div className="border-b border-border/50 bg-card">
      {/* ── Collapsed strip / expand toggle ─────────────────────────────────
          WHY a button (not a div with onClick): keyboard + screen-reader
          users get free focus + Enter activation. Action buttons live in the
          expanded footer (NOT nested here — nested buttons are invalid HTML). */}
      <button
        type="button"
        onClick={toggle}
        className="flex h-6 w-full items-center gap-2 px-3 text-left hover:bg-muted/20"
        aria-expanded={expanded}
      >
        <ChevronRight
          className={`size-3 shrink-0 text-muted-foreground transition-transform ${expanded ? "rotate-90" : "rotate-0"}`}
          aria-hidden="true"
        />
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-primary/80 font-semibold">
          AI Brief
        </span>
        {/* Collapsed: the citation-stripped LEAD is the one-line takeaway.
            WHY not slice(0,140): truncate handles any width honestly via
            CSS ellipsis instead of a hard character chop mid-word. */}
        {!expanded && (
          <span className="flex-1 truncate text-[11px] text-foreground/80">{lead}</span>
        )}
        {expanded && <span className="flex-1" />}
        {/* Right cluster: STALE tag (amber, only when >24h old) + rel time.
            Rendered in BOTH states so freshness is always one glance away. */}
        {stale && (
          <span className="shrink-0 rounded-[2px] bg-warning/15 px-1 text-[9px] uppercase tracking-wider text-warning">
            stale
          </span>
        )}
        <span className="shrink-0 font-mono text-[9px] text-muted-foreground/60">
          {formatRelativeTime(brief.generated_at)}
        </span>
      </button>

      {/* ── Expanded block ──────────────────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-border/30 px-3 pb-2 pt-2">
          {/* LEAD — the takeaway, prominent. Plain styled text (markdown
              chrome already stripped by the parser): 12px foreground beats
              the 10px muted body so the eye lands here first. */}
          <p className="text-[12px] leading-[1.55] text-foreground/90">{lead}</p>

          {/* DETAILS — real markdown via the house renderer (### sections,
              bullets, bold). Scroll-capped so a long brief can't shove the
              chart below the fold; the analyst scrolls within the block. */}
          {body.length > 0 && (
            <div className="mt-1.5 max-h-[260px] overflow-y-auto border-t border-border/30 pt-1.5">
              <MarkdownContent size="compact">{body}</MarkdownContent>
            </div>
          )}

          {/* Footer: timestamp + actions. mt-1.5 keeps the 22px rhythm. */}
          <div className="mt-1.5 flex items-center gap-3 border-t border-border/30 pt-1.5">
            <span className="font-mono text-[10px] text-muted-foreground">
              Updated {formatRelativeTime(brief.generated_at)}
            </span>
            <span className="flex-1" />
            {/* Discuss — deep-link into Chat scoped to this entity. The chat
                page reads ?entity_id= and seeds its context accordingly. */}
            <Link
              href={`/chat?entity_id=${encodeURIComponent(entityId)}`}
              className="inline-flex h-6 items-center gap-1 rounded-[2px] border border-border px-2 text-[10px] uppercase tracking-wide text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <MessageSquare className="size-3" aria-hidden="true" />
              Discuss
            </Link>
            {/* Regenerate — POST the lazy-generate trigger. Disabled while a
                regeneration is queued (label flips so the state is visible). */}
            <button
              type="button"
              onClick={() => void regenerate()}
              disabled={regenQueued}
              className="inline-flex h-6 items-center gap-1 rounded-[2px] border border-border px-2 text-[10px] uppercase tracking-wide text-muted-foreground hover:text-foreground disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <RefreshCw className={`size-3 ${regenQueued ? "animate-spin" : ""}`} aria-hidden="true" />
              {regenQueued ? "Queued…" : "Regenerate"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
