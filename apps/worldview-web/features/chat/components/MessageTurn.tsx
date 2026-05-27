/**
 * features/chat/components/MessageTurn.tsx — Flat one-turn renderer.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block B, T-07):
 *   Replaces the legacy `MessageBubble` rounded-shell renderer. Bloomberg /
 *   Refinitiv / Perplexity Finance chat surfaces render each turn FLAT
 *   against the column edge — no avatar bubble, no max-width container,
 *   no rounded corners. The visual language is "terminal log entry" rather
 *   than "chat conversation". The role gutter (single character `U` or
 *   `A`) anchors the eye and an accent rail (`border-l-2 border-primary/50`)
 *   appears on the gutter only WHILE the assistant turn is streaming, so
 *   the analyst's eye locks onto the in-flight cell at a glance.
 *
 *   This component composes every Wave K turn surface in one place:
 *     - role gutter + timestamp + MessageMetaStrip (T-09)
 *     - markdown body via LazyMarkdownContent (citation-anchor markers
 *       come through Block G T-20; we pass the existing `withCitationSups`
 *       prop in the meantime so superscripts render — same visual fix)
 *     - ToolCallTray (T-08) when tool_calls.length > 0
 *     - CitationStrip when citations.length > 0
 *     - ContradictionStrip when contradictions.length > 0
 *     - FollowUpChips when role=assistant AND >=1 citation
 *
 *   MessageBubble is NOT deleted in this commit (per Wave K Block I T-22).
 *
 * FOLLOW-UP DERIVATION:
 *   The spec leaves the chip-text derivation to "simple lookup tables".
 *   We seed off the optional `intent` prop (REASONING / RETRIEVAL / WRITE
 *   / SUMMARY / UNKNOWN). If no intent is supplied (legacy turn, or Q-9
 *   not landed) we render a generic three-question fallback so the
 *   acceptance gate ("chips appear under every assistant turn with >=1
 *   citation") still passes. The derivation lives in `deriveFollowUps`
 *   below — keeping it inside MessageTurn (not a shared helper) makes
 *   the heuristic visible at the call site and trivial to evolve.
 *
 * ACCENT RAIL CHOICE:
 *   We hand-roll a 2px primary-coloured left border on the gutter rather
 *   than reusing the `<AiContentRail>` primitive. AiContentRail uses
 *   `--accent-ai` (violet) as its visual signal that "this content is
 *   AI-generated"; the streaming accent rail is a different signal —
 *   "this turn is mid-flight" — and the Wave K design spec calls for
 *   `border-primary/50` (terminal-yellow at 50% alpha), not the AI accent
 *   colour. Mixing the two would dilute both signals.
 *
 * DATA SOURCE: pure prop forwarding from ChatMessageList. No fetch.
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5 (flat turn) +
 *   §6.4 (24 / 18 / 16 px row heights).
 */

"use client";
// WHY "use client": owns no state itself, but children (ToolCallTray,
// CitationStrip's HoverCard, FollowUpChips) all use client-only DOM
// listeners. Declaring it here keeps the component in the client tree
// boundary and prevents an accidental Server-Component import.

import { LazyMarkdownContent } from "@/features/chat/components/LazyMarkdownContent";
import { CitationStrip } from "@/features/chat/components/CitationStrip";
import { ContradictionStrip } from "@/features/chat/components/ContradictionStrip";
import { FollowUpChips } from "@/features/chat/components/FollowUpChips";
import { MessageMetaStrip } from "@/features/chat/components/MessageMetaStrip";
import { ToolCallTray } from "@/features/chat/components/ToolCallTray";
import { safeFormatClockTime } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { Message, CitationV2 } from "@/types/api";
import type { ToolCallState } from "@/features/chat/components/ToolCallIndicator";

interface MessageTurnProps {
  /**
   * The conversation turn to render. Both user and assistant turns flow
   * through this renderer; the role gutter glyph + the meta strip choose
   * different content based on `turn.role`.
   */
  readonly turn: Message;
  /**
   * True only for the synthetic in-flight assistant turn rendered at the
   * tail of `ChatMessageList`. Drives the accent rail and the streaming
   * label inside MessageMetaStrip.
   */
  readonly isStreaming?: boolean;
  /**
   * Visual density. `'compact'` shrinks the gutter + meta strip by ~1px;
   * used by `AskAiPanel` so the floating panel feels lighter than the
   * full `/chat` surface. Default is `'default'` (the /chat sizing).
   */
  readonly size?: "default" | "compact";
  /**
   * Click handler for follow-up chips. When unset the chips simply do not
   * render (we don't want dead-link affordances).
   */
  readonly onFollowUp?: (suggestion: string) => void;
  /**
   * In-flight tool-call entries from `useChatStream.activeTools`. Only
   * forwarded when `isStreaming` is true; for completed turns we read
   * `turn` directly (placeholder until S8 persists tool_calls on the
   * Message — see Q-11 deferred).
   */
  readonly activeTools?: ToolCallState[];
  /**
   * Streaming-only intent label. Sourced from `StreamingMessage.intent`
   * by ChatMessageList. Not on `Message` because the Q-9 wire shape did
   * not finalise it as a persisted field; passing it as a prop keeps the
   * type model accurate.
   */
  readonly intent?: string | null;
}

/**
 * deriveFollowUps — pick 2..4 follow-up suggestions based on optional
 * intent + the last citation title we have on the turn.
 *
 * WHY hard-coded tables (vs. backend-served suggestions): the wave-K
 * backend Q-11 (tool_data SSE event with suggested follow-ups) is
 * deferred. To still ship the chips we use a heuristic. The tables are
 * intentionally short — analysts ignore long suggestion strings — and
 * the design system bans chip text beyond ~30 chars per row.
 */
function deriveFollowUps(intent: string | null | undefined): string[] {
  // Default fallback used when no intent or unknown intent. Three generic
  // research questions that work for any topic the LLM just answered.
  const GENERIC = [
    "What's the risk here?",
    "Show me the evidence",
    "Compare to peers",
  ];
  if (!intent) return GENERIC;
  // Normalise the intent token. The backend emits e.g. "REASONING" or
  // "retrieval"; uppercasing centralises the lookup.
  const key = intent.toUpperCase();
  if (key === "REASONING")
    return [
      "What's the risk?",
      "Show me the evidence",
      "Counter-arguments?",
    ];
  if (key === "RETRIEVAL")
    return [
      "Summarise the sources",
      "Latest news on this",
      "Show contradictions",
    ];
  if (key === "WRITE")
    return ["Set an alert", "Add to watchlist"];
  if (key === "SUMMARY")
    return ["Drill into the numbers", "What changed last quarter?"];
  return GENERIC;
}

/**
 * adaptCitationsToV2 — bridge the legacy `Citation` array on `Message`
 * to the `CitationV2` shape that `CitationStrip` consumes.
 *
 * WHY here (not in the strip): the strip is V2-only by design (Block C
 * arch test enforces no legacy import). The bridge stays local to the
 * one consumer that still reads `Message.citations` (which is the
 * legacy persisted shape).
 *
 * Mapping rules:
 *   - `article_id` -> `id` (keeps polymorphic ids semantically valid)
 *   - `kind` defaults to `'article'` (the legacy shape was article-only)
 *   - `url` keeps its legacy value (was `string`; V2 expects `string | null`)
 *   - `relevance_score` passes through verbatim
 */
function adaptCitationsToV2(turn: Message): CitationV2[] {
  return turn.citations.map((c) => ({
    id: c.article_id,
    kind: "article" as const,
    title: c.title,
    source: c.source,
    url: c.url,
    relevance_score: c.relevance_score,
  }));
}

/**
 * MessageTurn — see file header.
 */
export function MessageTurn({
  turn,
  isStreaming = false,
  size = "default",
  onFollowUp,
  activeTools = [],
  intent,
}: MessageTurnProps) {
  const isAssistant = turn.role === "assistant";
  const isUser = turn.role === "user";
  // Single-character role glyph. Mono 11px keeps it readable but un-fussy.
  // We use `A` for assistant (vs. `B` for "bot") because Bloomberg-style
  // chat surfaces use `A` for "analyst response" — matches the design
  // doc's caption style.
  const glyph = isUser ? "U" : "A";

  // Bridge the legacy Citation shape to V2 for CitationStrip. The shipped
  // wire shape has not yet had `published_at` / `entity_name` filled in
  // by S8; CitationStrip gracefully omits those columns.
  const citationsV2 = adaptCitationsToV2(turn);

  // Follow-up chip strings — derived only for assistant turns with
  // citations (per acceptance gate #11).
  const followUps =
    isAssistant && citationsV2.length > 0 && onFollowUp
      ? deriveFollowUps(intent ?? null)
      : [];

  // Compact-vs-default sizing knobs. Compact trims the gutter from
  // w-7 -> w-6 and the body padding from py-1 -> py-0.5 (closer to the
  // 16px ToolCallTray row height) so AskAiPanel feels lighter.
  const gutterWidth = size === "compact" ? "w-6" : "w-7";
  const rowPadding = size === "compact" ? "py-0.5" : "py-1";

  return (
    // WHY data-cell on the root: the density-gate e2e (T-23) counts visible
    // [data-cell] elements above the fold. Each turn contributes its own
    // cell plus the cells declared by inner strips. Stable selector beats
    // tag-name targeting.
    <div
      data-cell
      data-message-turn={turn.message_id}
      data-message-role={turn.role}
      // grid-cols [gutter | body] — fixed width gutter, body takes the rest.
      // gap-2 reads as 8px between gutter and body; matches the 18px tool /
      // citation row internal spacing.
      className={cn(
        "grid w-full gap-2 border-b border-border/40",
        // The gutter is the only column that gets a left rail when streaming.
        // We do the rail on the gutter (not the whole row) so the citation
        // strip + meta strip below visually align with the body, not the
        // rail.
      )}
      style={{ gridTemplateColumns: `var(--gutter, 28px) 1fr` }}
    >
      {/* ── Role gutter ─────────────────────────────────────────────── */}
      {/* WHY a flex column: glyph at top, timestamp directly below.
          Vertically aligned to the first line of body content via flex
          start. mono+9px timestamp matches the rest of the meta strip. */}
      <div
        className={cn(
          // The accent rail. We use border-l-2 border-primary/50 ONLY when
          // streaming so the rail is a definitive "in-flight" marker. The
          // rail sits to the LEFT of the gutter content so the glyph itself
          // stays neutral.
          "flex flex-col items-center justify-start gap-1 pr-1 pt-1",
          gutterWidth,
          isStreaming && isAssistant
            ? "border-l-2 border-primary/50"
            : "border-l-2 border-transparent",
        )}
      >
        <span
          // The role glyph. font-mono 11px; muted for user so the eye
          // pre-attentively groups assistant turns as the primary read.
          className={cn(
            "font-mono text-[11px] tabular-nums",
            isAssistant ? "text-primary" : "text-muted-foreground",
          )}
          aria-label={isAssistant ? "Assistant" : "User"}
        >
          {glyph}
        </span>
        <span
          className="font-mono text-[9px] text-muted-foreground tabular-nums"
          // The same safeFormatClockTime helper used by SlashTurnBlock and
          // the legacy bubble — guards against "Invalid Date" for
          // optimistic messages whose created_at has not yet been
          // server-stamped.
          title={turn.created_at ?? undefined}
        >
          {safeFormatClockTime(turn.created_at)}
        </span>
      </div>

      {/* ── Body column ─────────────────────────────────────────────── */}
      <div className={cn("flex min-w-0 flex-col gap-1", rowPadding)}>
        {/* MessageMetaStrip — renders intent / provider / model / latency.
            For user turns the strip returns null itself (no fields to
            show), so we always include it and let the component decide. */}
        <MessageMetaStrip
          role={turn.role}
          intent={intent ?? null}
          provider={turn.provider ?? null}
          model={turn.model ?? null}
          latencyMs={turn.latency_ms ?? null}
          createdAt={turn.created_at}
          isFallback={turn.is_fallback === true}
          isStreaming={isStreaming}
        />

        {/* Body content.
            User turns: <pre> preserves literal whitespace (a user pasting
            a bulleted list keeps it intact). Markdown rendering on user
            input would mangle "*" wildcards and similar.
            Assistant turns: LazyMarkdownContent in compact density. The
            `withCitationSups` prop renders [N] -> <sup>N</sup> so inline
            anchors visually tie back to the citation strip. Block G T-20
            will swap this for the `withInlineCitationAnchors` prop +
            `<InlineCitationAnchor>` primitive — until then we keep the
            existing sup-rendering as-is so there is no regression. */}
        <div
          data-cell
          className="text-[11px] leading-[1.5] text-foreground"
        >
          {isUser ? (
            <pre className="whitespace-pre-wrap font-sans text-[11px]">
              {turn.content}
            </pre>
          ) : (
            <LazyMarkdownContent size="compact" withCitationSups>
              {turn.content}
            </LazyMarkdownContent>
          )}
        </div>

        {/* ToolCallTray — only when there are tools to show. For finished
            turns S8 will eventually persist `tool_calls` on Message
            (Q-11 deferred); until then activeTools (streaming) is the
            only source. The tray itself renders null on empty input. */}
        {activeTools.length > 0 ? (
          <ToolCallTray tools={activeTools} />
        ) : null}

        {/* CitationStrip — full-width strip; the strip already returns
            null on empty input. */}
        <CitationStrip citations={citationsV2} />

        {/* ContradictionStrip — only assistant turns produce these. */}
        {isAssistant && turn.contradictions && turn.contradictions.length > 0 ? (
          <ContradictionStrip contradictions={turn.contradictions} />
        ) : null}

        {/* FollowUpChips — only when we have an onFollowUp callback AND
            >=1 citation. The chips component itself enforces the >=2
            chip minimum (it returns null below MIN_CHIPS=2). */}
        {followUps.length > 0 && onFollowUp ? (
          <FollowUpChips suggestions={followUps} onPick={onFollowUp} />
        ) : null}
      </div>
    </div>
  );
}
