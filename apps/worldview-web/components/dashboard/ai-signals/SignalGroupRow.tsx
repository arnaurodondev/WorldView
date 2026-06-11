/**
 * components/dashboard/ai-signals/SignalGroupRow.tsx — one entity's signal row
 *
 * WHY THIS EXISTS: the pre-overhaul widget rendered one undifferentiated row
 * per raw signal ("BSX ——— 95%" three times). This component renders one row
 * per ENTITY with everything a trader needs to act:
 *
 *   ▲ LULU  Lululemon Athletica   [Guidance]  ×2   95%  4m
 *   └─ expanded: each signal with its type chip + triggering headline link
 *
 *  - direction glyph + color (semantic tokens, redundant encoding for
 *    color-blind users)
 *  - ticker in mono (ADR-F-15) with the entity NAME beside it — never a
 *    UUID prefix: entities without a ticker show their name instead
 *  - signal-type chip ("Earnings", "M&A", …) so the user knows WHAT fired
 *  - "×N" expand toggle when several signals cluster on one entity —
 *    repetition becomes information instead of noise
 *  - confidence % with a tooltip explaining the metric honestly
 *  - relative time so the user knows WHEN
 *  - row click → instrument page (ticker-first URL, entity_id fallback)
 *
 * WHO USES IT: AiSignalsWidget.tsx (one per SignalGroup)
 * DESIGN REFERENCE: DESIGN_SYSTEM §0 terminal density (22px rows), §15.9
 * mono numerics, §15.11 semantic color utilities.
 */

"use client";
// WHY "use client": owns local expand/collapse state (useState) and click
// handlers — both client-only React features.

import { useState } from "react";

import { cn } from "@/lib/utils";

import {
  chipLabel,
  compactRelativeTime,
  confidenceTitle,
  directionMeta,
  rowTitle,
} from "./signal-meta";
import type { EnrichedAiSignal, SignalGroup } from "./types";

interface SignalGroupRowProps {
  group: SignalGroup;
  /** Navigate to the entity's instrument page — wired to router.push by the
   *  widget. Kept as a prop so this component stays router-free (and thus
   *  trivially testable without a Next.js navigation mock). */
  onNavigate: () => void;
}

/**
 * SignalGroupRow — collapsed 22px entity row + optional expanded detail rows.
 */
export function SignalGroupRow({ group, onNavigate }: SignalGroupRowProps) {
  // Local expand state — per-row, intentionally NOT lifted to the widget:
  // collapsing one row must not re-render its siblings, and the state is
  // throwaway UI state (lost on refetch, which is fine).
  const [expanded, setExpanded] = useState(false);

  const top = group.top;
  const meta = directionMeta(top.label);
  const scorePct = Math.round(top.score * 100);

  // Display label priority: ticker → entity name → em-dash. The pre-overhaul
  // fallback was entity_id.slice(0,4) which produced the cryptic "9ECB"/"20D8"
  // rows — a UUID prefix must never reach the screen again.
  const primary = group.ticker ?? group.name ?? "—";
  // Show the name in the middle slot only when the primary slot used the
  // ticker (otherwise we would print the name twice).
  const secondary = group.ticker ? group.name : null;

  return (
    <div>
      {/* ── Collapsed row ──────────────────────────────────────────────────── */}
      <div
        // WHY h-[22px]: dashboard terminal density rule (§0) — every list row
        // on the dashboard is exactly 22px so columns align across widgets.
        className="flex h-[22px] cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
        onClick={onNavigate}
        onKeyDown={(e) => e.key === "Enter" && onNavigate()}
        role="button"
        tabIndex={0}
        title={rowTitle(top)}
        aria-label={`${primary} — ${chipLabel(top)}, ${meta.word} signal, ${scorePct}% extraction confidence`}
      >
        {/* Direction glyph — color + shape encode the same bit (WCAG 1.4.1).
            WHY a colored ▲/▼ glyph instead of the old 4px score bar: the bar
            encoded `score`, but live confidence is pinned at 0.90–0.95 so the
            bar was visually constant — pure decoration. Direction is the
            honest, varying datum. The glyph itself carries meta.text (color);
            the invisible-width span below carries meta.bg so tests/styling
            hooks can target the literal `bg-positive` token. */}
        <span aria-hidden className={cn("shrink-0 text-[8px] leading-none", meta.text)}>
          {meta.glyph}
        </span>
        <span aria-hidden className={cn("h-3 w-[2px] shrink-0", meta.bg)} />

        {/* Ticker (or name fallback) — mono per ADR-F-15, fixed width so the
            name column starts at the same x on every row. */}
        <span className="w-[38px] shrink-0 truncate font-mono text-[10px] font-medium tabular-nums text-foreground">
          {primary}
        </span>

        {/* Entity name — flex-1 + truncate absorbs whatever width remains.
            min-w-0 on the flex child is what makes truncate actually work. */}
        <span className="min-w-0 flex-1 truncate text-[9px] text-muted-foreground">
          {secondary ?? ""}
        </span>

        {/* Signal-type chip — WHAT kind of event fired ("Earnings", "M&A").
            max-w + truncate guards against long humanized fallback labels. */}
        <span className="max-w-[64px] shrink-0 truncate rounded-[2px] bg-muted/40 px-1 text-[8px] uppercase tracking-[0.04em] text-muted-foreground">
          {chipLabel(top)}
        </span>

        {/* "×N" expand toggle — only when >1 signal clusters on the entity.
            WHY a real <button> with stopPropagation: the row itself navigates;
            this nested control must not trigger navigation when toggled. */}
        {group.signals.length > 1 && (
          <button
            type="button"
            className="shrink-0 rounded-[2px] px-0.5 font-mono text-[9px] tabular-nums text-muted-foreground hover:bg-muted/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            aria-expanded={expanded}
            aria-label={`${group.signals.length} signals for ${primary} — ${expanded ? "collapse" : "expand"}`}
          >
            ×{group.signals.length}
          </button>
        )}

        {/* Confidence % — mono numerics (§15.9 hard 10px floor for data
            values), colored by direction, tooltip defines the metric. */}
        <span
          className={cn("w-[26px] shrink-0 text-right font-mono text-[10px] tabular-nums", meta.text)}
          title={confidenceTitle(top)}
        >
          {scorePct}%
        </span>

        {/* Relative time — WHEN the signal fired. 9px is allowed here:
            timestamps are metadata, not data values (§15.9). */}
        <span className="w-[24px] shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/70">
          {compactRelativeTime(top.created_at)}
        </span>
      </div>

      {/* ── Expanded detail rows — one per clustered signal ──────────────────── */}
      {expanded &&
        group.signals.map((signal) => <SignalDetailRow key={signal.signal_id} signal={signal} />)}
    </div>
  );
}

/**
 * SignalDetailRow — one signal inside an expanded group: the evidence line.
 *
 * Layout: indent · direction glyph · type chip · headline (links to the
 * source article when we have a URL) · confidence · time.
 *
 * WHY the headline links OUT to the article (not to /instruments): the
 * collapsed row already navigates to the instrument; the detail row's job is
 * to surface the EVIDENCE — "what exactly was reported?" — and the article
 * is that evidence.
 */
function SignalDetailRow({ signal }: { signal: EnrichedAiSignal }) {
  const meta = directionMeta(signal.label);
  const scorePct = Math.round(signal.score * 100);
  const headline = signal.article_title ?? "Article unavailable";

  return (
    <div className="flex h-[22px] items-center gap-1.5 bg-muted/10 py-0 pl-6 pr-2">
      <span aria-hidden className={cn("shrink-0 text-[8px] leading-none", meta.text)}>
        {meta.glyph}
      </span>

      <span className="max-w-[64px] shrink-0 truncate rounded-[2px] bg-muted/40 px-1 text-[8px] uppercase tracking-[0.04em] text-muted-foreground">
        {chipLabel(signal)}
      </span>

      {/* Headline — anchor when the article URL survived enrichment.
          stopPropagation: clicking the evidence must not ALSO navigate the
          row (the detail row has no row-level handler, but defensive against
          future wrapping). target=_blank + rel: external link hygiene. */}
      {signal.article_url ? (
        <a
          href={signal.article_url}
          target="_blank"
          rel="noopener noreferrer"
          className="min-w-0 flex-1 truncate text-[9px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          onClick={(e) => e.stopPropagation()}
          title={headline}
        >
          {headline}
        </a>
      ) : (
        <span className="min-w-0 flex-1 truncate text-[9px] text-muted-foreground/70" title={headline}>
          {headline}
        </span>
      )}

      <span
        className={cn("w-[26px] shrink-0 text-right font-mono text-[10px] tabular-nums", meta.text)}
        title={confidenceTitle(signal)}
      >
        {scorePct}%
      </span>

      <span className="w-[24px] shrink-0 text-right text-[9px] tabular-nums text-muted-foreground/70">
        {compactRelativeTime(signal.created_at)}
      </span>
    </div>
  );
}
