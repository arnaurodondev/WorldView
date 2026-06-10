/**
 * components/instrument/intelligence/context/NarrativeTimeline.tsx
 * Narrative history rendered as a vertical timeline (Round-2 Enhancement,
 * item 4).
 *
 * WHY THIS EXISTS: the narrative version history used to render as flat
 * <details> rows — functional, but it read as a debug list. A timeline
 * (marker column + connecting rail, most recent at top) communicates the
 * KG's evolving interpretation of an entity the way analysts expect change
 * logs to read.
 *
 * DATA TRUTHFULNESS — sentiment dots:
 * The S9 narrative payload (NarrativeVersionPublic: version_id,
 * narrative_text, model_id, generation_reason, generated_at, word_count,
 * quality_score — verified live 2026-06-10) carries NO sentiment field.
 * This component therefore supports an OPTIONAL `sentiment` per entry and
 * renders the positive/negative/neutral token dot ONLY when it is present;
 * absent sentiment renders a plain muted timeline marker that cannot be
 * misread as "neutral". The moment the backend adds per-version sentiment,
 * the adapter (NarrativeHistoryDisclosure) can pass it through with zero
 * changes here. Backend gap reported in the Round-2 report — we do NOT fake
 * a sentiment classification client-side.
 *
 * WHY PRESENTATIONAL (entries via props): the fetch + cursor pagination +
 * post-202 polling all stay in NarrativeHistoryDisclosure (the existing
 * owner). This component only sorts (defensively, newest-first) and renders,
 * which keeps every visual rule unit-testable without a QueryClient.
 *
 * WHO USES IT: NarrativeHistoryDisclosure (inside the accordion content).
 */

// WHY no "use client": pure render from props — the only interactivity is
// native <details> disclosure, which needs no React state or browser APIs.

import { History } from "lucide-react";

// Round-3 consolidation (DS §15.12): shared primitive + registry copy key
// replace the local components/instrument/shared/EmptyState.tsx fork.
import { EmptyState } from "@/components/primitives/EmptyState";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────────

/** Sentiment vocabulary matching the platform's article-level enum. */
export type NarrativeSentiment = "positive" | "negative" | "neutral";

export interface NarrativeTimelineEntry {
  /** Stable key (version_id). */
  readonly id: string;
  /** ISO datetime the narrative version was generated. */
  readonly date: string;
  /** One-line headline (first sentence of the narrative — derived upstream). */
  readonly headline: string;
  /** Full narrative text, shown in the expandable body. */
  readonly fullText?: string;
  /**
   * Per-version sentiment — OPTIONAL because the backend does not provide it
   * yet (see file header). undefined → plain muted marker, not a "neutral" dot.
   */
  readonly sentiment?: NarrativeSentiment;
}

export interface NarrativeTimelineProps {
  readonly entries: readonly NarrativeTimelineEntry[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * dotClass — sentiment → semantic colour token for the timeline marker.
 * WHY bg-* semantic tokens: text-positive/-negative/-warning resolve through
 * the Terminal Dark CSS variables (raw palette classes are lint-banned).
 * Neutral uses the muted-foreground token — visible but directionless.
 * No sentiment → border-only hollow marker (distinct from all three filled
 * dots, so "unknown" can never be confused with "neutral").
 */
function dotClass(sentiment: NarrativeSentiment | undefined): string {
  switch (sentiment) {
    case "positive":
      return "bg-positive";
    case "negative":
      return "bg-negative";
    case "neutral":
      return "bg-muted-foreground";
    default:
      return "border border-muted-foreground/60 bg-transparent";
  }
}

/**
 * formatTimelineDate — ISO → "12 Jun 26" (fixed UTC format).
 * WHY not Intl with locale: same hydration-mismatch rationale as the
 * disclosure's original formatter — locale-sensitive output differs between
 * server render and client hydration.
 */
function formatTimelineDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
}

// ── Component ────────────────────────────────────────────────────────────────

export function NarrativeTimeline({ entries }: NarrativeTimelineProps) {
  // Defensive newest-first sort: S9 returns versions newest-first, but the
  // visual contract "most recent at top" is THIS component's promise — we
  // don't outsource it to upstream ordering that a pagination merge could
  // accidentally scramble.
  const sorted = [...entries].sort((a, b) => b.date.localeCompare(a.date));

  if (sorted.length === 0) {
    // Round-3: copy moved verbatim into the registry under a new
    // instrument.* key (this Round-2 call site was outside the original
    // six-key reservation — see lib/copy/empty-states.ts comment).
    return (
      <EmptyState
        condition="empty-no-data"
        copyKey="instrument.no-narrative-history"
        icon={History}
      />
    );
  }

  return (
    // WHY <ol>: the version history is an ordered (reverse-chronological)
    // list — semantic for screen readers, free numbering suppressed via CSS.
    <ol className="space-y-0" aria-label="Narrative version history">
      {sorted.map((entry, idx) => (
        <li key={entry.id} className="relative flex gap-2 pl-0.5">
          {/* ── Marker column: dot + connecting rail ─────────────────────
              The rail (absolute 1px line) connects this dot to the next
              entry's dot; suppressed on the last item so the timeline
              visually terminates rather than dangling. */}
          <div className="relative flex w-3 shrink-0 justify-center">
            <span
              data-testid="timeline-dot"
              className={cn("mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full", dotClass(entry.sentiment))}
              aria-hidden="true"
            />
            {idx < sorted.length - 1 && (
              <span
                className="absolute top-[12px] bottom-[-5px] w-px bg-border/60"
                aria-hidden="true"
              />
            )}
          </div>

          {/* ── Entry body: date row + headline (+ expandable full text) ── */}
          <div className="min-w-0 flex-1 pb-2">
            <span className="block text-[9px] font-mono uppercase tracking-wider text-muted-foreground tabular-nums">
              {formatTimelineDate(entry.date)}
            </span>

            {entry.fullText ? (
              // WHY native <details>: progressive disclosure without N state
              // slots — same pattern the old VersionRow used. The headline is
              // the summary; the body reveals the complete narrative.
              <details className="group">
                {/* Round-3 item 5: hover bg + focus-visible ring — <summary>
                    is natively focusable/toggleable (Enter/Space), so adding
                    the visual affordances makes the existing keyboard path
                    VISIBLE. -mx-1 px-1 widens the hover hit-strip without
                    shifting the text column. */}
                <summary className="cursor-pointer list-none rounded-[2px] -mx-1 px-1 text-[10px] leading-snug text-foreground/85 hover:bg-muted/40 hover:text-foreground transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
                  {entry.headline}
                </summary>
                <p className="mt-1 max-h-[300px] overflow-y-auto whitespace-pre-wrap text-[10px] leading-relaxed text-foreground/70">
                  {entry.fullText}
                </p>
              </details>
            ) : (
              <p className="text-[10px] leading-snug text-foreground/85">{entry.headline}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
