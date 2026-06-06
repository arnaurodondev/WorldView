/**
 * features/chat/components/MessageMetaStrip.tsx — One-line meta footer.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-09):
 *   Until Wave K the chat surface DISCARDED the four end-of-stream fields
 *   S8 had been emitting for months: intent / provider / model / latency_ms.
 *   Analysts had no way to verify which LLM produced an answer, how long
 *   the back-end took, or which intent the orchestrator inferred. T-09
 *   surfaces all four on a single 9px terminal-style strip rendered under
 *   each assistant turn (and under user turns when there is something to
 *   show, which is currently never — user turns get a `null` render).
 *
 *   The format mirrors Bloomberg / Refinitiv command-line footers:
 *     `REASONING · via DeepInfra · deepseek-r1-distill-32b · 1.4s · 14:01:24`
 *
 *   Every fragment is independently optional — if `provider` is missing
 *   we drop `· via DeepInfra`; if `latency_ms` is null AND we are
 *   streaming we substitute `· streaming…`. If the strip would be
 *   empty after applying all guards, the component returns `null` so
 *   the meta row collapses to zero height (no blank line).
 *
 *   The `is_fallback` flag from acceptance gate #13 renders a `· ↻ fallback`
 *   chip in the warning colour so the analyst sees that the answer came
 *   from a degraded retrieval path.
 *
 * DATA SOURCE: pure prop — composed by MessageTurn from Message + the
 *   transient StreamingMessage intent (the only intent source today).
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5 (meta strip) and
 *   §6 (9px terminal text scale).
 */

"use client";
// WHY "use client": pure render but co-located inside the client-tree
// MessageTurn. Marking it client-side keeps the file in the same boundary
// and prevents an accidental Server-Component import.

import { cn } from "@/lib/utils";
import { safeFormatClockTime } from "@/lib/utils";

interface MessageMetaStripProps {
  /** Role of the parent turn. User turns currently render `null`. */
  readonly role: "user" | "assistant";
  /** Intent label from streaming metadata SSE event. */
  readonly intent?: string | null;
  /** LLM provider id (e.g. "DeepInfra", "OpenRouter"). */
  readonly provider?: string | null;
  /** Model id (e.g. "deepseek-r1-distill-qwen-32b"). */
  readonly model?: string | null;
  /** End-to-end latency in milliseconds. `null` while streaming. */
  readonly latencyMs?: number | null;
  /** Created-at timestamp for the clock-time fragment. */
  readonly createdAt?: string | Date | null;
  /** True when the message is a fallback (acceptance gate #13). */
  readonly isFallback?: boolean;
  /** True for the in-flight streaming turn (controls "streaming…" fragment). */
  readonly isStreaming?: boolean;
}

/**
 * formatLatency — renders milliseconds in the densest representation that
 * still reads as a single token. Sub-second values stay in ms; ≥1s
 * promote to seconds with 1 decimal (per spec).
 */
function formatLatency(latencyMs: number): string {
  if (latencyMs < 1000) return `${latencyMs.toFixed(0)}ms`;
  const seconds = latencyMs / 1000;
  return `${seconds.toFixed(1)}s`;
}

/**
 * MessageMetaStrip — see file header.
 *
 * Fragment-by-fragment logic:
 *   1. intent          → uppercase (matches design doc style); skipped if absent
 *   2. provider        → "via {provider}" prefix
 *   3. model           → bare token; tabular-nums so two stacked turns align
 *   4. latency / stream → `{N}ms` / `{N.N}s` / `streaming…`
 *   5. clock time      → mono via safeFormatClockTime
 *   6. fallback chip   → `↻ fallback` in warning colour (no leading `·`)
 *
 *   Each fragment is joined with `·` SEPARATORS rendered as `<span>`s so
 *   we can omit absent fragments without leaving stray dots.
 *
 * EMPTY-GUARD: if every fragment is absent (user turn, no createdAt) the
 *   component returns `null`.
 */
export function MessageMetaStrip({
  role,
  intent,
  provider,
  model,
  latencyMs,
  createdAt,
  isFallback,
  isStreaming,
}: MessageMetaStripProps) {
  // User turns currently have no metadata to show. We return null so the
  // grid row collapses to nothing visible (the timestamp lives in the
  // gutter, not here).
  if (role === "user") return null;

  // Collect renderable fragments in display order. Each entry is the JSX
  // for the fragment value (without separators). We add separators at
  // render time so adjacent absent fragments don't produce double dots.
  const fragments: React.ReactNode[] = [];

  if (intent && intent.length > 0) {
    fragments.push(
      <span key="intent" className="uppercase text-foreground">
        {intent}
      </span>,
    );
  }

  if (provider && provider.length > 0) {
    fragments.push(
      <span key="provider">
        via <span className="text-foreground">{provider}</span>
      </span>,
    );
  }

  if (model && model.length > 0) {
    fragments.push(
      <span key="model" className="tabular-nums text-foreground">
        {model}
      </span>,
    );
  }

  // Latency vs streaming label. If we have a latency value we always show
  // it (covers history-reloaded turns). If we don't AND we are streaming,
  // we show "streaming…" so the analyst sees the turn is still active.
  if (latencyMs !== null && latencyMs !== undefined && !Number.isNaN(latencyMs)) {
    fragments.push(
      <span key="latency" className="tabular-nums text-foreground">
        {formatLatency(latencyMs)}
      </span>,
    );
  } else if (isStreaming) {
    fragments.push(
      <span key="streaming" className="italic text-muted-foreground">
        streaming…
      </span>,
    );
  }

  // Clock time fragment. safeFormatClockTime returns "—" on invalid input,
  // which still reads cleanly as a fragment — better than dropping the
  // anchor entirely (the analyst still wants to see SOME stamp).
  if (createdAt) {
    const iso = createdAt instanceof Date ? createdAt.toISOString() : createdAt;
    fragments.push(
      <span key="clock" className="tabular-nums">
        {safeFormatClockTime(iso)}
      </span>,
    );
  }

  // Fallback chip. We append it last so the visual signal is the last
  // thing the eye reads, which matches the analyst's "answer first, then
  // qualifier" reading pattern. We render it WITHOUT a leading `·` so
  // the chip looks like a tag, not a fragment.
  // WHY a separate spacer span: keeps the chip from butting against the
  // last fragment when both are present.
  const showFallback = isFallback === true;

  if (fragments.length === 0 && !showFallback) return null;

  return (
    <div
      // WHY data-cell on the strip wrapper (not on every fragment): the
      // density gate counts each strip once (the design recount lands
      // 103 cells without double-counting fragments). A single
      // data-cell per strip is fair.
      data-cell
      data-meta-strip
      // Tier-1 muted text colour; we lift individual values to
      // text-foreground (above) so they pop above the muted separators.
      className={cn(
        "flex items-center gap-1 text-[9px] font-mono leading-tight",
        "text-muted-foreground",
      )}
      aria-label="Message metadata"
    >
      {fragments.map((fragment, idx) => (
        // We render each fragment with a leading `·` separator EXCEPT for
        // the first one. The fragment array is already filtered down to
        // present values, so this guarantees no orphan dots.
        <span key={idx} className="flex items-center gap-1">
          {idx > 0 ? <span aria-hidden="true">·</span> : null}
          {fragment}
        </span>
      ))}
      {showFallback ? (
        <span
          className={cn(
            // Warning palette token — never introduce a new colour for
            // this chip. The ↻ glyph plus the "fallback" label reads
            // unambiguously even without colour.
            "ml-1 text-warning",
          )}
          title="This answer used a fallback retrieval path"
        >
          {/* WHY a leading `·` when other fragments are present: keeps
              visual rhythm consistent with the rest of the strip. When
              the strip is fallback-only (no fragments) we drop the dot
              for the same reason as the orphan-dot guard above. */}
          {fragments.length > 0 ? <span aria-hidden="true">· </span> : null}
          ↻ fallback
        </span>
      ) : null}
    </div>
  );
}
