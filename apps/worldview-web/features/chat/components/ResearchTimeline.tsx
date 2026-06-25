/**
 * features/chat/components/ResearchTimeline.tsx
 *
 * WHY THIS EXISTS (Phase-1 Part C — "Research timeline"):
 * Until now the agent's reasoning was either (a) invisible (the silent gaps
 * between tool batches that made a 25s research query feel hung) or (b) only
 * inspectable behind the ?debug=1 ToolTraceDrawer raw-JSON power-user view —
 * which a normal user never opens. This component makes the agent's WORK a
 * FIRST-CLASS, ALWAYS-VISIBLE narrative: a legible, finance-grade timeline of
 * the steps it took, rendered DURING streaming inside the assistant bubble and
 * collapsed to a one-line summary once the answer settles.
 *
 * RELATIONSHIP TO THE OTHER TWO COMPONENTS:
 *   - AgentIterationProgress (PLAN-0099 W4): a single always-on "Step N of M ·
 *     Reasoning…" strip. This timeline SUPERSEDES it for the in-bubble view —
 *     it shows the same step grouping PLUS the concrete per-tool lines, so we
 *     no longer render the bare strip alongside it (avoids a redundant signal).
 *   - ToolTraceDrawer (?debug=1): the raw JSON/args/latency record for
 *     engineers. UNCHANGED and still gated behind ?debug=1 — this timeline is
 *     the human-facing view; the drawer is the forensic view. They coexist.
 *
 * DATA SOURCE (no new wiring — reads what useChatStream already exposes):
 *   - `trace` = useChatStream.toolTrace — each entry now carries an `iteration`
 *     (the agent-loop step it ran in, for grouping) and a `resultLabel` (the
 *     input-aware human completion label, e.g. "Searching news for NVIDIA").
 *   - `verifying` = useChatStream.verifying — TRUE during the post-synthesis
 *     grounding-validation phase; drives the "Verifying answer…" line.
 *
 * VISUAL DENSITY (Midnight Pro / Bloomberg-terminal mandate, PRD-0028 §6.9):
 * 11px monospace, hairline icons (strokeWidth 1.5), Midnight Pro tokens only
 * (primary accent, muted-foreground secondary, no off-palette colors). Compact,
 * not noisy: one line per tool, grouped under faint "Step N" dividers only when
 * there is more than one step.
 *
 * ANIMATION (DESIGN_SYSTEM.md §6.2): the ONLY motion is
 * `animate-skeleton-pulse` (sanctioned slow 2s fade) on the icon of the
 * currently-running line — paired with motion-reduce:animate-none. No spin,
 * no bounce, no raw animate-pulse (all banned on prose surfaces).
 */

"use client";
// WHY "use client": consumes runtime state derived from useChatStream (a
// client-only hook) and owns local collapse state. Renders no server data.

import { useMemo, useState } from "react";

import {
  Check,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Loader2,
  ShieldCheck,
  X,
} from "lucide-react";
// WHY these icons:
// - Loader2       → a step still running (the one in-flight line)
// - Check         → a step that returned data ("ok")
// - CircleDashed  → a step that completed but returned nothing ("empty")
// - X             → a step that errored
// - ShieldCheck   → the post-synthesis grounding-verification line
// - Chevron*      → expand/collapse affordance for the settled summary
// All ship with lucide-react (already a dep via shadcn/ui) — no new dependency.

import type { ToolTraceEntry } from "@/features/chat/lib/types";

interface ResearchTimelineProps {
  /**
   * The per-turn tool trace from useChatStream.toolTrace. Each entry carries a
   * human `resultLabel`, a terminal `status`, and the loop `iteration` it ran
   * in. Empty array before the first tool_call.
   */
  trace: ToolTraceEntry[];
  /**
   * useChatStream.verifying — TRUE during the post-synthesis grounding /
   * repair window. Renders a "Verifying answer against sources…" line at the
   * tail of the timeline while true.
   */
  verifying: boolean;
  /**
   * Render mode:
   *   - "live" (default) → expanded timeline shown DURING streaming, inside the
   *     assistant bubble. aria-live announces progress to assistive tech.
   *   - "done" → the stream has settled. Collapse to a single summary line
   *     ("Researched N sources across M steps") that the user can click to
   *     re-expand the full step list. No aria-live (the work is finished).
   */
  mode?: "live" | "done";
}

/**
 * Picks the status icon + accessible verb for one tool line. Extracted so the
 * JSX stays scannable and copy edits are one-liners (same rationale as
 * AgentIterationProgress.viewModelFor).
 */
function lineViewModel(status: ToolTraceEntry["status"]): {
  Icon: typeof Check;
  /** Whether this is the live/in-flight line (drives the pulse + spinner). */
  running: boolean;
  /** Tailwind text-color class for the icon (Midnight Pro tokens only). */
  colorClass: string;
} {
  switch (status) {
    case "running":
      return { Icon: Loader2, running: true, colorClass: "text-primary" };
    case "empty":
      // Completed but returned nothing — muted, not an error (a search that
      // found 0 articles is a valid, informative outcome).
      return { Icon: CircleDashed, running: false, colorClass: "text-muted-foreground" };
    case "error":
      return { Icon: X, running: false, colorClass: "text-destructive" };
    case "ok":
    default:
      return { Icon: Check, running: false, colorClass: "text-primary" };
  }
}

/**
 * Strips a trailing ellipsis from a call-time label so a settled line reads
 * "Searching news for NVIDIA" rather than "Searching news for NVIDIA…". Live
 * (running) lines keep the ellipsis — it signals "still in progress".
 */
function tidyLabel(label: string, running: boolean): string {
  if (running) return label;
  return label.replace(/[.…]+$/u, "").trim();
}

/**
 * ResearchTimeline — the human-facing live agent-step trace.
 *
 * LIVE mode: an aria-live region listing every tool line grouped by loop step,
 * plus a trailing "Verifying…" line when `verifying` is true. Renders nothing
 * when there is no activity yet (empty trace + not verifying) so it never
 * reserves blank space before the agent actually starts working.
 *
 * DONE mode: collapses to a one-line summary; clicking expands the full list.
 */
export function ResearchTimeline({ trace, verifying, mode = "live" }: ResearchTimelineProps) {
  // Collapse state for "done" mode. Starts collapsed (the answer is what the
  // user came for; the trail is secondary). Ignored entirely in "live" mode,
  // which is always expanded.
  const [expanded, setExpanded] = useState(false);

  // Group trace entries by their loop `iteration`, preserving first-seen order.
  // WHY a memo keyed on trace: regrouping on every streaming token would be
  // wasteful; the trace array identity only changes when an entry is added or
  // a status flips, which is exactly when we want to recompute.
  const steps = useMemo(() => {
    const byIteration = new Map<number, ToolTraceEntry[]>();
    for (const entry of trace) {
      const bucket = byIteration.get(entry.iteration);
      if (bucket) bucket.push(entry);
      else byIteration.set(entry.iteration, [entry]);
    }
    // Sort by iteration ascending so steps read top-to-bottom in loop order.
    return [...byIteration.entries()].sort((a, b) => a[0] - b[0]);
  }, [trace]);

  // Summary numbers for the collapsed "done" line and the aria-label.
  // "sources" = total tool invocations; "steps" = distinct agent-loop iterations.
  const toolCount = trace.length;
  const stepCount = steps.length;

  // Nothing to render yet: no tools have been called and we're not verifying.
  // Returning null (not an empty box) keeps the bubble tight until the agent
  // actually does something — the timeline appearing is itself a signal.
  if (toolCount === 0 && !verifying) return null;

  // ── DONE mode: collapsed summary that expands on click ─────────────────────
  if (mode === "done") {
    return (
      <div className="mt-1 text-[11px] font-mono text-muted-foreground" data-testid="research-timeline-done">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          // aria-expanded ties the toggle to the disclosure region for AT.
          aria-expanded={expanded}
          className="flex items-center gap-1.5 rounded-[2px] px-1 py-0.5 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary"
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3 shrink-0" strokeWidth={1.5} aria-hidden="true" />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" strokeWidth={1.5} aria-hidden="true" />
          )}
          {/* One-line summary. Singular/plural polish on both nouns. */}
          <span>
            Researched {toolCount} {toolCount === 1 ? "source" : "sources"} across {stepCount}{" "}
            {stepCount === 1 ? "step" : "steps"}
          </span>
        </button>

        {/* Expanded detail re-uses the same step list as the live view. */}
        {expanded ? (
          <div className="mt-1 border-l border-border/60 pl-2">
            <StepList steps={steps} verifying={false} />
          </div>
        ) : null}
      </div>
    );
  }

  // ── LIVE mode: full, always-visible, announced timeline ────────────────────
  return (
    <div
      // role="status" + aria-live="polite": announce step transitions to screen
      // readers WITHOUT interrupting the user — never louder than the answer.
      role="status"
      aria-live="polite"
      aria-label={`Researching: ${toolCount} ${toolCount === 1 ? "source" : "sources"} across ${stepCount} ${stepCount === 1 ? "step" : "steps"}`}
      data-testid="research-timeline"
      className="mb-1 text-[11px] font-mono text-muted-foreground"
    >
      <StepList steps={steps} verifying={verifying} />
    </div>
  );
}

/**
 * StepList — the shared renderer used by both the live view and the expanded
 * "done" disclosure. Extracted so the two modes can never visually drift.
 *
 * Renders a faint "Step N" divider ONLY when there is more than one step (a
 * single-iteration / classical answer folds into one implicit, unlabelled
 * group — a lone "Step 1" header would be noise).
 */
function StepList({
  steps,
  verifying,
}: {
  steps: [number, ToolTraceEntry[]][];
  verifying: boolean;
}) {
  const multiStep = steps.length > 1;

  return (
    <ol className="space-y-0.5">
      {steps.map(([iteration, entries], idx) => (
        <li key={iteration}>
          {multiStep ? (
            // 1-indexed for humans ("Step 1" not "Step 0") — matches the copy
            // convention in AgentIterationProgress.
            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground/70">
              Step {idx + 1}
            </div>
          ) : null}
          <ul className="space-y-0.5">
            {entries.map((entry, i) => {
              const { Icon, running, colorClass } = lineViewModel(entry.status);
              // resultLabel is the input-aware completion label; fall back to
              // the call-time `label` if a (legacy) backend omitted it.
              const text = tidyLabel(entry.resultLabel ?? entry.label, running);
              return (
                <li
                  // tool name + index keys the line stably across status flips.
                  key={`${entry.tool}-${i}`}
                  className="flex items-center gap-1.5"
                >
                  <Icon
                    className={`h-3 w-3 shrink-0 ${colorClass} ${
                      running ? "animate-skeleton-pulse motion-reduce:animate-none" : ""
                    }`}
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 truncate">{text}</span>
                  {/* For completed data tools, append the compact result count
                      ("· 12") when present — the headline "what came back". */}
                  {!running && typeof entry.result?.item_count === "number" ? (
                    <span className="shrink-0 tabular-nums text-muted-foreground/70">
                      · {entry.result.item_count as number}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </li>
      ))}

      {/* Trailing verification line — only while the grounding-validation phase
          is active. ShieldCheck reads as "checking against sources". */}
      {verifying ? (
        <li className="mt-1 flex items-center gap-1.5">
          <ShieldCheck
            className="h-3 w-3 shrink-0 text-primary animate-skeleton-pulse motion-reduce:animate-none"
            strokeWidth={1.5}
            aria-hidden="true"
          />
          <span className="min-w-0 truncate">Verifying answer against sources…</span>
        </li>
      ) : null}
    </ol>
  );
}
